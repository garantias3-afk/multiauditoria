#!/usr/bin/env python3
"""Pure slot-order and executor decisions for the 14-slot runtime.

The module does not call providers.  It turns the immutable per-run slot plan
and route snapshot into the next executable action, applies run-scoped circuit
breakers, and validates that evidence belongs to the current slot/candidate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SlotDecision:
    status: str
    slot_id: Optional[str]
    role: Optional[str]
    correction_policy: Optional[str]
    route_attempt_order: Tuple[str, ...]
    executors: Dict[str, Tuple[str, ...]]
    manual_required: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["route_attempt_order"] = list(self.route_attempt_order)
        value["executors"] = {key: list(routes) for key, routes in self.executors.items()}
        return value


def executor_for_route(route: Mapping[str, Any]) -> str:
    explicit = str(route.get("executor_worker") or "").strip()
    if explicit:
        return explicit
    interface = str(route.get("interface") or "").lower()
    provider = str(route.get("provider_id") or "").lower()
    route_kind = str(route.get("route") or "").lower()
    if "lmstudio" in provider or "lmstudio" in route_kind:
        return "lmstudio_bridge"
    if interface == "claude_cli":
        return "claude_code"
    if provider == "chatgpt_plan":
        return "manual_gpt"
    if "claude" in provider and "manual" in (interface + route_kind + provider):
        return "manual_claude"
    return "gateway"


def _ordered_slots(plan: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    slots = plan.get("slots")
    return slots if isinstance(slots, list) else []


def next_slot_decision(
    plan: Mapping[str, Any],
    routes: Mapping[str, Any],
    state: Mapping[str, Any],
) -> SlotDecision:
    completed = {str(value) for value in (state.get("completed_slots") or [])}
    breakers = {str(value) for value in (state.get("provider_circuit_breakers") or [])}
    route_map = routes.get("routes", routes)
    route_map = route_map if isinstance(route_map, dict) else {}

    current = None
    for slot in _ordered_slots(plan):
        sid = str(slot.get("slot_id") or "")
        if sid and sid not in completed:
            current = slot
            break
    if current is None:
        return SlotDecision("complete", None, None, None, (), {}, False,
                            "all_slots_completed")

    sid = str(current.get("slot_id"))
    raw_order = current.get("route_attempt_order") or current.get("enabled_routes") or []
    ordered = []
    executors: Dict[str, list[str]] = {}
    for route_id in raw_order:
        route_id = str(route_id)
        route = route_map.get(route_id, {})
        if not isinstance(route, dict):
            continue
        provider = str(route.get("provider_id") or "")
        if provider and provider in breakers:
            continue
        status = str(route.get("status") or "").lower()
        if status.startswith("disabled") or "quota" in status:
            continue
        ordered.append(route_id)
        executor = executor_for_route(route)
        executors.setdefault(executor, []).append(route_id)

    role = str(current.get("role") or "")
    policy = str(current.get("correction_policy") or "")
    if not raw_order:
        return SlotDecision("ready", sid, role, policy, (), {}, False,
                            "manual_or_harvest_slot_without_routes")
    if not ordered:
        return SlotDecision("unavailable", sid, role, policy, (), {}, False,
                            "no_enabled_route_after_policy_and_circuit_breakers")
    frozen = {key: tuple(value) for key, value in executors.items()}
    manual = any(key in {"manual_gpt", "manual_claude"} for key in frozen)
    return SlotDecision("ready", sid, role, policy, tuple(ordered), frozen,
                        manual, "canon_order_resolved")


def validate_slot_evidence(
    result: Mapping[str, Any],
    *,
    slot_id: str,
    candidate_sha256: str,
) -> Tuple[bool, str]:
    if str(result.get("slot_id") or "") != str(slot_id):
        return False, "slot_id_mismatch"
    if str(result.get("candidate_sha256") or "") != str(candidate_sha256):
        return False, "candidate_sha256_mismatch"
    if str(result.get("status") or "") not in {
        "ok", "completed", "bug_found", "patch_proposed",
    }:
        return False, "status_not_evidence"
    return True, "valid"


def trip_provider_circuit_breaker(
    state: Dict[str, Any], provider_id: str, reason: str,
) -> None:
    providers = {str(value) for value in (state.get("provider_circuit_breakers") or [])}
    providers.add(str(provider_id))
    state["provider_circuit_breakers"] = sorted(providers)
    events = list(state.get("circuit_breaker_events") or [])
    events.append({"provider_id": str(provider_id), "reason": str(reason)})
    state["circuit_breaker_events"] = events
