"""Tests for T0 handlers + dispatch — OT sec 3 / G2-G5, T0-2..T0-6."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.admisibilidad import RepairOutcome  # noqa: E402
from scripts.t0_dispatch import run_t0  # noqa: E402
from scripts.t0_handlers import HANDLERS, has_handler, no_sem_handlers  # noqa: E402


# ----- G2: no sem.* handlers; sem.* escalates directly to T1 ----- #

def test_no_sem_handlers_registered() -> None:
    """G2: NINGUN handler T0 para sem.*."""
    assert no_sem_handlers() is True
    for c in ("sem.contradiction", "sem.orphan_claim", "sem.unresolvable"):
        assert not has_handler(c)


def test_sem_escalates_to_t1_directly() -> None:
    """A sem.* registro has no T0 handler -> straight to T1 (no guessing)."""
    v = run_t0({"clase": "sem.contradiction"})
    assert v.escalates_to_t1
    assert v.outcome == RepairOutcome.ESCALATE_T1


# ----- T0-2: handlers exist for fs.* and fmt.* and net.* ----- #

def test_fs_and_fmt_and_net_all_have_handlers() -> None:
    for c in ("fs.disk_full", "fs.path_missing", "fs.permission_denied",
              "fs.mount_absent", "fs.partial_write", "fs.truncated",
              "fmt.encoding", "fmt.json_malformed", "fmt.schema_violation",
              "fmt.field_missing", "fmt.truncated_response",
              "net.rate_limited", "net.server_error", "net.timeout",
              "net.auth_failed", "net.model_not_found"):
        assert has_handler(c), f"missing handler for {c}"


# ----- T0-3: handlers return control / escalate, never guess ----- #

def test_fs_path_missing_escalates_does_not_invent_path() -> None:
    """The 1-ago error was hallucinating a path. T0 must NOT invent one."""
    v = run_t0({"clase": "fs.path_missing", "expected": "artefacto final"})
    assert v.escalates_to_t1
    assert v.repaired_bytes is None  # no invented content


def test_fmt_schema_violation_escalates_does_not_fabricate_field() -> None:
    v = run_t0({"clase": "fmt.schema_violation"})
    assert v.escalates_to_t1
    assert v.repaired_bytes is None


def test_fs_disk_full_returns_control() -> None:
    v = run_t0({"clase": "fs.disk_full"})
    assert v.outcome == RepairOutcome.CANNOT_HANDLE
    assert v.repaired_bytes is None


def test_fs_mount_absent_returns_control() -> None:
    v = run_t0({"clase": "fs.mount_absent"})
    assert v.outcome == RepairOutcome.CANNOT_HANDLE


# ----- net.* : not repaired, translated to NO_DISPONIBLE (NO_ACTION here) ----- #

def test_net_classes_not_repaired_no_action() -> None:
    """net.* handlers do not retry (no network). They signal NO_ACTION; the
    default action (ENTRA_FALLBACK) applies downstream."""
    for c in ("net.rate_limited", "net.timeout", "net.server_error"):
        v = run_t0({"clase": c})
        assert v.outcome == RepairOutcome.NO_ACTION
        assert not v.escalates_to_t1  # default action handles it, not T1
        assert "NO_DISPONIBLE" in v.reason or "fallback" in v.reason


# ----- G5: admisibilidad rejects a content-changing repair from a handler ----- #

def test_fmt_json_malformed_fence_strip_is_rejected_by_hash() -> None:
    """A handler proposes fence-strip; the hash check rejects (byte change) ->
    escalates to T1. This is the guardrail working."""
    fenced = b'```json\n{"a": 1}\n```'
    v = run_t0({"clase": "fmt.json_malformed", "artifact_bytes": fenced})
    # Handler proposed a repair; hash rejected it.
    assert v.outcome == RepairOutcome.REPAIRED
    assert v.admissible is False
    assert v.escalates_to_t1
    assert "RECHAZADO" in v.reason


def test_fmt_json_malformed_bom_prefixed_is_repaired_by_strip() -> None:
    """C7 (decision a): Python's json.loads SILENTLY accepts a leading UTF-8
    BOM, so under the old handler a BOM-prefixed JSON returned NO_ACTION and the
    BOM-strip branch was DEAD CODE (never executed). That left code pretending
    to handle a case it never reached.

    Decision (a): strip the BOM BEFORE parsing and propose it as an explicit
    REPAIR. The normalization becomes visible in the audit trail (instead of
    being silently swallowed), the dead branch comes alive, and the handler
    aligns with canonicalize() (which already strips BOM). BOM-strip is
    admissible (lossless), so the hash check passes."""
    with_bom = b"\xef\xbb\xbf" + b'{"a": 1}'
    v = run_t0({"clase": "fmt.json_malformed", "artifact_bytes": with_bom})
    assert v.outcome == RepairOutcome.REPAIRED
    assert v.admissible is True
    # CICLO5 / A7-C3-04: dispatch propagates the CANONICAL copy that was
    # hashed (BOM stripped + trailing-NL normalized), not the handler's raw
    # object. This assertion is also the G5 red-test for that propagation:
    # reverting dispatch to result.repaired_bytes would yield b'{"a": 1}'.
    assert v.repaired_bytes == b'{"a": 1}\n'
    assert not v.escalates_to_t1


def test_fmt_json_already_valid_is_no_action() -> None:
    v = run_t0({"clase": "fmt.json_malformed", "artifact_bytes": b'{"a": 1}'})
    assert v.outcome == RepairOutcome.NO_ACTION


# ----- T0-4: no network, no models (structural — handlers are pure) ----- #

def test_handlers_are_pure_functions_no_io_imports() -> None:
    """G4: T0 handlers must not import network/http/model libraries."""
    import scripts.t0_handlers as mod
    import inspect
    src = inspect.getsource(mod)
    for forbidden in ("urllib", "requests", "http", "socket", "subprocess",
                      "openai", "anthropic"):
        assert forbidden not in src, f"T0 imports forbidden I/O: {forbidden}"


# ----- UNMAPPED goes straight to T1 (no handler) ----- #

def test_unmapped_escalates_to_t1() -> None:
    v = run_t0({"clase": "UNMAPPED_CONDITION"})
    assert v.escalates_to_t1
    assert v.outcome == RepairOutcome.ESCALATE_T1


# ----- CICLO5 / A8-C3-02: the 8 handlers that had no test, one each ----- #
# Each test carries a FAILURE FIXTURE for its class and pins the handler's
# contract: return control / escalate, NEVER fabricate bytes.

def test_fs_permission_denied_returns_control_no_side_effect() -> None:
    """fs.permission_denied: EACCES/EPERM is not repairable in-band (chmod
    would be a privileged side effect). CANNOT_HANDLE, no bytes proposed."""
    v = run_t0({"clase": "fs.permission_denied", "expected": "artefacto.json"})
    assert v.outcome == RepairOutcome.CANNOT_HANDLE
    assert v.repaired_bytes is None
    assert v.escalates_to_t1


def test_fs_partial_write_escalates_without_fabricating_bytes() -> None:
    """fs.partial_write: an orphaned partial write cannot be reconstructed —
    that would be fabrication. Escalate with NO proposed content."""
    v = run_t0({"clase": "fs.partial_write",
                "artifact_bytes": b'{"finding": "x", "sev'})
    assert v.outcome == RepairOutcome.ESCALATE_T1
    assert v.repaired_bytes is None
    assert v.escalates_to_t1


def test_fs_truncated_escalates_without_inventing_missing_tail() -> None:
    """fs.truncated: the missing bytes are unknowable. Escalate; never invent."""
    v = run_t0({"clase": "fs.truncated", "artifact_bytes": b'{"a":'})
    assert v.outcome == RepairOutcome.ESCALATE_T1
    assert v.repaired_bytes is None


def test_fmt_encoding_latin1_transcoding_is_rejected_by_hash() -> None:
    """fmt.encoding on real latin-1 bytes: the handler proposes a latin-1 ->
    utf-8 transcode. That CHANGES bytes, so the strict hash check rejects it
    and escalates to T1 — the hash is the arbiter, not the handler's claim
    of losslessness."""
    v = run_t0({"clase": "fmt.encoding", "artifact_bytes": b"caf\xe9"})
    assert v.outcome == RepairOutcome.REPAIRED
    assert v.admissible is False
    assert v.escalates_to_t1
    assert "RECHAZADO" in v.reason


def test_fmt_field_missing_escalates_without_fabricating_value() -> None:
    """fmt.field_missing: the missing field's value cannot be invented."""
    v = run_t0({"clase": "fmt.field_missing",
                "artifact_bytes": b'{"finding": "x"}'})
    assert v.outcome == RepairOutcome.ESCALATE_T1
    assert v.repaired_bytes is None


