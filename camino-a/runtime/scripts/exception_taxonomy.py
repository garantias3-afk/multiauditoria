"""exception_taxonomy.py — closed, versioned enum of exception classes (OT sec 5).

OT RUNNER HANDLER, FASE 1. The taxonomy is the starting point; it is AMPLIFIED
by what FASE 1 instrumentation actually observes, never invented on the fly.

  fs.disk_full      fs.path_missing      fs.permission_denied
  fs.mount_absent   fs.partial_write     fs.truncated
  net.rate_limited  net.server_error     net.timeout
  net.auth_failed   net.model_not_found
  fmt.encoding      fmt.json_malformed   fmt.schema_violation
  fmt.field_missing fmt.truncated_response
  sem.contradiction sem.orphan_claim     sem.unresolvable
  UNMAPPED_CONDITION

Rule (OT sec 5): an executor CANNOT invent a class. If nothing fits, classify
as UNMAPPED_CONDITION with raw_condition preserved. If the UNMAPPED rate
exceeds 20%, the taxonomy does not fit and must be revised (G7).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

TAXONOMY_VERSION = "camino_n_exception_taxonomy.v1"

# The closed set. Order is stable for reporting.
CLASSES: Tuple[str, ...] = (
    # filesystem / protocol failures (deterministic by nature)
    "fs.disk_full",
    "fs.path_missing",
    "fs.permission_denied",
    "fs.mount_absent",
    "fs.partial_write",
    "fs.truncated",
    # network / provider
    "net.rate_limited",
    "net.server_error",
    "net.timeout",
    "net.auth_failed",
    "net.model_not_found",
    # format
    "fmt.encoding",
    "fmt.json_malformed",
    "fmt.schema_violation",
    "fmt.field_missing",
    "fmt.truncated_response",
    # semantic (the rare ones needing judgement)
    "sem.contradiction",
    "sem.orphan_claim",
    "sem.unresolvable",
    # escape hatch — MUST stay last
    "UNMAPPED_CONDITION",
)

FAMILIES = ("fs", "net", "fmt", "sem", "UNMAPPED")
UNMAPPED = "UNMAPPED_CONDITION"


@dataclass(frozen=True)
class Classification:
    """Result of classifying an observed signal."""
    clase: str                 # one of CLASSES
    raw_condition: str = ""    # preserved verbatim when UNMAPPED, for revision
    family: str = ""           # fs|net|fmt|sem|UNMAPPED

    @property
    def is_unmapped(self) -> bool:
        return self.clase == UNMAPPED


def _family_of(clase: str) -> str:
    if clase == UNMAPPED:
        return "UNMAPPED"
    return clase.split(".", 1)[0] if "." in clase else "UNMAPPED"


def classify_from_signal(
    error_str: str,
    *,
    fase: str = "",
    exc: Optional[BaseException] = None,
) -> Classification:
    """Classify a signal into the closed enum.

    `error_str` is the string the runner/gateway produced — for
    worker_gateway._post_json it looks like 'http_429', 'TimeoutError: ...',
    'invalid_json_response:...', etc. `exc` is the live exception when the
    signal came from a raised exception (carries errno / type info).

    Mapping is conservative: a clear signal maps to its class; anything
    ambiguous becomes UNMAPPED_CONDITION with raw_condition preserved. We never
    invent a class outside CLASSES (OT sec 5).
    """
    s = (error_str or "").strip()
    low = s.lower()

    # --- filesystem signals ---
    if exc is not None:
        en = getattr(exc, "errno", None)
        # POSIX ENOSPC / EDQUOT -> disk full.
        import errno as _errno
        if en in (_errno.ENOSPC, _errno.EDQUOT):
            return _c("fs.disk_full", s)
        if isinstance(exc, PermissionError) or en in (_errno.EACCES, _errno.EPERM):
            return _c("fs.permission_denied", s)
        if isinstance(exc, FileNotFoundError) or en == _errno.ENOENT:
            return _c("fs.path_missing", s)
        if isinstance(exc, IsADirectoryError) or en in (_errno.EISDIR, _errno.ENOTDIR):
            return _c("fs.path_missing", s)
    if "enosc" in low or "no space left" in low or "disk full" in low:
        return _c("fs.disk_full", s)
    if "permission denied" in low or "eacces" in low or "eperm" in low:
        return _c("fs.permission_denied", s)
    if "share_unavailable" in low or "mount_absent" in low or "intercambio_share" in low:
        return _c("fs.mount_absent", s)
    if "partial_write" in low or ".partial" in low:
        # fs.partial_write is specifically the orphaned .partial/tmp marker, not
        # any use of the word "orphan" (which also appears in sem.orphan_claim).
        return _c("fs.partial_write", s)
    if "truncated" in low and "response" not in low:
        return _c("fs.truncated", s)
    if "no such file" in low or "not found" in low and "http_" not in low:
        # Ambiguous: "not found" could be a file or a model. Defer unless it's
        # clearly fs (no http_ prefix and no provider context).
        if "http_" not in low and "model" not in low:
            return _c("fs.path_missing", s)

    # --- network signals (worker_gateway._post_json shapes) ---
    if "http_429" in low or "rate" in low and "limit" in low:
        return _c("net.rate_limited", s)
    if "http_401" in low or "http_403" in low or "auth" in low and "fail" in low:
        return _c("net.auth_failed", s)
    if "http_404" in low or ("model_not_found" in low) or ("model" in low and "not found" in low):
        return _c("net.model_not_found", s)
    if "http_5" in low and any(ch.isdigit() for ch in low[low.find("http_5"):low.find("http_5")+6]):
        return _c("net.server_error", s)
    if "timeout" in low or "timed out" in low or "TimeoutError".lower() in low:
        return _c("net.timeout", s)
    if "connectionerror" in low or "connection refused" in low or "connection reset" in low:
        return _c("net.timeout", s)  # connection-level failure: provider not reachable

    # --- format signals ---
    if "encoding" in low or "unicode" in low or "utf-8" in low and "decode" in low:
        return _c("fmt.encoding", s)
    if "invalid_json" in low or "jsondecodeerror" in low or "json_malformed" in low \
       or ("json" in low and ("decode" in low or "parse" in low)):
        return _c("fmt.json_malformed", s)
    if "schema" in low and ("violation" in low or "missing" in low):
        return _c("fmt.schema_violation", s)
    if "field_missing" in low or "required" in low and "field" in low:
        return _c("fmt.field_missing", s)
    if "truncated_response" in low or ("response" in low and "truncat" in low) \
       or "gateway_response_too_large" in low:
        return _c("fmt.truncated_response", s)

    # --- semantic signals (rare; usually raised explicitly by auditors) ---
    if "contradiction" in low:
        return _c("sem.contradiction", s)
    if "orphan_claim" in low or "orphan" in low and "claim" in low:
        return _c("sem.orphan_claim", s)
    if "unresolvable" in low:
        return _c("sem.unresolvable", s)

    # Nothing fit. UNMAPPED, raw_condition preserved for taxonomy revision.
    return Classification(clase=UNMAPPED, raw_condition=s or "(empty signal)",
                          family="UNMAPPED")


def _c(clase: str, raw: str) -> Classification:
    return Classification(clase=clase, raw_condition=raw if clase == UNMAPPED else "",
                          family=_family_of(clase))


def unmapped_rate(class_counts: dict[str, int]) -> float:
    """G7: the UNMAPPED rate. >20% => taxonomy must be revised."""
    total = sum(class_counts.values())
    if total == 0:
        return 0.0
    return class_counts.get(UNMAPPED, 0) / total
