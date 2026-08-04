"""Tests for the FASE 1 fault-injection harness (OT sec 11 / G2, G5, G7)."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.inject_faults import INJECTORS, run_harness  # noqa: E402


def test_harness_covers_every_family_and_unmapped(tmp_path: Path) -> None:
    """The harness fires faults across fs/net/fmt/sem AND an UNMAPPED one."""
    names = {n for n, _ in INJECTORS}
    assert "fs.mount_absent" in names
    assert any(n.startswith("net.") for n in names)
    assert any(n.startswith("fmt.") for n in names)
    assert any(n.startswith("sem.") for n in names)
    assert "UNMAPPED_CONDITION" in names


def test_every_injected_fault_emits_a_registro(tmp_path: Path) -> None:
    """G2: no exception swallowed. One registro per injector minimum."""
    report = run_harness(tmp_path / "run")
    assert report["registros"] >= len(INJECTORS)


def test_only_mount_absent_halts(tmp_path: Path) -> None:
    """G5: exactly one halting class, and it is fs.mount_absent."""
    report = run_harness(tmp_path / "run")
    assert report["halts"] == 1
    assert report["halt_classes"] == ["fs.mount_absent"]
    assert report["invariants"]["only_mount_absent_halts"] is True


def test_unmapped_rate_measured_escape_hatch_works(tmp_path: Path) -> None:
    """G7 (FASE 1B corrected): the UNMAPPED rate in an injection run measures
    the escape-hatch MACHINERY, not taxonomy coverage. We assert the escape
    hatch fires (>=1 UNMAPPED) and that coverage is explicitly deferred to a
    live run — NOT that the rate is 'low enough', which would be meaningless
    for planted cases."""
    report = run_harness(tmp_path / "run")
    assert "unmapped_rate" in report
    assert report["classes_observed"].get("UNMAPPED_CONDITION", 0) >= 1
    # Coverage decision deferred to FASE 2 live run.
    assert report["taxonomy_revision_needed_live_only"] == "N/A hasta corrida viva"


def test_no_classification_mismatches(tmp_path: Path) -> None:
    """Each injected fault classifies to the clase the injector expected."""
    report = run_harness(tmp_path / "run")
    assert report["classification_mismatches"] == [], \
        f"mismatches: {report['classification_mismatches']}"


def test_log_is_jsonl_and_canonical(tmp_path: Path) -> None:
    """The log file is one JSON object per line."""
    import json
    report = run_harness(tmp_path / "run")
    log_path = Path(report["log_file"])
    text = log_path.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == report["registros"]
    for l in lines:
        d = json.loads(l)
        assert "exception_id" in d and "clase" in d


# --- FASE 1B: the four previously-unexercised classes + excerpt stress. --- #

def test_all_enum_classes_exercised(tmp_path: Path) -> None:
    """G1 (FASE 1B): every class in the enum is exercised. Cero sin probar."""
    report = run_harness(tmp_path / "run")
    assert report["all_classes_exercised"] is True
    assert report["unexercised_classes"] == []
    assert report["classes_exercised_count"] == report["enum_classes_count"] - 1


def test_four_new_classes_present_and_classified(tmp_path: Path) -> None:
    """The four classes the prior run missed now appear, classified correctly
    (not UNMAPPED)."""
    report = run_harness(tmp_path / "run")
    dist = report["classes_observed"]
    for clase in ("fmt.encoding", "fmt.schema_violation",
                  "sem.contradiction", "sem.unresolvable"):
        assert dist.get(clase, 0) >= 1, f"{clase} not exercised"
    assert report["classification_mismatches"] == []


def test_sem_family_escalates_t2_does_not_halt(tmp_path: Path) -> None:
    """The sem.* classes are the most expensive path (T2). Their default action
    must ESCALATE, not halt — a halt here would be a costly bug."""
    report = run_harness(tmp_path / "run")
    assert report["halts"] == 1  # only mount_absent
    from scripts.default_actions import action_for, ESCALATE_T2
    for clase in ("sem.contradiction", "sem.unresolvable", "sem.orphan_claim"):
        assert action_for(clase).action == ESCALATE_T2


def test_excerpt_stress_caps_at_512_bytes(tmp_path: Path) -> None:
    """G5 (FASE 1B): a multi-KB payload forces truncation. The stored excerpt
    must be <= 512 BYTES (not chars), marked truncated, multibyte intact."""
    report = run_harness(tmp_path / "run")
    es = report["excerpt_stress"]
    assert es["cap_held"] is True
    assert es["max_excerpt_bytes"] <= es["cap_bytes"]
    assert es["largest_marked_truncated"] is True


def test_excerpt_stress_multibyte_not_split(tmp_path: Path) -> None:
    """A payload with accents + CJK must not have a codepoint sliced in half."""
    report = run_harness(tmp_path / "run")
    assert report["excerpt_stress"]["multibyte_intact"] is True


def test_excerpt_stress_found_and_expected_do_not_grow(tmp_path: Path) -> None:
    """The big payload must not leak into `found` or `expected`. found carries
    path/size/hash only; expected is a fixed hint."""
    report = run_harness(tmp_path / "run")
    es = report["excerpt_stress"]
    assert es["found_did_not_grow"] is True
    assert es["expected_did_not_grow"] is True
    # Hard ceilings: neither field should approach the 512B cap.
    assert es["found_max_bytes"] < 200
    assert es["expected_max_bytes"] < 200


def test_g7_unmapped_rate_is_machine_not_coverage(tmp_path: Path) -> None:
    """G7 (FASE 1B correction): in an injection run the UNMAPPED rate measures
    the escape-hatch MACHINERY, not taxonomy COVERAGE. The report says so."""
    report = run_harness(tmp_path / "run")
    assert "maquinaria" in report["unmapped_rate_measures"]
    assert "cobertura" in report["unmapped_rate_measures"]
    # The planted UNMAPPED is present (escape hatch works) but the report
    # explicitly defers coverage to a live run.
    assert report["classes_observed"].get("UNMAPPED_CONDITION", 0) >= 1
    assert report["taxonomy_revision_needed_live_only"] == "N/A hasta corrida viva"


def test_fuse_safe_write_still_only_write_path(tmp_path: Path) -> None:
    """G7 (FASE 1B): no new atomic write was added. The log still imports
    fuse_safe_write from drive_fuse."""
    report = run_harness(tmp_path / "run")
    assert report["invariants"]["fuse_safe_write_still_only_path"] is True


def test_at_least_21_registros(tmp_path: Path) -> None:
    """OT sec 7: >= 21 registros (20 classes + the excerpt-stress case)."""
    report = run_harness(tmp_path / "run")
    assert report["registros"] >= 21

