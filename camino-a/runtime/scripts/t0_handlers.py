"""t0_handlers.py — deterministic handlers (FASE 2A, OT sec 3).

NOW we write handlers (the FASE 1 'instrument, do not repair' rule is lifted).
They are PURE CODE (T0-4): no network, no models, no I/O side effects. Each
declares what class it handles and WHERE IT CANNOT (T0-2), and returns control
(ESCALATE_T1) rather than guessing (T0-3).

Order of writing follows the lab distribution + error cost (OT sec 3):
  fs.*   pure filesystem: statvfs/exists/access. Zero ambiguity.
  fmt.*  json.loads + repair of fences/encoding. The bulk of real work.
  net.*  NOT repaired: translated to NO_DISPONIBLE, fallback ladder enters.
  sem.*  NO T0 handler. Judgement by definition -> escalates to T2 (G2).

Every proposed repair passes through admisibilidad.check_repair, which rejects
any content change BY HASH. The handler's power is bounded by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from scripts.admisibilidad import HandlerResult, RepairOutcome  # noqa: E402


def _repaired(name: str, reason: str, data: bytes) -> HandlerResult:
    """Propose a repair. The framework checks admissibility before applying."""
    return HandlerResult(outcome=RepairOutcome.REPAIRED, repaired_bytes=data,
                         reason=reason, handler_name=name)


def _cannot(name: str, reason: str) -> HandlerResult:
    """This handler does not cover the case. Returns control; never guesses."""
    return HandlerResult(outcome=RepairOutcome.CANNOT_HANDLE, reason=reason,
                         handler_name=name)


def _escalate(name: str, reason: str) -> HandlerResult:
    """Explicit escalation. T1 gets to try. Escalating is cheap; guessing isn't."""
    return HandlerResult(outcome=RepairOutcome.ESCALATE_T1, reason=reason,
                         handler_name=name)


def _no_action(name: str, reason: str) -> HandlerResult:
    """Nothing to repair (e.g. the file is genuinely fine). Not an error."""
    return HandlerResult(outcome=RepairOutcome.NO_ACTION, reason=reason,
                         handler_name=name)


# =========================================================================== #
# fs.* handlers — pure filesystem. Zero ambiguity, zero hallucination risk.
# Most do NOT repair the bytes (there's nothing to fix in the bytes); they
# classify and return control so the default action (advance with debt, or halt
# for mount_absent) runs. The ones that CAN repair propose a lossless fix.
# =========================================================================== #

def handle_fs_disk_full(signal: dict) -> HandlerResult:
    """fs.disk_full: ENOSPC. Cannot write. Cannot repair from inside the handler
    (freeing space is an operator action). Returns control -> default action
    AVANZA_CON_DEUDA."""
    return _cannot("fs.disk_full",
                   "disco lleno: no es reparable en banda. El operador debe "
                   "liberar espacio. No adivino; devuelvo control.")


def handle_fs_path_missing(signal: dict) -> HandlerResult:
    """fs.path_missing: a required file is absent. CANNOT invent a path
    (hallucinating /Users/mariano/Intercambio when another path was correct is
    exactly the 1-ago error). Escalate to T1 with the registro; T1 may
    RETRY_WITH_PATH if it can ground one."""
    expected = signal.get("expected", "")
    return _escalate("fs.path_missing",
                     f"ruta ausente ({expected}). No invento rutas: el riesgo de "
                     "alucinar el destino es el error del 1-ago. T1 puede proponer "
                     "RETRY_WITH_PATH solo si lo fundamenta.")


def handle_fs_permission_denied(signal: dict) -> HandlerResult:
    """fs.permission_denied: EACCES/EPERM. Cannot chmod from inside the handler
    (side effect + privilege). Returns control -> AVANZA_CON_DEUDA."""
    return _cannot("fs.permission_denied",
                   "permiso denegado: no cambio permisos en banda (seria un "
                   "efecto lateral de privilegio). Devuelvo control.")


def handle_fs_mount_absent(signal: dict) -> HandlerResult:
    """fs.mount_absent: the Intercambio share is not mounted. The ONE class that
    halts the run. Cannot repair (mounting is an operator action)."""
    return _cannot("fs.mount_absent",
                   "share ausente: no se monta en banda. Esta es la unica clase "
                   "que DETIENE la corrida (default action HALT).")


