#!/usr/bin/env python3
"""internal_loop_runner.py — canonical internal agentic loop.

Implements the per-slot internal loop described by the canon
(general_rules.agentic_internal_loop = "audit_patch_reaudit_repeat"):

    audit -> (findings?) -> patch -> new version -> diff -> real tests
          -> reaudit -> repeat until clean OR max_internal_loops reached

On exhaustion it does NOT fake success: it returns status "residual_debt"
with the outstanding findings, honoring
CANON_RUNTIME_POLICY.slot_defaults.advance_with_explicit_residual_debt.

The loop is worker-agnostic. Any object implementing the Worker protocol can
drive it: the real Codex/Claude/Gateway workers, or the bundled local
reference worker (scripts/worker_agentic_local.py) used when no external
agent is available in the environment. The loop itself runs REAL tests
(whatever the worker's ``test`` returns) and computes REAL unified diffs.
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from scripts.run_multiaudit_cycle_legacy import utc_now, write_json


class Worker(Protocol):
    """Contract an agentic worker must satisfy to drive the internal loop."""

    worker_id: str

    def audit(self, workdir: Path) -> list[dict[str, Any]]:
        """Return a list of findings. Empty list => clean."""
        ...

    def patch(self, workdir: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
        """Attempt to fix ``findings`` in-place in ``workdir``.

        Must return: {"applied": bool, "new_version": str, "summary": str}.
        ``applied=False`` means the worker had no fix (drives no-progress/debt).
        """

    def test(self, workdir: Path) -> dict[str, Any]:
        """Run REAL tests on ``workdir``. Return
        {"passed": bool, "returncode": int, "summary": str}."""


@dataclass
class IterationRecord:
    index: int
    findings: list[dict[str, Any]]
    patch_applied: bool
    new_version: str | None
    diff_path: str | None
    test_passed: bool
    test_summary: str
    reaudit_findings: list[dict[str, Any]]
    artifacts_dir: str


@dataclass
class InternalLoopResult:
    slot_id: str
    worker_id: str
    max_internal_loops: int
    evidence_scope: str = ""
    cumulative_candidate_path: str | None = None
    status: str = ""  # clean | clean_no_corrections | residual_debt
    iterations: list[IterationRecord] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    residual_debt: list[dict[str, Any]] = field(default_factory=list)
    advanced: bool = False

    def to_serializable(self) -> dict[str, Any]:
        return {
            "schema_version": "camino_internal_loop_result.v1",
            "slot_id": self.slot_id,
            "worker_id": self.worker_id,
            "max_internal_loops": self.max_internal_loops,
            "evidence_scope": self.evidence_scope,
            "cumulative_candidate_path": self.cumulative_candidate_path,
            "status": self.status,
            "advanced": self.advanced,
            "iteration_count": len(self.iterations),
            "versions": self.versions,
            "residual_debt": self.residual_debt,
            "iterations": [
                {
                    "index": it.index,
                    "findings": it.findings,
                    "patch_applied": it.patch_applied,
                    "new_version": it.new_version,
                    "diff_path": it.diff_path,
                    "test_passed": it.test_passed,
                    "test_summary": it.test_summary,
                    "reaudit_findings": it.reaudit_findings,
                    "artifacts_dir": it.artifacts_dir,
                }
                for it in self.iterations
            ],
        }




def _python_files(workdir: Path) -> list[Path]:
    """Python files that should be independently syntax-checked.

    This deliberately ignores common virtualenv/cache directories so a malicious
    or sloppy worker cannot make the runner spend time in unrelated dependency
    trees.
    """
    ignored = {".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".venv", "venv", "env", "node_modules"}
    out: list[Path] = []
    for p in sorted(workdir.rglob("*.py")):
        if not p.is_file() or p.is_symlink():
            continue
        if any(part in ignored for part in p.relative_to(workdir).parts):
            continue
        out.append(p)
    return out


def _has_pytest_surface(workdir: Path) -> bool:
    if (workdir / "tests").exists():
        return True
    if any(workdir.glob("test_*.py")) or any(workdir.glob("*_test.py")):
        return True
    return any((workdir / name).exists() for name in ("pytest.ini", "pyproject.toml", "setup.cfg"))


def _run_verification_cmd(cmd: list[str], workdir: Path, *, timeout: int = 120) -> dict[str, Any]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env["PYTHONPYCACHEPREFIX"] = str(
        Path(tempfile.gettempdir()) / f"camino_internal_pycache_{os.getuid()}"
    )
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    cp = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return {
        "command": " ".join(cmd),
        "returncode": cp.returncode,
        "stdout_tail": cp.stdout[-2000:],
        "stderr_tail": cp.stderr[-2000:],
        "passed": cp.returncode == 0,
    }


def independent_test_verification(workdir: Path) -> dict[str, Any]:
    """Run local, runner-owned checks in addition to ``worker.test``.

    v1.3.2 hardening: the internal loop no longer trusts a worker's self-report
    alone. A malicious or buggy worker can still claim tests passed, but the
    runner independently executes cheap local gates when a Python surface is
    present:

    * ``python -m compileall -q .`` for syntax/importable bytecode checks.
    * ``python -m pytest -q`` when a pytest surface exists.

    This cannot prove semantic correctness, but it closes the easy fake-test
    class while remaining plug-and-play for arbitrary targets. The full result
    is embedded in each iteration's ``test_results.json``.
    """
    checks: list[dict[str, Any]] = []
    py_files = _python_files(workdir)
    if py_files:
        try:
            checks.append(_run_verification_cmd([sys.executable, "-m", "compileall", "-q", "."], workdir))
        except Exception as exc:
            checks.append({
                "command": f"{sys.executable} -m compileall -q .",
                "returncode": None,
                "passed": False,
                "error": f"{type(exc).__name__}:{exc}",
            })
    if _has_pytest_surface(workdir):
        # Avoid nested pytest-in-pytest deadlocks during the test-suite itself.
        # Real runtime/package smokes run outside PYTEST_CURRENT_TEST and will
        # execute the pytest surface. Compileall still runs inside tests.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            checks.append({
                "command": f"{sys.executable} -m pytest -q",
                "returncode": None,
                "passed": True,
                "status": "skipped_inside_parent_pytest",
            })
        else:
            try:
                checks.append(_run_verification_cmd([sys.executable, "-m", "pytest", "-q"], workdir, timeout=180))
            except Exception as exc:
                checks.append({
                    "command": f"{sys.executable} -m pytest -q",
                    "returncode": None,
                    "passed": False,
                    "error": f"{type(exc).__name__}:{exc}",
                })
    if not checks:
        return {
            "status": "skipped_no_local_test_surface",
            "passed": True,
            "checks": [],
        }
    return {
        "status": "checked",
        "passed": all(bool(c.get("passed")) for c in checks),
        "checks": checks,
    }


def _snapshot_tree(workdir: Path) -> dict[str, str]:
    """Map of relative path -> text content for all files under workdir."""
    out: dict[str, str] = {}
    for p in sorted(workdir.rglob("*")):
        if p.is_file() and not p.is_symlink():
            try:
                out[str(p.relative_to(workdir))] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return out


def _unified_diff(before: dict[str, str], after: dict[str, str], *, version: str) -> str:
    """Compute a REAL unified diff across the whole workdir snapshot."""
    parts: list[str] = []
    for rel in sorted(set(before) | set(after)):
        b = before.get(rel, "").splitlines(keepends=True)
        a = after.get(rel, "").splitlines(keepends=True)
        if b == a:
            continue
        parts.extend(difflib.unified_diff(
            b, a, fromfile=f"a/{rel}", tofile=f"b/{rel} ({version})",
        ))
    return "".join(parts)


def _default_cumulative_workdir(
    workdir: Path, artifacts_dir: Path, slot_id: str,
) -> Path | None:
    """Resolve the established per-run cumulative candidate directory.

    Canonical runs lay out internal-loop files as::

        INTERNAL_LOOP/slot_<id>/workdir
        INTERNAL_LOOP/slot_<id>/artifacts

    Keeping the cumulative candidate beside the slot directories lets every
    required slot consume the preceding slot's corrected state without ever
    writing back into ``INPUT/target_snapshot``.  For callers that use another
    layout, no implicit shared directory is selected.
    """
    workdir = Path(workdir).resolve()
    artifacts_dir = Path(artifacts_dir).resolve()
    slot_root = artifacts_dir.parent
    if (
        slot_root.name != f"slot_{slot_id}"
        or workdir.name != "workdir"
        or workdir.parent != slot_root
        or slot_root.parent.name != "INTERNAL_LOOP"
    ):
        return None
    return slot_root.parent / "cumulative_candidate"


def _replace_tree_from(source: Path, destination: Path) -> None:
    """Replace ``destination`` with a symlink-free copy of ``source``."""
    source = Path(source).resolve()
    destination = Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("internal_loop_cumulative_source_invalid")
    if destination.is_symlink():
        raise RuntimeError("internal_loop_cumulative_destination_symlink")
    for item in source.rglob("*"):
        if item.is_symlink():
            raise RuntimeError(
                f"internal_loop_candidate_symlink_rejected:{item.relative_to(source)}"
            )
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=False)


def run_internal_loop(
    workdir: Path,
    worker: Worker,
    *,
    slot_id: str,
    max_internal_loops: int,
    correction_policy: str,
    blocks_within_limit: bool,
    artifacts_dir: Path,
    cumulative_workdir: Path | None = None,
    on_event=None,
) -> InternalLoopResult:
    """Drive the agentic internal loop for one slot.

    The internal-loop contract always attempts mechanical repair when findings
    exist. ``blocks_within_limit`` only controls the outer slot's treatment of
    unresolved debt; it never suppresses the mandatory
    audit→patch→test→reaudit sequence for ``NO_BLOQUEA`` slots.

    Canonical slot workdirs share ``cumulative_workdir``.  When omitted, the
    standard ``INTERNAL_LOOP/slot_<id>/...`` layout resolves it automatically.
    The immutable ``INPUT`` snapshot is only an initial source and is never
    modified by this function.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    worker_id = str(getattr(worker, "worker_id", "unknown"))
    cumulative = (
        Path(cumulative_workdir).resolve()
        if cumulative_workdir is not None
        else _default_cumulative_workdir(workdir, artifacts_dir, slot_id)
    )
    if cumulative is not None:
        if cumulative.exists():
            _replace_tree_from(cumulative, workdir)
        else:
            cumulative.parent.mkdir(parents=True, exist_ok=True)
            _replace_tree_from(workdir, cumulative)

    result = InternalLoopResult(
        slot_id=slot_id,
        worker_id=worker_id,
        max_internal_loops=max_internal_loops,
        evidence_scope=(
            "mechanical_reference_only"
            if worker_id == "agentic_local"
            else "external_agentic_loop"
        ),
        cumulative_candidate_path=str(cumulative) if cumulative is not None else None,
    )

    def emit(event: str, **extra: Any) -> None:
        if on_event:
            on_event(event, slot_id=slot_id, **extra)

    def persist(event: str, **extra: Any) -> InternalLoopResult:
        if cumulative is not None:
            _replace_tree_from(workdir, cumulative)
        write_json(artifacts_dir / "internal_loop_result.json", result.to_serializable())
        emit(event, **extra)
        return result

    findings = worker.audit(workdir)
    emit("internal_loop_initial_audit", findings=len(findings))

    if not findings:
        result.status = "clean_no_corrections"
        result.advanced = True
        return persist("internal_loop_advance_no_corrections")

    # Every required internal loop attempts repair, including NO_BLOQUEA.  The
    # latter may advance with explicit debt only after a real repair attempt.
    for i in range(1, max_internal_loops + 1):
        it_dir = artifacts_dir / f"iteration_{i:02d}"
        it_dir.mkdir(parents=True, exist_ok=True)
        write_json(it_dir / "findings.json", {"findings": findings, "policy": correction_policy})

        before = _snapshot_tree(workdir)
        patch_res = worker.patch(workdir, findings)
        applied = bool(patch_res.get("applied"))
        new_version = str(patch_res.get("new_version") or f"iter{i}")
        after = _snapshot_tree(workdir)

        diff_text = _unified_diff(before, after, version=new_version)
        diff_path = it_dir / "patch.diff"
        diff_path.write_text(diff_text, encoding="utf-8")

        made_change = bool(diff_text.strip())
        if applied and made_change:
            result.versions.append(new_version)

        # REAL tests on the (possibly) patched workdir.
        # v1.3.2 hardening: do not trust worker.test() alone. The worker
        # still runs its own test command/report, but the runner also executes
        # independent local verification where possible and gates convergence
        # on BOTH passing.
        worker_test_res = worker.test(workdir)
        independent_res = independent_test_verification(workdir)
        test_res = {
            "passed": bool(worker_test_res.get("passed")) and bool(independent_res.get("passed")),
            "returncode": worker_test_res.get("returncode"),
            "summary": str(worker_test_res.get("summary", "")),
            "worker_report": worker_test_res,
            "independent_verification": independent_res,
        }
        write_json(it_dir / "test_results.json", test_res)
        test_passed = bool(test_res.get("passed"))

        # Reaudit — this is the audit of the NEXT state.
        reaudit = worker.audit(workdir)
        write_json(it_dir / "reaudit.json", {"findings": reaudit})

        # Per-iteration human-readable report.
        _write_iteration_report(
            it_dir, i, slot_id, findings, patch_res, test_res, reaudit, made_change,
        )

        result.iterations.append(IterationRecord(
            index=i, findings=findings, patch_applied=applied and made_change,
            new_version=new_version if (applied and made_change) else None,
            diff_path=str(diff_path), test_passed=test_passed,
            test_summary=str(test_res.get("summary", "")),
            reaudit_findings=reaudit, artifacts_dir=str(it_dir),
        ))
        emit("internal_loop_iteration", index=i, patch_applied=applied and made_change,
             test_passed=test_passed, reaudit_findings=len(reaudit))

        # Converged: reaudit clean AND tests pass.
        if not reaudit and test_passed:
            result.status = "clean"
            result.advanced = True
            return persist("internal_loop_converged", iterations=i)

        # No-progress guard: worker could not change anything → stop early with debt.
        if not (applied and made_change):
            result.residual_debt = [
                {"slot_id": slot_id, "kind": "unpatched_finding", **f} for f in reaudit
            ]
            result.status = "residual_debt"
            result.advanced = True  # canon: advance_with_explicit_residual_debt
            return persist(
                "internal_loop_no_progress_residual_debt",
                findings=len(reaudit),
                outer_slot_blocking=blocks_within_limit,
            )

        findings = reaudit

    # Exhausted the loop budget with findings still open.
    result.residual_debt = [
        {"slot_id": slot_id, "kind": "loop_limit_reached", **f} for f in findings
    ]
    result.status = "residual_debt"
    result.advanced = True  # canon: advance_with_explicit_residual_debt
    return persist(
        "internal_loop_exhausted_residual_debt",
        max_internal_loops=max_internal_loops,
        findings=len(findings),
        outer_slot_blocking=blocks_within_limit,
    )


