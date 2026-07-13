#!/usr/bin/env python3
"""retry_policy.py — Retry logic with backoff."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_retry_policy(root: Path = ROOT) -> dict:
    path = root / "config" / "roles.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("retry_policy", {})


def should_retry(error_type: str, attempt: int, root: Path = ROOT) -> bool:
    """Determine if an operation should be retried."""
    policy = load_retry_policy(root)

    limits = {
        "transient": policy.get("transient_max_retries", 2),
        "quota": policy.get("quota_max_retries", 0),
        "auth": policy.get("auth_max_retries", 0),
        "contract_error": policy.get("contract_error_max_retries", 0),
        "worker_timeout": policy.get("worker_timeout_max_retries", 1),
    }

    max_retries = limits.get(error_type, 0)
    return attempt < max_retries


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 300.0) -> float:
    """Calculate exponential backoff delay."""
    delay = base * (2 ** min(attempt, 6))
    return min(delay, cap)
