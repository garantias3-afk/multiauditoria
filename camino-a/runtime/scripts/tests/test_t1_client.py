"""Tests for t1_client — OT sec 5 / G6-G9, T1-1..T1-5."""
from __future__ import annotations

import sys
import time
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import pytest  # noqa: E402

from scripts.t1_client import (  # noqa: E402
    SYSTEM_PROMPT, T1_LATENCY_TIMEOUT_S, VOCABULARY, build_user_prompt,
    call_t1, _parse_response,
)


# ----- T1-1: closed vocabulary ----- #

def test_valid_vocabulary_line_is_accepted() -> None:
    # C2/C5: keyword instructions that REQUIRE an argument are not accepted in
    # their bare form. Only the no-argument keywords are accepted standalone.
    for line in ("ACCEPT_PARTIAL", "ESCALATE_T2", "ABORT_SLOT_KEEP_RUN"):
        p = _parse_response(line)
        assert not p.out_of_vocab, line
        assert p.instruction == line


def test_vocabulary_with_argument_is_parsed(tmp_path) -> None:
    # C3: RETRY_WITH_PATH now requires a permitted_root to confine the path.
    target = tmp_path / "x.json"
    target.write_text("{}")
    p = _parse_response(f"RETRY_WITH_PATH {target}",
                        permitted_root=str(tmp_path))
    assert p.instruction == "RETRY_WITH_PATH"
    assert p.argument == str(target)
    p2 = _parse_response("RENORMALIZE fence")
    assert p2.instruction == "RENORMALIZE"
    assert p2.argument == "fence"


def test_out_of_vocab_response_is_discarded_and_escalates() -> None:
    """T1-1: anything outside the vocabulary is discarded; we escalate to T2.
    We do NOT interpret a near-match (that would let the model invent)."""
    p = _parse_response("I think you should retry the request with a different URL")
    assert p.out_of_vocab
    assert p.escalate_t2
    assert p.instruction == "ESCALATE_T2"


def test_chatter_around_valid_instruction_is_tolerated() -> None:
    """Models add preambles; we extract the instruction line, strict on the
    INSTRUCTION, lenient on prose around it."""
    raw = "Sure! Here is my recommendation:\nACCEPT_PARTIAL\nHope that helps."
    p = _parse_response(raw)
    assert p.instruction == "ACCEPT_PARTIAL"
    assert not p.out_of_vocab


def test_empty_response_is_out_of_vocab() -> None:
    assert _parse_response("").out_of_vocab
    assert _parse_response(None).out_of_vocab  # type: ignore[arg-type]


# ----- T1-4: receives registro, never the artifact ----- #

def test_build_prompt_never_includes_artifact_bytes() -> None:
    reg = {"clase": "fmt.json_malformed", "excerpt": "x",
           "artifact_bytes": b"SHOULD_NOT_BE_SENT"}
    prompt = build_user_prompt(reg)
    assert "SHOULD_NOT_BE_SENT" not in prompt
    assert "excerpt: x" in prompt


def test_build_prompt_only_sends_bounded_fields() -> None:
    reg = {"clase": "net.timeout", "fase": "despacho", "slot": "1",
           "puesto": "auditores", "route_id": "r", "expected": "200",
           "found": "NO_CONSTA", "excerpt": "timed out",
           "raw_condition": ""}
    prompt = build_user_prompt(reg)
    for f in ("clase", "fase", "slot", "puesto", "route_id", "expected",
              "found", "excerpt"):
        assert f in prompt


# ----- T1-3: latency escalation at 15s ----- #

def test_t1_timeout_escalates_t2() -> None:
    """T1-3: if the provider doesn't answer in 15s, escalate without waiting."""
    def slow_provider(*, system, user, timeout_s):
        raise TimeoutError("15s elapsed")
    p = call_t1({"clase": "fmt.json_malformed", "excerpt": "x"},
                provider=slow_provider)
    assert p.escalated_t2_latency
    assert p.escalate_t2
    assert p.instruction == "ESCALATE_T2"
    assert "15" in p.reason and "escala T2" in p.reason


def test_t1_provider_error_escalates_t2_not_crash() -> None:
    def broken_provider(*, system, user, timeout_s):
        raise ConnectionError("network down")
    p = call_t1({"clase": "net.timeout", "excerpt": "x"},
                provider=broken_provider)
    assert p.escalate_t2
    assert "ConnectionError" in p.reason


# ----- C4: latency measured CLIENT-SIDE; a late answer is discarded ----- #

