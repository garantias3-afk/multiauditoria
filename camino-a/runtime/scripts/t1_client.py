"""t1_client.py — T1, the cheap cloud model that prescribes (FASE 2B, OT sec 5).

T1 is NOT a 'desktop-problem specialist' (none exists). It is a small reasoning
model that follows instructions and picks from a CLOSED VOCABULARY without
inventing. The job is CLASSIFY, not generate.

  T1-1 VOCABULARIO CERRADO — returns exactly ONE of:
        RETRY_WITH_PATH <ruta>
        RENORMALIZE <encoding|fence|case|newline>
        ACCEPT_PARTIAL
        SKIP_WITH_DEBT <clase>
        ESCALATE_T2
        ABORT_SLOT_KEEP_RUN
    Anything outside the vocabulary is DISCARDED and ESCALATE_T2 is used.
  T1-2 T1 does NOT write files, propose code, or draft. It prescribes; code runs.
  T1-3 ESCALACION POR LATENCIA: if T1 does not answer in 15s, escalate to T2.
  T1-4 T1 receives the REGISTRO (excerpt capped at 512B), never the artifact.
  T1-5 NO agentic framework. ONE call, ONE instruction.

Provider invocation is delegated to a caller-supplied callable so the client is
unit-testable without network. The real callable wraps a single OpenRouter /
NVIDIA chat completion on the registro's excerpt.
"""
from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

T1_LATENCY_TIMEOUT_S = 15.0  # T1-3: escalate to T2 after 15s.

# S4: the registro's excerpt is supposed to be capped at record time, but the
# client must not TRUST that — a raw/malformed registro with a huge excerpt
# would balloon the prompt. Re-validate here.
T1_EXCERPT_MAX_BYTES = 512

# T1-1: the closed vocabulary. The model returns ONE of these lines.
VOCABULARY = (
    "RETRY_WITH_PATH",    # + <ruta>
    "RENORMALIZE",        # + <encoding|fence|case|newline>
    "ACCEPT_PARTIAL",
    "SKIP_WITH_DEBT",     # + <clase>
    "ESCALATE_T2",
    "ABORT_SLOT_KEEP_RUN",
)
# A regex that accepts the line plus its optional argument, anchored.
_VOCAB_RE = re.compile(
    r"^(RETRY_WITH_PATH|RENORMALIZE|ACCEPT_PARTIAL|SKIP_WITH_DEBT|ESCALATE_T2"
    r"|ABORT_SLOT_KEEP_RUN)(?:\s+(.+))?$\s*$",
    re.MULTILINE,
)
# C1: a bare token of the vocabulary appearing anywhere in the response. We
# count how many DISTINCT vocabulary instructions the model emitted: anything
# other than exactly ONE is ambiguous and is discarded. This is what makes the
# closed vocabulary actually closed — the old parser silently kept the first
# and dropped the rest (the BLOQUEANTE defect: ESCALATE_T2 became ACCEPT_PARTIAL).
_VOCAB_TOKEN_RE = re.compile(
    r"\b(RETRY_WITH_PATH|RENORMALIZE|ACCEPT_PARTIAL|SKIP_WITH_DEBT|ESCALATE_T2"
    r"|ABORT_SLOT_KEEP_RUN)\b"
)

# C5: closed-set arguments. The model cannot invent these.
_RENORMALIZE_ARGS = ("encoding", "fence", "case", "newline")


def _is_known_exception_class(name: str) -> bool:
    """C5: SKIP_WITH_DEBT only accepts a class from the exception taxonomy.
    Imported lazily so t1_client stays importable in isolation."""
    try:
        from scripts.exception_taxonomy import CLASSES
    except Exception:
        # Without the taxonomy we fail CLOSED: reject the argument rather than
        # accept an unvalidated class. The audit log will show the reason.
        return False
    return name in CLASSES

# The system prompt T1 gets. Deliberately small and prescriptive: pick one.
SYSTEM_PROMPT = (
    "Sos un clasificador de fallas de un runner de auditoria de codigo. "
    "Recibis el REGISTRO de una excepcion (no el artefacto). Devolve UNA linea "
    "con UNA instruccion de esta lista y nada mas:\n"
    "  RETRY_WITH_PATH <ruta>     # la ruta correcta difiere de la usada\n"
    "  RENORMALIZE <encoding|fence|case|newline>  # normalizacion sin perdida\n"
    "  ACCEPT_PARTIAL             # usar lo que hay, declarar cobertura parcial\n"
    "  SKIP_WITH_DEBT <clase>     # saltear, registrar deuda de la clase\n"
    "  ESCALATE_T2                # necesita juicio: subir al modelo potente\n"
    "  ABORT_SLOT_KEEP_RUN        # el slot no tiene salvataje, la corrida sigue\n"
    "No escribas codigo, no redactes, no propongas archivos. Solo la linea."
)


