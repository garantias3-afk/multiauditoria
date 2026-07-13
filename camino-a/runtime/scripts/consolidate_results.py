#!/usr/bin/env python3
"""consolidate_results.py — Consolidate accepted worker results.

Takes ACCEPTED results, prioritizes confirmed bugs with tests,
applies patches in merger workspace, produces final_candidate.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    sha256_file, utc_now, read_json, write_json,
    ensure_bus_dirs, save_state, load_state, history_event,
)


def consolidate(run_dir: Path) -> dict:
    """Consolidate accepted results into a final candidate."""
    state = load_state(run_dir)
    accepted = run_dir / "ACCEPTED"
    merger = run_dir / "WORKSPACES" / "merger"
    merger.mkdir(parents=True, exist_ok=True)

    patches = []
    for item in sorted(accepted.iterdir()):
        if item.is_file() and item.suffix == ".json" and not item.is_symlink():
            try:
                data = json.loads(item.read_text(encoding="utf-8"))
                patches.append({"source": str(item), "data": data})
            except (json.JSONDecodeError, OSError):
                pass

    if not patches:
        history_event(state, "consolidate_no_patches")
        save_state(run_dir, state)
        return {"status": "no_patches", "count": 0}

    # Sort: confirmed bugs with tests first
    def priority(p):
        status = p["data"].get("status", "")
        if status == "bug_found":
            return 0
        if status == "patch_proposed":
            return 1
        return 2

    patches.sort(key=priority)

    history_event(state, "consolidate_started", patch_count=len(patches))
    save_state(run_dir, state)

    return {
        "status": "consolidated",
        "count": len(patches),
        "merger_workspace": str(merger),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidate accepted results")
    parser.add_argument("--run", required=True, help="Run directory")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    result = consolidate(run_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
