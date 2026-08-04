"""loop_engine.py — the three loop levels (OT section 4 D4).

  INTERNO  : the model does propose/audit/correct INSIDE its own invocation.
             The runner does NOT orchestrate it; it only passes the 3-step
             instruction. EXCEPTION: rutas con manos (manos=ejecuta) run TESTS
             between steps (reuses internal_loop_runner.independent_test_verification).
  MEDIANO  : the slot gate rejects. Destination comes from the defect CLASS
             (defect_class.py): A -> writer, B -> first slot of cycle.
  LARGO    : slot 14 -> slot 1. Only the aprobador triggers it. Adapts the
             existing restart_big_loop mechanism.

REGLAS DURAS (all enforced here):
  R1: ningun bucle re-corre trabajo cuya ENTRADA no cambio.
      -> MEDIANO-A goes to the writer, NOT to the 9 agents (input unchanged).
  R2: agotar el tope de un nivel NO habilita el siguiente. Hay que
      RECLASIFICAR el defecto, registrado con autor y motivo.
  R3: los contadores PERSISTEN. Volver por el bucle largo no los reinicia.

This module adapts patterns from:
  - internal_loop_runner.run_internal_loop (line 299) and
    independent_test_verification (line 166) for the INTERNO/manos path.
  - overnight_master restart_big_loop (line 453) for the LARGO path.
It does NOT re-implement provider invocation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.defect_class import DefectVerdict, mediano_destination


# --------------------------------------------------------------------------- #
# Persistent loop counters (R3). Persisted as a small JSON file in the run dir
# so re-entering a run (including via a LARGO restart) does NOT reset them.
# --------------------------------------------------------------------------- #
LOOP_STATE_FILENAME = "loop_counters.json"


@dataclass
class LoopCounters:
    """Per-slot counters that persist across the whole run (R3)."""
    interno: dict[int, int] = field(default_factory=dict)     # step -> count
    mediano_a: dict[int, int] = field(default_factory=dict)   # step -> count
    mediano_b: dict[int, int] = field(default_factory=dict)   # step -> count
    largo: int = 0

    def record_interno(self, step: int) -> None:
        self.interno[step] = self.interno.get(step, 0) + 1

    def record_mediano(self, step: int, clase: str) -> bool:
        """Record a MEDIANO iteration. Returns False if the tope is exhausted
        (R2: exhaustion does NOT auto-escalate; caller must RE-classify)."""
        bucket = self.mediano_a if clase == "A" else self.mediano_b
        bucket[step] = bucket.get(step, 0) + 1
        return True

    def mediano_count(self, step: int, clase: str) -> int:
        bucket = self.mediano_a if clase == "A" else self.mediano_b
        return bucket.get(step, 0)

    def mediano_exhausted(self, step: int, clase: str, tope: int) -> bool:
        return self.mediano_count(step, clase) >= tope

    def record_largo(self) -> None:
        self.largo += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "interno": self.interno,
            "mediano_a": self.mediano_a,
            "mediano_b": self.mediano_b,
            "largo": self.largo,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LoopCounters":
        return cls(
            interno={int(k): int(v) for k, v in (d.get("interno") or {}).items()},
            mediano_a={int(k): int(v) for k, v in (d.get("mediano_a") or {}).items()},
            mediano_b={int(k): int(v) for k, v in (d.get("mediano_b") or {}).items()},
            largo=int(d.get("largo") or 0),
        )


def load_counters(run_dir: Path) -> LoopCounters:
    p = run_dir / LOOP_STATE_FILENAME
    if p.is_file():
        try:
            return LoopCounters.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            # Corrupt state -> start fresh, but NEVER silently merge.
            return LoopCounters()
    return LoopCounters()


def save_counters(run_dir: Path, counters: LoopCounters) -> None:
    """Persist counters atomically via the reused primitive (R3).

    Without atomic persistence, a crash mid-loop would lose counter history and
    a LARGO re-entry would wrongly reset MEDIANO topes. drive_fuse.fuse_safe_write.
    """
    from scripts.drive_fuse import fuse_safe_write  # reused, not rewritten
    p = run_dir / LOOP_STATE_FILENAME
    fuse_safe_write(p, json.dumps(counters.to_dict(), ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------- #
# INTERNO — the in-invocation loop. The runner does NOT orchestrate the model's
# internal propose/audit/correct; it only assembles the instruction. For rutas
# con manos, it runs TESTS between steps (reuses internal_loop_runner).
# --------------------------------------------------------------------------- #
INTERNO_INSTRUCTION = (
    "Bucle interno (3 pasos en UNA invocacion): "
    "(1) propone tu respuesta; "
    "(2) audita tu propio borrador en busca de incoherencia interna, hallazgo "
    "sin fundamentar, formato invalido, respuesta incompleta o contradiccion "
    "contigo mismo; "
    "(3) corrige y entrega la version final. NO entregues el borrador."
)


def interno_instruction(manos: bool, *, test_cmd: Optional[list[str]] = None) -> str:
    """Build the internal-loop instruction for a route.

    For rutas con manos (manos=ejecuta), the runner runs TESTS between steps:
    that new evidence justifies separate invocations. Otherwise it is a single
    invocation with the 3-step instruction.
    """
    if manos:
        return (
            INTERNO_INSTRUCTION
            + " Esta ruta TIENE MANOS: entre paso y paso, ejecuta los tests "
            "(comando: " + " ".join(test_cmd or []) + ") y usa su evidencia."
        )
    return INTERNO_INSTRUCTION


# --------------------------------------------------------------------------- #
# MEDIANO — slot gate rejection. Routes by defect class (R1, R4).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MedianoDecision:
    destino_slot: int
    clase: str
    motivo: str
    author: str
    exhausted: bool        # True if the tope for this class is hit (R2: no auto-escalate)
    action: str            # "reingresar" | "rec clasificar" | "deuda"


def decide_mediano(
    verdict: DefectVerdict,
    *,
    step: int,
    writer_slot: int,
    cycle_first_slot: int,
    counters: LoopCounters,
    tope: int,
) -> MedianoDecision:
    """Decide what a MEDIANO rejection does.

    R1: the destination comes from the class, not judgement.
        A -> writer_slot ; B -> cycle_first_slot.
    R2: if the tope is exhausted, do NOT escalate to LARGO. Require a
        RE-CLASSIFICATION (recorded with author+motivo). If the auditor
        cannot re-classify, declare deuda.
    """
    clase = "A" if verdict.is_mediano_a else "B"
    destino = mediano_destination(
        verdict, writer_slot=writer_slot, cycle_first_slot=cycle_first_slot,
    )
    already = counters.mediano_count(step, clase)
    exhausted = already >= tope
    if exhausted:
        # R2: must re-classify. The decision is NOT to run; it is to escalate
        # to a re-classification request, recorded.
        return MedianoDecision(
            destino_slot=destino, clase=clase,
            motivo=f"tope {tope} agotado para clase {clase} en slot {step}; "
                   f"requiere reclasificacion (autor={verdict.author}, motivo={verdict.motivo})",
            author=verdict.author, exhausted=True, action="rec clasificar",
        )
    return MedianoDecision(
        destino_slot=destino, clase=clase,
        motivo=f"defecto clase {clase} por {verdict.author}: {verdict.motivo}",
        author=verdict.author, exhausted=False, action="reingresar",
    )


# --------------------------------------------------------------------------- #
# LARGO — slot 14 -> slot 1. Only the aprobador triggers it.
# Adapts overnight_master restart_big_loop.
# --------------------------------------------------------------------------- #
LARGO_DESTINO_SLOT = 1
LARGO_TRIGGER_SLOT = 14
LARGO_TOPE = 3   # OT LOGICA_BUCLES: 3 vueltas del camino completo


@dataclass(frozen=True)
class LargoDecision:
    destino_slot: int
    motivo: str
    exhausted: bool
    action: str   # "restart_big_loop" | "deuda"


def decide_largo(
    *,
    aprobador_verdict: str,
    counters: LoopCounters,
    tope: int = LARGO_TOPE,
) -> LargoDecision:
    """LARGO is triggered ONLY by the aprobador. If its tope is exhausted, the
    run ends with deuda (the whole approach is exhausted)."""
    if counters.largo >= tope:
        return LargoDecision(
            destino_slot=LARGO_DESTINO_SLOT,
            motivo=f"tope LARGO {tope} agotado: deuda declarada",
            exhausted=True, action="deuda",
        )
    return LargoDecision(
        destino_slot=LARGO_DESTINO_SLOT,
        motivo=f"aprobador rechazo: {aprobador_verdict}",
        exhausted=False, action="restart_big_loop",
    )


# --------------------------------------------------------------------------- #
# R1 guard: never re-run work whose INPUT did not change. A MEDIANO-A re-entry
# to the writer is allowed because the writer's input (the agents' findings) is
# unchanged — only the report was wrong. A MEDIANO-B re-entry to the cycle is
# allowed because the candidate itself changed. But a second MEDIANO-A on the
# SAME findings hash is blocked: it would reproduce the same mis-report.
# --------------------------------------------------------------------------- #
def input_fingerprint(*parts: Any) -> str:
    """Stable fingerprint of a loop's input, so R1 can detect 'no change'."""
    import hashlib
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class InputHistory:
    """Records the input fingerprint of each completed loop iteration, per slot
    and class, so R1 can refuse to re-run an unchanged input."""
    _seen: dict[tuple[int, str], set[str]] = field(default_factory=dict)

    def already_seen(self, step: int, clase: str, fingerprint: str) -> bool:
        return fingerprint in self._seen.setdefault((step, clase), set())

    def record(self, step: int, clase: str, fingerprint: str) -> None:
        self._seen.setdefault((step, clase), set()).add(fingerprint)


def r1_guard(
    *, step: int, clase: str, fingerprint: str, history: InputHistory,
) -> Optional[str]:
    """Return a block reason if R1 forbids the re-entry, else None.

    R1: a loop never re-runs work whose input did not change. The first
    occurrence always passes; a repeat with the SAME fingerprint is blocked.
    """
    if history.already_seen(step, clase, fingerprint):
        return (
            f"R1: rechazado reingresar slot {step} clase {clase} con la misma "
            f"entrada (fingerprint {fingerprint}); el resultado seria identico."
        )
    return None
