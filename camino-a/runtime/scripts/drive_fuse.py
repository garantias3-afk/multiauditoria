"""drive_fuse.py — Google Drive FUSE integration helpers.

Handles:
- Detecting FUSE mounts
- Safe atomic writes on FUSE (copy-then-rename)
- FUSE-aware mtime comparison
- Detecting sync conflicts
"""
from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any


def is_fuse_mount(path: Path) -> bool:
    """Check if a path is on a FUSE mount (Google Drive, etc.)."""
    try:
        st = os.statvfs(str(path))
        # FUSE mounts often have different characteristics
        # Check for known mount points
        mount_check = str(path)
        fuse_indicators = [
            "Google Drive",
            "GoogleDrive",
            "google-drive",
            "gdrive",
            "/Volumes/GoogleDrive",
            "/mnt/gdrive",
            "/fuse",
        ]
        return any(indicator in mount_check for indicator in fuse_indicators)
    except OSError:
        return False


def fuse_safe_write(path: Path, content: bytes | str, *, encoding: str = "utf-8") -> None:
    """Write to a FUSE mount safely using copy-then-rename pattern.

    On FUSE, direct writes can be partially synced. This writes to a
    temp file first, then atomically renames.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")

    try:
        if isinstance(content, str):
            tmp.write_text(content, encoding=encoding)
        else:
            tmp.write_bytes(content)

        # Fsync the temp file
        try:
            fd = os.open(str(tmp), os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass

        # Atomic rename
        os.replace(str(tmp), str(path))

        # Fsync parent directory
        try:
            fd = os.open(str(path.parent), os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
        except OSError:
            pass
    finally:
        tmp.unlink(missing_ok=True)


def fuse_safe_json_write(path: Path, data: dict) -> None:
    """Write JSON safely to FUSE mount."""
    import json
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fuse_safe_write(path, content)


def fuse_mtime_compare(path_a: Path, path_b: Path) -> int:
    """Compare mtimes accounting for FUSE sync delays.

    Returns:
        -1 if a < b (a written before b)
         0 if a == b (within tolerance)
         1 if a > b (a written after b)

    On FUSE, mtimes may reflect upload time, not write time.
    A tolerance of 2 seconds is applied.
    """
    FUSE_MTIME_TOLERANCE_NS = 2_000_000_000  # 2 seconds in nanoseconds

    mtime_a = path_a.stat().st_mtime_ns
    mtime_b = path_b.stat().st_mtime_ns

    diff = mtime_a - mtime_b
    if abs(diff) <= FUSE_MTIME_TOLERANCE_NS:
        return 0
    return -1 if diff < 0 else 1


def fuse_wait_for_sync(path: Path, timeout_seconds: float = 30.0, poll_seconds: float = 1.0) -> bool:
    """Wait for a file to be fully synced on FUSE.

    Checks that the file exists, is readable, and its size is stable
    for at least poll_seconds.
    """
    deadline = time.monotonic() + timeout_seconds
    last_size = -1
    stable_since = 0.0

    while time.monotonic() < deadline:
        if not path.exists():
            time.sleep(poll_seconds)
            continue

        current_size = path.stat().st_size
        if current_size == last_size:
            if stable_since == 0.0:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= poll_seconds:
                return True  # Stable
        else:
            last_size = current_size
            stable_since = 0.0

        time.sleep(poll_seconds)

    return False


def fuse_detect_conflict(path: Path) -> bool:
    """Detect if a file has a conflict marker (Google Drive conflict)."""
    if not path.exists():
        return False

    name = path.name
    # Google Drive conflict patterns
    conflict_patterns = [
        " (Conflicto",
        " (conflicto",
        " (conflict",
        " (Conflict",
        " - Conflicto",
    ]
    return any(p in name for p in conflict_patterns)


def fuse_resolve_conflicts(directory: Path) -> list[dict]:
    """Find and report conflict files in a directory."""
    conflicts = []
    for item in directory.rglob("*"):
        if item.is_file() and fuse_detect_conflict(item):
            conflicts.append({
                "path": str(item),
                "name": item.name,
                "size": item.stat().st_size,
            })
    return conflicts
