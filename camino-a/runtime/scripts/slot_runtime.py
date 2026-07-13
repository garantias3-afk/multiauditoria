#!/usr/bin/env python3
"""slot_runtime.py — canon-driven slot execution plan.

This module is the *single* place that turns the mutable canon
(CANON_WORKFLOW_SLOTS + CANON_RUNTIME_POLICY, loaded by canon_loader) into an
ordered execution plan the entrypoint can iterate over.

HARD RULE (spec §10/§11): this module contains NO hardcoded list of slots,
providers, models, fallbacks or close rules. Every value comes from the
CanonBundle. Change the JSON → the plan changes → the flow changes, with no
code edit. `tests/test_v13_canonical_entrypoint.py::test_03_*` enforces this.

Public API:
    build_slot_plan(bundle, profile) -> SlotPlan
    SlotPlan.slots            -> list[SlotSpec] in big_loop order
    slot_max_internal_loops(spec, runtime_policy) -> int
    SlotPlan.approver_slot_ids -> ids whose canon defines terminal approval
    SlotPlan.to_serializable() -> dict (snapshot into the run)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scripts.canon_loader import CanonBundle, CanonError


@dataclass(frozen=True)
class SlotSpec:
    slot_id: str
    cycle: str
    role: str
    loops: int | None
    correction_policy: str
    routes: tuple[str, ...]
    fallback_chain: tuple[str, ...]
    enabled_routes: tuple[str, ...]
    enabled_fallback_chain: tuple[str, ...]
    route_attempt_order: tuple[str, ...]
    enabled: bool
    is_approver: bool
    terminal_if_no_corrections: str | None
    executor_worker: str | None
    execution_mode: str | None
    approval_contract: dict[str, Any] = field(default_factory=dict)
    special: dict[str, Any] = field(default_factory=dict)
    internal_loop: dict[str, Any] = field(default_factory=dict)

    def to_serializable(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "cycle": self.cycle,
            "role": self.role,
            "loops": self.loops,
            "correction_policy": self.correction_policy,
            "routes": list(self.routes),
            "fallback_chain": list(self.fallback_chain),
            "enabled_routes": list(self.enabled_routes),
            "enabled_fallback_chain": list(self.enabled_fallback_chain),
            "route_attempt_order": list(self.route_attempt_order),
            "enabled": self.enabled,
            "is_approver": self.is_approver,
            "terminal_if_no_corrections": self.terminal_if_no_corrections,
            "executor_worker": self.executor_worker,
            "execution_mode": self.execution_mode,
            "approval_contract": self.approval_contract,
            "special": self.special,
            "internal_loop": self.internal_loop,
        }


@dataclass(frozen=True)
class SlotPlan:
    canon_version: str
    profile_name: str
    claude_enabled: bool
    slots: tuple[SlotSpec, ...]
    approver_slot_ids: tuple[str, ...]
    general_rules: dict[str, Any]
    slot_defaults: dict[str, Any]

    def to_serializable(self) -> dict[str, Any]:
        return {
            "schema_version": "camino_slot_plan.v1",
            "canon_version": self.canon_version,
            "profile": self.profile_name,
            "claude_enabled": self.claude_enabled,
            "approver_slot_ids": list(self.approver_slot_ids),
            "general_rules": self.general_rules,
            "slot_defaults": self.slot_defaults,
            "slots": [s.to_serializable() for s in self.slots],
        }

    def slot(self, slot_id: str) -> SlotSpec:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        raise CanonError(f"slot_not_in_plan:{slot_id}")


def _route_requires_claude(route: dict[str, Any]) -> bool:
    """Derive from the route record whether it needs Claude (never hardcoded).

    A route needs Claude if its provider/model/route identity references
    anthropic/claude. This lets the without_claude profile drop those routes
    without the runtime naming any specific model in code.
    """
    haystack = " ".join(
        str(route.get(k, "")).lower()
        for k in ("provider_id", "provider_name", "model_id", "route", "route_id", "interface")
    )
    return "claude" in haystack or "anthropic" in haystack


def route_status_is_enabled(route: dict[str, Any]) -> bool:
    """Return False for canon routes explicitly disabled by quota/policy.

    Availability still needs a live probe where the route contract requires it;
    this helper only prevents a route already known to be disabled/quota-bound
    from entering the ordered attempt list.
    """
    status = str(route.get("status") or "").strip().lower()
    if not status:
        return True
    return not (status.startswith("disabled") or "quota" in status)


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def resolve_enabled_route_order(spec: SlotSpec) -> tuple[str, ...]:
    """Return primary routes followed by independent fallbacks, in canon order."""
    return spec.route_attempt_order


def build_slot_plan(bundle: CanonBundle, profile: dict[str, Any]) -> SlotPlan:
    """Build the ordered slot plan for ``profile`` straight from the canon."""
    slots_doc = bundle.slots
    route_map = bundle.routes.get("routes", {})
    big_loop = [str(x) for x in slots_doc.get("big_loop", {}).get("slots", [])]
    slot_map = slots_doc.get("slots", {})
    claude_enabled = bool(profile.get("claude_enabled"))
    enabled_workers = set(profile.get("enabled_workers") or [])
    disabled_workers = set(profile.get("disabled_workers") or [])

    specs: list[SlotSpec] = []
    approver_ids: list[str] = []
    for sid in big_loop:
        slot = slot_map.get(sid)
        if not isinstance(slot, dict):
            raise CanonError(f"slot_missing_in_canon:{sid}")

        routes = tuple(str(r) for r in (slot.get("routes") or []))
        fallback = tuple(str(r) for r in (slot.get("fallback_chain") or []))
        terminal_if_no_corr = slot.get("terminal_if_no_corrections")
        approval_contract = dict(slot.get("approval_contract") or {})
        is_approver = bool(terminal_if_no_corr or approval_contract)
        if is_approver:
            approver_ids.append(sid)

        def route_allowed(route_id: str) -> bool:
            route = route_map.get(route_id, {})
            if not route_status_is_enabled(route):
                return False
            explicit_worker = str(route.get("executor_worker") or "")
            if explicit_worker and (
                explicit_worker in disabled_workers
                or (enabled_workers and explicit_worker not in enabled_workers)
            ):
                return False
            return claude_enabled or not _route_requires_claude(route)

        # Preserve canon order, drop known disabled/quota routes, and never
        # manufacture a duplicate attempt across primary/fallback lists.
        enabled_routes = _ordered_unique(tuple(r for r in routes if route_allowed(r)))
        fallback_unique = _ordered_unique(fallback)
        enabled_fallback = tuple(
            r for r in fallback_unique
            if r not in routes and route_allowed(r)
        )
        route_attempt_order = _ordered_unique(enabled_routes + enabled_fallback)

        route_for_executor = {}
        for route_id in route_attempt_order + routes + fallback_unique:
            candidate = route_map.get(route_id, {})
            if candidate:
                route_for_executor = candidate
                break
        executor_worker = str(
            slot.get("executor_worker")
            or route_for_executor.get("executor_worker")
            or ""
        ) or None
        execution_mode = str(
            slot.get("execution_mode")
            or route_for_executor.get("execution_mode")
            or ""
        ) or None

        # A slot is "enabled" for automatic execution when it either has no
        # provider routes (manual/harvest slots) or has at least one route that
        # survives the profile filter. Approver slots that lose their only route
        # under without_claude are recorded but not auto-approving — the
        # entrypoint routes their outcome to human final review via canon.
        enabled = (not routes and not fallback) or bool(route_attempt_order)

        specs.append(SlotSpec(
            slot_id=sid,
            cycle=str(slot.get("cycle", "")),
            role=str(slot.get("role", "")),
            loops=slot.get("loops") if isinstance(slot.get("loops"), int) else None,
            correction_policy=str(slot.get("correction_policy", "")),
            routes=routes,
            fallback_chain=fallback,
            enabled_routes=enabled_routes,
            enabled_fallback_chain=enabled_fallback,
            route_attempt_order=route_attempt_order,
            enabled=enabled,
            is_approver=is_approver,
            terminal_if_no_corrections=(str(terminal_if_no_corr) if terminal_if_no_corr else None),
            executor_worker=executor_worker,
            execution_mode=execution_mode,
            approval_contract=approval_contract,
            special=dict(slot.get("special") or {}),
            internal_loop=dict(slot.get("internal_loop") or {}),
        ))

    return SlotPlan(
        canon_version=bundle.canon_version,
        profile_name=str(profile.get("profile_name", "unknown")),
        claude_enabled=claude_enabled,
        slots=tuple(specs),
        approver_slot_ids=tuple(approver_ids),
        general_rules=dict(slots_doc.get("general_rules") or {}),
        slot_defaults=dict(profile.get("slot_defaults") or {}),
    )


def slot_max_internal_loops(spec: SlotSpec, runtime_policy: dict[str, Any] | None) -> int:
    """Resolve the internal-loop budget for a slot.

    Precedence (all from canon, never hardcoded):
      1. slot.loops when the slot defines an explicit integer budget.
      2. runtime_policy.slot_defaults.max_internal_loops otherwise.
      3. profile.slot_defaults.max_internal_loops as a final fallback.
    """
    internal_max = spec.internal_loop.get("max_iterations")
    if bool(spec.internal_loop.get("required")) and isinstance(internal_max, int) and internal_max > 0:
        return internal_max
    if isinstance(spec.loops, int) and spec.loops > 0:
        return spec.loops
    defaults = (runtime_policy or {}).get("slot_defaults") or {}
    val = defaults.get("max_internal_loops")
    if isinstance(val, int) and val > 0:
        return val
    raise CanonError("max_internal_loops_not_defined_in_canon")


def blocks_within_limit(correction_policy: str) -> bool:
    """True when the canon says this slot must correct findings within the loop
    limit (BLOCKING_WITHIN_LIMIT / RESTART_BIG_LOOP_...). Derived from the
    policy token text so new tokens containing BLOCKING/RESTART also count."""
    p = (correction_policy or "").upper()
    return "BLOCKING" in p or "RESTART" in p
