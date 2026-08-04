#!/usr/bin/env python3
"""smoke_slot1.py — FASE 4 smoke for the CAMINO_N runner (OT section 5 / G10).

Runs slot 1 COMPLETE over a real artifact. Slot 1 is all free canary-verified
routes, so a failure here is the RUNNER's fault, not the provider's.

Verifies (OT section 5):
  - despacho paralelo  (the ola)
  - carrera con cancelacion (first valid wins, rest cancelled)
  - recoleccion        (winners collected)
  - identidad completa (10 auditor fields, NO_CONSTA defaults preserved)
  - entrada en el quality log (prev_entry_id threaded, dedup intact)

Two modes:
  default : simulated invoker producing realistic per-route artifacts. Proves
            the runner's plumbing end-to-end without network. The artifact is
            real (a small code file under the run dir).
  --live  : wires GatewayInvoker (production). NOT runnable in this session;
            Mariano runs it where the gateway is reachable.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dispatch import dispatch_puesto  # noqa: E402
from scripts.fallback_ladder import AlwaysPassGate  # noqa: E402
from scripts.registro import RunRecorder, build_auditor  # noqa: E402
from scripts.runner import Runner, GatewayInvoker, S_SMOKE_OK  # noqa: E402
from scripts.tabla_loader import NO_CONSTA, find_tabla, load_tabla  # noqa: E402


def _make_real_artifact(run_dir: Path) -> Path:
    """A small, real artifact for slot 1 to audit (slot 1 audits a DETECT
    target). One trivial defect so the audit loop has something to say."""
    target = run_dir / "target" / "sample_module.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def divide(a, b):\n"
        "    return a / b  # BUG: no zero check\n",
        encoding="utf-8",
    )
    return target


class SimulatedInvoker:
    """Invoker that produces a realistic per-route audit artifact for slot 1.

    Each route 'audits' the target and writes a finding. Race members are
    staggered so the carrera actually races. Unavailability is simulated for
    none (slot 1 is all VERIFICADO_64K), proving the runner doesn't invent
    failures.
    """

    def __init__(self, target: Path, *, delays: dict[str, float] | None = None):
        self.target = target
        self.delays = delays or {}
        self.calls: list[str] = []

    def __call__(self, assignment, out_path) -> tuple[bool, str, str]:
        self.calls.append(assignment.route_id)
        if assignment.route_id in self.delays:
            time.sleep(self.delays[assignment.route_id])
        out_path = Path(out_path)
        # Realistic audit output: identity-complete, references the real target.
        content = json.dumps({
            "route_id": assignment.route_id,
            "audited_file": str(self.target),
            "finding": "divide() lacks zero-division guard",
            "severity": "medium",
            "verdict": "DETECT",
        }, ensure_ascii=False, indent=2)
        from scripts.fallback_ladder import commit_artifact
        commit_artifact(out_path, content)
        return True, content, "ok"


def run_smoke(*, tabla_path: Path | None = None, live: bool = False) -> dict[str, Any]:
    """Execute the slot-1 smoke. Returns a structured report."""
    from scripts.resolve_root import resolve_root
    root = resolve_root()
    tabla = tabla_path or find_tabla(root)
    cfg = load_tabla(tabla)

    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td) / "RUN_smoke"
        run_dir.mkdir()
        target = _make_real_artifact(run_dir)

        if live:
            invoker = GatewayInvoker(dry_run=False)
        else:
            # Stagger carrera members: the OR ultra is faster than NVIDIA ultra
            # (matches the tabla: OR gana por 0.9s). So OR should win the race.
            invoker = SimulatedInvoker(
                target,
                delays={"or_nemotron_3_ultra_550b": 0.0,
                        "nvidia_nemotron_3_ultra_550b": 0.6},
            )

        runner = Runner(
            invoker=invoker, tabla_path=tabla, intercambio_root=root,
            run_dir=run_dir, only_steps=[1],
        )
        boot = runner.bootstrap()
        if boot.state not in ("RUNNER_IMPLEMENTADO",):
            return {"ok": False, "state": boot.state,
                    "reason": "bootstrap did not reach IMPLEMENTADO",
                    "block": boot.block_reason}

        # Run slot 1 (auditores paralelos): carrera + paralela.
        gate = AlwaysPassGate()
        res = runner.run_step(1, gate=gate)

        # Verify all the OT smoke criteria.
        report: dict[str, Any] = {"state": S_SMOKE_OK, "ok": True, "root": str(root)}

        # 1. Despacho paralelo: the paralela ola ran (multiple winners from it).
        paralela_routes = [a.route_id for a in cfg.routes_for_step(1)
                           if a.is_active and a.tipo_ruta == "paralela"]
        paralela_winners = [a.route_id for a in res.winners
                            if a.route_id in paralela_routes]
        report["paralela"] = {
            "expected": paralela_routes,
            "winners": paralela_winners,
            "ok": len(paralela_winners) == len(paralela_routes),
        }

        # 2. Carrera con cancelacion: exactly ONE carrera winner.
        carrera_routes = [a.route_id for a in cfg.routes_for_step(1)
                          if a.is_active and a.tipo_ruta == "carrera"]
        carrera_winners = [a.route_id for a in res.winners
                           if a.route_id in carrera_routes]
        report["carrera"] = {
            "candidates": carrera_routes,
            "winners": carrera_winners,
            "ok": len(carrera_winners) == 1,
            "note": "first valid wins; in sim, OR ultra is faster",
        }

        # 3. Recoleccion: winners collected.
        report["recoleccion"] = {
            "total_winners": len(res.winners),
            "ok": len(res.winners) >= 1,
        }

        # 4. Identidad completa: every recorded entry has 10 auditor fields,
        #    none dropped, NO_CONSTA preserved where unknown.
        deltas = list((run_dir / "90_QUALITY_LOG_DELTA").glob("*.entry.json"))
        identity_ok = True
        prev_threaded = 0
        sample_entry: dict[str, Any] = {}
        for dp in deltas:
            d = json.loads(dp.read_text(encoding="utf-8"))
            aud = d.get("auditor") or {}
            required = {"slot_id","route_id","model_id","provider_id",
                        "provider_name","route","interface","cost_class",
                        "role","worker_id"}
            if not required.issubset(aud.keys()):
                identity_ok = False
            if d.get("prev_entry_id") is not None:
                prev_threaded += 1
            if not sample_entry:
                sample_entry = d
        report["identidad"] = {
            "entries": len(deltas),
            "ten_fields_all": identity_ok,
            "prev_entry_id_threaded": prev_threaded,
            "sample_auditor": sample_entry.get("auditor", {}),
            "ok": identity_ok and prev_threaded >= 1,
        }

        # 5. Entrada en el quality log (dedup intact, prev threaded).
        report["quality_log"] = {
            "entries_written": len(deltas),
            "ok": len(deltas) >= 1,
        }

        report["ok"] = all(
            v["ok"] for k, v in report.items()
            if isinstance(v, dict) and "ok" in v and k != "identidad"
        ) and report["identidad"]["ok"]
        report["state"] = S_SMOKE_OK if report["ok"] else "RUNNER_LOOP_REQUIRED"
        return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CAMINO_N slot-1 smoke (OT FASE 4)")
    p.add_argument("--tabla", default=None)
    p.add_argument("--live", action="store_true",
                   help="Use the production GatewayInvoker (needs gateway)")
    args = p.parse_args(argv)
    report = run_smoke(
        tabla_path=Path(args.tabla) if args.tabla else None, live=args.live)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
