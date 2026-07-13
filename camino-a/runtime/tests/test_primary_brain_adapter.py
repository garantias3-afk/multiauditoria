from __future__ import annotations

import pytest

from scripts.primary_brain_adapter import build_brain_task, validate_external_response


def _input() -> dict:
    return {
        "run_id": "RUN_20260710_120000_abc12",
        "stage": "primary_consolidation",
        "candidate_sha256": "a" * 64,
        "iteration_number": 1,
        "slot_id": "3",
        "evidence_catalog": [
            {"source": "audit.md", "sha256": "b" * 64, "size_bytes": 10},
        ],
    }


def test_adapter_builds_request_not_a_verdict() -> None:
    task = build_brain_task(
        _input(), {"brain_current": "gpt_manual_or_configured", "policy": {}}
    )
    assert task["schema_version"] == "camino_gpt_brain_task.v1"
    assert "decision" not in task
    assert task["delivery"]["openai_api_forbidden"] is True


def test_external_response_requires_real_evidence_and_exact_candidate() -> None:
    task = build_brain_task(
        _input(), {"brain_current": "gpt_manual_or_configured", "policy": {}}
    )
    response = {
        "schema_version": "camino_gpt_brain_result.v1",
        "run_id": task["run_id"],
        "stage": task["stage"],
        "brain": task["brain"],
        "candidate_sha256": task["candidate_sha256"],
        "slot_id": task["slot_id"],
        "status": "completed",
        "decision": {"verdict": "OBSERVACIONES_NO_BLOQUEANTES"},
        "evidence_read": [{"source": "audit.md", "sha256": "b" * 64}],
    }
    validated = validate_external_response(response, task)
    assert validated["synthetic"] is False

    stale = dict(response, candidate_sha256="c" * 64)
    with pytest.raises(ValueError, match="candidate_sha256"):
        validate_external_response(stale, task)

    no_evidence = dict(response, evidence_read=[])
    with pytest.raises(ValueError, match="evidence_required"):
        validate_external_response(no_evidence, task)

    wrong_slot = dict(response, slot_id="6")
    with pytest.raises(ValueError, match="slot_id"):
        validate_external_response(wrong_slot, task)
