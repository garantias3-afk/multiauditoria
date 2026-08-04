"""contradiccion.py — classify tabla-vs-canon disagreements (OT section 8).

Decision by Mariano (not the executor's): classify FIRST, then act. The
destination comes from the CLASS, not moment-to-moment judgement.

  CLASE 1 — ASIGNACION: who occupies a puesto / which routes form an ola /
  fallback order / a role / a route present in the tabla and absent in canon.
       -> GANA LA TABLA. NO bloquea. Se registra artefacto
          CONTRADICCION_TABLA_VS_CANON y se sigue.

  CLASE 2 — REGLA: a restriction the tabla cannot override — permission
  booleans, numeric limits, circuit-breaker definitions, exclusion rules.
       -> GANA EL CANON. PARA. -> RUNNER_BLOCKED_CONTRADICCION, sube a Mariano.

Mechanical rule (no judgement):
  - canon field that is a list of routes, role name, or model_id -> ASIGNACION
  - canon field that is a permission boolean, numeric limit, or circuit
    breaker definition -> REGLA
  - route present in tabla, absent in canon                  -> ASIGNACION
  - field that fits neither                                   -> REGLA
    (when in doubt, the conservative option is to BLOCK, not proceed)

The artefact MUST appear in the VERDICT of the run, never buried in a log.
The runner NEVER resolves a CLASE 2 conflict on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


CLASE_ASIGNACION = "ASIGNACION"
CLASE_REGLA = "REGLA"

ARTIFACT_NAME = "CONTRADICCION_TABLA_VS_CANON"
BLOCK_STATE = "RUNNER_BLOCKED_CONTRADICCION"

# Canon field-name heuristics. These are deliberately conservative: anything
# not clearly ASIGNACION defaults to REGLA (block).
_ASSIGNMENT_SUBSTRINGS = (
    "route", "routes", "model_id", "modelo", "provider", "role", "rol",
    "family", "familia", "worker", "workers", "slot", "puesto", "ola",
    "group", "grupo", "assignment", "asignacion",
    "order", "orden", "fallback",   # fallback ORDER / fallback chain = assignment
)
# Substrings that unambiguously signal a RULE (permission/limit/breaker).
_RULE_SUBSTRINGS = (
    "authoriz", "permit", "allow", "forbid", "prohibit", "never",
    "max_iter", "max_", "limit", "tope", "concurrenc", "concurrency",
    "breaker", "circuit", "skip_remaining", "exclusiv", "mutex", "lock",
    "throttle", "quota",
)


@dataclass(frozen=True)
class Conflict:
    """A single tabla-vs-canon disagreement, classified."""
    canon_field: str
    tabla_value: Any
    canon_value: Any
    clase: str          # ASIGNACION | REGLA
    where: str = ""     # step / puesto / route_id for human readability
    note: str = ""

    def as_artifact(self) -> dict[str, Any]:
        return {
            "artifact": ARTIFACT_NAME,
            "clase": self.clase,
            "canon_field": self.canon_field,
            "tabla_value": _safe(self.tabla_value),
            "canon_value": _safe(self.canon_value),
            "where": self.where,
            "note": self.note,
            # Resolution is mechanical, recorded for the verdict.
            "resolucion": (
                "tabla_gana_sigue" if self.clase == CLASE_ASIGNACION
                else "canon_gana_bloquea"
            ),
        }


@dataclass(frozen=True)
class ConflictVerdict:
    """Aggregate of all conflicts detected in a run, for the VERDICT."""
    asignacion: list[Conflict] = field(default_factory=list)   # proceed, recorded
    regla: list[Conflict] = field(default_factory=list)        # must block

    @property
    def blocks(self) -> bool:
        return bool(self.regla)

    @property
    def state(self) -> str:
        return BLOCK_STATE if self.blocks else "PROCEDE_CON_DEUDAS_DE_ASIGNACION"

    def all_artifacts(self) -> list[dict[str, Any]]:
        return [c.as_artifact() for c in (*self.asignacion, *self.regla)]

    def merge(self, other: "ConflictVerdict") -> "ConflictVerdict":
        return ConflictVerdict(
            asignacion=[*self.asignacion, *other.asignacion],
            regla=[*self.regla, *other.regla],
        )


def _safe(value: Any) -> str:
    try:
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(map(str, value)) + "]"
        return str(value)
    except Exception:
        return "<unrepresentable>"


def classify_field(canon_field: str, *, hint: Optional[str] = None) -> str:
    """Mechanical classification of a canon field name.

    Hint lets callers supply extra context (e.g. 'route_list', 'permission')
    when the name alone is ambiguous. Unknown => REGLA (conservative block).
    """
    name = str(canon_field or "").lower()

    if hint:
        h = hint.lower()
        if "asign" in h or "route" in h or "role" in h:
            return CLASE_ASIGNACION
        if "regla" in h or "rule" in h or "permission" in h or "limit" in h:
            return CLASE_REGLA

    # Explicit rule substrings win: a field named "max_routes" is a LIMIT on
    # routes, not an assignment of routes.
    for sub in _RULE_SUBSTRINGS:
        if sub in name:
            return CLASE_REGLA
    for sub in _ASSIGNMENT_SUBSTRINGS:
        if sub in name:
            return CLASE_ASIGNACION
    return CLASE_REGLA   # unknown => conservative block


def classify_value_type(tabla_value: Any, canon_value: Any) -> str:
    """Type-driven classification when the field name is inconclusive.

    A boolean or numeric value disagreement is almost always a RULE
    (permission/limit). A string/list/None disagreement is almost always an
    ASIGNACION (who/what). Used together with classify_field, the most
    restrictive wins: if EITHER says REGLA, it is REGLA.
    """
    if isinstance(tabla_value, bool) or isinstance(canon_value, bool):
        return CLASE_REGLA
    if isinstance(tabla_value, (int, float)) and not isinstance(tabla_value, bool):
        return CLASE_REGLA
    if isinstance(canon_value, (int, float)) and not isinstance(canon_value, bool):
        return CLASE_REGLA
    return CLASE_ASIGNACION


def make_conflict(
    canon_field: str,
    tabla_value: Any,
    canon_value: Any,
    *,
    where: str = "",
    note: str = "",
    hint: Optional[str] = None,
) -> Conflict:
    """Classify a disagreement and build the Conflict.

    Combines name-based and value-type-based classification. The MOST
    RESTRICTIVE result wins: if either classifier says REGLA, it is REGLA.
    This implements "ante la duda, bloquear".
    """
    by_name = classify_field(canon_field, hint=hint)
    by_type = classify_value_type(tabla_value, canon_value)
    if CLASE_REGLA in (by_name, by_type):
        # If name clearly says ASIGNACION but value type says REGLA, prefer
        # REGLA unless the name hint explicitly forces ASIGNACION.
        if by_name == CLASE_ASIGNACION and hint and "asign" in hint.lower():
            clase = CLASE_ASIGNACION
        else:
            clase = CLASE_REGLA
    else:
        clase = CLASE_ASIGNACION
    return Conflict(
        canon_field=canon_field,
        tabla_value=tabla_value,
        canon_value=canon_value,
        clase=clase,
        where=where,
        note=note or f"classified by name={by_name}, type={by_type}",
    )


def route_present_in_tabla_absent_in_canon(route_id: str, *, where: str = "") -> Conflict:
    """The canonical ASIGNACION case: a new route the canon hasn't absorbed.

    OT section 8: 'Ruta presente en la tabla y ausente del canon -> ASIGNACION
    -> gana la tabla. Las rutas nuevas aparecen constantemente: eso es el
    diseno, no un error.'
    """
    return Conflict(
        canon_field="route_id",
        tabla_value=route_id,
        canon_value="<ausente en canon>",
        clase=CLASE_ASIGNACION,
        where=where,
        note="ruta nueva de tabla, no absorbida por canon aun",
    )


def add_to_verdict(verdict: ConflictVerdict, conflict: Conflict) -> ConflictVerdict:
    """Return a new verdict with the conflict recorded in its bucket."""
    if conflict.clase == CLASE_REGLA:
        return ConflictVerdict(
            asignacion=list(verdict.asignacion),
            regla=[*verdict.regla, conflict],
        )
    return ConflictVerdict(
        asignacion=[*verdict.asignacion, conflict],
        regla=list(verdict.regla),
    )
