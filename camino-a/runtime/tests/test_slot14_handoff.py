from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.candidate_updates import hash_candidate_tree
from scripts.slot14_handoff import (
    DIFF_FILENAME,
    MARKDOWN_FILENAME,
    REQUEST_FILENAME,
    SCHEMA_VERSION,
    Slot14HandoffError,
    ensure_slot14_handoff,
    materialize_slot14_handoff,
    validate_slot14_handoff_binding,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_run(tmp_path: Path) -> tuple[Path, dict]:
    run = tmp_path / "RUN_20260712_120000_abc12"
    baseline = run / "INPUT" / "target_snapshot"
    baseline.mkdir(parents=True)
    (baseline / "unchanged.txt").write_text("same\n", encoding="utf-8")
    (baseline / "modified.py").write_text("VALUE = 1\n", encoding="utf-8")
    (baseline / "deleted.md").write_text("remove me\n", encoding="utf-8")
    (baseline / "binary.bin").write_bytes(b"\x00old")

    candidate = run / "00_CANDIDATE"
    shutil.copytree(baseline, candidate)
    (candidate / "modified.py").write_text("VALUE = 2\n", encoding="utf-8")
    (candidate / "deleted.md").unlink()
    (candidate / "added.txt").write_text("new\n", encoding="utf-8")
    (candidate / "binary.bin").write_bytes(b"\x00new")
    candidate_sha = hash_candidate_tree(candidate)

    history = [
        {
            "at": f"2026-07-12T12:00:{slot:02d}+00:00",
            "event": "canonical_slot_completed",
            "slot_id": str(slot),
            "evidence": ([{
                "lane": "gateway",
                "bundle": f"ACCEPTED/slot_{slot}",
                "route_id": f"route_{slot}",
                "status": "ok",
                "findings_count": 0,
                "candidate_sha256": candidate_sha,
            }] if slot != 2 else []),
        }
        for slot in range(1, 14)
    ]
    state = {
        "run_id": run.name,
        "current_candidate_sha256": candidate_sha,
        "completed_slots": [str(value) for value in range(1, 14)],
        "history": history,
        "residual_debt": [{
            "slot_id": "7",
            "role": "reviewer",
            "reason": "live_provider_not_reprobed",
            "routes": ["route_7"],
            "recorded_at_utc": "2026-07-12T12:01:00+00:00",
        }],
    }
    return run, state


def _job(run: Path, state: dict, receipt: dict) -> dict:
    return {
        **receipt,
        "run_id": run.name,
        "candidate_sha256": state["current_candidate_sha256"],
    }


def test_builds_complete_manifest_bounded_diff_and_adversarial_request(tmp_path: Path) -> None:
    run, state = _make_run(tmp_path)
    receipt = ensure_slot14_handoff(run, state, max_diff_chars=1600)
    handoff = run / "STATE" / "slot14_handoff"
    request_path = handoff / REQUEST_FILENAME
    markdown_path = handoff / MARKDOWN_FILENAME
    diff_path = handoff / DIFF_FILENAME
    request = json.loads(request_path.read_text(encoding="utf-8"))

    assert request["schema_version"] == SCHEMA_VERSION
    assert request["source_slot_id"] == "13" and request["slot_id"] == "14"
    assert request["completed_slots"] == [str(value) for value in range(1, 14)]
    assert request["baseline_candidate_sha256"] == hash_candidate_tree(
        run / "INPUT" / "target_snapshot"
    )
    assert request["candidate_sha256"] == state["current_candidate_sha256"]
    assert request["diff_summary"] == {
        "added": 1, "modified": 2, "deleted": 1, "unchanged": 1,
    }
    assert [entry["path"] for entry in request["file_manifest"]["added"]] == ["added.txt"]
    assert [entry["path"] for entry in request["file_manifest"]["deleted"]] == ["deleted.md"]
    assert [entry["path"] for entry in request["file_manifest"]["modified"]] == [
        "binary.bin", "modified.py",
    ]
    assert [entry["path"] for entry in request["file_manifest"]["unchanged"]] == [
        "unchanged.txt",
    ]

    assert len(diff_path.read_text(encoding="utf-8")) <= 1600
    assert any(
        item["path"] == "binary.bin" and item["reason"] == "binary_nul"
        for item in request["text_diff_coverage"]["omitted_paths"]
    )
    methodology = request["anti_confirmation_methodology"]
    assert methodology["prior_results_are_claims_not_truth"] is True
    assert methodology["minimum_falsifiable_hypotheses"] >= 3
    assert methodology["minimum_negative_controls"] >= 1
    assert methodology["require_counterexample_search"] is True
    assert request["required_output"] == [
        "audit_request_sha256", "verdict", "summary",
        "falsification_attempts", "independent_checks", "tests",
        "findings", "corrections_applied",
    ]
    assert len(request["prior_evidence_index"]) == 13
    assert request["prior_evidence_index"][0]["evidence"][0]["candidate_sha256"] == (
        state["current_candidate_sha256"]
    )
    assert request["prior_evidence_index"][1]["evidence_count"] == 0
    assert request["residual_risks"][0]["reason"] == "live_provider_not_reprobed"
    assert "intentar refutar" in markdown_path.read_text(encoding="utf-8")

    assert receipt["request_path"] == "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json"
    assert receipt["diff_path"] == "STATE/slot14_handoff/CANDIDATE_DIFF.diff"
    assert receipt["slot14_audit_request_ref"] == receipt["request_path"]
    assert receipt["slot14_audit_request_sha256"] == receipt["request_sha256"]
    assert receipt["request_sha256"] == _sha256(request_path)
    assert receipt["diff_sha256"] == _sha256(diff_path)
    assert request["artifacts"]["diff"]["sha256"] == receipt["diff_sha256"]


def test_handoff_is_idempotent_and_accepts_canonical_or_bridge_alias_binding(tmp_path: Path) -> None:
    run, state = _make_run(tmp_path)
    first = ensure_slot14_handoff(run, state)
    second = ensure_slot14_handoff(run, state)
    assert second == first

    job = _job(run, state, first)
    ok, reason, request = validate_slot14_handoff_binding(run, job)
    assert ok, reason
    assert request["candidate_sha256"] == state["current_candidate_sha256"]

    alias_only = dict(job)
    alias_only.pop("request_path")
    alias_only.pop("request_sha256")
    ok, reason, _ = validate_slot14_handoff_binding(run, alias_only)
    assert ok, reason


@pytest.mark.parametrize(
    "completed",
    [
        [str(value) for value in range(1, 13)],
        [str(value) for value in range(1, 14)] + ["13"],
        [str(value) for value in range(2, 15)],
        ["2", "1"] + [str(value) for value in range(3, 14)],
    ],
)
def test_build_rejects_any_completed_slot_set_other_than_exact_ordered_1_to_13(
    tmp_path: Path, completed: list[str],
) -> None:
    run, state = _make_run(tmp_path)
    state["completed_slots"] = completed
    with pytest.raises(
        Slot14HandoffError, match="completed_slots_must_be_exactly_1_to_13_in_order",
    ):
        ensure_slot14_handoff(run, state)


def test_validation_rejects_path_hash_run_and_candidate_tampering(tmp_path: Path) -> None:
    run, state = _make_run(tmp_path)
    receipt = ensure_slot14_handoff(run, state)
    job = _job(run, state, receipt)

    bad_path = dict(job)
    bad_path["request_path"] = bad_path["slot14_audit_request_ref"] = "STATE/escape.json"
    ok, reason, _ = validate_slot14_handoff_binding(run, bad_path)
    assert not ok and reason.startswith("artifact_path_invalid")

    bad_run = dict(job, run_id="RUN_OTHER")
    ok, reason, _ = validate_slot14_handoff_binding(run, bad_run)
    assert not ok and reason == "job_run_id_mismatch"

    bad_transition = dict(job, source_slot_id="12")
    ok, reason, _ = validate_slot14_handoff_binding(run, bad_transition)
    assert not ok and reason == "job_source_slot_id_mismatch"

    diff = run / receipt["diff_path"]
    diff.write_text(diff.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    ok, reason, _ = validate_slot14_handoff_binding(run, job)
    assert not ok and reason == "diff_sha256_mismatch"

    # Rebuild, then mutate the candidate after the signed request was created.
    receipt = ensure_slot14_handoff(run, state)
    job = _job(run, state, receipt)
    (run / "00_CANDIDATE" / "added.txt").write_text("drift\n", encoding="utf-8")
    ok, reason, _ = validate_slot14_handoff_binding(run, job)
    assert not ok and reason == "candidate_tree_sha256_mismatch"


def test_new_candidate_invalidates_and_regenerates_request(tmp_path: Path) -> None:
    run, state = _make_run(tmp_path)
    first = ensure_slot14_handoff(run, state)
    (run / "00_CANDIDATE" / "added.txt").write_text("new candidate\n", encoding="utf-8")
    state["current_candidate_sha256"] = hash_candidate_tree(run / "00_CANDIDATE")
    second = ensure_slot14_handoff(run, state)
    assert second["request_sha256"] != first["request_sha256"]
    request = json.loads((run / second["request_path"]).read_text(encoding="utf-8"))
    assert request["candidate_sha256"] == state["current_candidate_sha256"]
    ok, reason, _ = validate_slot14_handoff_binding(run, _job(run, state, second))
    assert ok, reason


def test_materialization_copies_only_validated_hash_bound_bundle(tmp_path: Path) -> None:
    run, state = _make_run(tmp_path)
    receipt = ensure_slot14_handoff(run, state)
    job = _job(run, state, receipt)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    ok, reason = materialize_slot14_handoff(run, workspace, job)
    assert ok, reason
    materialized = workspace / ".camino_runtime" / "slot14_handoff"
    assert _sha256(materialized / REQUEST_FILENAME) == receipt["request_sha256"]
    assert _sha256(materialized / DIFF_FILENAME) == receipt["diff_sha256"]
    assert _sha256(materialized / MARKDOWN_FILENAME) == receipt["markdown_sha256"]

    markdown = run / receipt["markdown_path"]
    markdown.write_text(markdown.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    ok, reason = materialize_slot14_handoff(run, workspace, job)
    assert not ok and reason == "markdown_sha256_mismatch"


def test_large_text_diff_is_omitted_without_exceeding_declared_budget(tmp_path: Path) -> None:
    run, state = _make_run(tmp_path)
    (run / "INPUT" / "target_snapshot" / "huge.txt").write_text(
        "before\n" * 500, encoding="utf-8",
    )
    (run / "00_CANDIDATE" / "huge.txt").write_text(
        "after\n" * 500, encoding="utf-8",
    )
    state["current_candidate_sha256"] = hash_candidate_tree(run / "00_CANDIDATE")
    receipt = ensure_slot14_handoff(run, state, max_diff_chars=1024)
    request = json.loads((run / receipt["request_path"]).read_text(encoding="utf-8"))
    diff = (run / receipt["diff_path"]).read_text(encoding="utf-8")
    assert len(diff) <= 1024
    assert {item["path"] for item in request["file_manifest"]["modified"]} >= {
        "huge.txt",
    }
    assert any(
        item == {"path": "huge.txt", "reason": "global_diff_budget"}
        for item in request["text_diff_coverage"]["omitted_paths"]
    )
