import json
from pathlib import Path

from scripts.canon_loader import load_canon, resolve_profile
from scripts.overnight_master import _slot_internal_loop_satisfied
from scripts.run_multiaudit_cycle import _run_internal_agentic_loop, build_parser
from scripts.run_multiaudit_cycle_legacy import load_state
from scripts.slot_runtime import build_slot_plan
from scripts.worker_lmstudio import _decode_json_object, _valid_external_loop


ROOT = Path(__file__).resolve().parents[1]


def test_slot_specific_internal_loop_limits_are_canonical() -> None:
    bundle = load_canon(ROOT)
    plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
    expected = {"1": 6, "4": 6, "7": 10, "8": 10}

    for slot_id, limit in expected.items():
        contract = plan.slot(slot_id).internal_loop
        assert contract["required"] is True
        assert contract["max_iterations"] == limit
        assert contract["version_suffixes"].endswith(f".{limit:03d}")
        assert contract["stop_conditions"][-1].endswith(f".{limit:03d}")


def test_all_enabled_required_internal_loops_are_executed(tmp_path: Path) -> None:
    run = tmp_path / "RUN_internal_loops"
    snapshot = run / "INPUT" / "target_snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    sha = "a" * 64
    state = {
        "run_id": run.name,
        "run_dir": str(run),
        "current_phase": "created",
        "target_sha256": sha,
        "current_candidate_sha256": sha,
        "history": [],
    }
    (run / "cycle_state.json").write_text(json.dumps(state), encoding="utf-8")

    bundle = load_canon(ROOT)
    plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
    summary = _run_internal_agentic_loop(run, plan, bundle.runtime_policy)
    saved = load_state(run)

    assert summary["selected_slots"] == ["1", "4", "7", "8"]
    assert summary["slot_count"] == 4
    assert set(saved["internal_loops"]) == {"1", "4", "7", "8"}
    assert all(value["ran"] is True for value in saved["internal_loops"].values())


def test_canonical_entrypoint_has_bounded_default_timeout() -> None:
    args = build_parser().parse_args([])
    assert args.watch_timeout_minutes == 480


def test_no_bloquea_repairs_and_slots_share_cumulative_candidate(tmp_path: Path) -> None:
    run = tmp_path / "RUN_cumulative_internal_loops"
    snapshot = run / "INPUT" / "target_snapshot"
    snapshot.mkdir(parents=True)
    broken = "def add(a, b):\n    return a - b  # add\n"
    (snapshot / "calc.py").write_text(broken, encoding="utf-8")
    (snapshot / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    sha = "b" * 64
    state = {
        "run_id": run.name,
        "run_dir": str(run),
        "current_phase": "created",
        "target_sha256": sha,
        "current_candidate_sha256": sha,
        "history": [],
    }
    (run / "cycle_state.json").write_text(json.dumps(state), encoding="utf-8")

    bundle = load_canon(ROOT)
    plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
    summary = _run_internal_agentic_loop(run, plan, bundle.runtime_policy)

    assert summary["slots"]["1"]["status"] == "clean"
    assert summary["slots"]["1"]["versions"]
    for slot_id in ("4", "7", "8"):
        assert summary["slots"][slot_id]["status"] == "clean_no_corrections"
        assert summary["slots"][slot_id]["iteration_count"] == 0
        assert "return a + b" in (
            run / "INTERNAL_LOOP" / f"slot_{slot_id}" / "workdir" / "calc.py"
        ).read_text(encoding="utf-8")

    cumulative = run / "INTERNAL_LOOP" / "cumulative_candidate" / "calc.py"
    assert "return a + b" in cumulative.read_text(encoding="utf-8")
    assert (snapshot / "calc.py").read_text(encoding="utf-8") == broken


def test_reference_internal_loop_never_satisfies_external_slot_evidence(tmp_path: Path) -> None:
    run = tmp_path / "RUN_external_loop_evidence"
    run.mkdir()
    bundle = load_canon(ROOT)
    plan = build_slot_plan(bundle, resolve_profile(bundle, "with_claude"))
    (run / "CANON_SLOT_PLAN.json").write_text(
        json.dumps(plan.to_serializable()), encoding="utf-8",
    )
    local_loop = {
        "schema_version": "camino_internal_loop_result.v1",
        "slot_id": "1",
        "worker_id": "agentic_local",
        "evidence_scope": "mechanical_reference_only",
        "max_internal_loops": 6,
        "status": "clean_no_corrections",
        "advanced": True,
        "iteration_count": 0,
        "versions": [],
        "residual_debt": [],
        "iterations": [],
    }
    state = {"internal_loops": {"1": local_loop}}

    assert not _slot_internal_loop_satisfied(run, state, "1")
    assert not _slot_internal_loop_satisfied(
        run, state, "1", {"worker_id": "gateway", "internal_loop": local_loop},
    )

    external_loop = dict(local_loop)
    external_loop.update({
        "worker_id": "gateway_provider_agent",
        "evidence_scope": "external_agentic_loop",
    })
    assert _slot_internal_loop_satisfied(
        run,
        state,
        "1",
        {"worker_id": "gateway", "internal_loop": external_loop},
    )


def test_lmstudio_structured_loop_must_be_external_and_bound() -> None:
    contract = {"required": True, "max_iterations": 10}
    loop = {
        "schema_version": "camino_internal_loop_result.v1",
        "slot_id": "7",
        "worker_id": "lmstudio-route-test",
        "evidence_scope": "external_agentic_loop",
        "status": "clean_no_corrections",
        "iteration_count": 0,
        "max_internal_loops": 10,
        "iterations": [],
        "residual_debt": [],
    }
    encoded = "```json\n" + json.dumps({"internal_loop": loop}) + "\n```"
    assert _decode_json_object(encoded)["internal_loop"] == loop
    assert _valid_external_loop(loop, "7", contract)
    assert not _valid_external_loop(
        {**loop, "evidence_scope": "mechanical_reference_only"}, "7", contract,
    )