def test_t1_late_answer_is_discarded_and_escalates() -> None:
    """C4 / G4: the provider may ignore the timeout and return late. The clock
    is measured CLIENT-SIDE, AFTER the call: a valid answer that arrives past
    T1_LATENCY_TIMEOUT_S is DISCARDED and we escalate. We do not trust the
    provider to honour timeout_s."""
    times = iter([0.0, 20.0])  # start, then +20s elapsed when clock() is read

    def late_but_valid_provider(*, system, user, timeout_s):
        # Returns a perfectly valid answer ... 20s after start.
        return "ACCEPT_PARTIAL"

    p = call_t1({"clase": "fmt.json_malformed", "excerpt": "x"},
                provider=late_but_valid_provider, timeout_s=15.0,
                clock=lambda: next(times))
    assert p.escalated_t2_latency is True
    assert p.escalate_t2
    assert p.instruction == "ESCALATE_T2"
    # The late answer must NOT be applied.
    assert "ACCEPT_PARTIAL" not in (p.reason or "")


# ----- T1-5: one call, no agentic framework (structural) ----- #

def test_t1_makes_exactly_one_provider_call() -> None:
    """T1-5: NO agentic framework. ONE call."""
    calls = {"n": 0}
    def counting_provider(*, system, user, timeout_s):
        calls["n"] += 1
        return "ACCEPT_PARTIAL"
    call_t1({"clase": "fmt.json_malformed", "excerpt": "x"},
            provider=counting_provider)
    assert calls["n"] == 1


# ----- T1-2: T1 prescribes, doesn't generate (structural) ----- #

def test_t1_client_imports_no_agentic_framework() -> None:
    """T1-5/G9: no OpenHands / langchain / agent framework. Pure single call."""
    import inspect
    import scripts.t1_client as mod
    src = inspect.getsource(mod)
    for forbidden in ("openhands", "langchain", "langgraph", "autogen",
                      "crewai", "agent"):
        # 'agent' as a substring is fine in 'agentic' prose; check imports.
        assert f"import {forbidden}" not in src, f"T1 imports {forbidden}"


def test_timeout_default_is_15_seconds() -> None:
    assert T1_LATENCY_TIMEOUT_S == 15.0


# ----- C1: multiple instructions are rejected (BLOQUEANTE) ----- #
# C1 is a regression of the old "swallow the second instruction" behaviour,
# which silently turned an ESCALATE_T2 into an ACCEPT_PARTIAL. The closed
# vocabulary exists to forbid this: ONE instruction or NONE.
#
# NOTE: the previous test_argument_with_newline_is_truncated_to_first_line
# asserted that 'SKIP_WITH_DEBT fmt.json_malformed\nESCALATE_T2' was ACCEPTED
# with the argument clipped. That response contains TWO vocabulary tokens
# (SKIP_WITH_DEBT and ESCALATE_T2) — it is structurally the same defect as
# 'ACCEPT_PARTIAL\nESCALATE_T2'. C1 is BLOQUEANTE and wins, so that test was
# encoding the bug; it is replaced by the rejection tests below.

def test_two_vocabulary_lines_is_out_of_vocab() -> None:
    """C1 / G2: 'ACCEPT_PARTIAL\\nESCALATE_T2' is the canonical verified defect.
    The model asked to escalate; the parser must NOT swallow the second token."""
    p = _parse_response("ACCEPT_PARTIAL\nESCALATE_T2")
    assert p.out_of_vocab is True
    assert p.escalate_t2
    assert p.instruction == "ESCALATE_T2"


def test_two_vocabulary_lines_skip_then_escalate_is_out_of_vocab() -> None:
    """C1: the same defect in a different guise. Two tokens = ambiguous =
    out_of_vocab, regardless of order. (Replaces the old swallow-test.)"""
    p = _parse_response("SKIP_WITH_DEBT fmt.json_malformed\nESCALATE_T2")
    assert p.out_of_vocab is True
    assert p.escalate_t2
    assert "ESCALATE_T2" not in (p.argument or "")


def test_two_instructions_same_line_is_out_of_vocab() -> None:
    """C1: also rejects two instructions glued onto one line (the vocab tokens
    are anchored, so two on one line still means two)."""
    p = _parse_response("ACCEPT_PARTIAL ESCALATE_T2")
    assert p.out_of_vocab is True


def test_single_instruction_still_accepted() -> None:
    """C1 regression guard: ONE instruction (even with chatter) is fine.
    The fix must not over-reject legitimate single responses."""
    p = _parse_response("Sure.\nACCEPT_PARTIAL\nDone.")
    assert not p.out_of_vocab
    assert p.instruction == "ACCEPT_PARTIAL"


# ----- C2: RETRY_WITH_PATH requires a non-empty argument ----- #

def test_retry_with_path_empty_argument_is_out_of_vocab() -> None:
    """C2: 'RETRY_WITH_PATH' with no argument is not actionable — it would be
    applied downstream as an empty path. Reject and escalate."""
    p = _parse_response("RETRY_WITH_PATH")
    assert p.out_of_vocab is True
    assert p.escalate_t2


def test_retry_with_path_whitespace_argument_is_out_of_vocab() -> None:
    """C2: whitespace-only is still empty."""
    p = _parse_response("RETRY_WITH_PATH   ")
    assert p.out_of_vocab is True


