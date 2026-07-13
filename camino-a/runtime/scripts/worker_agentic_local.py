#!/usr/bin/env python3
"""worker_agentic_local.py — reference LOCAL agentic worker.

This is the plug-and-play stand-in for the real Codex / Claude Code / Gateway
agentic workers when they are NOT available in the environment (no CLI, no
Gateway URL, forbidden API keys stripped). It exists so the internal agentic
loop can be exercised end-to-end with REAL evidence instead of staying a
conceptual NOT_IMPLEMENTED.

It is deliberately honest about what it is:
  * It never calls a provider, never consumes credits, never needs an API key.
  * Its "audit" and "test" run REAL subprocess pytest / py_compile on the
    candidate workdir — the pass/fail is genuine, not asserted.
  * Its "patch" applies deterministic, content-driven fixes from an ordered
    table. When it has no fix for the current findings it returns
    applied=False, which makes the loop stop with explicit residual_debt
    instead of spinning.

Implements the Worker protocol consumed by internal_loop_runner.run_internal_loop.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Ordered, content-driven fix table. Each entry: (needle, replacement, label).
# A finding is "fixable" iff one of these needles is present in some file.
# This table is intentionally small and explicit — it is a reference worker,
# not a general program repair engine.
_FIX_TABLE: tuple[tuple[str, str, str], ...] = (
    ("return a - b  # CAMINO_AGENTIC_ADD", "return a + b  # CAMINO_AGENTIC_ADD", "fix_add_operator"),
    ("return a - b  # add", "return a + b  # add", "fix_add_operator"),
    ("# CAMINO_AGENTIC_BROKEN\n", "", "remove_broken_marker"),
)


def _verification_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env["PYTHONPYCACHEPREFIX"] = str(
        Path(tempfile.gettempdir()) / f"camino_agentic_pycache_{os.getuid()}"
    )
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return env


class AgenticLocalWorker:
    """Deterministic, provider-free agentic worker for the internal loop."""

    worker_id = "agentic_local"

    def __init__(self, *, test_timeout_seconds: int = 60) -> None:
        self.test_timeout_seconds = test_timeout_seconds
        self._version_counter = 0

    # -- Worker protocol ---------------------------------------------------

    def audit(self, workdir: Path) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        # 1) Compile check (catches syntax errors deterministically).
        for py in sorted(workdir.rglob("*.py")):
            if py.is_symlink() or not py.is_file():
                continue
            cp = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py)],
                capture_output=True, text=True,
                env=_verification_env(),
            )
            if cp.returncode != 0:
                findings.append({
                    "severity": "HIGH",
                    "kind": "compile_error",
                    "file": str(py.relative_to(workdir)),
                    "description": f"py_compile failed for {py.name}",
                    "detail": cp.stderr.strip()[-500:],
                })
        # 2) Real test run (the substantive audit signal).
        test_res = self.test(workdir)
        if not test_res["passed"]:
            findings.append({
                "severity": "HIGH",
                "kind": "failing_tests",
                "description": "candidate test suite is red",
                "detail": test_res["summary"][-500:],
            })
        return findings

    def patch(self, workdir: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply at most ONE known fix per call.

        Applying a single fix per iteration is deliberate: it makes the internal
        loop take real, successive iterations (v1, v2, ...) when a candidate has
        more than one defect, and it makes the no-progress/residual_debt path
        unambiguous when no known fix matches.
        """
        for py in sorted(workdir.rglob("*.py")):
            if py.is_symlink() or not py.is_file():
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except OSError:
                continue
            for needle, replacement, label in _FIX_TABLE:
                if needle in text:
                    new_text = text.replace(needle, replacement, 1)  # one occurrence
                    py.write_text(new_text, encoding="utf-8")
                    self._version_counter += 1
                    return {
                        "applied": True,
                        "new_version": f"agentic_local.v{self._version_counter}",
                        "summary": f"applied: {label} in {py.relative_to(workdir)}",
                    }
        self._version_counter += 1
        return {
            "applied": False,
            "new_version": f"agentic_local.v{self._version_counter}",
            "summary": "no_known_fix_for_findings",
        }

    def test(self, workdir: Path) -> dict[str, Any]:
        test_files = [
            p for p in workdir.rglob("test_*.py")
            if p.is_file() and not p.is_symlink()
        ]
        if test_files:
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(workdir)]
        else:
            py_files = [str(p) for p in sorted(workdir.rglob("*.py"))
                        if p.is_file() and not p.is_symlink()]
            if not py_files:
                return {"passed": True, "returncode": 0, "summary": "no_python_files"}
            cmd = [sys.executable, "-m", "py_compile", *py_files]
        try:
            cp = subprocess.run(
                cmd, cwd=str(workdir), capture_output=True, text=True,
                timeout=self.test_timeout_seconds,
                env=_verification_env(),
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "returncode": 124, "summary": "test_timeout"}
        summary = (cp.stdout + "\n" + cp.stderr).strip()
        return {
            "passed": cp.returncode == 0,
            "returncode": cp.returncode,
            "summary": summary or ("ok" if cp.returncode == 0 else "failed"),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Reference local agentic worker (audit/test a workdir)")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--action", choices=["audit", "test"], default="audit")
    args = ap.parse_args()
    w = AgenticLocalWorker()
    workdir = Path(args.workdir).resolve()
    out = w.audit(workdir) if args.action == "audit" else w.test(workdir)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
