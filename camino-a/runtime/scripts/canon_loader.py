#!/usr/bin/env python3
"""canon_loader.py — shared mutable canon loader for Camino A / Camino B.

This module intentionally performs lightweight validation without external
packages. It is used by local scripts, tests and renderers so Camino A/B read
one canonical source for slots, routes and runtime policy.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CANON_FILENAMES = {
    "contract": "CANON_SHARED_CONTRACT_v1.md",
    "change_protocol": "CANON_CHANGE_PROTOCOL_v1.md",
    "routes": "CANON_PROVIDER_MODEL_ROUTES.v1.json",
    "slots": "CANON_WORKFLOW_SLOTS.v1.json",
    "runtime": "CANON_RUNTIME_POLICY.v1.json",
    "routes_schema": "CANON_PROVIDER_MODEL_ROUTES.v1.schema.json",
    "slots_schema": "CANON_WORKFLOW_SLOTS.v1.schema.json",
}


class CanonError(RuntimeError):
    pass


@dataclass(frozen=True)
class CanonBundle:
    canon_dir: Path
    contract_text: str
    routes: dict[str, Any]
    slots: dict[str, Any]
    runtime_policy: dict[str, Any]

    @property
    def canon_version(self) -> str:
        return str(self.routes.get("canon_version") or self.slots.get("canon_version") or "unknown")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CanonError(f"cannot_read_json:{path}:{exc}") from exc


def _candidate_canon_dirs(root: Path | None = None) -> list[Path]:
    root = root or ROOT
    return [root / "canon", root / "config", root]


def find_canon_dir(root: Path | None = None, explicit: Path | None = None) -> Path:
    if explicit is not None:
        d = explicit.expanduser().resolve()
        if not d.is_dir():
            raise CanonError(f"canon_dir_not_found:{d}")
        return d
    for d in _candidate_canon_dirs(root):
        if (d / CANON_FILENAMES["routes"]).exists() and (d / CANON_FILENAMES["slots"]).exists():
            return d
    raise CanonError("canon_files_not_found")


def load_canon(root: Path | None = None, canon_dir: Path | None = None) -> CanonBundle:
    d = find_canon_dir(root, canon_dir)
    contract = (d / CANON_FILENAMES["contract"]).read_text(encoding="utf-8")
    routes = read_json(d / CANON_FILENAMES["routes"])
    slots = read_json(d / CANON_FILENAMES["slots"])
    runtime_path = d / CANON_FILENAMES["runtime"]
    if not runtime_path.exists():
        runtime_path = (root or ROOT) / "config" / CANON_FILENAMES["runtime"]
    runtime = read_json(runtime_path) if runtime_path.exists() else default_runtime_policy()
    bundle = CanonBundle(d, contract, routes, slots, runtime)
    validate_canon(bundle)
    return bundle


def default_runtime_policy() -> dict[str, Any]:
    return {
        "schema_version": "canon_runtime_policy.v1",
        "canon_version": "missing_runtime_canon_version",
        "default_profile": "with_claude",
        "profiles": {
            "with_claude": {"claude_enabled": True, "enabled_workers": ["codex", "gateway", "claude_code", "manual_gpt", "manual_claude"]},
            "without_claude": {"claude_enabled": False, "enabled_workers": ["codex", "gateway", "manual_gpt"], "terminal_without_claude_reason": "ready_for_human_final_review"},
        },
        "api_policy": {"forbidden_env_vars_for_workers": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], "allow_paid_credit": False},
        "terminal_policy": {"require_accepted_evidence": True, "reject_stale_candidate": True},
    }


def validate_canon(bundle: CanonBundle) -> None:
    routes = bundle.routes
    slots = bundle.slots
    runtime = bundle.runtime_policy
    if not (bundle.canon_dir / CANON_FILENAMES["change_protocol"]).is_file():
        raise CanonError("canon_change_protocol_missing")
    if routes.get("schema_version") != "canon_provider_model_routes.v1":
        raise CanonError("bad_routes_schema_version")
    if slots.get("schema_version") != "canon_workflow_slots.v1":
        raise CanonError("bad_slots_schema_version")
    if runtime.get("schema_version") != "canon_runtime_policy.v1":
        raise CanonError("bad_runtime_policy_schema_version")
    versions = {
        "routes": str(routes.get("canon_version") or ""),
        "slots": str(slots.get("canon_version") or ""),
        "runtime": str(runtime.get("canon_version") or ""),
    }
    if any(not value for value in versions.values()) or len(set(versions.values())) != 1:
        raise CanonError(
            "canon_version_mismatch:"
            + ",".join(f"{name}={value or 'MISSING'}" for name, value in versions.items())
        )
    route_map = routes.get("routes")
    if not isinstance(route_map, dict) or not route_map:
        raise CanonError("routes_missing_or_empty")
    required_route_fields = set(routes.get("identity_fields") or [
        "route_id", "model_id", "provider_id", "provider_name", "route", "interface", "cost_class", "role"
    ])
    required_route_fields.discard("slot_id")
    missing_route_fields: list[str] = []
    for rid, data in route_map.items():
        if data.get("route_id") != rid:
            missing_route_fields.append(f"{rid}:route_id_mismatch")
        for field in required_route_fields:
            if field not in data and field != "role":
                missing_route_fields.append(f"{rid}:{field}")
    if missing_route_fields:
        raise CanonError("route_identity_fields_missing:" + ",".join(missing_route_fields[:20]))
    slot_map = slots.get("slots")
    if not isinstance(slot_map, dict) or len(slot_map) != 14:
        raise CanonError("slots_must_have_14_entries")
    big_slots = [str(x) for x in slots.get("big_loop", {}).get("slots", [])]
    if big_slots != [str(i) for i in range(1, 15)]:
        raise CanonError("big_loop_must_be_slots_1_to_14")
    def route_status_enabled(route: dict[str, Any]) -> bool:
        status = str(route.get("status") or "").strip().lower()
        return not (status.startswith("disabled") or "quota" in status)

    unknown: list[str] = []
    for sid, slot in slot_map.items():
        for field in ("cycle", "role", "loops", "correction_policy", "routes"):
            if field not in slot:
                raise CanonError(f"slot_{sid}_missing_{field}")
        for rid in slot.get("routes") or []:
            if rid not in route_map:
                unknown.append(f"slot_{sid}:{rid}")
        fallbacks = [str(rid) for rid in (slot.get("fallback_chain") or [])]
        if len(fallbacks) != len(set(fallbacks)):
            raise CanonError(f"slot_{sid}_fallback_chain_has_duplicates")
        primary_routes = [str(rid) for rid in (slot.get("routes") or [])]
        overlap = sorted(set(primary_routes) & set(fallbacks))
        if overlap:
            raise CanonError(f"slot_{sid}_fallback_repeats_primary:{','.join(overlap)}")
        for rid in fallbacks:
            if rid not in route_map:
                unknown.append(f"slot_{sid}:fallback:{rid}")

        breaker = (slot.get("special") or {}).get("provider_circuit_breaker")
        if breaker is not None:
            if not isinstance(breaker, dict) or not str(breaker.get("provider_id") or ""):
                raise CanonError(f"slot_{sid}_bad_provider_circuit_breaker")
            provider_id = str(breaker["provider_id"])
            if not any(
                str(route_map.get(rid, {}).get("provider_id") or "") == provider_id
                for rid in primary_routes
            ):
                raise CanonError(f"slot_{sid}_circuit_breaker_provider_not_primary:{provider_id}")
            independent = [
                route_map[rid] for rid in fallbacks if rid in route_map
                and str(route_map[rid].get("provider_id") or "") != provider_id
                and route_status_enabled(route_map[rid])
                and any(token in str(route_map[rid].get("cost_class") or "").lower()
                        for token in ("free", "plan"))
            ]
            if not independent:
                raise CanonError(f"slot_{sid}_missing_enabled_independent_free_or_plan_fallback")
    if unknown:
        raise CanonError("slot_references_unknown_routes:" + ",".join(unknown[:20]))

    sol_actions = route_map.get("chatgpt_gpt_5_6_sol_actions_plan", {})
    required_sol_actions = {
        "provider_id": "chatgpt_plan",
        "model_id": "gpt-5.6-sol",
        "route": "chatgpt_custom_gpt_actions",
        "interface": "interactive_plan",
        "surface": "custom_gpt_actions",
        "required_mode": "non_pro",
        "preferred_reasoning_level": "high",
        "actions_required": True,
        "api_key_allowed": False,
        "availability_gate": "builder_model_picker_and_live_action_smoke",
        "fallback_route_id": "chatgpt_gpt_5_5_plan",
    }
    if any(sol_actions.get(key) != value for key, value in required_sol_actions.items()):
        raise CanonError("chatgpt_sol_actions_route_invalid")
    builder_verification = sol_actions.get("builder_verification")
    if route_status_enabled(sol_actions) and (
        not isinstance(builder_verification, dict)
        or builder_verification.get("status") != "verified"
        or not str(builder_verification.get("verified_at_utc") or "").strip()
        or not str(builder_verification.get("action_smoke_evidence") or "").strip()
    ):
        raise CanonError("chatgpt_sol_actions_route_enabled_without_builder_smoke")
    expected_brain_slots = {
        "3": (["chatgpt_gpt_5_6_sol_actions_plan"], ["chatgpt_gpt_5_5_plan"]),
        "6": (["chatgpt_gpt_5_6_sol_actions_plan"], ["chatgpt_gpt_5_5_plan"]),
        "10": (["chatgpt_gpt_5_6_sol_actions_plan"], ["chatgpt_gpt_5_5_plan"]),
        "7": (["zai_glm_5_1"], [
            "lmstudio_qwen3_coder_30b_a3b",
            "chatgpt_gpt_5_6_sol_actions_plan",
            "chatgpt_gpt_5_5_plan",
        ]),
        "13": (["zai_glm_5_2"], [
            "lmstudio_qwen3_coder_30b_a3b",
            "chatgpt_gpt_5_6_sol_actions_plan",
            "chatgpt_gpt_5_5_plan",
        ]),
    }
    for sid, (expected_routes, expected_fallbacks) in expected_brain_slots.items():
        slot = slot_map.get(sid, {})
        if list(slot.get("routes") or []) != expected_routes:
            raise CanonError(f"slot_{sid}_sol_actions_primary_route_invalid")
        if list(slot.get("fallback_chain") or []) != expected_fallbacks:
            raise CanonError(f"slot_{sid}_sol_actions_fallback_chain_invalid")

    if slots.get("general_rules", {}).get("approval") != (
        "slot_14_claude_or_codex_subscription_fallback_only_without_corrections_or_findings"
    ):
        raise CanonError("slot_14_general_approval_rule_invalid")

    slot14 = slot_map.get("14", {})
    if slot14.get("executor_worker") != "claude_code":
        raise CanonError("slot_14_executor_worker_must_be_claude_code")
    if slot14.get("execution_mode") != "automatic_cli":
        raise CanonError("slot_14_execution_mode_must_be_automatic_cli")
    approval = slot14.get("approval_contract")
    required_approval = {
        "verdict": "APPROVED_BY_CLAUDE_OR_CODEX_SUBSCRIPTION_FALLBACK",
        "primary_verdict": "APPROVED_BY_CLAUDE",
        "fallback_verdict": "APPROVED_BY_CODEX_FALLBACK",
        "fallback_route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
        "fallback_requires_primary_unavailable": True,
        "requires_slot_id": "14",
        "requires_no_corrections": True,
        "requires_no_findings": True,
        "requires_current_candidate_sha256": True,
        "requires_prior_slots_complete": True,
    }
    if not isinstance(approval, dict) or any(approval.get(k) != v for k, v in required_approval.items()):
        raise CanonError("slot_14_approval_contract_invalid")
    slot14_routes = list(slot14.get("routes") or [])
    if len(slot14_routes) != 1:
        raise CanonError("slot_14_requires_exactly_one_cli_route")
    slot14_route = route_map.get(str(slot14_routes[0]), {})
    if (
        slot14_route.get("executor_worker") != "claude_code"
        or slot14_route.get("execution_mode") != "automatic_cli"
        or not route_status_enabled(slot14_route)
    ):
        raise CanonError("slot_14_cli_route_contract_invalid")
    slot14_fallbacks = list(slot14.get("fallback_chain") or [])
    if slot14_fallbacks != ["codex_gpt_5_6_sol_ultra_subscription_cli"]:
        raise CanonError("slot_14_codex_subscription_fallback_required")
    codex_fallback = route_map.get(slot14_fallbacks[0], {})
    if (
        codex_fallback.get("executor_worker") != "codex_fallback"
        or codex_fallback.get("execution_mode") != "automatic_cli_fallback"
        or codex_fallback.get("model_id") != "gpt-5.6-sol"
        or codex_fallback.get("model_reasoning_effort") != "ultra"
        or codex_fallback.get("api_key_allowed") is not False
        or not route_status_enabled(codex_fallback)
    ):
        raise CanonError("slot_14_codex_subscription_fallback_contract_invalid")
    required_fallback_isolation = {
        "process_isolation": "separate_codex_exec",
        "inherits_orchestrator_model": False,
        "self_model_switch": False,
    }
    if any(
        codex_fallback.get(key) != value
        for key, value in required_fallback_isolation.items()
    ):
        raise CanonError("slot_14_codex_subscription_fallback_isolation_invalid")
    if (
        codex_fallback.get("unavailable_policy")
        != "fail_closed_operator_action_required"
        or codex_fallback.get("manual_or_desktop_result_may_approve") is not False
    ):
        raise CanonError("slot_14_codex_subscription_fallback_contingency_invalid")
    profiles = runtime.get("profiles")
    if not isinstance(profiles, dict) or not {"with_claude", "without_claude"}.issubset(profiles):
        raise CanonError("runtime_policy_profiles_missing")
    for required_name in ("with_claude", "without_claude"):
        if profiles[required_name].get("require_gpt_brain_evidence") is not True:
            raise CanonError(f"profile_{required_name}_must_require_gpt_brain_evidence")
    sandbox = profiles.get("sandbox_reference")
    if not isinstance(sandbox, dict):
        raise CanonError("sandbox_reference_profile_missing")
    if sandbox.get("claude_enabled") is not False:
        raise CanonError("sandbox_reference_must_disable_claude")
    if sandbox.get("require_gpt_brain_evidence") is not False:
        raise CanonError("sandbox_reference_must_not_require_gpt_brain_evidence")
    if "local_static" not in set(sandbox.get("enabled_workers") or []):
        raise CanonError("sandbox_reference_must_enable_local_static")


def resolve_profile(bundle: CanonBundle, profile_name: str | None = None) -> dict[str, Any]:
    policy = bundle.runtime_policy
    name = profile_name or policy.get("default_profile") or "with_claude"
    profiles = policy.get("profiles", {})
    if name not in profiles:
        raise CanonError(f"unknown_runtime_profile:{name}")
    p = dict(profiles[name])
    p["profile_name"] = name
    p["api_policy"] = policy.get("api_policy", {})
    p["heartbeat_policy"] = policy.get("heartbeat_policy", {})
    p["slot_defaults"] = policy.get("slot_defaults", {})
    p["worker_limits"] = policy.get("worker_limits", {})
    p["terminal_policy"] = policy.get("terminal_policy", {})
    return p


def canon_summary(bundle: CanonBundle, profile: dict[str, Any]) -> dict[str, Any]:
    slots = bundle.slots.get("slots", {})
    routes = bundle.routes.get("routes", {})
    return {
        "canon_version": bundle.canon_version,
        "canon_dir": str(bundle.canon_dir),
        "profile": profile.get("profile_name"),
        "claude_enabled": bool(profile.get("claude_enabled")),
        "enabled_workers": list(profile.get("enabled_workers", [])),
        "slot_count": len(slots),
        "route_count": len(routes),
        "big_loop": bundle.slots.get("big_loop", {}).get("slots", []),
        "cycles": bundle.slots.get("cycles", {}),
        "forbidden_api_env_vars": profile.get("api_policy", {}).get("forbidden_env_vars_for_workers", []),
    }


def copy_canon_snapshot(dst_dir: Path, bundle: CanonBundle) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for filename in CANON_FILENAMES.values():
        src = bundle.canon_dir / filename
        if src.exists():
            shutil.copy2(src, dst_dir / filename)


def profile_enabled_workers(profile: dict[str, Any]) -> set[str]:
    return set(profile.get("enabled_workers") or [])


def worker_enabled(profile: dict[str, Any], worker_id: str) -> bool:
    return worker_id in profile_enabled_workers(profile)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Validate Camino shared canon")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--canon-dir", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--validate", action="store_true",
                        help="Correr validate_canon (fail-closed) antes de imprimir el summary. "
                             "Falla con exit!=0 si un slot referencia un route_id inexistente, "
                             "faltan campos de identidad, o el schema_version es inválido.")
    args = parser.parse_args()
    try:
        bundle = load_canon(Path(args.root), Path(args.canon_dir) if args.canon_dir else None)
        if args.validate:
            validate_canon(bundle)
        profile = resolve_profile(bundle, args.profile)
    except CanonError as exc:
        # Fail closed: canon inválido no debe permitir iniciar una corrida.
        print(f"CANON_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(canon_summary(bundle, profile), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
