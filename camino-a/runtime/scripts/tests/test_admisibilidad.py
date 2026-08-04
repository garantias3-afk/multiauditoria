"""Tests for admisibilidad — OT sec 4 / T0-5, T0-6, G5.

The load-bearing test is test_handler_that_changes_content_is_rejected: the
hash check rejects a content-changing repair BY CONSTRUCTION, not by the
handler's good behaviour. That is the whole point of the guardrail.
"""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.admisibilidad import (  # noqa: E402
    canonical_hash, canonicalize, check_repair,
)


# ----- canonicalize: only lossless normalizations ----- #

def test_canonicalize_strips_utf8_bom() -> None:
    """BOM strip is admisible (lossless). canonicalize removes it so it doesn't
    affect the hash."""
    with_bom = b"\xef\xbb\xbf" + b'{"a": 1}'
    without = b'{"a": 1}'
    assert canonicalize(with_bom) == canonicalize(without)
    assert canonical_hash(with_bom) == canonical_hash(without)


def test_canonicalize_normalizes_trailing_newlines() -> None:
    """A trailing newline (or several) doesn't change content for any parser.
    canonicalize collapses them so the hash is stable."""
    base = b'{"finding": "x"}'
    assert canonical_hash(base) == canonical_hash(base + b"\n")
    assert canonical_hash(base) == canonical_hash(base + b"\n\n\n")
    assert canonical_hash(base) == canonical_hash(base + b"\r\n")


def test_canonicalize_empty_normalizes_to_single_newline() -> None:
    # Empty + trailing-NL normalization => single "\n". Consistent and stable.
    assert canonicalize(b"") == b"\n"
    assert canonical_hash(b"") == canonical_hash(b"\n")


# ----- G5 / T0-6: the REJECTION test (load-bearing) ----- #

def test_handler_that_changes_content_is_rejected() -> None:
    """T0-6: a handler that tries to change content is rejected BY THE CHECK,
    not by good conduct. This is the guardrail that bounds handler power."""
    original = b'{"finding": "divide-by-zero", "severity": "high"}'
    # A misbehaving handler 'fixes' the finding text.
    tampered = b'{"finding": "false-alarm", "severity": "high"}'
    v = check_repair(original, tampered, handler_name="bad_handler")
    assert v.rejected
    assert "RECHAZADO" in v.reason
    assert v.hash_before != v.hash_after


def test_handler_that_drops_a_field_is_rejected() -> None:
    """Dropping a finding is NOT a repair; it's judgement. Rejected."""
    original = b'{"findings": ["a", "b"]}'
    dropped = b'{"findings": ["a"]}'
    assert check_repair(original, dropped).rejected


def test_admissible_repair_passes() -> None:
    """A repair that only does BOM/trailing-NL normalization passes."""
    original = b"\xef\xbb\xbf" + b'{"a": 1}\n\n'
    repaired = b'{"a": 1}'  # BOM stripped, trailing NL normalized
    v = check_repair(original, repaired, handler_name="good")
    assert v.admissible
    assert v.hash_before == v.hash_after


def test_byte_identical_repair_passes() -> None:
    """If the handler returns the bytes unchanged (no-op), it passes trivially."""
    original = b'{"x": 1}'
    v = check_repair(original, original)
    assert v.admissible


def test_fence_strip_is_rejected() -> None:
    """Stripping markdown fences (```json ... ```) changes bytes. Per OT sec 4
    fence-strip IS listed as admisible in prose, but it is a content change
    from the hash's view — so under our strict construction it REJECTS and
    escalates to T1. We choose strict: a false rejection is cheap (T1 retries);
    a false acceptance corrupts."""
    original = b'```json\n{"a": 1}\n```'
    stripped = b'{"a": 1}'
    v = check_repair(original, stripped)
    # This MUST reject under strict hash semantics. T1 can do fence-strip as
    # a sanctioned normalization; T0 cannot claim it losslessly.
    assert v.rejected


def test_rejection_reason_names_the_handler() -> None:
    """The rejection message names the handler so the audit trail is honest."""
    v = check_repair(b'{"a":1}', b'{"a":2}', handler_name="fmt_json_x")
    assert "fmt_json_x" in v.reason


# ----- C6: invalid types must not crash the run ----- #

def test_check_repair_with_str_arguments_returns_verdict_not_exception() -> None:
    """C6 / G5: a handler that hands str (not bytes) to check_repair used to
    crash with an uncaught TypeError (startswith() demands bytes/str match).
    A type error must ESCALATE (a normal RECHAZO verdict), not throw the run.
    The hash check stays strict; what changes is HOW an invalid type is
    reported."""
    # str where bytes are expected -> rejected by verdict, not by exception.
    v = check_repair('{"a": 1}', '{"a": 1}', handler_name="bad_types")
    assert v.rejected is True
    assert "RECHAZADO" in v.reason


