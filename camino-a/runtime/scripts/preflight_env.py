#!/usr/bin/env python3
"""preflight_env.py — Pre-flight environment checks.

Validates that the environment is ready for an overnight run:
- Python version
- Required directories
- Disk space
- Forbidden API keys not present
- SQLite available
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_python() -> bool:
    v = sys.version_info
    # The runtime intentionally supports the system Python shipped by both
    # Macs.  All production modules and tests must remain Python 3.9 compatible.
    ok = v >= (3, 9)
    print(f"  Python {v.major}.{v.minor}.{v.micro}: {'OK' if ok else 'FAIL (need 3.9+)'}")
    return ok


def check_claude_cli(*, require_auth: bool) -> bool:
    executable = shutil.which("claude")
    if not executable:
        print("  Claude CLI: not installed")
        return not require_auth
    try:
        import json
        cp = subprocess.run(
            [executable, "auth", "status"], capture_output=True, text=True,
            timeout=10, env={k: v for k, v in os.environ.items()
                             if k != "ANTHROPIC_API_KEY"},
        )
        payload = json.loads(cp.stdout or "{}")
        logged_in = cp.returncode == 0 and payload.get("loggedIn") is True
    except Exception:
        logged_in = False
    label = "authenticated" if logged_in else "NOT authenticated"
    print(f"  Claude CLI: {label} ({executable})")
    return logged_in if require_auth else True


def check_sqlite_wal() -> bool:
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as f:
            db = sqlite3.connect(f.name)
            db.execute("PRAGMA journal_mode=WAL")
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            db.close()
            ok = mode.upper() == "WAL"
            print(f"  SQLite WAL: {'OK' if ok else 'FAIL'} (mode={mode})")
            return ok
    except Exception as e:
        print(f"  SQLite WAL: FAIL ({e})")
        return False


def check_disk_space(min_gb: float = 1.0) -> bool:
    stat = shutil.disk_usage(ROOT)
    free_gb = stat.free / (1024 ** 3)
    ok = free_gb >= min_gb
    print(f"  Disk space: {'OK' if ok else 'FAIL'} ({free_gb:.1f} GB free, need {min_gb} GB)")
    return ok


def check_no_forbidden_keys() -> bool:
    forbidden = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    found = forbidden & set(os.environ.keys())
    if found:
        print(f"  Forbidden API keys found: {found}")
        return False
    print("  No forbidden API keys: OK")
    return True


def check_root_structure() -> bool:
    required = ["scripts", "config", "contracts", "schemas"]
    missing = [d for d in required if not (ROOT / d).is_dir()]
    if missing:
        print(f"  Missing directories: {missing}")
        return False
    print(f"  Project structure: OK")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flight environment checks")
    parser.add_argument("--min-disk-gb", type=float, default=1.0)
    parser.add_argument("--profile", choices=["with_claude", "without_claude"],
                        default="with_claude")
    args = parser.parse_args()

    print("Camino A Overnight — Preflight Checks")
    print("=" * 40)

    checks = [
        ("Python version", check_python),
        ("SQLite WAL", check_sqlite_wal),
        ("Disk space", lambda: check_disk_space(args.min_disk_gb)),
        ("No forbidden API keys", check_no_forbidden_keys),
        ("Claude CLI", lambda: check_claude_cli(require_auth=args.profile == "with_claude")),
        ("Project structure", check_root_structure),
    ]

    results = []
    for name, fn in checks:
        print(f"\n[{name}]")
        try:
            results.append(fn())
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append(False)

    print("\n" + "=" * 40)
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} checks passed")

    if all(results):
        print("PREFLIGHT OK — ready to run")
        return 0
    else:
        print("PREFLIGHT FAILED — fix issues above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
