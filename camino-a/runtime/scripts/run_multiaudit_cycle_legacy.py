#!/usr/bin/env python3
"""run_multiaudit_cycle_legacy.py — preserved v1.1 monolith (Drive/AUDIT_BUS GPT-primary flow).

This is the historical 3.8k-line orchestrator. As of v1.2 it is NO LONGER the
canonical entrypoint: `scripts/run_multiaudit_cycle.py` became a thin canonical
entrypoint that delegates to canon_loader + slot_runtime + internal_loop_runner
+ overnight_master + package_final.

This file is kept for two reasons:
  1. It is the single source of truth for policy-free plumbing helpers
     (utc_now, sha256_file, load_state/save_state, run, _sanitized_env, the
     worker-bus manifest/DONE writer, secret redaction, watcher locks, etc.).
     The new entrypoint re-exports those from here so the rest of the runtime
     keeps importing `from scripts.run_multiaudit_cycle import <helper>`.
  2. Its legacy GPT-web manual flow (`--input --candidate-name --target-version`,
     `--watch-gpt-output`, `--resume`, ...) is still reachable via
     `run_multiaudit_cycle.py --legacy ...` for anyone mid-run on the old path.

It intentionally still contains hardcoded historical slot aliases and manual
GPT-flow logic. New orchestration must NOT be added here; it goes through the
canon runtime modules.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import uuid
import re
import os
import signal
import plistlib
import unicodedata
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SALIDAS = ROOT / "salidas"
PRIMARY_BRAIN_ADAPTER = ROOT / "scripts" / "primary_brain_adapter.py"
PRIMARY_BRAIN_POLICY = ROOT / "config" / "primary_brain_policy.json"
DEFAULT_DRIVE_BUS = Path(os.environ.get("CAMINO_DRIVE_BUS_ROOT") or (ROOT / "CAMINO_RUNS"))
DEFAULT_MANUAL_FOLDER = Path(
    os.environ.get("CAMINO_MANUAL_AUDIT_ROOT") or (Path.home() / "CAMINO_A_AUDITORIAS_MANUALES")
)
DEFAULT_DESKTOP_MANUAL_FOLDER = Path(
    os.environ.get("CAMINO_MANUAL_INBOX_ROOT") or (Path.home() / "CAMINO_A_INGRESO_MANUAL")
)
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
STATE_NAME = "cycle_state.json"
MANUAL_REGISTRY_NAME = "MANUALES_RECIBIDAS.json"
MANUAL_INDEX_NAME = "AUDITORIAS_MANUALES_RECIBIDAS.md"
MANUAL_AUDIT_INDEX_JSON = "MANUAL_AUDIT_INDEX.json"
WATCH_LOCK_NAME = "watcher.lock.json"
WATCH_FLOCK_NAME = "watcher.lock"
WATCH_HEARTBEAT_MINUTES = 10
CODEX_ENABLED = False
TERMINAL_PHASES = {"final_gpt_closure_done", "cancelled"}

MAX_MANUAL_AUDIT_BYTES = int(os.environ.get("CAMINO_A_MAX_MANUAL_AUDIT_BYTES", str(2 * 1024 * 1024)))
MAX_OUTPUT_FILE_BYTES = int(os.environ.get("CAMINO_A_MAX_OUTPUT_FILE_BYTES", str(64 * 1024 * 1024)))

SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"ghp_[0-9A-Za-z]{20,}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?[^\s'\"]{12,}"),
    # --- R10: patrones adicionales (SECRET-03) ---
    re.compile(r"glpat-[A-Za-z0-9\-]{20,}"),
    re.compile(r"sk_live_[A-Za-z0-9]{20,}"),
    re.compile(r"sk_test_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"hvs\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}"),
    re.compile(r"-----BEGIN[ A-Z]*(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)(?:postgres|mysql|mongodb)(?:\+\w+)?:\/\/[^\s]{8,}"),
)
SECRET_FIXTURE_HINT = re.compile(r"(?i)\b(dummy|fake|example|fixture|simulad[ao]|simulada|test[_-]?only|valor[_ -]?falso)\b")


def _secret_token_for_entropy(match_text: str) -> str:
    token = re.split(r"[:=]\s*['\"]?", str(match_text), maxsplit=1)[-1].strip()
    token = re.sub(r"(?i)^(sk-proj-|sk-|ghp_|xox[baprs]-|AKIA|AIza)", "", token)
    return re.sub(r"[^A-Za-z0-9]", "", token)


def _looks_like_low_entropy_fixture(match_text: str) -> bool:
    token = _secret_token_for_entropy(match_text)
    if len(token) < 16:
        return False
    return len(set(token)) <= 4


def _secret_match_allowed_as_fixture(sample: str, start: int, end: int, match_text: str) -> bool:
    # No hay bypass global: la pista de fixture debe estar cerca del token y el token debe ser de baja entropía.
    lo = max(0, start - 80)
    hi = min(len(sample), end + 80)
    context = sample[lo:hi]
    return bool(SECRET_FIXTURE_HINT.search(context) and _looks_like_low_entropy_fixture(match_text))


def redact_secrets_text(text: str) -> str:
    redacted = str(text)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    for name, value in os.environ.items():
        if value and len(value) > 6 and any(token in name.upper() for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PAT", "CREDENTIAL", "AUTH")):
            redacted = redacted.replace(value, "<REDACTED_SECRET>")
    return redacted


def assert_no_unredacted_secret(text: str, *, context: str, allow_fixture_hint: bool = False) -> None:
    sample = str(text)
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(sample):
            if allow_fixture_hint and _secret_match_allowed_as_fixture(sample, match.start(), match.end(), match.group(0)):
                continue
            raise SystemExit(f"secret_detected:{context}")


def assert_file_has_no_unredacted_secret(path: Path, *, context: str, allow_fixture_hint: bool = False) -> None:
    if path.stat().st_size > MAX_OUTPUT_FILE_BYTES:
        raise SystemExit(f"output_file_too_large:{path.name}:{path.stat().st_size}")
    # R10:扩展可扫描文本扩展名 (SECRET-03)
    _SCANNABLE_EXTENSIONS = {".json", ".md", ".txt", ".py", ".yaml", ".yml", ".env", ".pem", ".key", ".crt", ".conf", ".cfg", ".ini", ".toml"}
    if path.suffix.lower() in _SCANNABLE_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert_no_unredacted_secret(text, context=context, allow_fixture_hint=allow_fixture_hint)


def validate_output_manifest(
    run_dir: Path,
    out_dir: str,
    manifest_names: tuple[str, ...],
    *,
    expected_stage: str | None,
    expected_candidate_sha256: str | None,
    required_files: tuple[str, ...],
    done_name: str | None = None,
) -> dict[str, Any]:
    out = run_dir / out_dir
    if out.is_symlink() or not out.is_dir():
        raise SystemExit(f"output_dir_invalid_or_symlink:{out_dir}")
    manifest_path = next((out / name for name in manifest_names if (out / name).exists()), None)
    if manifest_path is None:
        raise SystemExit(f"output_manifest_missing:{out_dir}")
    if manifest_path.is_symlink():
        raise SystemExit(f"output_manifest_symlink_rejected:{manifest_path.name}")
    if done_name:
        done_path = out / done_name
        if done_path.is_symlink() or not done_path.is_file():
            raise SystemExit(f"output_done_missing_or_symlink:{done_name}")
        if manifest_path.stat().st_mtime_ns > done_path.stat().st_mtime_ns:
            raise SystemExit(f"output_done_not_last:{done_name}")
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"output_manifest_invalid:{manifest_path}")
    if manifest.get("run_id") != run_dir.name:
        raise SystemExit(f"output_manifest_run_id_mismatch:{manifest.get('run_id')} != {run_dir.name}")
    if expected_stage and manifest.get("stage") != expected_stage:
        raise SystemExit(f"output_manifest_stage_invalid:{manifest.get('stage')}")
    if expected_candidate_sha256 and str(manifest.get("candidate_sha256") or "").lower() != str(expected_candidate_sha256).lower():
        raise SystemExit("output_manifest_candidate_sha256_mismatch")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise SystemExit("output_manifest_files_invalid")
    by_path: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict):
            raise SystemExit("output_manifest_file_entry_invalid")
        rel = str(item.get("path") or item.get("name") or "")
        # R10: INPUT-01 - normalizar Unicode (NFC) para compatibilidad macOS HFS+
        rel = unicodedata.normalize("NFC", rel)
        pp = Path(rel)
        if not rel or pp.is_absolute() or ".." in pp.parts or pp.name != rel:
            raise SystemExit(f"output_manifest_path_unsafe:{rel}")
        assert_no_unredacted_secret(rel, context=f"output_manifest_path:{out_dir}")
        if rel in by_path:
            raise SystemExit(f"output_manifest_duplicate_file:{rel}")
        target = out / rel
        if target.is_symlink() or not target.is_file():
            raise SystemExit(f"output_manifest_file_missing_or_symlink:{rel}")
        size = target.stat().st_size
        if size > MAX_OUTPUT_FILE_BYTES:
            raise SystemExit(f"output_file_too_large:{rel}:{size}")
        if item.get("size_bytes") is not None and int(item.get("size_bytes")) != size:
            raise SystemExit(f"output_manifest_size_mismatch:{rel}")
        expected_sha = str(item.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
            raise SystemExit(f"output_manifest_sha_invalid:{rel}")
        actual_sha = sha256_file(target)
        if actual_sha.lower() != expected_sha.lower():
            raise SystemExit(f"output_manifest_sha_mismatch:{rel}")
        assert_file_has_no_unredacted_secret(target, context=f"output_file:{out_dir}/{rel}", allow_fixture_hint=True)
        by_path[rel] = item
    missing = [name for name in required_files if name not in by_path]
    if missing:
        raise SystemExit(f"output_manifest_required_files_missing:{missing}")
    # R10: PATH-09/SECRET-03 - rechazar archivos no listados en manifest (evita bypass de secret scanning)
    _manifest_known_names = {"OUTPUT_MANIFEST.json", "GPT_CODE_OUTPUT.MANIFEST.json", "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json"}
    if done_name:
        _manifest_known_names.add(done_name)
    for actual in out.iterdir():
        if actual.name in _manifest_known_names:
            continue
        if actual.is_file() and actual.name not in by_path:
            raise SystemExit(f"output_manifest_unlisted_file:{actual.name}")
    return manifest


def write_output_manifest_and_done(run_dir: Path, out_dir: str, *, done_name: str, stage: str, candidate_sha256: str | None, files: tuple[str, ...]) -> None:
    out = run_dir / out_dir
    entries = []
    for rel in files:
        pp = Path(rel)
        if pp.is_absolute() or ".." in pp.parts or pp.name != rel:
            raise SystemExit(f"output_manifest_path_unsafe:{rel}")
        assert_no_unredacted_secret(rel, context=f"output_manifest_path:{out_dir}")
        target = out / rel
        if target.is_symlink() or not target.is_file():
            raise SystemExit(f"output_manifest_file_missing_or_symlink:{rel}")
        if target.stat().st_size > MAX_OUTPUT_FILE_BYTES:
            raise SystemExit(f"output_file_too_large:{rel}:{target.stat().st_size}")
        assert_file_has_no_unredacted_secret(target, context=f"output_file:{out_dir}/{rel}", allow_fixture_hint=True)
        entries.append({"path": rel, "sha256": sha256_file(target), "size_bytes": target.stat().st_size})
    write_json(out / "OUTPUT_MANIFEST.json", {
        "schema_version": "camino_a_output_manifest.v1",
        "run_id": run_dir.name,
        "stage": stage,
        "candidate_sha256": candidate_sha256,
        "files": entries,
        "created_at_utc": utc_now(),
    })
    done = out / done_name
    with done.open("w", encoding="utf-8") as f:
        f.write("DONE\n")
        f.flush()
        os.fsync(f.fileno())
    _fsync_parent_dir(done)

BUS_DIRS = [
    "00_CANDIDATE",
    "01_STATE",
    "10_MANUAL_AUDITS",
    "11_MANUAL_CONTEXT_SNAPSHOT",
    "12_MANUAL_REVIEW_REQUESTS",
    "13_WORKER_BUS",
    "20_AUTO_AUDITS_RAW",
    "21_AUTO_AUDITS_PRECONSOLIDATED",
    "30_GPT_PRIMARY_INPUT",
    "31_GPT_PRIMARY_OUTPUT",
    "40_GPT_CODE_OUTPUT",
    "41_LOCAL_VALIDATION",
    "50_POST_CODE_ADVERSARIAL_AUDITS",
    "51_POST_CODE_AUDIT_PRECONSOLIDATED",
    "60_GPT_ITERATION_INPUT",
    "61_GPT_ITERATION_OUTPUT",
    "70_FINAL_GPT_CLOSURE",
    "80_FINAL_HANDOFF",
    "90_ARCHIVE_MANUAL_CONTEXT",
    "90_QUALITY_LOG_DELTA",
]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_manual_audit_folder import (  # noqa: E402
    prepare as prepare_manual_audit_folder,
    write_auditoria_adversarial,
)
from scripts.camino_a_worker_bus import prepare_worker_bus, scan_worker_outputs, recover_worker_bus_archives  # noqa: E402


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def utc_now_compact() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_slug(value: str, *, fallback: str = "manual") -> str:
    # R10: PATH-13 - limitar longitud y strip prefijo -
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    if len(slug) > 200:
        slug = slug[:200].rstrip("_")
    return slug or fallback


# C-01/CR-CRIT-03: pid_alive reapa zombies y los detecta vía /proc o ps
def pid_alive(pid: int) -> bool:
    """Devuelve True si el proceso `pid` está vivo y NO es zombie.

    Si el proceso es hijo de este proceso, hace waitpid(WNOHANG) para reaparlo.
    Si no es hijo (e.g. lanzado por iteración previa del mismo watcher tras restart),
    sondea su estado vía /proc (Linux) o ps (macOS).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Intentar reap si es nuestro hijo
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            return False  # zombie reaped
    except ChildProcessError:
        # No es nuestro hijo; sondear estado
        if sys.platform == "darwin":
            try:
                cp = subprocess.run(["ps", "-p", str(pid), "-o", "state="],
                                    capture_output=True, text=True, timeout=2)
                st = cp.stdout.strip()
                if st and st[0] in ("Z", "X"):
                    return False
            except Exception:
                pass
        elif sys.platform.startswith("linux"):
            try:
                status_text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace")
                if "State:\tZ" in status_text:
                    return False
            except Exception:
                pass
    except OSError:
        return False
    return True


def reap_children() -> None:
    """Reapa todos los hijos zombie de este proceso (no bloquea)."""
    while True:
        try:
            wpid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if wpid == 0:
            break


def json_safe(data: Any) -> Any:
    if isinstance(data, dict):
        return {str(k): json_safe(v) for k, v in data.items()}
    if isinstance(data, list):
        return [json_safe(v) for v in data]
    if isinstance(data, tuple):
        return [json_safe(v) for v in data]
    if isinstance(data, Path):
        return str(data)
    return data


def write_jsonl_entry(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(json_safe(record), ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    _fsync_parent_dir(path)


def record_quality_log_delta(run_dir: Path, *, manual_audit: dict[str, Any], event: str, notes: str) -> None:
    delta_dir = run_dir / "90_QUALITY_LOG_DELTA"
    delta_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "schema_version": "ai_quality_log_entry.v1",
        "entry_id": str(uuid.uuid4()),
        "created_at_utc": utc_now(),
        "run_id": run_dir.name,
        "audit_family": "camino_a_stage1_manual_ingest",
        "artifact": {
            "file": manual_audit.get("source_file"),
            "version": manual_audit.get("candidate_version") or manual_audit.get("audit_id") or "manual",
        },
        "auditor": {
            "model": manual_audit.get("model") or manual_audit.get("author") or "NO_CONSTA",
            "provider": manual_audit.get("provider") or manual_audit.get("author") or "manual",
            "route": manual_audit.get("route") or "manual_ingest",
            "cost_class": manual_audit.get("cost_class") or "manual",
        },
        "finding": {
            "id": event,
            "type": "meta",
            "severity": "info",
            "summary": notes,
        },
        "adjudication": {
            "final_status": "PENDIENTE",
        },
        "write_actor": {
            "name": "watcher_supervisor",
        },
        "details": json_safe(manual_audit),
    }
    write_json(
        delta_dir / f"{utc_now_compact()}_{safe_slug(event)}_{entry['entry_id'][:8]}.entry.json",
        entry,
    )


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        size = path.stat().st_size
        if size > 50 * 1024 * 1024:  # 50 MiB cap
            raise SystemExit(f"json_file_too_large:{path.name}:{size}")
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"json_parse_error:{path.name}:{e}")
    except UnicodeDecodeError as e:
        raise SystemExit(f"encoding_error:{path.name}:{e}")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_parent_dir(path)
    finally:
        tmp.unlink(missing_ok=True)


def _fsync_parent_dir(path: Path) -> None:
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(fd)
        except OSError:
            return
    finally:
        os.close(fd)


def audit_metadata_from_text(text: str, source: Path, source_sha256: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines()]
    header_patterns = {
        "audit_id": re.compile(r"^(?:audit[_ -]?id|id[_ -]?auditoria)\s*[:=-]\s*(.+)$", re.I),
        "author": re.compile(r"^(?:author|autor)\s*[:=-]\s*(.+)$", re.I),
        "model": re.compile(r"^(?:model|modelo)\s*[:=-]\s*(.+)$", re.I),
        "received_at": re.compile(r"^(?:received[_ -]?at|fecha[_ -]?recepcion|fecha)\s*[:=-]\s*(.+)$", re.I),
    }
    meta: dict[str, Any] = {
        "source_file": str(source),
        "source_name": source.name,
        "source_sha256": source_sha256,
        "received_at": utc_now(),
        "author": None,
        "model": None,
        "audit_id": None,
        "findings": [],
        "state": "received",
        "relation": "independent",
    }
    for line in lines[:60]:
        for key, pattern in header_patterns.items():
            m = pattern.match(line)
            if m and not meta.get(key):
                meta[key] = m.group(1).strip()
    if not meta.get("audit_id"):
        meta["audit_id"] = f"manual_{source.stem}_{source_sha256[:12]}"

    findings: list[str] = []
    in_findings = False
    for raw in lines:
        lower = raw.lower()
        if re.match(r"^#{1,3}\s*(hallazgos|findings|bugs?|mejoras|deudas|observaciones)\b", raw, re.I):
            in_findings = True
            continue
        if in_findings and raw.startswith("#"):
            in_findings = False
        if in_findings and raw.startswith(("-", "*")):
            findings.append(raw.lstrip("-* ").strip())
    if not findings:
        for raw in lines:
            if raw.startswith(("-", "*")):
                findings.append(raw.lstrip("-* ").strip())
    meta["findings"] = [item for item in findings if item]
    meta["findings_count"] = len(meta["findings"])
    return meta


def load_manual_registry(run_dir: Path) -> dict[str, Any]:
    manual_dir = run_dir / "10_MANUAL_AUDITS"
    manual_dir.mkdir(parents=True, exist_ok=True)
    registry_path = manual_dir / MANUAL_AUDIT_INDEX_JSON
    registry = read_json(registry_path, {})
    registry.setdefault("manual_audits_received", 0)
    registry.setdefault("manual_audits", [])
    registry.setdefault("duplicates", [])
    registry.setdefault("source_sha256_index", {})
    if not registry["manual_audits"]:
        for legacy in sorted(manual_dir.glob("manual_[0-9]*.md")):
            source_sha = sha256_file(legacy)
            text = legacy.read_text(encoding="utf-8", errors="replace")
            meta = audit_metadata_from_text(text, legacy, source_sha)
            audit_id = safe_slug(f"legacy_{legacy.stem}_{source_sha[:12]}")
            audit_dir = manual_dir / "audits" / audit_id
            audit_dir.mkdir(parents=True, exist_ok=True)
            dst = audit_dir / legacy.name
            shutil.copy2(legacy, dst)
            meta.update({
                "audit_id": audit_id,
                "destination_file": str(dst.relative_to(run_dir)),
                "destination_name": dst.name,
                "source_label": "legacy_registry_migration",
                "size_bytes": dst.stat().st_size,
                "state": "pending_consolidator_validation",
                "relation": "independent",
            })
            write_json(audit_dir / "metadata.json", meta)
            registry["manual_audits"].append(meta)
            registry["source_sha256_index"][source_sha] = audit_id
        registry["manual_audits_received"] = len(registry["manual_audits"])
        if registry["manual_audits"]:
            write_json(registry_path, registry)
    return registry


def save_manual_registry(run_dir: Path, registry: dict[str, Any]) -> None:
    manual_dir = run_dir / "10_MANUAL_AUDITS"
    manual_dir.mkdir(parents=True, exist_ok=True)
    registry_path = manual_dir / MANUAL_AUDIT_INDEX_JSON
    write_json(registry_path, registry)
    summary_path = manual_dir / MANUAL_REGISTRY_NAME
    summary = {
        "manual_audits_received": registry.get("manual_audits_received", 0),
        "files": [
            {
                "name": audit.get("destination_name"),
                "source": audit.get("source_file"),
                "sha256": audit.get("source_sha256"),
                "size_bytes": audit.get("size_bytes"),
                "audit_id": audit.get("audit_id"),
                "author": audit.get("author"),
                "model": audit.get("model"),
                "received_at": audit.get("received_at"),
                "state": audit.get("state"),
                "relation": audit.get("relation"),
            }
            for audit in registry.get("manual_audits", [])
        ],
        "audits": registry.get("manual_audits", []),
        "duplicates": registry.get("duplicates", []),
    }
    write_json(summary_path, summary)


