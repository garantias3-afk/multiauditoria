"""admisibilidad.py — the hash-admissibility check (OT sec 4 / T0-5, T0-6, G5).

A repair is ADMISSIBLE iff the canonical content hashes equal BEFORE and AFTER.

  ADMISIBLE      encoding, BOM, mayusculas del nombre de archivo, resolucion de
                 ruta, quitar cercos de codigo, salto de linea final.
                 (normalizaciones sin perdida)
  NO ADMISIBLE   cambiar el valor de un campo, descartar un hallazgo, resolver
                 una ambiguedad de contenido. (eso es juicio, y escala a T1/T2)

The check is VERIFIED BY HASH, not by promise. A handler that tries to change
content is REJECTED by the check, not by good behaviour (T0-6). This acota el
poder del handler por construccion.

How it works:
  - The handler proposes a repaired artifact (bytes) for a given input (bytes).
  - The framework computes canonical_hash(input) and canonical_hash(output).
  - canonical_hash applies ONLY the lossless normalizations (BOM strip, trailing
    newline normalization) that the spec calls admisible; anything beyond that
    changes the hash and the repair is rejected.
  - A rejected repair escalates to T1. The handler never gets to "commit" a
    content change.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


# The lossless normalizations that define the CANONICAL view. These are the
# ONLY transformations considered "no-op for content": they are applied to BOTH
# before and after views, so a repair that only does these leaves the hash
# unchanged. Anything else changes the hash -> rejected.
#
# (OT sec 4: encoding/BOM/case-of-name/path-resolution/fence-strip/trailing-NL.)
def canonicalize(content: bytes) -> bytes:
    """Apply the lossless normalizations that define the canonical view.

    This is what we hash. A repair is admissible iff canonicalize(input) ==
    canonicalize(output). The normalizations here are ALL content-preserving:
      - strip a leading UTF-8 BOM
      - normalize a trailing newline to exactly one \n
    Path/filename/case resolution are NOT here: they change WHERE the bytes
    live, not WHAT the bytes are, so they don't enter the content hash at all.
    Fence-stripping is a content change and is therefore NOT lossless from the
    hash's perspective -> a handler that strips fences will be REJECTED and must
    escalate (fence stripping is a T1 judgement call, not a T0 guarantee).
    """
    # CICLO5 / A7-C4-04 fix: strict WHITELIST guard — exactly `bytes`, checked
    # by type identity. The CICLO4 materialization `c = bytes(content)` was a
    # BLACKLIST approach, and Python 3.14 gives the attacker two more doors
    # (both verified empirically on 3.14.6 with writes to real disk):
    #   - bytes() honours __bytes__ BEFORE the buffer protocol on bytes
    #     subclasses: a subclass whose real buffer is malicious but whose
    #     __bytes__ returns the benign view was ADMITTED and then written;
    #   - a PEP 688 __buffer__ can present a DIFFERENT view on each
    #     conversion: the hash saw one buffer, a later writer saw another.
    # `type(content) is bytes` cannot be enumerated by dunders — no subclass,
    # no __bytes__, no __buffer__, no future protocol reaches it. The class
    # of attacks is closed BY CONSTRUCTION, not by another blacklist round.
    # isinstance is FORBIDDEN here: it accepts subclasses, and the subclass
    # IS the attack. check_repair's except converts the TypeError below into
    # a RECHAZO verdict (escalates to T1), never a crash of the run.
    if type(content) is not bytes:
        raise TypeError(
            f"canonicalize espera bytes exacto, llego {type(content).__name__}"
        )
    c = content
    # Strip a single leading UTF-8 BOM if present.
    if c.startswith(b"\xef\xbb\xbf"):
        c = c[3:]
    # Normalize trailing newlines: collapse trailing \n / \r\n runs to one \n.
    # (Keeps content identical for any JSON/text parser; only whitespace tail.)
    c = c.rstrip(b"\r\n") + b"\n"
    return c


def canonical_hash(content: bytes) -> str:
    """SHA-256 of the canonicalized content. The single source of truth for
    whether a repair changed content."""
    return hashlib.sha256(canonicalize(content)).hexdigest()


@dataclass(frozen=True)
class AdmissibilityVerdict:
    """Result of checking a proposed repair.

    CICLO5 / A7-C3-04 (TOCTOU): the verdict carries `canonical_bytes`, the
    EXACT canonical copy that was hashed. Callers that apply/write the repair
    MUST propagate this copy, not the handler's original object: the object a
    handler returns can lie on a later conversion (dynamic __buffer__, mutable
    buffers), but the copy that was hashed is a plain immutable bytes and can
    no longer change between check and write.
    """
    admissible: bool
    reason: str
    hash_before: str
    hash_after: str
    canonical_bytes: bytes = b""  # the canonical copy that was hashed ("" if
                                  # the check never reached hashing)

    @property
    def rejected(self) -> bool:
        return not self.admissible


def check_repair(original: bytes, repaired: bytes, *, handler_name: str = "") -> AdmissibilityVerdict:
    """Verify a proposed repair is content-preserving.

    Returns AdmissibilityVerdict. If rejected, the caller MUST escalate to T1
    and NOT apply the repair. The handler's power is bounded here, regardless
    of what the handler tried to do.

    C6: invalid input types (str, None, mixed) used to crash with an uncaught
    TypeError out of canonicalize (e.g. str.startswith(b"...")). A type error
    is treated as a RECHAZO verdict and the caller escalates — it must NOT
    crash the run. The hash check stays strict; what changes is HOW an invalid
    type is reported. We never loosen the hash to accept a bad type.

    CICLO5: the except now also catches ValueError — a hostile or broken
    conversion path can raise it where TypeError was expected, and an uncaught
    ValueError out of the check is the same defect as an uncaught TypeError
    (a crash instead of a verdict). Both fail CLOSED: RECHAZO + escalation.
    """
    try:
        canon_before = canonicalize(original)
        canon_after = canonicalize(repaired)
    except (TypeError, ValueError) as e:
        # Invalid type (str/None/subclass/hostile dunder). Reject by verdict,
        # not by exception. The handler's power is STILL bounded: nothing is
        # applied. No canonical copy was hashed -> canonical_bytes stays b"".
        return AdmissibilityVerdict(
            admissible=False,
            reason=(f"RECHAZADO: el handler '{handler_name}' paso tipos "
                    f"invalidos a check_repair ({type(e).__name__}: {e}). "
                    f"Se espera bytes exacto. No se aplica la reparacion; "
                    f"escala a T1."),
            hash_before="", hash_after="",
        )
    h_before = hashlib.sha256(canon_before).hexdigest()
    h_after = hashlib.sha256(canon_after).hexdigest()
    if h_before == h_after:
        return AdmissibilityVerdict(
            admissible=True,
            reason=f"hash estable: {h_before[:16]} == {h_after[:16]}",
            hash_before=h_before, hash_after=h_after,
            canonical_bytes=canon_after,
        )
    # REJECTED: the handler tried to change content. This is the load-bearing
    # guardrail. The repair is discarded; T1 gets to try.
    return AdmissibilityVerdict(
        admissible=False,
        reason=(f"RECHAZADO: el handler '{handler_name}' cambio el contenido "
                f"(antes {h_before[:16]} != despues {h_after[:16]}). "
                f"Escala a T1: la reparacion no es sin perdida."),
        hash_before=h_before, hash_after=h_after,
        canonical_bytes=canon_after,
    )


# ---- the handler contract ---- #

class RepairOutcome(str, Enum):
    """What a T0 handler returns. It NEVER applies a repair directly; it
    PROPOSES one, and the framework decides admissibility."""
    REPAIRED = "REPAIRED"               # proposed a repair; framework checks hash
    CANNOT_HANDLE = "CANNOT_HANDLE"     # this handler doesn't cover the case
    ESCALATE_T1 = "ESCALATE_T1"         # explicit: needs T1 judgement
    NO_ACTION = "NO_ACTION"             # nothing to repair (not an error)


@dataclass(frozen=True)
class HandlerResult:
    """The result a T0 handler returns."""
    outcome: RepairOutcome
    repaired_bytes: Optional[bytes] = None  # only when outcome == REPAIRED
    reason: str = ""
    handler_name: str = ""

    @property
    def escalated(self) -> bool:
        return self.outcome == RepairOutcome.ESCALATE_T1


# A handler is a pure function: signal dict -> HandlerResult. No I/O, no network,
# no models (T0-4). The signal carries the exception registro's class + the
# artifact bytes (when relevant) + the error string.
HandlerFn = Callable[[dict], HandlerResult]
