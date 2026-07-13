from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.overnight_master import (
    has_clean_slot14_claude_approval,
    has_clean_slot14_codex_fallback_approval,
    has_validated_gpt_brain_evidence,
)
from scripts.run_multiaudit_cycle import write_output_manifest_and_done
from scripts.state_db import StateDB
from scripts.candidate_updates import hash_candidate_tree
from scripts.slot14_handoff import ensure_slot14_handoff
from scripts.primary_brain_adapter import (
    build_brain_task, validate_external_response, write_response, write_task_request,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _finish_bundle(
    run: Path, bundle: Path, result: dict, *, done_name: str, stage: str,
) -> None:
    _write(bundle / "result.json", result)
    write_output_manifest_and_done(
        run,
        str(bundle.relative_to(run)),
        done_name=done_name,
        stage=stage,
        candidate_sha256=str(result["candidate_sha256"]),
        files=("result.json",),
    )


def _record_job(
    run: Path, *, job_id: str, worker_id: str, candidate_sha256: str,
    status: str,
) -> None:
    with StateDB(run / "STATE" / "state.sqlite") as db:
        db.upsert_run(
            run.name, target_sha256=candidate_sha256, state="running",
        )
        existing = {item["job_id"] for item in db.list_jobs(run.name)}
        if job_id not in existing:
            db.insert_job(
                run_id=run.name, worker_id=worker_id,
                stage="slot_14_terminal_test", candidate_sha256=candidate_sha256,
                status=status, job_id=job_id,
            )
        else:
            db.update_job_status(job_id, status)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slot14_context(run: Path) -> tuple[str, dict, dict]:
    baseline = run / "INPUT" / "target_snapshot"
    candidate = run / "00_CANDIDATE"
    baseline.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    (baseline / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (candidate / "sample.py").write_text("value = 2\n", encoding="utf-8")
    sha = hash_candidate_tree(candidate)
    state = {
        "run_id": run.name,
        "current_candidate_sha256": sha,
        "completed_slots": list(range(1, 14)),
        "history": [],
        "residual_debt": [],
    }
    receipt = ensure_slot14_handoff(run, state)
    return sha, state, receipt


def _handoff_result_fields(receipt: dict) -> dict:
    return {
        **receipt,
        "audit_request_sha256": receipt["request_sha256"],
        "falsification_attempts": ["Intenté refutar el cambio con un caso negativo."],
        "independent_checks": ["Verifiqué la invariante terminal por una ruta independiente."],
    }


def test_gpt_evidence_must_be_external_and_current(tmp_path: Path) -> None:
    run = tmp_path / "RUN_20260710_120000_abc12"
    sha = "a" * 64
    state = {"current_candidate_sha256": sha}
    evidence_file = run / "00_CANDIDATE" / "audit.md"
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_text("verified evidence\n", encoding="utf-8")
    evidence_sha = _sha256(evidence_file)
    task = build_brain_task({
        "run_id": run.name, "stage": "primary_consolidation",
        "candidate_sha256": sha, "iteration_number": 0,
        "slot_id": "3",
        "evidence_catalog": [{
            "source": "00_CANDIDATE/audit.md", "sha256": evidence_sha,
            "size_bytes": evidence_file.stat().st_size,
        }],
    }, {"brain_current": "gpt_manual_or_configured", "policy": {}})
    write_task_request(run, "primary_consolidation", task)
    result = {
        "schema_version": "camino_gpt_brain_result.v1",
        "run_id": run.name,
        "stage": "primary_consolidation",
        "brain": "gpt_manual_or_configured",
        "candidate_sha256": sha,
        "synthetic": False,
        "slot_id": "3",
        "status": "completed",
        "decision": {"verdict": "ROUND_COMPLETE"},
        "evidence_read": [{"source": "00_CANDIDATE/audit.md", "sha256": evidence_sha}],
    }
    result = validate_external_response(result, task)
    path = write_response(run, "primary_consolidation", result)
    assert has_validated_gpt_brain_evidence(run, state)
    result["synthetic"] = True
    _write(path, result)
    assert not has_validated_gpt_brain_evidence(run, state)


def test_only_clean_current_slot14_after_slots_1_to_13_can_approve(tmp_path: Path) -> None:
    run = tmp_path / "RUN_20260710_120000_abc12"
    sha, state, receipt = _slot14_context(run)
    bundle = run / "ACCEPTED" / "claude_code_bundle"
    claude_result = {
        "worker_id": "claude_code",
        "job_id": "JOB_claude_clean",
        "run_id": run.name,
        "slot_id": "14",
        "candidate_sha256": sha,
        "status": "ok",
        "approval_eligible": True,
        "verdict": "APPROVED_BY_CLAUDE",
        "route_id": "claude_code_subscription_cli",
        "auth": {"ok": True, "status": "authenticated", "auth_method": "claude.ai"},
        "exit_code": 0,
        "changed_artifacts": [],
        "corrections_applied": False,
        "findings": [],
        **_handoff_result_fields(receipt),
    }
    _finish_bundle(
        run, bundle, claude_result,
        done_name="CLAUDE_CODE_OUTPUT.DONE", stage="slot_14_final_review",
    )
    _record_job(
        run, job_id="JOB_claude_clean", worker_id="claude_code",
        candidate_sha256=sha, status="completed",
    )
    assert has_clean_slot14_claude_approval(run, state)

    state["completed_slots"] = list(range(1, 13))
    assert not has_clean_slot14_claude_approval(run, state)
    state["completed_slots"] = list(range(1, 14))
    claude_result = {
        "worker_id": "claude_code", "slot_id": "14", "candidate_sha256": sha,
        "run_id": run.name,
        "status": "ok", "approval_eligible": True,
        "verdict": "APPROVED_BY_CLAUDE", "corrections_applied": True,
        "findings": [], "route_id": "claude_code_subscription_cli",
        "auth": {"ok": True, "status": "authenticated", "auth_method": "claude.ai"},
        "exit_code": 0, "changed_artifacts": [],
    }
    _finish_bundle(
        run, bundle, claude_result,
        done_name="CLAUDE_CODE_OUTPUT.DONE", stage="slot_14_final_review",
    )
    assert not has_clean_slot14_claude_approval(run, state)


def test_clean_codex_subscription_fallback_requires_failed_claude_attempt(tmp_path: Path) -> None:
    run = tmp_path / "RUN_20260710_120000_abc12"
    sha, state, receipt = _slot14_context(run)
    bundle = run / "ACCEPTED" / "codex_fallback_bundle"
    failed_bundle = run / "13_WORKER_BUS" / "claude_code" / "OUT" / "failed"
    failed_result = {
        "worker_id": "claude_code", "job_id": "JOB_claude_primary",
        "run_id": run.name, "slot_id": "14", "candidate_sha256": sha,
        "status": "failed", "approval_eligible": False,
        "error_class": "auth_missing", "findings": [],
    }
    _finish_bundle(
        run, failed_bundle, failed_result,
        done_name="CLAUDE_CODE_OUTPUT.DONE", stage="slot_14_final_review",
    )
    _record_job(
        run, job_id="JOB_claude_primary", worker_id="claude_code",
        candidate_sha256=sha, status="rejected",
    )
    result = {
        "worker_id": "codex_fallback",
        "job_id": "JOB_codex_fallback_clean",
        "run_id": run.name,
        "slot_id": "14",
        "candidate_sha256": sha,
        "status": "ok",
        "approval_eligible": True,
        "verdict": "APPROVED_BY_CODEX_FALLBACK",
        "corrections_applied": False,
        "findings": [],
        "route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
        "model_id": "gpt-5.6-sol",
        "model_reasoning_effort": "ultra",
        "auth": {"ok": True, "status": "authenticated", "auth_method": "chatgpt_subscription"},
        "exit_code": 0,
        "changed_artifacts": [],
        "fallback_trigger": "claude_auth_missing",
        "claude_attempt": {
            "worker_id": "claude_code", "job_id": "JOB_claude_primary",
            "run_id": run.name, "slot_id": "14", "candidate_sha256": sha,
            "status": "failed", "approval_eligible": False,
            "error_class": "auth_missing",
            "bundle": "13_WORKER_BUS/claude_code/OUT/failed",
            "output_manifest_sha256": _sha256(failed_bundle / "OUTPUT_MANIFEST.json"),
            "done_marker": "CLAUDE_CODE_OUTPUT.DONE",
            "source": "validated_claude_bundle",
        },
        **_handoff_result_fields(receipt),
    }
    _finish_bundle(
        run, bundle, result,
        done_name="CODEX_FALLBACK_OUTPUT.DONE",
        stage="slot_14_codex_subscription_fallback",
    )
    _record_job(
        run, job_id="JOB_codex_fallback_clean", worker_id="codex_fallback",
        candidate_sha256=sha, status="completed",
    )
    assert has_clean_slot14_codex_fallback_approval(run, state)

    result["claude_attempt"] = {"status": "ok", "approval_eligible": True}
    _finish_bundle(
        run, bundle, result,
        done_name="CODEX_FALLBACK_OUTPUT.DONE",
        stage="slot_14_codex_subscription_fallback",
    )
    assert not has_clean_slot14_codex_fallback_approval(run, state)


def test_slot14_rejects_tampered_auth_and_changed_workspace(tmp_path: Path) -> None:
    run = tmp_path / "RUN_20260710_120000_abc12"
    sha = "e" * 64
    state = {"current_candidate_sha256": sha, "completed_slots": list(range(1, 14))}

    claude = run / "ACCEPTED" / "claude_code_bundle"
    claude_result = {
        "worker_id": "claude_code", "slot_id": "14", "candidate_sha256": sha,
        "run_id": run.name,
        "job_id": "JOB_claude_tampered",
        "status": "ok", "approval_eligible": True, "verdict": "APPROVED_BY_CLAUDE",
        "route_id": "claude_code_subscription_cli", "corrections_applied": False,
        "findings": [], "changed_artifacts": [], "exit_code": 0,
        "auth": {"ok": False, "status": "authenticated", "auth_method": "api_key"},
    }
    _finish_bundle(
        run, claude, claude_result,
        done_name="CLAUDE_CODE_OUTPUT.DONE", stage="slot_14_final_review",
    )
    assert not has_clean_slot14_claude_approval(run, state)

    codex = run / "ACCEPTED" / "codex_fallback_bundle"
    codex_result = {
        "worker_id": "codex_fallback", "slot_id": "14", "candidate_sha256": sha,
        "run_id": run.name,
        "job_id": "JOB_codex_tampered",
        "status": "ok", "approval_eligible": True,
        "verdict": "APPROVED_BY_CODEX_FALLBACK", "corrections_applied": False,
        "findings": [], "route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
        "model_id": "gpt-5.6-sol", "model_reasoning_effort": "ultra",
        "auth": {"ok": True, "status": "authenticated", "auth_method": "chatgpt_subscription"},
        "exit_code": 0, "changed_artifacts": [{"path": "sample.py"}],
        "fallback_trigger": "claude_auth_missing",
        "claude_attempt": {"status": "failed", "approval_eligible": False},
    }
    _finish_bundle(
        run, codex, codex_result,
        done_name="CODEX_FALLBACK_OUTPUT.DONE",
        stage="slot_14_codex_subscription_fallback",
    )
    assert not has_clean_slot14_codex_fallback_approval(run, state)


def test_slot14_rejects_ghost_sources_and_wrong_job_binding(tmp_path: Path) -> None:
    run = tmp_path / "RUN_20260710_120000_abc12"
    sha = "f" * 64
    state = {"current_candidate_sha256": sha, "completed_slots": list(range(1, 14))}

    claude = run / "ACCEPTED" / "claude_code_ghost"
    claude_result = {
        "worker_id": "claude_code", "job_id": "JOB_not_in_db",
        "run_id": "RUN_wrong", "slot_id": "14", "candidate_sha256": sha,
        "status": "ok", "approval_eligible": True,
        "verdict": "APPROVED_BY_CLAUDE", "route_id": "claude_code_subscription_cli",
        "auth": {"ok": True, "status": "authenticated", "auth_method": "claude.ai"},
        "exit_code": 0, "changed_artifacts": [], "corrections_applied": False,
        "findings": [],
    }
    _finish_bundle(
        run, claude, claude_result,
        done_name="CLAUDE_CODE_OUTPUT.DONE", stage="slot_14_final_review",
    )
    assert not has_clean_slot14_claude_approval(run, state)

    codex = run / "ACCEPTED" / "codex_fallback_ghost"
    codex_result = {
        "worker_id": "codex_fallback", "job_id": "JOB_codex_ghost",
        "run_id": run.name, "slot_id": "14", "candidate_sha256": sha,
        "status": "ok", "approval_eligible": True,
        "verdict": "APPROVED_BY_CODEX_FALLBACK", "corrections_applied": False,
        "findings": [], "route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
        "model_id": "gpt-5.6-sol", "model_reasoning_effort": "ultra",
        "auth": {"ok": True, "status": "authenticated", "auth_method": "chatgpt_subscription"},
        "exit_code": 0, "changed_artifacts": [],
        "fallback_trigger": "claude_auth_missing",
        "claude_attempt": {
            "worker_id": "claude_code", "job_id": "JOB_claude_ghost",
            "run_id": run.name, "slot_id": "14", "candidate_sha256": sha,
            "status": "failed", "approval_eligible": False,
            "error_class": "auth_missing", "source": "validated_claude_bundle",
            "bundle": "13_WORKER_BUS/claude_code/OUT/does-not-exist",
            "output_manifest_sha256": "a" * 64,
            "done_marker": "CLAUDE_CODE_OUTPUT.DONE",
        },
    }
    _finish_bundle(
        run, codex, codex_result,
        done_name="CODEX_FALLBACK_OUTPUT.DONE",
        stage="slot_14_codex_subscription_fallback",
    )
    _record_job(
        run, job_id="JOB_codex_ghost", worker_id="codex_fallback",
        candidate_sha256=sha, status="completed",
    )
    assert not has_clean_slot14_codex_fallback_approval(run, state)