def test_fmt_truncated_response_escalates_without_fabricating_tail() -> None:
    """fmt.truncated_response: the gateway cut the tail off; T0 doesn't have
    it and won't invent it."""
    v = run_t0({"clase": "fmt.truncated_response",
                "artifact_bytes": b'{"findings": ['})
    assert v.outcome == RepairOutcome.ESCALATE_T1
    assert v.repaired_bytes is None


def test_net_auth_failed_translates_to_no_disponible() -> None:
    """net.auth_failed: NOT repaired in T0 (no network, T0-4). Translated to
    NO_DISPONIBLE -> the fallback ladder decides. No bytes, no crash, no T1
    escalation (the default action handles it)."""
    v = run_t0({"clase": "net.auth_failed"})
    assert v.outcome == RepairOutcome.NO_ACTION
    assert not v.escalates_to_t1
    assert v.repaired_bytes is None
    assert "NO_DISPONIBLE" in v.reason or "fallback" in v.reason


def test_net_model_not_found_translates_to_no_disponible() -> None:
    """net.model_not_found: same contract as the rest of net.* — classify,
    never retry, never fabricate."""
    v = run_t0({"clase": "net.model_not_found"})
    assert v.outcome == RepairOutcome.NO_ACTION
    assert not v.escalates_to_t1
    assert v.repaired_bytes is None
    assert "NO_DISPONIBLE" in v.reason or "fallback" in v.reason


# ----- CICLO5 / A7-C3-04: dispatch propagates the hashed canonical copy ----- #

def test_dispatch_propagates_the_hashed_canonical_copy() -> None:
    """TOCTOU closure by second path: when a repair is admissible, run_t0 must
    hand out the EXACT canonical copy that was hashed (plain immutable bytes),
    never the handler's live object. Whatever that object could show on a
    later conversion is irrelevant: what gets written is what was hashed."""
    v = run_t0({"clase": "fmt.json_malformed",
                "artifact_bytes": b"\xef\xbb\xbf" + b'{"a": 1}'})
    assert v.admissible is True
    assert type(v.repaired_bytes) is bytes
    assert v.repaired_bytes == b'{"a": 1}\n'

