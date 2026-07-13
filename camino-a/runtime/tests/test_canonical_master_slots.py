from __future__ import annotations

from pathlib import Path

from scripts.canon_loader import load_canon, resolve_profile
from scripts.overnight_master import (
    _canonical_slot_attempt_limit,
    _canonical_slot_iteration,
    _close_iteration_jobs,
    _promote_valid_harvest_to_accepted,
)
from scripts.run_multiaudit_cycle import write_json, write_output_manifest_and_done
from scripts.slot_runtime import build_slot_plan
from scripts.state_db import StateDB
from scripts.worker_codex_fallback import _validate_job as validate_codex_fallback_job
from scripts.candidate_updates import hash_candidate_tree


ROOT = Path(__file__).resolve().parents[1]


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "RUN_20260710_120000_abc12"
    (run / "STATE").mkdir(parents=True)
    (run / "13_WORKER_BUS").mkdir()
    (run / "00_CANDIDATE").mkdir()
    (run / "INPUT" / "target_snapshot").mkdir(parents=True)
    return run


def _documents(profile_name: str):
    bundle = load_canon(ROOT)
    profile = resolve_profile(bundle, profile_name)
    plan = build_slot_plan(bundle, profile).to_serializable()
    return bundle, profile, plan


def test_glm_disabled_advances_from_lmstudio_to_gpt_plan_fallback(tmp_path: Path) -> None:
    bundle, profile, plan = _documents("without_claude")
    run = _run_dir(tmp_path)
    sha = hash_candidate_tree(run / "00_CANDIDATE")
    state = {
        "run_id": run.name,
        "current_candidate_sha256": sha,
        "completed_slots": [str(value) for value in range(1, 7)],
        "current_slot": "7",
        "slot_route_phase": {"7": "fallback:0"},
    }
    db = StateDB(run / "STATE" / "state.sqlite")
    try:
        result = _canonical_slot_iteration(
            run, state, profile, plan, bundle.routes, db,
            dry_run=True, execute_workers=True, max_attempts=1,
        )
    finally:
        db.close()
    assert result["status"] == "fallback_unavailable_advancing"
    assert result["fallback"] == "chatgpt_gpt_5_5_plan"
    assert state["slot_route_phase"]["7"] == "fallback:1"


def test_slot14_without_claude_selects_codex_subscription_fallback(tmp_path: Path) -> None:
    bundle, profile, plan = _documents("without_claude")
    run = _run_dir(tmp_path)
    sha = hash_candidate_tree(run / "00_CANDIDATE")
    state = {
        "run_id": run.name,
        "current_candidate_sha256": sha,
        "completed_slots": [str(value) for value in range(1, 14)],
        "current_slot": "14",
    }
    db = StateDB(run / "STATE" / "state.sqlite")
    try:
        result = _canonical_slot_iteration(
            run, state, profile, plan, bundle.routes, db,
            dry_run=True, execute_workers=True, max_attempts=1,
        )
    finally:
        db.close()
    assert result["reason"] == "slot14_codex_subscription_fallback_not_clean"
    dispatch = result["dispatch"]
    assert dispatch == [{"worker": "codex_fallback", "status": "dry_run", "slot_id": "14"}]


def test_route_free_manual_harvest_slot_advances_without_fake_evidence(tmp_path: Path) -> None:
    bundle, profile, plan = _documents("without_claude")
    run = _run_dir(tmp_path)
    sha = hash_candidate_tree(run / "00_CANDIDATE")
    state = {
        "run_id": run.name,
        "current_candidate_sha256": sha,
        "completed_slots": ["1"],
        "current_slot": "2",
    }
    db = StateDB(run / "STATE" / "state.sqlite")
    try:
        result = _canonical_slot_iteration(
            run, state, profile, plan, bundle.routes, db,
            dry_run=True, execute_workers=True, max_attempts=1,
        )
    finally:
        db.close()
    assert result["status"] == "route_free_checkpoint_completed"
    assert state["completed_slots"] == ["1", "2"]
    assert state["current_slot"] == "3"