def handle_fs_partial_write(signal: dict) -> HandlerResult:
    """fs.partial_write: a .partial/tmp is orphaned, no final. The write failed;
    we cannot reconstruct the missing bytes (that would be fabrication).
    Escalate: T1 may ACCEPT_PARTIAL if a usable subset exists, else SKIP."""
    return _escalate("fs.partial_write",
                     "escritura parcial huerfana: no reconstruyo bytes faltantes "
                     "(seria fabricacion). T1 decide ACCEPT_PARTIAL o SKIP_WITH_DEBT.")


def handle_fs_truncated(signal: dict) -> HandlerResult:
    """fs.truncated: a file is shorter than expected. We cannot know what the
    missing bytes were. Escalate to T1 (ACCEPT_PARTIAL / SKIP_WITH_DEBT)."""
    return _escalate("fs.truncated",
                     "archivo truncado: no invento el contenido faltante. T1 "
                     "decide ACCEPT_PARTIAL o SKIP_WITH_DEBT.")


# =========================================================================== #
# fmt.* handlers — the bulk of real work. json.loads with lossless repair.
# Each proposed repair goes through the hash check; a content change rejects.
# =========================================================================== #

def handle_fmt_encoding(signal: dict) -> HandlerResult:
    """fmt.encoding: bytes that aren't valid UTF-8. ADMISSIBLE repair: re-encode
    via a declared encoding if the bytes carry one (latin-1 round-trips every
    byte). But this CHANGES bytes -> the hash check will reject unless the
    canonical view is stable. So we propose the re-encoded form and let the
    check decide; if it rejects, escalate."""
    data = signal.get("artifact_bytes")
    if data is None:
        return _cannot("fmt_encoding", "sin bytes de artefacto; no hay nada que decodificar")
    try:
        # latin-1 maps every byte 1:1, so decoding then re-encoding utf-8 is a
        # lossless *transcoding* when the source was latin-1. The hash check is
        # the arbiter of whether this counts as content-preserving.
        text = data.decode("latin-1")
        reencoded = text.encode("utf-8")
        return _repaired("fmt_encoding",
                         "transcoding latin-1 -> utf-8 (cada byte preservado)",
                         reencoded)
    except Exception as e:
        return _escalate("fmt_encoding",
                         f"no pude transcodificar: {type(e).__name__}. T1 decide.")


def handle_fmt_json_malformed(signal: dict) -> HandlerResult:
    """fmt.json_malformed: json.loads fails. T0 can try the genuinely-lossless
    fixes: strip a leading BOM, strip surrounding code fences ONLY if the fenced
    content parses. Fence-stripping changes bytes -> hash check may reject; we
    propose it and let the check arbitrate. We NEVER edit field values."""
    data = signal.get("artifact_bytes")
    if data is None:
        return _cannot("fmt_json_malformed", "sin bytes de artefacto")
    import json
    # C7 (decision a): strip a leading UTF-8 BOM BEFORE the as-is parse.
    # Previously the as-is json.loads silently accepted the BOM, so the BOM-strip
    # branch below was DEAD CODE (Try 2 was unreachable). That left the handler
    # pretending to handle BOM while never doing so. Stripping up front makes the
    # normalization EXPLICIT (visible in the audit trail) and aligns with
    # canonicalize(), which also strips BOM. BOM-strip is admissible (lossless),
    # so the hash check passes when we propose it.
    bom_stripped = False
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
        bom_stripped = True
    # Try 1: as-is (maybe the error was elsewhere, or only the BOM was the issue).
    try:
        json.loads(data)
        if bom_stripped:
            return _repaired("fmt_json_malformed", "strip de BOM UTF-8", data)
        return _no_action("fmt_json_malformed", "el JSON ya parsea; no hay nada que reparar")
    except Exception:
        pass
    # Try 3: fence strip — propose it; the hash check decides. If the fenced
    # payload parses, this is often the real fix (auditors wrap JSON in ```json).
    text = data.decode("utf-8", errors="replace").strip()
    if text.startswith("```"):
        # Drop the opening fence line and a trailing fence.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).encode("utf-8")
        try:
            json.loads(candidate)
            # It parses — propose it. NOTE: this is a byte change, so the hash
            # check will REJECT under strict semantics; that escalates to T1,
            # which is the correct call (fence-strip is a sanctioned T1
            # normalization, not a guaranteed T0 lossless op).
            return _repaired("fmt_json_malformed",
                             "strip de cercos ``` (propuesto; el hash check arbitra)",
                             candidate)
        except Exception:
            pass
    # Cannot resolve losslessly. Escalate; never edit values to make it parse.
    return _escalate("fmt_json_malformed",
                     "no pude reparar sin perdida (BOM/fence no alcanzaron). "
                     "T1 decide RENORMALIZE / ACCEPT_PARTIAL / SKIP. No edito valores.")


