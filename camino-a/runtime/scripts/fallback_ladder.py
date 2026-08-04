"""fallback_ladder.py — the fallback decision that does all the work.

OT section 4 D3. The distinction between NO_DISPONIBLE and CORRIO_Y_FALLO is
what makes the fallback ladder safe: a fallback must enter ONLY when the
primary never produced a valid artifact, never when the primary produced a
broken one.

Resolution is FILESYSTEM-DRIVEN via the atomic-write primitive (reused, NOT
rewritten — drive_fuse.py:40 fuse_safe_write):

  NO_DISPONIBLE          (429, 5xx, connection timeout: never ran)
     -> final artifact ABSENT, no abort marker        -> fallback ENTERS

  CORRIO_Y_FALLO         (attempted and produced something broken/aborted)
     -> orphan .partial/.tmp present OR explicit abort marker
     -> fallback STOPS (re-running a broken writer is not the answer)

  ESCRIBIO_PERO_NO_PASA_GATE
     -> final artifact PRESENT but the gate is red    -> NOT failover material,
                                                          this is LOOP material

The runner writes artifacts atomically: a write that completes is real; a
write that does not complete leaves no final file (only a tmp that
fuse_safe_write cleans up on failure, or a .partial marker for in-progress).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol

# Reused primitive — DO NOT reimplement. Declared in the report with its path.
from scripts.drive_fuse import fuse_safe_write  # noqa: E402  (drive_fuse.py:40)


class Outcome(str, Enum):
    NO_DISPONIBLE = "NO_DISPONIBLE"
    CORRIO_Y_FALLO = "CORRIO_Y_FALLO"
    ESCRIBIO_PERO_NO_PASA_GATE = "ESCRIBIO_PERO_NO_PASA_GATE"


# File conventions. The final artifact is the committed file; .partial marks an
# in-progress (or abandoned) write; .abort is an explicit abort marker.
PARTIAL_SUFFIX = ".partial"
ABORT_SUFFIX = ".abort"


class Gate(Protocol):
    """A gate decides if a completed artifact passes quality checks."""
    def evaluate(self, artifact_path: Path) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class ClassifiedOutcome:
    outcome: Outcome
    final_path: Optional[Path]
    reason: str
    fallback_enters: bool            # True only for NO_DISPONIBLE
    is_loop_material: bool           # True only for ESCRIBIO_PERO_NO_PASA_GATE

    @property
    def label(self) -> str:
        return self.outcome.value


def _final_exists(final_path: Path) -> bool:
    return final_path.is_file() and final_path.stat().st_size > 0


def _partial_exists(final_path: Path) -> bool:
    """A .partial (or stray tmp) without a final = an aborted/failed run."""
    if (final_path.with_name(final_path.name + PARTIAL_SUFFIX)).is_file():
        return True
    # Stray tmp files from a crashed fuse_safe_write attempt. These are cleaned
    # by fuse_safe_write's `finally`, but a hard crash (OOM, SIGKILL) can leave
    # them. Their presence means the run attempted and died.
    for tmp in final_path.parent.glob(f".{final_path.name}.*.tmp"):
        return True
    return False


def _abort_marker_exists(final_path: Path) -> bool:
    return (final_path.with_name(final_path.name + ABORT_SUFFIX)).is_file()


def classify_outcome(
    final_path: Path,
    *,
    gate: Optional[Gate] = None,
    abort_signal: Optional[bool] = None,
) -> ClassifiedOutcome:
    """Classify the outcome of a single route invocation.

    final_path : where the committed artifact SHOULD be.
    gate       : optional gate evaluated ONLY when the final exists. Without a
                 gate, a present final is treated as success (no failover, no
                 loop) — the caller wires the gate for write/approve puestos.
    abort_signal: explicit in-band signal (e.g. an exception class caught by
                 the caller) that the invocation aborted. Maps to CORRIO_Y_FALLO.
    """
    # 1. Explicit abort wins: the invocation started and gave up.
    if abort_signal is not None and abort_signal:
        return ClassifiedOutcome(
            outcome=Outcome.CORRIO_Y_FALLO,
            final_path=None,
            reason="abort_signal: la invocacion aborto explicitamente",
            fallback_enters=False,
            is_loop_material=False,
        )
    if _abort_marker_exists(final_path):
        return ClassifiedOutcome(
            outcome=Outcome.CORRIO_Y_FALLO,
            final_path=None,
            reason=f"marcador {ABORT_SUFFIX} presente: corrio y fallo",
            fallback_enters=False,
            is_loop_material=False,
        )

    # 2. Final artifact present -> the run completed. Either it passes the gate
    #    (success) or it does not (loop material, NEVER failover).
    if _final_exists(final_path):
        if gate is None:
            return ClassifiedOutcome(
                outcome=Outcome.ESCRIBIO_PERO_NO_PASA_GATE,
                final_path=final_path,
                reason="final presente sin gate definido: tratar como material de bucle",
                fallback_enters=False,
                # Without a gate we cannot call it success; be conservative and
                # route it to the loop. The caller SHOULD supply a gate.
                is_loop_material=True,
            )
        passed, why = gate.evaluate(final_path)
        if passed:
            # Not a real "outcome" for the ladder: success has no fallback
            # decision. We model it as passing-gate with no failover and no
            # loop, so the caller can branch uniformly.
            return ClassifiedOutcome(
                outcome=Outcome.ESCRIBIO_PERO_NO_PASA_GATE,
                final_path=final_path,
                reason=f"gate OK: {why}",
                fallback_enters=False,
                is_loop_material=False,
            )
        return ClassifiedOutcome(
            outcome=Outcome.ESCRIBIO_PERO_NO_PASA_GATE,
            final_path=final_path,
            reason=f"gate rojo: {why}",
            fallback_enters=False,
            is_loop_material=True,
        )

    # 3. No final. Distinguish NO_DISPONIBLE (never ran) from CORRIO_Y_FALLO
    #    (ran and left a corpse).
    if _partial_exists(final_path):
        return ClassifiedOutcome(
            outcome=Outcome.CORRIO_Y_FALLO,
            final_path=None,
            reason=f"{PARTIAL_SUFFIX}/tmp huerfano: intento producir algo y fallo",
            fallback_enters=False,
            is_loop_material=False,
        )

    # 4. Nothing at all: the provider was unavailable (429/5xx/timeout) and the
    #    invocation never produced any artifact. THIS is the fallback trigger.
    return ClassifiedOutcome(
        outcome=Outcome.NO_DISPONIBLE,
        final_path=None,
        reason="ausencia del archivo final: nunca corrio (429/5xx/timeout de conexion)",
        fallback_enters=True,
        is_loop_material=False,
    )


# ----- atomic write helpers built on the reused primitive ----- #

def commit_artifact(final_path: Path, content: bytes | str) -> Path:
    """Atomically commit a successful artifact.

    Thin wrapper over fuse_safe_write (drive_fuse.py:40). Returns the final
    path. The whole point of routing through here is that the runner has ONE
    atomic-write primitive, declared by its original path in the report.
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fuse_safe_write(final_path, content)
    return final_path


