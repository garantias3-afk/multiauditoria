"""Tests for contradiccion.py — OT section 8 (tab vs canon)."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.contradiccion import (  # noqa: E402
    CLASE_ASIGNACION, CLASE_REGLA, BLOCK_STATE,
    ConflictVerdict, add_to_verdict, classify_field, classify_value_type,
    make_conflict, route_present_in_tabla_absent_in_canon,
)


# ----- mechanical classification of field names ----- #

def test_route_list_fields_are_asignacion() -> None:
    assert classify_field("routes") == CLASE_ASIGNACION
    assert classify_field("model_id") == CLASE_ASIGNACION
    assert classify_field("provider_id") == CLASE_ASIGNACION
    assert classify_field("role") == CLASE_ASIGNACION
    assert classify_field("fallback_order") == CLASE_ASIGNACION


def test_permission_and_limit_fields_are_regla() -> None:
    assert classify_field("paid_fallbacks_authorized") == CLASE_REGLA
    assert classify_field("never_parallelize_with_heavy_exclusive") == CLASE_REGLA
    assert classify_field("max_iterations") == CLASE_REGLA
    assert classify_field("concurrency_limit") == CLASE_REGLA
    assert classify_field("circuit_breaker_triggers") == CLASE_REGLA
    assert classify_field("skip_remaining_provider_routes") == CLASE_REGLA


def test_unknown_field_defaults_to_regla_block() -> None:
    """OT: 'Si un campo no encaja... tratarlo como REGLA y parar.'"""
    assert classify_field("some_new_concept_xyz") == CLASE_REGLA


def test_hint_forces_asignacion_when_explicit() -> None:
    assert classify_field("ambiguous", hint="asignacion") == CLASE_ASIGNACION
    assert classify_field("ambiguous", hint="route_list") == CLASE_ASIGNACION


# ----- value-type classification ----- #

def test_boolean_and_numeric_disagreements_are_regla() -> None:
    assert classify_value_type(True, False) == CLASE_REGLA
    assert classify_value_type(3, 5) == CLASE_REGLA
    assert classify_value_type(1.5, 2.0) == CLASE_REGLA


def test_string_disagreement_is_asignacion() -> None:
    assert classify_value_type("model_a", "model_b") == CLASE_ASIGNACION
    assert classify_value_type(["r1", "r2"], ["r1"]) == CLASE_ASIGNACION


# ----- the known trigger: zai_glm rename, tabla right, canon stale ----- #

def test_known_zai_glm_rename_is_asignacion_proceeds() -> None:
    """The real first-run trigger: canon still has zai_glm_5_1@slot7 /
    zai_glm_5_2@slot13 because v2 renames never reached canon/. Tabla is right.

    This MUST be ASIGNACION (proceed), or the runner blocks on the first run
    for a known, decided discrepancy.
    """
    c = make_conflict(
        "model_id",
        tabla_value="zai_glm_5_2_plan",
        canon_value="zai_glm_5_1_plan",
        where="slot=7 puesto=auditores",
    )
    assert c.clase == CLASE_ASIGNACION
    assert c.as_artifact()["resolucion"] == "tabla_gana_sigue"


def test_new_route_in_tabla_absent_in_canon_is_asignacion() -> None:
    c = route_present_in_tabla_absent_in_canon(
        "xiaomi_mimo_v2_5_pro_plan", where="slot=1"
    )
    assert c.clase == CLASE_ASIGNACION
    assert "ausente en canon" in c.canon_value


# ----- the load-bearing rule case: a permission boolean ----- #

def test_permission_override_blocks() -> None:
    """If the tabla tries to enable paid_fallbacks_authorized while the canon
    forbids it, the runner MUST block and escalate. (OT: CLASE 2.)"""
    c = make_conflict(
        "paid_fallbacks_authorized",
        tabla_value=True,
        canon_value=False,
        where="runtime policy",
    )
    assert c.clase == CLASE_REGLA


def test_iteration_limit_override_blocks() -> None:
    c = make_conflict(
        "max_iterations",
        tabla_value=20,
        canon_value=15,
        where="loop policy",
    )
    assert c.clase == CLASE_REGLA


# ----- verdict aggregation: regla blocks, asignacion proceeds ----- #

def test_verdict_blocks_on_regla_only() -> None:
    v = ConflictVerdict()
    v = add_to_verdict(v, make_conflict("model_id", "a", "b"))   # asignacion
    assert not v.blocks
    v = add_to_verdict(v, make_conflict("max_iter", 20, 15))      # regla
    assert v.blocks
    assert v.state == BLOCK_STATE


def test_verdict_proceeds_with_deuda_when_only_asignacion() -> None:
    v = ConflictVerdict()
    v = add_to_verdict(v, make_conflict("routes", ["x"], ["y"]))
    v = add_to_verdict(v, route_present_in_tabla_absent_in_canon("new_route"))
    assert not v.blocks
    assert v.state == "PROCEDE_CON_DEUDAS_DE_ASIGNACION"
    assert len(v.asignacion) == 2
    assert len(v.all_artifacts()) == 2
