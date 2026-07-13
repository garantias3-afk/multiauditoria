#!/usr/bin/env python3
"""package_final.py — Package the final release ZIP.

Creates:
- final_candidate/
- final_patch.diff
- final_report.md
- external_audit_request_next.md
- final_manifest.json
- final_release.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    sha256_file, utc_now, utc_now_compact, read_json, write_json,
    load_state, history_event, save_state,
)
from scripts.hash_tree import hash_tree
from scripts.candidate_updates import (
    candidate_source, copy_candidate_tree, hash_candidate_tree,
)


def package(run_dir: Path) -> dict:
    """Package the final release."""
    state = load_state(run_dir)
    final_dir = run_dir / "FINAL"
    final_dir.mkdir(parents=True, exist_ok=True)

    candidate_dir = final_dir / "final_candidate"
    candidate_src = candidate_source(run_dir)
    if not candidate_src.is_dir() or candidate_src.is_symlink():
        raise RuntimeError("current_candidate_missing_or_symlink")
    actual_candidate_sha = hash_candidate_tree(candidate_src)
    expected_candidate_sha = str(state.get("current_candidate_sha256") or "")
    if actual_candidate_sha != expected_candidate_sha:
        raise RuntimeError("current_candidate_sha256_drift")
    copy_candidate_tree(candidate_src, candidate_dir)
    seed_manifest = read_json(run_dir / "INPUT" / "target_manifest.json", {})
    if int(seed_manifest.get("total_files") or 0) > 0 and not any(
        item.is_file() for item in candidate_dir.rglob("*")
    ):
        raise RuntimeError("final_candidate_unexpectedly_empty")

    # Generate manifest
    manifest = {
        "schema_version": "camino_a_final_manifest.v1",
        "run_id": run_dir.name,
        "packaged_at": utc_now(),
        "candidate_sha256": actual_candidate_sha,
        "iteration_number": state.get("iteration_number", 0),
        "files": [],
    }

    for item in sorted(candidate_dir.rglob("*")):
        if item.is_file() and not item.is_symlink():
            rel = str(item.relative_to(candidate_dir))
            manifest["files"].append({
                "path": rel,
                "sha256": sha256_file(item),
                "size_bytes": item.stat().st_size,
            })

    write_json(final_dir / "final_manifest.json", manifest)

    # Generate report
    report = f"""# Final Report — {run_dir.name}

Generated: {utc_now()}
Iterations: {state.get('iteration_number', 0)}
Candidate SHA: {state.get('current_candidate_sha256', 'N/A')}

## History

"""
    for event in state.get("history", [])[-50:]:
        report += f"- [{event.get('at', '')}] {event.get('event', '')}\n"

    (final_dir / "final_report.md").write_text(report, encoding="utf-8")

    # Generate external audit request
    audit_request = f"""# External Audit Request — Next Round

Run: {run_dir.name}
Packaged: {utc_now()}

## What to audit

1. Review FINAL/final_candidate/ for correctness
2. Run the test suite
3. Check for remaining security issues
4. Propose improvements

## Previous findings

See final_report.md for history of this run.
"""
    (final_dir / "external_audit_request_next.md").write_text(audit_request, encoding="utf-8")

    # Create ZIP
    zip_path = final_dir / "final_release.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(final_dir.rglob("*")):
            if item.is_file() and item != zip_path:
                zf.write(str(item), str(item.relative_to(final_dir)))

    zip_sha = sha256_file(zip_path)
    manifest["zip_sha256"] = zip_sha
    write_json(final_dir / "final_manifest.json", manifest)

    history_event(state, "final_packaged", zip_sha256=zip_sha)
    save_state(run_dir, state)

    return {
        "status": "packaged",
        "zip_path": str(zip_path),
        "zip_sha256": zip_sha,
        "file_count": len(manifest["files"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Package final release")
    parser.add_argument("--run", required=True, help="Run directory")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    result = package(run_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
