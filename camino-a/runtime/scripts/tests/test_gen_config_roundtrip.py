"""Tests for gen_camino_n_config — FASE 1 M1/M2 (G5 round-trip determinism).

The load-bearing test is test_roundtrip_two_generations_same_sha256: the tabla
is the source of truth and the JSON is its projection, so regenerating twice
from the same tabla MUST yield byte-identical output (same sha256). A
non-deterministic projection would defeat the whole point of M2.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.gen_camino_n_config import (  # noqa: E402
    build_projection, generate, serialize, sha256_of,
)
from scripts.tabla_loader import (  # noqa: E402
    ModelSpec, RouteAssignment, TablaConfig,
)


def _toy_cfg() -> TablaConfig:
    """A small, stable tabla for deterministic tests (no real xlsx needed)."""
    models = {
        "r_a": ModelSpec("r_a", "mod/a", "p1", "P1", "free", "fam", 30.0,
                         "relee", "simple"),
        "r_b": ModelSpec("r_b", "mod/b", "p2", "P2", "paid", "fam", 60.0,
                         "ejecuta", "simple"),
    }
    assignments = [
        RouteAssignment(1, "A", "auditores", "DETECT", "carrera", 1, "r_a",
                        "SKIP_STEP", "P1", "free", "fam", "VERIFICADO_64K",
                        10.0, 35.0, "relee", "", "carrera ultra"),
        RouteAssignment(1, "A", "auditores", "DETECT", "paralela", 0, "r_b",
                        "SKIP_STEP", "P2", "paid", "fam", "NO_CONSTA",
                        0.0, 60.0, "relee", "", "ola"),
    ]
    return TablaConfig(tabla_path=Path("/dev/null"), models=models,
                       assignments=tuple(assignments), loops={})


# ----- G5: determinism / round-trip ----- #

def test_roundtrip_two_generations_same_sha256(tmp_path: Path) -> None:
    """Two generations from the same tabla produce identical bytes."""
    cfg = _toy_cfg()
    proj1 = build_projection(cfg)
    proj2 = build_projection(cfg)
    assert serialize(proj1) == serialize(proj2)
    assert sha256_of(proj1) == sha256_of(proj2)


def test_generate_writes_deterministic_file(tmp_path: Path) -> None:
    """Writing twice to two paths gives byte-identical files."""
    cfg = _toy_cfg()
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    p1, h1 = generate(cfg.tabla_path, out1) if False else (out1, None)
    # `generate` loads from xlsx; for the toy cfg we write the projection
    # directly via serialize + fuse_safe_write to test the writer path.
    from scripts.drive_fuse import fuse_safe_write
    s1 = serialize(build_projection(cfg))
    s2 = serialize(build_projection(cfg))
    fuse_safe_write(out1, s1)
    fuse_safe_write(out2, s2)
    assert out1.read_bytes() == out2.read_bytes()
    assert hashlib.sha256(out1.read_bytes()).hexdigest() == \
           hashlib.sha256(out2.read_bytes()).hexdigest()


def test_no_timestamps_in_projection() -> None:
    """G5: a timestamp would break round-trip. Assert none of the unstable
    field names appear."""
    cfg = _toy_cfg()
    text = serialize(build_projection(cfg))
    for forbidden in ("updated_utc", "generated_at", "created_at", "now", "today"):
        assert forbidden not in text, f"non-deterministic field '{forbidden}' present"


def test_sorted_keys_stable() -> None:
    """Output uses sort_keys, so key order never depends on insertion order."""
    cfg = _toy_cfg()
    text = serialize(build_projection(cfg))
    # schema_version sorts before slots, which sorts before source_tabla_sheet
    # — confirm ordering is alphabetical at the top level.
    lines = [l for l in text.splitlines() if l.startswith('  "') and not l.startswith('    ')]
    keys = [l.split('"')[1] for l in lines]
    assert keys == sorted(keys)


# ----- shape mirrors the canon (M1 requirement) ----- #

def test_projection_has_canon_slot_shape() -> None:
    """Each slot mirrors CANON_WORKFLOW_SLOTS: cycle/role/loops/routes."""
    cfg = _toy_cfg()
    slots = build_projection(cfg)["slots"]
    s1 = slots["1"]
    for field in ("cycle", "role", "loops", "routes", "correction_policy"):
        assert field in s1, f"slot missing canon field '{field}'"
    assert s1["cycle"] == "A"
    assert s1["role"] == "auditores"
    assert set(s1["routes"]) == {"r_a", "r_b"}


def test_routes_grouped_by_tipo_deterministically() -> None:
    """carrera and paralela are grouped separately, deterministically ordered."""
    cfg = _toy_cfg()
    s1 = build_projection(cfg)["slots"]["1"]
    by_tipo = s1["routes_by_tipo"]
    assert [e["route_id"] for e in by_tipo["carrera"]] == ["r_a"]
    assert [e["route_id"] for e in by_tipo["paralela"]] == ["r_b"]


def test_models_project_stable_fields_only() -> None:
    """Models carry config fields (timeout, manos) but not telemetry (latency)."""
    cfg = _toy_cfg()
    models = build_projection(cfg)["models"]
    m = models["r_b"]
    assert m["timeout_s"] == 60.0
    assert m["manos"] == "ejecuta"
    assert "latencia" not in m and "latency" not in m
