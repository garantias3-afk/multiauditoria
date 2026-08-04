#!/usr/bin/env python3
"""runner.py — CAMINO_N adapter (OT RUNNER CAMINO_N v2, FASE 3).

The runner is an ADAPTER, not a new project (OT R6: ~70% already existed). It
ties together:

  D1 tabla_loader      : the tabla is the source of truth (change a model = a cell)
  D2 dispatch          : primaria/paralela/carrera/fallback/condicional
  D3 fallback_ladder   : NO_DISPONIBLE vs CORRIO_Y_FALLO vs ESCRIBIO_PERO_NO_PASA_GATE
  D4 loop_engine       : INTERNO/MEDIANO/LARGO with persistent counters
  D5 registro          : 10-field identity + prev_entry_id (reuses quality_log)
  §8 contradiccion     : tabla-vs-canon classified ASIGNACION/REGLA

It reuses (does NOT rewrite):
  - host_runtime.detect_host  (host_runtime.py:258)
  - drive_fuse.fuse_safe_write (drive_fuse.py:40)  via fallback_ladder/registro
  - quality_log.record_quality_event (quality_log.py:184)  via registro
  - the restart_big_loop pattern (overnight_master.py:453)  via loop_engine.decide_largo

Provider invocation is delegated to a caller-supplied Invoker so the runner is
testable without network; the production Invoker wraps worker_gateway.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.contradiccion import (  # noqa: E402
    BLOCK_STATE, Conflict, ConflictVerdict, add_to_verdict, make_conflict,
    route_present_in_tabla_absent_in_canon,
)
from scripts.defect_class import classify_defect  # noqa: E402
from scripts.dispatch import DispatchResult, dispatch_puesto  # noqa: E402
from scripts.fallback_ladder import (  # noqa: E402
    AlwaysPassGate, Outcome, commit_artifact, mark_abort,
)
from scripts.loop_engine import (  # noqa: E402
    LARGO_DESTINO_SLOT, LoopCounters, InputHistory, decide_largo, decide_mediano,
    load_counters, save_counters, r1_guard, input_fingerprint, interno_instruction,
)
from scripts.registro import HASH_CHAIN_DEBT, RunRecorder, build_auditor  # noqa: E402
from scripts.resolve_root import IntercambioShareUnavailable, resolve_root  # noqa: E402
from scripts.tabla_loader import (  # noqa: E402
    NO_CONSTA, TablaConfig, TablaError, find_tabla, load_tabla,
)


# Terminal states (OT section 8).
S_PRIMITIVA = "RUNNER_PRIMITIVA_LISTA"
S_IMPLEMENTADO = "RUNNER_IMPLEMENTADO"
S_SMOKE_OK = "RUNNER_SMOKE_OK"
S_LOOP_REQUIRED = "RUNNER_LOOP_REQUIRED"
S_INCOMPLETE = "RUNNER_INCOMPLETE_WITH_ARTIFACTS"
S_BLOCKED = "RUNNER_BLOCKED_{}"      # .format(razon)
BLOCK_INPUT = S_BLOCKED.format("INPUT_NOT_FOUND_TABLA")
BLOCK_SHARE = S_BLOCKED.format("INTERCAMBIO_SHARE_UNAVAILABLE")
BLOCK_CONTRADICCION = S_BLOCKED.format("CONTRADICCION")


@dataclass
class RunnerResult:
    state: str
    intercambio_root: Optional[Path] = None
    host: Optional[dict[str, Any]] = None
    tabla_path: Optional[Path] = None
    verdict: ConflictVerdict = field(default_factory=ConflictVerdict)
    per_slot: dict[int, DispatchResult] = field(default_factory=dict)
    counters: Optional[LoopCounters] = None
    block_reason: str = ""
    notes: list[str] = field(default_factory=list)


class Runner:
    """The CAMINO_N adapter. Stateless across runs; per-run state lives on disk."""

    def __init__(
        self,
        *,
        invoker: Callable[..., tuple[bool, str, str]],
        tabla_path: Optional[Path] = None,
        intercambio_root: Optional[Path] = None,
        run_dir: Optional[Path] = None,
        only_steps: Optional[list[int]] = None,
        canon_routes: Optional[set[str]] = None,
        detect: Optional[Callable[[], dict[str, Any]]] = None,
    ):
        self.invoker = invoker
        self.tabla_path = tabla_path
        self.intercambio_root = intercambio_root
        self.run_dir = run_dir
        self.only_steps = only_steps
        self.canon_routes = canon_routes or set()
        self._detect = detect
        self.notes: list[str] = []

    # ----- FASE 2: resolve root + tabla ----- #
    def bootstrap(self) -> RunnerResult:
        """Resolve the root (verified), load the tabla, classify conflicts."""
        try:
            root = self.intercambio_root or resolve_root(detect=self._detect)
        except IntercambioShareUnavailable as exc:
            return RunnerResult(state=BLOCK_SHARE, block_reason=str(exc))

        # Detect host for the report (reused detect_host).
        host_info: dict[str, Any] = {}
        try:
            if self._detect is not None:
                host_info = dict(self._detect())
            else:
                from scripts.host_runtime import detect_host
                host_info = dict(detect_host())
        except Exception as exc:
            self.notes.append(f"detect_host failed (non-fatal): {exc}")

        # Load tabla. Per OT section 0: try Intercambio, then the repo fallback.
        try:
            tabla_path = self.tabla_path or find_tabla(root)
            cfg = load_tabla(tabla_path)
        except TablaError as exc:
            return RunnerResult(
                state=BLOCK_INPUT, intercambio_root=root, host=host_info,
                block_reason=str(exc),
            )

        # §8: classify tabla-vs-canon conflicts (assignment vs rule).
        verdict = self._classify_conflicts(cfg)

        self.intercambio_root = root
        self.tabla_path = tabla_path
        self.cfg = cfg
        self.recorder = RunRecorder(self.run_dir or root / "RUN_camino_n")
        self.counters = load_counters(self.recorder.run_dir)
        self.input_history = InputHistory()
        (self.recorder.run_dir).mkdir(parents=True, exist_ok=True)

        return RunnerResult(
            state=(BLOCK_CONTRADICCION if verdict.blocks else S_IMPLEMENTADO),
            intercambio_root=root, host=host_info, tabla_path=tabla_path,
            verdict=verdict, counters=self.counters, notes=list(self.notes),
        )

    def _classify_conflicts(self, cfg: TablaConfig) -> ConflictVerdict:
        """Walk assignments; classify any route absent from canon as ASIGNACION.

        Full canon-vs-tabla field comparison happens in the runner's
        wire-up; here we cover the known first-run trigger (route in tabla,
        absent in canon) which is always ASIGNACION. A REGLA conflict must be
        injected explicitly by the caller when it detects a permission/limit
        disagreement with the canon runtime policy.
        """
        v = ConflictVerdict()
        for a in cfg.assignments:
            if not a.is_active:
                continue
            if self.canon_routes and a.route_id not in self.canon_routes:
                c = route_present_in_tabla_absent_in_canon(
                    a.route_id, where=f"step={a.step} puesto={a.puesto}")
                v = add_to_verdict(v, c)
        return v

    # ----- D2/D3: run one step ----- #
    def run_step(self, step: int, *, gate: Any = None,
                 context: Optional[dict[str, Any]] = None) -> DispatchResult:
        """Dispatch a step's puesto(s) and apply the fallback ladder.

        Fallback routes are dispatched here ONLY after a NO_DISPONIBLE is
        registered for the primary path (P1: registered unavailability, not
        just slowness).
        """
        assignments = [a for a in self.cfg.routes_for_step(step) if a.is_active]
        if not assignments:
            res = DispatchResult(puesto="-", step=step, tipo_ruta="-")
            self._record(step, res)
            return res

        ctx = context or {}
        res = dispatch_puesto(
            assignments, invoker=self.invoker, workdir=self.recorder.run_dir,
            gate=gate, context=ctx,
        )
        self._record(step, res)

        # Fallback ladder: if the puesto needs a fallback and fallback routes
        # are declared, dispatch them now (registered unavailability).
        if res.needs_fallback:
            fb_assignments = [
                a for a in assignments if a.tipo_ruta == "fallback"
            ]
            if fb_assignments:
                ctx = {**ctx, "primary_failed": True}
                fb_res = dispatch_puesto(
                    fb_assignments, invoker=self.invoker,
                    workdir=self.recorder.run_dir, gate=gate, context=ctx,
                )
                self._record(step, fb_res)
                # Merge: fallback success rescues the puesto.
                if fb_res.succeeded:
                    res = DispatchResult(
                        puesto=res.puesto, step=step,
                        tipo_ruta=res.tipo_ruta + "+fallback",
                        winners=[*res.winners, *fb_res.winners],
                        classifications=[*res.classifications, *fb_res.classifications],
                        skipped=res.skipped, succeeded=True, needs_fallback=False,
                    )
        return res

    # ----- D4: loop decisions ----- #
    def mediano_reentry(
        self, *, step: int, verdict_summary: str, auditor_clase: str,
        author: str, writer_slot: int, cycle_first_slot: int,
        fingerprint: str,
    ) -> Any:
        """Decide a MEDIANO re-entry after a gate rejection.

        Applies R1 (no rerun unchanged input), R2 (exhaust doesn't escalate),
        and routes by class (R4). Returns the loop_engine MedianoDecision, or
        a string block reason if R1 forbids the re-entry.
        """
        dv = classify_defect(
            auditor_clase=auditor_clase, auditor_summary=verdict_summary,
            author=author,
        )
        clase = "A" if dv.is_mediano_a else "B"
        block = r1_guard(step=step, clase=clase, fingerprint=fingerprint,
                         history=self.input_history)
        if block:
            return block
        # pick tope from the tabla LOOPS sheet if available, else default 3/2.
        loop_spec = self.cfg.loop_for(step)
        tope = (3 if dv.is_mediano_a else 2)
        if loop_spec:
            tope = loop_spec.tope_ejec or tope
        decision = decide_mediano(
            dv, step=step, writer_slot=writer_slot,
            cycle_first_slot=cycle_first_slot, counters=self.counters, tope=tope,
        )
        self.counters.record_mediano(step, clase)
        self.input_history.record(step, clase, fingerprint)
        save_counters(self.recorder.run_dir, self.counters)
        return decision

    def largo_reentry(self, *, aprobador_verdict: str) -> Any:
        """Decide a LARGO re-entry (slot 14 -> slot 1). Only the aprobador
        triggers this. Adapts restart_big_loop."""
        decision = decide_largo(aprobador_verdict=aprobador_verdict,
                                counters=self.counters)
        if not decision.exhausted:
            self.counters.record_largo()
            save_counters(self.recorder.run_dir, self.counters)
        return decision

    # ----- D5: record identity-complete events ----- #
    def _record(self, step: int, res: DispatchResult) -> None:
        for a, co in zip(
            [x for x in self.cfg.routes_for_step(step) if x.is_active],
            res.classifications,
        ):
            model = self.cfg.model(a.route_id)
            auditor = build_auditor(
                route_id=a.route_id,
                model_id=(model.modelo_exacto if model else NO_CONSTA),
                provider_id=(model.provider_id if model else NO_CONSTA),
                provider_name=a.provider_name or NO_CONSTA,
                cost_class=a.cost_class or NO_CONSTA,
                role=a.puesto or "auditor",
                worker_id=(model.provider_id if model else NO_CONSTA),
                slot_id=str(step),
                interface=(model.modo_agente if model else NO_CONSTA),
                route=a.tipo_ruta,
            )
            self.recorder.record(
                event=f"route_{co.outcome.value.lower()}",
                auditor=auditor,
                artifact={"step": step, "puesto": a.puesto,
                          "final_path": str(co.final_path) if co.final_path else None},
                finding={"id": f"{a.route_id}@{step}", "type": "dispatch",
                         "severity": "info", "summary": co.reason},
                adjudication={"final_status": co.outcome.value},
                details={"fallback_enters": co.fallback_enters,
                         "is_loop_material": co.is_loop_material,
                         "tipo_ruta": a.tipo_ruta},
                dedupe_key=f"{a.route_id}|{step}|{co.outcome.value}",
            )


# ----- Invoker that wraps worker_gateway for production ----- #
class GatewayInvoker:
    """Production Invoker: wraps worker_gateway to invoke a route.

    The actual provider call is delegated; this class turns the gateway result
    into the (ok, content, reason) contract dispatch expects and commits the
    artifact via the reused atomic-write primitive.
    """

    def __init__(self, gateway_url: str = "", *, dry_run: bool = False):
        self.gateway_url = gateway_url
        self.dry_run = dry_run

    def __call__(self, assignment, out_path) -> tuple[bool, str, str]:
        if self.dry_run:
            commit_artifact(Path(out_path), json.dumps({"dry_run": True,
                "route_id": assignment.route_id}))
            return True, "dry_run", "ok"
        # Real invocation would call worker_gateway; left to the runner wiring.
        # On connection error/timeout: return False, "", "timeout/429/5xx" and
        # do NOT commit -> classified NO_DISPONIBLE.
        # On a run that produced broken output: mark_abort + (False, "", "abort: ...")
        # -> classified CORRIO_Y_FALLO.
        raise NotImplementedError(
            "Production Invoker must wrap worker_gateway per the route's provider. "
            "Use a test/dry-run Invoker otherwise."
        )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="CAMINO_N runner adapter (OT v2)")
    p.add_argument("--tabla", default=None, help="Path to TABLA_CAMINO_N_v1.1.xlsx")
    p.add_argument("--shared-root", default=None,
                   help="Intercambio root override (verified against markers)")
    p.add_argument("--only-steps", default=None,
                   help="Comma-separated step numbers to run (e.g. 1,3,4)")
    p.add_argument("--smoke", action="store_true",
                   help="Run the slot-1 smoke with a dry-run invoker")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    only_steps = None
    if args.only_steps:
        only_steps = [int(s) for s in args.only_steps.split(",") if s.strip()]

    invoker = GatewayInvoker(dry_run=True) if (args.smoke or args.dry_run) else GatewayInvoker()
    runner = Runner(
        invoker=invoker,
        tabla_path=Path(args.tabla) if args.tabla else None,
        intercambio_root=Path(args.shared_root) if args.shared_root else None,
        only_steps=only_steps,
    )
    res = runner.bootstrap()
    print(f"STATE: {res.state}")
    print(f"ROOT: {res.intercambio_root}")
    print(f"HOST: {(res.host or {}).get('role')} / {(res.host or {}).get('hostname')}")
    print(f"TABLA: {res.tabla_path}")
    if res.verdict.asignacion or res.verdict.regla:
        print(f"CONTRADICCIONES: asignacion={len(res.verdict.asignacion)} regla={len(res.verdict.regla)}")
        for c in res.verdict.all_artifacts():
            print(f"  - [{c['clase']}] {c['canon_field']} @ {c['where']}: {c['note']}")
    if res.block_reason:
        print(f"BLOCK: {res.block_reason}")
    return 0 if res.state in (S_IMPLEMENTADO, S_PRIMITIVA, S_SMOKE_OK) else 2


if __name__ == "__main__":
    raise SystemExit(main())
