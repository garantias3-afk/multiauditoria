#!/usr/bin/env python3
"""Run a controlled, real slot-14 Claude→Codex subscription smoke.

The fixture contains no user data or secrets.  It begins with slots 1–13 marked
complete, uses the canonical ``without_claude`` profile to exercise the recorded
Claude-unavailable fallback, and invokes the real Codex CLI through the same
master/worker path used by Camino A.  Success requires terminal authority to
accept the hash-bound Sol/Ultra subscription result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.camino_a_worker_bus import prepare_worker_bus
from scripts.candidate_updates import hash_candidate_tree
from scripts.canon_loader import load_canon, resolve_profile
from scripts.overnight_master import (
    _canonical_slot_iteration,
    has_clean_slot14_codex_fallback_approval,
)
from scripts.run_multiaudit_cycle import save_state, write_json
from scripts.slot_runtime import build_slot_plan
from scripts.state_db import StateDB


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _write_fixture(root: Path) -> None:
    files = {
        "README.md": (
            "# Slot 14 subscription smoke\n\n"
            "Controlled fixture: add(2, 3) must equal 5. No external access.\n"
        ),
        "smoke_math.py": "def add(left: int, right: int) -> int:\n    return left + right\n",
        "test_smoke_math.py": (
            "from smoke_math import add\n\n"
            "def test_addition():\n    assert add(2, 3) == 5\n"
        ),
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _prior_slot_history(candidate_sha256: str) -> list[dict]:
    """Build explicit, hash-bound receipts for the controlled slots 1-13 fixture."""
    return [
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "event": "canonical_slot_completed",
            "slot_id": str(slot_id),
            "evidence": [{
                "lane": "slot14_subscription_smoke_fixture",
                "bundle": f"INPUT/target_snapshot#slot-{slot_id}",
                "route_id": "controlled_fixture_precondition",
                "status": "ok",
                "findings_count": 0,
                "residual_debt_count": 0,
                "candidate_sha256": candidate_sha256,
            }],
        }
        for slot_id in range(1, 14)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(ROOT / "outputs" / "operational_runs"))
    parser.add_argument("--max-attempts", type=int, default=1)
    args = parser.parse_args()

    if os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        print(json.dumps({"status": "blocked", "reason": "forbidden_api_key_present"}))
        return 2

    run_id = f"RUN_{_utc_stamp()}_{uuid.uuid4().hex[:5]}_slot14_subscription_smoke"
    run_dir = Path(args.output_root).expanduser().resolve() / run_id
    baseline = run_dir / "INPUT" / "target_snapshot"
    candidate = run_dir / "00_CANDIDATE"
    baseline.mkdir(parents=True)
    candidate.mkdir(parents=True)
    (run_dir / "STATE").mkdir()
    _write_fixture(baseline)
    _write_fixture(candidate)
    prepare_worker_bus(run_dir)

    candidate_sha = hash_candidate_tree(candidate)
    state = {
        "run_id": run_id,
        "run_label": "slot14_subscription_smoke",
        "current_phase": "running",
        "current_candidate_sha256": candidate_sha,
        "target_sha256": candidate_sha,
        "completed_slots": [str(value) for value in range(1, 14)],
        "current_slot": "14",
        "iteration_number": 0,
        "candidate_version": 1,
        "history": _prior_slot_history(candidate_sha),
        "residual_debt": [],
    }
    save_state(run_dir, state)

    bundle = load_canon(ROOT)
    profile = resolve_profile(bundle, "without_claude")
    state["runtime_profile"] = profile
    plan = build_slot_plan(bundle, profile).to_serializable()
    db = StateDB(run_dir / "STATE" / "state.sqlite")
    db.upsert_run(run_id, target_sha256=candidate_sha, state="running")
    try:
        result = _canonical_slot_iteration(
            run_dir,
            state,
            profile,
            plan,
            bundle.routes,
            db,
            dry_run=False,
            execute_workers=True,
            max_attempts=max(1, args.max_attempts),
        )
    finally:
        db.close()
    save_state(run_dir, state)
    terminal_clean = has_clean_slot14_codex_fallback_approval(run_dir, state)
    report = {
        "schema_version": "camino_slot14_subscription_smoke.v1",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "candidate_sha256": candidate_sha,
        "result": result,
        "terminal_clean_codex_fallback": terminal_clean,
        "operator_action_required": (
            run_dir / "STATE" / "SLOT14_OPERATOR_ACTION_REQUIRED.json"
        ).is_file(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(run_dir / "SLOT14_SUBSCRIPTION_SMOKE_RESULT.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if terminal_clean else 2


if __name__ == "__main__":
    raise SystemExit(main())
