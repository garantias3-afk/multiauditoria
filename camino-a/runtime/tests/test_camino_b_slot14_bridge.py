from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.camino_b_slot14_bridge import (
    AWAITING,
    CLAIMED,
    COMPLETED,
    FALLBACK_ROUTE,
    PRIMARY_ROUTE,
    BridgeError,
    LocalSlot14Queue,
)


RUN_ID = "RUN_20260712_120000_abcde"
CANDIDATE = "a" * 64
REQUEST_SHA = "b" * 64
DIFF_SHA = "c" * 64


def _request(*, idempotency_key: str = "slot14-review-key-0001") -> dict:
    return {
        "schema_version": "camino_b_slot14_review_request.v1",
        "path_id": "camino_b",
        "run_id": RUN_ID,
        "slot_id": "14",
        "source_slot_id": "13",
        "candidate_sha256": CANDIDATE,
        "prior_slots_complete": True,
        "request_path": "SLOT14_HANDOFF/SLOT14_AUDIT_REQUEST.json",
        "request_sha256": REQUEST_SHA,
        "slot14_audit_request_ref": "SLOT14_HANDOFF/SLOT14_AUDIT_REQUEST.json",
        "slot14_audit_request_sha256": REQUEST_SHA,
        "diff_path": "SLOT14_HANDOFF/SLOT13_TO_SLOT14.diff",
        "diff_sha256": DIFF_SHA,
        "idempotency_key": idempotency_key,
        "metadata": {"source": "unit_test"},
    }


def _assert_error(code: str, callback) -> BridgeError:
    with pytest.raises(BridgeError) as caught:
        callback()
    assert caught.value.code == code
    return caught.value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_bundle(
    root: Path,
    *,
    worker_id: str,
    route_id: str,
    status: str,
    error_class: str = "",
) -> Path:
    bundle = root / ("bundle_%s_%s" % (worker_id, status))
    bundle.mkdir()
    result = {
        "schema_version": "camino_slot14_worker_result.test.v1",
        "worker_id": worker_id,
        "job_id": "JOB_%s_%s" % (worker_id, status),
        "run_id": RUN_ID,
        "slot_id": "14",
        "candidate_sha256": CANDIDATE,
        "route_id": route_id,
        "status": status,
        "summary": "Bound worker result for bridge regression testing.",
        "findings": [],
        "corrections_applied": False,
        "approval_eligible": status == "ok",
    }
    if error_class:
        result["error_class"] = error_class
        result["approval_eligible"] = False
    if worker_id == "codex_fallback":
        result.update({
            "model_id": "gpt-5.6-sol",
            "model_reasoning_effort": "ultra",
            "auth": {"ok": True, "auth_method": "chatgpt_subscription"},
            "model_preflight": {
                "ok": True,
                "model_id": "gpt-5.6-sol",
                "reasoning_effort": "ultra",
            },
        })
    result_path = bundle / "result.json"
    result_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "camino_a_output_manifest.v1",
        "run_id": RUN_ID,
        "stage": "slot_14_bridge_test",
        "candidate_sha256": CANDIDATE,
        "created_at_utc": "2026-07-12T12:00:00+00:00",
        "files": [{
            "path": "result.json",
            "sha256": _sha(result_path),
            "size_bytes": result_path.stat().st_size,
        }],
    }
    (bundle / "OUTPUT_MANIFEST.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8",
    )
    done_name = (
        "CLAUDE_CODE_OUTPUT.DONE" if worker_id == "claude_code"
        else "CODEX_FALLBACK_OUTPUT.DONE"
    )
    (bundle / done_name).write_text("DONE\n", encoding="utf-8")
    return bundle


def test_request_is_idempotent_and_conflicting_reuse_fails(tmp_path: Path) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    first = queue.request_review(_request())
    second = queue.request_review(_request())

    assert first["status"] == AWAITING
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert first["handoff_id"] == second["handoff_id"]
    assert len(list((tmp_path / "queue/jobs").iterdir())) == 1

    conflict = _request()
    conflict["diff_sha256"] = "d" * 64
    _assert_error("idempotency_conflict", lambda: queue.request_review(conflict))


