"""defect_class.py — classify the MEDIANO loop's defect into A or B.

OT section 4 D4 (MEDIANO). When the gate of a slot rejects, the DESTINATION
comes from the CLASS of the defect, which the auditor declares:

  clase A (consolidacion, trazabilidad) -> vuelve al ESCRITOR
  clase B (sustantivo del candidato)    -> vuelve al PRIMER SLOT DEL CICLO

The inventory confirms this A/B classification does NOT exist yet (new code).
The auditor declares the class; the runner routes by it. This keeps the rule
hard: 'ningun bucle re-corre trabajo cuya ENTRADA no cambio' — a class-A
defect means the INPUT (what the agents audited) is unchanged, only the
report was mis-written, so relaunching 9 agents would reproduce the same
findings for nothing. It goes back to the single writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class DefectClass(str, Enum):
    """The two MEDIANO classes. Long-loop (LARGO) defects are handled
    separately by loop_engine: they always go to slot 1."""
    A = "A"   # consolidation / traceability -> back to the writer
    B = "B"   # substantive candidate issue -> back to first slot of the cycle


# Keywords the auditor uses to declare the class (in the verdict/finding).
# These are matched against the auditor's `clase` or `summary` field.
_A_KEYWORDS = ("consolidacion", "trazabilidad", "tergiverso", "omito",
               "huerfano", "fabricacion", "consolidation", "traceability")
_B_KEYWORDS = ("sustantivo", "persiste", "no vio", "substantive",
               "enfoque", "criterio")


@dataclass(frozen=True)
class DefectVerdict:
    """The auditor's classification of a rejected candidate."""
    clase: DefectClass
    author: str            # who classified it (model/worker id)
    motivo: str            # why — recorded (REGLA DURA: reclasificacion con autor y motivo)
    target_slot: Optional[int] = None   # explicit override of destination, if any
    raw: dict[str, Any] | None = None

    @property
    def is_mediano_a(self) -> bool:
        return self.clase == DefectClass.A

    @property
    def is_mediano_b(self) -> bool:
        return self.clase == DefectClass.B


def classify_defect(
    *,
    auditor_clase: Optional[str] = None,
    auditor_summary: str = "",
    author: str = "unknown",
    target_slot: Optional[int] = None,
) -> DefectVerdict:
    """Classify a defect from the auditor's declaration.

    The auditor's explicit `clase` field wins if present ("A" or "B"). If not,
    we infer from the summary text. If both fail, default to B (substantive):
    sending a possibly-substantive defect back to the writer would waste a
    cycle, while sending a possibly-consolidation defect back to the cycle is
    just an extra cautious re-audit. B is the safer default for correctness.
    """
    motivo_parts: list[str] = []
    if auditor_clase:
        c = auditor_clase.strip().upper().rstrip(".")
        if c.startswith("A"):
            clase = DefectClass.A
            motivo_parts.append(f"auditor declaro clase A")
        elif c.startswith("B"):
            clase = DefectClass.B
            motivo_parts.append(f"auditor declaro clase B")
        else:
            clase = _infer_from_summary(auditor_summary, motivo_parts)
    else:
        clase = _infer_from_summary(auditor_summary, motivo_parts)

    if not motivo_parts:
        motivo_parts.append("no explicit declaration; defaulted conservatively")
    return DefectVerdict(
        clase=clase, author=author,
        motivo="; ".join(motivo_parts),
        target_slot=target_slot,
    )


def _infer_from_summary(summary: str, motivo_parts: list[str]) -> DefectClass:
    s = (summary or "").lower()
    if any(k in s for k in _A_KEYWORDS):
        motivo_parts.append(f"inferido A por palabras clave en: '{summary[:40]}'")
        return DefectClass.A
    if any(k in s for k in _B_KEYWORDS):
        motivo_parts.append(f"inferido B por palabras clave en: '{summary[:40]}'")
        return DefectClass.B
    # Conservative default: substantive. Re-auditing is safer than re-writing.
    motivo_parts.append("sin palabras clave; default B (sustantivo)")
    return DefectClass.B


def mediano_destination(
    verdict: DefectVerdict,
    *,
    writer_slot: int,
    cycle_first_slot: int,
) -> int:
    """Where a MEDIANO re-entry goes, by class.

    clase A -> writer_slot    (consolidation: the writer mis-reported)
    clase B -> cycle_first_slot (substantive: the candidate itself is wrong)

    `target_slot` (an explicit auditor override) wins, but only if it points
    to one of the two valid destinations — the auditor cannot route a MEDIANO
    loop to an arbitrary slot, that would bypass the no-overlap rule.
    """
    default = writer_slot if verdict.is_mediano_a else cycle_first_slot
    if verdict.target_slot is not None and verdict.target_slot in (writer_slot, cycle_first_slot):
        return verdict.target_slot
    return default