@dataclass(frozen=True)
class T1Prescription:
    """The parsed, vocabulary-validated result of a T1 call."""
    instruction: str          # one of VOCABULARY
    argument: str = ""        # the <ruta>/<encoding>/<clase> after the keyword
    raw_response: str = ""    # the model's full response (for the audit log)
    out_of_vocab: bool = False  # True if the response was discarded
    escalated_t2_latency: bool = False  # True if it timed out
    reason: str = ""

    @property
    def escalate_t2(self) -> bool:
        return self.instruction == "ESCALATE_T2" or self.out_of_vocab or self.escalated_t2_latency


class T1Provider(Protocol):
    """A single chat-completion call. Implemented by the runner against the
    provider. Must enforce the 15s timeout itself OR the client wraps it."""
    def __call__(self, *, system: str, user: str, timeout_s: float) -> str: ...


def _parse_response(raw: str, *, permitted_root: Optional[str] = None) -> T1Prescription:
    """Parse + validate the model response against the closed vocabulary.

    T1-1: anything outside the vocabulary is DISCARDED and we escalate to T2.
    We never interpret a near-match (that would let the model invent).

    C1 (BLOQUEANTE): exactly ONE vocabulary token is allowed. Two or more is
        ambiguous (the canonical defect: 'ACCEPT_PARTIAL\\nESCALATE_T2' was
        silently collapsed to ACCEPT_PARTIAL). We count DISTINCT tokens.
    C2: RETRY_WITH_PATH REQUIRES a non-empty argument.
    C3: RETRY_WITH_PATH's argument is RESOLVED and CONFINED to permitted_root;
        a traversal that escapes the root is rejected. permitted_root is
        required for RETRY_WITH_PATH — without a root we cannot confine, so we
        fail closed (reject). Truncating is NOT confining.
    C5: RENORMALIZE and SKIP_WITH_DEBT take arguments from a CLOSED SET only.
    """
    if raw is None:
        return T1Prescription(instruction="ESCALATE_T2", raw_response="",
                              out_of_vocab=True,
                              reason="respuesta vacia; descartada, escala T2")
    # C1: count the DISTINCT vocabulary instructions the model emitted. We do
    # NOT silently keep the first and drop the rest — that was the defect.
    distinct = set(_VOCAB_TOKEN_RE.findall(raw))
    if len(distinct) > 1:
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
            reason=(f"respuesta con {len(distinct)} instrucciones del "
                    f"vocabulario ({sorted(distinct)}): ambigua, descartada, "
                    f"escala T2. El vocabulario cerrado exige UNA instruccion."))
    # Take the first vocabulary-matching line. Ignore surrounding prose: many
    # models add "Here is..." preambles. We are strict about the INSTRUCTION,
    # lenient about chatter around it — but if NO line matches, we discard.
    m = _VOCAB_RE.search(raw)
    if not m:
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
            reason=f"respuesta fuera del vocabulario cerrado; descartada, escala T2")
    instruction = m.group(1)
    argument = (m.group(2) or "").strip()
    # The argument is a bare token (path/keyword). Clip to one line and cap.
    if argument:
        argument = argument.splitlines()[0].strip()[:256]

    # C2: RETRY_WITH_PATH REQUIRES a non-empty argument.
    if instruction == "RETRY_WITH_PATH" and not argument:
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
            reason="RETRY_WITH_PATH sin argumento: no accionable, descartada, escala T2")

    # C3: confine RETRY_WITH_PATH to the permitted root. RESOLVE then CONFINE;
    # truncating is not confining. No root -> cannot confine -> fail closed.
    if instruction == "RETRY_WITH_PATH":
        if not permitted_root:
            return T1Prescription(
                instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
                reason="RETRY_WITH_PATH sin permitted_root: no se puede confinar "
                       "la ruta, descartada, escala T2")
        try:
            resolved = os.path.realpath(argument)
            root_real = os.path.realpath(permitted_root)
        except (OSError, ValueError) as e:
            return T1Prescription(
                instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
                reason=f"RETRY_WITH_PATH: ruta no resolvable ({type(e).__name__}), "
                       f"descartada, escala T2")
        # CONFINE: the resolved path must be EQUAL TO or BELOW the root.
        if resolved != root_real and not resolved.startswith(root_real + os.sep):
            return T1Prescription(
                instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
                reason=f"RETRY_WITH_PATH fuera de la raiz permitida "
                       f"('{resolved}' no esta bajo '{root_real}'): descartada, "
                       f"escala T2. Truncar no es confinar.")
        argument = resolved

    # C5: closed-set arguments for the two keyword instructions.
    if instruction == "RENORMALIZE":
        if argument not in _RENORMALIZE_ARGS:
            return T1Prescription(
                instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
                reason=f"RENORMALIZE '{argument}' no esta en el conjunto cerrado "
                       f"{_RENORMALIZE_ARGS}: descartada, escala T2")
    elif instruction == "SKIP_WITH_DEBT":
        if not _is_known_exception_class(argument):
            return T1Prescription(
                instruction="ESCALATE_T2", raw_response=raw, out_of_vocab=True,
                reason=f"SKIP_WITH_DEBT '{argument}' no es una clase del taxonomia "
                       f"de excepciones: descartada, escala T2")

    return T1Prescription(instruction=instruction, argument=argument,
                          raw_response=raw, out_of_vocab=False,
                          reason="vocabulario valido")


