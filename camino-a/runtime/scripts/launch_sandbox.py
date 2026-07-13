#!/usr/bin/env python3
"""launch_sandbox.py — plug-and-play local smoke launcher.

Creates a tiny target, starts a canonical run, executes supported local workers
inline, and validates the mechanical lifecycle only.

This is intentionally safe: no Claude API, no OpenAI API, no external Gateway
unless configured. The explicit `sandbox_reference` profile uses local_static
as deterministic evidence and is never presented as a production GPT audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(
    cmd: list[str], *, cwd: Path = ROOT, timeout: int = 180,
    env: dict[str, str] | None = None,
) -> dict:
    cp = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env
    )
    return {
        "cmd": cmd,
        "exit_code": cp.returncode,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
    }


def _extract_run_dir(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("Directory:"):
            return line.split("Directory:", 1)[1].strip()
    raise RuntimeError("could_not_parse_run_dir")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a plug-and-play Camino Nocturno sandbox smoke")
    ap.add_argument(
        "--profile",
        choices=["sandbox_reference", "without_claude", "with_claude"],
        default="sandbox_reference",
    )
    ap.add_argument("--runs-dir", default="", help="Optional runs directory; default temp dir")
    ap.add_argument("--target", default="", help="Optional target dir/file; default generated safe target")
    ap.add_argument("--keep", action="store_true", help="Do not delete temp sandbox")
    ap.add_argument(
        "--execute-codex", action="store_true",
        help="Opt in to a real Codex CLI worker call; disabled in deterministic smoke tests",
    )
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = ap.parse_args()

    temp_ctx = tempfile.TemporaryDirectory(prefix="camino_sandbox_") if not args.keep else None
    base = Path(args.runs_dir).resolve() if args.runs_dir else Path(temp_ctx.name if temp_ctx else tempfile.mkdtemp(prefix="camino_sandbox_keep_"))
    target = Path(args.target).resolve() if args.target else base / "target"
    target.mkdir(parents=True, exist_ok=True)
    sample = target / "sample.py"
    if not sample.exists():
        sample.write_text("def add(a, b):\n    return a + b\n\nassert add(2, 3) == 5\n", encoding="utf-8")

    start = _run([
        sys.executable, str(ROOT / "scripts" / "start_overnight.py"),
        "--target", str(target),
        "--runs-dir", str(base / "runs"),
        "--run-label", "sandbox",
        "--profile", args.profile,
    ])
    if start["exit_code"] != 0:
        out = {"status": "start_failed", "start": start}
        print(json.dumps(out, indent=2, ensure_ascii=False) if args.json else out)
        return 1
    run_dir = Path(_extract_run_dir(start["stdout"]))

    master_env = {
        key: value for key, value in os.environ.items()
        if key not in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
    }
    if not args.execute_codex:
        master_env["CAMINO_DISABLE_CODEX_WORKER"] = "1"

    master = _run([
        sys.executable, str(ROOT / "scripts" / "overnight_master.py"),
        "--run", str(run_dir),
        "--interval", "1",
        "--timeout-minutes", "2",
        "--max-iterations", "1",
        "--execute-workers",
    ], timeout=240, env=master_env)

    state_path = run_dir / "01_STATE" / "cycle_state.json"
    if not state_path.exists():
        state_path = run_dir / "cycle_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    accepted = sorted(p.name for p in (run_dir / "ACCEPTED").iterdir()) if (run_dir / "ACCEPTED").exists() else []
    rejected = sorted(p.name for p in (run_dir / "REJECTED").iterdir()) if (run_dir / "REJECTED").exists() else []
    final_zip = run_dir / "FINAL" / "final_release.zip"
    final_manifest_path = run_dir / "FINAL" / "final_manifest.json"
    final_manifest = (
        json.loads(final_manifest_path.read_text(encoding="utf-8"))
        if final_manifest_path.is_file() else {}
    )
    final_files = final_manifest.get("files") if isinstance(final_manifest.get("files"), list) else []
    final_zip_sha = (
        hashlib.sha256(final_zip.read_bytes()).hexdigest() if final_zip.is_file() else ""
    )
    zip_candidate_files = []
    if final_zip.is_file():
        with zipfile.ZipFile(final_zip) as archive:
            zip_candidate_files = [
                name for name in archive.namelist()
                if name.startswith("final_candidate/") and not name.endswith("/")
            ]
    final_candidate_verified = bool(
        final_files and zip_candidate_files
        and final_zip_sha == str(final_manifest.get("zip_sha256") or "")
        and (state.get("terminal_checks") or {}).get("final_zip_manifest_coherent", {}).get("status") == "pass"
    )
    quality_files = sorted((run_dir / "90_QUALITY_LOG_DELTA").glob("*.entry.json")) if (run_dir / "90_QUALITY_LOG_DELTA").exists() else []
    quality_sqlite_rows = None
    db_path = run_dir / "STATE" / "state.sqlite"
    if db_path.exists():
        try:
            con = sqlite3.connect(str(db_path))
            quality_sqlite_rows = con.execute("SELECT COUNT(*) FROM quality_log").fetchone()[0]
            con.close()
        except Exception:
            quality_sqlite_rows = None
    result = {
        "status": "ok" if master["exit_code"] == 0 and state.get("current_phase") == "closed" and accepted and final_candidate_verified and bool(quality_files) and bool(quality_sqlite_rows) else "failed",
        "profile": args.profile,
        "sandbox_base": str(base),
        "run_dir": str(run_dir),
        "phase": state.get("current_phase"),
        "terminal_reason": state.get("terminal_reason"),
        "accepted": accepted,
        "rejected": rejected,
        "final_zip_exists": final_zip.exists(),
        "final_zip_sha256": final_zip_sha,
        "final_manifest_file_count": len(final_files),
        "zip_candidate_file_count": len(zip_candidate_files),
        "final_candidate_verified": final_candidate_verified,
        "quality_delta_count": len(quality_files),
        "quality_sqlite_rows": quality_sqlite_rows,
        "quality_log_connected": bool(quality_files) and bool(quality_sqlite_rows),
        "start_stdout_tail": start["stdout"][-2000:],
        "master_stdout_tail": master["stdout"][-4000:],
        "master_stderr_tail": master["stderr"][-2000:],
    }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