# ----- C3: RETRY_WITH_PATH must confine to the permitted root ----- #

def test_retry_with_path_escape_is_out_of_vocab(tmp_path) -> None:
    """C3: a traversal that resolves OUTSIDE the permitted root is rejected,
    not passed through verbatim. Truncating is not confining."""
    root = tmp_path / "workspace"
    root.mkdir()
    p = _parse_response(f"RETRY_WITH_PATH ../../etc/passwd",
                        permitted_root=str(root))
    assert p.out_of_vocab is True
    assert p.escalate_t2


def test_retry_with_path_inside_root_is_accepted(tmp_path) -> None:
    """C3 regression: a legitimate path under the root is accepted."""
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "ok.json"
    target.write_text("{}")
    p = _parse_response(f"RETRY_WITH_PATH {target}",
                        permitted_root=str(root))
    assert not p.out_of_vocab
    assert p.instruction == "RETRY_WITH_PATH"
    assert p.argument == str(target)


# ----- C5: closed-set arguments (RENORMALIZE / SKIP_WITH_DEBT) ----- #

def test_renormalize_invalid_arg_is_out_of_vocab() -> None:
    """C5: RENORMALIZE only accepts encoding|fence|case|newline."""
    p = _parse_response("RENORMALIZE foobar")
    assert p.out_of_vocab is True


def test_renormalize_valid_args_accepted() -> None:
    """C5 regression: each sanctioned arg still parses."""
    for arg in ("encoding", "fence", "case", "newline"):
        p = _parse_response(f"RENORMALIZE {arg}")
        assert not p.out_of_vocab, arg
        assert p.argument == arg


def test_skip_with_debt_invalid_class_is_out_of_vocab() -> None:
    """C5: SKIP_WITH_DEBT only accepts a class from the exception taxonomy."""
    p = _parse_response("SKIP_WITH_DEBT clase.inventada")
    assert p.out_of_vocab is True


def test_skip_with_debt_valid_class_accepted() -> None:
    """C5 regression: a real taxonomy class is accepted."""
    p = _parse_response("SKIP_WITH_DEBT fmt.json_malformed")
    assert not p.out_of_vocab
    assert p.argument == "fmt.json_malformed"


# ----- S4: re-validate the 512-byte excerpt cap in the client ----- #

def test_build_prompt_rejects_oversized_excerpt() -> None:
    """S4: the registro's excerpt is ALREADY supposed to be <=512B, but the
    client must not trust that. A raw registro with a 1MB excerpt must not
    produce a 1MB prompt."""
    from scripts.t1_client import build_user_prompt, T1_EXCERPT_MAX_BYTES
    assert T1_EXCERPT_MAX_BYTES == 512
    # A distinctive tail so its absence after capping is unambiguous.
    huge = ("x" * (1024 * 1024 - 8)) + "TAILMARK"
    reg = {"clase": "fmt.json_malformed", "excerpt": huge}
    prompt = build_user_prompt(reg)
    # The prompt must not balloon: the excerpt must be capped client-side.
    assert len(prompt) < 2048, len(prompt)
    # The oversized tail must not appear verbatim after capping.
    assert "TAILMARK" not in prompt


# ----- argument sanitization (kept, narrowed) ----- #

def test_argument_with_newline_is_rejected_as_two_instructions() -> None:
    """Replaces the old swallow-test: a multi-line argument that smuggles a
    second vocabulary token is now out_of_vocab (see C1 tests above)."""
    p = _parse_response("SKIP_WITH_DEBT fmt.json_malformed\nESCALATE_T2")
    assert p.out_of_vocab is True


# ----- CICLO5 / A5-C3-01: a NaN timeout must fail CLOSED ----- #

def test_t1_nan_timeout_never_silently_accepts_a_late_answer() -> None:
    """A5-C3-01 (ALTA, abierta desde ciclo 3): with timeout_s=float('nan'),
    `elapsed > nan` is ALWAYS False, so a 500s-late answer was silently
    ACCEPTED (verified real in ciclo 4). An invalid budget cannot bound
    latency; the client must fail CLOSED and escalate to T2, never apply the
    late answer. Reverting the fix makes this test RED: the old comparison
    accepts 'ACCEPT_PARTIAL' at 500s."""
    times = iter([0.0, 500.0])
    calls = {"n": 0}

    def late_provider(*, system, user, timeout_s):
        calls["n"] += 1
        return "ACCEPT_PARTIAL"

    p = call_t1({"clase": "fmt.json_malformed", "excerpt": "x"},
                provider=late_provider, timeout_s=float("nan"),
                clock=lambda: next(times))
    assert p.escalate_t2 is True
    assert p.escalated_t2_latency is True
    assert p.instruction == "ESCALATE_T2"
    # The late answer must NOT be applied, and no call is made under an
    # invalid budget (there is nothing to honour, so we don't even call).
    assert p.instruction != "ACCEPT_PARTIAL"
    assert calls["n"] == 0