def test_check_repair_mixed_str_bytes_returns_verdict_not_exception() -> None:
    """C6: a mixed-type comparison must not raise either."""
    v = check_repair(b'{"a": 1}', '{"a": 1}', handler_name="mixed")
    assert v.rejected is True


def test_check_repair_bytes_still_works() -> None:
    """C6 regression guard: legitimate bytes input is unaffected."""
    v = check_repair(b'{"a": 1}', b'{"a": 1}')
    assert v.admissible is True


# ----- CICLO5 / A7-C4-04: the whitelist closes the smuggler CLASS ----- #
#
# `c = bytes(content)` (CICLO4) was a BLACKLIST fix: materialize, then hash.
# Python 3.14 enumerates two more dunders that defeat it (both verified
# empirically on 3.14.6 before these tests were written):
#   - bytes() honours __bytes__ BEFORE the buffer protocol on bytes subclasses
#     (a lying __bytes__ was hashed and ADMITTED while the real buffer was
#     malicious);
#   - a PEP 688 __buffer__ can present a DIFFERENT view on each conversion
#     (the hash saw the benign view; a writer would get the malicious one).
# The CICLO5 fix is a WHITELIST: type(content) is bytes. It cannot be
# enumerated by dunders, so the whole attack class closes by construction.
# Each vector below is a FAILURE FIXTURE: with the guard reverted to
# bytes(content), the ones marked RED-on-revert go red (verified for G5).
# NOTE: the two CICLO4 smuggler tests were REWRITTEN here, not deleted —
# their old semantics (materialize the real buffer) is exactly what the
# whitelist supersedes (canonicalize now refuses to convert at all).

class _Smuggler(bytes):
    """bytes subclass that overrides the three methods the pre-CICLO4
    canonicalize used to call, lying about its content at every step."""

    def startswith(self, *args, **kwargs):
        return False

    def __getitem__(self, i):
        return b"data\n"[i]

    def rstrip(self, *args):
        return b"data"


class _Smuggler2(bytes):
    """bytes subclass with a lying __bytes__. On Python 3.14 bytes(x) honours
    __bytes__ BEFORE the buffer protocol: the old `c = bytes(content)` guard
    materialized the LIE (b"data"), hashed it and ADMITTED it, while the real
    buffer stayed malicious and was what got written."""

    def __bytes__(self):
        return b"data"


class _TwoFace:
    """NOT a bytes subclass: a plain object that is a buffer via PEP 688
    __buffer__, and lies DYNAMICALLY. First conversion shows the benign view
    (what a hash would see); later conversions show the malicious payload
    (what a writer would write). The old bytes(content) materialization
    consumed view #1 and ADMITTED the repair."""

    def __init__(self) -> None:
        self._views = [b"data", b"XXX-malicious"]
        self._calls = 0

    def __buffer__(self, flags):
        view = self._views[min(self._calls, len(self._views) - 1)]
        self._calls += 1
        return memoryview(view)


def test_vector_smuggler_overrides_is_rejected() -> None:
    """Vector 1 (A7-C3-01 regression): subclass overriding startswith/
    __getitem__/rstrip. The CICLO4 guard already rejected it (bytes() bypassed
    the overrides); the CICLO5 whitelist rejects it by type. Must STAY
    rejected under any future edit (regression guard)."""
    v = check_repair(b"data", _Smuggler(b"XXX-malicious"), handler_name="smuggler")
    assert v.admissible is False
    assert v.rejected


def test_canonicalize_rejects_anything_not_exactly_bytes() -> None:
    """The whitelist raises TypeError for ANY object whose type is not exactly
    bytes — subclasses included (isinstance would accept them; that is the
    attack). check_repair converts this into a RECHAZO verdict."""
    import pytest
    for bad in (_Smuggler(b"x"), _Smuggler2(b"x"), _TwoFace(),
                bytearray(b"x"), "x", None, 42, [100]):
        with pytest.raises(TypeError):
            canonicalize(bad)
    # Plain bytes still canonicalize normally (this is the whole whitelist).
    assert canonicalize(b"x") == b"x\n"


def test_vector_smuggler2_dunder_bytes_is_rejected() -> None:
    """Vector 2 (A7-C4-04 BLOQUEANTE): bytes() honours __bytes__ first on
    subclasses, so under `c = bytes(content)` this fixture was ADMITTED (the
    hash saw the lie b"data"; the real buffer is malicious). The whitelist
    rejects by type before any conversion. RED-on-revert."""
    v = check_repair(b"data", _Smuggler2(b"XXX-malicious"), handler_name="smuggler2")
    assert v.admissible is False
    assert "RECHAZADO" in v.reason