def _write_iteration_report(
    it_dir: Path, index: int, slot_id: str,
    findings: list[dict[str, Any]], patch_res: dict[str, Any],
    test_res: dict[str, Any], reaudit: list[dict[str, Any]], made_change: bool,
) -> None:
    lines = [
        f"# Internal loop — slot {slot_id} — iteration {index}",
        "",
        f"Generated: {utc_now()}",
        "",
        f"## Findings at start ({len(findings)})",
    ]
    for f in findings:
        lines.append(f"- {f.get('severity', 'INFO')}: {f.get('description', json.dumps(f))}")
    lines += [
        "",
        "## Patch",
        f"- applied: {bool(patch_res.get('applied'))}",
        f"- changed files: {made_change}",
        f"- new_version: {patch_res.get('new_version')}",
        f"- summary: {patch_res.get('summary', '')}",
        "",
        "## Tests (real)",
        f"- passed: {bool(test_res.get('passed'))}",
        f"- returncode: {test_res.get('returncode')}",
        f"- summary: {test_res.get('summary', '')}",
        "",
        f"## Reaudit ({len(reaudit)})",
    ]
    for f in reaudit:
        lines.append(f"- {f.get('severity', 'INFO')}: {f.get('description', json.dumps(f))}")
    if not reaudit:
        lines.append("- clean")
    (it_dir / "iteration_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
