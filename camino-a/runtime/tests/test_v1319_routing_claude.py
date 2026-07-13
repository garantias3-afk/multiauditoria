from __future__ import annotations

import json
import os
import hashlib
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.canon_loader import CANON_FILENAMES, CanonBundle, CanonError, load_canon, resolve_profile, validate_canon
from scripts.slot_runtime import build_slot_plan
from scripts.validate_bundle import validate_bundle
from scripts.worker_claude_code import (
    APPROVAL_VERDICT,
    check_claude_auth,
    load_claude_route,
    run_claude_code,
    write_bundle,
)


ROOT = Path(__file__).resolve().parents[1]


class CanonRoutingTests(unittest.TestCase):
    def test_versions_and_slot14_contract_are_coherent(self) -> None:
        bundle = load_canon(ROOT)
        self.assertTrue((bundle.canon_dir / CANON_FILENAMES["change_protocol"]).is_file())
        self.assertEqual(bundle.canon_version, "camino_shared_canon.v1.3.21-slot14-handoff")
        self.assertEqual(bundle.routes["canon_version"], bundle.slots["canon_version"])
        self.assertEqual(bundle.routes["canon_version"], bundle.runtime_policy["canon_version"])
        self.assertEqual(bundle.runtime_policy["default_profile"], "with_claude")
        self.assertEqual(
            bundle.slots["general_rules"]["approval"],
            "slot_14_claude_or_codex_subscription_fallback_only_without_corrections_or_findings",
        )
        self.assertTrue(bundle.runtime_policy["profiles"]["with_claude"]["require_gpt_brain_evidence"])
        self.assertTrue(bundle.runtime_policy["profiles"]["without_claude"]["require_gpt_brain_evidence"])
        sandbox = resolve_profile(bundle, "sandbox_reference")
        self.assertFalse(sandbox["claude_enabled"])
        self.assertFalse(sandbox["require_gpt_brain_evidence"])
        self.assertIn("local_static", sandbox["enabled_workers"])
        sandbox_plan = build_slot_plan(bundle, sandbox)
        self.assertFalse(sandbox_plan.slot("14").enabled)
        self.assertEqual(sandbox_plan.slot("14").route_attempt_order, ())

        plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
        slot14 = plan.slot("14")
        self.assertEqual(slot14.executor_worker, "claude_code")
        self.assertEqual(slot14.execution_mode, "automatic_cli")
        self.assertEqual(slot14.route_attempt_order, (
            "claude_code_subscription_cli",
            "codex_gpt_5_6_sol_ultra_subscription_cli",
        ))
        self.assertEqual(slot14.approval_contract["primary_verdict"], APPROVAL_VERDICT)
        self.assertEqual(slot14.approval_contract["fallback_verdict"], "APPROVED_BY_CODEX_FALLBACK")
        self.assertTrue(slot14.approval_contract["requires_no_corrections"])
        codex_fallback = bundle.routes["routes"]["codex_gpt_5_6_sol_ultra_subscription_cli"]
        self.assertEqual(codex_fallback["process_isolation"], "separate_codex_exec")
        self.assertFalse(codex_fallback["inherits_orchestrator_model"])
        self.assertFalse(codex_fallback["self_model_switch"])
        self.assertEqual(
            codex_fallback["unavailable_policy"],
            "fail_closed_operator_action_required",
        )
        self.assertFalse(codex_fallback["manual_or_desktop_result_may_approve"])
        serialized = slot14.to_serializable()
        self.assertIn("special", serialized)
        self.assertIn("approval_contract", serialized)

    def test_disabled_glm_routes_resolve_to_ordered_independent_fallbacks(self) -> None:
        bundle = load_canon(ROOT)
        plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
        expected = ("lmstudio_qwen3_coder_30b_a3b", "chatgpt_gpt_5_5_plan")
        for slot_id in ("7", "13"):
            slot = plan.slot(slot_id)
            self.assertEqual(slot.enabled_routes, ())
            self.assertEqual(slot.enabled_fallback_chain, expected)
            self.assertEqual(slot.route_attempt_order, expected)
            self.assertEqual(len(slot.route_attempt_order), len(set(slot.route_attempt_order)))
            self.assertEqual(
                slot.special["provider_circuit_breaker"]["provider_id"],
                "zai_glm",
            )

    def test_without_claude_uses_subscription_codex_fallback(self) -> None:
        bundle = load_canon(ROOT)
        plan = build_slot_plan(bundle, resolve_profile(bundle, "without_claude"))
        slot14 = plan.slot("14")
        self.assertTrue(slot14.enabled)
        self.assertEqual(slot14.route_attempt_order, ("codex_gpt_5_6_sol_ultra_subscription_cli",))

    def test_version_mismatch_fails_closed(self) -> None:
        bundle = load_canon(ROOT)
        bad_runtime = dict(bundle.runtime_policy)
        bad_runtime["canon_version"] = "different"
        bad = CanonBundle(
            bundle.canon_dir,
            bundle.contract_text,
            bundle.routes,
            bundle.slots,
            bad_runtime,
        )
        with self.assertRaisesRegex(CanonError, "canon_version_mismatch"):
            validate_canon(bad)

    def test_sol_actions_is_preferred_but_filtered_until_builder_smoke(self) -> None:
        bundle = load_canon(ROOT)
        route = bundle.routes["routes"]["chatgpt_gpt_5_6_sol_actions_plan"]
        self.assertEqual(route["model_id"], "gpt-5.6-sol")
        self.assertEqual(route["surface"], "custom_gpt_actions")
        self.assertEqual(route["required_mode"], "non_pro")
        self.assertEqual(route["preferred_reasoning_level"], "high")
        self.assertEqual(route["status"], "disabled_pending_builder_verification")
        self.assertEqual(
            route["builder_verification"]["status"],
            "camino_a_verified_camino_b_pending",
        )
        self.assertEqual(route["builder_verification"]["visible_reasoning_level"], "high")
        builder_gpts = route["builder_verification"]["gpts"]
        self.assertTrue(builder_gpts["camino_a_cerebro"]["published"])
        self.assertEqual(
            builder_gpts["camino_a_cerebro"]["action_operation_count"], 15
        )
        self.assertFalse(builder_gpts["camino_b_auditor_externo"]["published"])
        self.assertIsNone(builder_gpts["camino_b_auditor_externo"]["action_smoke"])

        brain_policy = json.loads(
            (ROOT / "config" / "primary_brain_policy.json").read_text(encoding="utf-8")
        )["model_policy"]
        self.assertEqual(brain_policy["preferred_route_id"], route["route_id"])
        self.assertEqual(brain_policy["preferred_model_id"], route["model_id"])
        self.assertEqual(
            brain_policy["preferred_reasoning_level"], route["preferred_reasoning_level"]
        )
        self.assertFalse(brain_policy["api_key_allowed"])
        self.assertFalse(brain_policy["responses_api_active"])

        for slot_id in ("3", "6", "10"):
            raw = bundle.slots["slots"][slot_id]
            self.assertEqual(raw["routes"], [route["route_id"]])
            self.assertEqual(raw["fallback_chain"], ["chatgpt_gpt_5_5_plan"])
        for slot_id, glm_route in (("7", "zai_glm_5_1"), ("13", "zai_glm_5_2")):
            raw = bundle.slots["slots"][slot_id]
            self.assertEqual(raw["routes"], [glm_route])
            self.assertEqual(raw["fallback_chain"], [
                "lmstudio_qwen3_coder_30b_a3b",
                route["route_id"],
                "chatgpt_gpt_5_5_plan",
            ])

        plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
        self.assertEqual(plan.slot("3").route_attempt_order, ("chatgpt_gpt_5_5_plan",))
        self.assertEqual(plan.slot("7").route_attempt_order, (
            "lmstudio_qwen3_coder_30b_a3b", "chatgpt_gpt_5_5_plan",
        ))

    def test_sol_actions_cannot_be_enabled_without_builder_evidence(self) -> None:
        bundle = load_canon(ROOT)
        routes = json.loads(json.dumps(bundle.routes))
        routes["routes"]["chatgpt_gpt_5_6_sol_actions_plan"]["status"] = "manual_or_action"
        bad = CanonBundle(
            bundle.canon_dir,
            bundle.contract_text,
            routes,
            bundle.slots,
            bundle.runtime_policy,
        )
        with self.assertRaisesRegex(
            CanonError, "chatgpt_sol_actions_route_enabled_without_builder_smoke"
        ):
            validate_canon(bad)

    def test_slot14_codex_fallback_isolation_and_contingency_fail_closed(self) -> None:
        bundle = load_canon(ROOT)
        route_id = "codex_gpt_5_6_sol_ultra_subscription_cli"
        mutations = (
            ("process_isolation", "in_process"),
            ("inherits_orchestrator_model", True),
            ("self_model_switch", True),
        )
        for field, value in mutations:
            routes = json.loads(json.dumps(bundle.routes))
            routes["routes"][route_id][field] = value
            bad = CanonBundle(
                bundle.canon_dir, bundle.contract_text, routes,
                bundle.slots, bundle.runtime_policy,
            )
            with self.assertRaisesRegex(
                CanonError,
                "slot_14_codex_subscription_fallback_isolation_invalid",
            ):
                validate_canon(bad)

        for field, value in (
            ("unavailable_policy", "continue_without_review"),
            ("manual_or_desktop_result_may_approve", True),
        ):
            routes = json.loads(json.dumps(bundle.routes))
            routes["routes"][route_id][field] = value
            bad = CanonBundle(
                bundle.canon_dir, bundle.contract_text, routes,
                bundle.slots, bundle.runtime_policy,
            )
            with self.assertRaisesRegex(
                CanonError,
                "slot_14_codex_subscription_fallback_contingency_invalid",
            ):
                validate_canon(bad)

    def test_path_model_policies_do_not_bind_slot14_to_orchestrator_model(self) -> None:
        roles = json.loads((ROOT / "config" / "roles.json").read_text(encoding="utf-8"))
        path_roles = json.loads(
            (ROOT / "config" / "path_roles.json").read_text(encoding="utf-8")
        )
        for document in (roles, path_roles):
            camino_a = document["paths"]["camino_a"]
            policy_a = camino_a["orchestrator_model_policy"]
            self.assertEqual(policy_a["selection_mode"], "operator_selected")
            self.assertEqual(policy_a["model_tier_preference"], "low")
            self.assertEqual(policy_a["reasoning_preference"], "low")
            self.assertEqual(policy_a["cost_preference"], "low")
            self.assertIsNone(policy_a["fixed_model_id"])
            self.assertFalse(policy_a["self_model_switch_for_slot_14"])
            self.assertEqual(
                camino_a["slot_14_reviewer_process"], "independent_codex_cli"
            )

            camino_b = document["paths"]["camino_b"]
            policy_b = camino_b["orchestrator_model_policy"]
            self.assertEqual(policy_b["selection_mode"], "gpt_desktop")
            self.assertEqual(policy_b["reasoning_level"], "high")
            self.assertIsNone(policy_b["fixed_model_id"])
            self.assertFalse(policy_b["self_model_switch_for_slot_14"])
            self.assertEqual(
                camino_b["slot_14_reviewer_process"], "independent_codex_cli"
            )


class FakeClaudeWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        request_bytes = b'{"schema_version":"camino_slot14_audit_request.v1"}\n'
        diff_bytes = b"bounded diff fixture\n"
        handoff = self.workspace / ".camino_runtime" / "slot14_handoff"
        handoff.mkdir(parents=True)
        (handoff / "SLOT_14_AUDIT_REQUEST.json").write_bytes(request_bytes)
        (handoff / "CANDIDATE_DIFF.diff").write_bytes(diff_bytes)
        self.args_log = self.base / "args.json"
        self.cli = self.base / "fake_claude"
        self.cli.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

if sys.argv[1:3] == ["auth", "status"]:
    logged_in = os.environ.get("FAKE_CLAUDE_AUTH", "1") == "1"
    print(json.dumps({"loggedIn": logged_in, "authMethod": "claude.ai" if logged_in else "none", "apiProvider": "firstParty"}))
    raise SystemExit(0 if logged_in else 1)

Path(os.environ["FAKE_CLAUDE_ARGS_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
payload = json.loads(os.environ["FAKE_CLAUDE_OUTPUT"])
print(json.dumps({"result": json.dumps(payload), "model": "fake-opus-subscription"}))
""",
            encoding="utf-8",
        )
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.route = load_claude_route(ROOT)
        self.job = {
            "job_id": "JOB_TEST",
            "run_id": "RUN_TEST",
            "source_slot_id": "13",
            "slot_id": "14",
            "candidate_sha256": "a" * 64,
            "prior_slots_complete": True,
            "request_path": "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json",
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "diff_path": "STATE/slot14_handoff/CANDIDATE_DIFF.diff",
            "diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
            "instructions": "Revisá el archivo de prueba.",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _env(self, output: dict, *, authenticated: bool = True) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        env.update({
            "FAKE_CLAUDE_AUTH": "1" if authenticated else "0",
            "FAKE_CLAUDE_ARGS_LOG": str(self.args_log),
            "FAKE_CLAUDE_OUTPUT": json.dumps(output),
        })
        return env

    def _clean_output(self) -> dict:
        return {
            "verdict": APPROVAL_VERDICT,
            "summary": "Sin correcciones ni hallazgos dentro del alcance probado.",
            "findings": [],
            "corrections_applied": False,
            "tests": ["fake-test: passed"],
            "audit_request_sha256": self.job["request_sha256"],
            "falsification_attempts": ["Intenté refutar el fix con un caso negativo."],
            "independent_checks": ["Verifiqué una invariante crítica por otra ruta."],
        }

    def test_cli_receives_explicit_prompt_model_and_schema(self) -> None:
        result = run_claude_code(
            self.workspace,
            1,
            job=self.job,
            route=self.route,
            cli_command=str(self.cli),
            source_env=self._env(self._clean_output()),
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["approval_eligible"])
        self.assertEqual(result["verdict"], APPROVAL_VERDICT)
        self.assertEqual(result["model_id_actual"], "fake-opus-subscription")

        args = json.loads(self.args_log.read_text(encoding="utf-8"))
        self.assertIn("--json-schema", args)
        self.assertIn("--model", args)
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertIn("slot_id=14", args[-1])
        self.assertIn("candidate_sha256=" + "a" * 64, args[-1])

    def test_false_approval_with_corrections_is_rejected(self) -> None:
        output = self._clean_output()
        output["corrections_applied"] = True
        output["findings"] = [{"id": "F1", "severity": "HIGH", "summary": "Corregido"}]
        result = run_claude_code(
            self.workspace,
            1,
            job=self.job,
            route=self.route,
            cli_command=str(self.cli),
            source_env=self._env(output),
        )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["approval_eligible"])
        self.assertEqual(result["error_class"], "invalid_structured_output")

    def test_clean_claim_is_rejected_if_cli_changed_workspace(self) -> None:
        original = self.cli.read_text(encoding="utf-8")
        self.cli.write_text(
            original.replace(
                'payload = json.loads(os.environ["FAKE_CLAUDE_OUTPUT"])',
                'Path("changed.py").write_text("changed\\n", encoding="utf-8")\n'
                'payload = json.loads(os.environ["FAKE_CLAUDE_OUTPUT"])',
            ),
            encoding="utf-8",
        )
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        result = run_claude_code(
            self.workspace,
            1,
            job=self.job,
            route=self.route,
            cli_command=str(self.cli),
            source_env=self._env(self._clean_output()),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "workspace_changed_during_approval")
        self.assertTrue(result["changed_artifacts"])

    def test_bundle_persists_slot_verdict_findings_and_corrections(self) -> None:
        result = run_claude_code(
            self.workspace,
            1,
            job=self.job,
            route=self.route,
            cli_command=str(self.cli),
            source_env=self._env(self._clean_output()),
        )
        run_dir = self.base / "RUN_TEST"
        run_dir.mkdir()
        bundle = write_bundle(run_dir, self.job, result, self.workspace)
        saved = json.loads((bundle / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["slot_id"], "14")
        self.assertEqual(saved["verdict"], APPROVAL_VERDICT)
        self.assertEqual(saved["findings"], [])
        self.assertFalse(saved["corrections_applied"])
        self.assertTrue((bundle / "claude_code_stdout.txt").is_file())
        self.assertTrue((bundle / "CLAUDE_CODE_OUTPUT.DONE").is_file())
        validation = validate_bundle(bundle, "claude_code", "a" * 64)
        self.assertTrue(validation["valid"], validation["violations"])

    def test_missing_auth_fails_without_invoking_review(self) -> None:
        auth = check_claude_auth(
            str(self.cli),
            source_env=self._env(self._clean_output(), authenticated=False),
        )
        self.assertFalse(auth["ok"])
        self.assertEqual(auth["status"], "auth_missing")
        result = run_claude_code(
            self.workspace,
            1,
            job=self.job,
            route=self.route,
            cli_command=str(self.cli),
            source_env=self._env(self._clean_output(), authenticated=False),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "auth_missing")
        self.assertFalse(self.args_log.exists())

    def test_job_without_prior_slots_cannot_approve(self) -> None:
        job = dict(self.job)
        job["prior_slots_complete"] = False
        result = run_claude_code(
            self.workspace,
            1,
            job=job,
            route=self.route,
            cli_command=str(self.cli),
            source_env=self._env(self._clean_output()),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_class"], "invalid_job")
        self.assertFalse(self.args_log.exists())


if __name__ == "__main__":
    unittest.main()