def test_canonical_slot_loop_budget_overrides_global_legacy_limit() -> None:
    assert _canonical_slot_attempt_limit({"loops": 5}, 3) == 5
    assert _canonical_slot_attempt_limit({"loops": 4}, 1) == 4
    assert _canonical_slot_attempt_limit({}, 3) == 3


def test_async_slot_does_not_overwrite_inflight_job(tmp_path: Path) -> None:
    bundle, profile, plan = _documents("without_claude")
    run = _run_dir(tmp_path)
    sha = hash_candidate_tree(run / "00_CANDIDATE")
    state = {
        "run_id": run.name,
        "current_candidate_sha256": sha,
        "completed_slots": [str(value) for value in range(1, 14)],
        "current_slot": "14",
    }
    db = StateDB(run / "STATE" / "state.sqlite")
    db.upsert_run(run.name, target_sha256=sha, state="running")
    try:
        first = _canonical_slot_iteration(
            run, state, profile, plan, bundle.routes, db,
            dry_run=False, execute_workers=False, max_attempts=1,
        )
        first_job = (run / "13_WORKER_BUS" / "codex_fallback" / "IN" / "job.json").read_text()
        second = _canonical_slot_iteration(
            run, state, profile, plan, bundle.routes, db,
            dry_run=False, execute_workers=False, max_attempts=1,
        )
        jobs = db.list_jobs(run.name)
    finally:
        db.close()
    assert first["status"] == "waiting_worker_output"
    assert second["status"] == "waiting_worker_output"
    assert len(jobs) == 1
    assert jobs[0]["status"] == "dispatched"
    assert (run / "13_WORKER_BUS" / "codex_fallback" / "IN" / "job.json").read_text() == first_job
    assert state["slot_attempts"]["14"] == 1
    import json
    assert validate_codex_fallback_job(json.loads(first_job)) is None


def test_job_closure_is_correlated_by_exact_job_id(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    sha = "9" * 64
    db = StateDB(run / "STATE" / "state.sqlite")
    db.upsert_run(run.name, target_sha256=sha, state="running")
    db.insert_job(
        run_id=run.name, worker_id="gateway", stage="slot_1",
        candidate_sha256=sha, status="dispatched", job_id="J1",
    )
    db.insert_job(
        run_id=run.name, worker_id="gateway", stage="slot_4",
        candidate_sha256=sha, status="dispatched", job_id="J2",
    )
    try:
        _close_iteration_jobs(
            db, run.name,
            {"details": [{"worker": "gateway", "job_id": "J1", "valid": True}]},
        )
        statuses = {job["job_id"]: job["status"] for job in db.list_jobs(run.name)}
    finally:
        db.close()
    assert statuses == {"J1": "completed", "J2": "dispatched"}


def test_canonical_harvest_promotes_valid_bundle_to_trusted_accepted_lane(
    tmp_path: Path,
) -> None:
    run = _run_dir(tmp_path)
    sha = hash_candidate_tree(run / "00_CANDIDATE")
    bundle = run / "13_WORKER_BUS" / "codex_fallback" / "OUT" / "bundle"
    bundle.mkdir(parents=True)
    write_json(bundle / "result.json", {"candidate_sha256": sha})
    write_output_manifest_and_done(
        run,
        str(bundle.relative_to(run)),
        done_name="CODEX_FALLBACK_OUTPUT.DONE",
        stage="slot_14_codex_subscription_fallback",
        candidate_sha256=sha,
        files=("result.json",),
    )
    harvest = {
        "details": [{
            "worker": "codex_fallback",
            "bundle": str(bundle),
            "bundle_name": bundle.name,
            "valid": True,
            "job_id": "",
            "attempt_id": "",
        }],
    }

    promoted = _promote_valid_harvest_to_accepted(
        run, {"current_candidate_sha256": sha, "history": []}, harvest,
    )

    accepted = run / "ACCEPTED" / "codex_fallback_bundle"
    assert promoted == [str(accepted)]
    assert (accepted / "result.json").is_file()
    assert (accepted / "OUTPUT_MANIFEST.json").is_file()
    assert (accepted / "CODEX_FALLBACK_OUTPUT.DONE").is_file()