def test_alias_divergence_and_stale_candidate_fail_closed(tmp_path: Path) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    divergent = _request()
    divergent["slot14_audit_request_sha256"] = "e" * 64
    _assert_error(
        "slot14_audit_request_sha256_alias_mismatch",
        lambda: queue.request_review(divergent),
    )

    created = queue.request_review(_request(idempotency_key="slot14-review-key-0002"))
    _assert_error(
        "stale_candidate_sha256",
        lambda: queue.get_status(created["handoff_id"], "f" * 64),
    )


def test_claim_is_exclusive_and_same_claim_replay_is_idempotent(tmp_path: Path) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    handoff = queue.request_review(_request())["handoff_id"]
    first = queue.claim(
        handoff,
        CANDIDATE,
        worker_id="claude_code",
        route_id=PRIMARY_ROUTE,
        claim_id="CLAIM_primary_001",
        host_id="macbook",
    )
    replay = queue.claim(
        handoff,
        CANDIDATE,
        worker_id="claude_code",
        route_id=PRIMARY_ROUTE,
        claim_id="CLAIM_primary_001",
        host_id="macbook",
    )
    assert first["status"] == CLAIMED
    assert replay["idempotent_replay"] is True
    assert replay["claim_token"] == first["claim_token"]
    assert "claim_token_sha256" not in replay["claim"]

    _assert_error(
        "job_already_claimed",
        lambda: queue.claim(
            handoff,
            CANDIDATE,
            worker_id="claude_code",
            route_id=PRIMARY_ROUTE,
            claim_id="CLAIM_primary_002",
            host_id="imac",
        ),
    )


def test_codex_fallback_cannot_claim_without_claude_failure(tmp_path: Path) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    handoff = queue.request_review(_request())["handoff_id"]
    _assert_error(
        "fallback_requires_valid_claude_failure",
        lambda: queue.claim(
            handoff,
            CANDIDATE,
            worker_id="codex_fallback",
            route_id=FALLBACK_ROUTE,
            claim_id="CLAIM_fallback_001",
            host_id="imac",
        ),
    )


def test_failure_arms_fallback_and_valid_done_receipt_completes_transport(
    tmp_path: Path,
) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    created = queue.request_review(_request())
    handoff = created["handoff_id"]
    primary_claim = queue.claim(
        handoff,
        CANDIDATE,
        worker_id="claude_code",
        route_id=PRIMARY_ROUTE,
        claim_id="CLAIM_primary_003",
        host_id="macbook",
    )
    failed = _make_bundle(
        tmp_path,
        worker_id="claude_code",
        route_id=PRIMARY_ROUTE,
        status="failed",
        error_class="auth_missing",
    )
    after_failure = queue.complete(
        handoff,
        CANDIDATE,
        claim_token=primary_claim["claim_token"],
        bundle_dir=failed,
    )
    assert after_failure["status"] == AWAITING
    assert after_failure["fallback_armed"] is True
    assert after_failure["terminal_approval"] is False

    fallback_claim = queue.claim(
        handoff,
        CANDIDATE,
        worker_id="codex_fallback",
        route_id=FALLBACK_ROUTE,
        claim_id="CLAIM_fallback_002",
        host_id="imac",
    )
    success = _make_bundle(
        tmp_path,
        worker_id="codex_fallback",
        route_id=FALLBACK_ROUTE,
        status="ok",
    )
    completed = queue.complete(
        handoff,
        CANDIDATE,
        claim_token=fallback_claim["claim_token"],
        bundle_dir=success,
    )
    assert completed["status"] == COMPLETED
    assert completed["result_ready"] is True
    assert completed["transport_completed"] is True
    assert completed["terminal_approval"] is False
    assert completed["requires_terminal_gate_validation"] is True
    receipt = completed["completion"]
    assert receipt["candidate_sha256"] == CANDIDATE
    assert receipt["slot14_audit_request_sha256"] == REQUEST_SHA
    assert receipt["diff_sha256"] == DIFF_SHA
    assert receipt["worker_done"][0]["name"] == "CODEX_FALLBACK_OUTPUT.DONE"
    assert len(receipt["bundle_receipt_sha256"]) == 64

    bridge_done = tmp_path / "queue/jobs" / handoff / "CAMINO_B_SLOT14_BRIDGE.DONE"
    assert bridge_done.is_file()
    assert queue.get_result(handoff, CANDIDATE)["result_ready"] is True


