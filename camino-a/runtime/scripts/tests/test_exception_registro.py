"""Tests for exception_registro — OT sec 4 (E1) / G1."""
from __future__ import annotations

import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.exception_registro import (  # noqa: E402
    EXCERPT_MAX_BYTES, EXPECTED_FIELDS, TRUNCATED_MARKER, build_registro,
)


def test_has_the_11_fields() -> None:
    r = build_registro(slot="1", puesto="auditores", route_id="r",
                       fase="despacho", clase="net.timeout",
                       expected="un artefacto JSON", excerpt="TimeoutError: timed out")
    d = r.to_dict()
    for f in EXPECTED_FIELDS:
        assert f in d, f"missing field {f}"
    assert len(EXPECTED_FIELDS) == 11


def test_excerpt_under_cap_is_intact() -> None:
    short = "TimeoutError: timed out after 30s"
    r = build_registro(slot="1", puesto="p", route_id="r", fase="despacho",
                       clase="net.timeout", expected="x", excerpt=short)
    assert r.excerpt == short


def test_excerpt_over_cap_is_truncated_and_marked() -> None:
    """G1: excerpt is capped at 512 BYTES and marked as truncated."""
    big = "A" * 5000
    r = build_registro(slot="1", puesto="p", route_id="r", fase="escritura",
                       clase="fmt.json_malformed", expected="valid JSON", excerpt=big)
    b = r.excerpt.encode("utf-8", errors="replace")
    assert len(b) <= EXCERPT_MAX_BYTES
    assert r.excerpt.endswith(TRUNCATED_MARKER) or TRUNCATED_MARKER in r.excerpt


def test_excerpt_byte_cap_not_char_cap() -> None:
    """The cap is BYTES: multibyte content must be measured by bytes."""
    # 200 chars of 3-byte chars = 600 bytes > 512.
    big = "ñ" * 200
    r = build_registro(slot="1", puesto="p", route_id="r", fase="validacion",
                       clase="fmt.encoding", expected="utf-8", excerpt=big)
    assert len(r.excerpt.encode("utf-8", errors="replace")) <= EXCERPT_MAX_BYTES


def test_found_carries_path_size_hash_not_content() -> None:
    """G1/§4: `found` has path/size/hash, NEVER the file content."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".json") as tf:
        tf.write(b'{"secret": "DO_NOT_LEAK"}')
        p = Path(tf.name)
    try:
        r = build_registro(slot="1", puesto="p", route_id="r", fase="escritura",
                           clase="fmt.json_malformed", expected="valid JSON",
                           excerpt="x", found_path=p)
        assert "path=" in r.found
        assert "size=" in r.found
        assert "sha256_16=" in r.found
        # The CONTENT must never appear in `found`.
        assert "DO_NOT_LEAK" not in r.found
    finally:
        p.unlink(missing_ok=True)


def test_found_missing_path_records_exists_false() -> None:
    r = build_registro(slot="1", puesto="p", route_id="r", fase="recoleccion",
                       clase="fs.path_missing", expected="artifact present",
                       excerpt="x", found_path=Path("/no/such/file_xyz.json"))
    assert "exists=false" in r.found


def test_found_with_http_code() -> None:
    r = build_registro(slot="1", puesto="p", route_id="r", fase="despacho",
                       clase="net.rate_limited", expected="200 OK",
                       excerpt="x", http_code=429)
    assert "http=429" in r.found


def test_fase1_defaults_no_repair() -> None:
    """G3: FASE 1 does not repair. resolution=NONE, handler_tried empty."""
    r = build_registro(slot="1", puesto="p", route_id="r", fase="gate",
                       clase="sem.orphan_claim", expected="grounded claim", excerpt="x")
    assert r.resolution == "NONE"
    assert r.handler_tried == ""
