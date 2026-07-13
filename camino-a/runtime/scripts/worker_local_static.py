#!/usr/bin/env python3
"""worker_local_static.py — Local static analysis worker.

This is what v1.1 called "worker_gateway.py" — local AST/regex analysis
of the target snapshot. It is NOT an external auditor: it does not
call any provider, does not consume API credits, does not provide a
second-brain opinion.

In v1.2.0 (B-4 fix) we rename it honestly so the master and the
terminal gate logic do not confuse this worker with a real Gateway.

Output bundle layout (compatible with worker bus validation):
    13_WORKER_BUS/local_static/OUT/<bundle>/
        result.json
        local_static_report.md
        OUTPUT_MANIFEST.json
        LOCAL_STATIC_OUTPUT.DONE
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    sha256_file, utc_now, read_json, write_json,
    save_state, load_state, history_event,
    write_output_manifest_and_done, assert_no_unredacted_secret,
)
from scripts.candidate_updates import candidate_source, verify_candidate_binding


DANGEROUS_PATTERNS = [
    ("eval(", "Uses eval() — potential code injection"),
    ("exec(", "Uses exec() — potential code injection"),
    ("os.system(", "Uses os.system() — use subprocess instead"),
    ("subprocess.call(shell=True)", "Shell injection risk"),
    ("pickle.loads", "Unsafe deserialization"),
    ("__import__", "Dynamic import — potential bypass"),
    ("ctypes.", "Native code execution"),
    ("open('/etc/", "Accesses system files"),
]


def analyze_target_snapshot(run_dir: Path) -> dict:
    """Analyze the hash-bound current candidate (legacy seed fallback)."""
    snapshot = candidate_source(run_dir)
    if not snapshot.exists():
        return {
            "worker_id": "local_static",
            "status": "no_target_snapshot",
            "findings": [],
            "artifacts": [],
        }

    findings: list[dict] = []
    for py_file in sorted(snapshot.rglob("*.py")):
        if not py_file.is_file() or py_file.is_symlink():
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern, desc in DANGEROUS_PATTERNS:
            if pattern in source:
                findings.append({
                    "file": str(py_file.relative_to(snapshot)),
                    "pattern": pattern,
                    "description": desc,
                    "severity": "HIGH",
                })
        try:
            assert_no_unredacted_secret(source, context=f"local_static/{py_file.name}")
        except SystemExit:
            findings.append({
                "file": str(py_file.relative_to(snapshot)),
                "pattern": "secret_detected",
                "description": "Possible unredacted secret in code",
                "severity": "CRITICAL",
            })

    return {
        "worker_id": "local_static",
        "status": "ok",
        "route_id": "local_static_reference",
        "model_id": "local_static_ruleset",
        "provider_id": "local_static",
        "provider_name": "Local Static Worker",
        "route": "local_static",
        "interface": "local_process",
        "cost_class": "free_local",
        "role": "local_static_auditor",
        "provider": "local_static_analysis",
        "findings": findings,
        "artifacts": [],
    }


def run_local_static(run_dir: Path, dry_run: bool = False) -> dict:
    """Run local static analysis and write a valid bundle."""
    inbox = run_dir / "13_WORKER_BUS" / "local_static" / "IN"
    job_file = inbox / "job.json"
    job = read_json(job_file, {}) if job_file.exists() else {}

    if dry_run:
        return {"status": "dry_run", "worker": "local_static", "job": job}

    bound, binding = verify_candidate_binding(
        run_dir, str(job.get("candidate_sha256") or ""),
    )
    result = analyze_target_snapshot(run_dir) if bound else {
        "worker_id": "local_static", "status": "failed",
        "error": f"candidate_binding_failed:{binding}",
        "findings": [], "artifacts": [],
    }
    result.update({
        "job_id": str(job.get("job_id") or ""),
        "run_id": str(job.get("run_id") or run_dir.name),
        "candidate_sha256": str(job.get("candidate_sha256") or ""),
        "slot_id": str(job.get("slot_id") or "NO_CONSTA"),
    })

    out_dir = (run_dir / "13_WORKER_BUS" / "local_static" / "OUT"
               / f"local_static_{utc_now().replace(':', '-')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    write_json(out_dir / "result.json", result)

    report_lines = [
        "# Local Static Analysis Report",
        "",
        f"Run: {run_dir.name}",
        f"Time: {utc_now()}",
        "",
        f"## Findings ({len(result['findings'])})",
    ]
    for f in result["findings"]:
        report_lines.append(f"- **{f['severity']}** [{f['file']}] {f['description']}")
    if not result["findings"]:
        report_lines.append("- No issues found")
    (out_dir / "local_static_report.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8",
    )

    write_output_manifest_and_done(
        run_dir, str(out_dir.relative_to(run_dir)),
        done_name="LOCAL_STATIC_OUTPUT.DONE",
        stage="local_static_audit",
        candidate_sha256=job.get("candidate_sha256", ""),
        files=("result.json", "local_static_report.md"),
    )

    result["output_dir"] = str(out_dir)
    result["output_bundle"] = str(out_dir.relative_to(run_dir))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Local static analysis worker")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    state = load_state(run_dir)
    result = run_local_static(run_dir, dry_run=args.dry_run)
    history_event(state, "local_static_worker_done", status=result.get("status"))
    save_state(run_dir, state)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
