import json
from pathlib import Path

from scripts import package_release
from scripts.package_release import CURRENT_KNOWLEDGE_PREFIX, is_excluded


ROOT = Path(__file__).resolve().parents[1]


def test_release_excludes_obsolete_knowledge_and_manifests() -> None:
    assert is_excluded(Path("CAMINO_A_OVERNIGHT_KNOWLEDGE_BUNDLE_UNICO_v1_3_18.md"))
    assert is_excluded(Path("CAMINO_A_OVERNIGHT_KNOWLEDGE_BUNDLE_UNICO_v1_3_18.zip"))
    assert is_excluded(Path("CLEAN_RELEASE_MANIFEST_v1_3_18.json"))
    assert is_excluded(Path("MANIFEST_MINIMO_AUDITORIA.json"))
    assert is_excluded(Path("CONTEXTO_MINIMO_AUDITORIA.md"))
    assert is_excluded(Path("CHANGELOG_LMSTUDIO_V1_3_16.md"))
    assert is_excluded(Path("reports/D1_LIVE_ROUTE_PROBE_20260710T040612Z.json"))
    assert is_excluded(Path("reports/AUDIT_OPERATIVA_V1_3_19.md"))
    assert is_excluded(Path("reports/PRODUCTION_NEGATIVE_SMOKE_20260711.json"))
    assert is_excluded(Path("CHANGELOG_V1_3_20_SOL56.md"))
    assert is_excluded(Path("reports/AUDIT_OPERATIVA_V1_3_20_SOL56.md"))
    assert is_excluded(Path("outputs/operational_runs/RUN_x/STATE/state.sqlite"))


def test_release_keeps_only_current_versioned_knowledge() -> None:
    assert not is_excluded(Path(f"{CURRENT_KNOWLEDGE_PREFIX}.md"))
    assert not is_excluded(Path(f"{CURRENT_KNOWLEDGE_PREFIX}.zip"))
    assert not is_excluded(Path("CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.md"))


def test_camino_b_entrypoints_keep_executable_bits_in_release() -> None:
    assert "bin/start_camino_b_gateway.sh" in package_release.EXECUTABLE_RELEASE_PATHS
    assert "bin/run_camino_b_agent.sh" in package_release.EXECUTABLE_RELEASE_PATHS


def test_actions_deployment_guide_matches_current_knowledge_manifest() -> None:
    manifest = json.loads(
        (ROOT / "CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.manifest.json").read_text(encoding="utf-8")
    )
    guide = (ROOT / "actions" / "CAMINO_A_ACTIONS_DEPLOYMENT_GUIDE.md").read_text(
        encoding="utf-8"
    )
    assert manifest["bundle_version"] in guide
    assert manifest["sha256"] in guide


def test_camino_b_builder_instructions_preserve_current_authority_and_fallback() -> None:
    instructions = (
        ROOT / "actions" / "CAMINO_B_GPT_BUILDER_INSTRUCTIONS.md"
    ).read_text(encoding="utf-8")
    assert "único cerebro y orquestador lógico de Camino B" in instructions
    assert "Claude Code CLI por suscripción es primario" in instructions
    assert "Codex CLI 'gpt-5.6-sol' con razonamiento 'ultra'" in instructions
    assert "OpenAI API, Anthropic API y Claude API están prohibidas" in instructions
    assert "'approveReservedProvider'" in instructions
    assert "Los slots 1 y 4 usan `.001`–`.006`" in instructions
    assert "los slots 7 y 8 conservan" in instructions
    assert "`.001`–`.010`" in instructions


def test_camino_a_brain_instructions_preserve_slot_specific_loop_limits() -> None:
    instructions = (
        ROOT / "generated" / "GPT_BUILDER_INSTRUCTIONS.md"
    ).read_text(encoding="utf-8")
    assert "Los slots 1" in instructions
    assert "y 4 usan exactamente el rango `.001`–`.006`" in instructions
    assert "los slots 7 y 8 conservan" in instructions
    assert "`.001`–`.010`" in instructions


def test_packaging_fails_closed_when_compileall_fails(tmp_path, monkeypatch) -> None:
    (tmp_path / "tests").mkdir()
    compile_env = {}

    def fake_run(cmd, root, timeout, env=None):
        if "compileall" in cmd:
            compile_env.update(env or {})
            return {"command": "compileall", "exit_code": 1}
        return {"command": "check", "exit_code": 0}

    monkeypatch.setattr(package_release, "run", fake_run)
    validation, ok = package_release.build_validation(tmp_path)
    assert ok is False
    assert validation["aborted"].startswith("compileall failed")
    assert compile_env["PYTHONPYCACHEPREFIX"]
    assert "Library/Caches" not in compile_env["PYTHONPYCACHEPREFIX"]
