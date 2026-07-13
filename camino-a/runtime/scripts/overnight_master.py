#!/usr/bin/env python3
"""overnight_master.py — The master watcher loop. v1.2.0 — B-1/B-2/B-3 fix.

Single authority for operational state. Handles full lifecycle:
  created → manual_window → running → consolidating → testing → finalizing → closed

CHANGES vs v1.1:

B-1: The master NO LONGER closes when there is no accepted evidence.
     If `consolidating` finds zero valid bundles AND no `--allow-empty`
     was passed, the run lands on `blocked` with
     `terminal_reason='no_accepted_evidence'`. `finalizing` is gated on
     ACCEPTED being non-empty OR an explicit skip acknowledged in
     `state['skip_accepted_evidence']`.

B-2: `harvest_workers()` now calls `validate_bundle.validate_bundle()`
     on every candidate. Only `valid=True` bundles count as accepted.
     Invalid bundles are moved to `REJECTED/<worker>_<bundle>/` with a
     `rejection_reason.json` written by `validate_bundle.write_rejection_reason`.

B-3: `state_db.StateDB` is the authority for `runs.state` and
     `terminal_checks`. Before reaching `closed_success`, the master
     records the four mandated terminal checks
     (no_pending_jobs / no_incomplete_out_bundles / accepted_evidence /
     final_zip_manifest_coherent) and verifies they all pass.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    utc_now, read_json, write_json,
    load_state, save_state, history_event,
    acquire_watcher_lock, release_watcher_lock,
    ensure_bus_dirs, reap_children, sha256_file,
    write_output_manifest_and_done,
    _run_internal_agentic_loop,
)
from scripts.camino_a_worker_bus import (
    prepare_worker_bus, scan_worker_outputs, reconcile_recorded_outputs,
    list_pending_outputs,
)
from scripts.ast_analysis import analyze_file_ast
from scripts.package_final import package as package_final
from scripts.state_db import StateDB
from scripts.validate_bundle import (
    validate_bundle, write_rejection_reason,
)
from scripts.canon_loader import load_canon, resolve_profile, CanonError
from scripts.quality_log import (
    record_quality_event, auditor_from_result, load_result_json,
)
from scripts.slot_execution import executor_for_route, next_slot_decision, validate_slot_evidence
from scripts.slot_runtime import build_slot_plan
from scripts.primary_brain_adapter import (
    build_brain_task, collect_input_for_stage, load_brain_config,
    validate_external_response, write_task_request,
)
from scripts.host_runtime import (
    detect_host as detect_runtime_host,
    load_policy as load_host_runtime_policy,
    resolve_lmstudio_endpoint,
    resolve_peer_settings,
)
from scripts.candidate_updates import (
    CandidateUpdateError, candidate_source, hash_candidate_tree, promote_candidate_update,
    scan_candidate_for_secrets, validate_candidate_update_bundle,
    verify_candidate_binding,
)
from scripts.slot14_handoff import (
    Slot14HandoffError, ensure_slot14_handoff, validate_slot14_handoff_binding,
)


# ---------------------------------------------------------------------------
# Phase machine
# ---------------------------------------------------------------------------

PHASE_TRANSITIONS = {
    "created": "manual_window",
    "manual_window": "running",
    "running": "consolidating",
    "consolidating": "testing",
    "testing": "finalizing",
    "finalizing": "closed",
    "blocked": "blocked",
}

# Phases that count as terminal (master loop breaks).
TERMINAL_PHASES = {"closed", "blocked", "cancelled"}


def advance_phase(state: dict, target: str | None = None) -> str:
    current = state.get("current_phase", "created")
    if target:
        state["current_phase"] = target
    else:
        state["current_phase"] = PHASE_TRANSITIONS.get(current, current)
    return state["current_phase"]


# ---------------------------------------------------------------------------
# Runtime profile helpers
# ---------------------------------------------------------------------------


def runtime_profile_from_state(run_dir: Path, state: dict) -> dict[str, Any]:
    """Return immutable runtime profile snapshot for this run.

    The profile is stored in cycle_state/RUN_CONFIG at run creation time. If a
    legacy run lacks it, fall back to the package canon default.
    """
    if isinstance(state.get("runtime_profile"), dict) and state["runtime_profile"]:
        return state["runtime_profile"]
    cfg = read_json(run_dir / "RUN_CONFIG.json", {})
    if isinstance(cfg.get("runtime_profile"), dict) and cfg["runtime_profile"]:
        return cfg["runtime_profile"]
    try:
        return resolve_profile(load_canon(ROOT), None)
    except CanonError:
        return {"profile_name": "legacy", "claude_enabled": True,
                "enabled_workers": ["codex", "gateway"]}


def worker_is_enabled(profile: dict[str, Any], worker_id: str) -> bool:
    enabled = set(profile.get("enabled_workers") or ["codex", "gateway"])
    disabled = set(profile.get("disabled_workers") or [])
    return worker_id in enabled and worker_id not in disabled


def _canonical_slot_documents(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = read_json(run_dir / "CANON_SLOT_PLAN.json", {})
    routes = read_json(
        run_dir / "INPUT" / "canon_snapshot" / "CANON_PROVIDER_MODEL_ROUTES.v1.json",
        {},
    )
    if not routes:
        routes = read_json(ROOT / "canon" / "CANON_PROVIDER_MODEL_ROUTES.v1.json", {})
    return (plan if isinstance(plan, dict) else {}, routes if isinstance(routes, dict) else {})


def _slot_spec(plan: dict[str, Any], slot_id: str) -> dict[str, Any]:
    for spec in plan.get("slots") or []:
        if isinstance(spec, dict) and str(spec.get("slot_id") or "") == str(slot_id):
            return spec
    return {}


def _gpt_response_paths(run_dir: Path) -> list[Path]:
    return [
        run_dir / "31_GPT_PRIMARY_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        run_dir / "40_GPT_CODE_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        run_dir / "61_GPT_ITERATION_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        run_dir / "70_FINAL_GPT_CLOSURE" / "PRIMARY_BRAIN_RESPONSE.json",
    ]


def _validated_gpt_response(
    run_dir: Path, path: Path, current_sha: str,
) -> dict[str, Any] | None:
    request_dirs = {
        "31_GPT_PRIMARY_OUTPUT": "30_GPT_PRIMARY_INPUT",
        "40_GPT_CODE_OUTPUT": "39_GPT_CODE_INPUT",
        "61_GPT_ITERATION_OUTPUT": "60_GPT_ITERATION_INPUT",
        "70_FINAL_GPT_CLOSURE": "69_FINAL_GPT_CLOSURE_INPUT",
    }
    request_dir = request_dirs.get(path.parent.name)
    if not request_dir:
        return None
    task = read_json(run_dir / request_dir / "BRAIN_TASK_REQUEST.json", {})
    payload = read_json(path, {})
    if (
        not isinstance(task, dict) or not isinstance(payload, dict)
        or payload.get("synthetic") is not False
        or not str(payload.get("validated_at_utc") or "")
    ):
        return None
    validation = validate_bundle(
        path.parent, worker_id="manual_gpt",
        expected_candidate_sha256=current_sha,
    )
    if not validation.get("valid"):
        return None
    try:
        validate_external_response(payload, task)
    except ValueError:
        return None
    return payload


def _internal_loop_result_valid(value: Any, slot_id: str, contract: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("schema_version") != "camino_internal_loop_result.v1":
        return False
    if str(value.get("slot_id") or "") != str(slot_id):
        return False
    if value.get("status") not in {"clean", "clean_no_corrections", "residual_debt"}:
        return False
    try:
        iteration_count = int(value.get("iteration_count") or 0)
        recorded_max = int(value.get("max_internal_loops") or 0)
        allowed_max = int(contract.get("max_iterations") or 10)
    except (TypeError, ValueError):
        return False
    if iteration_count < 0 or recorded_max < 1 or recorded_max > allowed_max or iteration_count > recorded_max:
        return False
    iterations = value.get("iterations")
    if not isinstance(iterations, list) or len(iterations) != iteration_count:
        return False
    residual_debt = value.get("residual_debt")
    if value.get("status") == "residual_debt" and not residual_debt:
        return False
    if value.get("status") in {"clean", "clean_no_corrections"} and residual_debt:
        return False
    return True


def _slot_internal_loop_satisfied(
    run_dir: Path, state: dict[str, Any], slot_id: str, result: Any = None,
) -> bool:
    plan = read_json(run_dir / "CANON_SLOT_PLAN.json", {})
    spec = _slot_spec(plan, slot_id)
    contract = spec.get("internal_loop") if isinstance(spec, dict) else None
    if not isinstance(contract, dict) or contract.get("required") is not True:
        return True
    # ``state.internal_loops`` is runner-owned mechanical QA.  It is useful for
    # cumulative candidate repair, but it is never independent provider evidence
    # and therefore cannot satisfy an external audit slot by itself.
    external = result.get("internal_loop") if isinstance(result, dict) else None
    if not _internal_loop_result_valid(external, slot_id, contract):
        return False
    if str(external.get("evidence_scope") or "") != "external_agentic_loop":
        return False
    reference_workers = {"agentic_local", "local_static", "reference_local_agentic"}
    if str(external.get("worker_id") or "") in reference_workers:
        return False
    if str(result.get("worker_id") or result.get("brain") or "") in reference_workers:
        return False
    return True


def _validated_gpt_slot_result(
    run_dir: Path, state: dict, slot_id: str,
) -> dict[str, Any] | None:
    current_sha = str(state.get("current_candidate_sha256") or "")
    plan = read_json(run_dir / "CANON_SLOT_PLAN.json", {})
    spec = _slot_spec(plan, slot_id)
    policy = str(spec.get("correction_policy") or "").upper()
    blocking = "BLOCKING" in policy or "RESTART" in policy
    for path in _gpt_response_paths(run_dir):
        result = _validated_gpt_response(run_dir, path, current_sha)
        if result is None:
            continue
        if str(result.get("slot_id") or "") != str(slot_id):
            continue
        evidence = result.get("evidence_read")
        decision = result.get("decision")
        findings = result.get("findings")
        internal = result.get("internal_loop") if isinstance(result.get("internal_loop"), dict) else {}
        residual = internal.get("residual_debt") if isinstance(internal.get("residual_debt"), list) else []
        corrections = (
            result.get("corrections_applied") is True
            or (isinstance(decision, dict) and decision.get("corrections_applied") is True)
        )
        if (result.get("status") == "completed"
                and isinstance(evidence, list) and evidence and isinstance(decision, dict)
                and decision.get("verdict") not in {
                    "BLOCKED", "INSUFFICIENT_EVIDENCE", "CORRECTIONS_APPLIED",
                }
                and not corrections
                and (not blocking or (not findings and not residual))
                and _slot_internal_loop_satisfied(run_dir, state, slot_id, result)):
            return result
    return None


def has_validated_gpt_slot_evidence(run_dir: Path, state: dict, slot_id: str) -> bool:
    return _validated_gpt_slot_result(run_dir, state, slot_id) is not None


def _promote_gpt_candidate_update(
    run_dir: Path, state: dict[str, Any], slot_id: str,
) -> dict[str, Any] | None:
    """Promote a candidate archive materialized by the fail-closed GPT adapter."""
    current_sha = str(state.get("current_candidate_sha256") or "")
    for path in _gpt_response_paths(run_dir):
        result = _validated_gpt_response(run_dir, path, current_sha)
        if result is None or not isinstance(result.get("candidate_update"), dict):
            continue
        decision = result.get("decision")
        evidence = result.get("evidence_read")
        if (
            str(result.get("slot_id") or "") != str(slot_id)
            or str(result.get("candidate_sha256") or "") != current_sha
            or not isinstance(decision, dict)
            or not isinstance(evidence, list) or not evidence
            or not _slot_internal_loop_satisfied(run_dir, state, slot_id, result)
        ):
            continue
        try:
            extracted, update = validate_candidate_update_bundle(
                run_dir, path.parent, result, state,
                expected_slot_id=str(slot_id),
            )
            record = promote_candidate_update(run_dir, extracted, update, state)
        except CandidateUpdateError:
            continue
        history_event(
            state, "gpt_candidate_update_promoted_restart_big_loop",
            response=str(path.relative_to(run_dir)), **record,
        )
        return record
    return None


def dispatch_gpt_brain_task(run_dir: Path, state: dict, slot_id: str,
                            slot_spec: dict[str, Any], dry_run: bool = False) -> dict:
    stage = str((slot_spec.get("special") or {}).get("brain_stage") or "")
    if stage not in {"primary_consolidation", "code_generation", "post_code_review", "closure"}:
        return {"worker": "manual_gpt", "status": "configuration_error",
                "slot_id": slot_id, "error": "brain_stage_missing_from_canon"}
    if has_validated_gpt_slot_evidence(run_dir, state, slot_id):
        return {"worker": "manual_gpt", "status": "evidence_present", "slot_id": slot_id}
    input_data = collect_input_for_stage(run_dir, stage)
    input_data["slot_id"] = str(slot_id)
    task = build_brain_task(input_data, load_brain_config())
    if dry_run:
        return {"worker": "manual_gpt", "status": "dry_run", "slot_id": slot_id,
                "stage": stage}
    request = write_task_request(run_dir, stage, task)
    state["primary_brain_status"] = "waiting_external_gpt"
    state["primary_brain_task"] = {
        "slot_id": slot_id,
        "stage": stage,
        "request": str(request.relative_to(run_dir)),
        "candidate_sha256": state.get("current_candidate_sha256", ""),
    }
    history_event(state, "gpt_brain_task_requested", slot_id=slot_id, stage=stage,
                  request=str(request.relative_to(run_dir)))
    return {"worker": "manual_gpt", "status": "waiting_external_gpt",
            "slot_id": slot_id, "stage": stage, "request": str(request)}


def valid_slot_bus_evidence(run_dir: Path, state: dict, slot_id: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    bus = run_dir / "13_WORKER_BUS"
    current_sha = str(state.get("current_candidate_sha256") or "")
    plan = read_json(run_dir / "CANON_SLOT_PLAN.json", {})
    spec = _slot_spec(plan, slot_id)
    policy = str(spec.get("correction_policy") or "").upper()
    blocking = "BLOCKING" in policy or "RESTART" in policy
    if not bus.exists():
        return evidence
    for lane in bus.iterdir():
        out = lane / "OUT"
        if not out.is_dir():
            continue
        for bundle in out.iterdir():
            if not bundle.is_dir() or bundle.is_symlink() or not list(bundle.glob("*.DONE")):
                continue
            validation = validate_bundle(bundle, lane.name, current_sha)
            if not validation.get("valid"):
                continue
            result = read_json(bundle / "result.json", {})
            ok, reason = validate_slot_evidence(
                result, slot_id=str(slot_id), candidate_sha256=current_sha,
            )
            if ok and result.get("corrections_applied") is True:
                # A correction is evidence only after the hash-bound complete
                # candidate update has been promoted. The pre-promotion bundle
                # cannot complete its slot against the old candidate.
                ok, reason = False, "candidate_correction_not_promoted"
            findings = result.get("findings") if isinstance(result.get("findings"), list) else []
            internal = result.get("internal_loop") if isinstance(result.get("internal_loop"), dict) else {}
            residual = internal.get("residual_debt") if isinstance(internal.get("residual_debt"), list) else []
            if ok and blocking and (
                findings or residual or result.get("status") in {"bug_found", "patch_proposed"}
            ):
                ok, reason = False, "blocking_slot_has_unresolved_findings"
            if ok and not _slot_internal_loop_satisfied(run_dir, state, slot_id, result):
                ok, reason = False, "internal_loop_evidence_missing_or_invalid"
            if ok:
                evidence.append({
                    "lane": lane.name,
                    "bundle": str(bundle),
                    "route_id": result.get("route_id"),
                    "status": result.get("status"),
                    "findings_count": len(findings),
                    "residual_debt_count": len(residual),
                })
            elif reason == "status_not_evidence" and result.get("status") == "manual_audit_ingested":
                # Manual multi-format submissions use a distinct honest status;
                # identity/slot/candidate still have to match exactly.
                if (str(result.get("slot_id") or "") == str(slot_id)
                        and str(result.get("candidate_sha256") or "") == current_sha
                        and _slot_internal_loop_satisfied(run_dir, state, slot_id, result)):
                    evidence.append({"lane": lane.name, "bundle": str(bundle),
                                     "route_id": result.get("route_id"),
                                     "status": result.get("status")})
    return evidence


def _promote_candidate_update_from_harvest(
    run_dir: Path,
    state: dict[str, Any],
    harvest: dict[str, Any],
    slot_id: str,
    db: StateDB,
) -> dict[str, Any] | None:
    """Promote one exact job-bound correction and restart the canonical loop."""
    allowed_non_success = {"worker_non_success_status:failed"}
    for entry in harvest.get("details", []):
        bundle = Path(str(entry.get("bundle") or ""))
        result = read_json(bundle / "result.json", {})
        if not isinstance(result, dict) or not isinstance(result.get("candidate_update"), dict):
            continue
        violations = {str(value) for value in (entry.get("violations") or [])}
        structural = {value for value in violations if value not in allowed_non_success}
        if structural or not str(entry.get("job_id") or ""):
            entry["valid"] = False
            entry.setdefault("violations", []).append("candidate_update_job_or_bundle_invalid")
            continue
        try:
            extracted, update = validate_candidate_update_bundle(
                run_dir, bundle, result, state, expected_slot_id=str(slot_id),
            )
            record = promote_candidate_update(run_dir, extracted, update, state)
        except CandidateUpdateError as exc:
            entry["valid"] = False
            entry.setdefault("violations", []).append(f"candidate_update_invalid:{exc}")
            continue
        entry["candidate_update_promoted"] = True
        entry["valid"] = False  # correction evidence is not approval evidence
        db.update_job_status(str(entry["job_id"]), "completed_correction")
        history_event(
            state, "candidate_update_promoted_restart_big_loop",
            job_id=entry["job_id"], worker=entry.get("worker"), **record,
        )
        return record
    return None


def _complete_slot(state: dict, plan: dict[str, Any], slot_id: str,
                   evidence: list[dict[str, Any]] | None = None) -> None:
    completed = {str(value) for value in (state.get("completed_slots") or [])}
    completed.add(str(slot_id))
    ordered = [str(spec.get("slot_id")) for spec in (plan.get("slots") or []) if isinstance(spec, dict)]
    state["completed_slots"] = [sid for sid in ordered if sid in completed]
    remaining = [sid for sid in ordered if sid not in completed]
    state["current_slot"] = remaining[0] if remaining else None
    inflight = state.get("slot_inflight_job_ids")
    if isinstance(inflight, dict):
        inflight.pop(str(slot_id), None)
    history_event(state, "canonical_slot_completed", slot_id=slot_id,
                  evidence=evidence or [], next_slot=state.get("current_slot"))


def _record_slot_debt(state: dict, slot_id: str, role: str, reason: str,
                      routes: list[str]) -> None:
    debt = list(state.get("residual_debt") or [])
    key = (str(slot_id), str(reason), tuple(routes))
    if not any((str(item.get("slot_id")), str(item.get("reason")),
                tuple(item.get("routes") or [])) == key for item in debt if isinstance(item, dict)):
        debt.append({"slot_id": str(slot_id), "role": role, "reason": reason,
                     "routes": list(routes), "recorded_at_utc": utc_now()})
    state["residual_debt"] = debt


def _record_evidence_residual_debt(
    state: dict[str, Any], slot_id: str, spec: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> None:
    count = sum(
        int(item.get("findings_count") or 0) + int(item.get("residual_debt_count") or 0)
        for item in evidence if isinstance(item, dict)
    )
    if count:
        _record_slot_debt(
            state, slot_id, str(spec.get("role") or ""),
            f"nonblocking_evidence_with_residual_debt:{count}",
            [str(item.get("route_id") or item.get("lane") or "") for item in evidence],
        )

# ---------------------------------------------------------------------------
# Worker dispatch (writes job.json into the worker inbox)
# ---------------------------------------------------------------------------

def dispatch_codex(run_dir: Path, state: dict, db: StateDB | None = None,
                   dry_run: bool = False) -> dict:
    """Dispatch Codex worker by writing a job.json into its inbox."""
    if dry_run:
        return {"worker": "codex", "status": "dry_run"}

    ws = run_dir / "WORKSPACES" / "codex"
    ws.mkdir(parents=True, exist_ok=True)

    snapshot = candidate_source(run_dir)
    if snapshot.exists():
        for item in snapshot.rglob("*"):
            if item.is_file() and not item.is_symlink():
                rel = item.relative_to(snapshot)
                dst = ws / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)

    agents = ROOT / "generated" / "AGENTS.md"
    if agents.exists():
        shutil.copy2(agents, ws / "AGENTS.md")

    inbox = run_dir / "13_WORKER_BUS" / "codex" / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    job_id = f"JOB_codex_{utc_now().replace(':', '-').replace('.', '')}"
    write_json(inbox / "job.json", {
        "job_id": job_id,
        "run_id": run_dir.name,
        "worker_id": "codex",
        "task": "audit_and_fix",
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "iteration": state.get("iteration_number", 0),
        "workspace": str(ws),
        "dispatched_at": utc_now(),
    })

    if db is not None:
        db.insert_job(run_id=run_dir.name, worker_id="codex",
                      stage="audit_and_fix", job_id=job_id,
                      candidate_sha256=state.get("current_candidate_sha256", ""),
                      status="dispatched")
        db.event("codex_dispatched", run_id=run_dir.name,
                 component="master", details={"job_id": job_id})

    history_event(state, "codex_dispatched", job_id=job_id)
    return {"worker": "codex", "status": "dispatched",
            "workspace": str(ws), "job_id": job_id}


def dispatch_gateway(run_dir: Path, state: dict, db: StateDB | None = None,
                     dry_run: bool = False, *, slot_id: str = "",
                     route_ids: list[str] | None = None,
                     slot_role: str = "",
                     internal_loop_contract: dict[str, Any] | None = None) -> dict:
    """Dispatch Gateway worker by writing a job.json into its inbox."""
    if dry_run:
        return {"worker": "gateway", "status": "dry_run"}

    inbox = run_dir / "13_WORKER_BUS" / "gateway" / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    job_id = f"JOB_gateway_{utc_now().replace(':', '-').replace('.', '')}"
    write_json(inbox / "job.json", {
        "job_id": job_id,
        "run_id": run_dir.name,
        "worker_id": "gateway",
        "task": "external_audit",
        "slot_id": str(slot_id or state.get("current_slot") or ""),
        "slot_role": slot_role,
        "route_ids": list(route_ids or []),
        "internal_loop_contract": dict(internal_loop_contract or {}),
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "iteration": state.get("iteration_number", 0),
        "dispatched_at": utc_now(),
    })

    if db is not None:
        db.insert_job(run_id=run_dir.name, worker_id="gateway",
                      stage="external_audit", job_id=job_id,
                      candidate_sha256=state.get("current_candidate_sha256", ""),
                      status="dispatched")
        db.event("gateway_dispatched", run_id=run_dir.name,
                 component="master", details={"job_id": job_id})

    history_event(state, "gateway_dispatched", job_id=job_id)
    return {"worker": "gateway", "status": "dispatched", "job_id": job_id,
            "slot_id": str(slot_id or state.get("current_slot") or ""),
            "route_ids": list(route_ids or [])}


def _build_lmstudio_slot_prompt(run_dir: Path, slot_id: str, slot_role: str,
                                max_chars: int = 200000) -> dict[str, Any]:
    """Create a bounded, auditable local-model context without claiming completeness."""
    snapshot = candidate_source(run_dir)
    prompt_dir = run_dir / "REPORTS" / "slot_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"slot_{slot_id}_lmstudio.md"
    text_suffixes = {
        ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
        ".ini", ".cfg", ".sh", ".js", ".ts", ".tsx", ".jsx", ".sql",
    }
    sections = [
        "# Canonical local audit request",
        "",
        f"slot_id: {slot_id}",
        f"slot_role: {slot_role}",
        "",
        "Audit the supplied evidence only. Report omissions explicitly. Do not claim global approval.",
        "Return findings with severity, path and evidence, followed by residual uncertainty.",
        "",
    ]
    used = sum(len(value) + 1 for value in sections)
    omitted: list[dict[str, Any]] = []
    included = 0
    for item in sorted(snapshot.rglob("*")) if snapshot.exists() else []:
        if not item.is_file() or item.is_symlink():
            continue
        relative = str(item.relative_to(snapshot))
        size = item.stat().st_size
        if item.suffix.lower() not in text_suffixes or size > 1024 * 1024:
            omitted.append({"path": relative, "size_bytes": size, "reason": "binary_or_oversize"})
            continue
        try:
            content = item.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            omitted.append({"path": relative, "size_bytes": size, "reason": "not_utf8_readable"})
            continue
        block = f"\n## FILE {relative}\n\n```\n{content}\n```\n"
        if used + len(block) > max_chars:
            omitted.append({"path": relative, "size_bytes": size, "reason": "context_budget"})
            continue
        sections.append(block)
        used += len(block)
        included += 1
    sections += [
        "", "## Coverage", "",
        f"included_files: {included}",
        f"omitted_files: {len(omitted)}",
        "omitted_manifest: " + json.dumps(omitted, ensure_ascii=False, separators=(",", ":")),
    ]
    prompt_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return {
        "path": str(prompt_path.relative_to(run_dir)),
        "included_files": included,
        "omitted_files": omitted,
        "context_complete": not omitted,
        "size_chars": used,
    }


def dispatch_lmstudio(run_dir: Path, state: dict, route_ids: list[str],
                      slot_id: str, slot_role: str,
                      internal_loop_contract: dict[str, Any] | None = None,
                      db: StateDB | None = None, dry_run: bool = False) -> dict:
    if dry_run:
        return {"worker": "lmstudio_bridge", "status": "dry_run", "slot_id": slot_id,
                "route_ids": list(route_ids)}
    context = _build_lmstudio_slot_prompt(run_dir, slot_id, slot_role)
    if (internal_loop_contract or {}).get("required"):
        prompt_path = Path(context["path"])
        if not prompt_path.is_absolute():
            prompt_path = run_dir / prompt_path
        with prompt_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n\n## Mandatory internal loop contract\n\n"
                + json.dumps(internal_loop_contract, ensure_ascii=False, indent=2)
                + "\n\nReturn ONLY one JSON object with keys verdict, summary, findings, "
                  "corrections_applied, tests and internal_loop. internal_loop must use "
                  "schema_version=camino_internal_loop_result.v1, this exact slot_id, "
                  "evidence_scope=external_agentic_loop, your route/model identity as "
                  "worker_id, iteration_count, max_internal_loops, iterations and "
                  "residual_debt. This chat transport cannot mutate files: never claim "
                  "corrections_applied. If a change is needed, return status=residual_debt "
                  "and describe it explicitly; use clean/clean_no_corrections only after "
                  "a genuine re-audit of the supplied evidence.\n"
            )
    inbox = run_dir / "13_WORKER_BUS" / "lmstudio_bridge" / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    job_id = f"JOB_lmstudio_{slot_id}_{utc_now().replace(':', '-').replace('.', '')}"
    write_json(inbox / "job.json", {
        "job_id": job_id,
        "run_id": run_dir.name,
        "worker_id": "lmstudio_bridge",
        "task": "slot_scoped_local_audit",
        "slot_id": slot_id,
        "slot_role": slot_role,
        "route_ids": list(route_ids),
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "prompt_file": context["path"],
        "context_coverage": context,
        "internal_loop_contract": dict(internal_loop_contract or {}),
        "pool_size": 2,
        "dispatched_at": utc_now(),
    })
    if db is not None:
        db.insert_job(run_id=run_dir.name, worker_id="lmstudio_bridge",
                      stage=f"slot_{slot_id}_lmstudio", job_id=job_id,
                      candidate_sha256=state.get("current_candidate_sha256", ""),
                      status="dispatched")
    history_event(state, "lmstudio_dispatched", job_id=job_id, slot_id=slot_id,
                  route_ids=list(route_ids), context_complete=context["context_complete"])
    return {"worker": "lmstudio_bridge", "status": "dispatched", "job_id": job_id,
            "slot_id": slot_id, "route_ids": list(route_ids), "context": context}


def _latest_claude_nonapproval(run_dir: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    out = run_dir / "13_WORKER_BUS" / "claude_code" / "OUT"
    bundles = sorted(
        (path for path in out.iterdir() if path.is_dir() and not path.is_symlink()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    ) if out.exists() else []
    current_sha = str(state.get("current_candidate_sha256") or "")
    for bundle in bundles:
        result = read_json(bundle / "result.json", {})
        if not isinstance(result, dict) or result.get("approval_eligible") is True:
            continue
        validation = validate_bundle(
            bundle, worker_id="claude_code", expected_candidate_sha256=current_sha,
        )
        structural_violations = [
            value for value in validation.get("violations", [])
            if not str(value).startswith("worker_non_success_status:")
        ]
        if structural_violations:
            continue
        manifest = validation.get("manifest") or {}
        if result.get("worker_id") != "claude_code":
            continue
        if str(result.get("run_id") or "") != run_dir.name:
            continue
        if str(result.get("run_id") or "") != run_dir.name:
            continue
        if str(result.get("slot_id") or "") != "14":
            continue
        if current_sha and str(result.get("candidate_sha256") or "") != current_sha:
            continue
        if not _job_binding_exists(
            run_dir,
            str(result.get("job_id") or ""),
            "claude_code",
            current_sha,
            allowed_statuses={"dispatched", "running", "failed", "rejected", "no_output"},
        ):
            # A syntactically plausible bundle dropped into OUT is not proof
            # that the master actually launched the Claude attempt.
            continue
        error_class = str(result.get("error_class") or "")
        mapping = {
            "auth_missing": "claude_auth_missing",
            "worker_missing": "claude_worker_missing",
            "auth_check_failed": "claude_auth_check_failed",
            "auth_check_invalid_json": "claude_auth_check_failed",
            "auth_check_timeout": "claude_auth_check_timeout",
            "claude_cli_nonzero": "claude_cli_nonzero",
            "cli_execution_failed": "claude_cli_execution_failed",
            "timeout": "claude_timeout",
        }
        trigger = mapping.get(error_class)
        if trigger:
            public = {key: value for key, value in result.items() if not key.startswith("_")}
            public["bundle"] = str(bundle.relative_to(run_dir))
            public["source"] = "validated_claude_bundle"
            public["output_manifest_sha256"] = sha256_file(bundle / "OUTPUT_MANIFEST.json")
            public["done_marker"] = sorted(path.name for path in bundle.glob("*.DONE"))[0]
            public["manifest_stage"] = str(manifest.get("stage") or "")
            return {"trigger": trigger, "attempt": public}
    return None


def dispatch_codex_fallback(run_dir: Path, state: dict, *,
                            claude_failure: dict[str, Any],
                            db: StateDB | None = None,
                            dry_run: bool = False) -> dict:
    if dry_run:
        return {"worker": "codex_fallback", "status": "dry_run", "slot_id": "14"}
    try:
        handoff = ensure_slot14_handoff(run_dir, state, path_id="camino_a")
    except Slot14HandoffError as exc:
        return {
            "worker": "codex_fallback", "status": "invalid_slot14_handoff",
            "slot_id": "14", "error": str(exc),
        }
    inbox = run_dir / "13_WORKER_BUS" / "codex_fallback" / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    job_id = f"JOB_codex_fallback_{utc_now().replace(':', '-').replace('.', '')}"
    write_json(inbox / "job.json", {
        "job_id": job_id,
        "run_id": run_dir.name,
        "worker_id": "codex_fallback",
        "task": "slot14_subscription_fallback",
        "slot_id": "14",
        "route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "prior_slots_complete": True,
        "fallback_trigger": claude_failure["trigger"],
        "claude_attempt": claude_failure["attempt"],
        **handoff,
        "audit_request_sha256": handoff["request_sha256"],
        "dispatched_at": utc_now(),
    })
    if db is not None:
        db.insert_job(run_id=run_dir.name, worker_id="codex_fallback",
                      stage="slot_14_codex_subscription_fallback", job_id=job_id,
                      candidate_sha256=state.get("current_candidate_sha256", ""),
                      status="dispatched")
    history_event(state, "codex_subscription_fallback_dispatched", job_id=job_id,
                  trigger=claude_failure["trigger"],
                  audit_request_sha256=handoff["request_sha256"])
    return {"worker": "codex_fallback", "status": "dispatched", "job_id": job_id,
            "slot_id": "14", "fallback_trigger": claude_failure["trigger"]}


def dispatch_claude_code(run_dir: Path, state: dict, db: StateDB | None = None,
                         dry_run: bool = False) -> dict:
    """Dispatch Claude Code worker by writing a job.json into its inbox.

    This never uses Claude API. The actual worker wrapper performs its own
    env preflight and will return worker_missing/skipped if Claude CLI is not
    available or forbidden API credentials are present.
    """
    if dry_run:
        return {"worker": "claude_code", "status": "dry_run"}

    completed_slots = {str(value) for value in (state.get("completed_slots") or [])}
    required_prior = {str(value) for value in range(1, 14)}
    if completed_slots != required_prior:
        return {
            "worker": "claude_code",
            "status": "deferred_prior_slots",
            "slot_id": "14",
            "missing_slots": sorted(required_prior - completed_slots, key=int),
        }

    try:
        handoff = ensure_slot14_handoff(run_dir, state, path_id="camino_a")
    except Slot14HandoffError as exc:
        return {
            "worker": "claude_code", "status": "invalid_slot14_handoff",
            "slot_id": "14", "error": str(exc),
        }

    inbox = run_dir / "13_WORKER_BUS" / "claude_code" / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    job_id = f"JOB_claude_code_{utc_now().replace(':', '-').replace('.', '')}"
    profile = runtime_profile_from_state(run_dir, state)
    write_json(inbox / "job.json", {
        "job_id": job_id,
        "run_id": run_dir.name,
        "worker_id": "claude_code",
        "task": "claude_code_limited_review",
        "slot_id": "14",
        "route_id": "claude_code_subscription_cli",
        "prior_slots_complete": True,
        "instructions": (
            "Leer el pedido 13→14 ligado por SHA; auditar el delta y sus fronteras, "
            "intentar refutar los fixes y conclusiones previas, ejecutar controles "
            "independientes y aprobar sólo sin correcciones ni hallazgos."
        ),
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "iteration": state.get("iteration_number", 0),
        "runtime_profile": profile.get("profile_name"),
        **handoff,
        "audit_request_sha256": handoff["request_sha256"],
        "dispatched_at": utc_now(),
    })

    if db is not None:
        db.insert_job(run_id=run_dir.name, worker_id="claude_code",
                      stage="claude_code_limited_review", job_id=job_id,
                      candidate_sha256=state.get("current_candidate_sha256", ""),
                      status="dispatched")
        db.event("claude_code_dispatched", run_id=run_dir.name,
                 component="master", details={"job_id": job_id})

    history_event(state, "claude_code_dispatched", job_id=job_id,
                  audit_request_sha256=handoff["request_sha256"])
    return {"worker": "claude_code", "status": "dispatched", "job_id": job_id}




def dispatch_local_static(run_dir: Path, state: dict, db: StateDB | None = None,
                          dry_run: bool = False) -> dict:
    """Dispatch deterministic local static worker.

    This worker is intentionally local, cheap and plug-and-play. It is not an
    external auditor, but it gives the sandbox/default profile valid local
    evidence so the lifecycle can complete without Codex/Claude/Gateway being
    installed.
    """
    if dry_run:
        return {"worker": "local_static", "status": "dry_run"}

    inbox = run_dir / "13_WORKER_BUS" / "local_static" / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    job_id = f"JOB_local_static_{utc_now().replace(':', '-').replace('.', '')}"
    write_json(inbox / "job.json", {
        "job_id": job_id,
        "run_id": run_dir.name,
        "worker_id": "local_static",
        "task": "local_static_audit",
        "candidate_sha256": state.get("current_candidate_sha256", ""),
        "iteration": state.get("iteration_number", 0),
        "dispatched_at": utc_now(),
    })

    if db is not None:
        db.insert_job(run_id=run_dir.name, worker_id="local_static",
                      stage="local_static_audit", job_id=job_id,
                      candidate_sha256=state.get("current_candidate_sha256", ""),
                      status="dispatched")
        db.event("local_static_dispatched", run_id=run_dir.name,
                 component="master", details={"job_id": job_id})

    history_event(state, "local_static_dispatched", job_id=job_id)
    return {"worker": "local_static", "status": "dispatched", "job_id": job_id}


def _db_job_attempt_context(db: StateDB | None, run_id: str, worker: str, job_id: str | None) -> tuple[str, str]:
    """Return (job_id, attempt_id) for a worker execution, creating attempt rows.

    v1.3.2: attempts are no longer decorative. Every inline execution, skip,
    timeout or failure is represented in SQLite attempts and linked to outputs
    when possible.
    """
    if db is None:
        return job_id or "", ""
    if not job_id:
        job = db.latest_job_for_worker(run_id, worker)
        job_id = str(job.get("job_id")) if job else ""
    if not job_id:
        return "", ""
    db.update_job_status(job_id, "running")
    attempt_id = db.record_attempt(
        job_id=job_id,
        worker_id=worker,
        started_at=utc_now(),
        status="running",
    )
    return job_id, attempt_id


def _db_finish_attempt(db: StateDB | None, attempt_id: str, *, status: str,
                       exit_code: int | None = None, timeout_seconds: int | None = None,
                       error_class: str | None = None) -> None:
    if db is None or not attempt_id:
        return
    db.conn.execute(
        """UPDATE attempts SET ended_at = ?, status = ?, exit_code = ?,
                              timeout_seconds = ?, error_class = ?
           WHERE attempt_id = ?""",
        (utc_now(), status, exit_code, timeout_seconds, error_class, attempt_id),
    )
    db.conn.commit()


def _record_worker_execution_quality(run_dir: Path, worker: str, status: str,
                                     *, job_id: str = "", attempt_id: str = "",
                                     db: StateDB | None = None, details: dict[str, Any] | None = None) -> None:
    """Record provider/model quality signal for a worker execution/skip.

    Skips (CLI missing, gateway not configured) are operational quality events:
    they explain why a route/provider did not contribute evidence in this run.
    """
    result = {"worker_id": worker, "status": status, **(details or {})}
    auditor = auditor_from_result(worker, result, stage="worker_execution")
    record_quality_event(
        run_dir,
        event="worker_execution_status",
        auditor=auditor,
        artifact={"job_id": job_id, "attempt_id": attempt_id},
        finding={
            "id": f"worker_execution_{worker}_{status}",
            "type": "worker_execution",
            "severity": "info" if status in {"executed", "completed", "skipped_cli_missing", "skipped_not_configured"} else "warning",
            "summary": f"Worker {worker} execution status: {status}",
        },
        adjudication={"final_status": "RECORDED"},
        details=result,
        audit_family="camino_a_worker_execution",
        dedupe_key=f"{job_id}:{attempt_id}:{worker}:{status}",
        db=db,
    )


def _command_is_available(command: str) -> bool:
    """Return whether one configured CLI can be executed locally.

    Explicit paths are checked as paths instead of being passed to ``which``;
    this keeps the master decision aligned with the Claude/Codex wrappers.
    """
    raw = str(command or "").strip()
    if not raw:
        return False
    if os.sep in raw or (os.altsep and os.altsep in raw):
        candidate = Path(raw).expanduser()
        return candidate.is_file() and not candidate.is_symlink() and os.access(str(candidate), os.X_OK)
    return shutil.which(raw) is not None


def _local_cli_for_worker(worker: str) -> str | None:
    if worker in {"codex", "codex_fallback"}:
        return os.environ.get("CODEX_CLI", "codex")
    if worker == "claude_code":
        return os.environ.get("CLAUDE_CLI", "claude")
    return None


def _parallel_worker_cap(configured_max: int, live_pressure: str) -> int:
    """Bound the subprocess pool using the current, not launch-time, pressure.

    Unknown telemetry is deliberately serialized: parallel execution is only
    safe when the resource guard has an authoritative current measurement.
    """
    configured = max(1, int(configured_max))
    pressure = str(live_pressure or "unknown").strip().lower()
    if pressure == "normal":
        return configured
    if pressure == "warning":
        return min(configured, 2)
    return 1


def execute_inline_workers(run_dir: Path, dispatch_results: list[dict],
                           runtime_profile: dict[str, Any], db: StateDB | None = None) -> list[dict]:
    """Run isolated workers concurrently within host/resource limits.

    The master remains the only authority; this helper only turns queued jobs
    into worker output bundles. It is disabled unless --execute-workers is used
    or the runtime profile has auto_execute_workers=true. SQLite/quality-log
    mutations remain serialized in the master thread; only subprocess work runs
    in parallel.
    """
    executable = {
        "local_static": ROOT / "scripts" / "worker_local_static.py",
        "gateway": ROOT / "scripts" / "worker_gateway.py",
        "codex": ROOT / "scripts" / "worker_codex.py",
        "claude_code": ROOT / "scripts" / "worker_claude_code.py",
        "codex_fallback": ROOT / "scripts" / "worker_codex_fallback.py",
        "lmstudio_bridge": ROOT / "scripts" / "worker_lmstudio.py",
    }
    worker_limits = runtime_profile.get("worker_limits", {}) if isinstance(runtime_profile, dict) else {}
    ordered_results: list[tuple[int, dict]] = []
    prepared: list[dict[str, Any]] = []
    run_config = read_json(run_dir / "RUN_CONFIG.json", {})
    execution = run_config.get("execution_context", {})
    execution = execution if isinstance(execution, dict) else {}
    selection = execution.get("selection", {})
    selection = selection if isinstance(selection, dict) else {}
    lm_base = str((execution.get("lmstudio", {}) or {}).get("base_url") or "")
    try:
        host_policy = load_host_runtime_policy()
        live_host = detect_runtime_host(host_policy)
        live_pressure = str((live_host.get("memory") or {}).get("pressure") or "unknown")
        live_peer = resolve_peer_settings(
            host_policy, os.environ, str(live_host.get("role") or "")
        )
        prefer_peer_now = (
            str(live_host.get("role") or "") == "macbook"
            and live_pressure in {"warning", "critical"}
        )
        if any(item.get("worker") == "lmstudio_bridge" for item in dispatch_results):
            lm_now = resolve_lmstudio_endpoint(host_policy, execute_probe=True)
            lm_base = str(lm_now.get("base_url") or "")
        else:
            lm_now = execution.get("lmstudio", {})
    except Exception as exc:
        live_host = execution.get("host", {})
        live_pressure = str((live_host.get("memory") or {}).get("pressure") or "unknown") if isinstance(live_host, dict) else "unknown"
        live_peer = execution.get("peer", {})
        live_peer = live_peer if isinstance(live_peer, dict) else {}
        prefer_peer_now = bool(selection.get("prefer_peer_for_non_lm"))
        lm_now = {"status": "refresh_failed", "error": f"{type(exc).__name__}:{exc}", "base_url": lm_base}
    configured_parallel = max(1, int(runtime_profile.get("max_parallel_workers", 3)))
    live_parallel_cap = _parallel_worker_cap(configured_parallel, live_pressure)
    state_snapshot = {
        "captured_at_utc": utc_now(),
        "host": live_host,
        "memory_pressure": live_pressure,
        "parallel_worker_cap": live_parallel_cap,
        "prefer_peer_for_non_lm": prefer_peer_now,
        "peer": live_peer,
        "lmstudio": lm_now,
    }
    write_json(run_dir / "STATE" / "last_dispatch_resource_snapshot.json", state_snapshot)

    def record_skip(order: int, worker: str, status: str, job_id: str,
                    attempt_id: str, details: dict[str, Any],
                    error_class: str, exit_code: int = 0) -> None:
        payload = {"worker": worker, "status": status, "job_id": job_id,
                   "attempt_id": attempt_id, **details}
        ordered_results.append((order, payload))
        _record_worker_execution_quality(
            run_dir, worker, status, job_id=job_id, attempt_id=attempt_id,
            db=db, details=details,
        )
        _db_finish_attempt(
            db, attempt_id, status="skipped" if exit_code == 0 else "failed",
            exit_code=exit_code, error_class=error_class,
        )
        if db is not None and job_id:
            db.update_job_status(job_id, "no_output" if exit_code == 0 else "failed")

    for order, item in enumerate(dispatch_results):
        worker = item.get("worker")
        if item.get("status") != "dispatched" or worker not in executable:
            continue
        worker = str(worker)
        job_id, attempt_id = _db_job_attempt_context(db, run_dir.name, worker, item.get("job_id"))
        script = executable[worker]
        if not script.exists():
            record_skip(order, worker, "script_missing", job_id, attempt_id,
                        {"script": str(script)}, "script_missing", 127)
            continue
        lm_remote = bool(lm_base) and not any(token in lm_base for token in ("127.0.0.1", "localhost", "[::1]"))
        peer_workers = {
            "local_static": "worker_local_static",
            "gateway": "worker_gateway",
            "codex": "worker_codex",
            "claude_code": "worker_claude_code",
            "codex_fallback": "worker_codex_fallback",
            "lmstudio_bridge": "worker_lmstudio",
        }
        peer_ready = bool(live_peer.get("enabled") and live_peer.get("configured"))
        local_cli = _local_cli_for_worker(worker)
        local_cli_missing = bool(local_cli and not _command_is_available(local_cli))
        production_profile = runtime_profile.get("profile_name") != "sandbox_reference"
        peer_reason = ""
        use_peer = (
            worker == "lmstudio_bridge" and lm_remote
        ) or (
            prefer_peer_now
            and production_profile
            and peer_ready
            and worker in {"codex", "claude_code", "codex_fallback"}
        ) or (
            local_cli_missing
            and production_profile
            and peer_ready
            and worker in {"codex", "claude_code", "codex_fallback"}
        )
        if worker == "lmstudio_bridge" and lm_remote:
            peer_reason = "lmstudio_remote_endpoint"
        elif use_peer and local_cli_missing:
            peer_reason = "local_cli_missing"
        elif use_peer and prefer_peer_now:
            peer_reason = "live_memory_pressure"
        # Plug-and-play rule: do not manufacture a worker_missing bundle just
        # because an optional CLI/provider is absent in the sandbox. Optional
        # workers are skipped cleanly; installed/configured workers can run.
        if not use_peer and worker == "codex" and local_cli_missing:
            record_skip(order, worker, "skipped_cli_missing", job_id, attempt_id,
                        {"cli": local_cli or "codex", "peer_ready": peer_ready}, "cli_missing:codex")
            continue
        if not use_peer and worker == "claude_code" and local_cli_missing:
            record_skip(order, worker, "skipped_cli_missing", job_id, attempt_id,
                        {"cli": local_cli or "claude", "peer_ready": peer_ready}, "cli_missing:claude")
            continue
        if not use_peer and worker == "codex_fallback" and local_cli_missing:
            record_skip(order, worker, "skipped_cli_missing", job_id, attempt_id,
                        {"cli": local_cli or "codex", "peer_ready": peer_ready}, "cli_missing:codex")
            continue
        if worker == "gateway" and not (os.environ.get("CAMINO_B_GATEWAY_URL") or os.environ.get("GATEWAY_URL")):
            record_skip(order, worker, "skipped_not_configured", job_id, attempt_id,
                        {"env": "CAMINO_B_GATEWAY_URL"}, "gateway_not_configured")
            continue
        limit = worker_limits.get(worker, {}) if isinstance(worker_limits, dict) else {}
        timeout_minutes = int(limit.get("timeout_minutes", 15 if worker == "local_static" else 45))
        command = [sys.executable, str(script), "--run", str(run_dir)]
        if use_peer:
            command = [
                sys.executable, str(ROOT / "scripts" / "peer_executor.py"),
                "--worker", peer_workers[worker], "--run", str(run_dir), "--json",
            ]
        prepared.append({
            "order": order, "worker": worker, "job_id": job_id,
            "attempt_id": attempt_id, "timeout_minutes": timeout_minutes,
            "cmd": command, "execution_transport": "ssh_peer" if use_peer else "local",
            "peer_selection_reason": peer_reason or None,
        })

    def invoke(task: dict[str, Any]) -> dict[str, Any]:
        worker = str(task["worker"])
        try:
            cp = subprocess.run(task["cmd"], cwd=str(ROOT), capture_output=True, text=True,
                                timeout=max(30, int(task["timeout_minutes"]) * 60),
                                env=_worker_env_for(worker))
            return {
                **task,
                "status": "executed",
                "exit_code": cp.returncode,
                "stdout_tail": cp.stdout[-2000:],
                "stderr_tail": cp.stderr[-2000:],
            }
        except subprocess.TimeoutExpired as exc:
            return {
                **task,
                "status": "timeout",
                "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
                "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
            }

    if prepared:
        max_workers = min(len(prepared), live_parallel_cap)
        completed: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="camino-worker") as pool:
            futures = {pool.submit(invoke, task): task for task in prepared}
            for future in as_completed(futures):
                completed.append(future.result())

        # Serialize all state/SQLite writes after subprocesses finish.
        for result in completed:
            worker = str(result["worker"])
            job_id = str(result.get("job_id") or "")
            attempt_id = str(result.get("attempt_id") or "")
            if result["status"] == "timeout":
                timeout_minutes = int(result["timeout_minutes"])
                _record_worker_execution_quality(
                    run_dir, worker, "timeout", job_id=job_id,
                    attempt_id=attempt_id, db=db,
                    details={"timeout_minutes": timeout_minutes},
                )
                _db_finish_attempt(db, attempt_id, status="timeout",
                                   timeout_seconds=timeout_minutes * 60,
                                   error_class="timeout")
                if db is not None and job_id:
                    db.update_job_status(job_id, "failed")
            else:
                exit_code = int(result.get("exit_code") or 0)
                exec_status = "executed" if exit_code == 0 else "failed"
                _record_worker_execution_quality(
                    run_dir, worker, exec_status, job_id=job_id,
                    attempt_id=attempt_id, db=db, details={"exit_code": exit_code},
                )
                _db_finish_attempt(
                    db, attempt_id,
                    status="completed" if exit_code == 0 else "failed",
                    exit_code=exit_code,
                )
                if db is not None and job_id and exit_code != 0:
                    db.update_job_status(job_id, "failed")
            public = {k: v for k, v in result.items() if k not in {"order", "cmd", "timeout_minutes"}}
            ordered_results.append((int(result["order"]), public))

    return [payload for _, payload in sorted(ordered_results, key=lambda item: item[0])]


def _worker_env_for(worker: str) -> dict[str, str]:
    """Return environment for worker subprocesses with forbidden API vars removed."""
    env = dict(os.environ)
    if worker in {"claude_code", "codex", "codex_fallback", "gateway"}:
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
    return env

# ---------------------------------------------------------------------------
# Harvest + validate (B-2 fix)
# ---------------------------------------------------------------------------

def harvest_workers(run_dir: Path, state: dict,
                    db: StateDB | None = None) -> dict:
    """Harvest and validate worker outputs.

    Returns dict with:
      - accepted: int (valid bundles)
      - rejected: int (invalid bundles)
      - pending: int (bundles present but no DONE marker)
      - details: list of dicts {worker, bundle, valid, violations?}
    """
    reconcile_recorded_outputs(run_dir, state)

    accepted: list[dict] = []
    rejected: list[dict] = []
    pending: list[dict] = []
    jobs_by_id = {
        str(job.get("job_id") or ""): job
        for job in (db.list_jobs(run_dir.name) if db is not None else [])
        if str(job.get("job_id") or "")
    }

    bus = run_dir / "13_WORKER_BUS"
    if not bus.exists():
        return {"accepted": 0, "rejected": 0, "pending": 0, "details": []}

    for worker_dir in sorted(bus.iterdir()):
        if not worker_dir.is_dir() or worker_dir.name.startswith("."):
            continue
        out_dir = worker_dir / "OUT"
        if not out_dir.exists():
            continue
        for bundle in sorted(out_dir.iterdir()):
            if not bundle.is_dir() or bundle.is_symlink():
                continue
            done_files = list(bundle.glob("*.DONE"))
            if not done_files:
                pending.append({
                    "worker": worker_dir.name,
                    "bundle": str(bundle),
                    "bundle_name": bundle.name,
                    "reason": "no_DONE_marker",
                })
                continue

            validation = validate_bundle(
                bundle, worker_id=worker_dir.name,
                expected_candidate_sha256=state.get("current_candidate_sha256")
            )
            manifest = validation.get("manifest", {}) if isinstance(validation.get("manifest", {}), dict) else {}
            result_payload = load_result_json(bundle)
            claimed_job_id = str(result_payload.get("job_id") or "")
            job_id = ""
            attempt_id = ""
            machine_lane = worker_dir.name not in {"manual_gpt", "manual_claude"}
            if db is not None and machine_lane and not claimed_job_id:
                validation["valid"] = False
                validation.setdefault("violations", []).append("missing_job_binding")
            if db is not None and machine_lane:
                claimed_run_id = str(result_payload.get("run_id") or "")
                if claimed_run_id != run_dir.name:
                    validation["valid"] = False
                    validation.setdefault("violations", []).append(
                        f"run_binding_mismatch:{claimed_run_id or '<missing>'}"
                    )
            if claimed_job_id and db is not None:
                job = jobs_by_id.get(claimed_job_id)
                owned_job = bool(
                    job
                    and str(job.get("run_id") or "") == run_dir.name
                    and str(job.get("worker_id") or "") == worker_dir.name
                )
                if owned_job:
                    # Preserve the exact owned job id even when another binding
                    # check fails, so closeout can mark that job rejected instead
                    # of leaving it indefinitely dispatched.
                    job_id = claimed_job_id
                    att = db.latest_attempt_for_job(job_id)
                    attempt_id = str(att.get("attempt_id") or "") if att else ""
                binding_ok = bool(
                    owned_job
                    and str(job.get("candidate_sha256") or "")
                    == str(manifest.get("candidate_sha256") or "")
                    and str(result_payload.get("candidate_sha256") or "")
                    == str(manifest.get("candidate_sha256") or "")
                )
                if not binding_ok:
                    validation["valid"] = False
                    validation.setdefault("violations", []).append(
                        f"job_binding_mismatch:{claimed_job_id}"
                    )
            entry = {
                "worker": worker_dir.name,
                "bundle": str(bundle),
                "bundle_name": bundle.name,
                "valid": validation["valid"],
                "violations": validation.get("violations", []),
                "files": validation.get("files", []),
                "job_id": job_id,
                "attempt_id": attempt_id,
            }
            auditor = auditor_from_result(worker_dir.name, result_payload, manifest, stage=str(manifest.get("stage") or "worker_bundle"))
            if validation["valid"]:
                accepted.append(entry)
                if db is not None:
                    db.record_output(
                        path=str(bundle),
                        job_id=job_id,
                        attempt_id=attempt_id,
                        validation_status="valid",
                        payload_sha256=manifest.get("candidate_sha256", ""),
                    )
                record_quality_event(
                    run_dir, event="worker_bundle_validated", auditor=auditor,
                    artifact={"bundle": str(bundle), "job_id": job_id, "attempt_id": attempt_id, "candidate_sha256": manifest.get("candidate_sha256", "")},
                    finding={"id": f"bundle_valid_{worker_dir.name}_{bundle.name}", "type": "worker_bundle", "severity": "info", "summary": f"Valid worker bundle from {worker_dir.name}"},
                    adjudication={"final_status": "ACCEPTED_FOR_CONSOLIDATION"},
                    details={"validation": validation, "result_status": result_payload.get("status"), "findings_count": len(result_payload.get("findings", []) or [])},
                    audit_family="camino_a_worker_bus",
                    dedupe_key=f"bundle:{bundle}:{manifest.get('candidate_sha256','')}:valid",
                    db=db,
                )
            else:
                rejected.append(entry)
                if db is not None:
                    db.record_output(
                        path=str(bundle),
                        job_id=job_id,
                        attempt_id=attempt_id,
                        validation_status="invalid",
                        rejected_reason=";".join(validation.get("violations", [])),
                    )
                record_quality_event(
                    run_dir, event="worker_bundle_rejected", auditor=auditor,
                    artifact={"bundle": str(bundle), "job_id": job_id, "attempt_id": attempt_id, "candidate_sha256": manifest.get("candidate_sha256", "")},
                    finding={"id": f"bundle_rejected_{worker_dir.name}_{bundle.name}", "type": "worker_bundle", "severity": "warning", "summary": f"Rejected worker bundle from {worker_dir.name}"},
                    adjudication={"final_status": "REJECTED", "violations": validation.get("violations", [])},
                    details={"validation": validation, "result_status": result_payload.get("status"), "findings_count": len(result_payload.get("findings", []) or [])},
                    audit_family="camino_a_worker_bus",
                    dedupe_key=f"bundle:{bundle}:{manifest.get('candidate_sha256','')}:invalid:{';'.join(validation.get('violations', []))}",
                    db=db,
                )

    return {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "pending": len(pending),
        "details": accepted + rejected,
        "pending_details": pending,
    }




# Trusted worker lanes. These are the ONLY directory names the master itself
# creates under 13_WORKER_BUS/ and dispatches jobs into. A bundle's identity is
# derived from the lane it physically came from — encoded as the ACCEPTED bundle
# directory prefix `<lane>_<original_bundle_name>` at consolidation time — NOT
# from any self-declared field inside the bundle.
KNOWN_WORKER_LANES = (
    # Order matters: longer / more specific names first so that a prefix match
    # against `manual_claude` is not shadowed by a hypothetical `manual` lane.
    "manual_claude", "manual_gpt", "claude_code", "codex_fallback",
    "lmstudio_bridge", "local_static", "codex", "gateway",
)

# Lanes that constitute a genuine Claude final review for terminal purposes.
CLAUDE_EVIDENCE_LANES = frozenset({"claude_code"})
CODEX_FALLBACK_EVIDENCE_LANES = frozenset({"codex_fallback"})
CLAUDE_TRIGGER_ERRORS = {
    "claude_auth_missing": {"auth_missing"},
    "claude_worker_missing": {"worker_missing", "skipped_cli_missing"},
    "claude_auth_check_failed": {"auth_check_failed", "auth_check_invalid_json"},
    "claude_auth_check_timeout": {"auth_check_timeout"},
    "claude_cli_nonzero": {"claude_cli_nonzero"},
    "claude_cli_execution_failed": {"cli_execution_failed"},
    "claude_timeout": {"timeout"},
    "claude_unavailable": {"claude_unavailable", "disabled_by_profile"},
}


def _claude_attempt_is_bound(
    primary: Any,
    *,
    trigger: str,
    run_id: str,
    candidate_sha256: str,
) -> bool:
    if not isinstance(primary, dict) or primary.get("approval_eligible") is True:
        return False
    if primary.get("worker_id") != "claude_code":
        return False
    if str(primary.get("run_id") or "") != run_id or str(primary.get("slot_id") or "") != "14":
        return False
    if str(primary.get("candidate_sha256") or "") != candidate_sha256:
        return False
    if not str(primary.get("job_id") or "").strip():
        return False
    if str(primary.get("error_class") or "") not in CLAUDE_TRIGGER_ERRORS.get(trigger, set()):
        return False
    durable = (
        re.fullmatch(r"[a-f0-9]{64}", str(primary.get("output_manifest_sha256") or "").lower())
        and str(primary.get("done_marker") or "").endswith(".DONE")
        and bool(str(primary.get("bundle") or "").strip())
    )
    recorded_unavailable = (
        primary.get("source") in {"runtime_profile", "master_inline_execution"}
        and trigger in {"claude_unavailable", "claude_worker_missing"}
    )
    return bool(durable or recorded_unavailable)


def _job_binding_exists(
    run_dir: Path, job_id: str, worker_id: str, candidate_sha256: str,
    *, allowed_statuses: set[str] | None = None,
) -> bool:
    db_path = run_dir / "STATE" / "state.sqlite"
    if not db_path.is_file() or not job_id:
        return False
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT run_id, worker_id, candidate_sha256, status FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        connection.close()
    except sqlite3.Error:
        return False
    if row is None:
        return False
    if (str(row[0]) != run_dir.name or str(row[1]) != worker_id
            or str(row[2] or "") != candidate_sha256):
        return False
    return allowed_statuses is None or str(row[3]) in allowed_statuses


def _claude_attempt_source_is_real(
    run_dir: Path,
    state: dict[str, Any],
    primary: Any,
    *,
    trigger: str,
    candidate_sha256: str,
) -> bool:
    if not _claude_attempt_is_bound(
        primary, trigger=trigger, run_id=run_dir.name,
        candidate_sha256=candidate_sha256,
    ):
        return False
    assert isinstance(primary, dict)
    source = str(primary.get("source") or "")
    if source == "runtime_profile":
        profile = state.get("runtime_profile") or {}
        return (
            isinstance(profile, dict)
            and profile.get("claude_enabled") is False
            and trigger == "claude_unavailable"
        )
    if source == "master_inline_execution":
        return _job_binding_exists(
            run_dir, str(primary.get("job_id") or ""), "claude_code",
            candidate_sha256,
            allowed_statuses={"failed", "no_output", "rejected"},
        )
    if source != "validated_claude_bundle":
        return False
    relative = Path(str(primary.get("bundle") or ""))
    if relative.is_absolute() or ".." in relative.parts:
        return False
    bundle = (run_dir / relative).resolve()
    try:
        bundle.relative_to(run_dir.resolve())
    except ValueError:
        return False
    if not bundle.is_dir() or bundle.is_symlink():
        return False
    manifest_path = bundle / "OUTPUT_MANIFEST.json"
    done_path = bundle / str(primary.get("done_marker") or "")
    if (not manifest_path.is_file() or manifest_path.is_symlink()
            or not done_path.is_file() or done_path.is_symlink()):
        return False
    if sha256_file(manifest_path) != str(primary.get("output_manifest_sha256") or ""):
        return False
    validation = validate_bundle(
        bundle, worker_id="claude_code",
        expected_candidate_sha256=candidate_sha256,
    )
    structural = [
        value for value in validation.get("violations", [])
        if not str(value).startswith("worker_non_success_status:")
    ]
    if structural:
        return False
    original = read_json(bundle / "result.json", {})
    for key in ("worker_id", "job_id", "run_id", "slot_id", "candidate_sha256", "error_class"):
        if str(original.get(key) or "") != str(primary.get(key) or ""):
            return False
    return _job_binding_exists(
        run_dir, str(primary.get("job_id") or ""), "claude_code",
        candidate_sha256,
        allowed_statuses={"failed", "rejected", "no_output"},
    )


def has_validated_gpt_brain_evidence(run_dir: Path, state: dict) -> bool:
    """Return True only for an externally supplied, validated GPT result.

    Merely naming a lane ``manual_gpt`` is insufficient.  The result must use
    the brain result schema, bind to this run/candidate and explicitly state it
    was not synthesized by the local adapter.
    """
    candidates = [
        run_dir / "31_GPT_PRIMARY_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        run_dir / "40_GPT_CODE_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        run_dir / "61_GPT_ITERATION_OUTPUT" / "PRIMARY_BRAIN_RESPONSE.json",
        run_dir / "70_FINAL_GPT_CLOSURE" / "PRIMARY_BRAIN_RESPONSE.json",
    ]
    current_sha = str(state.get("current_candidate_sha256") or "")
    for path in candidates:
        payload = _validated_gpt_response(run_dir, path, current_sha)
        if payload is None:
            continue
        evidence = payload.get("evidence_read")
        if isinstance(evidence, list) and evidence:
            return True
    return False


def _slot14_handoff_ack_is_current(run_dir: Path, result: dict[str, Any]) -> bool:
    request_sha = str(result.get("request_sha256") or result.get("audit_request_sha256") or "")
    if not request_sha or str(result.get("audit_request_sha256") or "") != request_sha:
        return False
    if not isinstance(result.get("falsification_attempts"), list) or not result["falsification_attempts"]:
        return False
    if not isinstance(result.get("independent_checks"), list) or not result["independent_checks"]:
        return False
    ok, _, _ = validate_slot14_handoff_binding(run_dir, result)
    return ok


def has_clean_slot14_claude_approval(run_dir: Path, state: dict) -> bool:
    """Enforce the complete slot-14 approval contract, not just lane identity."""
    completed = {str(x) for x in (state.get("completed_slots") or [])}
    if not {str(i) for i in range(1, 14)}.issubset(completed):
        return False
    accepted = run_dir / "ACCEPTED"
    if not accepted.exists():
        return False
    current_sha = str(state.get("current_candidate_sha256") or "")
    for bundle in sorted(accepted.iterdir()):
        if not bundle.is_dir() or bundle.is_symlink():
            continue
        lane = _lane_from_accepted_bundle(bundle.name)
        if lane not in CLAUDE_EVIDENCE_LANES:
            continue
        if not validate_bundle(bundle, worker_id=lane, expected_candidate_sha256=current_sha)["valid"]:
            continue
        result = read_json(bundle / "result.json", {})
        manifest = read_json(bundle / "OUTPUT_MANIFEST.json", {})
        auth = result.get("auth")
        if str(result.get("slot_id") or "") != "14":
            continue
        if result.get("worker_id") != "claude_code":
            continue
        if str(result.get("run_id") or "") != run_dir.name:
            continue
        job_id = str(result.get("job_id") or "")
        if not job_id:
            continue
        if result.get("status") != "ok" or result.get("approval_eligible") is not True:
            continue
        if result.get("verdict") != "APPROVED_BY_CLAUDE":
            continue
        if result.get("route_id") != "claude_code_subscription_cli":
            continue
        if not isinstance(auth, dict) or auth.get("ok") is not True or auth.get("status") != "authenticated":
            continue
        auth_method = str(auth.get("auth_method") or "").lower().replace("-", "_")
        if not auth_method or auth_method in {"none", "api_key", "apikey"}:
            continue
        if result.get("exit_code") != 0:
            continue
        if result.get("corrections_applied") is not False or result.get("findings") != []:
            continue
        if result.get("changed_artifacts") != []:
            continue
        if current_sha and str(result.get("candidate_sha256") or "") != current_sha:
            continue
        if current_sha and str(manifest.get("candidate_sha256") or "") != current_sha:
            continue
        if not _slot14_handoff_ack_is_current(run_dir, result):
            continue
        if not _job_binding_exists(
            run_dir, job_id, "claude_code", current_sha,
            allowed_statuses={"completed"},
        ):
            continue
        return True
    return False


def has_clean_slot14_codex_fallback_approval(run_dir: Path, state: dict) -> bool:
    """Accept Codex only as a clean, subscription-authenticated Claude fallback."""
    completed = {str(value) for value in (state.get("completed_slots") or [])}
    if not {str(value) for value in range(1, 14)}.issubset(completed):
        return False
    accepted = run_dir / "ACCEPTED"
    if not accepted.exists():
        return False
    current_sha = str(state.get("current_candidate_sha256") or "")
    allowed_triggers = {
        "claude_auth_missing", "claude_worker_missing", "claude_auth_check_failed",
        "claude_auth_check_timeout", "claude_cli_nonzero",
        "claude_cli_execution_failed", "claude_timeout", "claude_unavailable",
    }
    for bundle in sorted(accepted.iterdir()):
        if not bundle.is_dir() or bundle.is_symlink():
            continue
        if _lane_from_accepted_bundle(bundle.name) not in CODEX_FALLBACK_EVIDENCE_LANES:
            continue
        if not validate_bundle(
            bundle, worker_id="codex_fallback", expected_candidate_sha256=current_sha,
        )["valid"]:
            continue
        result = read_json(bundle / "result.json", {})
        manifest = read_json(bundle / "OUTPUT_MANIFEST.json", {})
        primary = result.get("claude_attempt")
        auth = result.get("auth")
        if str(result.get("slot_id") or "") != "14":
            continue
        if result.get("worker_id") != "codex_fallback":
            continue
        if str(result.get("run_id") or "") != run_dir.name:
            continue
        if result.get("status") != "ok" or result.get("approval_eligible") is not True:
            continue
        if result.get("verdict") != "APPROVED_BY_CODEX_FALLBACK":
            continue
        if result.get("corrections_applied") is not False or result.get("findings") not in ([], None):
            continue
        if result.get("route_id") != "codex_gpt_5_6_sol_ultra_subscription_cli":
            continue
        if result.get("model_id") != "gpt-5.6-sol" or result.get("model_reasoning_effort") != "ultra":
            continue
        if not isinstance(auth, dict) or auth.get("ok") is not True:
            continue
        if auth.get("status") != "authenticated" or auth.get("auth_method") != "chatgpt_subscription":
            continue
        if result.get("exit_code") != 0 or result.get("changed_artifacts") != []:
            continue
        if result.get("fallback_trigger") not in allowed_triggers:
            continue
        if not _claude_attempt_source_is_real(
            run_dir,
            state,
            primary,
            trigger=str(result.get("fallback_trigger") or ""),
            candidate_sha256=current_sha,
        ):
            continue
        if current_sha and str(result.get("candidate_sha256") or "") != current_sha:
            continue
        if current_sha and str(manifest.get("candidate_sha256") or "") != current_sha:
            continue
        if not _slot14_handoff_ack_is_current(run_dir, result):
            continue
        if not _job_binding_exists(
            run_dir, str(result.get("job_id") or ""), "codex_fallback",
            current_sha, allowed_statuses={"completed"},
        ):
            continue
        return True
    return False


def has_clean_slot14_subscription_approval(run_dir: Path, state: dict) -> bool:
    return (
        has_clean_slot14_claude_approval(run_dir, state)
        or has_clean_slot14_codex_fallback_approval(run_dir, state)
    )


def _lane_from_accepted_bundle(bundle_name: str) -> str | None:
    """Derive the trusted bus lane from an ACCEPTED bundle directory name.

    Consolidation names ACCEPTED bundles as `<lane>_<original_bundle_name>`
    where `<lane>` is one of the master-created lanes under 13_WORKER_BUS/.
    Only that trusted prefix determines identity. Returns None if the name does
    not begin with a known lane followed by a separator, so an unrecognised or
    tampered name can never be silently promoted to a privileged identity.
    """
    name = bundle_name.strip().lower()
    for lane in KNOWN_WORKER_LANES:
        if name == lane or name.startswith(lane + "_"):
            return lane
    return None


def accepted_evidence_workers(run_dir: Path) -> set[str]:
    """Return the trusted worker lanes represented in ACCEPTED bundles.

    This is used by the final terminal decision. In ``with_claude`` profile,
    local_static/Codex/Gateway evidence may be valid evidence, but it is not a
    Claude final approval. Therefore the run must not report ``closed_success``
    unless a bundle that physically came from a Claude lane is present.

    F-1 fix: identity is bound to the trusted bus lane (encoded in the ACCEPTED
    directory prefix that the master itself wrote), NOT to the self-declared
    ``worker_id`` inside ``result.json``. A non-Claude worker (or a malicious /
    compromised worker) that stamps ``worker_id: "claude_code"`` into its own
    ``result.json`` must NOT be able to fabricate Claude evidence and trigger a
    false ``closed_success``. The self-declared field is only used as a
    consistency cross-check that can DEMOTE (flag a mismatch) but never PROMOTE.
    """
    workers: set[str] = set()
    accepted = run_dir / "ACCEPTED"
    if not accepted.exists():
        return workers
    for bundle in sorted(accepted.iterdir()):
        if not bundle.is_dir() or bundle.is_symlink():
            continue
        lane = _lane_from_accepted_bundle(bundle.name)
        if lane is None:
            # Unrecognised ACCEPTED bundle name: refuse to attribute any
            # trusted identity. Fail closed — do not guess.
            continue
        # Cross-check: if the bundle self-declares a DIFFERENT worker than its
        # trusted lane, that is a red flag (spoof attempt or misrouted bundle).
        # We still attribute the TRUSTED lane only, and never the claimed one.
        declared = str(read_json(bundle / "result.json", {}).get("worker_id") or "").strip().lower()
        if declared and declared != lane:
            # The claimed identity is discarded; only the lane counts.
            # (A stricter policy could reject the bundle outright here; we keep
            #  it as accepted evidence for its TRUE lane and drop the claim.)
            pass
        workers.add(lane)
    return workers


def terminal_reason_for_profile(run_dir: Path, runtime_profile: dict[str, Any],
                                accepted_workers: set[str]) -> str:
    """Return the honest terminal reason for the runtime profile.

    * ``without_claude`` never fakes Claude approval: it closes as human review.
    * ``with_claude`` requires accepted Claude evidence for ``closed_success``.
      If Claude is enabled but absent/unavailable, the run is complete as a
      machine step but waits for manual Claude/final review.
    """
    state = load_state(run_dir)
    if has_clean_slot14_codex_fallback_approval(run_dir, state):
        return "closed_success_codex_subscription_fallback"
    if runtime_profile.get("final_without_claude"):
        return runtime_profile.get("terminal_without_claude_reason") or "ready_for_human_final_review"
    if runtime_profile.get("claude_enabled"):
        if not has_clean_slot14_claude_approval(run_dir, state):
            return (runtime_profile.get("terminal_if_claude_missing")
                    or "waiting_manual_claude_final_review")
    return "closed_success"

# ---------------------------------------------------------------------------
# Terminal gates (B-1 / B-3 fix)
# ---------------------------------------------------------------------------

def terminal_gate_check(run_dir: Path, state: dict, db: StateDB,
                        accepted_count: int) -> dict[str, Any]:
    """Run all terminal gate checks. Returns dict of check_name -> status.

    A check status is one of: 'pass', 'fail', 'skipped'.
    The run may only reach `closed_success` if ALL non-skipped checks pass.
    """
    checks: dict[str, dict[str, Any]] = {}

    # Check 1: no pending jobs in DB
    pending_jobs = db.count_pending_jobs(run_dir.name)
    checks["no_pending_jobs"] = {
        "status": "pass" if pending_jobs == 0 else "fail",
        "details": {"pending_jobs": pending_jobs},
    }

    # Check 2: no incomplete OUT bundles (DONE missing)
    incomplete = 0
    bus = run_dir / "13_WORKER_BUS"
    if bus.exists():
        for worker_dir in bus.iterdir():
            if not worker_dir.is_dir():
                continue
            out_dir = worker_dir / "OUT"
            if not out_dir.exists():
                continue
            for bundle in out_dir.iterdir():
                if not bundle.is_dir() or bundle.is_symlink():
                    continue
                if not list(bundle.glob("*.DONE")):
                    incomplete += 1
    checks["no_incomplete_out_bundles"] = {
        "status": "pass" if incomplete == 0 else "fail",
        "details": {"incomplete_bundles": incomplete},
    }

    # Check 3: accepted evidence present (unless explicit skip)
    skip = bool(state.get("skip_accepted_evidence", False))
    if skip:
        checks["accepted_evidence"] = {
            "status": "skipped",
            "details": {"skip_accepted_evidence": True},
        }
    else:
        checks["accepted_evidence"] = {
            "status": "pass" if accepted_count > 0 else "fail",
            "details": {"accepted_count": accepted_count},
        }

    # Check 4: production profiles require evidence actually produced by GPT.
    # The explicit reference/sandbox profile may turn this off for mechanical
    # smoke tests, but local_static alone can never satisfy a production brain.
    runtime_profile = runtime_profile_from_state(run_dir, state)
    require_gpt = bool(runtime_profile.get("require_gpt_brain_evidence", True))
    gpt_ok = has_validated_gpt_brain_evidence(run_dir, state)
    checks["gpt_brain_evidence"] = {
        "status": "pass" if (gpt_ok or not require_gpt) else "fail",
        "details": {"required": require_gpt, "validated_external_result": gpt_ok},
    }

    # Check 5: with_claude may only approve through a clean, current slot 14
    # after slots 1-13 completed.  Absence is an honest waiting state rather
    # than permission for any Claude-lane bundle to close the run.
    slot14_required = bool(runtime_profile.get("claude_enabled")) or worker_is_enabled(runtime_profile, "codex_fallback")
    if slot14_required:
        clean14 = has_clean_slot14_subscription_approval(run_dir, state)
        checks["slot14_clean_subscription_approval"] = {
            "status": "pass" if clean14 else "skipped",
            "details": {
                "clean_slot14": clean14,
                "claude_clean": has_clean_slot14_claude_approval(run_dir, state),
                "codex_subscription_fallback_clean": has_clean_slot14_codex_fallback_approval(run_dir, state),
                "terminal_if_absent": "waiting_manual_claude_final_review",
            },
        }

    # Check 6: final ZIP manifest checksums coherent
    final_zip = run_dir / "FINAL" / "final_release.zip"
    final_manifest = run_dir / "FINAL" / "final_manifest.json"
    zip_ok = False
    zip_details: dict[str, Any] = {"final_zip_exists": final_zip.exists()}
    if final_zip.exists() and final_manifest.exists():
        try:
            manifest_data = read_json(final_manifest, {})
            recorded_sha = manifest_data.get("zip_sha256", "")
            actual_sha = sha256_file(final_zip)
            final_candidate = run_dir / "FINAL" / "final_candidate"
            current_candidate = candidate_source(run_dir)
            current_tree_sha = hash_candidate_tree(current_candidate)
            final_tree_sha = hash_candidate_tree(final_candidate)
            manifest_entries = manifest_data.get("files") if isinstance(manifest_data.get("files"), list) else []
            listed = {
                str(item.get("path") or ""): str(item.get("sha256") or "")
                for item in manifest_entries if isinstance(item, dict)
            }
            actual_files = {
                str(item.relative_to(final_candidate)): sha256_file(item)
                for item in sorted(final_candidate.rglob("*"))
                if item.is_file() and not item.is_symlink()
            }
            zip_ok = bool(
                recorded_sha == actual_sha
                and current_tree_sha == str(state.get("current_candidate_sha256") or "")
                and final_tree_sha == current_tree_sha
                and str(manifest_data.get("candidate_sha256") or "") == current_tree_sha
                and listed == actual_files
            )
            zip_details.update({
                "recorded_sha256": recorded_sha,
                "actual_sha256": actual_sha,
                "match": zip_ok,
                "candidate_tree_sha256": current_tree_sha,
                "final_candidate_tree_sha256": final_tree_sha,
                "manifest_file_count": len(listed),
                "actual_file_count": len(actual_files),
            })
        except Exception as e:
            zip_details["error"] = str(e)
    checks["final_zip_manifest_coherent"] = {
        "status": "pass" if zip_ok else "fail",
        "details": zip_details,
    }

    # Persist to SQLite
    for name, payload in checks.items():
        db.record_terminal_check(run_dir.name, name,
                                 payload["status"], payload["details"])

    return checks


def _close_iteration_jobs(
    db: StateDB,
    run_id: str,
    harvest: dict[str, Any],
    *,
    mark_missing: bool = False,
) -> None:
    valid_job_ids = {
        str(item.get("job_id") or "")
        for item in harvest.get("details", [])
        if item.get("valid") and item.get("job_id")
    }
    invalid_job_ids = {
        str(item.get("job_id") or "")
        for item in harvest.get("details", [])
        if not item.get("valid") and item.get("job_id")
    }
    jobs = db.list_jobs(run_id, status="dispatched") + db.list_jobs(run_id, status="running")
    seen: set[str] = set()
    for job in jobs:
        job_id = str(job["job_id"])
        if job_id in seen:
            continue
        seen.add(job_id)
        if job_id in valid_job_ids:
            db.update_job_status(job_id, "completed")
        elif job_id in invalid_job_ids:
            db.update_job_status(job_id, "rejected")
        elif mark_missing:
            db.update_job_status(job_id, "no_output")


def _canonical_slot_attempt_limit(spec: dict[str, Any], fallback: int) -> int:
    """Use the immutable per-slot loop budget; global CLI value is legacy fallback."""
    try:
        configured = int(spec.get("loops"))
    except (TypeError, ValueError):
        configured = 0
    return max(1, configured if configured > 0 else int(fallback))


def _canonical_slot_iteration(
    run_dir: Path,
    state: dict[str, Any],
    runtime_profile: dict[str, Any],
    plan: dict[str, Any],
    routes: dict[str, Any],
    db: StateDB,
    *,
    dry_run: bool,
    execute_workers: bool,
    max_attempts: int,
) -> dict[str, Any]:
    """Execute exactly one canon-bound slot step and return the next action."""
    decision = next_slot_decision(plan, routes, state)
    if decision.status == "complete":
        return {"action": "consolidate", "reason": "all_slots_completed"}
    slot_id = str(decision.slot_id or "")
    spec = _slot_spec(plan, slot_id)
    if not spec:
        return {"action": "blocked", "reason": f"slot_spec_missing:{slot_id}"}
    candidate_ok, candidate_reason = verify_candidate_binding(
        run_dir, str(state.get("current_candidate_sha256") or ""),
    )
    if not candidate_ok:
        return {"action": "blocked", "reason": candidate_reason, "slot_id": slot_id}
    secret_violations = scan_candidate_for_secrets(candidate_source(run_dir))
    if secret_violations:
        return {
            "action": "blocked", "slot_id": slot_id,
            "reason": "candidate_secret_detected",
            "violation_count": len(secret_violations),
        }
    state["current_slot"] = slot_id
    state["canonical_slot_decision"] = decision.to_dict()
    gpt_promotion = _promote_gpt_candidate_update(run_dir, state, slot_id)
    if gpt_promotion is not None:
        return {
            "action": "continue", "slot_id": slot_id,
            "status": "gpt_candidate_promoted_restart_big_loop",
            "promotion": gpt_promotion,
        }

    # Harvest before dispatch so a completed asynchronous job is consumed on
    # re-entry and a still-running one is never overwritten by another job.json.
    pre_observed_claude = (
        _latest_claude_nonapproval(run_dir, state) if slot_id == "14" else None
    )
    if pre_observed_claude:
        state["slot14_claude_failure"] = pre_observed_claude
    pre_harvest = harvest_workers(run_dir, state, db=db)
    _close_iteration_jobs(db, run_dir.name, pre_harvest, mark_missing=False)
    pre_promotion = _promote_candidate_update_from_harvest(
        run_dir, state, pre_harvest, slot_id, db,
    )
    _move_invalid_to_rejected(run_dir, pre_harvest)
    if pre_promotion is not None:
        return {
            "action": "continue", "slot_id": slot_id,
            "status": "candidate_promoted_restart_big_loop",
            "harvest": pre_harvest, "promotion": pre_promotion,
        }
    existing = valid_slot_bus_evidence(run_dir, state, slot_id)
    gpt_existing = _validated_gpt_slot_result(run_dir, state, slot_id)
    if gpt_existing is not None:
        gpt_internal = gpt_existing.get("internal_loop") if isinstance(gpt_existing.get("internal_loop"), dict) else {}
        existing.append({
            "lane": "gpt_brain", "status": "validated_external",
            "slot_id": slot_id, "route_id": "chatgpt_plan",
            "findings_count": len(gpt_existing.get("findings") or []),
            "residual_debt_count": len(gpt_internal.get("residual_debt") or []),
        })
    if existing:
        _promote_valid_harvest_to_accepted(run_dir, state, pre_harvest, db)
        _record_evidence_residual_debt(state, slot_id, spec, existing)
        _complete_slot(state, plan, slot_id, existing)
        return {"action": "continue", "slot_id": slot_id, "status": "completed_existing",
                "evidence": existing}

    primary_routes = [str(value) for value in (spec.get("enabled_routes") or [])]
    fallback_routes = [str(value) for value in (spec.get("enabled_fallback_chain") or [])]
    if not primary_routes and not fallback_routes:
        # A route-free manual harvest slot is an explicit checkpoint.  It does
        # not manufacture evidence; it records that currently available manual
        # bundles were harvested and then advances.
        _complete_slot(state, plan, slot_id, [])
        return {"action": "continue", "slot_id": slot_id,
                "status": "route_free_checkpoint_completed"}

    attempts = state.setdefault("slot_attempts", {})
    phases = state.setdefault("slot_route_phase", {})
    phase = str(phases.get(slot_id) or ("primary" if primary_routes else "fallback:0"))

    claude_failure: dict[str, Any] | None = None
    if slot_id == "14":
        stored_failure = state.get("slot14_claude_failure")
        if not (
            isinstance(stored_failure, dict)
            and _claude_attempt_source_is_real(
                run_dir,
                state,
                stored_failure.get("attempt"),
                trigger=str(stored_failure.get("trigger") or ""),
                candidate_sha256=str(state.get("current_candidate_sha256") or ""),
            )
        ):
            stored_failure = None
        if worker_is_enabled(runtime_profile, "claude_code"):
            claude_failure = (
                pre_observed_claude
                or stored_failure
                or _latest_claude_nonapproval(run_dir, state)
            )
        else:
            claude_failure = {
                "trigger": "claude_unavailable",
                "attempt": {
                    "worker_id": "claude_code",
                    "job_id": "PROFILE_DISABLED",
                    "run_id": run_dir.name,
                    "slot_id": "14",
                    "candidate_sha256": state.get("current_candidate_sha256", ""),
                    "status": "disabled_by_profile",
                    "approval_eligible": False,
                    "error_class": "claude_unavailable",
                    "source": "runtime_profile",
                },
            }
        if claude_failure:
            active_routes = [
                route for route in fallback_routes
                if route == "codex_gpt_5_6_sol_ultra_subscription_cli"
            ]
            phase = "codex_subscription_fallback"
        else:
            active_routes = [
                route for route in primary_routes
                if route == "claude_code_subscription_cli"
            ]
            phase = "claude_primary"
    elif phase == "primary":
        active_routes = primary_routes
    elif phase.startswith("fallback:"):
        try:
            fallback_index = int(phase.split(":", 1)[1])
        except ValueError:
            fallback_index = 0
        active_routes = fallback_routes[fallback_index:fallback_index + 1]
    else:
        active_routes = []

    if not active_routes:
        return {"action": "blocked", "slot_id": slot_id,
                "reason": "no_active_route_for_slot_phase", "phase": phase}

    route_map = routes.get("routes", routes)
    grouped: dict[str, list[str]] = {}
    for route_id in active_routes:
        route = route_map.get(route_id, {}) if isinstance(route_map, dict) else {}
        if not isinstance(route, dict):
            continue
        grouped.setdefault(executor_for_route(route), []).append(route_id)

    inline_requested = execute_workers or bool(runtime_profile.get("auto_execute_workers"))
    tracked = state.setdefault("slot_inflight_job_ids", {})
    tracked_ids = {str(value) for value in (tracked.get(slot_id) or [])}
    if not inline_requested and not dry_run and tracked_ids:
        inflight = [
            job for status in ("dispatched", "running")
            for job in db.list_jobs(run_dir.name, status=status)
            if str(job.get("job_id") or "") in tracked_ids
        ]
        if inflight:
            return {
                "action": "wait",
                "slot_id": slot_id,
                "status": "waiting_worker_output",
                "phase": phase,
                "inflight_job_ids": [str(job["job_id"]) for job in inflight],
            }

    attempts[slot_id] = int(attempts.get(slot_id, 0)) + 1
    dispatch_results: list[dict[str, Any]] = []
    for executor, route_ids in grouped.items():
        if not worker_is_enabled(runtime_profile, executor):
            dispatch_results.append({"worker": executor, "status": "disabled_by_profile",
                                     "slot_id": slot_id, "route_ids": route_ids})
        elif executor == "lmstudio_bridge":
            dispatch_results.append(dispatch_lmstudio(
                run_dir, state, route_ids, slot_id, str(spec.get("role") or ""),
                internal_loop_contract=(spec.get("internal_loop") or {}),
                db=db, dry_run=dry_run,
            ))
        elif executor == "manual_gpt":
            dispatch_results.append(dispatch_gpt_brain_task(
                run_dir, state, slot_id, spec, dry_run=dry_run,
            ))
        elif executor == "manual_claude":
            dispatch_results.append({"worker": executor, "status": "waiting_manual_claude",
                                     "slot_id": slot_id, "route_ids": route_ids})
        elif executor == "claude_code":
            dispatch_results.append(dispatch_claude_code(run_dir, state, db=db, dry_run=dry_run))
        elif executor == "codex_fallback":
            if claude_failure is None:
                dispatch_results.append({"worker": executor, "status": "fallback_not_authorized",
                                         "slot_id": slot_id})
            else:
                dispatch_results.append(dispatch_codex_fallback(
                    run_dir, state, claude_failure=claude_failure, db=db, dry_run=dry_run,
                ))
        else:
            # External/API/provider-specific routes are executed behind Camino B
            # Gateway; the job carries the exact requested route ids.
            dispatch_results.append(dispatch_gateway(
                run_dir, state, db=db, dry_run=dry_run, slot_id=slot_id,
                route_ids=route_ids, slot_role=str(spec.get("role") or ""),
                internal_loop_contract=(spec.get("internal_loop") or {}),
            ))

    dispatched_ids = [
        str(item.get("job_id")) for item in dispatch_results
        if item.get("status") == "dispatched" and item.get("job_id")
    ]
    if dispatched_ids:
        tracked[slot_id] = dispatched_ids
    invalid_handoff = next(
        (item for item in dispatch_results if item.get("status") == "invalid_slot14_handoff"),
        None,
    )
    if invalid_handoff is not None:
        return {
            "action": "blocked", "slot_id": slot_id,
            "reason": "slot14_handoff_invalid",
            "dispatch": dispatch_results,
        }
    inline_results: list[dict[str, Any]] = []
    if inline_requested and not dry_run:
        inline_results = execute_inline_workers(run_dir, dispatch_results, runtime_profile, db=db)

    harvest = harvest_workers(run_dir, state, db=db)
    observed_claude_after_harvest = (
        _latest_claude_nonapproval(run_dir, state)
        if slot_id == "14" and phase == "claude_primary"
        else None
    )
    if observed_claude_after_harvest:
        state["slot14_claude_failure"] = observed_claude_after_harvest
    _close_iteration_jobs(db, run_dir.name, harvest, mark_missing=inline_requested)
    promotion = _promote_candidate_update_from_harvest(
        run_dir, state, harvest, slot_id, db,
    )
    _move_invalid_to_rejected(run_dir, harvest)
    if promotion is not None:
        return {
            "action": "continue",
            "slot_id": slot_id,
            "status": "candidate_promoted_restart_big_loop",
            "phase": phase,
            "dispatch": dispatch_results,
            "inline": inline_results,
            "harvest": harvest,
            "promotion": promotion,
        }
    evidence = valid_slot_bus_evidence(run_dir, state, slot_id)
    gpt_result = _validated_gpt_slot_result(run_dir, state, slot_id)
    if gpt_result is not None:
        gpt_internal = gpt_result.get("internal_loop") if isinstance(gpt_result.get("internal_loop"), dict) else {}
        evidence.append({
            "lane": "gpt_brain", "status": "validated_external",
            "slot_id": slot_id, "route_id": "chatgpt_plan",
            "findings_count": len(gpt_result.get("findings") or []),
            "residual_debt_count": len(gpt_internal.get("residual_debt") or []),
        })
    if evidence:
        _promote_valid_harvest_to_accepted(run_dir, state, harvest, db)
        _record_evidence_residual_debt(state, slot_id, spec, evidence)
        _complete_slot(state, plan, slot_id, evidence)
        return {
            "action": "continue", "slot_id": slot_id, "status": "completed",
            "phase": phase, "dispatch": dispatch_results, "inline": inline_results,
            "harvest": harvest, "evidence": evidence,
        }

    if not inline_requested and any(item.get("status") == "dispatched" for item in dispatch_results):
        return {"action": "wait", "slot_id": slot_id, "status": "waiting_worker_output",
                "phase": phase, "dispatch": dispatch_results}

    waiting_gpt = any(item.get("status") == "waiting_external_gpt" for item in dispatch_results)
    if waiting_gpt:
        return {"action": "blocked", "slot_id": slot_id,
                "reason": f"waiting_external_gpt_brain_slot_{slot_id}",
                "dispatch": dispatch_results}

    if slot_id == "14" and phase == "claude_primary":
        observed = (
            observed_claude_after_harvest
            or stored_failure
            or _latest_claude_nonapproval(run_dir, state)
        )
        if observed is None:
            for result in inline_results:
                if result.get("worker") == "claude_code" and result.get("status") in {
                    "skipped_cli_missing", "failed", "timeout",
                }:
                    observed = {
                        "trigger": "claude_worker_missing" if result.get("status") == "skipped_cli_missing" else "claude_unavailable",
                        "attempt": {
                            "worker_id": "claude_code",
                            "job_id": str(result.get("job_id") or "MASTER_INLINE"),
                            "run_id": run_dir.name,
                            "slot_id": "14",
                            "candidate_sha256": state.get("current_candidate_sha256", ""),
                            "status": result.get("status"),
                            "approval_eligible": False,
                            "error_class": (
                                "skipped_cli_missing" if result.get("status") == "skipped_cli_missing"
                                else "claude_unavailable"
                            ),
                            "source": "master_inline_execution",
                        },
                    }
                    break
        if observed:
            phases[slot_id] = "codex_subscription_fallback"
            state["slot14_claude_failure"] = observed
            return {"action": "continue", "slot_id": slot_id,
                    "status": "claude_failed_codex_fallback_armed", "failure": observed}

    if slot_id == "14" and phase == "codex_subscription_fallback":
        operator_marker = run_dir / "STATE" / "SLOT14_OPERATOR_ACTION_REQUIRED.json"
        return {"action": "blocked", "slot_id": slot_id,
                "reason": (
                    "SLOT14_OPERATOR_ACTION_REQUIRED"
                    if operator_marker.is_file()
                    else "slot14_codex_subscription_fallback_not_clean"
                ),
                "dispatch": dispatch_results, "inline": inline_results}

    if phase == "primary" and fallback_routes:
        phases[slot_id] = "fallback:0"
        return {"action": "continue", "slot_id": slot_id,
                "status": "primary_unavailable_advancing_to_fallback", "fallback": fallback_routes[0]}
    if phase.startswith("fallback:"):
        index = int(phase.split(":", 1)[1])
        if index + 1 < len(fallback_routes):
            phases[slot_id] = f"fallback:{index + 1}"
            return {"action": "continue", "slot_id": slot_id,
                    "status": "fallback_unavailable_advancing", "fallback": fallback_routes[index + 1]}

    policy = str(spec.get("correction_policy") or "").upper()
    blocking = "BLOCKING" in policy or "RESTART" in policy
    limit = _canonical_slot_attempt_limit(spec, max_attempts)
    if int(attempts[slot_id]) < limit:
        return {"action": "continue", "slot_id": slot_id,
                "status": "retrying_slot", "attempt": attempts[slot_id], "limit": limit}
    if blocking:
        return {"action": "blocked", "slot_id": slot_id,
                "reason": f"blocking_slot_{slot_id}_exhausted_without_evidence"}
    _record_slot_debt(state, slot_id, str(spec.get("role") or ""),
                      "routes_unavailable_or_no_valid_evidence", active_routes)
    _complete_slot(state, plan, slot_id, [])
    return {"action": "continue", "slot_id": slot_id,
            "status": "advanced_with_explicit_residual_debt"}


# ---------------------------------------------------------------------------
# Master loop
# ---------------------------------------------------------------------------

def master_loop(run_dir: Path, interval: int = 30, timeout_minutes: int = 0,
                dry_run: bool = False, max_iterations: int = 5,
                allow_empty: bool = False, execute_workers: bool = False) -> dict:
    """Main master loop — handles full lifecycle.

    The `allow_empty` flag (mapped from --allow-empty on the CLI) is the
    ONLY way the run can reach `closed_success` without accepted bundles.
    It is recorded in state['skip_accepted_evidence'] for audit.
    """
    _shutdown = False

    def _handle_term(signum, frame):
        nonlocal _shutdown
        _shutdown = True

    prev_term = signal.signal(signal.SIGTERM, _handle_term)
    prev_int = signal.signal(signal.SIGINT, _handle_term)

    lock = acquire_watcher_lock(run_dir)
    db = StateDB(run_dir / "STATE" / "state.sqlite")
    try:
        state = load_state(run_dir)
        runtime_profile = runtime_profile_from_state(run_dir, state)
        slot_plan, slot_routes = _canonical_slot_documents(run_dir)
        canonical_slot_mode = (
            slot_plan.get("schema_version") == "camino_slot_plan.v1"
            and runtime_profile.get("profile_name") != "sandbox_reference"
        )
        state["runtime_profile"] = runtime_profile
        state["runtime_profile_name"] = runtime_profile.get("profile_name", "legacy")
        state["watcher_status"] = "running"
        state["watcher_error_streak"] = 0
        if allow_empty:
            state["skip_accepted_evidence"] = True
        history_event(state, "master_started")
        state["canonical_slot_mode"] = canonical_slot_mode
        # A GPT response may arrive while the previous watcher is stopped.
        # Rerunning the master resumes only after that exact slot/candidate
        # evidence validates. Subscription CLI availability blocks may be
        # retried explicitly by rerunning after login is repaired.
        reason = str(state.get("terminal_reason") or "")
        if state.get("current_phase") == "blocked" and reason.startswith("waiting_external_gpt_brain_slot_"):
            waiting_slot = reason.rsplit("_", 1)[-1]
            if has_validated_gpt_slot_evidence(run_dir, state, waiting_slot):
                state["current_phase"] = "running"
                state["terminal_reason"] = None
                history_event(state, "resumed_after_validated_gpt_evidence", slot_id=waiting_slot)
        elif state.get("current_phase") == "blocked" and reason in {
            "slot14_codex_subscription_fallback_not_clean",
            "SLOT14_OPERATOR_ACTION_REQUIRED",
        }:
            state["current_phase"] = "running"
            state["terminal_reason"] = None
            history_event(state, "retrying_slot14_subscription_fallback")
        save_state(run_dir, state)

        # SQLite WAL is authority for run state — upsert the run row.
        target_sha = state.get("target_sha256", "")
        brain = state.get("brain_current", "")
        db.upsert_run(run_dir.name,
                      target_sha256=target_sha,
                      state=state.get("current_phase", "created"),
                      label=state.get("run_label", ""),
                      brain_current=brain)
        db.event("master_initialized",
                 run_id=run_dir.name, component="master",
                 details={"phase": state.get("current_phase")})
        print(f"  SQLite WAL: {db.db_path} (journal_mode={db.journal_mode()})")

        prepare_worker_bus(run_dir)

        if canonical_slot_mode and execute_workers and not state.get("internal_loops"):
            try:
                canonical_bundle = load_canon(ROOT)
                canonical_profile = resolve_profile(
                    canonical_bundle, str(runtime_profile.get("profile_name") or "with_claude")
                )
                _run_internal_agentic_loop(
                    run_dir,
                    build_slot_plan(canonical_bundle, canonical_profile),
                    canonical_bundle.runtime_policy,
                )
                state = load_state(run_dir)
                history_event(state, "canonical_internal_loops_integrated")
                save_state(run_dir, state)
            except Exception as exc:
                state = load_state(run_dir)
                state["current_phase"] = "blocked"
                state["terminal_reason"] = f"internal_loop_setup_failed:{type(exc).__name__}"
                history_event(state, "canonical_internal_loops_failed", error=str(exc)[:500])
                save_state(run_dir, state)
                db.update_run_state(
                    run_dir.name, "blocked", terminal_reason=state["terminal_reason"],
                )

        deadline = None if timeout_minutes <= 0 else time.monotonic() + timeout_minutes * 60
        next_heartbeat = 0.0
        iteration = 0
        last_accepted_count = 0

        while not _shutdown:
            reap_children()
            state = load_state(run_dir)
            now = time.monotonic()

            if deadline and now > deadline:
                print("Timeout reached.")
                state["current_phase"] = "blocked"
                state["terminal_reason"] = "timeout"
                save_state(run_dir, state)
                db.update_run_state(run_dir.name, "blocked", terminal_reason="timeout")
                break

            # Heartbeat (cap at 1 MiB)
            if now >= next_heartbeat:
                state["last_heartbeat"] = utc_now()
                hb = run_dir / "STATE" / "heartbeat.jsonl"
                hb.parent.mkdir(parents=True, exist_ok=True)
                _MAX_HB = 1 * 1024 * 1024
                if hb.exists() and hb.stat().st_size > _MAX_HB:
                    lines = hb.read_text(encoding="utf-8").splitlines()
                    hb.write_text("\n".join(lines[-500:]) + "\n", encoding="utf-8")
                with hb.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": utc_now(),
                                        "phase": state.get("current_phase"),
                                        "iter": iteration}) + "\n")
                next_heartbeat = now + 60

            phase = state.get("current_phase", "created")
            db.update_run_state(run_dir.name, phase)

            # --- PHASE: created ---
            if phase == "created":
                print(f"[{phase}] Initializing run...")
                prepare_worker_bus(run_dir)
                advance_phase(state, "manual_window")
                history_event(state, "phase_advanced",
                              from_phase="created", to_phase="manual_window")
                save_state(run_dir, state)
                db.update_run_state(run_dir.name, "manual_window")
                print("  → Advanced to manual_window")
                # fall through to next iteration
                time.sleep(max(1, interval))
                continue

            # --- PHASE: manual_window ---
            elif phase == "manual_window":
                manual_dir = run_dir / "10_MANUAL_AUDITS"
                has_manuals = manual_dir.exists() and any(manual_dir.glob("*.md"))
                if has_manuals:
                    print(f"[{phase}] Manual audits found, processing...")
                else:
                    print(f"[{phase}] No manual audits, advancing to running")
                advance_phase(state, "running")
                history_event(state, "phase_advanced",
                              from_phase="manual_window", to_phase="running")
                save_state(run_dir, state)
                db.update_run_state(run_dir.name, "running")
                continue

            # --- PHASE: running ---
            elif phase == "running":
                iteration += 1
                state["iteration_number"] = iteration
                if canonical_slot_mode:
                    print(f"[{phase}] Canonical step {iteration}")
                else:
                    print(f"[{phase}] Iteration {iteration}/{max_iterations}")

                if canonical_slot_mode:
                    runtime_profile = runtime_profile_from_state(run_dir, state)
                    slot_result = _canonical_slot_iteration(
                        run_dir, state, runtime_profile, slot_plan, slot_routes, db,
                        dry_run=dry_run, execute_workers=execute_workers,
                        max_attempts=max_iterations,
                    )
                    history_event(state, "canonical_slot_step", result=slot_result)
                    action = slot_result.get("action")
                    print(
                        "  → Canon slot %s: %s (%s)" % (
                            slot_result.get("slot_id", state.get("current_slot", "done")),
                            slot_result.get("status", action),
                            slot_result.get("reason", "ok"),
                        )
                    )
                    if action == "consolidate":
                        advance_phase(state, "consolidating")
                    elif action == "blocked":
                        state["current_phase"] = "blocked"
                        state["terminal_reason"] = str(slot_result.get("reason") or "canonical_slot_blocked")
                    save_state(run_dir, state)
                    db.update_run_state(
                        run_dir.name, state["current_phase"],
                        terminal_reason=state.get("terminal_reason") if action == "blocked" else None,
                    )
                    if action == "blocked":
                        break
                    if action == "wait":
                        time.sleep(max(1, interval))
                    continue

                if iteration > max_iterations:
                    print("  → Max iterations reached, advancing to consolidating")
                    advance_phase(state, "consolidating")
                    save_state(run_dir, state)
                    db.update_run_state(run_dir.name, "consolidating")
                    continue

                runtime_profile = runtime_profile_from_state(run_dir, state)
                dispatch_results = []
                if worker_is_enabled(runtime_profile, "local_static"):
                    dispatch_results.append(dispatch_local_static(run_dir, state, db=db, dry_run=dry_run))
                else:
                    dispatch_results.append({"worker": "local_static", "status": "disabled_by_profile"})
                if worker_is_enabled(runtime_profile, "codex"):
                    dispatch_results.append(dispatch_codex(run_dir, state, db=db, dry_run=dry_run))
                else:
                    dispatch_results.append({"worker": "codex", "status": "disabled_by_profile"})
                if worker_is_enabled(runtime_profile, "gateway"):
                    dispatch_results.append(dispatch_gateway(run_dir, state, db=db, dry_run=dry_run))
                else:
                    dispatch_results.append({"worker": "gateway", "status": "disabled_by_profile"})
                if worker_is_enabled(runtime_profile, "claude_code"):
                    dispatch_results.append(dispatch_claude_code(run_dir, state, db=db, dry_run=dry_run))
                else:
                    dispatch_results.append({"worker": "claude_code", "status": "disabled_by_profile"})
                print("  → Dispatch: " + ", ".join(f"{r['worker']}={r['status']}" for r in dispatch_results))
                history_event(state, "workers_dispatched_by_profile", profile=runtime_profile.get("profile_name"), results=dispatch_results)

                inline_requested = execute_workers or bool(runtime_profile.get("auto_execute_workers"))
                if inline_requested and not dry_run:
                    inline_results = execute_inline_workers(run_dir, dispatch_results, runtime_profile, db=db)
                    print("  → Inline workers: " + ", ".join(f"{r['worker']}={r['status']}:{r.get('exit_code','')}" for r in inline_results) if inline_results else "  → Inline workers: none")
                    history_event(state, "inline_workers_executed", results=inline_results)
                elif not dry_run:
                    time.sleep(2)

                harvest = harvest_workers(run_dir, state, db=db)
                last_accepted_count = harvest["accepted"]
                print(f"  → Harvested: {harvest['accepted']} accepted, "
                      f"{harvest['rejected']} rejected, "
                      f"{harvest['pending']} pending")

                # Move invalid bundles to REJECTED immediately
                _move_invalid_to_rejected(run_dir, harvest)

                # Close out dispatched jobs in DB so terminal_check
                # `no_pending_jobs` can pass. A job is marked:
                #   - 'completed'  if its worker produced a valid bundle
                #   - 'rejected'   if its worker produced an invalid bundle
                #   - 'no_output'  if the worker produced no bundle this round
                if db is not None:
                    workers_with_valid = {
                        d["worker"] for d in harvest.get("details", []) if d["valid"]
                    }
                    workers_with_invalid = {
                        d["worker"] for d in harvest.get("details", []) if not d["valid"]
                    }
                    closeout_jobs = db.list_jobs(run_dir.name, status="dispatched") + db.list_jobs(run_dir.name, status="running")
                    seen_closeout = set()
                    for job in closeout_jobs:
                        if job["job_id"] in seen_closeout:
                            continue
                        seen_closeout.add(job["job_id"])
                        wid = job["worker_id"]
                        if wid in workers_with_valid:
                            db.update_job_status(job["job_id"], "completed")
                        elif wid in workers_with_invalid:
                            db.update_job_status(job["job_id"], "rejected")
                        else:
                            db.update_job_status(job["job_id"], "no_output")

                if harvest["accepted"] > 0 or iteration >= max_iterations:
                    advance_phase(state, "consolidating")
                    print("  → Advancing to consolidating")
                else:
                    print("  → Continuing running")

                save_state(run_dir, state)
                db.update_run_state(run_dir.name, state["current_phase"])
                continue

            # --- PHASE: consolidating ---
            elif phase == "consolidating":
                print(f"[{phase}] Consolidating results...")

                accepted_dir = run_dir / "ACCEPTED"
                accepted_dir.mkdir(parents=True, exist_ok=True)
                rejected_dir = run_dir / "REJECTED"
                rejected_dir.mkdir(parents=True, exist_ok=True)

                bus = run_dir / "13_WORKER_BUS"
                moved_valid = 0
                moved_invalid = 0
                if bus.exists():
                    for worker_dir in bus.iterdir():
                        if not worker_dir.is_dir():
                            continue
                        out_dir = worker_dir / "OUT"
                        if not out_dir.exists():
                            continue
                        for bundle in out_dir.iterdir():
                            if not bundle.is_dir() or bundle.is_symlink():
                                continue
                            done_files = list(bundle.glob("*.DONE"))
                            if not done_files:
                                continue

                            v = validate_bundle(
                                bundle, worker_id=worker_dir.name,
                                expected_candidate_sha256=state.get("current_candidate_sha256")
                            )
                            dst_name = f"{worker_dir.name}_{bundle.name}"
                            if v["valid"]:
                                dst = accepted_dir / dst_name
                                if not dst.exists():
                                    # NEW-BUG-B fix (v1.2.0-iter2):
                                    # wrap copytree in try/except — if it
                                    # fails (e.g. permission denied on a
                                    # dereferenced symlink target), the
                                    # bundle is corrupt/unreadable and
                                    # MUST go to REJECTED instead of
                                    # crashing the master.
                                    try:
                                        shutil.copytree(str(bundle), str(dst),
                                                        symlinks=False)
                                        moved_valid += 1
                                        if db is not None:
                                            db.record_output(
                                                path=str(dst),
                                                validation_status="valid",
                                                payload_sha256=v.get("manifest", {}).get("candidate_sha256", ""),
                                            )
                                    except (OSError, shutil.Error) as e:
                                        # Demote to REJECTED with a
                                        # rejection_reason explaining the
                                        # copy failure.
                                        err_msg = f"copy_failed:{type(e).__name__}:{str(e)[:200]}"
                                        dst_rej = rejected_dir / dst_name
                                        if not dst_rej.exists():
                                            try:
                                                shutil.copytree(str(bundle),
                                                                str(dst_rej),
                                                                symlinks=False)
                                            except Exception:
                                                pass
                                        write_rejection_reason(
                                            rejected_dir, dst_name,
                                            [err_msg],
                                            worker_id=worker_dir.name,
                                        )
                                        moved_invalid += 1
                                        if db is not None:
                                            db.record_output(
                                                path=str(dst_rej),
                                                validation_status="invalid",
                                                rejected_reason=err_msg,
                                            )
                                        # Clean up partial ACCEPTED dst
                                        if dst.exists():
                                            shutil.rmtree(str(dst), ignore_errors=True)
                                        history_event(state, "bundle_copy_failed",
                                                      bundle=dst_name,
                                                      error=err_msg)
                            else:
                                dst = rejected_dir / dst_name
                                if not dst.exists():
                                    try:
                                        shutil.copytree(str(bundle), str(dst),
                                                        symlinks=False)
                                    except (OSError, shutil.Error) as e:
                                        # Even invalid-bundle copy can fail;
                                        # we still write the rejection_reason.
                                        history_event(
                                            state, "invalid_bundle_copy_failed",
                                            bundle=dst_name, error=str(e)[:200],
                                        )
                                moved_invalid += 1
                                write_rejection_reason(
                                    rejected_dir, dst_name,
                                    v.get("violations", []), worker_id=worker_dir.name,
                                )
                                if db is not None:
                                    db.record_output(
                                        path=str(dst) if dst.exists() else str(bundle),
                                        validation_status="invalid",
                                        rejected_reason=";".join(v.get("violations", [])),
                                    )

                print(f"  → Moved {moved_valid} valid bundles to ACCEPTED, "
                      f"{moved_invalid} invalid bundles to REJECTED")

                state["last_accepted_count"] = moved_valid
                save_state(run_dir, state)

                # B-1 fix: gate consolidating → testing on evidence
                if moved_valid == 0 and not state.get("skip_accepted_evidence", False):
                    state["current_phase"] = "blocked"
                    state["terminal_reason"] = "no_accepted_evidence"
                    history_event(state, "blocked_no_accepted_evidence",
                                  moved_invalid=moved_invalid)
                    save_state(run_dir, state)
                    db.update_run_state(run_dir.name, "blocked",
                                        terminal_reason="no_accepted_evidence")
                    db.event("blocked_no_accepted_evidence",
                             run_id=run_dir.name, component="master",
                             level="warn",
                             details={"moved_invalid": moved_invalid})
                    print("  → BLOCKED: no accepted evidence (B-1 fix)")
                    break

                advance_phase(state, "testing")
                save_state(run_dir, state)
                db.update_run_state(run_dir.name, "testing")
                continue

            # --- PHASE: testing ---
            elif phase == "testing":
                print(f"[{phase}] Running tests...")

                candidate_dir = run_dir / "00_CANDIDATE"
                ast_results = []
                if candidate_dir.exists():
                    for py_file in candidate_dir.rglob("*.py"):
                        if py_file.is_file() and not py_file.is_symlink():
                            result = analyze_file_ast(py_file)
                            ast_results.append({
                                "file": str(py_file.relative_to(candidate_dir)),
                                "safe": result["safe"],
                                "violations": len(result["violations"]),
                            })
                            print(f"  → AST {py_file.name}: "
                                  f"{'SAFE' if result['safe'] else 'UNSAFE'} "
                                  f"({len(result['violations'])} violations)")

                test_dir = run_dir / "TEST_RESULTS"
                test_dir.mkdir(parents=True, exist_ok=True)
                write_json(test_dir / "ast_analysis.json", {
                    "run_id": run_dir.name,
                    "tested_at": utc_now(),
                    "results": ast_results,
                })

                state["test_results"] = {"ast_analysis": ast_results}
                advance_phase(state, "finalizing")
                save_state(run_dir, state)
                db.update_run_state(run_dir.name, "finalizing")
                continue

            # --- PHASE: finalizing ---
            elif phase == "finalizing":
                print(f"[{phase}] Packaging final release...")

                # B-1: refuse to finalize without evidence (unless explicit skip)
                accepted_dir = run_dir / "ACCEPTED"
                accepted_bundles = (list(accepted_dir.iterdir())
                                    if accepted_dir.exists() else [])
                if not accepted_bundles and not state.get("skip_accepted_evidence", False):
                    state["current_phase"] = "blocked"
                    state["terminal_reason"] = "no_accepted_evidence_at_finalize"
                    history_event(state, "blocked_at_finalize")
                    save_state(run_dir, state)
                    db.update_run_state(
                        run_dir.name, "blocked",
                        terminal_reason="no_accepted_evidence_at_finalize",
                    )
                    db.event("blocked_at_finalize",
                             run_id=run_dir.name, component="master",
                             level="warn", details={})
                    print("  → BLOCKED: no accepted evidence at finalize")
                    break

                # BUG-3 FIX: package_final y los terminal gate checks estaban
                # sin try/except. Si package_final lanzaba una excepción (disco
                # lleno, permiso denegado, etc.) la corrida quedaba atrapada en
                # current_phase="finalizing" permanentemente (estado zombie).
                # Ahora cualquier excepción no capturada en esta fase transiciona
                # la corrida a "blocked" con terminal_reason="finalizing_exception"
                # antes de propagar.
                try:
                    result = package_final(run_dir)
                    print(f"  → Package: {result['status']}")
                    if result.get("zip_sha256"):
                        print(f"  → SHA-256: {result['zip_sha256'][:16]}...")

                    # Run terminal gates
                    checks = terminal_gate_check(
                        run_dir, state, db, accepted_count=len(accepted_bundles),
                    )
                    all_pass, failing = db.all_terminal_checks_pass(run_dir.name)
                    state["terminal_checks"] = checks
                    save_state(run_dir, state)

                    if not all_pass:
                        state["current_phase"] = "blocked"
                        state["terminal_reason"] = "terminal_check_failed"
                        history_event(state, "blocked_terminal_check_failed",
                                      failing_checks=failing)
                        save_state(run_dir, state)
                        db.update_run_state(
                            run_dir.name, "blocked",
                            terminal_reason="terminal_check_failed",
                        )
                        print(f"  → BLOCKED: terminal checks failed: "
                              f"{[c['check_name'] for c in failing]}")
                        break

                    # All gates pass — close with an honest terminal reason.
                    # Valid local/Codex/Gateway evidence may complete the machine
                    # run, but in with_claude profile it is NOT a Claude approval.
                    runtime_profile = runtime_profile_from_state(run_dir, state)
                    workers = accepted_evidence_workers(run_dir)
                    terminal_reason = terminal_reason_for_profile(run_dir, runtime_profile, workers)
                    advance_phase(state, "closed")
                    state["watcher_status"] = "completed"
                    state["terminal_reason"] = terminal_reason
                    history_event(state, "run_completed", package=result, runtime_profile=runtime_profile.get("profile_name"), terminal_reason=terminal_reason, accepted_workers=sorted(workers))
                    save_state(run_dir, state)
                except Exception as _fin_exc:
                    _fin_reason = f"finalizing_exception:{type(_fin_exc).__name__}:{str(_fin_exc)[:200]}"
                    state["current_phase"] = "blocked"
                    state["terminal_reason"] = _fin_reason
                    history_event(state, "blocked_finalizing_exception", error=_fin_reason)
                    save_state(run_dir, state)
                    try:
                        db.update_run_state(run_dir.name, "blocked",
                                            terminal_reason=_fin_reason)
                        db.event("blocked_finalizing_exception",
                                 run_id=run_dir.name, component="master",
                                 level="error", details={"error": _fin_reason})
                    except Exception:
                        pass
                    print(f"  → BLOCKED: exception in finalizing: {_fin_reason}")
                    break  # sale del while para evitar re-entrar en finalizing
                db.update_run_state(
                    run_dir.name, "closed",
                    terminal_reason=terminal_reason,
                )
                db.event("run_completed",
                         run_id=run_dir.name, component="master",
                         details={"zip_sha256": result.get("zip_sha256", "")})
                print(f"[closed] Run complete ({terminal_reason}).")
                break

            # --- PHASE: closed/blocked/cancelled ---
            elif phase in TERMINAL_PHASES:
                print(f"[{phase}] Terminal phase reached.")
                break

            else:
                print(f"[{phase}] Unknown phase, advancing...")
                advance_phase(state)
                save_state(run_dir, state)

            if deadline and time.monotonic() > deadline:
                print("Timeout reached.")
                state["current_phase"] = "blocked"
                state["terminal_reason"] = "timeout"
                save_state(run_dir, state)
                db.update_run_state(run_dir.name, "blocked",
                                    terminal_reason="timeout")
                break

            # Per-phase failure ceiling
            pf = state.setdefault("phase_failures", {})
            current_pf = pf.get(phase, 0)
            if current_pf >= 5:
                print(f"  → Phase {phase} failed {current_pf} times, blocking.")
                state["current_phase"] = "blocked"
                state["block_reason"] = f"phase_{phase}_failed_{current_pf}_times"
                save_state(run_dir, state)
                db.update_run_state(
                    run_dir.name, "blocked",
                    terminal_reason=state["block_reason"],
                )
                break

            streak = state.get("watcher_error_streak", 0)
            if streak > 0:
                backoff = min(interval * (2 ** min(streak, 6)), 300)
                time.sleep(backoff)
            else:
                time.sleep(max(1, interval))

        state = load_state(run_dir)
        state["watcher_status"] = "stopped"
        history_event(state, "master_stopped", iteration=iteration)
        save_state(run_dir, state)
        db.update_run_state(run_dir.name, state.get("current_phase", "stopped"))
        db.event("master_stopped",
                 run_id=run_dir.name, component="master",
                 details={"phase": state.get("current_phase"),
                          "iterations": iteration})

        return state

    finally:
        db.close()
        release_watcher_lock(run_dir, lock)
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)


def _promote_valid_harvest_to_accepted(
    run_dir: Path,
    state: dict,
    harvest: dict,
    db: StateDB | None = None,
) -> list[str]:
    """Copy validated canonical-slot bundles into the trusted ACCEPTED lane."""
    accepted_dir = run_dir / "ACCEPTED"
    accepted_dir.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    current_sha = str(state.get("current_candidate_sha256") or "")
    for entry in harvest.get("details", []):
        if not entry.get("valid"):
            continue
        src = Path(str(entry.get("bundle") or ""))
        worker = str(entry.get("worker") or "")
        bundle_name = str(entry.get("bundle_name") or src.name)
        if not src.is_dir() or src.is_symlink() or worker not in KNOWN_WORKER_LANES:
            continue
        dst = accepted_dir / f"{worker}_{bundle_name}"
        if not dst.exists():
            try:
                shutil.copytree(str(src), str(dst), symlinks=False)
            except (OSError, shutil.Error) as exc:
                if dst.exists():
                    shutil.rmtree(str(dst), ignore_errors=True)
                history_event(
                    state,
                    "canonical_bundle_promotion_failed",
                    worker=worker,
                    bundle=bundle_name,
                    error=f"{type(exc).__name__}:{str(exc)[:200]}",
                )
                continue
        validation = validate_bundle(
            dst, worker_id=worker, expected_candidate_sha256=current_sha,
        )
        if not validation.get("valid"):
            shutil.rmtree(str(dst), ignore_errors=True)
            history_event(
                state,
                "canonical_bundle_promotion_rejected",
                worker=worker,
                bundle=bundle_name,
                violations=validation.get("violations", []),
            )
            continue
        promoted.append(str(dst))
        if db is not None:
            db.record_output(
                path=str(dst),
                job_id=str(entry.get("job_id") or ""),
                attempt_id=str(entry.get("attempt_id") or ""),
                validation_status="valid",
                payload_sha256=validation.get("manifest", {}).get("candidate_sha256", ""),
            )
    return promoted


def _move_invalid_to_rejected(run_dir: Path, harvest: dict) -> None:
    """Move invalid bundles detected during harvest to REJECTED/.
    Writes rejection_reason.json next to each move target."""
    rejected_dir = run_dir / "REJECTED"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    for entry in harvest.get("details", []):
        if entry["valid"] or entry.get("candidate_update_promoted"):
            continue
        src = Path(entry["bundle"])
        if not src.exists():
            continue
        dst_name = f"{entry['worker']}_{entry['bundle_name']}"
        dst = rejected_dir / dst_name
        if not dst.exists():
            try:
                shutil.copytree(str(src), str(dst), symlinks=False)
            except Exception:
                # BUG-2 FIX: era 'continue'; eso salteaba write_rejection_reason
                # cuando copytree fallaba (disco lleno, permiso, etc.).
                # Cambiado a 'pass': write_rejection_reason siempre se llama
                # para que quede el audit trail en disco incluso si la copia
                # del bundle físico no pudo completarse.
                pass
        write_rejection_reason(
            rejected_dir, dst_name,
            entry.get("violations", []), worker_id=entry["worker"],
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Overnight master watcher")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--interval", type=int, default=2, help="Loop interval seconds")
    parser.add_argument("--timeout-minutes", type=int, default=480,
                        help="Max runtime (0=unlimited, default 8h)")
    parser.add_argument("--max-iterations", type=int, default=5,
                        help=("Legacy/default attempt limit; canonical slot plans "
                              "use each slot's immutable loops value"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-empty", action="store_true",
                        help="Allow closed_success with zero accepted bundles "
                             "(recorded as skip_accepted_evidence in state).")
    parser.add_argument("--execute-workers", action="store_true",
                        help="Execute supported workers inline after dispatch. Use for sandbox/plug-and-play runs.")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run dir not found: {run_dir}", file=sys.stderr)
        return 1

    print(f"Starting master: {run_dir}")
    print(f"Interval: {args.interval}s, Legacy attempt fallback: {args.max_iterations}")

    state = master_loop(
        run_dir, args.interval, args.timeout_minutes,
        dry_run=args.dry_run, max_iterations=args.max_iterations,
        allow_empty=args.allow_empty, execute_workers=args.execute_workers,
    )
    print(f"\nFinal phase: {state.get('current_phase')}")
    print(f"Terminal reason: {state.get('terminal_reason', 'n/a')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
