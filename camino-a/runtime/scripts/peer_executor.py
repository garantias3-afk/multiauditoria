#!/usr/bin/env python3
"""Closed-surface SSH peer executor for the two-Mac Camino topology.

Security properties:

* SSH is non-interactive (BatchMode) with strict host-key checking.
* Host, identity path, remote root and Python executable come from the portable
  host-runtime policy/environment and are validated before use.
* The local process always uses argv lists with ``shell=False``.  The one command
  string required by the SSH protocol is produced exclusively by
  ``shlex.join`` from allowlisted executable/argument vectors.
* Only explicitly allowlisted workers can run. No raw command or arbitrary worker argument
  is accepted.
* Non-LM workers receive a fresh, isolated copy of the run snapshot and their
  lane job.  Secret-looking files are not transferred.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.host_runtime import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    detect_host,
    load_policy,
    resolve_peer_settings,
)
from scripts.candidate_updates import candidate_source  # noqa: E402


ProcessRunner = Callable[..., Any]

ALLOWED_WORKERS: Dict[str, Dict[str, str]] = {
    "worker_lmstudio": {"script": "worker_lmstudio.py", "lane": "lmstudio_bridge"},
    "worker_local_static": {"script": "worker_local_static.py", "lane": "local_static"},
    "worker_gateway": {"script": "worker_gateway.py", "lane": "gateway"},
    "worker_codex": {"script": "worker_codex.py", "lane": "codex"},
    "worker_claude_code": {"script": "worker_claude_code.py", "lane": "claude_code"},
    "worker_codex_fallback": {"script": "worker_codex_fallback.py", "lane": "codex_fallback"},
}

HOST_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9][A-Za-z0-9._-]*$")
EXECUTABLE_RE = re.compile(r"^(?:/[A-Za-z0-9._/-]+|[A-Za-z0-9._-]+)$")
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_RUN_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")

FORBIDDEN_SNAPSHOT_NAMES = {
    ".env", ".netrc", "id_rsa", "id_ed25519", "credentials", "credentials.json",
}
FORBIDDEN_SNAPSHOT_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".mobileprovision"}
SECRET_BYTES_PATTERNS = (
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(rb"ghp_[0-9A-Za-z]{20,}"),
    re.compile(rb"-----BEGIN[ A-Z]*(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class PeerExecutionError(RuntimeError):
    pass


def _safe_remote_root(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or raw.startswith("~") or ".." in path.parts:
        raise PeerExecutionError("unsafe_remote_root")
    if any(not SAFE_SEGMENT_RE.fullmatch(part) for part in path.parts):
        raise PeerExecutionError("unsafe_remote_root_segment")
    if len(raw) > 180:
        raise PeerExecutionError("remote_root_too_long")
    return str(path)


def _safe_host(value: str) -> str:
    host = str(value or "").strip()
    if not HOST_RE.fullmatch(host) or host.startswith("-"):
        raise PeerExecutionError("unsafe_or_missing_ssh_host")
    return host


def _safe_executable(value: str, field: str) -> str:
    executable = str(value or "").strip()
    if not EXECUTABLE_RE.fullmatch(executable) or ".." in PurePosixPath(executable).parts:
        raise PeerExecutionError("unsafe_%s" % field)
    return executable


def _sanitized_subprocess_env(environ: Mapping[str, str]) -> Dict[str, str]:
    allowed = {
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
        "SSH_AUTH_SOCK", "TMPDIR",
    }
    return {key: value for key, value in environ.items() if key in allowed}


def _result_dict(result: Any) -> Dict[str, Any]:
    return {
        "returncode": int(getattr(result, "returncode", 1)),
        "stdout": str(getattr(result, "stdout", "") or ""),
        "stderr": str(getattr(result, "stderr", "") or ""),
    }


class PeerExecutor:
    def __init__(
        self,
        policy: Optional[Mapping[str, Any]] = None,
        peer_settings: Optional[Mapping[str, Any]] = None,
        root: Path = ROOT,
        environ: Optional[Mapping[str, str]] = None,
        process_runner: ProcessRunner = subprocess.run,
    ) -> None:
        self.policy = dict(policy or load_policy())
        self.root = Path(root).resolve()
        self.environ = dict(os.environ if environ is None else environ)
        self.process_runner = process_runner
        if peer_settings is None:
            host = detect_host(self.policy, self.environ)
            peer_settings = resolve_peer_settings(self.policy, self.environ, str(host.get("role") or ""))
        self.peer = dict(peer_settings)
        self.peer_cfg = dict(self.policy.get("peer", {}))
        self.host = _safe_host(str(self.peer.get("ssh_host") or ""))
        self.remote_root = _safe_remote_root(str(self.peer.get("remote_root") or self.peer_cfg.get("remote_root_default", ".camino/peer-runtime")))
        self.remote_python = _safe_executable(str(self.peer.get("python") or self.peer_cfg.get("python_default", "python3")), "remote_python")
        self.connect_timeout = max(1, int(self.peer.get("connect_timeout_seconds") or self.peer_cfg.get("connect_timeout_seconds", 5)))
        self.command_timeout = max(5, int(self.peer.get("command_timeout_seconds") or self.peer_cfg.get("command_timeout_seconds", 900)))
        identity = str(self.peer.get("ssh_identity_file") or "").strip()
        self.identity_file = Path(identity).expanduser().resolve() if identity else None
        self._validate_identity()

    def _validate_identity(self) -> None:
        if self.identity_file is None:
            return
        if not self.identity_file.is_file() or self.identity_file.is_symlink():
            raise PeerExecutionError("ssh_identity_missing_or_symlink")
        mode = stat.S_IMODE(self.identity_file.stat().st_mode)
        if mode & 0o077:
            raise PeerExecutionError("ssh_identity_permissions_too_open")

    def _ssh_options(self) -> List[str]:
        values = [
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=%s" % self.connect_timeout,
        ]
        if self.identity_file:
            values.extend(["-o", "IdentitiesOnly=yes", "-i", str(self.identity_file)])
        return values

    def _run_process(self, argv: Sequence[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        try:
            completed = self.process_runner(
                list(argv),
                capture_output=True,
                text=True,
                timeout=int(timeout or self.command_timeout),
                check=False,
                shell=False,
                env=_sanitized_subprocess_env(self.environ),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "returncode": 124,
                "stdout": str(exc.stdout or ""),
                "stderr": "timeout",
            }
        except OSError as exc:
            return {"returncode": 127, "stdout": "", "stderr": "%s:%s" % (type(exc).__name__, exc)}
        return _result_dict(completed)

    def _ssh(self, remote_argv: Sequence[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        command = shlex.join([str(value) for value in remote_argv])
        argv = ["/usr/bin/ssh", *self._ssh_options(), self.host, command]
        result = self._run_process(argv, timeout)
        result["argv"] = argv
        result["remote_argv"] = list(remote_argv)
        return result

    def _scp_to(self, local_path: Path, remote_relative: str) -> Dict[str, Any]:
        remote = str(PurePosixPath(remote_relative))
        _safe_remote_root(remote)
        argv = [
            "/usr/bin/scp", "-q", *self._ssh_options(),
            str(local_path.resolve()), "%s:%s" % (self.host, remote),
        ]
        result = self._run_process(argv)
        result["argv"] = argv
        return result

    def _scp_from_dir(self, remote_relative: str, local_dir: Path) -> Dict[str, Any]:
        remote = str(PurePosixPath(remote_relative))
        _safe_remote_root(remote)
        local_dir.mkdir(parents=True, exist_ok=True)
        argv = [
            "/usr/bin/scp", "-q", "-r", *self._ssh_options(),
            "%s:%s/." % (self.host, remote), str(local_dir.resolve()),
        ]
        result = self._run_process(argv)
        result["argv"] = argv
        return result

    def probe(self) -> Dict[str, Any]:
        result = self._ssh(["/usr/bin/true"], timeout=self.connect_timeout + 2)
        return {
            "status": "ok" if result["returncode"] == 0 else "unavailable",
            "returncode": result["returncode"],
            "stderr": result["stderr"][-1000:],
            "host": self.host,
            "batch_mode": True,
            "strict_host_key_checking": True,
            "argv": result["argv"],
        }

    def _script_dependency_closure(self, entry_name: str) -> List[Path]:
        scripts_dir = self.root / "scripts"
        entry = scripts_dir / entry_name
        if not entry.is_file() or entry.is_symlink():
            raise PeerExecutionError("worker_script_missing:%s" % entry_name)
        queue = [entry]
        seen: Set[Path] = set()
        while queue:
            path = queue.pop()
            path = path.resolve()
            if path in seen:
                continue
            try:
                path.relative_to(scripts_dir.resolve())
            except ValueError:
                raise PeerExecutionError("script_dependency_outside_scripts")
            seen.add(path)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as exc:
                raise PeerExecutionError("cannot_parse_script_dependency:%s:%s" % (path.name, exc))
            modules: Set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = str(node.module or "")
                    if module == "scripts":
                        modules.update("scripts.%s" % alias.name for alias in node.names)
                    elif module.startswith("scripts."):
                        modules.add(module)
                elif isinstance(node, ast.Import):
                    modules.update(alias.name for alias in node.names if alias.name.startswith("scripts."))
            for module in modules:
                rel = module.split(".")[1:]
                candidate = scripts_dir.joinpath(*rel).with_suffix(".py")
                if candidate.is_file() and candidate.resolve() not in seen:
                    queue.append(candidate)
        init_file = scripts_dir / "__init__.py"
        if init_file.is_file():
            seen.add(init_file.resolve())
        return sorted(seen)

    def bootstrap_files(self, worker: str) -> List[Path]:
        if worker not in ALLOWED_WORKERS:
            raise PeerExecutionError("worker_not_allowed")
        files: Set[Path] = set(self._script_dependency_closure(ALLOWED_WORKERS[worker]["script"]))
        if worker == "worker_lmstudio":
            required = [
                self.root / "config" / "host_runtime.policy.json",
                self.root / "canon" / "CANON_PROVIDER_MODEL_ROUTES.v1.json",
            ]
        else:
            required = []
            for directory_name in ("config", "canon"):
                directory = self.root / directory_name
                required.extend(
                    path for path in directory.iterdir()
                    if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".json", ".md"}
                )
            generated_by_worker = {
                "worker_codex": self.root / "generated" / "AGENTS.md",
                "worker_codex_fallback": self.root / "generated" / "AGENTS.md",
                "worker_claude_code": self.root / "generated" / "CLAUDE.md",
            }
            generated = generated_by_worker.get(worker)
            if generated is not None:
                required.append(generated)
        files.update(path.resolve() for path in required if path.is_file() and not path.is_symlink())
        max_bytes = int(self.peer_cfg.get("bootstrap_max_file_bytes", 10 * 1024 * 1024))
        result = []
        for path in sorted(files):
            try:
                path.relative_to(self.root)
            except ValueError:
                raise PeerExecutionError("bootstrap_file_outside_root")
            if path.stat().st_size > max_bytes:
                raise PeerExecutionError("bootstrap_file_too_large:%s" % path.name)
            result.append(path)
        return result

    def _transfer_files(self, files: Iterable[Path], remote_base: str) -> Dict[str, Any]:
        pairs: List[Tuple[Path, str]] = []
        directories: Set[str] = set()
        for local in files:
            relative = local.resolve().relative_to(self.root)
            remote = str(PurePosixPath(remote_base).joinpath(*relative.parts))
            _safe_remote_root(remote)
            pairs.append((local, remote))
            directories.add(str(PurePosixPath(remote).parent))
        mkdir = self._ssh(["/bin/mkdir", "-p", *sorted(directories)])
        if mkdir["returncode"] != 0:
            raise PeerExecutionError("remote_mkdir_failed:%s" % mkdir["stderr"][-300:])
        transferred = []
        for local, remote in pairs:
            result = self._scp_to(local, remote)
            if result["returncode"] != 0:
                raise PeerExecutionError("bootstrap_transfer_failed:%s:%s" % (local.name, result["stderr"][-300:]))
            transferred.append(str(local.relative_to(self.root)))
        return {"files": transferred, "count": len(transferred)}

    def bootstrap(self, worker: str, remote_base: Optional[str] = None) -> Dict[str, Any]:
        files = self.bootstrap_files(worker)
        base = _safe_remote_root(remote_base or self.remote_root)
        transferred = self._transfer_files(files, base)
        return {
            "status": "ok",
            "worker": worker,
            "remote_root": base,
            "transferred": transferred,
        }

    @staticmethod
    def _contains_secret(path: Path) -> bool:
        try:
            sample = path.read_bytes()
        except OSError:
            return True
        return any(pattern.search(sample) for pattern in SECRET_BYTES_PATTERNS)

    def _snapshot_files(self, run_dir: Path, lane: str) -> Tuple[List[Path], List[str]]:
        required = [
            run_dir / "cycle_state.json",
            run_dir / "RUN_CONFIG.json",
            run_dir / "13_WORKER_BUS" / lane / "IN" / "job.json",
        ]
        job_path = required[-1]
        if not job_path.is_file() or job_path.is_symlink():
            raise PeerExecutionError("worker_job_missing:%s" % lane)
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PeerExecutionError("worker_job_invalid:%s" % exc)
        secret_keys = {"api_key", "token", "password", "secret", "authorization"}

        def contains_secret_key(value: Any) -> bool:
            if isinstance(value, dict):
                return any(
                    str(key).lower() in secret_keys or contains_secret_key(child)
                    for key, child in value.items()
                )
            if isinstance(value, list):
                return any(contains_secret_key(child) for child in value)
            return False

        if contains_secret_key(job):
            raise PeerExecutionError("worker_job_contains_forbidden_secret_field")

        # Slot-scoped LM Studio jobs carry a bounded prompt/context pack under
        # the run directory.  Transfer that exact file as part of the isolated
        # snapshot; otherwise the remote worker would receive a valid job whose
        # prompt_file points to a path that was never staged.
        prompt_file = str(job.get("prompt_file") or "").strip()
        if prompt_file:
            prompt_path = Path(prompt_file).expanduser()
            prompt_path = prompt_path.resolve() if prompt_path.is_absolute() else (run_dir / prompt_path).resolve()
            try:
                prompt_path.relative_to(run_dir)
            except ValueError:
                raise PeerExecutionError("worker_prompt_file_outside_run")
            if not prompt_path.is_file() or prompt_path.is_symlink():
                raise PeerExecutionError("worker_prompt_file_missing_or_symlink")
            required.append(prompt_path)

        snapshot = candidate_source(run_dir)
        if not snapshot.is_dir():
            raise PeerExecutionError("target_snapshot_missing")
        max_files = int(self.peer_cfg.get("snapshot_max_files", 20000))
        max_bytes = int(self.peer_cfg.get("snapshot_max_file_bytes", 50 * 1024 * 1024))
        selected: List[Path] = [path for path in required if path.is_file() and not path.is_symlink()]
        skipped: List[str] = []
        for path in sorted(snapshot.rglob("*")):
            if path.is_symlink():
                skipped.append(str(path.relative_to(snapshot)) + ":symlink")
                continue
            if not path.is_file():
                continue
            rel = path.relative_to(snapshot)
            if any(part in {".git", ".ssh", "__pycache__"} for part in rel.parts):
                skipped.append(str(rel) + ":forbidden_directory")
                continue
            if path.name.lower() in FORBIDDEN_SNAPSHOT_NAMES or path.suffix.lower() in FORBIDDEN_SNAPSHOT_SUFFIXES:
                skipped.append(str(rel) + ":secret_filename")
                continue
            if path.stat().st_size > max_bytes:
                skipped.append(str(rel) + ":too_large")
                continue
            if self._contains_secret(path):
                skipped.append(str(rel) + ":secret_pattern")
                continue
            selected.append(path)
            if len(selected) > max_files:
                raise PeerExecutionError("snapshot_file_limit_exceeded")
        if skipped:
            # A peer result may bind to the original candidate hash only when
            # the peer receives the complete candidate. Silent filtering would
            # turn a partial snapshot into falsely current evidence.
            raise PeerExecutionError(
                "snapshot_incomplete:" + ",".join(skipped[:10])
            )
        return selected, skipped

    def _stage_isolated_run(
        self, worker: str, run_dir: Path, remote_base: Optional[str] = None,
    ) -> Dict[str, Any]:
        lane = ALLOWED_WORKERS[worker]["lane"]
        files, skipped = self._snapshot_files(run_dir, lane)
        safe_run = SAFE_RUN_ID_RE.sub("_", run_dir.name).strip("._-") or "run"
        base = _safe_remote_root(remote_base or self.remote_root)
        remote_run = str(PurePosixPath(base) / "runs" / (safe_run + "_" + uuid.uuid4().hex[:12]))
        pairs: List[Tuple[Path, str]] = []
        directories: Set[str] = set()
        for local in files:
            relative = local.relative_to(run_dir)
            remote = str(PurePosixPath(remote_run).joinpath(*relative.parts))
            _safe_remote_root(remote)
            pairs.append((local, remote))
            directories.add(str(PurePosixPath(remote).parent))
        directories.add(str(PurePosixPath(remote_run) / "13_WORKER_BUS" / lane / "OUT"))
        directories.add(str(PurePosixPath(remote_run) / "REPORTS" / "lmstudio_attempts"))
        mkdir = self._ssh(["/bin/mkdir", "-p", *sorted(directories)])
        if mkdir["returncode"] != 0:
            raise PeerExecutionError("remote_run_mkdir_failed:%s" % mkdir["stderr"][-300:])
        for local, remote in pairs:
            result = self._scp_to(local, remote)
            if result["returncode"] != 0:
                raise PeerExecutionError("snapshot_transfer_failed:%s:%s" % (local.name, result["stderr"][-300:]))
        return {
            "remote_run": remote_run,
            "transferred_count": len(pairs),
            "skipped": skipped,
            "lane": lane,
        }

    def execute(self, worker: str, run_dir: Path) -> Dict[str, Any]:
        if worker not in ALLOWED_WORKERS:
            raise PeerExecutionError("worker_not_allowed")
        local_run = Path(run_dir).expanduser().resolve()
        if not local_run.is_dir():
            raise PeerExecutionError("run_dir_not_found")
        probe = self.probe()
        if probe["status"] != "ok":
            return {"status": "peer_unavailable", "worker": worker, "probe": probe}
        execution_root = str(
            PurePosixPath(self.remote_root) / "executions" / uuid.uuid4().hex
        )
        bootstrap = self.bootstrap(worker, execution_root)
        staged = self._stage_isolated_run(worker, local_run, execution_root)
        script = str(PurePosixPath(execution_root) / "scripts" / ALLOWED_WORKERS[worker]["script"])
        # Fresh per-execution source root plus -B prevents persistent/stale
        # bytecode from an earlier peer bootstrap from being imported.
        remote_argv = [self.remote_python, "-B", script, "--run", staged["remote_run"]]
        command = self._ssh(remote_argv, timeout=self.command_timeout)

        lane = staged["lane"]
        local_out = local_run / "13_WORKER_BUS" / lane / "OUT"
        fetched = self._scp_from_dir(
            str(PurePosixPath(staged["remote_run"]) / "13_WORKER_BUS" / lane / "OUT"),
            local_out,
        )
        attempt_fetch = None
        if worker == "worker_lmstudio" and (
            fetched["returncode"] != 0 or command["returncode"] != 0
        ):
            attempt_fetch = self._scp_from_dir(
                str(PurePosixPath(staged["remote_run"]) / "REPORTS" / "lmstudio_attempts"),
                local_run / "REPORTS" / "lmstudio_attempts",
            )
        if command["returncode"] == 0 and fetched["returncode"] == 0:
            status = "ok"
        elif command["returncode"] != 0:
            status = "worker_failed"
        else:
            status = "result_fetch_failed"
        return {
            "status": status,
            "worker": worker,
            "host": self.host,
            "probe": probe,
            "bootstrap": bootstrap,
            "staged_run": staged,
            "remote_command": {
                "argv": remote_argv,
                "returncode": command["returncode"],
                "stdout_tail": command["stdout"][-2000:],
                "stderr_tail": command["stderr"][-2000:],
            },
            "fetch": {"returncode": fetched["returncode"], "stderr_tail": fetched["stderr"][-1000:]},
            "attempt_fetch": (
                {"returncode": attempt_fetch["returncode"], "stderr_tail": attempt_fetch["stderr"][-1000:]}
                if attempt_fetch is not None else None
            ),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute one allowlisted Camino worker on a configured SSH peer")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--worker", choices=sorted(ALLOWED_WORKERS), default="")
    parser.add_argument("--run", default="")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--bootstrap-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        executor = PeerExecutor(load_policy(Path(args.policy)))
        if args.probe_only:
            result = executor.probe()
        elif args.bootstrap_only:
            if not args.worker:
                raise PeerExecutionError("worker_required_for_bootstrap")
            probe = executor.probe()
            result = executor.bootstrap(args.worker) if probe["status"] == "ok" else {"status": "peer_unavailable", "probe": probe}
        else:
            if not args.worker or not args.run:
                raise PeerExecutionError("worker_and_run_required")
            result = executor.execute(args.worker, Path(args.run))
    except PeerExecutionError as exc:
        result = {"status": "configuration_error", "error": str(exc)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Peer executor: %s" % result.get("status"))
        if result.get("error"):
            print("Error: %s" % result["error"])
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
