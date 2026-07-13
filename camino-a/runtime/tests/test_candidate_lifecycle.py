from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.candidate_updates import (
    CandidateUpdateError,
    copy_candidate_tree,
    create_candidate_update_archive,
    hash_candidate_tree,
    validate_candidate_update_bundle,
)
from scripts.overnight_master import (
    _promote_candidate_update_from_harvest,
    harvest_workers,
)
from scripts.package_final import package
from scripts.run_multiaudit_cycle import write_output_manifest_and_done
from scripts.state_db import StateDB


ROOT = Path(__file__).resolve().parents[1]


def test_start_creates_hash_bound_current_candidate(tmp_path: Path) -> None:
    target = tmp_path / "target"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    runs = tmp_path / "runs"
    completed = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts" / "start_overnight.py"),
            "--target", str(target), "--runs-dir", str(runs),
            "--profile", "sandbox_reference",
        ],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    run_line = next(line for line in completed.stdout.splitlines() if line.startswith("Directory:"))
    run = Path(run_line.split(":", 1)[1].strip())
    state = json.loads((run / "cycle_state.json").read_text(encoding="utf-8"))
    assert (run / "00_CANDIDATE" / "nested" / "app.py").read_text() == "VALUE = 1\n"
    assert state["current_candidate_sha256"] == hash_candidate_tree(run / "00_CANDIDATE")
    assert hash_candidate_tree(run / "INPUT" / "target_snapshot") == state["current_candidate_sha256"]


def test_package_preserves_nested_candidate_and_refuses_hash_drift(tmp_path: Path) -> None:
    run = tmp_path / "RUN_package"
    candidate = run / "00_CANDIDATE"
    (candidate / "pkg").mkdir(parents=True)
    (candidate / "pkg" / "mod.py").write_text("OK = True\n", encoding="utf-8")
    sha = hash_candidate_tree(candidate)
    (run / "INPUT").mkdir()
    (run / "INPUT" / "target_manifest.json").write_text(
        json.dumps({"total_files": 1}), encoding="utf-8",
    )
    (run / "cycle_state.json").write_text(
        json.dumps({"current_candidate_sha256": sha, "iteration_number": 0}),
        encoding="utf-8",
    )
    result = package(run)
    assert result["file_count"] == 1
    with zipfile.ZipFile(result["zip_path"]) as archive:
        assert "final_candidate/pkg/mod.py" in archive.namelist()
    (candidate / "pkg" / "mod.py").write_text("DRIFT = True\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="sha256_drift"):
        package(run)


def _correction_bundle(run: Path, state: dict, workspace: Path) -> Path:
    bundle = run / "13_WORKER_BUS" / "gateway" / "OUT" / "correction"
    bundle.mkdir(parents=True)
    update = create_candidate_update_archive(
        workspace, bundle,
        source_candidate_sha256=state["current_candidate_sha256"],
        worker_id="gateway", slot_id="1",
    )
    result = {
        "worker_id": "gateway", "job_id": "JOB_update", "run_id": run.name,
        "slot_id": "1", "candidate_sha256": state["current_candidate_sha256"],
        "status": "ok", "verdict": "CORRECTIONS_APPLIED",
        "corrections_applied": True, "findings": [], "artifacts": [],
        "candidate_update": update,
    }
    (bundle / "result.json").write_text(json.dumps(result), encoding="utf-8")
    write_output_manifest_and_done(
        run, str(bundle.relative_to(run)), done_name="GATEWAY_OUTPUT.DONE",
        stage="gateway_audit", candidate_sha256=state["current_candidate_sha256"],
        files=("result.json", "candidate_update.zip"),
    )
    return bundle


def test_job_bound_correction_promotes_and_restarts_without_mutating_seed(tmp_path: Path) -> None:
    run = tmp_path / "RUN_promote"
    seed = run / "INPUT" / "target_snapshot"
    seed.mkdir(parents=True)
    (seed / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    copy_candidate_tree(seed, run / "00_CANDIDATE")
    old_sha = hash_candidate_tree(run / "00_CANDIDATE")
    state = {
        "current_candidate_sha256": old_sha, "candidate_sha256": old_sha,
        "iteration_number": 0, "completed_slots": ["1", "2"],
        "current_slot": "3", "slot_attempts": {"1": 1},
        "internal_loops": {"1": {"status": "clean"}},
    }
    workspace = run / "workspace"
    copy_candidate_tree(run / "00_CANDIDATE", workspace)
    (workspace / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _correction_bundle(run, state, workspace)

    db = StateDB(run / "STATE" / "state.sqlite")
    db.upsert_run(run.name, target_sha256=old_sha, state="running")
    db.insert_job(
        run_id=run.name, worker_id="gateway", stage="slot_1",
        candidate_sha256=old_sha, status="dispatched", job_id="JOB_update",
    )
    try:
        harvested = harvest_workers(run, state, db=db)
        record = _promote_candidate_update_from_harvest(run, state, harvested, "1", db)
        job_status = db.list_jobs(run.name)[0]["status"]
    finally:
        db.close()
    assert record is not None
    assert (run / "00_CANDIDATE" / "app.py").read_text() == "VALUE = 2\n"
    assert (seed / "app.py").read_text() == "VALUE = 1\n"
    assert state["current_candidate_sha256"] == hash_candidate_tree(run / "00_CANDIDATE")
    assert state["completed_slots"] == [] and state["current_slot"] == "1"
    assert state["iteration_number"] == 1
    assert "internal_loops" not in state
    assert job_status == "completed_correction"


def test_candidate_update_rejects_zip_traversal(tmp_path: Path) -> None:
    run = tmp_path / "RUN_traversal"
    current = run / "00_CANDIDATE"
    current.mkdir(parents=True)
    (current / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    sha = hash_candidate_tree(current)
    bundle = run / "bundle"
    bundle.mkdir()
    archive = bundle / "candidate_update.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.py", "PWNED = True\n")
    import hashlib
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = {
        "worker_id": "gateway", "run_id": run.name, "slot_id": "1",
        "candidate_sha256": sha, "verdict": "CORRECTIONS_APPLIED",
        "corrections_applied": True,
        "candidate_update": {
            "schema_version": "camino_candidate_update.v1",
            "source_candidate_sha256": sha, "candidate_sha256": "b" * 64,
            "archive_path": "candidate_update.zip", "archive_sha256": archive_sha,
            "file_count": 1, "total_bytes": 13,
            "worker_id": "gateway", "slot_id": "1",
        },
    }
    (bundle / "OUTPUT_MANIFEST.json").write_text(
        json.dumps({"files": [{"path": "candidate_update.zip"}]}), encoding="utf-8",
    )
    with pytest.raises(CandidateUpdateError, match="traversal"):
        validate_candidate_update_bundle(
            run, bundle, result, {"current_candidate_sha256": sha},
            expected_slot_id="1",
        )