def mark_partial(final_path: Path, content: bytes | str = "") -> Path:
    """Mark an in-progress write so a crash classifies as CORRIO_Y_FALLO."""
    partial = final_path.with_name(final_path.name + PARTIAL_SUFFIX)
    fuse_safe_write(partial, content)
    return partial


def clear_partial(final_path: Path) -> None:
    partial = final_path.with_name(final_path.name + PARTIAL_SUFFIX)
    partial.unlink(missing_ok=True)


def mark_abort(final_path: Path, reason: str) -> Path:
    """Mark that an invocation started and deliberately aborted.

    Used when the caller catches an exception that means 'produced something
    broken' rather than 'never ran'.
    """
    abort = final_path.with_name(final_path.name + ABORT_SUFFIX)
    fuse_safe_write(abort, reason)
    return abort


def clear_abort(final_path: Path) -> None:
    final_path.with_name(final_path.name + ABORT_SUFFIX).unlink(missing_ok=True)


@dataclass
class AlwaysPassGate:
    """Trivial gate: passes everything. For puestos without a quality gate."""
    def evaluate(self, artifact_path: Path) -> tuple[bool, str]:
        return True, "always-pass (sin gate definido para este puesto)"


@dataclass
class AlwaysFailGate:
    """Trivial gate: fails everything. For tests only."""
    def evaluate(self, artifact_path: Path) -> tuple[bool, str]:
        return False, "always-fail (gate de prueba)"