def handle_fmt_schema_violation(signal: dict) -> HandlerResult:
    """fmt.schema_violation: valid JSON missing a required contract field. We
    CANNOT invent the missing field's value (that's fabrication). Escalate to T1."""
    return _escalate("fmt_schema_violation",
                     "JSON valido pero incompleto: no invento el valor del campo "
                     "faltante (fabricacion). T1 decide SKIP_WITH_DEBT o ESCALATE_T2.")


def handle_fmt_field_missing(signal: dict) -> HandlerResult:
    """fmt.field_missing: same shape as schema_violation. Cannot fabricate."""
    return _escalate("fmt_field_missing",
                     "campo obligatorio ausente: no fabrico su valor. T1 decide.")


def handle_fmt_truncated_response(signal: dict) -> HandlerResult:
    """fmt.truncated_response: the gateway cut off the response. We don't have
    the missing tail. Escalate: ACCEPT_PARTIAL or SKIP_WITH_DEBT."""
    return _escalate("fmt_truncated_response",
                     "respuesta truncada en el gateway: no tengo la cola faltante. "
                     "T1 decide ACCEPT_PARTIAL o SKIP_WITH_DEBT.")


# =========================================================================== #
# net.* handlers — NOT repaired. Translated to NO_DISPONIBLE; the fallback
# ladder (D3) enters. The handler only classifies; it does not retry the network
# (no network access — T0-4).
# =========================================================================== #

def handle_net_generic(signal: dict) -> HandlerResult:
    """All net.* classes: rate_limited, server_error, timeout, auth_failed,
    model_not_found. The handler does NOT retry (no network). It signals
    NO_DISPONIBLE so the fallback ladder enters. This is the default action."""
    clase = signal.get("clase", "net.*")
    return _no_action(f"net[{clase}]",
                      f"{clase}: no reintentado en T0 (sin red). Traducido a "
                      "NO_DISPONIBLE -> entra la escalera de fallback.")


# =========================================================================== #
# sem.* — NO T0 HANDLER. By definition these are judgement and escalate to T2.
# (G2: NINGUN handler T0 para sem.*.) We do not register any here.
# =========================================================================== #


# ---- registry: clase -> handler. sem.* deliberately absent. ---- #
HANDLERS: dict[str, Callable[[dict], HandlerResult]] = {
    "fs.disk_full": handle_fs_disk_full,
    "fs.path_missing": handle_fs_path_missing,
    "fs.permission_denied": handle_fs_permission_denied,
    "fs.mount_absent": handle_fs_mount_absent,
    "fs.partial_write": handle_fs_partial_write,
    "fs.truncated": handle_fs_truncated,
    "fmt.encoding": handle_fmt_encoding,
    "fmt.json_malformed": handle_fmt_json_malformed,
    "fmt.schema_violation": handle_fmt_schema_violation,
    "fmt.field_missing": handle_fmt_field_missing,
    "fmt.truncated_response": handle_fmt_truncated_response,
    "net.rate_limited": handle_net_generic,
    "net.server_error": handle_net_generic,
    "net.timeout": handle_net_generic,
    "net.auth_failed": handle_net_generic,
    "net.model_not_found": handle_net_generic,
    # sem.* intentionally NOT here.
}


def has_handler(clase: str) -> bool:
    """G2: is there a T0 handler for this class? sem.* and UNMAPPED -> False."""
    return clase in HANDLERS


def no_sem_handlers() -> bool:
    """G2 invariant: no sem.* handler is registered."""
    return not any(c.startswith("sem.") for c in HANDLERS)