def render_manual_index(registry: dict[str, Any]) -> str:
    lines = ["# Auditorias manuales recibidas\n\n"]
    if not registry.get("manual_audits"):
        lines.append("Sin auditorias manuales materializadas.\n")
        return "".join(lines)
    for audit in registry.get("manual_audits", []):
        lines.append(f"## {audit.get('audit_id')}\n\n")
        lines.append(f"- source: `{audit.get('source_file')}`\n")
        lines.append(f"- sha256: `{audit.get('source_sha256')}`\n")
        lines.append(f"- received_at: `{audit.get('received_at')}`\n")
        if audit.get("author"):
            lines.append(f"- author: `{audit.get('author')}`\n")
        if audit.get("model"):
            lines.append(f"- model: `{audit.get('model')}`\n")
        lines.append(f"- state: `{audit.get('state')}`\n")
        lines.append(f"- relation: `{audit.get('relation')}`\n")
        findings = audit.get("findings") or []
        lines.append(f"- findings_count: `{len(findings)}`\n")
        if findings:
            lines.append("- findings:\n")
            for item in findings:
                lines.append(f"  - {item}\n")
        lines.append("\n")
    if registry.get("duplicates"):
        lines.append("## Duplicados\n\n")
        for item in registry["duplicates"]:
            lines.append(f"- `{item.get('source_name')}` duplica `{item.get('duplicate_of')}`\n")
    return "".join(lines)


def write_manual_index_artifacts(run_dir: Path, registry: dict[str, Any]) -> None:
    manual_dir = run_dir / "10_MANUAL_AUDITS"
    manual_dir.mkdir(parents=True, exist_ok=True)
    save_manual_registry(run_dir, registry)
    (manual_dir / MANUAL_INDEX_NAME).write_text(render_manual_index(registry), encoding="utf-8")


def prepare_desktop_manual_inbox(run_dir: Path) -> None:
    inbox = DEFAULT_DESKTOP_MANUAL_FOLDER
    inbox.mkdir(parents=True, exist_ok=True)
    readme = inbox / "README_CAMINO_A_INGRESO_MANUAL.md"
    readme.write_text(
        "# CAMINO_A_INGRESO_MANUAL\n\n"
        "Dejá o pegá aqui auditorías manuales en `.md`.\n"
        f"El orquestador las importa al run `{run_dir.name}` sin fusionarlas.\n"
        "No subir ZIPs ni archivos temporales.\n",
        encoding="utf-8",
    )


def materialize_manual_audit(
    run_dir: Path,
    source: Path,
    *,
    source_label: str,
    copy_target_name: str | None = None,
) -> tuple[dict[str, Any], bool]:
    if not source.exists() or not source.is_file():
        raise SystemExit(f"manual_no_encontrada:{source}")
    # M-03/SEG-MED-03: rechazar symlinks en source de manual audit
    if source.is_symlink():
        raise SystemExit(f"manual_symlink_rejected:{source}")
    if source.suffix.lower() not in {".md", ".txt"}:
        raise SystemExit(f"manual_extension_invalida:{source}")
    if source.stat().st_size > MAX_MANUAL_AUDIT_BYTES:
        raise SystemExit(f"manual_too_large:{source.stat().st_size}>{MAX_MANUAL_AUDIT_BYTES}")
    assert_no_unredacted_secret(source.name, context="manual_filename", allow_fixture_hint=True)

    registry = load_manual_registry(run_dir)
    source_sha256 = sha256_file(source)
    existing_id = registry.get("source_sha256_index", {}).get(source_sha256)
    if existing_id:
        duplicate_record = {
            "source_name": source.name,
            "source_file": str(source),
            "source_sha256": source_sha256,
            "duplicate_of": existing_id,
            "source_label": source_label,
            "received_at": utc_now(),
        }
        registry.setdefault("duplicates", []).append(duplicate_record)
        write_manual_index_artifacts(run_dir, registry)
        return duplicate_record, False

    text = source.read_text(encoding="utf-8", errors="replace")
    assert_no_unredacted_secret(text, context="manual_content", allow_fixture_hint=True)
    if len(text.strip()) < 40:
        raise SystemExit(f"manual_contenido_insuficiente:{source}")
    meta = audit_metadata_from_text(text, source, source_sha256)
    audit_id = safe_slug(str(meta.get("audit_id") or f"manual_{source_sha256[:12]}"))
    used_ids = {str(item.get("audit_id")) for item in registry.get("manual_audits", [])}
    if audit_id in used_ids:
        audit_id = f"{audit_id}_{source_sha256[:12]}"
    audit_dir = run_dir / "10_MANUAL_AUDITS" / "audits" / audit_id
    audit_dir.mkdir(parents=True, exist_ok=True)
    dst_name = copy_target_name or (source.name if source.suffix.lower() == ".md" else f"{audit_id}.md")
    dst = audit_dir / dst_name
    # M-07/CR-MED-03: pending_ingest marker para reanudación ante crash
    pending_marker = run_dir / "01_STATE" / f"pending_ingest_{source_sha256[:12]}.json"
    write_json(pending_marker, {
        "audit_id": audit_id, "source": str(source), "source_sha256": source_sha256,
        "started_at": utc_now(), "source_label": source_label,
    })
    shutil.copy2(source, dst)
    meta.update({
        "audit_id": audit_id,
        "destination_file": str(dst.relative_to(run_dir)),
        "destination_name": dst.name,
        "source_label": source_label,
        "size_bytes": dst.stat().st_size,
        "state": "pending_consolidator_validation",
        "relation": "independent",
        "candidate_sha256_at_receipt": load_state(run_dir).get("current_candidate_sha256"),
    })
    write_json(audit_dir / "metadata.json", meta)
    registry["source_sha256_index"][source_sha256] = audit_id
    registry.setdefault("manual_audits", []).append(meta)
    registry["manual_audits_received"] = len(registry["manual_audits"])
    write_manual_index_artifacts(run_dir, registry)
    record_quality_log_delta(run_dir, manual_audit=meta, event="manual_audit_ingested",
                             notes=f"Materializada auditoria manual independiente {audit_id}")
    pending_marker.unlink(missing_ok=True)  # commit
    return meta, True


