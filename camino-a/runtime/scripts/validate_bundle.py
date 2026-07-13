#!/usr/bin/env python3
"""validate_bundle.py — Standalone bundle validator.

Wraps `scripts.camino_a_worker_bus._validate_output_bundle` with a
structured return and a `rejection_reason.json` writer, so the master
and tests can call a single authoritative validator.

A bundle is **valid** iff:
  - has at least one *.DONE marker
  - has a parseable OUTPUT_MANIFEST.json (or one of the legacy names)
  - every file listed in the manifest exists, is a regular file (no symlinks)
  - is within size limits
  - sha256 in manifest matches actual sha256 of the file
  - passes secret scanning (with allow_fixture=True)
  - no unlisted files in the bundle directory

Any violation => `valid=False`. The caller MUST move invalid bundles
to REJECTED/ and write rejection_reason.json next to the move target.
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

from scripts.camino_a_worker_bus import _validate_output_bundle, _read_manifest


def validate_bundle(bundle_dir: Path, worker_id: str = "unknown",
                    expected_candidate_sha256: str | None = None) -> dict[str, Any]:
    """Validate a single bundle directory.

    Returns a dict with keys:
      - valid: bool
      - worker_id: str
      - bundle_dir: str
      - bundle_name: str
      - violations: list[str]
      - files: list[{path, size}]
      - manifest: dict | None
    """
    bundle_dir = Path(bundle_dir).resolve()
    result = _validate_output_bundle(bundle_dir, worker_id)
    manifest = _read_manifest(bundle_dir)
    violations = list(result.get("violations", []))

    # Camino A invariant: late/stale audits must be revalidated against
    # the current candidate. File-level SHA validity is not enough.
    # A bundle whose manifest points to an old or unrelated candidate must
    # be rejected before ACCEPTED/ or terminal gates can count it as evidence.
    if expected_candidate_sha256:
        manifest_candidate = (manifest or {}).get("candidate_sha256")
        if manifest_candidate != expected_candidate_sha256:
            violations.append(
                "candidate_sha256_mismatch:"
                f"manifest={manifest_candidate!r}:expected={expected_candidate_sha256!r}"
            )

    # Structural validity is not enough: a worker that reports it could not
    # run (worker_missing/codex_not_found/not_implemented/timeout/failed) must
    # never count as ACCEPTED evidence merely because its result.json bundle is
    # well formed.
    result_json = bundle_dir / "result.json"
    if result_json.exists() and result_json.is_file() and not result_json.is_symlink():
        try:
            payload = json.loads(result_json.read_text(encoding="utf-8"))
            worker_status = str(payload.get("status", "")).lower()
            non_success = {
                "worker_missing", "codex_not_found", "not_implemented",
                "timeout", "failed", "no_job", "dry_run", "quota_limited",
                "probe_failed",
            }
            if worker_status in non_success:
                violations.append(f"worker_non_success_status:{worker_status}")
        except Exception as exc:
            violations.append(f"result_json_unreadable:{type(exc).__name__}")

    valid = result["status"] == "valid" and not violations
    status = "valid" if valid else "invalid"
    return {
        "valid": valid,
        "worker_id": worker_id,
        "bundle_dir": str(bundle_dir),
        "bundle_name": bundle_dir.name,
        "status": status,
        "violations": violations,
        "files": result.get("files", []),
        "manifest": manifest,
    }


def write_rejection_reason(rejected_dir: Path, bundle_name: str, violations: list[str],
                           worker_id: str = "unknown") -> Path:
    """Write rejection_reason.json next to a rejected bundle.

    The file is named `<bundle_name>.rejection_reason.json` so the master
    can later inspect it without parsing directory layout ambiguity.
    """
    rejected_dir.mkdir(parents=True, exist_ok=True)
    reason_path = rejected_dir / f"{bundle_name}.rejection_reason.json"
    reason = {
        "schema_version": "camino_a_rejection_reason.v1",
        "bundle_name": bundle_name,
        "worker_id": worker_id,
        "rejected_at_utc": _utc_now(),
        "violations": violations,
        "violation_count": len(violations),
    }
    reason_path.write_text(
        json.dumps(reason, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return reason_path


def _utc_now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a worker output bundle")
    parser.add_argument("--bundle", required=True, help="Bundle directory to validate")
    parser.add_argument("--worker", default="unknown", help="Worker id for context")
    parser.add_argument("--expected-candidate-sha256", default=None,
                        help="Reject if manifest candidate_sha256 differs from this current candidate SHA")
    args = parser.parse_args()

    bundle = Path(args.bundle).resolve()
    if not bundle.is_dir():
        print(f"INVALID: bundle_dir_not_found:{bundle}", file=sys.stderr)
        return 2

    result = validate_bundle(bundle, args.worker, args.expected_candidate_sha256)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
