"""t0_dispatch.py — route an exception registro through T0, then admissibility.

The pipeline:
  registro -> classify -> T0 handler (if any) -> admissibility check -> result
  - no handler / CANNOT_HANDLE / ESCALATE_T1 -> goes to T1
  - REPAIRED proposal -> hash check; if rejected, escalates to T1
  - NO_ACTION -> default action applies (no repair needed)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from scripts.admisibilidad import HandlerResult, RepairOutcome, check_repair  # noqa: E402
from scripts.t0_handlers import HANDLERS, has_handler, no_sem_handlers  # noqa: E402


@dataclass(frozen=True)
class T0Verdict:
    """What T0 decided for a registro."""
    clase: str
    handler_name: str
    outcome: RepairOutcome
    admissible: bool              # only meaningful when outcome == REPAIRED
    repaired_bytes: Optional[bytes] = None
    reason: str = ""
    escalates_to_t1: bool = False  # True when T0 gives up / is rejected

    @property
    def repaired(self) -> bool:
        return self.outcome == RepairOutcome.REPAIRED and self.admissible


def run_t0(signal: dict) -> T0Verdict:
    """Run the T0 handler for a signal's class, if any.

    `signal` is the exception registro as a dict, optionally carrying
    `artifact_bytes` (the bytes of the artifact the exception refers to). T0
    handlers are pure functions of this dict (no I/O, no network, no models).
    """
    clase = str(signal.get("clase") or "UNMAPPED_CONDITION")
    if not has_handler(clase):
        # No T0 handler (sem.*, UNMAPPED, or anything else) -> straight to T1.
        return T0Verdict(clase=clase, handler_name="(none)",
                         outcome=RepairOutcome.ESCALATE_T1, admissible=False,
                         reason=f"sin handler T0 para {clase}",
                         escalates_to_t1=True)

    handler = HANDLERS[clase]
    result: HandlerResult = handler(signal)

    if result.outcome == RepairOutcome.REPAIRED:
        # The handler proposed a repair. The hash check decides admissibility.
        original = signal.get("artifact_bytes") or b""
        verdict = check_repair(original, result.repaired_bytes or b"",
                               handler_name=result.handler_name)
        if verdict.rejected:
            # T0-6: rejected BY THE CHECK, not by good conduct. Escalate to T1.
            return T0Verdict(clase=clase, handler_name=result.handler_name,
                             outcome=RepairOutcome.REPAIRED, admissible=False,
                             reason=verdict.reason, escalates_to_t1=True)
        # CICLO5 / A7-C3-04 (TOCTOU), second independent closure: propagate the
        # EXACT canonical copy that was hashed, never the handler's live object.
        # The verdict's copy is plain immutable bytes; whatever the handler's
        # object would show on a later conversion can no longer matter, because
        # what gets applied/written is what was hashed. Independent of the
        # type-identity guard in canonicalize: even a well-typed bytes from a
        # handler is passed through as the snapshotted canonical form.
        return T0Verdict(clase=clase, handler_name=result.handler_name,
                         outcome=RepairOutcome.REPAIRED, admissible=True,
                         repaired_bytes=verdict.canonical_bytes,
                         reason=result.reason, escalates_to_t1=False)

    if result.outcome in (RepairOutcome.CANNOT_HANDLE, RepairOutcome.ESCALATE_T1):
        return T0Verdict(clase=clase, handler_name=result.handler_name,
                         outcome=result.outcome, admissible=False,
                         reason=result.reason, escalates_to_t1=True)

    # NO_ACTION: nothing to repair; default action applies.
    return T0Verdict(clase=clase, handler_name=result.handler_name,
                     outcome=RepairOutcome.NO_ACTION, admissible=False,
                     reason=result.reason, escalates_to_t1=False)
