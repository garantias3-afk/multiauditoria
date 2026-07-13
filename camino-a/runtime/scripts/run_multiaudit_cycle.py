#!/usr/bin/env python3
"""run_multiaudit_cycle.py — CANONICAL entrypoint (v1.2).

Historically this filename was a 3.8k-line monolith that carried its own
hardcoded slot/provider/close logic. As of v1.2 it is a *thin* canonical
entrypoint that owns NO policy of its own and delegates 100% to the canon
runtime:

    canon_loader.py          -> load + validate the mutable canon (fail closed)
    slot_runtime.py          -> build the slot execution plan from the canon
    internal_loop_runner.py  -> run the agentic internal loop (audit/patch/
                                test/reaudit) with explicit residual_debt
    overnight_master.py      -> phase engine: create/execute/wait/validate/
                                package/close with the correct terminal_reason
    package_final.py         -> final packaging (invoked by overnight_master)

Spec guarantees enforced here:
  * §10/§11 — this file contains NO hardcoded list of slots, providers, models,
    fallbacks or close rules. Everything comes from the canon.
  * §8 — interactive runs without --canon-profile are ASKED which profile.
  * §9 — non-interactive/CI runs without a profile FAIL CLOSED, unless the
    operator explicitly opts into the documented canon default with
    --ci-default-profile.

The preserved monolith lives in run_multiaudit_cycle_legacy.py and stays
reachable via `run_multiaudit_cycle.py --legacy ...`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Backwards-compat re-exports (COMPAT SHIM, not policy).
#
# The rest of the runtime and the test-suite import policy-free plumbing via
# `from scripts.run_multiaudit_cycle import <helper>`. Those helpers are exposed
# through scripts/canon_plumbing.py: a stable canonical import target for
# state/hash/secret/manifest/lock IO. The facade intentionally re-exports the
# still-live legacy implementations instead of moving a fragile 48-function
# transitive closure without the full historical test suite.
#
# This keeps the canonical entrypoint free of slot/provider/close policy while
# making the remaining legacy dependency explicit and auditable.
# ---------------------------------------------------------------------------
from scripts.canon_plumbing import (  # noqa: F401  (re-export, canonical facade)
    BUS_DIRS,
    sha256_file, utc_now, utc_now_compact, safe_slug,
    read_json, write_json, save_state, load_state, history_event,
    ensure_bus_dirs, reap_children,
    validate_output_manifest, write_output_manifest_and_done,
    assert_no_unredacted_secret, assert_file_has_no_unredacted_secret,
    redact_secrets_text,
    acquire_watcher_lock, release_watcher_lock,
    _sanitized_env, run,
    record_quality_log_delta, send_local_notification,
)

from scripts.canon_loader import (
    load_canon, resolve_profile, canon_summary, CanonError,
)
from scripts import slot_runtime
from scripts.internal_loop_runner import run_internal_loop
from scripts.worker_agentic_local import AgenticLocalWorker
from scripts.quality_log import record_quality_event, auditor_from_result
from scripts.state_db import StateDB
from scripts.candidate_updates import candidate_source


# ---------------------------------------------------------------------------
# Profile resolution (spec §1 / §8 / §9)
# ---------------------------------------------------------------------------

_PROFILE_PROMPT = "¿Querés automatización CON Claude en el flujo o SIN Claude?"


def _is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def resolve_canon_profile_name(args: argparse.Namespace, default_profile: str) -> str | None:
    """Decide the runtime profile. Returns None to signal fail-closed.

    Precedence:
      1. explicit --canon-profile
      2. interactive TTY -> ask the mandatory question (§8)
      3. --ci-default-profile -> documented canon default (§9)
      4. otherwise -> None (caller fails closed, §9)
    """
    if args.canon_profile:
        return args.canon_profile
    if _is_interactive():
        print(_PROFILE_PROMPT)
        print("  [1] CON Claude   (with_claude)")
        print("  [2] SIN Claude   (without_claude)")
        while True:
            try:
                choice = input("Elegí 1/2 (o con/sin): ").strip().lower()
            except EOFError:
                return None
            if choice in ("1", "con", "with", "with_claude"):
                return "with_claude"
            if choice in ("2", "sin", "without", "without_claude"):
                return "without_claude"
            print("Respuesta no reconocida. Escribí 1, 2, con o sin.")
    if args.ci_default_profile:
        return default_profile
    return None


# ---------------------------------------------------------------------------
# Delegated helpers
# ---------------------------------------------------------------------------

def _run_subprocess(cmd: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)


def _create_run(target: Path, runs_dir: Path, profile_name: str,
                canon_dir: str, run_label: str, *, execution_host: str = "auto",
                lmstudio_base_url: str = "", shared_root: str = "") -> tuple[int, Path | None, str]:
    """Delegate run creation + canon snapshot to start_overnight.py."""
    cmd = [
        sys.executable, str(ROOT / "scripts" / "start_overnight.py"),
        "--target", str(target),
        "--runs-dir", str(runs_dir),
        "--run-label", safe_slug(run_label or "canon_multiaudit"),
        "--profile", profile_name,
        "--execution-host", execution_host,
    ]
    if canon_dir:
        cmd += ["--canon-dir", str(Path(canon_dir).expanduser().resolve())]
    if lmstudio_base_url:
        cmd += ["--lmstudio-base-url", lmstudio_base_url]
    if shared_root:
        cmd += ["--shared-root", str(Path(shared_root).expanduser())]
    cp = _run_subprocess(cmd)
    sys.stdout.write(cp.stdout)
    if cp.stderr:
        sys.stderr.write(cp.stderr)
    if cp.returncode != 0:
        return cp.returncode, None, cp.stdout
    run_dir = None
    for line in cp.stdout.splitlines():
        if line.startswith("Directory:"):
            run_dir = Path(line.split("Directory:", 1)[1].strip())
            break
    if run_dir is None:
        return 2, None, cp.stdout
    return 0, run_dir, cp.stdout


def _run_internal_agentic_loop(run_dir: Path, plan: "slot_runtime.SlotPlan",
                               runtime_policy: dict[str, Any]) -> dict[str, Any]:
    """Run every enabled canon-required internal loop with durable evidence.

    This runner-owned reference gate does not impersonate an external model. It
    guarantees that slots 1/4/7/8 (or any future required slots) all receive a
    real audit/test/reaudit loop record instead of exercising only the first
    entry. Provider jobs still receive their own loop contract separately.
    """
    required_agentic = [
        s for s in plan.slots
        if bool(s.internal_loop.get("required"))
        and s.internal_loop.get("loop_type") == "internal_agentic"
        and s.enabled
    ]
    if not required_agentic:
        return {"status": "no_required_agentic_slot_in_canon", "ran": False}
    il_root = run_dir / "INTERNAL_LOOP"
    snapshot = candidate_source(run_dir)
    summaries: dict[str, dict[str, Any]] = {}
    all_debt: list[dict[str, Any]] = []
    db = None
    try:
        db_path = run_dir / "STATE" / "state.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = StateDB(db_path)

        for spec in required_agentic:
            max_loops = slot_runtime.slot_max_internal_loops(spec, runtime_policy)
            slot_root = il_root / f"slot_{spec.slot_id}"
            workdir = slot_root / "workdir"
            if workdir.is_symlink():
                raise RuntimeError(f"internal_loop_workspace_symlink:{spec.slot_id}")
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True, exist_ok=True)
            if snapshot.exists():
                for item in sorted(snapshot.rglob("*")):
                    if item.is_file() and not item.is_symlink():
                        rel = item.relative_to(snapshot)
                        dst = workdir / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dst)

            def _quality_event(event: str, _spec=spec, _workdir=workdir, **extra: Any) -> None:
                auditor = auditor_from_result("agentic_local", {
                    "worker_id": "agentic_local",
                    "slot_id": _spec.slot_id,
                    "role": _spec.role,
                    "status": event,
                }, stage="internal_loop")
                record_quality_event(
                    run_dir, event=f"internal_loop_{event}", auditor=auditor,
                    artifact={"slot_id": _spec.slot_id, "workdir": str(_workdir)},
                    finding={
                        "id": f"internal_loop_{_spec.slot_id}_{event}_{extra.get('index', 'na')}",
                        "type": "internal_loop",
                        "severity": "info" if not str(event).endswith("residual_debt") else "warning",
                        "summary": f"Internal agentic loop event {event} for slot {_spec.slot_id}",
                    },
                    adjudication={"final_status": "RECORDED"},
                    details={"event": event, **extra},
                    audit_family="camino_a_internal_loop",
                    dedupe_key=f"internal:{_spec.slot_id}:{event}:{extra.get('index','na')}:{extra.get('findings','')}:{extra.get('iterations','')}",
                    db=db,
                )

            result = run_internal_loop(
                workdir, AgenticLocalWorker(),
                slot_id=spec.slot_id,
                max_internal_loops=max_loops,
                correction_policy=spec.correction_policy,
                blocks_within_limit=slot_runtime.blocks_within_limit(spec.correction_policy),
                artifacts_dir=slot_root / "artifacts",
                on_event=_quality_event,
            )
            per_slot = result.to_serializable()
            per_slot.update({
                "ran": True,
                "selected_slot": spec.slot_id,
                "worker_kind": "reference_local_agentic",
            })
            summaries[spec.slot_id] = per_slot
            all_debt.extend(result.residual_debt)
            write_json(slot_root / "internal_loop_summary.json", per_slot)
    finally:
        if db is not None:
            db.close()
    statuses = {value.get("status") for value in summaries.values()}
    summary = {
        "schema_version": "camino_internal_loops_aggregate.v1",
        "ran": True,
        "status": "residual_debt" if "residual_debt" in statuses else "clean",
        "selected_slot": required_agentic[0].slot_id,
        "selected_slots": [spec.slot_id for spec in required_agentic],
        "slot_count": len(required_agentic),
        "iteration_count": sum(int(value.get("iteration_count") or 0) for value in summaries.values()),
        "max_internal_loops": max(int(value.get("max_internal_loops") or 0) for value in summaries.values()),
        "worker_kind": "reference_local_agentic",
        "slots": summaries,
        "residual_debt": all_debt,
    }
    write_json(il_root / "internal_loop_summary.json", summary)

    # Annotate run state with the loop outcome + residual debt (before the
    # phase engine runs; it preserves unknown keys via dict updates).
    state = load_state(run_dir)
    state["internal_loop"] = summary
    state["internal_loops"] = summaries
    if all_debt:
        existing = state.get("residual_debt") or []
        state["residual_debt"] = existing + all_debt
    history_event(
        state, "internal_loops_done",
        slot_ids=summary["selected_slots"], status=summary["status"],
        residual_debt=len(all_debt),
    )
    save_state(run_dir, state)
    return summary


def _drive_phase_engine(run_dir: Path, *, interval: int, timeout_minutes: int,
                        max_iterations: int, execute_workers: bool) -> int:
    cmd = [
        sys.executable, str(ROOT / "scripts" / "overnight_master.py"),
        "--run", str(run_dir),
        "--interval", str(max(1, interval)),
        "--timeout-minutes", str(max(0, timeout_minutes)),
        "--max-iterations", str(max(1, max_iterations)),
    ]
    if execute_workers:
        cmd.append("--execute-workers")
    # Bound the wall-clock so a hung run cannot wedge the entrypoint.
    hard_timeout = max(120, (timeout_minutes or 2) * 60 + 120)
    try:
        cp = _run_subprocess(cmd, timeout=hard_timeout)
    except subprocess.TimeoutExpired:
        print("ERROR: phase engine wall-clock timeout", file=sys.stderr)
        return 124
    sys.stdout.write(cp.stdout)
    if cp.stderr:
        sys.stderr.write(cp.stderr)
    return cp.returncode


# ---------------------------------------------------------------------------
# Canonical orchestration
# ---------------------------------------------------------------------------

CANON_ALLOWED_TERMINAL = {
    "closed_success", "ready_for_human_final_review",
    "waiting_manual_claude_final_review", "reference_smoke_complete",
    "closed_success_codex_subscription_fallback",
}


def canonical_run(args: argparse.Namespace) -> int:
    target_raw = args.input or args.target
    if not target_raw:
        print("ERROR: falta --input/--target", file=sys.stderr)
        return 2
    target = Path(target_raw).expanduser().resolve()
    if not target.exists():
        print(f"ERROR: target not found: {target}", file=sys.stderr)
        return 1

    # 1) Load + validate canon (fail closed).
    try:
        bundle = load_canon(ROOT, Path(args.canon_dir) if args.canon_dir else None)
        default_profile = str(bundle.runtime_policy.get("default_profile") or "without_claude")
    except CanonError as exc:
        print(f"CANON_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 2

    # 2) Resolve profile (§8 interactive / §9 fail-closed).
    profile_name = resolve_canon_profile_name(args, default_profile)
    if profile_name is None:
        print(
            "PROFILE_REQUIRED: corrida no interactiva sin --canon-profile. "
            "Pasá --canon-profile with_claude|without_claude, o --ci-default-profile "
            f"para usar el default documentado del canon ('{default_profile}').",
            file=sys.stderr,
        )
        return 2
    try:
        profile = resolve_profile(bundle, profile_name)
    except CanonError as exc:
        print(f"CANON_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 2

    runs_dir = Path(args.drive_bus_root or args.runs_dir).expanduser().resolve()
    run_label = args.candidate_name or args.run_label

    # 3) Create run (delegated) — also snapshots the canon into the run.
    rc, run_dir, _ = _create_run(
        target, runs_dir, profile_name, args.canon_dir, run_label,
        execution_host=args.execution_host,
        lmstudio_base_url=args.lmstudio_base_url,
        shared_root=args.shared_root,
    )
    if rc != 0 or run_dir is None:
        print("ERROR: canon run creation failed", file=sys.stderr)
        return rc or 2

    # 4) Build the canon-driven slot plan and record it into the run.
    plan = slot_runtime.build_slot_plan(bundle, profile)
    write_json(run_dir / "CANON_SLOT_PLAN.json", plan.to_serializable())

    # 5) Internal agentic loop (real audit/patch/test/reaudit + residual_debt).
    internal_summary: dict[str, Any] = {"ran": False}
    if args.execute_workers and not args.no_internal_loop:
        internal_summary = _run_internal_agentic_loop(run_dir, plan, bundle.runtime_policy)

    if args.no_start_watcher:
        print(json.dumps({
            "status": "created",
            "run_dir": str(run_dir),
            "profile": profile_name,
            "internal_loop": internal_summary,
        }, indent=2, ensure_ascii=False))
        return 0

    # 6) Drive the phase engine (execute/wait/validate/package/close).
    engine_rc = _drive_phase_engine(
        run_dir,
        interval=int(args.watch_interval_seconds or 1),
        timeout_minutes=int(args.watch_timeout_minutes or 0),
        max_iterations=int(args.max_iterations or 1),
        execute_workers=args.execute_workers,
    )

    # 7) Read final state and emit an honest summary.
    state = load_state(run_dir)
    phase = state.get("current_phase")
    terminal_reason = state.get("terminal_reason")
    accepted = sorted(p.name for p in (run_dir / "ACCEPTED").iterdir()) \
        if (run_dir / "ACCEPTED").exists() else []
    final_zip = run_dir / "FINAL" / "final_release.zip"
    qdir = run_dir / "90_QUALITY_LOG_DELTA"
    quality_delta_count = len(list(qdir.glob("*.entry.json"))) if qdir.exists() else 0
    quality_sqlite_rows = None
    db_path = run_dir / "STATE" / "state.sqlite"
    if db_path.exists():
        try:
            import sqlite3
            con = sqlite3.connect(str(db_path))
            quality_sqlite_rows = con.execute("SELECT COUNT(*) FROM quality_log").fetchone()[0]
            con.close()
        except Exception:
            quality_sqlite_rows = None
    quality_log_connected = quality_delta_count > 0 and bool(quality_sqlite_rows)
    ok = (
        engine_rc == 0
        and phase == "closed"
        and terminal_reason in CANON_ALLOWED_TERMINAL
        and bool(accepted)
        and final_zip.exists()
        and quality_log_connected
    )
    summary = {
        "status": "ok" if ok else "failed",
        "run_dir": str(run_dir),
        "profile": profile_name,
        "phase": phase,
        "terminal_reason": terminal_reason,
        "accepted_evidence": accepted,
        "final_zip_exists": final_zip.exists(),
        "quality_delta_count": quality_delta_count,
        "quality_sqlite_rows": quality_sqlite_rows,
        "quality_log_connected": quality_log_connected,
        "internal_loop": state.get("internal_loop", internal_summary),
        "residual_debt": state.get("residual_debt", []),
        "canon_slot_plan": "CANON_SLOT_PLAN.json",
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if ok else 2


def _print_status(args: argparse.Namespace) -> int:
    run_dir = Path(args.status).expanduser().resolve()
    state = load_state(run_dir) if (run_dir / "cycle_state.json").exists() else {}
    print(json.dumps({
        "run_dir": str(run_dir),
        "phase": state.get("current_phase"),
        "terminal_reason": state.get("terminal_reason"),
        "internal_loop": state.get("internal_loop"),
        "residual_debt": state.get("residual_debt", []),
    }, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Canonical Camino Nocturno entrypoint (delegates to the mutable canon runtime).",
    )
    # Canonical flags (spec §5/§6/§7).
    ap.add_argument("--canon-profile", choices=["with_claude", "without_claude", "sandbox_reference"], default="",
                    help="Runtime profile from CANON_RUNTIME_POLICY. If omitted: ask (interactive) or fail closed (CI).")
    ap.add_argument("--canon-dir", default="", help="Directory with CANON_* files (defaults to packaged canon/).")
    ap.add_argument("--execute-workers", action="store_true",
                    help="Execute supported local workers inline and run the internal agentic loop.")
    ap.add_argument("--ci-default-profile", action="store_true",
                    help="Non-interactive opt-in to the canon's documented default_profile (spec §9).")
    ap.add_argument("--no-internal-loop", action="store_true",
                    help="Skip the internal agentic loop (phase engine only).")
    # Target / runs.
    ap.add_argument("--input", default="", help="Target file or directory to audit.")
    ap.add_argument("--target", default="", help="Alias of --input.")
    ap.add_argument("--drive-bus-root", default="", help="Runs directory (compat alias of --runs-dir).")
    ap.add_argument("--runs-dir", default=str(ROOT / "CAMINO_RUNS"), help="Runs directory.")
    ap.add_argument("--shared-root", default="", help="Immutable Google Drive/Gateway exchange root.")
    ap.add_argument("--execution-host", choices=["auto", "local", "macbook", "imac"], default="auto")
    ap.add_argument("--lmstudio-base-url", default="", help="Explicit LM Studio endpoint override.")
    ap.add_argument("--candidate-name", default="", help="Compat alias used as run label.")
    ap.add_argument("--run-label", default="", help="Run label.")
    ap.add_argument("--target-version", default="", help="Accepted for compat; ignored by the canon runtime.")
    # Watcher / phase engine.
    ap.add_argument("--watch-interval-seconds", type=int, default=1)
    ap.add_argument("--watch-timeout-minutes", type=int, default=480)
    ap.add_argument("--max-iterations", type=int, default=1)
    ap.add_argument("--no-start-watcher", action="store_true", help="Create the run but do not drive the phase engine.")
    # Introspection / escape hatch.
    ap.add_argument("--status", default="", help="Print status JSON for an existing run dir.")
    ap.add_argument("--legacy", action="store_true",
                    help="Delegate to the preserved monolith (run_multiaudit_cycle_legacy.py).")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Escape hatch: forward everything after --legacy to the preserved monolith.
    if "--legacy" in argv:
        argv.remove("--legacy")
        from scripts import run_multiaudit_cycle_legacy as legacy
        old = sys.argv
        try:
            sys.argv = ["run_multiaudit_cycle_legacy.py", *argv]
            return legacy.main()
        finally:
            sys.argv = old

    args = build_parser().parse_args(argv)
    if args.status:
        return _print_status(args)
    return canonical_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
