"""default_actions.py — the predeclared default action per class (OT sec 6).

Each class has an action declared IN ADVANCE, applied automatically if nothing
handles it. The process NEVER stops dead except for fs.mount_absent. In the
worst case the run ends with less evidence and more declared debt — never
halted. (OT sec 6: "En el peor caso la corrida termina con menos evidencia y
mas deuda declarada. NUNCA detenida, salvo mount_absent.")

  fs.* (salvo mount_absent) -> SKIP explicito con NO_CONSTA, deuda, AVANZA
  fs.mount_absent            -> INTERCAMBIO_SHARE_UNAVAILABLE, PARA  (unico que para)
  net.*                      -> NO_DISPONIBLE: entra el fallback de la escalera
  fmt.*                      -> evidencia del slot declarada insuficiente, AVANZA
  sem.*                      -> escala a T2; si T2 no: insuficiente, AVANZA
  UNMAPPED_CONDITION        -> escala a T2; si T2 no: insuficiente, AVANZA

This is the floor that guarantees G2 (no exception swallowed) and G5 (only
mount_absent stops).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from scripts.exception_taxonomy import CLASSES, UNMAPPED


# Action codes — stable vocabulary the runner switches on.
ADVANCE_WITH_DEBT = "AVANCE_CON_DEUDA"          # fs.*, fmt.*
ENTER_FALLBACK = "ENTRA_FALLBACK"                # net.*
ESCALATE_T2 = "ESCALA_T2"                        # sem.*, UNMAPPED (T2 may be absent in FASE 1)
HALT_RUN = "PARA_CORRIDA"                        # fs.mount_absent only

BLOCK_STATE_MOUNT = "RUNNER_BLOCKED_INTERCAMBIO_SHARE_UNAVAILABLE"

# Map clase -> (action, state, advance?). advance=False only for mount_absent.
_ACTIONS: dict[str, Tuple[str, str, bool]] = {}


def _register(family_or_class: str, action: str, state: str, advance: bool) -> None:
    _ACTIONS[family_or_class] = (action, state, advance)


# fs.* except mount_absent -> skip + NO_CONSTA + debt, ADVANCE
for _c in CLASSES:
    if _c.startswith("fs.") and _c != "fs.mount_absent":
        _register(_c, ADVANCE_WITH_DEBT, "EVIDENCIA_INSUFICIENTE_DEUDA", True)
# fs.mount_absent -> the ONLY halt
_register("fs.mount_absent", HALT_RUN, BLOCK_STATE_MOUNT, False)
# net.* -> fallback ladder enters
for _c in CLASSES:
    if _c.startswith("net."):
        _register(_c, ENTER_FALLBACK, "NO_DISPONIBLE", True)
# fmt.* -> insufficient evidence, advance
for _c in CLASSES:
    if _c.startswith("fmt."):
        _register(_c, ADVANCE_WITH_DEBT, "EVIDENCIA_INSUFICIENTE_DEUDA", True)
# sem.* + UNMAPPED -> escalate T2; if absent, advance with debt
for _c in CLASSES:
    if _c.startswith("sem.") or _c == UNMAPPED:
        _register(_c, ESCALATE_T2, "ESCALADO_T2_SI_DISPONIBLE_SI_NO_AVANZA", True)


@dataclass(frozen=True)
class DefaultAction:
    """The predeclared action for a class."""
    clase: str
    action: str              # ADVANCE_WITH_DEBT | ENTER_FALLBACK | ESCALATE_T2 | HALT_RUN
    state: str               # terminal/sub-state for the quality log
    advance: bool            # False only for mount_absent (G5)
    t2_required: bool        # True for sem.* and UNMAPPED (may be absent in FASE 1)


def action_for(clase: str) -> DefaultAction:
    """Return the declared default action for a class.

    Every class in CLASSES has one (G4). A class outside CLASSES is a bug; we
    treat it as UNMAPPED (escalate) rather than crash the instrumentation.
    """
    entry = _ACTIONS.get(clase)
    if entry is None:
        # Defensive: never crash the exception path. Escalate as UNMAPPED.
        entry = _ACTIONS[UNMAPPED]
        clase = UNMAPPED
    action, state, advance = entry
    return DefaultAction(
        clase=clase, action=action, state=state, advance=advance,
        t2_required=(action == ESCALATE_T2),
    )


def only_mount_absent_halts() -> bool:
    """G5 invariant: exactly one class halts, and it is fs.mount_absent."""
    halting = [c for c, (a, _, adv) in _ACTIONS.items() if not adv]
    return halting == ["fs.mount_absent"]


def every_class_has_action() -> bool:
    """G4 invariant: every class in CLASSES has a declared action."""
    return all(c in _ACTIONS for c in CLASSES)
