"""Tests for loop_engine + defect_class — OT section 4 D4 (G6, G7)."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.defect_class import (  # noqa: E402
    DefectClass, classify_defect, mediano_destination,
)
from scripts.loop_engine import (  # noqa: E402
    InputHistory, LARGO_DESTINO_SLOT, LoopCounters, decide_largo, decide_mediano,
    input_fingerprint, interno_instruction, load_counters, save_counters, r1_guard,
)


# ----- defect classification: A vs B ----- #

def test_classify_explicit_a() -> None:
    v = classify_defect(auditor_clase="A", author="glm5.2",
                        auditor_summary="el escritor tergiverso un hallazgo")
    assert v.clase == DefectClass.A
    assert "clase A" in v.motivo


def test_classify_explicit_b() -> None:
    v = classify_defect(auditor_clase="B", author="glm5.2",
                        auditor_summary="defecto sustantivo persiste")
    assert v.clase == DefectClass.B


def test_classify_inferred_from_keywords() -> None:
    va = classify_defect(auditor_summary="hallazgo huerfano: fabricacion", author="x")
    assert va.clase == DefectClass.A
    vb = classify_defect(auditor_summary="el defecto persiste pese a estar reportado", author="x")
    assert vb.clase == DefectClass.B


def test_classify_defaults_to_b_when_unknown() -> None:
    """Conservative: unknown -> B (re-audit is safer than re-write)."""
    v = classify_defect(auditor_summary="xyz qwerty", author="x")
    assert v.clase == DefectClass.B


# ----- G7: MEDIANO destination comes from the class ----- #

def test_mediano_a_goes_to_writer() -> None:
    v = classify_defect(auditor_clase="A", author="glm5.2", auditor_summary="consolidacion")
    assert mediano_destination(v, writer_slot=12, cycle_first_slot=7) == 12


def test_mediano_b_goes_to_cycle_first_slot() -> None:
    v = classify_defect(auditor_clase="B", author="glm5.2", auditor_summary="sustantivo")
    assert mediano_destination(v, writer_slot=12, cycle_first_slot=7) == 7


def test_mediano_target_override_constrained() -> None:
    """An auditor override can only route to writer or cycle-first — never an
    arbitrary slot (that would bypass the no-overlap rule)."""
    v = classify_defect(auditor_clase="A", author="glm5.2", auditor_summary="x",
                        target_slot=3)
    # target 3 is neither writer(12) nor cycle-first(7) -> ignored, defaults to A->writer
    assert mediano_destination(v, writer_slot=12, cycle_first_slot=7) == 12


# ----- G6 + R3: persistent counters ----- #

def test_counters_persist_across_save_load(tmp_path: Path) -> None:
    c = LoopCounters()
    c.record_interno(3)
    c.record_mediano(5, "A")
    c.record_mediano(5, "B")
    c.record_largo()
    save_counters(tmp_path, c)
    c2 = load_counters(tmp_path)
    assert c2.interno == {3: 1}
    assert c2.mediano_a == {5: 1}
    assert c2.mediano_b == {5: 1}
    assert c2.largo == 1


def test_largo_restart_does_not_reset_mediano(tmp_path: Path) -> None:
    """R3: a LARGO re-entry does NOT reset MEDIANO topes."""
    c = LoopCounters()
    c.record_mediano(6, "A")
    c.record_mediano(6, "A")
    c.record_largo()  # big loop restart
    save_counters(tmp_path, c)
    c2 = load_counters(tmp_path)
    assert c2.mediano_count(6, "A") == 2  # preserved, NOT reset


# ----- R2: exhausting a tope does NOT auto-escalate ----- #

def test_mediano_exhaustion_requires_reclassification() -> None:
    c = LoopCounters()
    c.record_mediano(3, "A")
    c.record_mediano(3, "A")
    c.record_mediano(3, "A")  # tope 3 hit
    v = classify_defect(auditor_clase="A", author="glm5.2", auditor_summary="consolidacion")
    d = decide_mediano(v, step=3, writer_slot=12, cycle_first_slot=7,
                       counters=c, tope=3)
    assert d.exhausted is True
    assert d.action == "rec clasificar"
    # NOT auto-escalation to LARGO.
    assert "reclasificacion" in d.motivo


def test_mediano_under_tope_reingreses() -> None:
    c = LoopCounters()
    v = classify_defect(auditor_clase="B", author="glm5.2", auditor_summary="sustantivo")
    d = decide_mediano(v, step=7, writer_slot=12, cycle_first_slot=7,
                       counters=c, tope=2)
    assert d.exhausted is False
    assert d.action == "reingresar"
    assert d.destino_slot == 7  # B -> cycle first slot


# ----- LARGO: only aprobador, with tope ----- #

def test_largo_triggers_restart_big_loop() -> None:
    c = LoopCounters()
    d = decide_largo(aprobador_verdict="enfoque equivocado", counters=c)
    assert d.action == "restart_big_loop"
    assert d.destino_slot == LARGO_DESTINO_SLOT


def test_largo_exhaustion_declares_deuda() -> None:
    c = LoopCounters()
    for _ in range(3):
        c.record_largo()
    d = decide_largo(aprobador_verdict="otra vez", counters=c)
    assert d.exhausted is True
    assert d.action == "deuda"


# ----- R1: never re-run unchanged input ----- #

def test_r1_blocks_repeat_of_unchanged_input() -> None:
    h = InputHistory()
    fp = input_fingerprint("findings_v1")
    assert r1_guard(step=12, clase="A", fingerprint=fp, history=h) is None
    h.record(12, "A", fp)
    block = r1_guard(step=12, clase="A", fingerprint=fp, history=h)
    assert block is not None
    assert "R1" in block


def test_r1_allows_changed_input() -> None:
    h = InputHistory()
    h.record(12, "A", input_fingerprint("v1"))
    # Different fingerprint => allowed.
    assert r1_guard(step=12, clase="A", fingerprint=input_fingerprint("v2"), history=h) is None


# ----- INTERNO instruction shape ----- #

def test_interno_instruction_three_steps_no_manos() -> None:
    s = interno_instruction(manos=False)
    assert "propone" in s and "audita" in s and "corrige" in s
    assert "MANOS" not in s


def test_interno_instruction_with_manos_mentions_tests() -> None:
    s = interno_instruction(manos=True, test_cmd=["pytest", "-q"])
    assert "MANOS" in s
    assert "pytest" in s
