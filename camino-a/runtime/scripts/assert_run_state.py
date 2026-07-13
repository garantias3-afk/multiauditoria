#!/usr/bin/env python3
"""assert_run_state.py — Assert run state for B-1 manual probe.

Usage:
    python3 scripts/assert_run_state.py --run RUN_DIR \
        --not-phase closed --expect-no-accepted

Exits 0 if assertions pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--not-phase", action="append", default=[],
                        help="Phase that the run must NOT be in")
    parser.add_argument("--expect-phase", default=None,
                        help="Phase that the run MUST be in")
    parser.add_argument("--expect-no-accepted", action="store_true",
                        help="ACCEPTED/ must be empty")
    parser.add_argument("--expect-terminal-reason", default=None,
                        help="Terminal reason must match")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    # El runtime escribe el state en dos ubicaciones (legado): raíz del run y
    # 01_STATE/. La raíz es la autoritativa (cf. load_state en
    # run_multiaudit_cycle_legacy.py). Toleramos ambas para no romper si la
    # doble escritura se elimina en el futuro. Patrón idéntico al de
    # launch_sandbox.py.
    state_path = run_dir / "cycle_state.json"
    if not state_path.exists():
        state_path = run_dir / "01_STATE" / "cycle_state.json"
    if not state_path.exists():
        print(f"FAIL: state file not found under: {run_dir}", file=sys.stderr)
        return 1
    state = json.loads(state_path.read_text())
    phase = state.get("current_phase")
    terminal_reason = state.get("terminal_reason")

    failures = []
    if args.expect_phase and phase != args.expect_phase:
        failures.append(f"phase={phase}, expected={args.expect_phase}")
    if args.not_phase and phase in args.not_phase:
        failures.append(f"phase={phase}, must NOT be in {args.not_phase}")
    if args.expect_terminal_reason and terminal_reason != args.expect_terminal_reason:
        failures.append(
            f"terminal_reason={terminal_reason}, "
            f"expected={args.expect_terminal_reason}"
        )
    if args.expect_no_accepted:
        accepted = run_dir / "ACCEPTED"
        if accepted.exists() and any(accepted.iterdir()):
            failures.append(
                f"ACCEPTED not empty: {[p.name for p in accepted.iterdir()]}"
            )

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"OK: phase={phase} terminal_reason={terminal_reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
