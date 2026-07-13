#!/usr/bin/env python3
"""event_log.py — Append-only event logging."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def append_event(log_path: Path, event: str, data: Any = None) -> None:
    """Append an event to a JSONL log file."""
    import datetime as dt
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "event": event,
    }
    if data:
        record["data"] = data
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_events(log_path: Path, limit: int = 100) -> list[dict]:
    """Read recent events from a JSONL log file."""
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    events = []
    for line in lines[-limit:]:
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events
