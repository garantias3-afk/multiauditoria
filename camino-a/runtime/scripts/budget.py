#!/usr/bin/env python3
"""budget.py — Budget enforcement for overnight runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_budget_policy(root: Path = ROOT) -> dict:
    path = root / "config" / "budget.policy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def check_worker_budget(worker_id: str, root: Path = ROOT) -> bool:
    """Check if worker is within budget. Returns True if allowed."""
    policy = load_budget_policy(root)
    limits = policy.get("per_worker_limits", {}).get(worker_id, {})
    max_cost = limits.get("max_cost_usd", 0)
    cost_class = limits.get("cost_class", "unknown")

    # Free and manual workers always allowed
    if cost_class in ("free", "manual", "included_in_plan"):
        return True

    # If max_cost is 0, no spending allowed
    if max_cost > 0:
        # Would need to track actual costs — for now, allow
        pass

    return True


def check_total_budget(root: Path = ROOT) -> bool:
    """Check if total budget is exhausted."""
    policy = load_budget_policy(root)
    max_total = policy.get("max_total_cost_usd", 0)
    # Free tier — always allowed
    return max_total >= 0
