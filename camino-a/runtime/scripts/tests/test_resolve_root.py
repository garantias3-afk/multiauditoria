"""Tests for resolve_root — FASE 2 primitive (OT G2).

The load-bearing test is test_rejects_root_with_correct_name_but_no_markers:
that is the exact failure mode of OT v1 on the MBP (1-ago-2026), where a
directory named "Intercambio" existed locally with different content and was
wrongly accepted.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the runtime package importable when run directly.
RUNTIME = Path(__file__).resolve().parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from scripts.resolve_root import (  # noqa: E402
    CANINO_COMMONS_DIR,
    QUALITY_LOG_REL,
    IntercambioShareUnavailable,
    resolve_root,
    validate_root_markers,
)


def _make_valid_root(root: Path) -> None:
    """Build a root that carries BOTH markers, like the real Intercambio."""
    commons = root / CANINO_COMMONS_DIR
    commons.mkdir(parents=True)
    # Seven non-init modules, matching the real camino_commons layout.
    for name in (
        "adapters", "cost_class", "envelope", "identity",
        "ingest", "ledger", "reason_codes",
    ):
        (commons / f"{name}.py").write_text("# stub\n")
    qlog = root / QUALITY_LOG_REL
    qlog.parent.mkdir(parents=True, exist_ok=True)
    qlog.write_text("{}\n")


def _fake_detect(role: str):
    def _d(*a, **k):
        return {"role": role, "hostname": f"{role}-host"}
    return _d


def test_validates_real_markers(tmp_path: Path) -> None:
    _make_valid_root(tmp_path)
    assert validate_root_markers(tmp_path) == []


def test_rejects_root_with_correct_name_but_no_markers(tmp_path: Path) -> None:
    """G2 — the case that failed on 1-ago-2026.

    A dir literally named 'Intercambio' but missing both markers MUST be
    rejected. The name alone is never proof of the right root.
    """
    fake_intercambio = tmp_path / "Intercambio"
    fake_intercambio.mkdir()
    (fake_intercambio / "some_other_file.txt").write_text("unrelated content\n")

    problems = validate_root_markers(fake_intercambio)
    assert problems, "a dir named Intercambio without markers was wrongly accepted"
    # Both markers must be reported missing.
    joined = " ; ".join(problems)
    assert "MEGA_OT_WORK/camino_commons" in joined
    assert QUALITY_LOG_REL in joined


def test_resolves_via_override_when_valid(tmp_path: Path) -> None:
    _make_valid_root(tmp_path)
    env = {"CAMINO_INTERCAMBIO_ROOT": str(tmp_path)}
    # detect should not even be consulted when override is valid.
    got = resolve_root(
        detect=_fake_detect("macbook"),
        environ=env,
        volumes_dir=tmp_path / "no_volumes",
    )
    assert got == tmp_path


def test_override_with_wrong_content_falls_through_and_blocks(tmp_path: Path) -> None:
    """An override pointing at a marker-less dir is NOT trusted by name."""
    bogus = tmp_path / "Intercambio"
    bogus.mkdir()
    env = {"CAMINO_INTERCAMBIO_ROOT": str(bogus)}
    try:
        resolve_root(
            detect=_fake_detect("macbook"),
            environ=env,
            volumes_dir=tmp_path / "no_volumes",
        )
    except IntercambioShareUnavailable as exc:
        assert "override rejected" in str(exc)
    else:
        raise AssertionError("override without markers was silently accepted")


def test_imac_uses_local_home_when_markers_present(tmp_path: Path, monkeypatch) -> None:
    """On iMac the local /Users/mariano/Intercambio is the root IF marked.

    We monkeypatch the iMac default root to a tmp path so the test does not
    depend on (nor mutate) the real machine layout.
    """
    import scripts.resolve_root as rr
    fake_home = tmp_path / "home_int"
    _make_valid_root(fake_home)
    monkeypatch.setattr(rr, "_imac_default_root", lambda: fake_home)
    got = resolve_root(detect=_fake_detect("imac"), environ={}, volumes_dir=tmp_path / "none")
    assert got == fake_home


def test_macbook_enumerates_volumes_without_assuming_name(tmp_path: Path) -> None:
    """On macbook we scan /Volumes/* — the share name must not be assumed.

    Mirrors OT section 0: 'ls /Volumes sin asumir nombre de volumen'.
    """
    volumes = tmp_path / "Volumes"
    volumes.mkdir()
    # A volume with a non-obvious name carrying a VALID Intercambio.
    weird_vol = volumes / "DiscoDeMariano"
    good = weird_vol / "Users/mariano/Intercambio"
    _make_valid_root(good)
    # A decoy volume literally named Intercambio but WITHOUT markers (the v1
    # trap). It must not win.
    decoy_vol = volumes / "Intercambio"
    (decoy_vol / "Users/mariano/Intercambio").mkdir(parents=True)

    got = resolve_root(
        detect=_fake_detect("macbook"),
        environ={},
        volumes_dir=volumes,
    )
    assert got == good


def test_ambiguity_blocks(tmp_path: Path) -> None:
    """Two equally-valid roots => ambiguous => block (do not guess)."""
    # First valid root via override candidate, second valid via enumeration.
    env_root = tmp_path / "a"
    _make_valid_root(env_root)
    volumes = tmp_path / "Volumes"
    volumes.mkdir()
    vol_root = volumes / "X" / "Users/mariano/Intercambio"
    _make_valid_root(vol_root)
    # Provide BOTH via the candidate list so both pass markers.
    try:
        resolve_root(
            detect=_fake_detect("macbook"),
            environ={},
            volumes_dir=volumes,
            extra_candidates=[env_root, vol_root],
        )
    except IntercambioShareUnavailable as exc:
        # It must report a block; it must not silently pick one.
        assert "candidate" in str(exc).lower() or "verif" in str(exc).lower()
        return
    # If only ONE of the two is reachable through the normal enumeration path,
    # resolution returning exactly that one is also acceptable. The hard rule
    # is: never return an unverified path. Re-assert that property.
    raise AssertionError("resolver returned without verifying against markers")


def test_absent_share_blocks_with_report(tmp_path: Path) -> None:
    """No candidate at all -> block, with a message naming what was tried."""
    try:
        resolve_root(
            detect=_fake_detect("macbook"),
            environ={},
            volumes_dir=tmp_path / "empty_volumes",
        )
    except IntercambioShareUnavailable as exc:
        msg = str(exc)
        assert "role=macbook" in msg or "no Intercambio candidate" in msg
        return
    raise AssertionError("expected IntercambioShareUnavailable when share absent")
