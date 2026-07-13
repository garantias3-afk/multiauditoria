#!/usr/bin/env python3
"""hash_tree.py — Merkle-tree style hashing for directories."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path) -> str:
    """Compute a Merkle-style hash of a directory tree."""
    if not root.exists():
        return hashlib.sha256(b"").hexdigest()

    entries = []
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            continue
        rel = item.relative_to(root)
        if item.is_file():
            entries.append(f"F:{rel}:{sha256_file(item)}")
        elif item.is_dir():
            entries.append(f"D:{rel}")

    combined = "\n".join(entries)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def verify_manifest_files(root: Path, manifest: list[dict]) -> list[str]:
    """Verify files against a manifest. Returns list of errors."""
    errors = []
    for entry in manifest:
        path = root / entry["path"]
        if not path.exists():
            errors.append(f"missing:{entry['path']}")
            continue
        if path.is_symlink():
            errors.append(f"symlink:{entry['path']}")
            continue
        actual = sha256_file(path)
        expected = entry.get("sha256", "")
        if actual.lower() != expected.lower():
            errors.append(f"sha_mismatch:{entry['path']}")
    return errors
