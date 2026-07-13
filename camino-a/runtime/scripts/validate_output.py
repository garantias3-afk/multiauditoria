#!/usr/bin/env python3
"""validate_output.py — Validate output manifests and artifacts.

Standalone validation tool that can be called independently or by the master.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    validate_output_manifest, sha256_file,
    assert_file_has_no_unredacted_secret,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate output manifest and artifacts")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--out-dir", required=True, help="Output subdirectory name")
    parser.add_argument("--stage", required=True, help="Expected stage")
    parser.add_argument("--candidate-sha256", default=None, help="Expected candidate SHA")
    parser.add_argument("--required-files", nargs="+", default=[], help="Required file names")
    parser.add_argument("--done-name", default=None, help="DONE file name")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 1

    try:
        manifest = validate_output_manifest(
            run_dir, args.out_dir,
            ("OUTPUT_MANIFEST.json",),
            expected_stage=args.stage,
            expected_candidate_sha256=args.candidate_sha256,
            required_files=tuple(args.required_files),
            done_name=args.done_name,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("\nVALID", file=sys.stderr)
        return 0
    except SystemExit as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
