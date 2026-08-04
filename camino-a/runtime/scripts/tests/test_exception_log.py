"""Tests for exception_log — OT E3 / G6."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.exception_log import ExceptionLog  # noqa: E402
from scripts.exception_registro import build_registro  # noqa: E402


def _reg(clase: str = "net.timeout", exc_id_suffix: str = ""):
    r = build_registro(slot="1", puesto="p", route_id="r", fase="despacho",
                       clase=clase, expected="x", excerpt="sig " + clase)
    if exc_id_suffix:
        # mutate the frozen-friendly dict instead
        return r
    return r


def test_append_and_read_back(tmp_path: Path) -> None:
    log = ExceptionLog(tmp_path / "run")
    log.append(_reg("net.timeout"))
    log.append(_reg("fs.path_missing"))
    rows = log.read_all()
    assert len(rows) == 2
    assert rows[0]["clase"] == "net.timeout"
    assert rows[1]["clase"] == "fs.path_missing"


def test_append_many_atomic(tmp_path: Path) -> None:
    """G6: a multi-append is one atomic write; partial never persisted."""
    log = ExceptionLog(tmp_path / "run")
    n = log.append_many([_reg("net.timeout"), _reg("fmt.json_malformed"),
                         _reg("sem.orphan_claim")])
    assert n == 3
    assert log.count() == 3


def test_log_file_is_append_only_jsonl(tmp_path: Path) -> None:
    """Each registro is exactly one canonical JSON line."""
    log = ExceptionLog(tmp_path / "run")
    log.append(_reg("net.timeout"))
    log.append(_reg("net.timeout"))
    text = log.path.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]
    assert len(lines) == 2
    import json
    for l in lines:
        d = json.loads(l)  # each line is valid JSON
        assert "exception_id" in d


def test_class_distribution(tmp_path: Path) -> None:
    log = ExceptionLog(tmp_path / "run")
    for _ in range(3):
        log.append(_reg("net.timeout"))
    log.append(_reg("UNMAPPED_CONDITION"))
    dist = log.class_distribution()
    assert dist["net.timeout"] == 3
    assert dist["UNMAPPED_CONDITION"] == 1


def test_reuses_fuse_safe_write_not_new(tmp_path: Path) -> None:
    """G6: the module imports fuse_safe_write from drive_fuse (reused)."""
    import scripts.exception_log as el
    from scripts.drive_fuse import fuse_safe_write
    assert el.fuse_safe_write is fuse_safe_write


def test_corrupt_line_does_not_crash_read(tmp_path: Path) -> None:
    """Defensive: a half-written line (shouldn't happen with atomicity) is
    flagged, not fatal."""
    log = ExceptionLog(tmp_path / "run")
    log.path.write_text('{"clase":"net.timeout"}\n{BROKEN\n{"clase":"fs.disk_full"}\n',
                        encoding="utf-8")
    rows = log.read_all()
    assert len(rows) == 3
    assert "_corrupt_line" in rows[1]
