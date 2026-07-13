#!/usr/bin/env python3
"""primary_brain_adapter.py — fail-closed bridge for the GPT brain.

This process never impersonates GPT and never manufactures a brain verdict.
It prepares a task envelope for Gateway/Drive/manual delivery and materializes
an externally supplied GPT result only after validating its identity, candidate
hash and evidence contract.

Called by overnight_master.py as a subprocess:
    python primary_brain_adapter.py --run-dir RUN_DIR --stage STAGE

Stages:
  - primary_consolidation: consolidate audit findings
  - code_generation: generate code fixes
  - post_code_review: review generated code
  - closure: final closure assessment

Reads:
  - config/roles.json (brain_current)
  - config/primary_brain_policy.json (limits, timeouts)
  - Run state + manual audits from run_dir

Writes:
  - PRIMARY_BRAIN_RESPONSE.json to the appropriate stage directory
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.candidate_updates import UPDATE_SCHEMA, candidate_source  # noqa: E402


def _utc_now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import uuid, tempfile
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Brain task bridge
# ---------------------------------------------------------------------------

def load_brain_config(root: Path = ROOT) -> dict:
    """Load brain configuration."""
    roles = _read_json(root / "config" / "roles.json", {})
    policy = _read_json(root / "config" / "primary_brain_policy.json", {})
    return {
        "brain_current": roles.get("brain_current", "gpt_manual_or_configured"),
        "authority": roles.get("authority", {}),
        "policy": policy,
    }


def collect_input_for_stage(run_dir: Path, stage: str) -> dict:
    """Collect relevant input data for a given stage."""
    state_path = run_dir / "cycle_state.json"
    state = _read_json(state_path, {})

    input_data = {
        "run_id": run_dir.name,
        "stage": stage,
        "slot_id": str(state.get("current_slot") or ""),
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "candidate_version": state.get("current_candidate_version", ""),
        "iteration_number": state.get("iteration_number", 0),
        "phase": state.get("current_phase", ""),
    }

    # Collect manual audits
    manual_dir = run_dir / "10_MANUAL_AUDITS"
    if manual_dir.exists():
        audits = []
        for item in sorted(manual_dir.glob("*.md")):
            if item.is_file() and not item.is_symlink():
                try:
                    text = item.read_text(encoding="utf-8", errors="replace")
                    audits.append({
                        "file": item.name,
                        "sha256": _sha256_file(item),
                        "size": item.stat().st_size,
                        "preview": text[:2000],
                    })
                except OSError:
                    pass
        input_data["manual_audits"] = audits

    # Collect worker results
    input_data["worker_bus_results"] = state.get("worker_bus_results", [])
    input_data["evidence_catalog"] = collect_evidence_catalog(run_dir)

    # Stage-specific input
    if stage == "primary_consolidation":
        # Include candidate code preview
        candidate_dir = run_dir / "00_CANDIDATE"
        if candidate_dir.exists():
            candidates = []
            for item in sorted(candidate_dir.rglob("*.py")):
                if item.is_file() and not item.is_symlink():
                    try:
                        text = item.read_text(encoding="utf-8", errors="replace")
                        candidates.append({
                            "path": str(item.relative_to(candidate_dir)),
                            "preview": text[:3000],
                        })
                    except OSError:
                        pass
            input_data["candidate_files"] = candidates

    elif stage == "code_generation":
        # Include audit findings for code generation
        post_audits = run_dir / "50_POST_CODE_ADVERSARIAL_AUDITS"
        if post_audits.exists():
            findings = []
            for item in sorted(post_audits.rglob("*.md")):
                if item.is_file() and not item.is_symlink():
                    try:
                        findings.append({
                            "file": item.name,
                            "preview": item.read_text(encoding="utf-8", errors="replace")[:2000],
                        })
                    except OSError:
                        pass
            input_data["post_code_findings"] = findings

    return input_data


def collect_evidence_catalog(run_dir: Path, max_files: int = 5000) -> list[dict[str, Any]]:
    """Hash the exact local evidence GPT is allowed to claim it read."""
    roots = [
        candidate_source(run_dir),
        run_dir / "10_MANUAL_AUDITS",
        run_dir / "ACCEPTED",
        run_dir / "REPORTS",
        run_dir / "INTERNAL_LOOP",
    ]
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for item in sorted(root.rglob("*")):
            if not item.is_file() or item.is_symlink():
                continue
            try:
                source = str(item.relative_to(run_dir))
            except ValueError:
                continue
            if source in seen:
                continue
            seen.add(source)
            catalog.append({
                "source": source,
                "sha256": _sha256_file(item),
                "size_bytes": item.stat().st_size,
            })
            if len(catalog) >= max_files:
                return catalog
    return catalog


ALLOWED_STAGES = {
    "primary_consolidation", "code_generation", "post_code_review", "closure",
}
ALLOWED_RESULT_STATUS = {
    "completed", "blocked", "insufficient_evidence", "needs_more_context",
}


def build_brain_task(input_data: dict, brain_config: dict) -> dict:
    """Build a bounded envelope; this is a request, never GPT evidence."""
    stage = str(input_data.get("stage") or "")
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"unknown_stage:{stage}")
    brain = str(brain_config.get("brain_current") or "")
    if brain != "gpt_manual_or_configured":
        raise ValueError(f"unsupported_brain:{brain}")
    task = {
        "schema_version": "camino_gpt_brain_task.v1",
        "run_id": str(input_data.get("run_id") or ""),
        "stage": stage,
        "brain": brain,
        "candidate_sha256": str(input_data.get("candidate_sha256") or ""),
        "iteration": int(input_data.get("iteration_number") or 0),
        "created_at_utc": _utc_now(),
        "delivery": {
            "preferred": "gateway_actions",
            "fallback": "drive_or_manual_batch",
            "openai_api_forbidden": True,
        },
        "input": input_data,
    }
    slot_id = str(input_data.get("slot_id") or "").strip()
    if slot_id:
        task["slot_id"] = slot_id
    return task


def validate_external_response(response: dict, task: dict) -> dict:
    """Validate externally produced GPT evidence against its exact task."""
    if not isinstance(response, dict):
        raise ValueError("brain_response_not_object")
    required = {
        "schema_version", "run_id", "stage", "brain", "candidate_sha256",
        "status", "decision", "evidence_read",
    }
    missing = sorted(required - set(response))
    if missing:
        raise ValueError("brain_response_missing:" + ",".join(missing))
    if response.get("schema_version") != "camino_gpt_brain_result.v1":
        raise ValueError("brain_response_bad_schema")
    for key in ("run_id", "stage", "brain", "candidate_sha256"):
        if str(response.get(key) or "") != str(task.get(key) or ""):
            raise ValueError(f"brain_response_mismatch:{key}")
    # Slot-bound requests cannot be satisfied by a response from another
    # point in the 14-slot flow, even when stage/candidate happen to match.
    if task.get("slot_id") and str(response.get("slot_id") or "") != str(task["slot_id"]):
        raise ValueError("brain_response_mismatch:slot_id")
    if str(response.get("status")) not in ALLOWED_RESULT_STATUS:
        raise ValueError("brain_response_bad_status")
    evidence = response.get("evidence_read")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("brain_response_evidence_required")
    if not all(isinstance(e, dict) and e.get("sha256") and e.get("source") for e in evidence):
        raise ValueError("brain_response_evidence_invalid")
    catalog_entries = (task.get("input") or {}).get("evidence_catalog")
    if not isinstance(catalog_entries, list) or not catalog_entries:
        raise ValueError("brain_task_evidence_catalog_missing")
    catalog = {
        str(item.get("source") or ""): str(item.get("sha256") or "").lower()
        for item in catalog_entries if isinstance(item, dict)
    }
    for item in evidence:
        source = str(item.get("source") or "")
        claimed_sha = str(item.get("sha256") or "").lower()
        expected_sha = catalog.get(source, "")
        if not expected_sha or not hmac.compare_digest(expected_sha, claimed_sha):
            raise ValueError(f"brain_response_evidence_not_in_task:{source}")
    decision = response.get("decision")
    if not isinstance(decision, dict) or not decision.get("verdict"):
        raise ValueError("brain_response_decision_invalid")
    corrections = (
        response.get("corrections_applied") is True
        or decision.get("corrections_applied") is True
        or str(decision.get("verdict") or "") == "CORRECTIONS_APPLIED"
    )
    update = response.get("candidate_update")
    if corrections:
        if not isinstance(update, dict) or update.get("schema_version") != UPDATE_SCHEMA:
            raise ValueError("brain_response_candidate_update_required")
        if str(update.get("source_candidate_sha256") or "") != str(task.get("candidate_sha256") or ""):
            raise ValueError("brain_response_candidate_update_source_mismatch")
        if str(update.get("worker_id") or "") != str(task.get("brain") or ""):
            raise ValueError("brain_response_candidate_update_worker_mismatch")
        if str(update.get("slot_id") or "") != str(task.get("slot_id") or ""):
            raise ValueError("brain_response_candidate_update_slot_mismatch")
        if str(update.get("archive_path") or "") != "candidate_update.zip":
            raise ValueError("brain_response_candidate_update_archive_path")
    elif update is not None:
        raise ValueError("brain_response_candidate_update_without_correction")
    validated = dict(response)
    validated["validated_at_utc"] = _utc_now()
    validated["synthetic"] = False
    return validated


def write_task_request(run_dir: Path, stage: str, task: dict) -> Path:
    request_dirs = {
        "primary_consolidation": "30_GPT_PRIMARY_INPUT",
        "code_generation": "39_GPT_CODE_INPUT",
        "post_code_review": "60_GPT_ITERATION_INPUT",
        "closure": "69_FINAL_GPT_CLOSURE_INPUT",
    }
    out = run_dir / request_dirs[stage]
    out.mkdir(parents=True, exist_ok=True)
    path = out / "BRAIN_TASK_REQUEST.json"
    _write_json(path, task)
    return path


def write_response(
    run_dir: Path, stage: str, response: dict,
    candidate_update_archive: Path | None = None,
) -> Path:
    """Write PRIMARY_BRAIN_RESPONSE.json + manifest + DONE to the stage directory."""
    stage_dirs = {
        "primary_consolidation": "31_GPT_PRIMARY_OUTPUT",
        "code_generation": "40_GPT_CODE_OUTPUT",
        "post_code_review": "61_GPT_ITERATION_OUTPUT",
        "closure": "70_FINAL_GPT_CLOSURE",
    }
    done_names = {
        "primary_consolidation": "PRIMARY_BRAIN_RESPONSE.DONE",
        "code_generation": "GPT_CODE_OUTPUT.DONE",
        "post_code_review": "GPT_ITERATION_OUTPUT.DONE",
        "closure": "FINAL_GPT_CLOSURE.DONE",
    }

    out_dir_name = stage_dirs.get(stage, "31_GPT_PRIMARY_OUTPUT")
    done_name = done_names.get(stage, "PRIMARY_BRAIN_RESPONSE.DONE")
    out_dir = run_dir / out_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    response_path = out_dir / "PRIMARY_BRAIN_RESPONSE.json"
    _write_json(response_path, response)
    (out_dir / "candidate_update.zip").unlink(missing_ok=True)
    if candidate_update_archive is not None:
        shutil.copy2(candidate_update_archive, out_dir / "candidate_update.zip")

    # Write manifest + DONE for compatibility
    import hashlib
    def _sha(p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for chunk in iter(lambda: f.read(1024*1024), b''):
                h.update(chunk)
        return h.hexdigest()

    files = [{
        "path": "PRIMARY_BRAIN_RESPONSE.json",
        "sha256": _sha(response_path),
        "size_bytes": response_path.stat().st_size,
    }]
    update_path = out_dir / "candidate_update.zip"
    if update_path.is_file():
        files.append({
            "path": update_path.name,
            "sha256": _sha(update_path),
            "size_bytes": update_path.stat().st_size,
        })
    manifest = {
        "schema_version": "camino_a_output_manifest.v1",
        "run_id": run_dir.name,
        "stage": stage,
        "candidate_sha256": response.get("candidate_sha256", ""),
        "files": files,
        "created_at_utc": _utc_now(),
    }
    (out_dir / "OUTPUT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    done = out_dir / done_name
    done.write_text("DONE\n", encoding="utf-8")

    return response_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Primary brain adapter")
    parser.add_argument("--run-dir", required=True, help="Run directory")
    parser.add_argument("--stage", required=True, help="Stage name")
    parser.add_argument("--slot-id", default="", help="Canonical slot id binding for this task")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--response-file", default="",
        help="Externally produced camino_gpt_brain_result.v1 JSON to validate/materialize",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 1

    config = load_brain_config()
    input_data = collect_input_for_stage(run_dir, args.stage)
    if args.slot_id:
        input_data["slot_id"] = str(args.slot_id)

    if args.dry_run:
        print(json.dumps({
            "brain": config["brain_current"],
            "stage": args.stage,
            "input_keys": list(input_data.keys()),
        }, indent=2))
        return 0

    try:
        task = build_brain_task(input_data, config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    request_path = write_task_request(run_dir, args.stage, task)

    if not args.response_file:
        print(json.dumps({
            "status": "waiting_external_gpt",
            "synthetic_evidence_created": False,
            "request": str(request_path),
            "delivery": task["delivery"],
        }, ensure_ascii=False, indent=2))
        return 3

    source = Path(args.response_file).expanduser().resolve()
    if not source.is_file() or source.is_symlink() or source.stat().st_size > 16 * 1024 * 1024:
        print("ERROR: invalid response file", file=sys.stderr)
        return 2
    try:
        raw_response = _read_json(source, None)
        response = validate_external_response(raw_response, task)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: external GPT response rejected: {exc}", file=sys.stderr)
        return 2
    update_archive = None
    update = response.get("candidate_update")
    if isinstance(update, dict):
        candidate = source.parent / str(update.get("archive_path") or "")
        if (
            not candidate.is_file() or candidate.is_symlink()
            or candidate.stat().st_size > 64 * 1024 * 1024
            or _sha256_file(candidate) != str(update.get("archive_sha256") or "")
        ):
            print("ERROR: external GPT candidate update archive rejected", file=sys.stderr)
            return 2
        update_archive = candidate
    response_path = write_response(
        run_dir, args.stage, response, candidate_update_archive=update_archive,
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    print(f"\nValidated external GPT result: {response_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
