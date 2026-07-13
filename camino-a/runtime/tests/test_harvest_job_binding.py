from __future__ import annotations

import json
from pathlib import Path

from scripts.overnight_master import _close_iteration_jobs, harvest_workers
from scripts.run_multiaudit_cycle import write_output_manifest_and_done
from scripts.state_db import StateDB


def _write_bundle(run: Path, result: dict, sha: str) -> Path:
    bundle = run / "13_WORKER_BUS" / "gateway" / "OUT" / "gateway_result"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "result.json").write_text(json.dumps(result), encoding="utf-8")
    write_output_manifest_and_done(
        run, str(bundle.relative_to(run)), done_name="GATEWAY_OUTPUT.DONE",
        stage="gateway_audit", candidate_sha256=sha, files=("result.json",),
    )
    return bundle


def _db(run: Path, sha: str, job_id: str = "JOB_gateway") -> StateDB:
    db = StateDB(run / "STATE" / "state.sqlite")
    db.upsert_run(run.name, target_sha256=sha, state="running")
    db.insert_job(
        run_id=run.name, worker_id="gateway", stage="slot_1_gateway",
        candidate_sha256=sha, status="dispatched", job_id=job_id,
    )
    return db


def _result(run: Path, sha: str, **overrides: object) -> dict:
    result = {
        "worker_id": "gateway", "job_id": "JOB_gateway",
        "run_id": run.name, "slot_id": "1", "candidate_sha256": sha,
        "status": "ok", "findings": [], "artifacts": [],
    }
    result.update(overrides)
    return result


def test_machine_bundle_requires_exact_job_and_run_binding(tmp_path: Path) -> None:
    run = tmp_path / "RUN_binding"
    sha = "a" * 64
    _write_bundle(run, _result(run, sha, job_id=""), sha)
    db = _db(run, sha)
    try:
        harvested = harvest_workers(run, {"current_candidate_sha256": sha}, db=db)
    finally:
        db.close()
    assert harvested["accepted"] == 0
    assert harvested["rejected"] == 1
    assert "missing_job_binding" in harvested["details"][0]["violations"]


def test_wrong_run_rejects_and_closes_only_the_claimed_owned_job(tmp_path: Path) -> None:
    run = tmp_path / "RUN_binding"
    sha = "b" * 64
    _write_bundle(run, _result(run, sha, run_id="RUN_wrong"), sha)
    db = _db(run, sha)
    try:
        harvested = harvest_workers(run, {"current_candidate_sha256": sha}, db=db)
        assert harvested["details"][0]["job_id"] == "JOB_gateway"
        _close_iteration_jobs(db, run.name, harvested)
        status = db.list_jobs(run.name)[0]["status"]
    finally:
        db.close()
    assert harvested["accepted"] == 0
    assert any(value.startswith("run_binding_mismatch:") for value in harvested["details"][0]["violations"])
    assert status == "rejected"


def test_exact_machine_binding_is_accepted(tmp_path: Path) -> None:
    run = tmp_path / "RUN_binding"
    sha = "c" * 64
    _write_bundle(run, _result(run, sha), sha)
    db = _db(run, sha)
    try:
        harvested = harvest_workers(run, {"current_candidate_sha256": sha}, db=db)
        _close_iteration_jobs(db, run.name, harvested)
        status = db.list_jobs(run.name)[0]["status"]
    finally:
        db.close()
    assert harvested["accepted"] == 1
    assert harvested["details"][0]["job_id"] == "JOB_gateway"
    assert status == "completed"
