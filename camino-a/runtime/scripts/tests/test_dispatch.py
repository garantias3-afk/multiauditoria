"""Tests for dispatch.py — OT section 4 D2."""
from __future__ import annotations

import sys
import time
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.dispatch import (  # noqa: E402
    dispatch_puesto, dispatch_paralela, dispatch_carrera, evaluate_condicion,
)
from scripts.fallback_ladder import AlwaysPassGate  # noqa: E402
from scripts.tabla_loader import RouteAssignment  # noqa: E402


def _assignment(route_id: str, *, tipo: str, step: int = 1, puesto: str = "auditores",
                notas: str = "") -> RouteAssignment:
    return RouteAssignment(
        step=step, ciclo="A", puesto=puesto, capacidades="DETECT", tipo_ruta=tipo,
        orden=0, route_id=route_id, on_unavailable="SKIP_STEP", provider_name="P",
        cost_class="free", familia="f", verificacion="VERIFICADO_64K", latencia_s=1.0,
        timeout_s=10, manos="relee", fallback_real="", notas=notas,
    )


def _make_invoker(results: dict[str, tuple[bool, str]], *, delay: dict[str, float] | None = None):
    """Build an Invoker that commits artifacts per route_id."""
    delays = delay or {}

    def _invoker(assignment, out_path):
        if assignment.route_id in delays:
            time.sleep(delays[assignment.route_id])
        out_path = Path(out_path)
        if assignment.route_id in results:
            ok, content = results[assignment.route_id]
            if ok:
                from scripts.fallback_ladder import commit_artifact
                commit_artifact(out_path, content)
                return True, content, "ok"
            return False, "", "abort: produced broken"
        # Not in results => unavailable (no artifact produced).
        return False, "", "timeout 429"

    return _invoker


# ----- paralela: the ola; redundancy absorbs a loss ----- #

def test_paralela_ola_succeeds_if_any_route_wins(tmp_path: Path) -> None:
    routes = [
        _assignment("r_a", tipo="paralela"),
        _assignment("r_b", tipo="paralela"),
        _assignment("r_c", tipo="paralela"),
    ]
    invoker = _make_invoker({
        "r_a": (True, '{"a":1}'),
        # r_b unavailable (429, no artifact)
        "r_c": (True, '{"c":1}'),
    })
    res = dispatch_paralela(routes, invoker=invoker, workdir=tmp_path, gate=AlwaysPassGate())
    assert res.succeeded is True
    assert set(res.winner_routes) == {"r_a", "r_c"}
    assert res.needs_fallback is False  # redundancy absorbed the loss


def test_paralela_all_unavailable_needs_fallback(tmp_path: Path) -> None:
    routes = [_assignment("r_a", tipo="paralela"), _assignment("r_b", tipo="paralela")]
    invoker = _make_invoker({})  # both unavailable
    res = dispatch_paralela(routes, invoker=invoker, workdir=tmp_path)
    assert res.succeeded is False
    assert res.needs_fallback is True


# ----- carrera: first VALID wins, rest cancelled ----- #

def test_carrera_first_valid_wins(tmp_path: Path) -> None:
    routes = [
        _assignment("fast", tipo="carrera"),
        _assignment("slow", tipo="carrera"),
    ]
    invoker = _make_invoker(
        {"fast": (True, '{"f":1}'), "slow": (True, '{"s":1}')},
        delay={"fast": 0.0, "slow": 1.0},
    )
    res = dispatch_carrera(routes, invoker=invoker, workdir=tmp_path, gate=AlwaysPassGate())
    assert res.succeeded is True
    assert res.winner_routes == ["fast"]
    # The loser did not become a winner even though it would have succeeded.
    assert "slow" not in res.winner_routes


def test_carrera_redundancy_same_model_different_providers(tmp_path: Path) -> None:
    """P5: same model across providers is one independence group. If one is
    unavailable, the other wins."""
    routes = [
        _assignment("or_ultra", tipo="carrera"),
        _assignment("nvidia_ultra", tipo="carrera"),
    ]
    invoker = _make_invoker({"nvidia_ultra": (True, '{"n":1}')})  # OR unavailable
    res = dispatch_carrera(routes, invoker=invoker, workdir=tmp_path, gate=AlwaysPassGate())
    assert res.winner_routes == ["nvidia_ultra"]
    assert res.needs_fallback is False


# ----- condicional: gated by note ----- #

def test_condicional_runs_only_when_condition_met(tmp_path: Path) -> None:
    a = _assignment("cond_route", tipo="condicional",
                    notas="SUPER solo si fallan las TRES ultras")
    # Condition false -> skipped.
    assert evaluate_condicion(a, context={}) is False
    assert evaluate_condicion(a, context={"ultras_failed": True}) is True


def test_condicional_unrecognized_note_does_not_run(tmp_path: Path) -> None:
    """Conservative: a vague note never silently injects a (possibly paid) route."""
    a = _assignment("paid_route", tipo="condicional", notas="some vague text")
    assert evaluate_condicion(a, context={}) is False


def test_dispatch_puesto_skips_condicional_when_condition_false(tmp_path: Path) -> None:
    routes = [
        _assignment("primary", tipo="primaria"),
        _assignment("cond", tipo="condicional", notas="solo si fallan los grandes"),
    ]
    invoker = _make_invoker({"primary": (True, '{"p":1}')})
    res = dispatch_puesto(routes, invoker=invoker, workdir=tmp_path, gate=AlwaysPassGate())
    assert res.succeeded is True
    # cond was skipped, not run.
    cond_skipped = [r for r, _ in res.skipped if r.route_id == "cond"]
    assert cond_skipped


# ----- slowness alone never triggers fallback (P8) ----- #

def test_slow_but_present_does_not_need_fallback(tmp_path: Path) -> None:
    """P8: truncation disqualifies, latency does not. A slow-but-complete route
    is a success, not a fallback trigger."""
    routes = [_assignment("slow_ok", tipo="paralela")]
    invoker = _make_invoker({"slow_ok": (True, '{"ok":1}')}, delay={"slow_ok": 0.5})
    res = dispatch_paralela(routes, invoker=invoker, workdir=tmp_path, gate=AlwaysPassGate())
    assert res.succeeded is True
    assert res.needs_fallback is False
