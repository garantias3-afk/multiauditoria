from __future__ import annotations

import json
from pathlib import Path

from scripts.canon_loader import load_canon, resolve_profile
from scripts.slot_execution import (
    next_slot_decision, trip_provider_circuit_breaker, validate_slot_evidence,
)
from scripts.slot_runtime import build_slot_plan


ROOT = Path(__file__).resolve().parents[1]


def _documents():
    bundle = load_canon(ROOT)
    plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude")).to_serializable()
    return plan, bundle.routes


def test_slots_are_selected_in_exact_order() -> None:
    plan, routes = _documents()
    state = {"completed_slots": []}
    for expected in range(1, 15):
        decision = next_slot_decision(plan, routes, state)
        assert decision.slot_id == str(expected)
        state["completed_slots"].append(str(expected))
    assert next_slot_decision(plan, routes, state).status == "complete"


def test_glm_quota_uses_independent_free_then_plan_fallback() -> None:
    plan, routes = _documents()
    state = {"completed_slots": [str(value) for value in range(1, 7)]}
    decision = next_slot_decision(plan, routes, state)
    assert decision.slot_id == "7"
    assert decision.route_attempt_order == (
        "lmstudio_qwen3_coder_30b_a3b", "chatgpt_gpt_5_5_plan"
    )
    assert "zai_glm_5_1" not in decision.route_attempt_order


def test_provider_breaker_removes_every_route_of_provider() -> None:
    plan, routes = _documents()
    state = {"completed_slots": [str(value) for value in range(1, 7)]}
    trip_provider_circuit_breaker(state, "lmstudio_macbook_bridge", "memory_pressure")
    decision = next_slot_decision(plan, routes, state)
    assert decision.route_attempt_order == ("chatgpt_gpt_5_5_plan",)


def test_insufficient_evidence_never_completes_a_slot() -> None:
    ok, reason = validate_slot_evidence(
        {
            "slot_id": "4", "candidate_sha256": "a" * 64,
            "status": "insufficient_evidence",
        },
        slot_id="4", candidate_sha256="a" * 64,
    )
    assert not ok
    assert reason == "status_not_evidence"
