"""Tests for fallback_ladder — OT section 4 D3 / G5.

One test per condition:
  - NO_DISPONIBLE          -> fallback ENTERS
  - CORRIO_Y_FALLO         -> fallback STOPS
  - ESCRIBIO_PERO_NO_PASA_GATE -> NOT failover (loop material)
"""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.fallback_ladder import (  # noqa: E402
    Outcome, classify_outcome, commit_artifact, mark_partial, mark_abort,
    clear_partial, AlwaysPassGate, AlwaysFailGate,
)


def test_no_disponible_fallback_enters(tmp_path: Path) -> None:
    """G5 condition 1: no final, no partial, no abort -> NO_DISPONIBLE.

    This is the 429/5xx/connection-timeout case: the provider never produced
    anything. The fallback MUST enter.
    """
    final = tmp_path / "slot1" / "out.json"
    co = classify_outcome(final)
    assert co.outcome == Outcome.NO_DISPONIBLE
    assert co.fallback_enters is True
    assert co.is_loop_material is False
    assert co.final_path is None


def test_corrio_y_fallo_fallback_stops(tmp_path: Path) -> None:
    """G5 condition 2: orphan .partial (or abort marker) -> CORRIO_Y_FALLO.

    The invocation attempted and failed. Re-running a broken writer is not the
    answer; the fallback MUST stop.
    """
    final = tmp_path / "slot1" / "out.json"
    final.parent.mkdir(parents=True)
    # Simulate a crash mid-write: a .partial is left behind, no final.
    mark_partial(final, "incompleto")
    co = classify_outcome(final)
    assert co.outcome == Outcome.CORRIO_Y_FALLO
    assert co.fallback_enters is False
    assert co.is_loop_material is False
    clear_partial(final)

    # Same result via an explicit abort marker (exception caught upstream).
    mark_abort(final, "produjo JSON invalido")
    co2 = classify_outcome(final)
    assert co2.outcome == Outcome.CORRIO_Y_FALLO
    assert co2.fallback_enters is False


def test_corrio_y_fallo_via_abort_signal(tmp_path: Path) -> None:
    """The caller can pass abort_signal=True when it catches a 'produced
    broken' exception. Maps to CORRIO_Y_FALLO regardless of filesystem state."""
    final = tmp_path / "slot1" / "out.json"
    co = classify_outcome(final, abort_signal=True)
    assert co.outcome == Outcome.CORRIO_Y_FALLO
    assert co.fallback_enters is False


def test_escribio_pero_no_pasa_gate_is_loop_material(tmp_path: Path) -> None:
    """G5 condition 3: final present + gate red -> ESCRIBIO_PERO_NO_PASA_GATE.

    NOT failover material. The artifact exists; the problem is quality, so it
    routes to the loop, never to the fallback.
    """
    final = tmp_path / "slot1" / "out.json"
    commit_artifact(final, '{"audit": "ok-ish"}')
    co = classify_outcome(final, gate=AlwaysFailGate())
    assert co.outcome == Outcome.ESCRIBIO_PERO_NO_PASA_GATE
    assert co.fallback_enters is False
    assert co.is_loop_material is True


def test_gate_pass_is_success_no_failover_no_loop(tmp_path: Path) -> None:
    """Final present + gate green -> success. No failover, no loop material."""
    final = tmp_path / "slot1" / "out.json"
    commit_artifact(final, '{"audit": "ok"}')
    co = classify_outcome(final, gate=AlwaysPassGate())
    assert co.fallback_enters is False
    assert co.is_loop_material is False


def test_no_gate_with_final_is_conservatively_loop_material(tmp_path: Path) -> None:
    """A final with no gate defined is treated as loop material, not success.

    This forces the caller to wire a gate for write/approve puestos rather
    than silently treating 'file exists' as 'passed'.
    """
    final = tmp_path / "slot1" / "out.json"
    commit_artifact(final, "x")
    co = classify_outcome(final, gate=None)
    assert co.is_loop_material is True
    assert co.fallback_enters is False
