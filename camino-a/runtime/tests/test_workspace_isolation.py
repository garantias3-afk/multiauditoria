from pathlib import Path

import pytest

from scripts.worker_claude_code import prepare_workspace as prepare_claude_workspace
from scripts.worker_codex import prepare_workspace as prepare_legacy_codex_workspace
from scripts.worker_codex_fallback import prepare_workspace as prepare_codex_workspace


def _assert_workspace_is_recreated_without_following_symlinks(
    tmp_path: Path, prepare,
) -> None:
    run = tmp_path / "RUN_workspace_isolation"
    snapshot = run / "INPUT" / "target_snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "base.py").write_text("SAFE = True\n", encoding="utf-8")
    outside = run / "cycle_state.json"
    outside.write_text("ORIGINAL\n", encoding="utf-8")

    workspace = prepare(run)
    (workspace / "base.py").unlink()
    (workspace / "base.py").symlink_to(outside)
    (workspace / "stale.py").write_text("stale = True\n", encoding="utf-8")

    recreated = prepare(run)
    assert outside.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert not (recreated / "base.py").is_symlink()
    assert (recreated / "base.py").read_text(encoding="utf-8") == "SAFE = True\n"
    assert not (recreated / "stale.py").exists()


def test_claude_workspace_is_fresh_per_attempt(tmp_path: Path) -> None:
    _assert_workspace_is_recreated_without_following_symlinks(
        tmp_path, prepare_claude_workspace,
    )


def test_codex_fallback_workspace_is_fresh_per_attempt(tmp_path: Path) -> None:
    _assert_workspace_is_recreated_without_following_symlinks(
        tmp_path, prepare_codex_workspace,
    )


def test_codex_workspace_is_fresh_per_attempt(tmp_path: Path) -> None:
    _assert_workspace_is_recreated_without_following_symlinks(
        tmp_path, prepare_legacy_codex_workspace,
    )


def test_codex_rejects_workspace_root_symlink(tmp_path: Path) -> None:
    run = tmp_path / "RUN_workspace_root_link"
    outside = tmp_path / "outside"
    outside.mkdir()
    run.mkdir()
    (run / "WORKSPACES").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="workspaces_root_symlink_rejected"):
        prepare_legacy_codex_workspace(run)
    assert list(outside.iterdir()) == []


def test_codex_rejects_symlink_inside_snapshot(tmp_path: Path) -> None:
    run = tmp_path / "RUN_snapshot_link"
    snapshot = run / "INPUT" / "target_snapshot"
    snapshot.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = True\n", encoding="utf-8")
    (snapshot / "linked.py").symlink_to(outside)

    with pytest.raises(RuntimeError, match="snapshot_symlink_rejected"):
        prepare_legacy_codex_workspace(run)
    assert outside.read_text(encoding="utf-8") == "SECRET = True\n"
