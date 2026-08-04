"""Tests for exception_taxonomy — OT sec 5 / G7."""
from __future__ import annotations

import errno
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.exception_taxonomy import (  # noqa: E402
    CLASSES, UNMAPPED, Classification, classify_from_signal, unmapped_rate,
)


# ----- the real worker_gateway._post_json signal shapes ----- #

def test_http_429_is_rate_limited() -> None:
    c = classify_from_signal("http_429")
    assert c.clase == "net.rate_limited"
    assert c.family == "net"


def test_http_5xx_is_server_error() -> None:
    assert classify_from_signal("http_502").clase == "net.server_error"
    assert classify_from_signal("http_503").clase == "net.server_error"
    assert classify_from_signal("http_500").clase == "net.server_error"


def test_http_401_403_is_auth_failed() -> None:
    assert classify_from_signal("http_401").clase == "net.auth_failed"
    assert classify_from_signal("http_403").clase == "net.auth_failed"


def test_http_404_is_model_not_found() -> None:
    assert classify_from_signal("http_404").clase == "net.model_not_found"


def test_timeout_signal() -> None:
    assert classify_from_signal("TimeoutError: timed out").clase == "net.timeout"
    assert classify_from_signal("URLError: timeout").clase == "net.timeout"


def test_invalid_json_response_is_json_malformed() -> None:
    c = classify_from_signal("invalid_json_response:<html>bad</html>")
    assert c.clase == "fmt.json_malformed"


def test_gateway_response_too_large_is_truncated_response() -> None:
    assert classify_from_signal("gateway_response_too_large").clase == "fmt.truncated_response"


# ----- filesystem signals (from raised exceptions) ----- #

def test_enospc_is_disk_full() -> None:
    e = OSError(errno.ENOSPC, "No space left on device")
    assert classify_from_signal(str(e), exc=e).clase == "fs.disk_full"


def test_permission_error_is_permission_denied() -> None:
    e = PermissionError(13, "Permission denied")
    assert classify_from_signal(str(e), exc=e).clase == "fs.permission_denied"


def test_file_not_found_is_path_missing() -> None:
    e = FileNotFoundError(2, "No such file or directory")
    assert classify_from_signal(str(e), exc=e).clase == "fs.path_missing"


def test_mount_absent_signal() -> None:
    assert classify_from_signal("INTERCAMBIO_SHARE_UNAVAILABLE: no markers").clase == "fs.mount_absent"


def test_partial_write_signal() -> None:
    assert classify_from_signal("orphan .partial present").clase == "fs.partial_write"


# ----- unknown -> UNMAPPED with raw_condition preserved ----- #

def test_unknown_signal_is_unmapped_with_raw_preserved() -> None:
    c = classify_from_signal("quantum_flux_anomaly_detected")
    assert c.is_unmapped
    assert c.clase == UNMAPPED
    assert "quantum_flux_anomaly_detected" in c.raw_condition


def test_empty_signal_is_unmapped() -> None:
    assert classify_from_signal("").is_unmapped


# ----- G7: unmapped rate ----- #

def test_unmapped_rate_zero_when_all_mapped() -> None:
    counts = {"net.timeout": 5, "fs.path_missing": 3}
    assert unmapped_rate(counts) == 0.0


def test_unmapped_rate_above_20pct_detected() -> None:
    counts = {"net.timeout": 3, UNMAPPED: 2}  # 2/5 = 40%
    assert unmapped_rate(counts) == 0.4
    assert unmapped_rate(counts) > 0.20  # taxonomy must be revised


# ----- the enum is closed and versioned ----- #

def test_enum_is_closed_and_unmapped_present() -> None:
    assert UNMAPPED in CLASSES
    assert len(CLASSES) == 20  # 19 named + UNMAPPED
    # families covered (UNMAPPED_CONDITION is its own "family")
    fams = {c.split(".", 1)[0] if "." in c else c for c in CLASSES}
    assert {"fs", "net", "fmt", "sem", "UNMAPPED_CONDITION"} == fams
