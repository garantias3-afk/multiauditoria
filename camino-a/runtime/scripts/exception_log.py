"""exception_log.py — append-only exception log (OT sec 4 / E3, G6).

REUSES fuse_safe_write (drive_fuse.py:40). Does NOT write a new atomic-write
primitive (OT sec 13). The log is one canonical-JSON line per registro, written
atomically per append so a crash mid-run never corrupts prior entries.

Atomicity strategy: read current bytes (if any) + new line, write the whole
file atomically. This is safe for our append volumes (one line per exception,
not high frequency). For very large logs this would switch to a tmp+rename
on a rotating basis; out of scope for FASE 1.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

# Reused primitive — declared by original path in the report (G6).
from scripts.drive_fuse import fuse_safe_write  # noqa: E402  (drive_fuse.py:40)
from scripts.exception_registro import ExceptionRegistro

LOG_FILENAME = "exceptions.jsonl"


class ExceptionLog:
    """Append-only JSONL log of exception registros.

    Each append rewrites the file via fuse_safe_write so the on-disk file is
    always complete and consistent (atomic replace). Reads are line-by-line.
    """

    def __init__(self, run_dir: Path, *, filename: str = LOG_FILENAME):
        self.path = Path(run_dir) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            # Initialize an empty file atomically so reads never fail.
            fuse_safe_write(self.path, "")

    def reset(self) -> None:
        """Truncate the log to empty, atomically.

        Production logging is append-only (never lose an observation). This is
        for MEASUREMENT tools (the fault-injection harness) that need each run
        to reflect only that run's data, not accumulated history.
        """
        fuse_safe_write(self.path, "")

    def append(self, registro: ExceptionRegistro) -> None:
        """Append one registro as one canonical JSON line, atomically.

        Canonical JSON (sorted keys, no extra whitespace) so the log is
        diff-stable and a partial write is detectable on reload.
        """
        line = json.dumps(registro.to_dict(), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
        existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        # Ensure prior content ends with a newline before we add ours.
        if existing and not existing.endswith("\n"):
            existing += "\n"
        fuse_safe_write(self.path, existing + line + "\n")

    def append_many(self, registros: Iterable[ExceptionRegistro]) -> int:
        """Append several registros in one atomic write. Returns count."""
        regs = list(registros)
        if not regs:
            return 0
        lines = [
            json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
            for r in regs
        ]
        existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        fuse_safe_write(self.path, existing + "\n".join(lines) + "\n")
        return len(regs)

    def read_all(self) -> list[dict]:
        """Read every registro line. Skips blank/corrupt lines defensively."""
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A corrupt line means a prior write was interrupted despite
                # atomicity guarantees (e.g. disk full mid-replace). Record
                # the anomaly but never crash the read.
                out.append({"_corrupt_line": line[:120]})
        return out

    def class_distribution(self) -> dict[str, int]:
        """Tally registros by clase. Used for the G7 UNMAPPED-rate report."""
        counts: dict[str, int] = {}
        for r in self.read_all():
            if "_corrupt_line" in r:
                continue
            c = str(r.get("clase") or "UNMAPPED_CONDITION")
            counts[c] = counts.get(c, 0) + 1
        return counts

    def count(self) -> int:
        return len(self.read_all())