def build_user_prompt(registro: dict) -> str:
    """T1-4: build the prompt from the REGISTRO, never the artifact.

    Only the bounded fields go in. The excerpt is supposed to be <=512B (capped
    at record time) but we DO NOT trust that (S4): a raw/malformed registro with
    a huge excerpt would balloon the prompt. We re-cap client-side.
    """
    if "artifact_bytes" in registro:
        # Defensive: never send the full artifact even if a caller slipped it in.
        registro = {k: v for k, v in registro.items() if k != "artifact_bytes"}
    # S4: re-cap the excerpt client-side. Encode to measure bytes, not chars.
    excerpt = registro.get("excerpt", "")
    if isinstance(excerpt, str):
        eb = excerpt.encode("utf-8", errors="replace")
        if len(eb) > T1_EXCERPT_MAX_BYTES:
            eb = eb[:T1_EXCERPT_MAX_BYTES]
        excerpt = eb.decode("utf-8", errors="replace")
        registro = {**registro, "excerpt": excerpt}
    fields = ("clase", "fase", "expected", "found", "excerpt", "slot",
              "puesto", "route_id", "raw_condition")
    lines = [f"{k}: {registro.get(k, 'NO_CONSTA')}" for k in fields]
    return "REGISTRO DE EXCEPCION:\n" + "\n".join(lines) + "\n\nTu instruccion:"


def call_t1(
    registro: dict,
    *,
    provider: T1Provider,
    timeout_s: float = T1_LATENCY_TIMEOUT_S,
    clock: Callable[[], float] = time.monotonic,
    permitted_root: Optional[str] = None,
) -> T1Prescription:
    """Make ONE T1 call (T1-5) on the registro, with latency escalation (T1-3).

    Returns a validated T1Prescription. On timeout or out-of-vocab, escalates
    to T2. Never sends the artifact; only the registro (T1-4).

    C4: the latency clock is measured CLIENT-SIDE, AFTER the call. We do NOT
    trust the provider to honour timeout_s — a valid answer that arrives past
    the budget is DISCARDED and we escalate. TimeoutError remains an additional
    path, not the only one.

    C3: permitted_root confines any RETRY_WITH_PATH argument. If absent,
    RETRY_WITH_PATH fails closed (rejected); other instructions are unaffected.
    """
    user = build_user_prompt(registro)
    # CICLO5 / A5-C3-01 fix: NaN comparisons are ALWAYS False, so with a NaN
    # budget `elapsed > timeout_s` never fires and ANY late answer (verified:
    # 500s late) was silently ACCEPTED. A non-finite float budget (NaN/inf)
    # cannot bound latency; fail CLOSED and escalate to T2 instead of accepting
    # in silence under an invalid budget. Checked BEFORE the call: without a
    # comparable budget there is nothing to honour, so we don't even make it.
    if isinstance(timeout_s, float) and not math.isfinite(timeout_s):
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response="",
            escalated_t2_latency=True,
            reason=(f"timeout_s invalido ({timeout_s!r}): no es un numero "
                    f"finito, no hay presupuesto de latencia comparable. No se "
                    f"acepta en silencio con presupuesto invalido; escala T2."))
    start = clock()
    try:
        raw = provider(system=SYSTEM_PROMPT, user=user, timeout_s=timeout_s)
    except TimeoutError:
        # T1-3: latency escalation. Don't wait; go to T2.
        elapsed = clock() - start
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response="",
            escalated_t2_latency=True,
            reason=f"T1 no contesto en {timeout_s}s (tardo ~{elapsed:.1f}s); escala T2")
    except Exception as e:
        # Any provider failure is an escalation, not a crash of the handler path.
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response="",
            out_of_vocab=True,
            reason=f"fallo del proveedor T1 ({type(e).__name__}); escala T2")
    # C4: measure CLIENT-SIDE. The provider may have ignored timeout_s and
    # returned late. A late answer is DISCARDED, even if it was valid.
    elapsed = clock() - start
    if elapsed > timeout_s:
        return T1Prescription(
            instruction="ESCALATE_T2", raw_response=raw,
            escalated_t2_latency=True,
            reason=(f"T1 tardo ~{elapsed:.1f}s > {timeout_s}s (reloj del lado "
                    f"del cliente): respuesta DESCARTADA, escala T2. No se confia "
                    f"en que el proveedor respete el timeout."))
    return _parse_response(raw, permitted_root=permitted_root)
