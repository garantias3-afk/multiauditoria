"""Tests for default_actions — OT sec 6 / G4, G5."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.default_actions import (  # noqa: E402
    ADVANCE_WITH_DEBT, ENTER_FALLBACK, ESCALATE_T2, HALT_RUN,
    action_for, every_class_has_action, only_mount_absent_halts,
)
from scripts.exception_taxonomy import CLASSES, UNMAPPED  # noqa: E402


def test_every_class_has_a_default_action() -> None:
    """G4: each class in the enum has a predeclared default."""
    assert every_class_has_action()
    for c in CLASSES:
        assert action_for(c).clase == c


def test_fs_family_advances_with_debt() -> None:
    for c in ("fs.disk_full", "fs.path_missing", "fs.permission_denied",
              "fs.partial_write", "fs.truncated"):
        a = action_for(c)
        assert a.action == ADVANCE_WITH_DEBT, c
        assert a.advance is True, c
        assert a.t2_required is False, c


def test_fs_mount_absent_is_the_only_halt() -> None:
    """G5: ONLY fs.mount_absent halts the run."""
    a = action_for("fs.mount_absent")
    assert a.action == HALT_RUN
    assert a.advance is False
    assert only_mount_absent_halts()


def test_net_family_enters_fallback() -> None:
    for c in ("net.rate_limited", "net.server_error", "net.timeout",
              "net.auth_failed", "net.model_not_found"):
        assert action_for(c).action == ENTER_FALLBACK, c


def test_fmt_family_advances_with_debt() -> None:
    for c in ("fmt.encoding", "fmt.json_malformed", "fmt.schema_violation",
              "fmt.field_missing", "fmt.truncated_response"):
        a = action_for(c)
        assert a.action == ADVANCE_WITH_DEBT, c
        assert a.t2_required is False, c


def test_sem_and_unmapped_escalate_t2() -> None:
    for c in ("sem.contradiction", "sem.orphan_claim", "sem.unresolvable",
              UNMAPPED):
        a = action_for(c)
        assert a.action == ESCALATE_T2, c
        assert a.t2_required is True, c


def test_unknown_class_does_not_crash_falls_to_unmapped() -> None:
    """The instrumentation path must never crash on an out-of-enum class."""
    a = action_for("nonexistent.bogus")
    assert a.action == ESCALATE_T2
    assert a.clase == UNMAPPED


def test_exactly_one_halt_class() -> None:
    """G5 invariant: count of halting classes is 1, and it is mount_absent."""
    halting = [c for c in CLASSES if not action_for(c).advance]
    assert halting == ["fs.mount_absent"]
