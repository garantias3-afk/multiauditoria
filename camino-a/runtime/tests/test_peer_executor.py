from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.host_runtime import load_policy
from scripts.peer_executor import ALLOWED_WORKERS, PeerExecutionError, PeerExecutor


ROOT = Path(__file__).resolve().parents[1]


def _executor(tmp_path: Path) -> PeerExecutor:
    identity = tmp_path / "id_ed25519_camino"
    identity.write_text("test-private-key-placeholder\n", encoding="utf-8")
    identity.chmod(0o600)
    return PeerExecutor(
        load_policy(),
        peer_settings={
            "ssh_host": "mariano@10.0.0.2",
            "ssh_identity_file": str(identity),
            "remote_root": ".camino/peer-runtime",
            "python": "python3",
        },
        root=ROOT,
    )


def _run(tmp_path: Path, prompt: str) -> Path:
    run = tmp_path / "RUN_20260710_120000_abc12"
    (run / "13_WORKER_BUS/lmstudio_bridge/IN").mkdir(parents=True)
    (run / "INPUT/target_snapshot").mkdir(parents=True)
    (run / "INPUT/target_snapshot/sample.py").write_text("x = 1\n", encoding="utf-8")
    (run / "cycle_state.json").write_text("{}\n", encoding="utf-8")
    (run / "RUN_CONFIG.json").write_text("{}\n", encoding="utf-8")
    job = {"prompt_file": prompt, "route_ids": ["lmstudio_qwen3_coder_30b_a3b"]}
    (run / "13_WORKER_BUS/lmstudio_bridge/IN/job.json").write_text(json.dumps(job), encoding="utf-8")
    return run


def test_lmstudio_remote_snapshot_includes_bounded_prompt(tmp_path: Path) -> None:
    run = _run(tmp_path, "REPORTS/slot_prompts/slot_7_lmstudio.md")
    prompt = run / "REPORTS/slot_prompts/slot_7_lmstudio.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("bounded local context\n", encoding="utf-8")
    selected, skipped = _executor(tmp_path)._snapshot_files(run, "lmstudio_bridge")
    assert prompt in selected
    assert not skipped


def test_remote_snapshot_rejects_prompt_outside_run(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    run = _run(tmp_path, str(outside))
    with pytest.raises(PeerExecutionError, match="outside_run"):
        _executor(tmp_path)._snapshot_files(run, "lmstudio_bridge")


def test_claude_peer_worker_is_allowlisted_with_generated_contract(tmp_path: Path) -> None:
    assert ALLOWED_WORKERS["worker_claude_code"]["lane"] == "claude_code"
    files = _executor(tmp_path).bootstrap_files("worker_claude_code")
    assert ROOT / "scripts" / "worker_claude_code.py" in files
    assert ROOT / "generated" / "CLAUDE.md" in files


def test_remote_snapshot_fails_closed_when_any_candidate_file_is_filtered(tmp_path: Path) -> None:
    run = _run(tmp_path, "")
    (run / "INPUT/target_snapshot/.env").write_text(
        "TOKEN=fake-example-value-aaaaaaaaaaaaaaaa\n", encoding="utf-8",
    )
    with pytest.raises(PeerExecutionError, match="snapshot_incomplete"):
        _executor(tmp_path)._snapshot_files(run, "lmstudio_bridge")