def scan_manual_sources(run_dir: Path, *, source_label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state = load_state(run_dir)
    sources = [
        Path(state.get("manual_folder") or DEFAULT_MANUAL_FOLDER) / run_dir.name / "INBOX",
        Path(state.get("desktop_manual_inbox") or (DEFAULT_DESKTOP_MANUAL_FOLDER / run_dir.name / "INBOX")),
    ]
    ingested: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for base in sources:
        if not base.exists() or not base.is_dir():
            continue
        processed = base.parent / "PROCESSED"
        processed.mkdir(parents=True, exist_ok=True)
        for path in sorted(p for p in base.iterdir() if p.is_file() and p.suffix.lower() in {".md", ".txt"}):
            if path.name in {"auditoria_adversarial.md", MANUAL_INDEX_NAME}:
                continue
            record, added = materialize_manual_audit(run_dir, path, source_label=source_label)
            if added:
                ingested.append(record)
            else:
                duplicates.append(record)
            destination = processed / f"{utc_now_compact()}_{safe_slug(path.stem)}{path.suffix.lower()}"
            if destination.exists():
                destination = processed / f"{utc_now_compact()}_{safe_slug(path.stem)}_{uuid.uuid4().hex[:8]}{path.suffix.lower()}"
            shutil.move(str(path), destination)
    return ingested, duplicates


def brain_job_path(run_dir: Path) -> Path:
    return run_dir / "01_STATE" / "primary_brain_job.json"


def brain_stage_for_phase(phase: str | None) -> str | None:
    return {
        "waiting_gpt_primary_output": "primary_consolidation",
        "waiting_gpt_code_output": "code_generation",
        "waiting_gpt_post_code_output": "post_code_review",
    }.get(str(phase))


def brain_done_path(run_dir: Path, stage: str) -> Path:
    mapping = {
        "primary_consolidation": run_dir / "31_GPT_PRIMARY_OUTPUT" / "CONSOLIDACION_GPT_PRIMARIA.DONE",
        "code_generation": run_dir / "40_GPT_CODE_OUTPUT" / "GPT_CODE_OUTPUT.DONE",
        "post_code_review": run_dir / "61_GPT_ITERATION_OUTPUT" / "AUDITORIA_ADVERSARIAL_POST_CODIGO.DONE",
    }
    return mapping[stage]


def brain_adapter_response_path(run_dir: Path, stage: str) -> Path:
    mapping = {
        "primary_consolidation": run_dir / "31_GPT_PRIMARY_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        "code_generation": run_dir / "40_GPT_CODE_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        "post_code_review": run_dir / "61_GPT_ITERATION_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
    }
    return mapping[stage]


# R2-CONC-06: cancel_active_brain_job espera exit real del adapter antes de retornar
def cancel_active_brain_job(run_dir: Path, *, reason: str, wait_exit_seconds: float = 5.0) -> None:
    path = brain_job_path(run_dir)
    job = read_json(path, {})
    pid = int(job.get("pid", 0) or 0)
    stage = str(job.get("stage") or "")
    completed_by_adapter = bool(
        stage
        and stage in {"primary_consolidation", "code_generation", "post_code_review"}
        and brain_done_path(run_dir, stage).exists()
        and brain_adapter_response_path(run_dir, stage).exists()
    )
    if pid_alive(pid) and not completed_by_adapter:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        # R2-CONC-06: esperar exit real antes de retornar (evita race con archive_stale_outputs)
        deadline = time.monotonic() + wait_exit_seconds
        while time.monotonic() < deadline:
            if not pid_alive(pid):
                break
            time.sleep(0.1)
        else:
            # SIGKILL si no murió en wait_exit_seconds
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    if job:
        suffix = "brain_job_completed" if completed_by_adapter else "brain_job_cancelled"
        archive = run_dir / "90_ARCHIVE_MANUAL_CONTEXT" / f"{utc_now_compact()}_{suffix}"
        archive.mkdir(parents=True, exist_ok=True)
        job["completed_at" if completed_by_adapter else "cancelled_at"] = utc_now()
        job["completion_reason" if completed_by_adapter else "cancel_reason"] = reason
        write_json(archive / "primary_brain_job.json", job)
    path.unlink(missing_ok=True)


def launch_primary_brain_job(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    if not state.get("primary_brain_adapter_enabled", True):
        return state
    stage = brain_stage_for_phase(state.get("current_phase"))
    if not stage or brain_done_path(run_dir, stage).exists():
        return state
    job_path = brain_job_path(run_dir)
    current = read_json(job_path, {})
    current_pid = int(current.get("pid", 0) or 0)
    if current.get("stage") == stage and pid_alive(current_pid):
        state["primary_brain_status"] = "running"
        return state
    if current and not pid_alive(current_pid):
        current["observed_exited_at"] = utc_now()
        archive = run_dir / "01_STATE" / "primary_brain_jobs"
        archive.mkdir(parents=True, exist_ok=True)
        write_json(archive / f"{utc_now_compact()}_{safe_slug(str(current.get('stage')))}.json", current)
        job_path.unlink(missing_ok=True)

    attempts = state.setdefault("primary_brain_job_attempts", {})
    attempt_key = f"{stage}:{str(state.get('current_candidate_sha256') or '')[:16]}"
    attempt = int(attempts.get(attempt_key, 0)) + 1
    if attempt > 2:
        state["primary_brain_status"] = "failed_waiting_manual_output"
        state["next_action_for_mariano"] = "cerebro_automatico_fallo_dos_veces; watcher_sigue_activo_y_acepta_salida_manual"
        # FIX B-2: el agotamiento del cerebro automatico setea primary_brain_status
        # (NO current_phase), por lo que la rama de limbo del watch loop —que chequea
        # current_phase— jamas dispara. Sin esta notificacion el run queda en stall
        # silencioso en waiting_gpt_*. Notificar una sola vez por (stage, candidato).
        notify_once(
            run_dir, state,
            f"primary_brain_exhausted_{stage}_{str(state.get('current_candidate_sha256') or '')[:12]}",
            "Camino A: cerebro automatico agotado",
            f"El cerebro automatico fallo {attempt - 1} veces en {stage}. "
            "Cargar salida GPT manual o revisar logs; el watcher sigue activo.",
        )
        return state
    log_dir = run_dir / "01_STATE" / "primary_brain_jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{stage}_attempt_{attempt}.stdout.log"
    stderr_path = log_dir / f"{stage}_attempt_{attempt}.stderr.log"
    stdout_handle = stdout_path.open("ab")
    stderr_handle = stderr_path.open("ab")
    try:
        process = subprocess.Popen(
            [sys.executable, str(PRIMARY_BRAIN_ADAPTER), "--run-dir", str(run_dir), "--stage", stage],
            cwd=ROOT,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    job = {
        "schema_version": "primary_brain_job.v1",
        "run_id": run_dir.name,
        "stage": stage,
        "pid": process.pid,
        "attempt": attempt,
        "started_at": utc_now(),
        "candidate_sha256": state.get("current_candidate_sha256"),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    write_json(job_path, job)
    attempts[attempt_key] = attempt
    state["primary_brain_status"] = "running"
    state["primary_brain_current_job"] = job
    history_event(state, "primary_brain_job_started", stage=stage, pid=process.pid, attempt=attempt)
    return state


def workflow_job_path(run_dir: Path) -> Path:
    return run_dir / "01_STATE" / "workflow_job.json"


def launch_workflow_job(run_dir: Path, state: dict[str, Any], *, action: str, dry_run: bool) -> dict[str, Any]:
    commands = {
        "cycle1_auto_audits": "--run-auto-audits-cycle1",
        "post_code_adversarial_audits": "--run-post-code-adversarial-audits",
    }
    running_phases = {
        "cycle1_auto_audits": "cycle_1_auto_running",
        "post_code_adversarial_audits": "post_code_adversarial_running",
    }
    if action not in commands:
        raise ValueError(f"workflow_action_unknown:{action}")
    path = workflow_job_path(run_dir)
    current = read_json(path, {})
    pid = int(current.get("pid", 0) or 0)
    if current.get("action") == action and pid_alive(pid):
        state["workflow_job_status"] = "running"
        return state
    if current and not pid_alive(pid):
        archive = run_dir / "01_STATE" / "workflow_jobs"
        archive.mkdir(parents=True, exist_ok=True)
        current["observed_exited_at"] = utc_now()
        write_json(archive / f"{utc_now_compact()}_{safe_slug(str(current.get('action')))}.json", current)
        path.unlink(missing_ok=True)
        if state.get("current_phase") != running_phases.get(current.get("action")):
            return state
    attempts = state.setdefault("workflow_job_attempts", {})
    attempt_key = f"{action}:{str(state.get('current_candidate_sha256') or '')[:16]}"
    attempt = int(attempts.get(attempt_key, 0)) + 1
    if attempt > 2:
        state["workflow_job_status"] = "failed_waiting_operator"
        state["next_action_for_mariano"] = f"workflow_{action}_fallo_dos_veces"
        # FIX B-1: tambien notificar aca (path legacy de subproceso) para no dejar
        # stall silencioso si este path se usara.
        notify_once(
            run_dir, state,
            f"workflow_exhausted_{action}_{str(state.get('current_candidate_sha256') or '')[:12]}",
            "Camino A requiere intervencion",
            f"El workflow automatico {action} fallo {attempt - 1} veces; el watcher sigue activo.",
        )
        return state
    log_dir = run_dir / "01_STATE" / "workflow_jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{action}_attempt_{attempt}.stdout.log"
    stderr_path = log_dir / f"{action}_attempt_{attempt}.stderr.log"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--resume", str(run_dir), commands[action]]
    if dry_run:
        cmd.append("--dry-run")
    state["workflow_job_status"] = "starting"
    state["current_phase"] = running_phases[action]
    save_state(run_dir, state)
    stdout_handle = stdout_path.open("ab")
    stderr_handle = stderr_path.open("ab")
    try:
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    job = {
        "schema_version": "camino_a_workflow_job.v1",
        "run_id": run_dir.name,
        "action": action,
        "pid": process.pid,
        "attempt": attempt,
        "started_at": utc_now(),
        "candidate_sha256": state.get("current_candidate_sha256"),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    write_json(path, job)
    attempts[attempt_key] = attempt
    state["workflow_job_status"] = "running"
    state["workflow_current_job"] = job
    state["current_phase"] = running_phases[action]
    history_event(state, "workflow_job_started", action=action, pid=process.pid, attempt=attempt)
    return state


def run_workflow_action_inline(run_dir: Path, state: dict[str, Any], *, action: str, dry_run: bool) -> dict[str, Any]:
    """FIX B-1 (estructural): ejecuta cycle1/post-code EN PROCESO.

    Causa raiz: el watcher mantiene el run-lock toda su vida (C-02). `launch_workflow_job`
    relanzaba estas acciones como SUBPROCESO que reentra por main() y pide el MISMO
    run-lock -> BlockingIOError -> SystemExit('watcher_lock_active') -> exit 1. Bajo el
    watcher persistente, cycle1 y post-code NUNCA corrian; tras 2 intentos fallidos el run
    quedaba en `failed_waiting_operator` SILENCIOSO.

    Ejecutar inline elimina la colision (mismo proceso, mismo lock) y la carrera RMW que
    tendria un subproceso eximido del lock (watcher + hijo escribiendo cycle_state.json a
    la vez). Mantiene conteo de intentos acotado y notifica al agotar.

    Tradeoff (residual, no bloqueante): bloquea el watch loop durante la auditoria. Con el
    auditor real (no-stub) conviene migrar a un hijo que herede el fd del flock (pass_fds)
    y que el watcher pause sus escrituras de estado mientras el hijo corre.
    """
    runners = {
        "cycle1_auto_audits": lambda: run_cycle1(run_dir, load_state(run_dir), dry_run=dry_run),
        "post_code_adversarial_audits": lambda: run_post_code_adversarial_audits(run_dir, load_state(run_dir), dry_run=dry_run),
    }
    if action not in runners:
        raise ValueError(f"workflow_action_unknown:{action}")
    attempts = state.setdefault("workflow_inline_attempts", {})
    key = f"{action}:{str(state.get('current_candidate_sha256') or '')[:16]}"
    attempt = int(attempts.get(key, 0)) + 1
    if attempt > 2:
        state["workflow_job_status"] = "failed_waiting_operator"
        state["next_action_for_mariano"] = f"workflow_{action}_fallo_dos_veces; cargar_salida_manual_o_revisar_logs"
        notify_once(
            run_dir, state,
            f"workflow_exhausted_{action}_{str(state.get('current_candidate_sha256') or '')[:12]}",
            "Camino A requiere intervencion",
            f"El workflow automatico {action} fallo {attempt - 1} veces; el watcher sigue activo.",
        )
        save_state(run_dir, state)
        return state
    attempts[key] = attempt
    save_state(run_dir, state)
    new_state = runners[action]()
    new_state.setdefault("workflow_inline_attempts", {}).pop(key, None)
    save_state(run_dir, new_state)
    return new_state


# M-05/CR-MED-01 + M-09/CONC-MED-10 + M-06/CR-MED-02: archive_stale_outputs con guards FileNotFoundError + uuid suffix
def archive_stale_outputs(run_dir: Path, *, reason: str) -> str | None:
    output_dirs = [
        "31_GPT_PRIMARY_OUTPUT",
        "40_GPT_CODE_OUTPUT",
        "41_LOCAL_VALIDATION",
        "50_POST_CODE_ADVERSARIAL_AUDITS",
        "51_POST_CODE_AUDIT_PRECONSOLIDATED",
        "60_GPT_ITERATION_INPUT",
        "61_GPT_ITERATION_OUTPUT",
        "70_FINAL_GPT_CLOSURE",
    ]
    # M-05: guards FileNotFoundError en iterdir
    has_content = False
    for name in output_dirs:
        src = run_dir / name
        try:
            if src.exists() and any(src.iterdir()):
                has_content = True
                break
        except FileNotFoundError:
            continue
    if not has_content:
        return None
    # M-09: uuid suffix para uniquing ante concurrencia
    archive = run_dir / "90_ARCHIVE_MANUAL_CONTEXT" / f"{utc_now_compact()}_{safe_slug(reason)}_{uuid.uuid4().hex[:8]}"
    for name in output_dirs:
        src = run_dir / name
        try:
            if not src.exists():
                continue
            items = list(src.iterdir())
        except FileNotFoundError:
            continue
        if not items:
            continue
        dst = archive / name
        dst.mkdir(parents=True, exist_ok=True)
        for item in items:
            try:
                shutil.move(str(item), dst / item.name)
            except FileNotFoundError:
                continue
    return str(archive.relative_to(run_dir))


# M-05 + M-06 + R2-CR-05: archive_output_dir atómico con os.rename + fallback cross-FS seguro
def archive_output_dir(run_dir: Path, dirname: str, *, reason: str) -> str | None:
    src = run_dir / dirname
    try:
        if not src.exists() or not any(src.iterdir()):
            return None
    except FileNotFoundError:
        return None
    archive_root = run_dir / "90_ARCHIVE_MANUAL_CONTEXT" / f"{utc_now_compact()}_{safe_slug(reason)}_{uuid.uuid4().hex[:8]}"
    archive_root.mkdir(parents=True, exist_ok=True)
    dst = archive_root / dirname
    try:
        # M-06: intentar os.rename del dir entero (atómico mismo FS)
        os.rename(str(src), str(dst))
    except OSError:
        # R2-CR-05: cross-FS fallback seguro — copytree a dst.tmp + fsync + rename + rmtree src
        dst_tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copytree(str(src), str(dst_tmp), symlinks=False)
            _fsync_parent_dir(dst_tmp)
            os.rename(str(dst_tmp), str(dst))
            _fsync_parent_dir(dst)
            shutil.rmtree(str(src))  # si falla, src queda pero dst ya está completo
        except OSError as exc:
            # Limpiar dst_tmp si quedó; propagar para que caller maneje
            shutil.rmtree(dst_tmp, ignore_errors=True)
            raise
    _fsync_parent_dir(archive_root)
    src.mkdir(parents=True, exist_ok=True)  # re-crear vacío para invariantes
    return str(archive_root.relative_to(run_dir))


def write_late_manual_review_request(run_dir: Path, state: dict[str, Any], audits: list[dict[str, Any]]) -> None:
    out = run_dir / "12_MANUAL_REVIEW_REQUESTS"
    out.mkdir(parents=True, exist_ok=True)
    stamp = utc_now_compact()
    payload = {
        "schema_version": "camino_a_late_manual_review.v1",
        "created_at_utc": utc_now(),
        "run_id": run_dir.name,
        "candidate_sha256_to_validate": state.get("current_candidate_sha256"),
        "candidate_version_to_validate": state.get("current_candidate_version"),
        "audit_ids": [item.get("audit_id") for item in audits],
        "required_status_per_finding": [
            "persiste",
            "corregido_previamente",
            "duplicado",
            "no_reproducible",
            "pendiente",
        ],
        "rule": "Validar cada hallazgo contra el candidato vigente antes de consolidar; la antiguedad de la auditoria no permite descartarla.",
    }
    write_json(out / f"LATE_MANUAL_REVIEW_{stamp}.json", payload)
    (out / f"LATE_MANUAL_REVIEW_{stamp}.md").write_text(
        "# Revalidacion obligatoria de cosecha manual tardia\n\n"
        f"Candidato vigente: `{payload['candidate_sha256_to_validate']}`.\n\n"
        "El consolidador debe revisar cada hallazgo de las auditorias listadas y asignar uno de estos estados: "
        "`persiste`, `corregido_previamente`, `duplicado`, `no_reproducible` o `pendiente`. "
        "Si un problema persiste, debe incorporarlo a la consolidacion actual.\n\n"
        + "\n".join(f"- `{audit_id}`" for audit_id in payload["audit_ids"])
        + "\n",
        encoding="utf-8",
    )


# H-05/CR-HIGH-03 + H-07/CONC-HIGH-07: invalidate_downstream_after_manual_update transaccional + reset attempts
def invalidate_downstream_after_manual_update(run_dir: Path, state: dict[str, Any], audits: list[dict[str, Any]]) -> None:
    """Invalida downstream tras evidencia manual tardía. Transaccional vía invalidate_pending.

    1. Persiste `invalidate_pending` ANTES de side-effects (durabilidad ante crash).
    2. Cancela brain job, archivea outputs stale, resetea phase.
    3. Resetea `primary_brain_job_attempts` para que los reintentos se cuenten desde cero
       (H-07): el request_sha256 del adapter cambia al incluir nuevos manuales.
    4. Limpia `invalidate_pending` al final (commit).
    Si el proceso muere a mitad, el watcher ve `invalidate_pending` y reanuda.
    """
    state["invalidate_pending"] = {
        "reason": "late_manual_evidence",
        "audit_ids": [item.get("audit_id") for item in audits],
        "started_at": utc_now(),
    }
    save_state(run_dir, state)  # checkpoint durable
    try:
        cancel_active_brain_job(run_dir, reason="late_manual_evidence")
        archived = archive_stale_outputs(run_dir, reason="late_manual")
        # H-07/CONC-HIGH-07 + R2-CONC-07 + R3-02: reset de attempts si se recibieron nuevos manuales
        # desde el último reset. Usar manual_audits_received como trigger (cuando llegan manuales
        # nuevos, el request_sha256 del adapter cambia implícitamente al incluirlos en el prompt).
        # R3-02: comparar contra manual_audits_received es más robusto que candidate_sha256
        # porque el candidato no cambia hasta que se genere nuevo código, pero los manuales sí.
        last_reset_manuals = state.get("_invalidate_last_reset_manuals", -1)
        current_manuals = int(state.get("manual_audits_received", 0))
        if last_reset_manuals != current_manuals:
            attempts = state.setdefault("primary_brain_job_attempts", {})
            for stage in ("primary_consolidation", "code_generation", "post_code_review"):
                key = f"{stage}:{str(state.get('current_candidate_sha256') or '')[:16]}"
                attempts.pop(key, None)
            state["_invalidate_last_reset_manuals"] = current_manuals
        state["gpt_primary_consolidation_status"] = "waiting"
        if state.get("gpt_code_generation_status") in {"complete", "waiting", "not_required"}:
            state["gpt_code_generation_status"] = "pending"
        if state.get("local_validation_status") in {"passed", "failed"}:
            state["local_validation_status"] = "pending"
        if state.get("post_code_adversarial_audit_status") in {"complete", "running", "ready"}:
            state["post_code_adversarial_audit_status"] = "pending"
        if state.get("gpt_post_code_audit_status") in {"bug0_mejoras0", "code_required", "blocked", "waiting"}:
            state["gpt_post_code_audit_status"] = "pending"
        if state.get("current_phase") not in TERMINAL_PHASES:
            state["current_phase"] = "waiting_gpt_primary_output"
        state["manual_revision_required"] = True
        state["manual_revision_audit_ids"] = [item.get("audit_id") for item in audits]
        if archived:
            state["last_stale_output_archive"] = archived
        state["watcher_status"] = "active"
        state["next_action_for_mariano"] = "guardar_CONSOLIDACION_GPT_PRIMARIA_en_31_GPT_PRIMARY_OUTPUT"
        write_late_manual_review_request(run_dir, state, audits)
        state.pop("invalidate_pending", None)  # commit
    except BaseException:
        # Persistir estado parcial para reanudación
        save_state(run_dir, state)
        raise


def refresh_manual_ingress(run_dir: Path, state: dict[str, Any], *, source_label: str = "watcher") -> dict[str, Any]:
    ingested, duplicates = scan_manual_sources(run_dir, source_label=source_label)
    if not ingested and not duplicates:
        return state
    if ingested:
        state["manual_audits_received"] = len((load_manual_registry(run_dir).get("manual_audits") or []))
        state["manual_window"] = "open_until_terminal"
        was_late = state.get("auto_audits_cycle1_status") == "complete" or state.get("gpt_primary_consolidation_status") not in {"pending", None}
        if was_late:
            invalidate_downstream_after_manual_update(run_dir, state, ingested)
            event = "late_manual_audits_ingested"
        elif manual_gate_open(state):
            state["current_phase"] = "cycle_1_auto_ready"
            state["next_action_for_mariano"] = "continuar_ciclo_1_automatico"
            event = "manual_audits_ingested_gate_open"
        else:
            event = "manual_audits_ingested_gate_pending"
        history_event(state, event, audit_ids=[item.get("audit_id") for item in ingested], duplicates=len(duplicates))
        write_gpt_primary_input(run_dir, state)
    elif duplicates:
        history_event(state, "late_manual_audits_duplicate_only", count=len(duplicates))
    save_state(run_dir, state)
    return state


def load_watcher_lock(run_dir: Path) -> dict[str, Any]:
    lock_path = run_dir / "01_STATE" / WATCH_LOCK_NAME
    if not lock_path.exists():
        return {}
    return read_json(lock_path, {})


def acquire_watcher_lock(run_dir: Path) -> dict[str, Any]:
    lock_path = run_dir / "01_STATE" / WATCH_LOCK_NAME
    flock_path = run_dir / "01_STATE" / WATCH_FLOCK_NAME
    flock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(flock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        current = load_watcher_lock(run_dir)
        raise SystemExit(f"watcher_lock_active:{current.get('pid', 'unknown')}")
    current = load_watcher_lock(run_dir)
    pid = os.getpid()
    lock = {
        "fd": fd,
        "pid": pid,
        "run_id": run_dir.name,
        "started_at": utc_now(),
        "updated_at": utc_now(),
        "script": str(Path(__file__).resolve()),
    }
    write_json(lock_path, {k: v for k, v in lock.items() if k != "fd"})
    return lock


def touch_watcher_lock(run_dir: Path, lock: dict[str, Any]) -> None:
    lock_path = run_dir / "01_STATE" / WATCH_LOCK_NAME
    lock["updated_at"] = utc_now()
    write_json(lock_path, {k: v for k, v in lock.items() if k != "fd"})


def release_watcher_lock(run_dir: Path, lock: dict[str, Any]) -> None:
    lock_path = run_dir / "01_STATE" / WATCH_LOCK_NAME
    current = load_watcher_lock(run_dir)
    if current.get("pid") == lock.get("pid"):
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
    fd = lock.get("fd")
    if isinstance(fd, int):
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _sanitized_env() -> dict[str, str]:
    """R10: EXEC-03 - entorno sanitizado para ejecutar código generado.
    Solo incluye变量 de sistema esenciales, excluye tokens/keys."""
    safe_vars = {
        "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
        "TMPDIR", "TMP", "TEMP", "PYTHONPATH", "PYTHONIOENCODING",
        "PYTHONDONTWRITEBYTECODE", "TERM", "COLORTERM", "NO_COLOR",
    }
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.upper() in safe_vars or (k.startswith("PYTHON") and "KEY" not in k.upper() and "SECRET" not in k.upper()):
            env[k] = v
    return env


def _sandbox_preexec() -> None:
    """R10: EXEC-01/05/06 - sandbox para código generado no confiable.
    Aplica resource limits y intenta bloquear red."""
    import resource
    # CPU time: 60s max
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    # Address space: 512 MiB
    _512mb = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (_512mb, _512mb))
    # File size: 50 MiB max write
    _50mb = 50 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (_50mb, _50mb))
    # No core dumps
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # Max 64 file descriptors
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # Max 8 processes (prevents fork bombs)
    resource.setrlimit(resource.RLIMIT_NPROC, (8, 8))
    # PR_SET_NO_NEW_PRIVS:阻止获取新权限
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(38, 1, 0, 0, 0)  # PR_SET_NO_NEW_PRIVS = 38
    except (OSError, AttributeError, TypeError):
        pass
    # Intentar bloquear red via iptables (requiere cap_net_admin o root)
    # Si no tiene permisos, falla silenciosamente — los resource limits ya protegen
    try:
        uid = os.getuid()
        subprocess.run(
            ["iptables", "-A", "OUTPUT", "-m", "owner", "--uid-owner", str(uid),
             "-p", "tcp", "-j", "DROP"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def run(cmd: list[str], *, capture_to: Path | None = None, timeout: int | None = 120, env: dict[str, str] | None = None, sandbox: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    # R10: RESIL-06/EXEC-04/EXEC-07 - timeout por defecto 120s; env/sandbox para código no confiable
    cp = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture_to is not None,
                        timeout=timeout, env=env, preexec_fn=_sandbox_preexec if sandbox else None)
    if capture_to is not None:
        capture_to.parent.mkdir(parents=True, exist_ok=True)
        # R10: EXEC-08 - limitar tamaño de logs a 10 MiB
        _log_content = (cp.stdout or "") + (cp.stderr or "")
        _MAX_LOG_BYTES = 10 * 1024 * 1024
        if len(_log_content.encode("utf-8", errors="replace")) > _MAX_LOG_BYTES:
            _log_content = _log_content[:_MAX_LOG_BYTES] + "\n[TRUNCATED: log exceeded 10 MiB]"
        capture_to.write_text(_log_content, encoding="utf-8")
    if cp.returncode != 0:
        raise subprocess.CalledProcessError(cp.returncode, cmd, output=cp.stdout, stderr=cp.stderr)
    return cp


def resolve_run_dir(value: str) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p


def ensure_bus_dirs(run_dir: Path) -> None:
    for name in BUS_DIRS:
        (run_dir / name).mkdir(parents=True, exist_ok=True)


def make_run_dir(drive_bus_root: Path) -> Path:
    drive_bus_root.mkdir(parents=True, exist_ok=True)
    run_id = "RUN_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = drive_bus_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    ensure_bus_dirs(run_dir)
    prepare_worker_bus(run_dir)
    return run_dir


def copy_tree_files(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for item in src.iterdir():
        # R10: PATH-01 -拒绝符号链接
        if item.is_symlink():
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target)


def find_candidate_file(input_path: Path, candidate_name: str = "") -> Path:
    if input_path.is_file() and input_path.suffix == ".py":
        return input_path
    if not input_path.is_dir():
        raise SystemExit(f"input_no_existe_o_no_soportado:{input_path}")
    py_files = sorted(input_path.glob("*.py"))
    if candidate_name:
        hits = [p for p in py_files if candidate_name in p.name]
        if hits:
            return hits[0]
    hits = [p for p in py_files if "adaptador" in p.name and "validador" in p.name]
    if hits:
        return hits[0]
    if len(py_files) == 1:
        return py_files[0]
    raise SystemExit(f"candidate_no_detectado:{input_path}")


def validate_candidate(input_path: Path, candidate_name: str, target_version: str, *, dry_run: bool) -> dict[str, str]:
    candidate_file = find_candidate_file(input_path, candidate_name)
    sha = sha256_file(candidate_file)
    if dry_run:
        print(f"DRY_RUN: validaria py_compile/self-test de {candidate_file}")
    else:
        run([sys.executable, "-m", "py_compile", str(candidate_file)])
        # R10: EXEC-02/EXEC-03 - sandbox también en validate_candidate
        run([sys.executable, str(candidate_file), "--self-test"], env=_sanitized_env(), timeout=30, sandbox=True)
    return {
        "candidate_path": str(input_path),
        "candidate_file": str(candidate_file),
        "candidate_sha256": sha,
        "candidate_version": target_version,
    }


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    ensure_bus_dirs(run_dir)
    state["updated_at"] = utc_now()
    # R10: CONC-02 -先写 01_STATE/ 再写 root，使 root 始终为最新
    write_json(run_dir / "01_STATE" / STATE_NAME, state)
    write_json(run_dir / STATE_NAME, state)


def load_state(run_dir: Path) -> dict[str, Any]:
    ensure_bus_dirs(run_dir)
    state_path = run_dir / STATE_NAME
    if not state_path.exists():
        raise SystemExit(f"cycle_state_no_existe:{state_path}")
    state = read_json(state_path, {})
    migrate_state_defaults(run_dir, state)
    return state


def history_event(state: dict[str, Any], event: str, **extra: Any) -> None:
    # R10: RESIL-03 - limitar historial a 500 entradas
    history = state.setdefault("history", [])
    history.append({"at": utc_now(), "event": event, **extra})
    if len(history) > 500:
        state["history"] = history[-500:]


# L-03/SEG-LOW-03: send_local_notification con ensure_ascii=False + sanitización de control chars
def _applescript_string(s: str) -> str:
    """Escapa un string para AppleScript vía json.dumps con ensure_ascii=False.
    Limpia control chars que AppleScript no soporta."""
    cleaned = "".join(c for c in s if c >= " " or c in "\t")
    return json.dumps(cleaned, ensure_ascii=False)


def send_local_notification(title: str, message: str) -> bool:
    if sys.platform != "darwin" or os.environ.get("CAMINO_A_DISABLE_NOTIFICATIONS") == "1":
        return False
    script = 'display notification ' + _applescript_string(message[:220]) + ' with title ' + _applescript_string(title[:80])
    completed = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


# L-02/SEG-LOW-02: safe_error_text con tokens ampliados
def safe_error_text(exc: BaseException) -> str:
    text = f"{type(exc).__name__}:{exc}"
    return redact_secrets_text(text)[:2000]


# H-03/CONC-HIGH-04: notify_once consulta disco antes de enviar (durable ante crash)
def notify_once(run_dir: Path, state: dict[str, Any], key: str, title: str, message: str) -> None:
    sent = state.setdefault("notifications_sent", {})
    tombstone = run_dir / "01_STATE" / f"NOTIFICATION_{safe_slug(key)}.json"
    if key in sent or tombstone.exists():
        # Ya notificado (en memoria o en disco); sincronizar memoria con disco si hace falta
        if key not in sent and tombstone.exists():
            sent[key] = read_json(tombstone, {"at": utc_now(), "delivered": True})
        return
    delivered = send_local_notification(title, message)
    record = {"at": utc_now(), "delivered": delivered}
    # Persistir PRIMERO en disco (durabilidad ante crash), luego en memoria
    write_json(tombstone, record)
    sent[key] = record
    # R10: RESIL-05 - limitar notifications_sent a 100 entradas
    if len(sent) > 100:
        oldest_keys = sorted(sent, key=lambda k: sent[k].get("at", ""))[:len(sent) - 50]
        for old_key in oldest_keys:
            sent.pop(old_key, None)
    history_event(state, "operator_notification", notification_key=key, message=message[:220])


def record_worker_bus_event_delta(run_dir: Path, event: dict[str, Any]) -> None:
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    worker = str(event.get("worker_id") or "unknown")
    entry = {
        "schema_version": "ai_quality_log_entry.v1",
        "entry_id": str(uuid.uuid4()),
        "created_at_utc": utc_now(),
        "run_id": run_dir.name,
        "audit_family": "camino_a_worker_bus",
        "artifact": {
            "file": str(event.get("archive_dir") or "NO_CONSTA"),
            "version": str(result.get("candidate_sha256") or event.get("job_id") or "NO_CONSTA"),
        },
        "auditor": {
            "model": str(result.get("model_id") or "NO_CONSTA"),
            "provider": str(result.get("provider_id") or result.get("worker_id") or worker),
            "route": str(result.get("route") or "worker_bus"),
            "cost_class": str(result.get("cost_class") or "manual_or_external"),
            "worker_id": worker,
        },
        "finding": {
            "id": f"worker_bus_{event.get('status')}_{event.get('job_id')}",
            "type": "meta",
            "severity": "info" if event.get("status") == "accepted" else "warning",
            "summary": f"Worker {worker} output {event.get('status')}",
        },
        "adjudication": {"final_status": "PENDIENTE"},
        "write_actor": {"name": "watcher_supervisor"},
        "details": json_safe(event),
    }
    path = run_dir / "90_QUALITY_LOG_DELTA" / (
        f"{utc_now_compact()}_{safe_slug(worker)}_{safe_slug(str(event.get('job_id')))}_{entry['entry_id'][:8]}.entry.json"
    )
    write_json(path, entry)


# H-04/CONC-HIGH-05 + CR-HIGH-02 + M-10/CR-MED-05: process_worker_bus con reconcile + recorded_ids
def process_worker_bus(run_dir: Path, state: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Procesa eventos del worker bus. Idempotente post-crash vía reconcile_recorded_outputs.

    1. Reconcilia bundles ACCEPTED/REJECTED/STALE cuyo evento se perdió en crash.
    2. Escanea OUT/ para eventos frescos.
    3. Para cada evento nuevo (job_id no en recorded_ids):
       a. Escribe delta en 90_QUALITY_LOG_DELTA (durable)
       b. Agrega job_id a recorded_ids (en memoria)
       c. Persiste state inmediatamente (ventana de re-emisión <= 1 evento)
    """
    from scripts.camino_a_worker_bus import reconcile_recorded_outputs

    recorded = set(state.setdefault("worker_bus_recorded_ids", []))
    current_sha = state.get("current_candidate_sha256")
    # Reconciliar eventos perdidos (bundles en ACCEPTED/REJECTED sin registro en state)
    reconciled_events = reconcile_recorded_outputs(run_dir, recorded_job_ids=recorded)
    fresh_events = scan_worker_outputs(run_dir)
    events = reconciled_events + fresh_events
    if not events:
        return state, []
    results = state.setdefault("worker_bus_results", [])
    newly_recorded = 0
    for event in events:
        job_id = str(event.get("job_id"))
        if job_id in recorded:
            continue
        summary = {
            "worker_id": event.get("worker_id"),
            "job_id": job_id,
            "status": event.get("status"),
            "observed_at_utc": event.get("observed_at_utc"),
            "archive_dir": event.get("archive_dir"),
            "stage": (event.get("result") or {}).get("stage") if isinstance(event.get("result"), dict) else None,
            "reconciled": bool(event.get("reconciled")),
            "stale": bool(event.get("stale")),
        }
        results.append(summary)
        # R10: RESIL-04 - limitar worker_bus_results a 200 entradas
        if len(results) > 200:
            state["worker_bus_results"] = results[-200:]
        record_worker_bus_event_delta(run_dir, event)
        history_event(state, "worker_bus_output_observed", **summary)
        if event.get("status") in {"rejected", "stale"}:
            state["worker_bus_intervention_required"] = True
            state["next_action_for_mariano"] = "revalidar_worker_bus_stale" if event.get("status") == "stale" else "revisar_worker_bus_rejected"
            notify_once(
                run_dir,
                state,
                f"worker_{event.get('status')}_{job_id}",
                "Camino A requiere revision",
                f"Salida {event.get('status')} {job_id} de {event.get('worker_id')}; revisar evidencia archivada.",
            )
        # Persistir el id INMEDIATAMENTE después del delta (ventana <= 1)
        recorded.add(job_id)
        newly_recorded += 1
        state["worker_bus_recorded_ids"] = sorted(recorded)
        state["worker_bus_completed_count"] = len(recorded)
        save_state(run_dir, state)
    return state, events


def migrate_state_defaults(run_dir: Path, state: dict[str, Any]) -> None:
    state.setdefault("primary_orchestrator", "gpt_5_5_web_via_drive")
    state.setdefault("primary_orchestrator_enabled", True)
    state.setdefault("primary_brain", True)
    state.setdefault("secondary_brain", True)
    state.setdefault("consolidator", True)
    state.setdefault("code_generator", True)
    state.setdefault("post_code_adversarial_auditor", True)
    state.setdefault("final_decider_until_bug0_mejoras0", True)
    state.setdefault("local_orchestrator_role", "state_machine_runner_drive_bus")
    state.setdefault("codex_enabled", False)
    state.setdefault("codex_required", False)
    state.setdefault("codex_role", "infrastructure_only_no_brain_no_patcher")
    state.setdefault("operation_mode", "codex_operator")
    state.setdefault("manual_terminal_supported", True)
    state.setdefault("manual_drop_folder", str(DEFAULT_DESKTOP_MANUAL_FOLDER))
    state.setdefault("gpt_drive_write_capability", "unknown")
    state.setdefault("gpt_api_actions_capability", "unknown")
    state.setdefault("manual_missing_policy", "open_incremental_inbox")
    state.setdefault("manual_audits_expected", 3)
    state.setdefault("manual_audits_override", False)
    state.setdefault("manual_window", "open_until_terminal")
    state.setdefault("manual_registry_version", "camino_a_manual_registry.v2")
    state.setdefault("manual_revision_required", False)
    state.setdefault("desktop_manual_inbox", str(DEFAULT_DESKTOP_MANUAL_FOLDER / run_dir.name / "INBOX"))
    state.setdefault("chat_manual_ingest_supported", True)
    state.setdefault("watcher_status", "inactive")
    state.setdefault("manual_codex_paste_allowed", "always_until_terminal")
    state.setdefault("manual_codex_paste_content", [
        "latest_gpt_generated_full_code",
        "latest_gpt_post_code_audit",
    ])
    state.setdefault("manual_codex_paste_policy", "only_materialize_drive_files_no_consolidation_no_decision_no_code_authoring")
    state.setdefault("cheap_api_audits_allowed_during_operation", True)
    state.setdefault("api_calls_allowed_during_infra_patch", False)
    state.setdefault("watch_gpt_output_supported", True)
    state.setdefault("watch_mode", "persistent_drive_and_manual_inbox")
    state.setdefault("watcher_heartbeat_seconds", WATCH_HEARTBEAT_MINUTES * 60)
    state.setdefault("watcher_poll_seconds", 10)
    state.setdefault("worker_bus_version", "camino_a_worker_bus.v1")
    state.setdefault("worker_bus_completed_count", 0)
    state.setdefault("worker_bus_results", [])
    state.setdefault("worker_bus_intervention_required", False)
    state.setdefault("notifications_sent", {})
    state.setdefault("real_improvements_policy", "all_real_improvements_must_be_implemented")
    state.setdefault("auto_audits_cycle1_status", state.get("cycle_1_status", "pending"))
    state.setdefault("gpt_primary_consolidation_status", "pending")
    state.setdefault("gpt_code_generation_status", "pending")
    state.setdefault("local_validation_status", "pending")
    state.setdefault("post_code_adversarial_audit_status", "pending")
    state.setdefault("gpt_post_code_audit_status", "pending")
    state.setdefault("current_candidate_version", state.get("candidate_version"))
    state.setdefault("current_candidate_sha256", state.get("candidate_sha256"))
    state.setdefault("iteration_number", 0)
    state.setdefault("history", [])
    state.setdefault("drive_bus_layout_version", "camino_a_stage1_v2")
    state.setdefault("primary_brain_mode", "automatic_provider_with_manual_gpt_compatible")
    state.setdefault("primary_brain_adapter_enabled", True)
    state.setdefault("primary_brain_job_attempts", {})
    state.setdefault("primary_brain_status", "idle")
    state["run_dir"] = str(run_dir)


def initial_state(run_dir: Path, candidate: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    state = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "created_at": utc_now(),
        "candidate_name": args.candidate_name,
        **candidate,
        "drive_bus_root": str(Path(args.drive_bus_root).expanduser().resolve()),
        "manual_folder": str(Path(args.manual_folder).expanduser().resolve()),
        "manual_drop_folder": str(DEFAULT_DESKTOP_MANUAL_FOLDER),
        "manual_audits_required": True,
        "manual_missing_policy": "open_incremental_inbox",
        "manual_audits_expected": 3,
        "manual_audits_received": 0,
        "manual_window": "open_until_terminal",
        "manual_registry_version": "camino_a_manual_registry.v2",
        "manual_revision_required": False,
        "desktop_manual_inbox": str(DEFAULT_DESKTOP_MANUAL_FOLDER / run_dir.name / "INBOX"),
        "chat_manual_ingest_supported": True,
        "manual_audits_override": False,
        "manual_audits_reuse_on_later_iterations": True,
        "cycle_1_scope": "manuals_plus_cheap_intermediate",
        "cycle_2_scope": "expensive_vertex_disabled_until_gpt_closure",
        "ready_for_expensive_vertex_audits": False,
        "ready_for_claude_stage": False,
        "ready_for_glm_external": False,
        "primary_orchestrator": "gpt_5_5_web_via_drive",
        "primary_brain_mode": "automatic_provider_with_manual_gpt_compatible",
        "primary_brain_adapter_enabled": True,
        "primary_brain_job_attempts": {},
        "primary_brain_status": "idle",
        "primary_orchestrator_enabled": True,
        "primary_brain": True,
        "secondary_brain": True,
        "consolidator": True,
        "code_generator": True,
        "post_code_adversarial_auditor": True,
        "final_decider_until_bug0_mejoras0": True,
        "local_orchestrator_role": "state_machine_runner_drive_bus",
        "codex_enabled": False,
        "codex_required": False,
        "codex_role": "infrastructure_only_no_brain_no_patcher",
        "operation_mode": "codex_operator",
        "manual_terminal_supported": True,
        "gpt_drive_write_capability": "unknown",
        "gpt_api_actions_capability": "unknown",
        "watcher_status": "inactive",
        "manual_codex_paste_allowed": "always_until_terminal",
        "manual_codex_paste_content": [
            "latest_gpt_generated_full_code",
            "latest_gpt_post_code_audit",
        ],
        "manual_codex_paste_policy": "only_materialize_drive_files_no_consolidation_no_decision_no_code_authoring",
        "cheap_api_audits_allowed_during_operation": True,
        "api_calls_allowed_during_infra_patch": False,
        "watch_gpt_output_supported": True,
        "watch_mode": "persistent_drive_and_manual_inbox",
        "watcher_heartbeat_seconds": WATCH_HEARTBEAT_MINUTES * 60,
        "watcher_poll_seconds": 10,
        "real_improvements_policy": "all_real_improvements_must_be_implemented",
        "auto_audits_cycle1_status": "pending",
        "gpt_primary_consolidation_status": "pending",
        "gpt_code_generation_status": "pending",
        "local_validation_status": "pending",
        "post_code_adversarial_audit_status": "pending",
        "gpt_post_code_audit_status": "pending",
        "current_candidate_version": candidate["candidate_version"],
        "current_candidate_sha256": candidate["candidate_sha256"],
        "iteration_number": 0,
        "current_phase": "manual_window",
        "last_completed_step": None,
        "next_action_for_mariano": "cargar_auditorias_manuales_o_autorizar_avance_parcial",
        "child_runs": [],
        "history": [],
        "dry_run": bool(args.dry_run),
        "drive_bus_layout_version": "camino_a_stage1_v2",
    }
    history_event(state, "run_created", candidate_sha256=candidate["candidate_sha256"])
    return state


def list_relevant_files(run_dir: Path) -> list[str]:
    relevant: list[str] = []
    for dirname in [
        "00_CANDIDATE",
        "10_MANUAL_AUDITS",
        "11_MANUAL_CONTEXT_SNAPSHOT",
        "20_AUTO_AUDITS_RAW",
        "21_AUTO_AUDITS_PRECONSOLIDATED",
        "41_LOCAL_VALIDATION",
        "50_POST_CODE_ADVERSARIAL_AUDITS",
        "51_POST_CODE_AUDIT_PRECONSOLIDATED",
    ]:
        base = run_dir / dirname
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            relevant.append(str(path.relative_to(run_dir)))
    relevant.append(STATE_NAME)
    return relevant


def write_file_listing(run_dir: Path, out: Path) -> None:
    lines = ["# LISTADO_ARCHIVOS_RELEVANTES\n\n"]
    for item in list_relevant_files(run_dir):
        lines.append(f"- `{item}`\n")
    out.write_text("".join(lines), encoding="utf-8")


def manual_gate_open(state: dict[str, Any]) -> bool:
    received = int(state.get("manual_audits_received", 0))
    expected = int(state.get("manual_audits_expected", 3))
    return received >= expected or bool(state.get("manual_audits_override"))


def write_ready_for_mariano(run_dir: Path, state: dict[str, Any]) -> None:
    if not (manual_gate_open(state) and state.get("auto_audits_cycle1_status") == "complete"):
        return
    out = run_dir / "30_GPT_PRIMARY_INPUT"
    (out / "GPT_READY_FOR_MARIANO.md").write_text(
        "# GPT_READY_FOR_MARIANO\n\n"
        "AUDITORIAS AUTOMATICAS COMPLETAS.\n\n"
        "Abrir GPT-5.5. Indicarle que lea `30_GPT_PRIMARY_INPUT` y los directorios referenciados.\n"
        "GPT debe leer manuales + automaticas desde Drive, consolidar y, si corresponde, generar codigo completo.\n",
        encoding="utf-8",
    )
    (out / "GPT_PRIMARY_INPUT.READY").write_text("READY\n", encoding="utf-8")


def write_gpt_primary_input(run_dir: Path, state: dict[str, Any]) -> None:
    ensure_bus_dirs(run_dir)
    out = run_dir / "30_GPT_PRIMARY_INPUT"
    manifest = {
        "role": "gpt_primary_orchestrator_consolidator_code_generator",
        "candidate_sha256": state.get("current_candidate_sha256") or state.get("candidate_sha256"),
        "candidate_version": state.get("current_candidate_version") or state.get("candidate_version"),
        "iteration_number": state.get("iteration_number", 0),
        "input_dirs": {
            "candidate": "../00_CANDIDATE",
            "manual_audits": "../10_MANUAL_AUDITS",
            "manual_context_snapshot": "../11_MANUAL_CONTEXT_SNAPSHOT",
            "late_manual_review_requests": "../12_MANUAL_REVIEW_REQUESTS",
            "auto_audits_raw": "../20_AUTO_AUDITS_RAW",
            "auto_preconsolidated": "../21_AUTO_AUDITS_PRECONSOLIDATED",
            "state": "../cycle_state.json",
        },
        "required_output_dir": "../31_GPT_PRIMARY_OUTPUT",
        "required_outputs": [
            "CONSOLIDACION_GPT_PRIMARIA.md",
            "CONSOLIDACION_GPT_PRIMARIA.json",
            "OUTPUT_MANIFEST.json",
            "CONSOLIDACION_GPT_PRIMARIA.DONE",
        ],
        "allowed_status": ["bug0_mejoras0", "code_required", "blocked"],
        "required_improvement_policy": "Toda mejora tecnica real se implementa; solo cosmetica pura, downstream claro o diferimiento autorizado por Mariano pueden no bloquear.",
        "api_iteration_rule": "Si no hay bug0/mejoras0, GPT debe pedir API audits o justificar code_required_direct con evidencia suficiente.",
        "manual_audit_protocol": {
            "minimum_initial_count": state.get("manual_audits_expected", 3),
            "received_count": state.get("manual_audits_received", 0),
            "window": "open_until_terminal",
            "registry": "../10_MANUAL_AUDITS/MANUAL_AUDIT_INDEX.json",
            "late_audits_must_be_revalidated_against_current_candidate": True,
            "required_finding_statuses": ["persiste", "corregido_previamente", "duplicado", "no_reproducible", "pendiente"],
        },
        "codex_enabled": False,
        "codex_required": False,
    }
    write_json(out / "GPT_PRIMARY_INPUT_MANIFEST.json", manifest)
    (out / "CANDIDATE_SHA256.txt").write_text(str(manifest["candidate_sha256"]) + "\n", encoding="utf-8")
    write_file_listing(run_dir, out / "LISTADO_ARCHIVOS_RELEVANTES.md")
    (out / "INSTRUCCIONES_GPT_PRIMARIO.md").write_text(
        "# INSTRUCCIONES_GPT_PRIMARIO\n\n"
        "Rol: GPT-5.5 web es el orquestador lógico primario, consolidador y generador de código.\n"
        "Codex queda deshabilitado como cerebro o parcheador: solo mueve archivos, valida localmente y mantiene estado.\n\n"
        "Camino A automatico: GPT debe escribir sus salidas en Drive. Mariano puede pegar o adjuntar auditorias manuales "
        "en el chat de Codex durante toda la corrida; Codex solo las materializa e indexa como evidencia independiente. "
        "El watcher detecta `.DONE`, importa auditorias manuales tardias y el orquestador continua.\n"
        "Fallback: solo si GPT no puede escribir en Drive, el watcher falla o Mariano necesita avisar que GPT termino, "
        "Mariano puede materializar en Codex/orquestador la ultima version completa generada por GPT o la ultima auditoria "
        "post-codigo. Codex solo debe guardarla en Drive, generar JSON/.DONE si falta, validar SHA, correr py_compile/self-test "
        "y actualizar estado; no consolida, no decide bugs/mejoras y no cierra bug0/mejoras0.\n\n"
        "Leer el candidato, las auditorías manuales individuales si existen, auditorías automáticas baratas/intermedias, "
        "preconsolidación local y `cycle_state.json`.\n\n"
        "Las auditorías manuales deben preservar identidad propia: `audit_id`, archivo fuente, autor/modelo si consta, "
        "fecha de recepción, hash SHA-256, hallazgos propios, estado individual y relación con otras auditorías. "
        "No fusionarlas antes de que el consolidador vea su procedencia.\n\n"
        "La ventana manual permanece abierta hasta el estado terminal. Si llega una auditoria tardia, validar cada hallazgo "
        "contra el candidato vigente y marcarlo `persiste`, `corregido_previamente`, `duplicado`, `no_reproducible` o `pendiente`. "
        "Una auditoria vieja no se descarta por antiguedad.\n\n"
        "No reescribir por estilo. No hacer auditoría jurídica. No inventar SHA. No afirmar tests no ejecutados. "
        "No pedir Claude, GLM externo ni Vertex caro en esta etapa.\n\n"
        "Regla absoluta sobre mejoras: toda mejora tecnica real se implementa. No diferir por costo, refactor, "
        "rediseño, riesgo o complejidad. Solo no bloquean la cosmetica pura, responsabilidad clara downstream "
        "o diferimiento explicito autorizado por Mariano.\n\n"
        "Si no hay `bug0_mejoras0`, GPT debe elegir una ruta: pedir auditorias/API baratas/intermedias con "
        "`API_AUDIT_REQUESTS.json`, o declarar `api_audits_required=false`, `code_generation_allowed_now=true` "
        "y `reason=evidencia_suficiente_y_no_hay_duda_relevante`.\n\n"
        "Escribir en `../31_GPT_PRIMARY_OUTPUT/`:\n"
        "- `CONSOLIDACION_GPT_PRIMARIA.md`\n"
        "- `CONSOLIDACION_GPT_PRIMARIA.json`\n"
        "- `CONSOLIDACION_GPT_PRIMARIA.DONE`\n\n"
        "JSON mínimo requerido:\n"
        "`stage`, `candidate_sha256`, `status`, `bugs`, `mejoras`, `falsos_positivos`, "
        "`deudas_diferidas`, `code_required`, `next_version`, `next_action`.\n\n"
        "Valores válidos de `status`: `bug0_mejoras0`, `code_required`, `blocked`.\n"
        "Si `status=code_required`, generar después un archivo completo nuevo en `../40_GPT_CODE_OUTPUT/` "
        "junto con `GPT_CODE_OUTPUT.json`, changelog/tests y `GPT_CODE_OUTPUT.DONE`.\n",
        encoding="utf-8",
    )
    write_ready_for_mariano(run_dir, state)


def write_gpt_post_code_input(run_dir: Path, state: dict[str, Any]) -> None:
    ensure_bus_dirs(run_dir)
    out = run_dir / "60_GPT_ITERATION_INPUT"
    manifest = {
        "role": "gpt_primary_post_code_adversarial_consolidator",
        "candidate_sha256": state.get("current_candidate_sha256"),
        "candidate_version": state.get("current_candidate_version"),
        "iteration_number": state.get("iteration_number", 0),
        "input_dirs": {
            "candidate": "../00_CANDIDATE",
            "local_validation": "../41_LOCAL_VALIDATION",
            "post_code_raw": "../50_POST_CODE_ADVERSARIAL_AUDITS",
            "post_code_preconsolidated": "../51_POST_CODE_AUDIT_PRECONSOLIDATED",
            "state": "../cycle_state.json",
        },
        "required_output_dir": "../61_GPT_ITERATION_OUTPUT",
        "required_outputs": [
            "AUDITORIA_ADVERSARIAL_POST_CODIGO.md",
            "AUDITORIA_ADVERSARIAL_POST_CODIGO.json",
            "OUTPUT_MANIFEST.json",
            "AUDITORIA_ADVERSARIAL_POST_CODIGO.DONE",
        ],
        "allowed_status": ["bug0_mejoras0", "code_required", "blocked"],
        "required_closure_shape": {
            "verdict": "bug0_mejoras0",
            "bugs": [],
            "mejoras": [],
            "cosmeticas_no_bloqueantes": [],
            "deudas_diferidas_autorizadas": [],
        },
        "codex_enabled": False,
        "codex_required": False,
    }
    write_json(out / "GPT_POST_CODE_INPUT_MANIFEST.json", manifest)
    write_file_listing(run_dir, out / "LISTADO_ARCHIVOS_RELEVANTES.md")
    (out / "INSTRUCCIONES_GPT_POST_CODIGO.md").write_text(
        "# INSTRUCCIONES_GPT_POST_CODIGO\n\n"
        "Consolidar la auditoría adversarial posterior al código generado por GPT. "
        "El objetivo es iterar hasta `bug0_mejoras0` razonable.\n\n"
        "Camino A automatico: GPT escribe estos archivos en Drive y el watcher detecta `.DONE`. "
        "Pegado manual a Codex/orquestador solo es fallback si falla escritura Drive o watcher.\n\n"
        "Escribir en `../61_GPT_ITERATION_OUTPUT/`:\n"
        "- `AUDITORIA_ADVERSARIAL_POST_CODIGO.md`\n"
        "- `AUDITORIA_ADVERSARIAL_POST_CODIGO.json`\n"
        "- `AUDITORIA_ADVERSARIAL_POST_CODIGO.DONE`\n\n"
        "JSON mínimo: `stage`, `candidate_version`, `candidate_sha256`, `verdict`, `bugs`, `mejoras`, "
        "`falsos_positivos`, `deudas_diferidas`, `iterations_reviewed`, `next_version`, `next_action`.\n"
        "Valores válidos de `verdict`: `bug0_mejoras0`, `code_required`, `blocked`.\n"
        "Para cerrar, `bugs` y `mejoras` deben estar vacios. Si existe una mejora tecnica real pendiente, "
        "el verdict debe ser `code_required` con reason `mejora_real_pendiente`.\n"
        "Si no hay bug0/mejoras0, pedir APIs adicionales o justificar codigo directo con evidencia suficiente.\n"
        "Si queda `code_required`, GPT debe volver a producir código completo en `../40_GPT_CODE_OUTPUT/`.\n",
        encoding="utf-8",
    )


def upsert_manifest_auditoria(manifest_path: Path, adv_path: Path) -> None:
    manifest = read_json(manifest_path, {})
    manifest["auditoria_adversarial_md"] = "auditoria_adversarial.md"
    files = manifest.setdefault("files", [])
    if isinstance(files, list):
        files[:] = [item for item in files if isinstance(item, dict) and item.get("name") != "auditoria_adversarial.md"]
        files.append({
            "name": "auditoria_adversarial.md",
            "sha256": sha256_file(adv_path),
            "size_bytes": adv_path.stat().st_size,
            "reason": "auditoria_adversarial",
        })
    write_json(manifest_path, manifest)


def refresh_manual_audit_request(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    ensure_bus_dirs(run_dir)
    manual_folder = Path(state["manual_folder"])
    candidate_file = Path(state["candidate_file"]).name
    script_version = str(state.get("current_candidate_version") or state.get("candidate_version") or "")
    candidate_sha = str(state.get("current_candidate_sha256") or state.get("candidate_sha256") or "")
    adv_manual = write_auditoria_adversarial(manual_folder, candidate_file, script_version, candidate_sha)
    manifest_path = manual_folder / "MANIFEST_AUDITORIA_MANUAL.json"
    if manifest_path.exists():
        upsert_manifest_auditoria(manifest_path, adv_manual)
    for dirname in ["11_MANUAL_CONTEXT_SNAPSHOT", "30_GPT_PRIMARY_INPUT"]:
        target = run_dir / dirname
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(adv_manual, target / "auditoria_adversarial.md")
        if manifest_path.exists():
            shutil.copy2(manifest_path, target / "MANIFEST_AUDITORIA_MANUAL.json")
    state.update({
        "manual_audit_request_file": "auditoria_adversarial.md",
        "manual_audit_request_generated": True,
    })
    history_event(state, "manual_audit_request_refreshed", file="auditoria_adversarial.md")
    save_state(run_dir, state)
    return state


def prepare_manual_inbox(run_dir: Path, *, open_window: bool) -> Path:
    state = load_state(run_dir)
    inbox = Path(state.get("desktop_manual_inbox") or (DEFAULT_DESKTOP_MANUAL_FOLDER / run_dir.name / "INBOX"))
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox.parent / "PROCESSED").mkdir(parents=True, exist_ok=True)
    legacy_inbox = Path(state.get("manual_folder") or DEFAULT_MANUAL_FOLDER) / run_dir.name / "INBOX"
    legacy_inbox.mkdir(parents=True, exist_ok=True)
    (legacy_inbox.parent / "PROCESSED").mkdir(parents=True, exist_ok=True)
    instructions = inbox.parent / "LEEME.txt"
    instructions.write_text(
        "Pegue aqui auditorias manuales .md o .txt. El watcher las importa sin cerrar la ventana manual.\n"
        "Tambien puede adjuntarlas directamente en el chat de Codex; Codex ejecutara --ingest-manual.\n",
        encoding="utf-8",
    )
    state["desktop_manual_inbox"] = str(inbox)
    state["manual_window"] = "open_until_terminal"
    save_state(run_dir, state)
    if open_window and sys.platform == "darwin":
        subprocess.run(["open", str(inbox)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return inbox


def watcher_launch_agent_label(run_dir: Path) -> str:
    return "com.mariano.caminoa." + safe_slug(run_dir.name.lower())


def install_watcher_launch_agent(run_dir: Path) -> Path:
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    label = watcher_launch_agent_label(run_dir)
    plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"
    log_dir = run_dir / "01_STATE"
    payload = {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            str(Path(__file__).resolve()),
            "--resume",
            str(run_dir),
            "--watch-gpt-output",
            "--watch-interval-seconds",
            "10",
            "--watch-timeout-minutes",
            "0",
        ],
        "RunAtLoad": True,
        # H-08/CR-HIGH-04 + R2-CR-06 + R3-04 + R4-02: relanza en crash y en exit non-zero,
        # pero con ThrottleInterval=30 para no saturar. SystemExit("msg") (exit 1) SÍ relanza
        # (deseable para acquire_watcher_lock falla transitoria). SystemExit() puro (exit 0) no relanza.
        "KeepAlive": {"SuccessfulExit": False, "Crashed": True},
        "ThrottleInterval": 30,
        "ExitTimeOut": 300,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "watcher.stdout.log"),
        "StandardErrorPath": str(log_dir / "watcher.stderr.log"),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
            "PYTHONUNBUFFERED": "1",
        },
    }
    with plist_path.open("wb") as f:
        plistlib.dump(payload, f, sort_keys=True)
    if sys.platform == "darwin":
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cp = subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], text=True, capture_output=True)
        if cp.returncode != 0:
            raise SystemExit(f"watcher_launch_agent_install_failed:{cp.stderr.strip()[:300]}")
    state = load_state(run_dir)
    state.update({
        "watcher_service": "launch_agent",
        "watcher_service_label": label,
        "watcher_service_plist": str(plist_path),
        "watcher_status": "active",
    })
    history_event(state, "watcher_service_installed", label=label)
    save_state(run_dir, state)
    return plist_path


def migrate_stage1_run(run_dir: Path, *, install_service: bool, open_window: bool) -> dict[str, Any]:
    state = load_state(run_dir)
    registry = load_manual_registry(run_dir)
    write_manual_index_artifacts(run_dir, registry)
    state.update({
        "manual_audits_received": int(registry.get("manual_audits_received", 0)),
        "manual_window": "open_until_terminal",
        "manual_missing_policy": "open_incremental_inbox",
        "manual_registry_version": "camino_a_manual_registry.v2",
        "manual_codex_paste_allowed": "always_until_terminal",
        "chat_manual_ingest_supported": True,
        "watch_mode": "persistent_drive_and_manual_inbox",
        "drive_bus_layout_version": "camino_a_stage1_v2",
        "primary_brain_mode": "automatic_provider_with_manual_gpt_compatible",
        "primary_brain_adapter_enabled": True,
        "primary_brain_job_attempts": state.get("primary_brain_job_attempts", {}),
        "primary_brain_status": state.get("primary_brain_status", "idle"),
    })
    if state.get("current_phase") == "waiting_gpt_output":
        state["current_phase"] = "waiting_gpt_primary_output"
        state["next_action_for_mariano"] = "esperar_o_materializar_CONSOLIDACION_GPT_PRIMARIA"
    history_event(state, "stage1_contract_migrated", manual_audits_received=state["manual_audits_received"])
    save_state(run_dir, state)
    prepare_worker_bus(run_dir)
    prepare_manual_inbox(run_dir, open_window=open_window)
    if install_service:
        install_watcher_launch_agent(run_dir)
    return load_state(run_dir)


def start(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser().resolve()
    manual_folder = Path(args.manual_folder).expanduser().resolve()
    drive_bus_root = Path(args.drive_bus_root).expanduser().resolve()
    candidate = validate_candidate(input_path, args.candidate_name, args.target_version, dry_run=args.dry_run)
    run_dir = make_run_dir(drive_bus_root)

    candidate_file = Path(candidate["candidate_file"])
    shutil.copy2(candidate_file, run_dir / "00_CANDIDATE" / candidate_file.name)
    checksum = run_dir / "00_CANDIDATE" / f"checksums_v{args.target_version.replace('.', '_')}.txt"
    checksum.write_text(f"{candidate['candidate_sha256']}  {candidate_file.name}\n", encoding="utf-8")

    manifest = prepare_manual_audit_folder(
        input_path,
        f"Auditoria manual obligatoria inicial para {args.candidate_name} v{args.target_version}.",
        clean=True,
    )
    previous = manual_folder / "AUDITORIAS_PREVIAS_CONSOLIDADAS.md"
    if not previous.exists():
        previous.write_text(
            "# Auditorías previas consolidadas\n\n"
            "No se detectaron auditorías previas en el input inicial.\n",
            encoding="utf-8",
        )
    copy_tree_files(manual_folder, run_dir / "11_MANUAL_CONTEXT_SNAPSHOT")
    prepare_desktop_manual_inbox(run_dir)

    state = initial_state(run_dir, candidate, args)
    state["manual_manifest_files"] = manifest.get("files", [])
    state["manual_audit_request_file"] = "auditoria_adversarial.md"
    state["manual_audit_request_generated"] = True
    write_gpt_primary_input(run_dir, state)
    save_state(run_dir, state)
    refresh_manual_audit_request(run_dir, state)
    inbox = prepare_manual_inbox(run_dir, open_window=not args.no_open_manual_window and not args.dry_run)
    if not args.no_start_watcher and not args.dry_run:
        install_watcher_launch_agent(run_dir)

    print("RUN_DIR:", run_dir)
    print("VENTANA MANUAL ABIERTA.")
    print("INBOX_MANUAL:", inbox)
    print("Cargá al menos 3 auditorías manuales .md/.txt; la ventana queda abierta hasta el cierre terminal.")
    print("GPT primario consolida y genera código por Drive.")
    print("Codex queda solo como infraestructura.")
    print("No Vertex. No Claude. No GLM externo.")
    print("next_action_for_mariano:", state["next_action_for_mariano"])
    return 0


def copy_manual(src_raw: str, dst: Path) -> dict[str, Any]:
    src = Path(src_raw).expanduser().resolve()
    if not src.is_file() or src.suffix.lower() != ".md":
        raise SystemExit(f"manual_md_no_valida:{src}")
    # R10: PATH-03 - rechazar symlinks en source
    if src.is_symlink():
        raise SystemExit(f"manual_md_symlink_rejected:{src}")
    shutil.copy2(src, dst)
    return {"name": dst.name, "source": str(src), "sha256": sha256_file(dst), "size_bytes": dst.stat().st_size}


def ingest_manual_paths(run_dir: Path, source_paths: list[str], *, source_label: str) -> dict[str, Any]:
    state = load_state(run_dir)
    ingested: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for src_raw in source_paths:
        src = Path(src_raw).expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"manual_no_valida:{src}")
        record, added = materialize_manual_audit(
            run_dir,
            src,
            source_label=source_label,
        )
        if added:
            ingested.append(record)
        else:
            duplicates.append(record)
    registry = load_manual_registry(run_dir)
    write_manual_index_artifacts(run_dir, registry)
    state["manual_audits_received"] = int(registry.get("manual_audits_received", len(ingested)))
    state["manual_window"] = "open_until_terminal"
    was_late = state.get("auto_audits_cycle1_status") == "complete" or state.get("gpt_primary_consolidation_status") not in {"pending", None}
    if ingested and was_late:
        invalidate_downstream_after_manual_update(run_dir, state, ingested)
        event = "late_manual_audits_ingested"
    elif manual_gate_open(state):
        state.update({
            "current_phase": "cycle_1_auto_ready" if state.get("auto_audits_cycle1_status") == "pending" else state.get("current_phase"),
            "last_completed_step": "manual_audits_minimum_reached",
            "next_action_for_mariano": "continuar_ciclo_1_automatico" if state.get("auto_audits_cycle1_status") == "pending" else state.get("next_action_for_mariano"),
        })
        event = "manual_audits_ingested_gate_open"
    else:
        state["next_action_for_mariano"] = "agregar_auditorias_manuales"
        event = "manual_audits_ingested_gate_pending"
    history_event(
        state,
        event,
        audit_ids=[item.get("audit_id") for item in ingested],
        files=[item.get("destination_name") or item.get("source_name") for item in ingested],
        duplicates=[item.get("source_name") for item in duplicates],
        manual_audits_received=state["manual_audits_received"],
    )
    write_gpt_primary_input(run_dir, state)
    save_state(run_dir, state)
    return state


def incorporate_manuals(run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    return ingest_manual_paths(
        run_dir,
        [args.manual_1, args.manual_2, args.manual_3],
        source_label="manual_chat_input",
    )


def latest_parallel_run(before: set[str]) -> Path:
    candidates = [p for p in SALIDAS.glob("*_fase1_parallel") if p.is_dir() and p.name not in before]
    if not candidates:
        raise SystemExit("runner_no_genero_run_fase1_parallel")
    return max(candidates, key=lambda p: p.name)


def mirror_runner_output(child: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in child.iterdir():
        # R10: PATH-02 -拒绝符号链接
        if item.is_symlink():
            continue
        dst = target / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, dst)


def run_preconsolidation(run_dir: Path, raw_dir: Path, *, out_dir_name: str, base_name: str, cycle: int, dry_run: bool) -> None:
    if dry_run:
        print("DRY_RUN: preconsolidacion automatica no ejecutada")
        return
    out_dir = run_dir / out_dir_name
    run([
        sys.executable,
        str(ROOT / "scripts" / "preconsolidate_auto_findings.py"),
        "--raw-dir",
        str(raw_dir),
        "--out-dir",
        str(out_dir),
        "--cycle",
        str(cycle),
        "--base-name",
        base_name,
    ])


def run_runner_to_bus(run_dir: Path, state: dict[str, Any], *, raw_dir_name: str, profile: str, max_workers: str, dry_run: bool) -> Path:
    before = {p.name for p in SALIDAS.glob("*_fase1_parallel") if p.is_dir()}
    cmd = [
        sys.executable,
        str(ROOT / "auditor_biblio_parallel.py"),
        "--input",
        state["candidate_path"],
        "--profile",
        profile,
        "--allow-paid",
        "--max-workers",
        max_workers,
        "--manual-audits-received",
        str(state.get("manual_audits_received", 0)),
    ]
    if dry_run:
        cmd.append("--dry-run-smoke")
    run(cmd)
    child = latest_parallel_run(before)
    raw_dir = run_dir / raw_dir_name
    mirror_runner_output(child, raw_dir)
    run([sys.executable, str(ROOT / "scripts" / "check_run_providers.py"), "--run-dir", str(raw_dir)])
    state.setdefault("child_runs", []).append({
        "profile": profile,
        "runner_run_dir": str(child),
        "bus_raw_dir": str(raw_dir),
        "dry_run": dry_run,
    })
    return raw_dir


def run_cycle1(run_dir: Path, state: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    if not manual_gate_open(state):
        state.update({
            "manual_missing_policy": "ask_or_wait",
            "manual_window": "waiting_user_decision",
            "next_action_for_mariano": "cargar_auditorias_manuales_o_autorizar_avance_parcial",
        })
        save_state(run_dir, state)
        raise SystemExit("manuales_incompletas_no_correr_ciclo_1")
    state.update({
        "auto_audits_cycle1_status": "running",
        "current_phase": "cycle_1_auto_running",
        "ready_for_expensive_vertex_audits": False,
        "ready_for_claude_stage": False,
    })
    save_state(run_dir, state)
    raw_dir = run_runner_to_bus(run_dir, state, raw_dir_name="20_AUTO_AUDITS_RAW", profile="fused_no_gemini", max_workers="5", dry_run=dry_run)
    run_preconsolidation(run_dir, raw_dir, out_dir_name="21_AUTO_AUDITS_PRECONSOLIDATED", base_name="AUTO_PRECONSOLIDACION", cycle=1, dry_run=dry_run)
    state.update({
        "auto_audits_cycle1_status": "complete",
        "gpt_primary_consolidation_status": "waiting",
        "current_phase": "waiting_gpt_primary_output",
        "last_completed_step": "cycle_1_auto_raw_ready",
        "next_action_for_mariano": "abrir_30_GPT_PRIMARY_INPUT_en_GPT_5_5_web_y_guardar_31_GPT_PRIMARY_OUTPUT",
    })
    history_event(state, "cycle1_auto_audits_ready", dry_run=dry_run)
    write_gpt_primary_input(run_dir, state)
    save_state(run_dir, state)
    return state


def validate_json_output(
    run_dir: Path,
    out_dir: str,
    stem: str,
    expected_stage: str | None,
    state_sha_key: str = "current_candidate_sha256",
    *,
    status_field: str = "status",
) -> dict[str, Any]:
    out = run_dir / out_dir
    done = out / f"{stem}.DONE"
    data_path = out / f"{stem}.json"
    if not done.exists():
        raise SystemExit(f"gpt_output_done_no_existe:{done}")
    state = load_state(run_dir)
    expected_sha = state.get(state_sha_key) or state.get("candidate_sha256")
    validate_output_manifest(
        run_dir, out_dir,
        ("OUTPUT_MANIFEST.json", f"{stem}.MANIFEST.json", f"{stem}_MANIFEST.json", "MANIFEST.json"),
        expected_stage=expected_stage,
        expected_candidate_sha256=expected_sha,
        required_files=(f"{stem}.json",),
        done_name=f"{stem}.DONE",
    )
    data = read_json(data_path, None)
    if not isinstance(data, dict):
        raise SystemExit(f"gpt_output_json_invalido:{data_path}")
    if str(data.get("candidate_sha256") or "").lower() != str(expected_sha).lower():
        raise SystemExit(f"gpt_output_candidate_sha256_no_coincide:{data.get('candidate_sha256')} != {expected_sha}")
    if expected_stage and data.get("stage") not in {expected_stage, None}:
        raise SystemExit(f"gpt_output_stage_invalido:{data.get('stage')}")
    if data.get(status_field) not in {"bug0_mejoras0", "code_required", "blocked"}:
        raise SystemExit(f"gpt_output_status_invalido:{status_field}={data.get(status_field)}")
    return data


def api_route_satisfied(run_dir: Path, out_dir: str, data: dict[str, Any], request_name: str) -> bool:
    if data.get("api_audits_required") is False and data.get("code_generation_allowed_now") is True:
        return str(data.get("reason")) == "evidencia_suficiente_y_no_hay_duda_relevante"
    if data.get("api_audits_required") is True and isinstance(data.get("requests"), list):
        return True
    request_path = run_dir / out_dir / request_name
    if request_path.exists():
        request = read_json(request_path, {})
        return bool(request.get("api_audits_required") and isinstance(request.get("requests"), list))
    return False


def require_api_or_direct_code_route(run_dir: Path, out_dir: str, data: dict[str, Any], request_name: str) -> None:
    status = data.get("status", data.get("verdict"))
    if status == "bug0_mejoras0" or status == "blocked":
        return
    if not api_route_satisfied(run_dir, out_dir, data, request_name):
        raise SystemExit(
            "gpt_output_sin_ruta_api_o_codigo_directo: se requiere API_AUDIT_REQUESTS "
            "o api_audits_required=false + code_generation_allowed_now=true + reason=evidencia_suficiente_y_no_hay_duda_relevante"
        )


def wait_for_output(validate_fn, timeout_seconds: int) -> dict[str, Any]:
    start_time = time.monotonic()
    while True:
        try:
            return validate_fn()
        except SystemExit:
            if timeout_seconds <= 0 or time.monotonic() - start_time >= timeout_seconds:
                raise
            time.sleep(5)


def wait_gpt_primary_output(run_dir: Path, *, timeout_seconds: int = 0) -> dict[str, Any]:
    data = wait_for_output(
        lambda: validate_json_output(run_dir, "31_GPT_PRIMARY_OUTPUT", "CONSOLIDACION_GPT_PRIMARIA", "gpt_primary_consolidation"),
        timeout_seconds,
    )
    state = load_state(run_dir)
    status = data["status"]
    require_api_or_direct_code_route(run_dir, "31_GPT_PRIMARY_OUTPUT", data, "API_AUDIT_REQUESTS.json")
    if status == "bug0_mejoras0":
        state.update({
            "gpt_primary_consolidation_status": "complete",
            "gpt_code_generation_status": "not_required",
            "post_code_adversarial_audit_status": "ready",
            "current_phase": "post_code_adversarial_ready",
            "last_completed_step": "gpt_primary_bug0_mejoras0",
            "next_action_for_mariano": "correr_auditoria_adversarial_post_codigo_o_cierre_gpt_si_corresponde",
        })
    elif status == "code_required":
        state.update({
            "gpt_primary_consolidation_status": "complete",
            "gpt_code_generation_status": "waiting",
            "current_phase": "waiting_gpt_code_output",
            "last_completed_step": "gpt_primary_code_required",
            "next_action_for_mariano": "guardar_codigo_completo_en_40_GPT_CODE_OUTPUT",
        })
    else:
        state.update({
            "gpt_primary_consolidation_status": "failed",
            "current_phase": "blocked",
            "next_action_for_mariano": "revisar_bloqueo_gpt_primario",
        })
    history_event(state, "gpt_primary_output_received", status=status)
    save_state(run_dir, state)
    return state


def wait_gpt_code_output(run_dir: Path, *, timeout_seconds: int = 0) -> dict[str, Any]:
    def validate() -> dict[str, Any]:
        out = run_dir / "40_GPT_CODE_OUTPUT"
        done = out / "GPT_CODE_OUTPUT.DONE"
        data_path = out / "GPT_CODE_OUTPUT.json"
        if not done.exists():
            raise SystemExit(f"gpt_code_done_no_existe:{done}")
        state = load_state(run_dir)
        expected_sha = state.get("current_candidate_sha256")
        validate_output_manifest(
            run_dir, "40_GPT_CODE_OUTPUT",
            ("OUTPUT_MANIFEST.json", "GPT_CODE_OUTPUT.MANIFEST.json", "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json"),
            expected_stage="gpt_code_generation",
            expected_candidate_sha256=expected_sha,
            required_files=("GPT_CODE_OUTPUT.json",),
            done_name="GPT_CODE_OUTPUT.DONE",
        )
        data = read_json(data_path, None)
        if not isinstance(data, dict):
            raise SystemExit(f"gpt_code_json_invalido:{data_path}")
        if str(data.get("source_candidate_sha256") or "").lower() != str(expected_sha).lower():
            raise SystemExit("gpt_code_source_sha256_no_coincide")
        # M-02/SEG-MED-02: re-validar generated_file para prevenir path traversal post-materialización
        from scripts.camino_a_worker_bus import assert_safe_generated_name
        try:
            generated_name = assert_safe_generated_name(data.get("generated_file"))
        except ValueError as exc:
            raise SystemExit(f"gpt_code_generated_file_invalid:{exc}")
        generated = out / generated_name
        if generated.is_symlink() or not generated.is_file():
            raise SystemExit(f"gpt_code_generated_file_no_existe:{generated}")
        validate_output_manifest(
            run_dir, "40_GPT_CODE_OUTPUT",
            ("OUTPUT_MANIFEST.json", "GPT_CODE_OUTPUT.MANIFEST.json", "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json"),
            expected_stage="gpt_code_generation",
            expected_candidate_sha256=expected_sha,
            required_files=("GPT_CODE_OUTPUT.json", generated_name),
            done_name="GPT_CODE_OUTPUT.DONE",
        )
        if data.get("generated_file_sha256") and str(data.get("generated_file_sha256")).lower() != sha256_file(generated).lower():
            raise SystemExit("gpt_code_generated_file_sha256_no_coincide")
        return data

    data = wait_for_output(validate, timeout_seconds)
    state = load_state(run_dir)
    state.update({
        "gpt_code_generation_status": "complete",
        "current_phase": "local_validation_ready",
        "last_completed_step": "gpt_code_output_received",
        "next_action_for_mariano": "ejecutar_validacion_local",
    })
    history_event(state, "gpt_code_output_received", generated_file=data.get("generated_file"))
    save_state(run_dir, state)
    return state


def validate_gpt_code(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    data = read_json(run_dir / "40_GPT_CODE_OUTPUT" / "GPT_CODE_OUTPUT.json", {})
    # M-02/SEG-MED-02: re-validar generated_file antes de ejecutarlo
    from scripts.camino_a_worker_bus import assert_safe_generated_name
    try:
        generated_name = assert_safe_generated_name(data.get("generated_file"))
    except ValueError as exc:
        # R2-CR-03: mutar estado PRIMERO (durable ante crash del propio archive), luego archivar
        state.update({"local_validation_status": "failed", "gpt_code_generation_status": "failed",
                      "current_phase": "failed_waiting_manual_output",
                      "next_action_for_mariano": "archivar_40_GPT_CODE_OUTPUT_a_mano"})
        history_event(state, "local_validation_failed_invalid_name", error=safe_error_text(exc))
        save_state(run_dir, state)
        try:
            archive_output_dir(run_dir, "40_GPT_CODE_OUTPUT",
                               reason=f"validation_failed_invalid_name_iter_{state.get('iteration_number', 0)}")
        except OSError as arch_exc:
            history_event(state, "archive_output_dir_failed",
                          error=safe_error_text(arch_exc))
            save_state(run_dir, state)
        return state
    generated = run_dir / "40_GPT_CODE_OUTPUT" / generated_name
    if not generated.is_file():
        # R2-CR-03: mutar estado PRIMERO, luego archivar
        state.update({"local_validation_status": "failed", "gpt_code_generation_status": "failed",
                      "current_phase": "failed_waiting_manual_output",
                      "next_action_for_mariano": "archivar_40_GPT_CODE_OUTPUT_a_mano"})
        history_event(state, "local_validation_failed_no_file")
        save_state(run_dir, state)
        try:
            archive_output_dir(run_dir, "40_GPT_CODE_OUTPUT",
                               reason=f"validation_failed_no_file_iter_{state.get('iteration_number', 0)}")
        except OSError as arch_exc:
            history_event(state, "archive_output_dir_failed",
                          error=safe_error_text(arch_exc))
            save_state(run_dir, state)
        return state
    # FIX C-1 (TOCTOU de ejecucion): R8-3 valida el SHA del .py en wait_gpt_code_output
    # (gate de transicion), pero la EJECUCION ocurre aca, en una iteracion posterior. En la
    # ventana intermedia el archivo puede alterarse (Drive sync / sobre-escritura) y correrse
    # sin verificar. Revalidamos manifest + SHA JUSTO ANTES de ejecutar.
    try:
        validate_output_manifest(
            run_dir, "40_GPT_CODE_OUTPUT",
            ("OUTPUT_MANIFEST.json", "GPT_CODE_OUTPUT.MANIFEST.json", "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json"),
            expected_stage="gpt_code_generation",
            expected_candidate_sha256=state.get("current_candidate_sha256"),
            required_files=("GPT_CODE_OUTPUT.json", generated_name),
            done_name="GPT_CODE_OUTPUT.DONE",
        )
        _expected_gen_sha = str(data.get("generated_file_sha256") or "")
        if _expected_gen_sha and _expected_gen_sha.lower() != sha256_file(generated).lower():
            raise SystemExit("gpt_code_generated_file_sha256_no_coincide")
    except SystemExit as exc:
        state.update({"local_validation_status": "failed", "gpt_code_generation_status": "failed",
                      "current_phase": "failed_waiting_manual_output",
                      "next_action_for_mariano": "archivar_40_GPT_CODE_OUTPUT_a_mano"})
        history_event(state, "local_validation_failed_manifest_recheck", error=safe_error_text(exc))
        save_state(run_dir, state)
        try:
            archive_output_dir(run_dir, "40_GPT_CODE_OUTPUT",
                               reason=f"manifest_recheck_failed_iter_{state.get('iteration_number', 0)}")
        except OSError as arch_exc:
            history_event(state, "archive_output_dir_failed", error=safe_error_text(arch_exc))
            save_state(run_dir, state)
        return state
    validation = run_dir / "41_LOCAL_VALIDATION"
    compile_log = validation / "py_compile.log"
    selftest_log = validation / "self_test.log"
    result: dict[str, Any] = {
        "generated_file": str(generated),
        "source_candidate_sha256": data.get("source_candidate_sha256"),
        "new_version": data.get("new_version"),
        "local_validation_status": "pending",
        "candidate_sha256": None,
        "py_compile": "pending",
        "self_test": "pending",
        "next_action": "pending",
    }
    try:
        run([sys.executable, "-m", "py_compile", str(generated)], capture_to=compile_log)
        result["py_compile"] = "passed"
        # Deep AST analysis before execution
        try:
            from scripts.ast_analysis import analyze_file_ast
            ast_result = analyze_file_ast(generated)
            ast_log = validation / "ast_analysis.json"
            ast_log.parent.mkdir(parents=True, exist_ok=True)
            write_json(ast_log, ast_result)
            result["ast_analysis"] = "safe" if ast_result["safe"] else "unsafe"
            if not ast_result["safe"]:
                critical = [v for v in ast_result["violations"] if v["severity"] == "CRITICAL"]
                result["ast_violations"] = len(critical)
                if critical:
                    raise SystemExit(f"ast_critical_violations:{len(critical)}:{critical[0]['kind']}")
        except ImportError:
            result["ast_analysis"] = "skipped_module_not_found"
        # R10: EXEC-02/EXEC-03 - entorno sanitizado + sandbox + timeout para código generado
        run([sys.executable, str(generated), "--self-test"], capture_to=selftest_log, env=_sanitized_env(), timeout=30, sandbox=True)
        result["self_test"] = "passed"
        new_sha = sha256_file(generated)
        result.update({
            "local_validation_status": "passed",
            "candidate_sha256": new_sha,
            "new_sha256": new_sha,
            "next_action": "run_post_code_adversarial_audits",
        })
    except subprocess.CalledProcessError as exc:
        result["local_validation_status"] = "failed"
        if result["py_compile"] == "pending":
            result["py_compile"] = "failed"
        elif result["self_test"] == "pending":
            result["self_test"] = "failed"
        result["next_action"] = "return_to_gpt"
        result["error"] = str(exc)
        write_json(validation / "LOCAL_VALIDATION.json", result)
        # R2-CR-03: mutar estado PRIMERO (durable ante crash del propio archive)
        # H-06/CR-HIGH-01: archivar 40_GPT_CODE_OUTPUT para evitar loop infinito
        state.update({"local_validation_status": "failed", "gpt_code_generation_status": "failed",
                      "current_phase": "waiting_gpt_code_output"})
        history_event(state, "local_validation_failed_and_archived")
        save_state(run_dir, state)
        try:
            archive_output_dir(run_dir, "40_GPT_CODE_OUTPUT",
                               reason=f"validation_failed_iter_{state.get('iteration_number', 0)}")
        except OSError as arch_exc:
            # Si archive falla, ya mutamos state a waiting_gpt_code_output; el watcher reintentará
            # pero el .DONE sigue ahí. Para evitar loop, cambiar a failed_waiting_manual_output.
            state["current_phase"] = "failed_waiting_manual_output"
            state["next_action_for_mariano"] = "archivar_40_GPT_CODE_OUTPUT_a_mano"
            history_event(state, "archive_output_dir_failed",
                          error=safe_error_text(arch_exc))
            save_state(run_dir, state)
        return state

    (validation / "candidate_sha256.txt").write_text(result["new_sha256"] + "\n", encoding="utf-8")
    write_json(validation / "LOCAL_VALIDATION.json", result)
    new_candidate_dir = run_dir / "00_CANDIDATE"
    shutil.copy2(generated, new_candidate_dir / generated.name)
    (new_candidate_dir / "CURRENT_SHA256.txt").write_text(result["new_sha256"] + "\n", encoding="utf-8")
    state.update({
        "candidate_path": str(new_candidate_dir),
        "candidate_file": str(new_candidate_dir / generated.name),
        "candidate_sha256": result["new_sha256"],
        "candidate_version": data.get("new_version") or state.get("candidate_version"),
        "current_candidate_sha256": result["new_sha256"],
        "current_candidate_version": data.get("new_version") or state.get("current_candidate_version"),
        "iteration_number": int(state.get("iteration_number", 0)) + 1,
        "gpt_code_generation_status": "complete",
        "local_validation_status": "passed",
        "post_code_adversarial_audit_status": "ready",
        "current_phase": "post_code_adversarial_ready",
        "last_completed_step": "local_validation_ok",
        "next_action_for_mariano": "correr_auditoria_adversarial_post_codigo",
    })
    history_event(state, "local_validation_ok", new_sha256=result["new_sha256"])
    save_state(run_dir, state)
    return state


def run_post_code_adversarial_audits(run_dir: Path, state: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    state.update({
        "post_code_adversarial_audit_status": "running",
        "current_phase": "post_code_adversarial_running",
        "ready_for_claude_stage": False,
    })
    save_state(run_dir, state)
    raw_dir = run_runner_to_bus(run_dir, state, raw_dir_name="50_POST_CODE_ADVERSARIAL_AUDITS", profile="fused_no_gemini", max_workers="5", dry_run=dry_run)
    run_preconsolidation(run_dir, raw_dir, out_dir_name="51_POST_CODE_AUDIT_PRECONSOLIDATED", base_name="POST_CODE_PRECONSOLIDACION", cycle=1, dry_run=dry_run)
    state.update({
        "post_code_adversarial_audit_status": "complete",
        "gpt_post_code_audit_status": "waiting",
        "current_phase": "waiting_gpt_post_code_output",
        "last_completed_step": "post_code_adversarial_raw_ready",
        "next_action_for_mariano": "abrir_60_GPT_ITERATION_INPUT_y_guardar_61_GPT_ITERATION_OUTPUT",
    })
    write_gpt_post_code_input(run_dir, state)
    history_event(state, "post_code_adversarial_audits_ready", dry_run=dry_run)
    save_state(run_dir, state)
    return state


def wait_gpt_post_code_output(run_dir: Path, *, timeout_seconds: int = 0) -> dict[str, Any]:
    data = wait_for_output(
        lambda: validate_json_output(
            run_dir,
            "61_GPT_ITERATION_OUTPUT",
            "AUDITORIA_ADVERSARIAL_POST_CODIGO",
            "gpt_post_code_adversarial_audit",
            status_field="verdict",
        ),
        timeout_seconds,
    )
    state = load_state(run_dir)
    status = data["verdict"]
    if status == "bug0_mejoras0":
        if data.get("bugs") or data.get("mejoras"):
            raise SystemExit("gpt_post_code_bug0_invalido_con_bugs_o_mejoras_pendientes")
        state.update({
            "gpt_post_code_audit_status": "bug0_mejoras0",
            "ready_for_expensive_vertex_audits": False,
            "ready_for_claude_stage": False,
            "current_phase": "final_gpt_closure_ready",
            "last_completed_step": "gpt_post_code_bug0_mejoras0",
            "next_action_for_mariano": "preparar_cierre_final_gpt_en_70_FINAL_GPT_CLOSURE",
        })
        write_final_gpt_closure(run_dir, state, data)
        write_final_handoff(run_dir, state, data)
    elif status == "code_required":
        max_short_iterations = int(read_json(PRIMARY_BRAIN_POLICY, {}).get("max_short_iterations", 7))
        if int(state.get("iteration_number", 0)) >= max_short_iterations:
            state.update({
                "gpt_post_code_audit_status": "blocked_iteration_limit",
                "current_phase": "blocked",
                "next_action_for_mariano": "intervencion_requerida_por_limite_de_7_bucles_cortos",
            })
            history_event(state, "short_iteration_limit_reached", limit=max_short_iterations)
            save_state(run_dir, state)
            return state
        require_api_or_direct_code_route(
            run_dir,
            "61_GPT_ITERATION_OUTPUT",
            data,
            f"API_AUDIT_REQUESTS_ITER_{state.get('iteration_number', 0)}.json",
        )
        previous_code_archive = archive_output_dir(
            run_dir,
            "40_GPT_CODE_OUTPUT",
            reason=f"iteration_{state.get('iteration_number', 0)}_previous_code",
        )
        state.update({
            "gpt_post_code_audit_status": "code_required",
            "gpt_code_generation_status": "waiting",
            "current_phase": "waiting_gpt_code_output",
            "last_completed_step": "gpt_post_code_code_required",
            "next_action_for_mariano": "gpt_debe_generar_nuevo_codigo_completo_en_40_GPT_CODE_OUTPUT",
        })
        if previous_code_archive:
            state["previous_code_output_archive"] = previous_code_archive
    else:
        state.update({
            "gpt_post_code_audit_status": "blocked",
            "current_phase": "blocked",
            "next_action_for_mariano": "revisar_bloqueo_gpt_post_codigo",
        })
    history_event(state, "gpt_post_code_output_received", status=status)
    save_state(run_dir, state)
    return state


def write_final_gpt_closure(run_dir: Path, state: dict[str, Any], data: dict[str, Any]) -> None:
    out = run_dir / "70_FINAL_GPT_CLOSURE"
    closure = {
        "status": "bug0_mejoras0",
        "initial_candidate_version": state.get("candidate_version"),
        "initial_candidate_sha256": state.get("candidate_sha256"),
        "candidate_sha256": state.get("current_candidate_sha256"),
        "candidate_version": state.get("current_candidate_version"),
        "history": state.get("history", []),
        "bugs_corregidos": data.get("bugs", []),
        "mejoras_corregidas": data.get("mejoras", []),
        "falsos_positivos": data.get("falsos_positivos", []),
        "cosmeticas_no_bloqueantes": data.get("cosmeticas_no_bloqueantes", []),
        "deudas_diferidas_autorizadas": data.get("deudas_diferidas_autorizadas", data.get("deudas_diferidas", [])),
        "auditorias_manuales_usadas": str(run_dir / "10_MANUAL_AUDITS"),
        "auditorias_automaticas_usadas": str(run_dir / "20_AUTO_AUDITS_RAW"),
        "auditorias_post_codigo": str(run_dir / "50_POST_CODE_ADVERSARIAL_AUDITS"),
        "global_approval_declared": False,
        "external_final_audits_enforced_by_terminal_gate": False,
        "external_final_audits_policy": "GPT-only closure handoff; Claude/GLM may audit externally in a later gate, but this watcher does not declare global approval.",
        "ready_for_claude_stage": False,
        "source": data,
    }
    write_json(out / "AUDITORIA_FINAL_GPT_BUG0_MEJORAS0.json", closure)
    (out / "AUDITORIA_FINAL_GPT_BUG0_MEJORAS0.md").write_text(
        "# AUDITORIA_FINAL_GPT_BUG0_MEJORAS0\n\n"
        "GPT primario dejó la iteración post-código en `bug0_mejoras0`.\n"
        f"Versión inicial: `{closure['initial_candidate_version']}`.\n"
        f"SHA inicial: `{closure['initial_candidate_sha256']}`.\n"
        f"Versión final: `{closure['candidate_version']}`.\n"
        f"SHA final: `{closure['candidate_sha256']}`.\n\n"
        "Esto no habilita por sí solo Claude/GLM externo: el handoff final sigue siendo etapa separada.\n",
        encoding="utf-8",
    )
    (out / "HISTORIAL_ITERACIONES.md").write_text(
        "# HISTORIAL_ITERACIONES\n\n"
        "```json\n"
        + json.dumps(state.get("history", []), ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    write_output_manifest_and_done(
        run_dir, "70_FINAL_GPT_CLOSURE",
        done_name="FINAL_GPT_CLOSURE.DONE",
        stage="final_gpt_closure",
        candidate_sha256=state.get("current_candidate_sha256"),
        files=("AUDITORIA_FINAL_GPT_BUG0_MEJORAS0.json", "AUDITORIA_FINAL_GPT_BUG0_MEJORAS0.md", "HISTORIAL_ITERACIONES.md"),
    )


def write_final_handoff(run_dir: Path, state: dict[str, Any], data: dict[str, Any]) -> None:
    out = run_dir / "80_FINAL_HANDOFF"
    out.mkdir(parents=True, exist_ok=True)
    candidate = Path(str(state.get("candidate_file") or ""))
    if not candidate.is_file():
        raise SystemExit(f"final_handoff_candidate_no_existe:{candidate}")
    delivered = out / candidate.name
    shutil.copy2(candidate, delivered)
    summary = str(data.get("executive_summary") or "").strip()
    if not summary:
        summary = (
            "El cerebro primario concluyo su propia iteracion sin bugs ni mejoras tecnicas pendientes. "
            "Esto no constituye aprobacion organizacional ni reemplaza etapas externas."
        )
    (out / "RESUMEN_EJECUTIVO.md").write_text(
        "# Resumen ejecutivo\n\n" + summary + "\n\n"
        f"- version: `{state.get('current_candidate_version')}`\n"
        f"- sha256: `{state.get('current_candidate_sha256')}`\n"
        f"- iteraciones: `{state.get('iteration_number', 0)}`\n"
        "- validacion local: `passed`\n"
        "- auditorias externas: `NO_EJECUTADAS`\n",
        encoding="utf-8",
    )
    write_json(out / "FINAL_HANDOFF.json", {
        "schema_version": "camino_a_final_handoff.v1",
        "run_id": run_dir.name,
        "candidate_file": delivered.name,
        "candidate_version": state.get("current_candidate_version"),
        "candidate_sha256": sha256_file(delivered),
        "executive_summary": "RESUMEN_EJECUTIVO.md",
        "local_validation_status": state.get("local_validation_status"),
        "external_audits": "NO_EJECUTADAS",
        "created_at_utc": utc_now(),
    })
    write_output_manifest_and_done(
        run_dir, "80_FINAL_HANDOFF",
        done_name="FINAL_HANDOFF.DONE",
        stage="final_handoff",
        candidate_sha256=state.get("current_candidate_sha256"),
        files=(delivered.name, "RESUMEN_EJECUTIVO.md", "FINAL_HANDOFF.json"),
    )


def prepare_gpt_primary_input_command(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    write_gpt_primary_input(run_dir, state)
    if not manual_gate_open(state):
        state.update({
            "gpt_primary_consolidation_status": "pending",
            "manual_missing_policy": "open_incremental_inbox",
            "manual_window": "open_until_terminal",
            "current_phase": "manual_window",
            "next_action_for_mariano": "cargar_auditorias_manuales_o_autorizar_avance_parcial",
        })
    elif state.get("auto_audits_cycle1_status") != "complete":
        state.update({
            "gpt_primary_consolidation_status": "pending",
            "current_phase": "cycle_1_auto_ready",
            "next_action_for_mariano": "correr_auditorias_automaticas_ciclo_1",
        })
    else:
        state.update({
            "gpt_primary_consolidation_status": "waiting",
            "current_phase": "waiting_gpt_primary_output",
            "next_action_for_mariano": "guardar_CONSOLIDACION_GPT_PRIMARIA_en_31_GPT_PRIMARY_OUTPUT",
        })
    history_event(state, "gpt_primary_input_prepared")
    save_state(run_dir, state)
    return state


def prepare_gpt_post_code_input_command(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    write_gpt_post_code_input(run_dir, state)
    state.update({
        "gpt_post_code_audit_status": "waiting",
        "current_phase": "waiting_gpt_post_code_output",
        "next_action_for_mariano": "guardar_AUDITORIA_ADVERSARIAL_POST_CODIGO_en_61_GPT_ITERATION_OUTPUT",
    })
    history_event(state, "gpt_post_code_input_prepared")
    save_state(run_dir, state)
    return state


def probe_gpt_drive_write(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    out = run_dir / "30_GPT_PRIMARY_INPUT"
    (out / "DRIVE_WRITE_PROBE_INSTRUCTIONS.md").write_text(
        "# DRIVE_WRITE_PROBE\n\n"
        "Crear en `../31_GPT_PRIMARY_OUTPUT/` estos archivos:\n"
        "- `DRIVE_WRITE_PROBE.md`\n"
        "- `DRIVE_WRITE_PROBE.json`\n"
        "- `DRIVE_WRITE_PROBE.DONE`\n\n"
        "Contenido JSON esperado:\n"
        "```json\n"
        "{\n"
        '  "probe": "drive_write",\n'
        '  "status": "ok",\n'
        '  "written_by": "gpt"\n'
        "}\n"
        "```\n"
        "Si GPT no puede escribir directo en Drive, Mariano debe guardar manualmente esos archivos.\n",
        encoding="utf-8",
    )
    (out / "DRIVE_WRITE_PROBE.READY").write_text("READY\n", encoding="utf-8")
    state.update({
        "gpt_drive_write_capability": "unknown",
        "current_phase": "waiting_gpt_drive_write_probe",
        "next_action_for_mariano": "pedir_a_GPT_drive_write_probe_o_guardar_output_manualmente",
    })
    history_event(state, "gpt_drive_write_probe_ready")
    save_state(run_dir, state)
    return state


def check_gpt_drive_write(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    out = run_dir / "31_GPT_PRIMARY_OUTPUT"
    done = out / "DRIVE_WRITE_PROBE.DONE"
    data = read_json(out / "DRIVE_WRITE_PROBE.json", {})
    if done.exists() and data.get("probe") == "drive_write" and data.get("status") == "ok":
        state["gpt_drive_write_capability"] = "confirmed"
        state["next_action_for_mariano"] = next_command_for_state(run_dir, state)
        history_event(state, "gpt_drive_write_probe_confirmed")
    else:
        state.update({
            "gpt_drive_write_capability": "manual_save_required",
            "gpt_drive_write_fallback": "GPT genera contenido en ChatGPT y Mariano lo guarda en Drive",
            "next_action_for_mariano": "guardar_outputs_GPT_manualmente_en_Drive",
        })
        history_event(state, "gpt_drive_write_probe_manual_save_required")
    save_state(run_dir, state)
    return state


def probe_gpt_api_actions(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    out = run_dir / "30_GPT_PRIMARY_INPUT"
    (out / "API_ACTION_PROBE_INSTRUCTIONS.md").write_text(
        "# API_ACTION_PROBE\n\n"
        "Verificar si GPT tiene Action/MCP/API configurado para pedir o ejecutar auditorias baratas.\n"
        "No imprimir claves. No gastar cuota relevante. Si no hay herramienta, declararlo.\n\n"
        "Escribir en `../31_GPT_PRIMARY_OUTPUT/`:\n"
        "- `API_ACTION_PROBE.md`\n"
        "- `API_ACTION_PROBE.json`\n"
        "- `API_ACTION_PROBE.DONE`\n\n"
        "JSON esperado si puede llamar APIs:\n"
        "```json\n"
        "{\n"
        '  "probe": "gpt_api_actions",\n'
        '  "gpt_can_call_external_apis_directly": true,\n'
        '  "available_actions": [],\n'
        '  "fallback_required": false\n'
        "}\n"
        "```\n\n"
        "JSON esperado si no puede:\n"
        "```json\n"
        "{\n"
        '  "probe": "gpt_api_actions",\n'
        '  "gpt_can_call_external_apis_directly": false,\n'
        '  "fallback_required": true,\n'
        '  "fallback": "orquestador_local_ejecuta_api_requests_generados_por_gpt"\n'
        "}\n"
        "```\n",
        encoding="utf-8",
    )
    (out / "API_ACTION_PROBE.READY").write_text("READY\n", encoding="utf-8")
    state.update({
        "gpt_api_actions_capability": "unknown",
        "current_phase": "waiting_gpt_api_actions_probe",
        "next_action_for_mariano": "pedir_a_GPT_api_action_probe_o_guardar_resultado_manualmente",
    })
    history_event(state, "gpt_api_actions_probe_ready")
    save_state(run_dir, state)
    return state


def check_gpt_api_actions(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    out = run_dir / "31_GPT_PRIMARY_OUTPUT"
    done = out / "API_ACTION_PROBE.DONE"
    data = read_json(out / "API_ACTION_PROBE.json", {})
    if done.exists() and data.get("probe") == "gpt_api_actions" and data.get("gpt_can_call_external_apis_directly") is True:
        state["gpt_api_actions_capability"] = "confirmed"
        history_event(state, "gpt_api_actions_confirmed", available_actions=data.get("available_actions", []))
    elif done.exists() and data.get("probe") == "gpt_api_actions":
        state.update({
            "gpt_api_actions_capability": "orchestrator_fallback_required",
            "gpt_api_actions_fallback": "orquestador_local_ejecuta_api_requests_generados_por_gpt",
        })
        history_event(state, "gpt_api_actions_orchestrator_fallback_required")
    else:
        state.update({
            "gpt_api_actions_capability": "orchestrator_fallback_required",
            "gpt_api_actions_fallback": "orquestador_local_ejecuta_api_requests_generados_por_gpt",
        })
        history_event(state, "gpt_api_actions_probe_missing_or_incomplete")
    state["next_action_for_mariano"] = next_command_for_state(run_dir, state)
    save_state(run_dir, state)
    return state


def next_command_for_state(run_dir: Path, state: dict[str, Any]) -> str:
    base = f'python3 scripts/run_multiaudit_cycle.py --resume "{run_dir}"'
    phase = state.get("current_phase")
    if int(state.get("manual_audits_received", 0)) < int(state.get("manual_audits_expected", 3)) and not state.get("manual_audits_override"):
        return "cargar_auditorias_manuales_o_autorizar_avance_parcial"
    if phase in {"cycle_1_auto_ready", "cycle_1_repeat_without_manuals"} or state.get("auto_audits_cycle1_status") == "pending":
        return f"{base} --run-auto-audits-cycle1"
    if phase == "waiting_gpt_primary_output":
        return f"{base} --wait-gpt-primary-output"
    if phase == "waiting_gpt_code_output":
        return f"{base} --wait-gpt-code-output"
    if phase == "local_validation_ready":
        return f"{base} --validate-gpt-code"
    if phase == "post_code_adversarial_ready":
        return f"{base} --run-post-code-adversarial-audits"
    if phase == "waiting_gpt_post_code_output":
        return f"{base} --wait-gpt-post-code-output"
    return f"{base} --continue"


def print_next_command(run_dir: Path) -> int:
    state = load_state(run_dir)
    print(next_command_for_state(run_dir, state))
    return 0


def print_gpt_instructions(run_dir: Path) -> int:
    state = load_state(run_dir)
    if state.get("current_phase") == "waiting_gpt_post_code_output":
        path = run_dir / "60_GPT_ITERATION_INPUT" / "INSTRUCCIONES_GPT_POST_CODIGO.md"
    else:
        path = run_dir / "30_GPT_PRIMARY_INPUT" / "INSTRUCCIONES_GPT_PRIMARIO.md"
    if not path.exists():
        if path.parent.name == "60_GPT_ITERATION_INPUT":
            write_gpt_post_code_input(run_dir, state)
        else:
            write_gpt_primary_input(run_dir, state)
    print(path.read_text(encoding="utf-8", errors="replace"))
    return 0


def manual_terminal_status(run_dir: Path) -> int:
    state = load_state(run_dir)
    state.update({
        "operation_mode": "manual_terminal",
        "manual_terminal_supported": True,
        "codex_required": False,
        "next_action_for_mariano": next_command_for_state(run_dir, state),
    })
    history_event(state, "manual_terminal_status_requested")
    save_state(run_dir, state)
    print(json.dumps({
        "operation_mode": state["operation_mode"],
        "codex_required": state["codex_required"],
        "manual_codex_paste_allowed": state.get("manual_codex_paste_allowed"),
        "current_phase": state.get("current_phase"),
        "next_command": state["next_action_for_mariano"],
    }, ensure_ascii=False, indent=2))
    return 0


def materialize_gpt_code_fallback(run_dir: Path, source_file: str, *, new_version: str, source_sha256: str) -> dict[str, Any]:
    state = load_state(run_dir)
    src = Path(source_file).expanduser().resolve()
    if not src.is_file() or src.suffix != ".py":
        raise SystemExit(f"gpt_code_fallback_source_invalido:{src}")
    # R10: PATH-04 - rechazar symlinks en source
    if src.is_symlink():
        raise SystemExit(f"gpt_code_fallback_source_symlink:{src}")
    expected_sha = source_sha256 or str(state.get("current_candidate_sha256") or "")
    if expected_sha and str(expected_sha).lower() != str(state.get("current_candidate_sha256","")).lower():
        raise SystemExit("gpt_code_fallback_source_sha256_no_coincide")
    out = run_dir / "40_GPT_CODE_OUTPUT"
    dst = out / src.name
    shutil.copy2(src, dst)
    write_json(out / "GPT_CODE_OUTPUT.json", {
        "new_version": new_version,
        "source_candidate_sha256": state.get("current_candidate_sha256"),
        "generated_file": dst.name,
        "claimed_fixes": [],
        "claimed_tests": [],
        "requires_local_validation": True,
        "materialized_by": "codex_orchestrator_fallback_only",
        "manual_codex_paste_policy": state.get("manual_codex_paste_policy"),
    })
    write_output_manifest_and_done(
        run_dir, "40_GPT_CODE_OUTPUT",
        done_name="GPT_CODE_OUTPUT.DONE",
        stage="gpt_code_generation",
        candidate_sha256=state.get("current_candidate_sha256"),
        files=("GPT_CODE_OUTPUT.json", dst.name),
    )
    state.update({
        "watcher_status": "active",
        "gpt_code_generation_status": "complete",
        "current_phase": "local_validation_ready",
        "next_action_for_mariano": "ejecutar_validate_gpt_code",
    })
    history_event(state, "gpt_code_materialized_from_manual_fallback", file=dst.name)
    save_state(run_dir, state)
    return state


def _extract_fenced_block(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        m = re.search(r"```[ \t]*" + re.escape(label) + r"[^\n]*\n(.*?)\n```", text, re.S | re.I)
        if m:
            return m.group(1).strip() + "\n"
    return None


def materialize_gpt_code_envelope_fallback(run_dir: Path, source_envelope: str, *, new_version: str, source_sha256: str) -> dict[str, Any]:
    state = load_state(run_dir)
    src = Path(source_envelope).expanduser().resolve()
    if not src.is_file() or src.suffix.lower() not in {".md", ".txt"}:
        raise SystemExit(f"gpt_code_envelope_source_invalido:{src}")
    # R10: PATH-05 - rechazar symlinks en source
    if src.is_symlink():
        raise SystemExit(f"gpt_code_envelope_source_symlink:{src}")

    expected_sha = source_sha256 or str(state.get("current_candidate_sha256") or "")
    if expected_sha and str(expected_sha).lower() != str(state.get("current_candidate_sha256","")).lower():
        raise SystemExit("gpt_code_envelope_source_sha256_no_coincide")

    text = src.read_text(encoding="utf-8")
    json_block = _extract_fenced_block(text, ("json",))
    py_block = _extract_fenced_block(text, ("python", "py"))

    if not py_block:
        raise SystemExit("gpt_code_envelope_sin_bloque_python")

    meta: dict[str, Any] = {}
    if json_block:
        try:
            meta = json.loads(json_block)
        except Exception as e:
            raise SystemExit(f"gpt_code_envelope_json_invalido:{e}")

    if meta.get("source_candidate_sha256") and str(meta.get("source_candidate_sha256")).lower() != str(state.get("current_candidate_sha256","")).lower():
        raise SystemExit("gpt_code_envelope_json_source_sha256_no_coincide")
    if meta.get("new_version") and str(meta.get("new_version")) != str(new_version):
        raise SystemExit("gpt_code_envelope_json_new_version_no_coincide")

    out = run_dir / "40_GPT_CODE_OUTPUT"
    out.mkdir(parents=True, exist_ok=True)

    candidate_name = str(state.get("candidate_name") or "candidate")
    version_token = "v" + str(new_version).replace(".", "_")
    generated_name = str(meta.get("generated_file") or f"{candidate_name}_{version_token}.py")

    generated_path = Path(generated_name)
    if generated_path.name != generated_name or generated_path.suffix != ".py":
        raise SystemExit(f"gpt_code_envelope_generated_file_invalido:{generated_name}")

    dst = out / generated_name
    tmp = out / f".{dst.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"

    try:
        with tmp.open("x", encoding="utf-8") as f:
            f.write(py_block)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)
        _fsync_parent_dir(dst)
    finally:
        tmp.unlink(missing_ok=True)

    changelog = _extract_fenced_block(text, ("markdown", "md", "changelog"))
    if changelog:
        (out / f"CHANGELOG_{version_token}.md").write_text(changelog, encoding="utf-8")

    write_json(out / "GPT_CODE_OUTPUT.json", {
        "new_version": new_version,
        "source_candidate_sha256": state.get("current_candidate_sha256"),
        "generated_file": dst.name,
        "generated_file_sha256": sha256_file(dst),
        "envelope_file": src.name,
        "envelope_sha256": sha256_file(src),
        "claimed_fixes": meta.get("claimed_fixes", []),
        "claimed_tests": meta.get("claimed_tests", []),
        "requires_local_validation": True,
        "materialized_by": "codex_orchestrator_envelope_fallback_only",
        "manual_codex_paste_policy": state.get("manual_codex_paste_policy"),
    })
    write_output_manifest_and_done(
        run_dir, "40_GPT_CODE_OUTPUT",
        done_name="GPT_CODE_OUTPUT.DONE",
        stage="gpt_code_generation",
        candidate_sha256=state.get("current_candidate_sha256"),
        files=("GPT_CODE_OUTPUT.json", dst.name),
    )

    state.update({
        "watcher_status": "active",
        "gpt_code_generation_status": "complete",
        "current_phase": "local_validation_ready",
        "next_action_for_mariano": "ejecutar_validate_gpt_code",
        "gpt_code_materialization_mode": "envelope_fallback",
    })
    history_event(state, "gpt_code_materialized_from_envelope_fallback", file=dst.name, envelope=src.name)
    save_state(run_dir, state)
    return state


def materialize_gpt_code_zip_fallback(run_dir: Path, source_zip: str, *, new_version: str, source_sha256: str) -> dict[str, Any]:
    import zipfile

    state = load_state(run_dir)
    src = Path(source_zip).expanduser().resolve()
    if not src.is_file() or src.suffix.lower() != ".zip":
        raise SystemExit(f"gpt_code_zip_fallback_source_invalido:{src}")
    # R10: PATH-07 - rechazar symlinks en source
    if src.is_symlink():
        raise SystemExit(f"gpt_code_zip_fallback_source_symlink:{src}")

    expected_sha = source_sha256 or str(state.get("current_candidate_sha256") or "")
    if expected_sha and str(expected_sha).lower() != str(state.get("current_candidate_sha256","")).lower():
        raise SystemExit("gpt_code_zip_fallback_source_sha256_no_coincide")

    out = run_dir / "40_GPT_CODE_OUTPUT"
    out.mkdir(parents=True, exist_ok=True)

    package_sha256 = sha256_file(src)
    meta = {}

    with zipfile.ZipFile(src, "r") as z:
        names = [
            n for n in z.namelist()
            if n and not n.endswith("/") and not n.startswith("__MACOSX/")
        ]

        for n in names:
            pp = Path(n)
            if pp.is_absolute() or ".." in pp.parts:
                raise SystemExit(f"gpt_code_zip_path_inseguro:{n}")

        # M-01/SEG-MED-01: zip bomb protection
        MAX_DECOMPRESSED_PY_BYTES = 5 * 1024 * 1024  # 5 MiB
        MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MiB
        total_uncompressed = sum(z.getinfo(n).file_size for n in names)
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise SystemExit(f"gpt_code_zip_total_too_large:{total_uncompressed}")

        py_names = [n for n in names if Path(n).suffix == ".py"]
        if len(py_names) != 1:
            raise SystemExit(f"gpt_code_zip_py_count_invalido:{len(py_names)}")

        py_info = z.getinfo(py_names[0])
        if py_info.file_size > MAX_DECOMPRESSED_PY_BYTES:
            raise SystemExit(f"gpt_code_zip_py_too_large:{py_info.file_size}")

        json_names = [n for n in names if Path(n).name == "GPT_CODE_OUTPUT.json"]
        if json_names:
            try:
                meta = json.loads(z.read(json_names[0]).decode("utf-8"))
            except Exception as e:
                raise SystemExit(f"gpt_code_zip_json_invalido:{json_names[0]}:{e}")

        if meta.get("source_candidate_sha256") and str(meta.get("source_candidate_sha256")).lower() != str(state.get("current_candidate_sha256","")).lower():
            raise SystemExit("gpt_code_zip_json_source_sha256_no_coincide")
        if meta.get("new_version") and str(meta.get("new_version")) != str(new_version):
            raise SystemExit("gpt_code_zip_json_new_version_no_coincide")

        py_name = py_names[0]
        dst = out / Path(py_name).name
        tmp = out / f".{dst.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"

        try:
            with tmp.open("xb") as f:
                f.write(z.read(py_name))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dst)
            _fsync_parent_dir(dst)
        finally:
            tmp.unlink(missing_ok=True)

    write_json(out / "GPT_CODE_OUTPUT.json", {
        "new_version": new_version,
        "source_candidate_sha256": state.get("current_candidate_sha256"),
        "generated_file": dst.name,
        "generated_file_sha256": sha256_file(dst),
        "package_file": src.name,
        "package_sha256": package_sha256,
        "claimed_fixes": meta.get("claimed_fixes", []),
        "claimed_tests": meta.get("claimed_tests", []),
        "requires_local_validation": True,
        "materialized_by": "codex_orchestrator_zip_fallback_only",
        "manual_codex_paste_policy": state.get("manual_codex_paste_policy"),
    })
    write_output_manifest_and_done(
        run_dir, "40_GPT_CODE_OUTPUT",
        done_name="GPT_CODE_OUTPUT.DONE",
        stage="gpt_code_generation",
        candidate_sha256=state.get("current_candidate_sha256"),
        files=("GPT_CODE_OUTPUT.json", dst.name),
    )

    state.update({
        "watcher_status": "active",
        "gpt_code_generation_status": "complete",
        "current_phase": "local_validation_ready",
        "next_action_for_mariano": "ejecutar_validate_gpt_code",
        "gpt_code_materialization_mode": "zip_fallback",
    })
    history_event(state, "gpt_code_materialized_from_zip_fallback", file=dst.name, package=src.name)
    save_state(run_dir, state)
    return state


def materialize_gpt_post_audit_fallback(run_dir: Path, source_file: str) -> dict[str, Any]:
    state = load_state(run_dir)
    src = Path(source_file).expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"gpt_post_audit_fallback_source_invalido:{src}")
    # R10: PATH-06 - rechazar symlinks en source
    if src.is_symlink():
        raise SystemExit(f"gpt_post_audit_fallback_source_symlink:{src}")
    out = run_dir / "61_GPT_ITERATION_OUTPUT"
    if src.suffix.lower() == ".json":
        dst_json = out / "AUDITORIA_ADVERSARIAL_POST_CODIGO.json"
        shutil.copy2(src, dst_json)
        data = read_json(dst_json, {})
        md = out / "AUDITORIA_ADVERSARIAL_POST_CODIGO.md"
        if not md.exists():
            md.write_text(
                "# AUDITORIA_ADVERSARIAL_POST_CODIGO\n\n"
                "Materializada por fallback manual. Ver JSON adjunto.\n",
                encoding="utf-8",
            )
    else:
        md = out / "AUDITORIA_ADVERSARIAL_POST_CODIGO.md"
        shutil.copy2(src, md)
        data = {
            "stage": "gpt_post_code_adversarial_audit",
            "candidate_version": state.get("current_candidate_version"),
            "candidate_sha256": state.get("current_candidate_sha256"),
            "verdict": "blocked",
            "bugs": [],
            "mejoras": [],
            "falsos_positivos": [],
            "deudas_diferidas": [],
            "materialized_by": "codex_orchestrator_fallback_only",
            "requires_json_review": True,
        }
        write_json(out / "AUDITORIA_ADVERSARIAL_POST_CODIGO.json", data)
    write_output_manifest_and_done(
        run_dir, "61_GPT_ITERATION_OUTPUT",
        done_name="AUDITORIA_ADVERSARIAL_POST_CODIGO.DONE",
        stage="gpt_post_code_adversarial_audit",
        candidate_sha256=state.get("current_candidate_sha256"),
        files=("AUDITORIA_ADVERSARIAL_POST_CODIGO.json",),
    )
    state.update({
        "watcher_status": "active",
        "gpt_post_code_audit_status": "waiting",
        "current_phase": "waiting_gpt_post_code_output",
        "next_action_for_mariano": "ejecutar_wait_gpt_post_code_output",
    })
    history_event(state, "gpt_post_code_audit_materialized_from_manual_fallback", source=src.name)
    save_state(run_dir, state)
    return state


def terminal_blockers(run_dir: Path, state: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    # A estado terminal no se llega con trabajos canonicos vivos o colas del worker bus pendientes.
    for job_name, path_fn in (("primary_brain", brain_job_path), ("workflow", workflow_job_path)):
        job = read_json(path_fn(run_dir), {})
        pid = int(job.get("pid", 0) or 0)
        if pid_alive(pid):
            blockers.append(f"{job_name}_pid_alive:{pid}")
    bus = run_dir / "13_WORKER_BUS"
    if bus.exists():
        for worker in ("gpt", "claude"):
            base = bus / worker
            for dirname in ("IN", "OUT"):
                folder = base / dirname
                if folder.exists():
                    pending = [p.name for p in folder.iterdir() if p.is_dir()]
                    if pending:
                        blockers.append(f"worker_{worker}_{dirname.lower()}_pending:{len(pending)}")
    canonical_waits = {
        "waiting_gpt_primary_output": run_dir / "31_GPT_PRIMARY_OUTPUT" / "CONSOLIDACION_GPT_PRIMARIA.DONE",
        "waiting_gpt_code_output": run_dir / "40_GPT_CODE_OUTPUT" / "GPT_CODE_OUTPUT.DONE",
        "waiting_gpt_post_code_output": run_dir / "61_GPT_ITERATION_OUTPUT" / "AUDITORIA_ADVERSARIAL_POST_CODIGO.DONE",
    }
    phase = str(state.get("current_phase"))
    wait_marker = canonical_waits.get(phase)
    if wait_marker is not None and not wait_marker.exists():
        blockers.append(f"canonical_marker_pending:{phase}")
    return blockers


def terminal_ready(run_dir: Path, state: dict[str, Any]) -> bool:
    blockers = terminal_blockers(run_dir, state)
    if blockers:
        state["terminal_blockers"] = blockers
        history_event(state, "terminal_blocked_pending_work", blockers=blockers[:20])
        save_state(run_dir, state)
        return False
    state.pop("terminal_blockers", None)
    save_state(run_dir, state)
    return True


def watch_gpt_output(run_dir: Path, *, interval_seconds: int, timeout_minutes: int, dry_run: bool) -> dict[str, Any]:
    # R10: CONC-01 - signal handling para apoyo graceful
    _watcher_shutdown = False
    def _handle_term(signum: int, frame: Any) -> None:
        nonlocal _watcher_shutdown
        _watcher_shutdown = True
    _prev_term = signal.signal(signal.SIGTERM, _handle_term)
    _prev_int = signal.signal(signal.SIGINT, _handle_term)

    lock = acquire_watcher_lock(run_dir)
    try:
        state = load_state(run_dir)
        if state.get("current_phase") == "waiting_gpt_output":
            state["current_phase"] = "waiting_gpt_primary_output"
        state.update({
            "watch_gpt_output_supported": True,
            "watch_mode": "persistent_drive_and_manual_inbox",
            "watcher_status": "active",
            "manual_window": "open_until_terminal",
        })
        save_state(run_dir, state)
        prepare_worker_bus(run_dir)
        recover_worker_bus_archives(run_dir)
        prepare_manual_inbox(run_dir, open_window=False)
        deadline = None if timeout_minutes <= 0 else time.monotonic() + timeout_minutes * 60
        next_heartbeat = 0.0
        while True:
            # R10: CONC-01 - check graceful shutdown
            if _watcher_shutdown:
                state = load_state(run_dir)
                state["watcher_status"] = "shutdown_requested"
                history_event(state, "watcher_shutdown_signal_received")
                save_state(run_dir, state)
                break
            # C-01: reaper de hijos zombie cada iteración
            reap_children()
            state = load_state(run_dir)
            invalidate_failed = False  # R4-03: flag separado para no pisar con iteration_failed
            # H-05/CR-HIGH-03: reanudar invalidate_pending si quedó pendiente por crash
            # R3-05: dentro del try interno para que un fallo persistente sume al error streak
            try:
                if state.get("invalidate_pending"):
                    pending = dict(state.get("invalidate_pending") or {})
                    audit_ids = pending.get("audit_ids") or []
                    history_event(state, "invalidate_pending_resumed", pending=pending)
                    save_state(run_dir, state)
                    # R2-CONC-05: preservar audit_ids originales para no perder el contexto
                    audits = [{"audit_id": aid} for aid in audit_ids]
                    invalidate_downstream_after_manual_update(run_dir, state, audits)
                    state = load_state(run_dir)
            except (SystemExit, subprocess.CalledProcessError, OSError, ValueError) as exc:
                invalidate_failed = True
                state = load_state(run_dir)
                state["watcher_last_error"] = safe_error_text(exc)[:500]
                state["watcher_last_error_at"] = utc_now()
                state["watcher_error_streak"] = int(state.get("watcher_error_streak", 0)) + 1
                history_event(state, "watcher_invalidate_resume_error", error=state["watcher_last_error"])
                if state["watcher_error_streak"] >= 3:
                    notify_once(
                        run_dir, state,
                        f"watcher_invalidate_error_{hashlib.sha256(state['watcher_last_error'].encode()).hexdigest()[:12]}",
                        "Camino A requiere intervencion (invalidate_pending)",
                        f"El watcher no pudo reanudar invalidate_pending: {state['watcher_last_error'][:140]}",
                    )
                save_state(run_dir, state)
            if state.get("current_phase") in TERMINAL_PHASES and terminal_ready(run_dir, state):
                state["watcher_status"] = "terminal_complete"
                notify_once(
                    run_dir,
                    state,
                    "terminal_complete",
                    "Camino A finalizado",
                    f"El run {run_dir.name} llego al estado terminal {state.get('current_phase')}.",
                )
                save_state(run_dir, state)
                return state
            manual_before = int(state.get("manual_audits_received", 0))
            state = refresh_manual_ingress(run_dir, state, source_label="persistent_watcher") or state
            manual_after = int(load_state(run_dir).get("manual_audits_received", manual_before))
            state, worker_events = process_worker_bus(run_dir, load_state(run_dir))
            phase = state.get("current_phase")
            # R3-01: rama explícita para failed_waiting_manual_output (no dejar al watcher en limbo)
            if phase == "failed_waiting_manual_output":
                notify_once(
                    run_dir, state,
                    "failed_waiting_manual_output",
                    "Camino A requiere archivo manual",
                    f"40_GPT_CODE_OUTPUT debe archivarse a mano o re-materializar. Phase={phase}.",
                )
                state["watcher_status"] = "waiting_manual_intervention"
                save_state(run_dir, state)
                # R4-05: backoff para no quemar CPU en phase que no progresa sin acción humana
                time.sleep(max(60, interval_seconds * 6))
                continue
            if (run_dir / "70_FINAL_GPT_CLOSURE" / "FINAL_GPT_CLOSURE.DONE").exists():
                state["current_phase"] = "final_gpt_closure_done"
                state["next_action_for_mariano"] = "revisar_70_FINAL_GPT_CLOSURE"
                if terminal_ready(run_dir, state):
                    state["watcher_status"] = "terminal_complete"
                    notify_once(
                        run_dir,
                        state,
                        "terminal_complete",
                        "Camino A finalizado",
                        f"El run {run_dir.name} completo el cierre GPT y esta listo para revision.",
                    )
                    save_state(run_dir, state)
                    return state
                state["watcher_status"] = "terminal_blocked_pending_work"
                save_state(run_dir, state)

            iteration_failed = False
            try:
                if phase in {"cycle_1_auto_ready", "cycle_1_repeat_without_manuals", "cycle_1_auto_running"}:
                    # FIX B-1: inline en vez de subproceso reentrante (que choca con el run-lock)
                    state = run_workflow_action_inline(run_dir, state, action="cycle1_auto_audits", dry_run=dry_run)
                elif phase == "waiting_gpt_primary_output" and (run_dir / "31_GPT_PRIMARY_OUTPUT" / "CONSOLIDACION_GPT_PRIMARIA.DONE").exists():
                    cancel_active_brain_job(run_dir, reason="primary_output_arrived")
                    state = wait_gpt_primary_output(run_dir)
                elif phase == "waiting_gpt_code_output" and (run_dir / "40_GPT_CODE_OUTPUT" / "GPT_CODE_OUTPUT.DONE").exists():
                    cancel_active_brain_job(run_dir, reason="code_output_arrived")
                    state = wait_gpt_code_output(run_dir)
                elif phase == "local_validation_ready":
                    state = validate_gpt_code(run_dir)
                elif phase in {"post_code_adversarial_ready", "post_code_adversarial_running"}:
                    # FIX B-1: inline en vez de subproceso reentrante (que choca con el run-lock)
                    state = run_workflow_action_inline(run_dir, state, action="post_code_adversarial_audits", dry_run=dry_run)
                elif phase == "waiting_gpt_post_code_output" and (run_dir / "61_GPT_ITERATION_OUTPUT" / "AUDITORIA_ADVERSARIAL_POST_CODIGO.DONE").exists():
                    cancel_active_brain_job(run_dir, reason="post_code_output_arrived")
                    state = wait_gpt_post_code_output(run_dir)
            except (SystemExit, subprocess.CalledProcessError, OSError, ValueError) as exc:
                iteration_failed = True
                state = load_state(run_dir)
                state["watcher_last_error"] = safe_error_text(exc)[:500]
                state["watcher_last_error_at"] = utc_now()
                state["watcher_error_streak"] = int(state.get("watcher_error_streak", 0)) + 1
                history_event(state, "watcher_iteration_error", error=state["watcher_last_error"])
                if state["watcher_error_streak"] >= 3:
                    notify_once(
                        run_dir,
                        state,
                        f"watcher_error_{hashlib.sha256(state['watcher_last_error'].encode()).hexdigest()[:12]}",
                        "Camino A requiere intervencion",
                        f"El watcher acumulo {state['watcher_error_streak']} errores: {state['watcher_last_error'][:140]}",
                    )
                save_state(run_dir, state)

            if not iteration_failed and not invalidate_failed:
                # R4-03: solo resetear streak si AMBOS try tuvieron éxito
                state = load_state(run_dir)
                state["watcher_error_streak"] = 0
                save_state(run_dir, state)

            state = launch_primary_brain_job(run_dir, load_state(run_dir))
            save_state(run_dir, state)

            now = time.monotonic()
            if now >= next_heartbeat:
                state = load_state(run_dir)
                state["watcher_last_heartbeat_at"] = utc_now()
                state["watcher_status"] = "active"
                save_state(run_dir, state)
                touch_watcher_lock(run_dir, lock)
                print(json.dumps({
                    "heartbeat": "camino_a_persistent_watcher",
                    "at": state["watcher_last_heartbeat_at"],
                    "run_id": run_dir.name,
                    "current_phase": state.get("current_phase"),
                    "manual_audits_received": state.get("manual_audits_received"),
                    "manual_ingress_delta": max(0, manual_after - manual_before),
                    "manual_window": state.get("manual_window"),
                    "worker_events_delta": len(worker_events),
                    "worker_bus_completed_count": state.get("worker_bus_completed_count", 0),
                }, ensure_ascii=False))
                sys.stdout.flush()
                next_heartbeat = now + WATCH_HEARTBEAT_MINUTES * 60

            if deadline is not None and time.monotonic() > deadline:
                break
            # R10: RESIL-02 - exponential backoff en errores consecutivos
            error_streak = int(load_state(run_dir).get("watcher_error_streak", 0))
            if error_streak > 0:
                backoff = min(interval_seconds * (2 ** min(error_streak, 6)), 300)  # cap 5 min
                time.sleep(max(1, backoff))
            else:
                time.sleep(max(1, interval_seconds))

        state = load_state(run_dir)
        state.update({
            "watcher_status": "paused_by_explicit_timeout",
            "next_action_for_mariano": "reiniciar_watcher_o_continuar_carga_manual",
        })
        history_event(state, "watcher_explicit_timeout", timeout_minutes=timeout_minutes)
        save_state(run_dir, state)
        return state
    finally:
        release_watcher_lock(run_dir, lock)
        # R10: CONC-01 - restaurar signal handlers anteriores
        signal.signal(signal.SIGTERM, _prev_term)
        signal.signal(signal.SIGINT, _prev_int)


def continue_flow(run_dir: Path, *, dry_run: bool) -> dict[str, Any]:
    state = load_state(run_dir)
    state = refresh_manual_ingress(run_dir, state, source_label="continue_flow")
    phase = state.get("current_phase")
    if phase in {"cycle_1_auto_ready", "cycle_1_repeat_without_manuals"}:
        return run_cycle1(run_dir, state, dry_run=dry_run)
    if phase == "waiting_gpt_primary_output":
        return wait_gpt_primary_output(run_dir)
    if phase == "waiting_gpt_code_output":
        return wait_gpt_code_output(run_dir)
    if phase == "local_validation_ready":
        return validate_gpt_code(run_dir)
    if phase == "post_code_adversarial_ready":
        return run_post_code_adversarial_audits(run_dir, state, dry_run=dry_run)
    if phase == "waiting_gpt_post_code_output":
        return wait_gpt_post_code_output(run_dir)
    # R10: STATE-01 - manejar fases bloqueantes y de cierre
    if phase == "blocked":
        # Verificar si se resolvió el bloqueo (ej: iteration limit reset o manual override)
        state = load_state(run_dir)
        if state.get("gpt_post_code_audit_status") == "code_required":
            state["current_phase"] = "waiting_gpt_code_output"
            state["next_action_for_mariano"] = "gpt_debe_generar_nuevo_codigo_completo_en_40_GPT_CODE_OUTPUT"
            history_event(state, "blocked_phase_auto_resolved")
            save_state(run_dir, state)
            return state
        raise SystemExit(f"phase_bloqueada_requiere_intervencion_manual:{state.get('next_action_for_mariano')}")
    if phase == "final_gpt_closure_ready":
        # Verificar si FINAL_GPT_CLOSURE.DONE existe
        closure_done = run_dir / "70_FINAL_GPT_CLOSURE" / "FINAL_GPT_CLOSURE.DONE"
        if closure_done.exists():
            state["current_phase"] = "final_gpt_closure_done"
            state["next_action_for_mariano"] = "revisar_70_FINAL_GPT_CLOSURE"
            history_event(state, "final_gpt_closure_detected")
            save_state(run_dir, state)
            return state
        raise SystemExit("final_gpt_closure_ready_pero_DONE_no_existe")
    if phase in TERMINAL_PHASES:
        return state
    raise SystemExit(f"no_hay_accion_automatica_para_phase:{phase}")


def print_status(run_dir: Path) -> int:
    state = load_state(run_dir)
    # R10: SECRET-01 - redactar secretos antes de imprimir
    print(redact_secrets_text(json.dumps(state, ensure_ascii=False, indent=2)))
    return 0




def canon_mutable_entrypoint(args: argparse.Namespace) -> int:
    """Compatibility bridge from legacy multiaudit CLI to canon mutable runtime.

    This keeps the historical `run_multiaudit_cycle.py` entrypoint usable while
    delegating new plug-and-play runs to start_overnight.py + overnight_master.py.
    It avoids duplicating slot/provider/Claude policy inside the monolith.
    """
    target = Path(args.input).expanduser().resolve()
    if not target.exists():
        print(f"ERROR: target not found: {target}", file=sys.stderr)
        return 1
    runs_dir = Path(args.drive_bus_root).expanduser().resolve()
    profile = args.canon_profile
    start_cmd = [
        sys.executable, str(ROOT / "scripts" / "start_overnight.py"),
        "--target", str(target),
        "--runs-dir", str(runs_dir),
        "--run-label", safe_slug(args.candidate_name or "canon_multiaudit"),
        "--profile", profile,
    ]
    if getattr(args, "canon_dir", ""):
        start_cmd += ["--canon-dir", str(Path(args.canon_dir).expanduser().resolve())]
    cp = subprocess.run(start_cmd, cwd=str(ROOT), text=True, capture_output=True)
    print(cp.stdout, end="")
    if cp.stderr:
        print(cp.stderr, end="", file=sys.stderr)
    if cp.returncode != 0:
        return cp.returncode
    run_dir = None
    for line in cp.stdout.splitlines():
        if line.startswith("Directory:"):
            run_dir = Path(line.split("Directory:", 1)[1].strip())
            break
    if run_dir is None:
        print("ERROR: canon start did not print run directory", file=sys.stderr)
        return 2
    if args.no_start_watcher:
        return 0
    master_cmd = [
        sys.executable, str(ROOT / "scripts" / "overnight_master.py"),
        "--run", str(run_dir),
        "--interval", str(max(1, int(args.watch_interval_seconds or 1))),
        "--timeout-minutes", str(int(args.watch_timeout_minutes or 0)),
        "--max-iterations", str(int(getattr(args, "max_iterations", 1) or 1)),
    ]
    if args.execute_workers:
        master_cmd.append("--execute-workers")
    cp2 = subprocess.run(master_cmd, cwd=str(ROOT), text=True, capture_output=True)
    print(cp2.stdout, end="")
    if cp2.stderr:
        print(cp2.stderr, end="", file=sys.stderr)
    return cp2.returncode

def main() -> int:
    ap = argparse.ArgumentParser(description="Orquestador Drive/AUDIT_BUS con GPT primario y Codex infra-only.")
    ap.add_argument("--input", default="")
    ap.add_argument("--candidate-name", default="")
    ap.add_argument("--target-version", default="")
    ap.add_argument("--drive-bus-root", default=str(DEFAULT_DRIVE_BUS))
    ap.add_argument("--manual-folder", default=str(DEFAULT_MANUAL_FOLDER))
    ap.add_argument("--resume", default="")
    ap.add_argument("--status", default="")
    ap.add_argument("--manual-1", default="")
    ap.add_argument("--manual-2", default="")
    ap.add_argument("--manual-3", default="")
    ap.add_argument("--ingest-manual", action="append", default=[], help="Materializa una cosecha manual .md/.txt; puede repetirse")
    ap.add_argument("--materialize-gpt-code-from-envelope", default="")
    ap.add_argument("--materialize-gpt-code-from-zip", default="")
    ap.add_argument("--materialize-gpt-code-from-file", default="")
    ap.add_argument("--materialize-gpt-post-audit-from-file", default="")
    ap.add_argument("--new-version", default="")
    ap.add_argument("--source-candidate-sha256", default="")
    ap.add_argument("--run-auto-audits-cycle1", action="store_true")
    ap.add_argument("--prepare-gpt-primary-input", action="store_true")
    ap.add_argument("--probe-gpt-drive-write", action="store_true")
    ap.add_argument("--check-gpt-drive-write", action="store_true")
    ap.add_argument("--probe-gpt-api-actions", action="store_true")
    ap.add_argument("--check-gpt-api-actions", action="store_true")
    ap.add_argument("--watch-gpt-output", action="store_true")
    ap.add_argument("--prepare-worker-bus", action="store_true")
    ap.add_argument("--scan-worker-bus", action="store_true")
    ap.add_argument("--scan-worker-bus-readonly", action="store_true",
                    help="R3-03: inspecciona el bus sin mutar state ni tomar lock (diagnóstico con watcher activo)")
    ap.add_argument("--install-watcher-service", action="store_true")
    ap.add_argument("--migrate-stage1", action="store_true")
    ap.add_argument("--open-manual-window", action="store_true")
    ap.add_argument("--no-start-watcher", action="store_true")
    ap.add_argument("--no-open-manual-window", action="store_true")
    ap.add_argument("--wait-gpt-primary-output", action="store_true")
    ap.add_argument("--wait-gpt-code-output", action="store_true")
    ap.add_argument("--validate-gpt-code", action="store_true")
    ap.add_argument("--run-post-code-adversarial-audits", action="store_true")
    ap.add_argument("--prepare-gpt-post-code-input", action="store_true")
    ap.add_argument("--wait-gpt-post-code-output", action="store_true")
    ap.add_argument("--next-command", action="store_true")
    ap.add_argument("--print-gpt-instructions", action="store_true")
    ap.add_argument("--manual-terminal-status", action="store_true")
    ap.add_argument("--continue", dest="continue_run", action="store_true")
    ap.add_argument("--refresh-manual-folder", action="store_true")
    ap.add_argument("--wait-timeout-seconds", type=int, default=0)
    ap.add_argument("--watch-interval-seconds", type=int, default=30)
    ap.add_argument("--watch-timeout-minutes", type=int, default=0, help="0 mantiene el watcher activo hasta estado terminal")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--canon-profile", choices=["with_claude", "without_claude"], default="", help="Use canon mutable runtime instead of legacy monolith start path")
    ap.add_argument("--canon-dir", default="", help="Optional canon directory for --canon-profile")
    ap.add_argument("--execute-workers", action="store_true", help="With --canon-profile, execute supported workers inline")
    ap.add_argument("--max-iterations", type=int, default=1, help="With --canon-profile, max master iterations")
    args = ap.parse_args()

    if args.status:
        return print_status(resolve_run_dir(args.status))
    if args.input and args.canon_profile:
        return canon_mutable_entrypoint(args)
    if args.input:
        if not args.candidate_name or not args.target_version:
            raise SystemExit("--candidate-name y --target-version son obligatorios con --input")
        return start(args)
    if not args.resume:
        raise SystemExit("usar --input, --resume o --status")

    run_dir = resolve_run_dir(args.resume)

    # C-02/CONC-CRIT-02 + CONC-HIGH-06 + R2-CONC-02/04: lock global del run_dir para cualquier comando que mute estado.
    # Comandos que NO mutan estado (status, next-command, print-gpt-instructions, manual-terminal-status,
    # install-watcher-service, prepare-worker-bus, open-manual-window) se eximen.
    # R2-CONC-02: --watch-gpt-output se exime porque toma su propio lock internamente.
    # R2-CONC-04: --scan-worker-bus NO se exime porque process_worker_bus muta state.
    state_mutating_flags = (
        args.migrate_stage1, args.ingest_manual, args.materialize_gpt_code_from_envelope,
        args.materialize_gpt_code_from_zip, args.materialize_gpt_code_from_file,
        args.materialize_gpt_post_audit_from_file, args.manual_1 or args.manual_2 or args.manual_3,
        args.run_auto_audits_cycle1, args.prepare_gpt_primary_input, args.probe_gpt_drive_write,
        args.check_gpt_drive_write, args.probe_gpt_api_actions, args.check_gpt_api_actions,
        args.scan_worker_bus,  # R2-CONC-04: process_worker_bus muta state
        args.wait_gpt_primary_output, args.wait_gpt_code_output,
        args.validate_gpt_code, args.run_post_code_adversarial_audits,
        args.prepare_gpt_post_code_input, args.wait_gpt_post_code_output,
        args.refresh_manual_folder, args.continue_run,
    )
    needs_run_lock = any(state_mutating_flags)
    run_lock = None
    if needs_run_lock:
        # adquirir run lock (mismo flock que watcher; si watcher activo, falla con exit 3)
        run_lock = acquire_watcher_lock(run_dir)
    try:
        if args.migrate_stage1:
            state = migrate_stage1_run(run_dir, install_service=True, open_window=not args.no_open_manual_window)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.install_watcher_service:
            print(install_watcher_launch_agent(run_dir))
            return 0
        if args.prepare_worker_bus:
            print(prepare_worker_bus(run_dir))
            return 0
        if args.scan_worker_bus:
            state, events = process_worker_bus(run_dir, load_state(run_dir))
            print(json.dumps({"state": state, "events": events}, ensure_ascii=False, indent=2))
            return 0
        if args.scan_worker_bus_readonly:
            # R3-03/R4-01: diagnóstico PURAMENTE read-only — solo reconcile + list_pending
            # NO llamar a scan_worker_outputs (mueve bundles OUT/→ACCEPTED y choca con watcher)
            from scripts.camino_a_worker_bus import reconcile_recorded_outputs, list_pending_outputs
            pending = list_pending_outputs(run_dir)
            state_snapshot = read_json(run_dir / STATE_NAME, {})
            recorded = set(state_snapshot.get("worker_bus_recorded_ids", []))
            events_reconciled = reconcile_recorded_outputs(run_dir, recorded_job_ids=recorded)
            print(json.dumps({"pending": pending,
                              "events_reconciled": events_reconciled,
                              "recorded_count": len(recorded)},
                             ensure_ascii=False, indent=2))
            return 0
        if args.open_manual_window:
            print(prepare_manual_inbox(run_dir, open_window=True))
            return 0
        if args.ingest_manual:
            state = ingest_manual_paths(run_dir, args.ingest_manual, source_label="codex_chat_attachment")
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.next_command:
            return print_next_command(run_dir)
        if args.print_gpt_instructions:
            return print_gpt_instructions(run_dir)
        if args.manual_terminal_status:
            return manual_terminal_status(run_dir)
        if args.materialize_gpt_code_from_envelope:
            if not args.new_version:
                raise SystemExit("--new-version es obligatorio con --materialize-gpt-code-from-envelope")
            state = materialize_gpt_code_envelope_fallback(
                run_dir,
                args.materialize_gpt_code_from_envelope,
                new_version=args.new_version,
                source_sha256=args.source_candidate_sha256,
            )
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.materialize_gpt_code_from_zip:
            if not args.new_version:
                raise SystemExit("--new-version es obligatorio con --materialize-gpt-code-from-zip")
            state = materialize_gpt_code_zip_fallback(
                run_dir,
                args.materialize_gpt_code_from_zip,
                new_version=args.new_version,
                source_sha256=args.source_candidate_sha256,
            )
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.materialize_gpt_code_from_file:
            if not args.new_version:
                raise SystemExit("--new-version es obligatorio con --materialize-gpt-code-from-file")
            state = materialize_gpt_code_fallback(
                run_dir,
                args.materialize_gpt_code_from_file,
                new_version=args.new_version,
                source_sha256=args.source_candidate_sha256,
            )
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.materialize_gpt_post_audit_from_file:
            state = materialize_gpt_post_audit_fallback(run_dir, args.materialize_gpt_post_audit_from_file)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.manual_1 or args.manual_2 or args.manual_3:
            if not (args.manual_1 and args.manual_2 and args.manual_3):
                raise SystemExit("se requieren --manual-1 --manual-2 --manual-3")
            state = incorporate_manuals(run_dir, args)
        elif args.run_auto_audits_cycle1:
            state = run_cycle1(run_dir, load_state(run_dir), dry_run=args.dry_run)
        elif args.prepare_gpt_primary_input:
            state = prepare_gpt_primary_input_command(run_dir)
        elif args.probe_gpt_drive_write:
            state = probe_gpt_drive_write(run_dir)
        elif args.check_gpt_drive_write:
            state = check_gpt_drive_write(run_dir)
        elif args.probe_gpt_api_actions:
            state = probe_gpt_api_actions(run_dir)
        elif args.check_gpt_api_actions:
            state = check_gpt_api_actions(run_dir)
        elif args.watch_gpt_output:
            # R2-CONC-02: --watch-gpt-output se exime del lock global porque toma su propio lock.
            # Si run_lock se adquirió (por error de config), liberarlo antes de invocar watch_gpt_output.
            if run_lock is not None:
                release_watcher_lock(run_dir, run_lock)
                run_lock = None
            state = watch_gpt_output(
                run_dir,
                interval_seconds=args.watch_interval_seconds,
                timeout_minutes=args.watch_timeout_minutes,
                dry_run=args.dry_run,
            )
        elif args.wait_gpt_primary_output:
            state = wait_gpt_primary_output(run_dir, timeout_seconds=args.wait_timeout_seconds)
        elif args.wait_gpt_code_output:
            state = wait_gpt_code_output(run_dir, timeout_seconds=args.wait_timeout_seconds)
        elif args.validate_gpt_code:
            state = validate_gpt_code(run_dir)
        elif args.run_post_code_adversarial_audits:
            state = run_post_code_adversarial_audits(run_dir, load_state(run_dir), dry_run=args.dry_run)
        elif args.prepare_gpt_post_code_input:
            state = prepare_gpt_post_code_input_command(run_dir)
        elif args.wait_gpt_post_code_output:
            state = wait_gpt_post_code_output(run_dir, timeout_seconds=args.wait_timeout_seconds)
        elif args.refresh_manual_folder:
            state = refresh_manual_audit_request(run_dir, load_state(run_dir))
        elif args.continue_run:
            state = continue_flow(run_dir, dry_run=args.dry_run)
        else:
            return print_status(run_dir)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    finally:
        if run_lock is not None:
            release_watcher_lock(run_dir, run_lock)


if __name__ == "__main__":
    raise SystemExit(main())
