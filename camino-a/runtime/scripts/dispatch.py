"""dispatch.py — dispatch a puesto's routes by tipo_ruta (OT section 4 D2).

The tabla declares five tipo_ruta values; each maps to a dispatch shape:

  primaria     -> exactly one route; always run.
  paralela     -> an OLA: all routes at once. P7: every free VERIFICADO route
                  starts together; the wall is fixed by the slowest and that
                  is accepted. Losing 1 of N is absorbed by redundancy.
  carrera      -> all routes at once; the FIRST VALID output wins and the rest
                  are cancelled. P5: same model across providers counts as ONE
                  independence group.
  fallback     -> runs ONLY after a REGISTERED unavailability of the primary.
                  Slowness alone never triggers it (P8: truncation
                  disqualifies, latency does not).
  condicional  -> runs according to the condition declared in `notas`.

This module ADAPTS the dispatch pattern of the existing orchestrator
(run_multiaudit_cycle.canonical_run + overnight_master.harvest_workers); it
does not re-implement provider invocation. Route invocation is delegated to a
caller-supplied Invoker so the dispatcher is unit-testable without network.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from scripts.fallback_ladder import (
    AlwaysPassGate, ClassifiedOutcome, Outcome, classify_outcome, commit_artifact,
)
from scripts.tabla_loader import (
    NO_CONSTA, RouteAssignment, TIPO_CARRERA, TIPO_CONDICIONAL, TIPO_FALLBACK,
    TIPO_PARALELA, TIPO_PRIMARIA,
)


class Invoker(Protocol):
    """Invoke a single route. Implemented by the runner against worker_gateway.

    Returns (success: bool, content: str, reason: str). On a provider
    unavailable (429/5xx/timeout) success=False and the caller classifies it
    as NO_DISPONIBLE via the filesystem (no artifact produced).
    """

    def __call__(self, assignment: RouteAssignment, out_path: Any) -> tuple[bool, str, str]: ...


@dataclass(frozen=True)
class DispatchResult:
    puesto: str
    step: int
    tipo_ruta: str
    # Winners: routes that produced a valid artifact this dispatch.
    winners: list[RouteAssignment] = field(default_factory=list)
    # Full classification per route, for the quality log.
    classifications: list[ClassifiedOutcome] = field(default_factory=list)
    # Routes that were skipped and why (unavailable, condition false, etc.)
    skipped: list[tuple[RouteAssignment, str]] = field(default_factory=list)
    # Whether the puesto as a whole produced a valid artifact.
    succeeded: bool = False
    # Whether a fallback is warranted for this puesto.
    needs_fallback: bool = False

    @property
    def winner_routes(self) -> list[str]:
        return [a.route_id for a in self.winners]


def _out_path_for(workdir: Any, step: int, puesto: str, route_id: str, kind: str) -> Any:
    """Build a deterministic output path for a route's artifact.

    `kind` is typically the route_id (or the ola slot) so carrera/paralela
    members do not clobber each other.
    """
    from pathlib import Path
    safe_puesto = "".join(c if c.isalnum() else "_" for c in puesto)[:40] or "puesto"
    return Path(workdir) / f"step{step}" / safe_puesto / f"{kind}.json"


def dispatch_primaria(
    assignment: RouteAssignment,
    *,
    invoker: Invoker,
    workdir: Any,
    gate: Optional[Any] = None,
) -> DispatchResult:
    """A single primary route. Always run."""
    out = _out_path_for(workdir, assignment.step, assignment.puesto, assignment.route_id, assignment.route_id)
    ok, content, reason = invoker(assignment, out)
    co = classify_outcome(out, gate=gate, abort_signal=(not ok and "abort" in reason.lower()))
    res = DispatchResult(
        puesto=assignment.puesto, step=assignment.step, tipo_ruta=TIPO_PRIMARIA,
        classifications=[co], succeeded=(co.final_path is not None and not co.is_loop_material),
        needs_fallback=(co.outcome == Outcome.NO_DISPONIBLE),
        winners=[assignment] if (co.final_path is not None and not co.is_loop_material) else [],
        skipped=[(assignment, co.reason)] if co.outcome == Outcome.NO_DISPONIBLE else [],
    )
    return res


def dispatch_paralela(
    assignments: list[RouteAssignment],
    *,
    invoker: Invoker,
    workdir: Any,
    gate: Optional[Any] = None,
    max_workers: Optional[int] = None,
) -> DispatchResult:
    """An OLA: all routes at once. P7 — every free VERIFICADO route starts
    together; the slowest fixes the wall. Losing 1 of N is absorbed.

    For an ola there is NO fallback per route: redundancy is the fallback
    (FALLBACKS sheet: 'perder 1 de N lo absorbe la redundancia'). The puesto
    succeeds if ANY route produces a valid artifact.
    """
    if not assignments:
        return DispatchResult(puesto="-", step=0, tipo_ruta=TIPO_PARALELA)
    step = assignments[0].step
    puesto = assignments[0].puesto
    workers = max_workers or max(1, len(assignments))

    classifications: list[ClassifiedOutcome] = []
    winners: list[RouteAssignment] = []
    skipped: list[tuple[RouteAssignment, str]] = []

    def _run(a: RouteAssignment) -> tuple[RouteAssignment, ClassifiedOutcome]:
        out = _out_path_for(workdir, a.step, a.puesto, a.route_id, a.route_id)
        ok, content, reason = invoker(a, out)
        co = classify_outcome(out, gate=gate, abort_signal=(not ok and "abort" in reason.lower()))
        return a, co

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for a, co in pool.map(_run, assignments):
            classifications.append(co)
            if co.final_path is not None and not co.is_loop_material:
                winners.append(a)
            elif co.outcome == Outcome.NO_DISPONIBLE:
                skipped.append((a, co.reason))

    # The ola as a whole needs a fallback only if NO route produced anything.
    needs_fallback = not winners and any(
        c.outcome == Outcome.NO_DISPONIBLE for c in classifications
    )
    return DispatchResult(
        puesto=puesto, step=step, tipo_ruta=TIPO_PARALELA,
        classifications=classifications, winners=winners,
        skipped=skipped, succeeded=bool(winners),
        needs_fallback=needs_fallback,
    )


def dispatch_carrera(
    assignments: list[RouteAssignment],
    *,
    invoker: Invoker,
    workdir: Any,
    gate: Optional[Any] = None,
    max_workers: Optional[int] = None,
) -> DispatchResult:
    """A RACE: all at once, first VALID output wins, the rest are cancelled.

    P5: same model across providers is ONE independence group, so a carrera
    member failing to availability does not block — another provider of the
    same model can win. Cancellation is cooperative: once a winner commits,
    pending futures are told to stop (their result, if any, is discarded).
    """
    if not assignments:
        return DispatchResult(puesto="-", step=0, tipo_ruta=TIPO_CARRERA)
    step = assignments[0].step
    puesto = assignments[0].puesto
    workers = max_workers or max(1, len(assignments))

    classifications: list[ClassifiedOutcome] = []
    winners: list[RouteAssignment] = []
    skipped: list[tuple[RouteAssignment, str]] = []
    cancelled: list[RouteAssignment] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for a in assignments:
            out = _out_path_for(workdir, a.step, a.puesto, a.route_id, a.route_id)
            fut = pool.submit(_invoke_and_classify, invoker, a, out, gate)
            futures[fut] = a

        pending = set(futures)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                a, co = fut.result()
                classifications.append(co)
                # First VALID output wins.
                if co.final_path is not None and not co.is_loop_material and not winners:
                    winners.append(a)
                    # Cancel the rest. Already-running ones can't be hard-killed,
                    # but their results will be discarded.
                    for p in pending:
                        p.cancel()
                    cancelled.extend(futures[p] for p in pending if p.cancel())
                    pending = set()
                    break
                if co.outcome == Outcome.NO_DISPONIBLE:
                    skipped.append((a, co.reason))

        # Drain anything still running after a winner (their artifacts are
        # discarded; they classify as losers, not failures).
        for p in list(pending):
            a = futures[p]
            try:
                _, co = p.result()
                classifications.append(co)
                if co.outcome == Outcome.NO_DISPONIBLE:
                    skipped.append((a, co.reason))
            except Exception:
                cancelled.append(a)

    return DispatchResult(
        puesto=puesto, step=step, tipo_ruta=TIPO_CARRERA,
        classifications=classifications, winners=winners,
        skipped=skipped, succeeded=bool(winners),
        # A carrera has built-in redundancy; needs_fallback only if everything
        # was unavailable.
        needs_fallback=not winners and bool(classifications) and all(
            c.outcome == Outcome.NO_DISPONIBLE for c in classifications),
    )


def _invoke_and_classify(invoker, a, out, gate) -> tuple[RouteAssignment, ClassifiedOutcome]:
    ok, content, reason = invoker(a, out)
    co = classify_outcome(out, gate=gate, abort_signal=(not ok and "abort" in reason.lower()))
    return a, co


def evaluate_condicion(assignment: RouteAssignment, *, context: dict[str, Any]) -> bool:
    """Evaluate whether a `condicional` route should run.

    The condition is declared in `notas`. The tabla's documented conditions are
    phrasings like 'solo si fallan las TRES ultras' or 'entra RECIEN ACA'. We
    parse the most common patterns mechanically; anything unrecognised defaults
    to False (do not run) so a vague note never silently injects a paid route.
    """
    nota = (assignment.notas or "").lower()
    # Known trigger: 'solo si fallan las TRES ultras' / 'si fallan los grandes'
    if "tres ultras" in nota or "3 ultras" in nota:
        return bool(context.get("ultras_failed"))
    if "fallan los grandes" in nota or "fallan los 3" in nota:
        return bool(context.get("grandes_failed"))
    if "solo si fallan" in nota or "recien aca" in nota or "entra recien" in nota:
        # Generic 'only after the primary path failed' guard.
        return bool(context.get("primary_failed"))
    # Unrecognised condition -> do not run (conservative; log for review).
    return False


def dispatch_puesto(
    assignments: list[RouteAssignment],
    *,
    invoker: Invoker,
    workdir: Any,
    gate: Optional[Any] = None,
    context: Optional[dict[str, Any]] = None,
    max_workers: Optional[int] = None,
) -> DispatchResult:
    """Top-level dispatcher: split assignments by tipo_ruta and dispatch.

    This is what the runner calls per puesto. It groups routes by tipo_ruta
    and applies the right shape. Fallback routes are NOT dispatched here: they
    are dispatched by the runner only after a NO_DISPONIBLE is registered.
    """
    ctx = context or {}
    by_tipo: dict[str, list[RouteAssignment]] = {}
    for a in assignments:
        by_tipo.setdefault(a.tipo_ruta, []).append(a)

    # Condicional routes are gated by their note.
    cond_false: list[tuple[RouteAssignment, str]] = []
    active: dict[str, list[RouteAssignment]] = {}
    for tipo, routes in by_tipo.items():
        if tipo == TIPO_CONDICIONAL:
            kept = []
            for a in routes:
                if evaluate_condicion(a, context=ctx):
                    kept.append(a)
                else:
                    cond_false.append((a, "condicion no satisfecha: " + (a.notas or "")[:60]))
            if kept:
                active[TIPO_CONDICIONAL] = kept
        else:
            active[tipo] = routes

    # Dispatch primaries (one each) and the ola/carrera.
    results: list[DispatchResult] = []
    for primaria in active.get(TIPO_PRIMARIA, []):
        results.append(dispatch_primaria(
            primaria, invoker=invoker, workdir=workdir, gate=gate))
    if active.get(TIPO_PARALELA):
        results.append(dispatch_paralela(
            active[TIPO_PARALELA], invoker=invoker, workdir=workdir, gate=gate,
            max_workers=max_workers))
    if active.get(TIPO_CARRERA):
        results.append(dispatch_carrera(
            active[TIPO_CARRERA], invoker=invoker, workdir=workdir, gate=gate,
            max_workers=max_workers))
    if active.get(TIPO_CONDICIONAL):
        # Condicionales that passed their gate run as an ola.
        results.append(dispatch_paralela(
            active[TIPO_CONDICIONAL], invoker=invoker, workdir=workdir, gate=gate,
            max_workers=max_workers))

    return _merge(results, cond_false, step=assignments[0].step if assignments else 0,
                  puesto=assignments[0].puesto if assignments else "-")


def _merge(results: list[DispatchResult], cond_false, *, step: int, puesto: str) -> DispatchResult:
    winners: list[RouteAssignment] = []
    classifications: list[ClassifiedOutcome] = []
    skipped: list[tuple[RouteAssignment, str]] = list(cond_false)
    tipos = []
    needs_fb = False
    for r in results:
        winners.extend(r.winners)
        classifications.extend(r.classifications)
        skipped.extend(r.skipped)
        if r.needs_fallback:
            needs_fb = True
        if r.tipo_ruta not in tipos:
            tipos.append(r.tipo_ruta)
    return DispatchResult(
        puesto=puesto, step=step, tipo_ruta="+".join(tipos) or "-",
        winners=winners, classifications=classifications, skipped=skipped,
        succeeded=bool(winners), needs_fallback=needs_fb,
    )