def test_bundle_without_done_is_rejected(tmp_path: Path) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    handoff = queue.request_review(_request())["handoff_id"]
    claim = queue.claim(
        handoff,
        CANDIDATE,
        worker_id="claude_code",
        route_id=PRIMARY_ROUTE,
        claim_id="CLAIM_primary_004",
        host_id="macbook",
    )
    bundle = _make_bundle(
        tmp_path,
        worker_id="claude_code",
        route_id=PRIMARY_ROUTE,
        status="ok",
    )
    (bundle / "CLAUDE_CODE_OUTPUT.DONE").unlink()
    error = _assert_error(
        "worker_bundle_invalid",
        lambda: queue.complete(
            handoff,
            CANDIDATE,
            claim_token=claim["claim_token"],
            bundle_dir=bundle,
        ),
    )
    assert "no_DONE_marker" in error.details["violations"]


def test_fallback_bundle_must_prove_sol_ultra_subscription_identity(tmp_path: Path) -> None:
    queue = LocalSlot14Queue(tmp_path / "queue")
    handoff = queue.request_review(_request())["handoff_id"]
    primary = queue.claim(
        handoff, CANDIDATE, worker_id="claude_code", route_id=PRIMARY_ROUTE,
        claim_id="CLAIM_primary_005", host_id="macbook",
    )
    failed = _make_bundle(
        tmp_path, worker_id="claude_code", route_id=PRIMARY_ROUTE,
        status="failed", error_class="auth_missing",
    )
    queue.complete(
        handoff, CANDIDATE, claim_token=primary["claim_token"], bundle_dir=failed,
    )
    fallback = queue.claim(
        handoff, CANDIDATE, worker_id="codex_fallback", route_id=FALLBACK_ROUTE,
        claim_id="CLAIM_fallback_003", host_id="imac",
    )
    bundle = _make_bundle(
        tmp_path, worker_id="codex_fallback", route_id=FALLBACK_ROUTE, status="ok",
    )
    result_path = bundle / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["model_id"] = "gpt-5.5"
    result_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = bundle / "OUTPUT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = _sha(result_path)
    manifest["files"][0]["size_bytes"] = result_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    _assert_error(
        "codex_fallback_subscription_identity_invalid",
        lambda: queue.complete(
            handoff, CANDIDATE, claim_token=fallback["claim_token"], bundle_dir=bundle,
        ),
    )


def test_contract_files_are_versioned_and_explicitly_not_deployed() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas/camino_b_slot14_bridge.schema.json").read_text(encoding="utf-8")
    )
    assert schema["x-camino-deployment-status"] == "contract_only_not_deployed"
    openapi = (root / "actions/CAMINO_B_SLOT14_BRIDGE_ACTIONS.v1.yaml").read_text(
        encoding="utf-8"
    )
    assert "x-camino-deployment-status: contract_only_not_deployed" in openapi
    assert "requestCaminoBSlot14SubscriptionReview" in openapi
    assert "getCaminoBSlot14SubscriptionReviewStatus" in openapi
    assert "getCaminoBSlot14SubscriptionReviewResult" in openapi
    assert "x-camino-replaces-existing-spec: false" in openapi
    assert "#/components/parameters" not in openapi