def test_vector_twoface_dunder_buffer_is_rejected() -> None:
    """Vector 3 (A7-C4-04 via PEP 688): a buffer-protocol object that is not
    bytes and lies BETWEEN conversions. Under bytes(content) the hash saw view
    #1 (benign) and ADMITTED; a writer would then get view #2 (malicious).
    The whitelist rejects: type is not bytes. RED-on-revert."""
    v = check_repair(b"data", _TwoFace(), handler_name="twoface")
    assert v.admissible is False
    assert "RECHAZADO" in v.reason


def test_vector_bytearray_is_rejected() -> None:
    """Vector 4: bytearray with IDENTICAL content. Under bytes(content) this
    was ADMITTED (and the mutable object stayed live downstream = TOCTOU
    A7-C3-04). The whitelist rejects: type is not bytes. RED-on-revert."""
    v = check_repair(b"data", bytearray(b"data"), handler_name="mutable")
    assert v.admissible is False


def test_vector_int_fabricates_zeros_is_rejected() -> None:
    """Vector 5 (fabricacion ALTA del ciclo 4): bytes(42) fabricates 42 zero
    bytes; against original b"\\x00"*42 + b"\\n" the old guard said ADMISSIBLE
    (check_repair admitted a number as if it were content). The whitelist
    rejects: an int is not bytes. RED-on-revert."""
    v = check_repair(b"\x00" * 42 + b"\n", 42, handler_name="fabricator")
    assert v.admissible is False


def test_vector_list_of_ints_fabricates_bytes_is_rejected() -> None:
    """Vector 6: bytes([100, 97, 116, 97]) fabricates b"data" from an
    iterable of ints; the old guard ADMITTED it against original b"data".
    The whitelist rejects: a list is not bytes. RED-on-revert."""
    v = check_repair(b"data", [100, 97, 116, 97], handler_name="iterable")
    assert v.admissible is False


def test_vector_str_is_rejected() -> None:
    """Vector 7: str where bytes are expected. RECHAZO by verdict, never a
    crash; nothing gets hashed (C6 reporting path, now reached through the
    whitelist's TypeError)."""
    v = check_repair(b"data", "data", handler_name="str_type")
    assert v.admissible is False
    assert v.hash_before == "" and v.hash_after == ""


def test_vector_none_is_rejected() -> None:
    """Vector 8: None. RECHAZO by verdict, not a crash, nothing hashed."""
    v = check_repair(b"data", None, handler_name="none_type")
    assert v.admissible is False
    assert v.hash_before == "" and v.hash_after == ""


# ----- G4: the whitelist must NOT tighten what was lossless ----- #

def test_lossless_bom_still_admissible_after_guard() -> None:
    """G4/G5: BOM strip stays admisible under the whitelist. If someone
    'fixes' the guard by dropping the lossless normalizations, this goes RED."""
    original = b"\xef\xbb\xbf" + b'{"finding": "x"}'
    repaired = b'{"finding": "x"}'
    v = check_repair(original, repaired, handler_name="bom")
    assert v.admissible is True
    assert v.hash_before == v.hash_after
    # The verdict carries the exact canonical copy that was hashed.
    assert v.canonical_bytes == b'{"finding": "x"}\n'
    assert type(v.canonical_bytes) is bytes


def test_lossless_trailing_newline_still_admissible_after_guard() -> None:
    """G4/G5: trailing-newline normalization stays admisible under the
    whitelist."""
    original = b'{"finding": "x"}'
    v = check_repair(original, original + b"\n\n", handler_name="tail")
    assert v.admissible is True
    assert v.hash_before == v.hash_after
    assert v.canonical_bytes == b'{"finding": "x"}\n'


# ----- CICLO5: except widened to ValueError (fail CLOSED, never crash) ----- #

def test_valueerror_out_of_canonicalize_is_rechazo_not_crash(monkeypatch) -> None:
    """Gate for the except widening: a ValueError raised inside the
    canonicalization path must become a RECHAZO verdict exactly like a
    TypeError. Reverting the except to TypeError-only lets the ValueError
    propagate -> this test goes RED (G5)."""
    import scripts.admisibilidad as adm

    def _raising(content):
        raise ValueError("conversion hostil simulada")

    monkeypatch.setattr(adm, "canonicalize", _raising)
    v = adm.check_repair(b'{"a": 1}', b'{"a": 1}', handler_name="valueerror")
    assert v.admissible is False
    assert "RECHAZADO" in v.reason
    assert "ValueError" in v.reason
