#!/usr/bin/env python3
"""gen_camino_n_config.py — project the CAMINO_N tabla (xlsx) to a runtime JSON.

FASE 1, M1+M2 (OT RUNNER + MIGRACION). The tabla is the editable SOURCE OF
TRUTH (Mariano edits cells); this JSON is its deterministic PROJECTION in the
format the runtime already reads. Mirrors the shape of
CANON_WORKFLOW_SLOTS.v1.json (slots: cycle/role/loops/correction_policy/routes)
and config/provider.policy.json, but lives in its OWN file so the shared canon
of the 14 slots is never mixed with CAMINO_N (OT prohibition sec 10).

Determinism (G5): NO timestamps, NO run-dependent fields, sorted keys, stable
ordering of derived lists (by step -> orden -> route_id). Regenerating twice
from the same tabla yields byte-identical output (same sha256). Reuses
tabla_loader.load_tabla for parsing — does not re-parse the xlsx.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tabla_loader import (  # noqa: E402
    NO_CONSTA, RouteAssignment, TablaConfig, load_tabla,
)

# Fixed schema/canon version stamps for the projection. These are CONSTANTS,
# not timestamps: changing them is a deliberate version bump, so the output
# stays deterministic across regenerations within a version.
SCHEMA_VERSION = "camino_n_assignments.v1"
# v1.2: the projection now reads the CAMINO_N_v1_2 assignments sheet (the
# v1.2 tabla replaced it; LEEME declares the context sheets stay v1.1) and
# projects puestos. Deliberate version bump, per the determinism contract:
# output stays byte-identical across regenerations within a version.
CANON_VERSION = "camino_n.projection.v1.2"

DEFAULT_OUTPUT = ROOT / "config" / "camino_n.assignments.json"

# Cycles per the tabla (CAMINO_N_v1_1 sheet). Mirrors CANON_WORKFLOW_SLOTS
# cycles shape, derived deterministically from the assignments.
CYCLE_ORDER = ("A", "B", "C", "FINAL")


def _slot_key(a: RouteAssignment) -> tuple:
    """Stable sort key for an assignment: step, then orden, then route_id.

    Sorting by this key makes the routes list inside each slot deterministic
    regardless of row order in the xlsx.
    """
    return (a.step, a.orden, a.route_id or "")


def _build_models(cfg: TablaConfig) -> dict[str, Any]:
    """Project the MODELOS sheet -> a stable dict keyed by route_id.

    Sorted by route_id. Mirrors the route-record style of
    CANON_PROVIDER_MODEL_ROUTES.v1.json (one record per route).
    """
    out: dict[str, Any] = {}
    for route_id in sorted(cfg.models):
        m = cfg.models[route_id]
        # Only stable, meaning-bearing fields. No latency samples (those are
        # telemetry, not config) — but timeout_s IS config.
        out[route_id] = {
            "modelo_exacto": m.modelo_exacto,
            "provider_id": m.provider_id,
            "provider_name": m.provider_name,
            "cost_class": m.cost_class,
            "familia": m.familia,
            "timeout_s": m.timeout_s,
            "manos": m.manos,
            "modo_agente": m.modo_agente,
        }
    return out


# v1.2b prose decision, declared in the CAMINO_N_v1_2 sheet itself (slot 6
# row note and the "STOP Y BLOCK REVISADOS" section): "v1.2b: ESCALATE_HUMAN
# -> BLOCK". The LOOPS sheet is v1.1 context and still says escalate_human
# for step 6; per MEGA-OT-8 rule 3.2 the DECLARED TEXT WINS. The divergent
# cell (LOOPS, step 6, al_agotarse=escalate_human) is recorded in
# camino-n/DECISIONES_PENDIENTES.md. Keyed by step.
POLICY_OVERRIDES_V1_2B: dict[int, str] = {6: "block"}


def _slot_correction_policy(step: int, loop: Any) -> str:
    if step in POLICY_OVERRIDES_V1_2B:
        return POLICY_OVERRIDES_V1_2B[step]
    if loop:
        al = (loop.al_agotarse or "").strip().lower()
        return al if al else "advance_with_debt"
    return "NO_BLOQUEA"


def _is_human_checkpoint(rows: list[RouteAssignment]) -> bool:
    """Human points per the v1.2 prose (CAMINO_N_v1_2 sheet, literal:
    "UNICA INTERVENCION HUMANA: EL SLOT 14 ... Quedan dos: la cosecha manual
    del slot 2, que es humana por definicion, y el aprobador del slot 14").

    Derived rule: a slot is a human checkpoint when it has NO active routes
    (manual harvest) or when any of its rows declares ESCALATE_HUMAN (the
    approver). Empty route_id ALONE is not a checkpoint: the previous
    heuristic wrongly flagged slot 12's mechanical-axis floor row and
    missed slot 14, whose rows all carry routes.
    """
    if not any(a.is_active for a in rows):
        return True
    return any(
        a.on_unavailable.strip().upper() == "ESCALATE_HUMAN" for a in rows)


def _route_entry(a: RouteAssignment) -> dict[str, Any]:
    entry = {
        "route_id": a.route_id,
        "orden": a.orden,
        "on_unavailable": a.on_unavailable,
        "fallback_real": a.fallback_real or None,
    }
    # Keep the note only where it carries a condition (condicional).
    if a.tipo_ruta == "condicional" and a.notas:
        entry["condicion"] = a.notas
    return entry


def _build_puestos(rows: list[RouteAssignment]) -> dict[str, Any]:
    """Group a slot's rows by puesto (v1.2 slots can have several: e.g.
    slot 12 planificador/agentes/escritor, slot 14 auditoria/aprobador).
    Inactive rows (empty route_id) are excluded from the route lists."""
    by_puesto: dict[str, list[RouteAssignment]] = {}
    for a in rows:
        by_puesto.setdefault(a.puesto, []).append(a)
    puestos: dict[str, Any] = {}
    for puesto in sorted(by_puesto):
        by_tipo: dict[str, list[dict[str, Any]]] = {}
        for a in sorted(by_puesto[puesto], key=_slot_key):
            if not a.is_active:
                continue
            by_tipo.setdefault(a.tipo_ruta, []).append(_route_entry(a))
        puestos[puesto] = {
            "routes_by_tipo": {t: by_tipo[t] for t in sorted(by_tipo)},
            "routes": sorted(
                {e["route_id"] for entries in by_tipo.values() for e in entries}),
        }
    return puestos


def _build_slots(cfg: TablaConfig) -> dict[str, Any]:
    """Project the assignments sheet -> slots dict mirroring
    CANON_WORKFLOW_SLOTS, plus the per-puesto structure.

    Each slot: cycle, role (first puesto, compat shape), loops (from LOOPS
    sheet, nullable), correction_policy (loop's al_agotarse, with the v1.2b
    overrides), human_checkpoint (derived per v1.2 prose), routes grouped
    by tipo_ruta (flattened across puestos, compat shape) and `puestos`
    with the per-puesto grouping.
    """
    # Group assignments by step.
    by_step: dict[int, list[RouteAssignment]] = {}
    for a in cfg.assignments:
        by_step.setdefault(a.step, []).append(a)

    slots: dict[str, Any] = {}
    for step in sorted(by_step):
        rows = sorted(by_step[step], key=_slot_key)
        # Slot-level fields come from the first row (they share step/ciclo
        # in a well-formed tabla; we take the first rather than guessing).
        first = rows[0]
        loop = cfg.loop_for(step)
        correction_policy = _slot_correction_policy(step, loop)
        if loop:
            loops_field: Any = {
                "nivel": "slot",
                "tope_ejec": loop.tope_ejec,
                "vuelve_a": loop.vuelve_a,
                "clase_que_dispara": loop.clase_que_dispara or None,
                "contador_persiste": loop.contador_persiste,
            }
            if loop.interno_pasos and loop.interno_modo:
                loops_field["interno"] = {
                    "pasos": loop.interno_pasos,
                    "modo": loop.interno_modo,
                }
        else:
            loops_field = None

        # Slot-level routes grouped by tipo_ruta, deterministically ordered
        # (flattened across puestos; `puestos` carries the structure).
        by_tipo: dict[str, list[dict[str, Any]]] = {}
        for a in rows:
            if not a.is_active:
                continue
            by_tipo.setdefault(a.tipo_ruta, []).append(_route_entry(a))

        slot_obj: dict[str, Any] = {
            "cycle": first.ciclo,
            "role": first.puesto,
            "capacidades": first.capacidades,
            "loops": loops_field,
            "correction_policy": correction_policy,
            "human_checkpoint": _is_human_checkpoint(rows),
            "puestos": _build_puestos(rows),
            "routes_by_tipo": {
                t: by_tipo[t] for t in sorted(by_tipo)
            },
        }
        # Also expose a flat routes list (route_ids only) like the canon, for
        # any consumer that wants the simple shape.
        flat = [e["route_id"] for entries in by_tipo.values() for e in entries]
        slot_obj["routes"] = sorted(set(flat))
        slots[str(step)] = slot_obj
    return slots


def _build_cycles(cfg: TablaConfig) -> dict[str, list[int]]:
    """Derive cycles -> [steps] deterministically from assignments."""
    cycles: dict[str, list[int]] = {}
    for a in cfg.assignments:
        cycles.setdefault(a.ciclo, [])
        if a.step not in cycles[a.ciclo]:
            cycles[a.ciclo].append(a.step)
    # Sort steps within each cycle; order cycles canonically.
    ordered: dict[str, list[int]] = {}
    for c in CYCLE_ORDER:
        if c in cycles:
            ordered[c] = sorted(set(cycles[c]))
    # Any cycle not in CYCLE_ORDER (defensive) appended alphabetically.
    for c in sorted(set(cycles) - set(CYCLE_ORDER)):
        ordered[c] = sorted(set(cycles[c]))
    return ordered


def build_projection(cfg: TablaConfig) -> dict[str, Any]:
    """Build the full deterministic projection dict from a loaded tabla."""
    return {
        "schema_version": SCHEMA_VERSION,
        "canon_version": CANON_VERSION,
        # NO updated_utc on purpose: a timestamp would break G5 round-trip.
        # The sheet actually read (v1.2 preferred; synthetic configs fall
        # back to the historical name).
        "source_tabla_sheet": cfg.sheet_camino or "CAMINO_N_v1_1",
        "cycles": _build_cycles(cfg),
        "slots": _build_slots(cfg),
        "models": _build_models(cfg),
    }


def serialize(projection: dict[str, Any]) -> str:
    """Serialize deterministically: sorted keys, fixed separators, trailing NL.

    This is the function the round-trip test hashes; it MUST be stable."""
    return json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_of(projection: dict[str, Any]) -> str:
    return hashlib.sha256(serialize(projection).encode("utf-8")).hexdigest()


def generate(tabla_path: Path, output: Path | None = None) -> tuple[Path, str]:
    """Load tabla, build projection, write atomically to `output`.

    Returns (written_path, sha256). Reuses fuse_safe_write so a crash mid-write
    never leaves a half-written config (drive_fuse.py:40, reused not rewritten).
    """
    from scripts.drive_fuse import fuse_safe_write
    cfg = load_tabla(tabla_path)
    projection = build_projection(cfg)
    out = output or DEFAULT_OUTPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    fuse_safe_write(out, serialize(projection))
    return out, sha256_of(projection)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate config/camino_n.assignments.json from the tabla")
    p.add_argument("--tabla", required=True, help="Path to TABLA_CAMINO_N_v1.1.xlsx")
    p.add_argument("--output", default=str(DEFAULT_OUTPUT),
                   help="Output JSON path (default: config/camino_n.assignments.json)")
    p.add_argument("--print-sha256", action="store_true",
                   help="Print the sha256 of the projection and exit")
    args = p.parse_args(argv)

    out_path, digest = generate(Path(args.tabla), Path(args.output))
    if args.print_sha256:
        print(digest)
        return 0
    print(f"wrote {out_path}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
