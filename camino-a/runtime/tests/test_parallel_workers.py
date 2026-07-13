from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from scripts import overnight_master


def _live_host(pressure: str = "normal", role: str = "generic") -> dict:
    return {"role": role, "memory": {"pressure": pressure}}


def _peer(enabled: bool = False, configured: bool = False) -> dict:
    return {"enabled": enabled, "configured": configured, "status": "configured_not_probed"}


def test_inline_workers_overlap_but_state_writes_stay_outside_threads(
    tmp_path: Path, monkeypatch,
) -> None:
    run = tmp_path / "RUN_test"
    run.mkdir()
    active = 0
    maximum = 0
    lock = threading.Lock()

    def fake_run(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.08)
        with lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(overnight_master.subprocess, "run", fake_run)
    monkeypatch.setattr(overnight_master, "_record_worker_execution_quality", lambda *a, **k: None)
    monkeypatch.setattr(overnight_master, "detect_runtime_host", lambda policy: _live_host())
    monkeypatch.setattr(overnight_master, "resolve_peer_settings", lambda *a, **k: _peer())
    monkeypatch.setenv("CAMINO_B_GATEWAY_URL", "http://127.0.0.1:9999")
    result = overnight_master.execute_inline_workers(
        run,
        [
            {"worker": "local_static", "status": "dispatched", "job_id": "J1"},
            {"worker": "gateway", "status": "dispatched", "job_id": "J2"},
        ],
        {
            "max_parallel_workers": 2,
            "worker_limits": {
                "local_static": {"timeout_minutes": 1},
                "gateway": {"timeout_minutes": 1},
            },
        },
        db=None,
    )
    assert [item["worker"] for item in result] == ["local_static", "gateway"]
    assert maximum == 2


def test_missing_local_cli_selects_configured_peer(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / "RUN_peer_fallback"
    run.mkdir()
    commands: list[list[str]] = []

    def fake_run(args, **kwargs):
        commands.append(list(args))
        return SimpleNamespace(returncode=0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setattr(overnight_master.subprocess, "run", fake_run)
    monkeypatch.setattr(overnight_master, "_record_worker_execution_quality", lambda *a, **k: None)
    monkeypatch.setattr(overnight_master, "detect_runtime_host", lambda policy: _live_host())
    monkeypatch.setattr(
        overnight_master, "resolve_peer_settings",
        lambda *a, **k: _peer(enabled=True, configured=True),
    )
    monkeypatch.setattr(
        overnight_master, "_command_is_available",
        lambda command: False if command == "claude" else True,
    )

    result = overnight_master.execute_inline_workers(
        run,
        [{"worker": "claude_code", "status": "dispatched", "job_id": "J-peer"}],
        {"profile_name": "with_claude", "max_parallel_workers": 3},
        db=None,
    )

    assert result[0]["execution_transport"] == "ssh_peer"
    assert result[0]["peer_selection_reason"] == "local_cli_missing"
    assert commands and "peer_executor.py" in " ".join(commands[0])
    assert "worker_claude_code" in commands[0]


def test_missing_local_cli_without_peer_is_explicit_skip(tmp_path: Path, monkeypatch) -> None:
    run = tmp_path / "RUN_no_peer"
    run.mkdir()
    monkeypatch.setattr(overnight_master, "_record_worker_execution_quality", lambda *a, **k: None)
    monkeypatch.setattr(overnight_master, "detect_runtime_host", lambda policy: _live_host())
    monkeypatch.setattr(overnight_master, "resolve_peer_settings", lambda *a, **k: _peer())
    monkeypatch.setattr(overnight_master, "_command_is_available", lambda command: False)

    result = overnight_master.execute_inline_workers(
        run,
        [{"worker": "claude_code", "status": "dispatched", "job_id": "J-skip"}],
        {"profile_name": "with_claude", "max_parallel_workers": 3},
        db=None,
    )

    assert result[0]["status"] == "skipped_cli_missing"
    assert result[0]["peer_ready"] is False


def test_live_critical_pressure_overrides_stale_launch_snapshot(
    tmp_path: Path, monkeypatch,
) -> None:
    run = tmp_path / "RUN_live_pressure"
    run.mkdir()
    (run / "RUN_CONFIG.json").write_text(
        '{"execution_context":{"host":{"memory":{"pressure":"normal"}}}}',
        encoding="utf-8",
    )
    active = 0
    maximum = 0
    lock = threading.Lock()

    def fake_run(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(overnight_master.subprocess, "run", fake_run)
    monkeypatch.setattr(overnight_master, "_record_worker_execution_quality", lambda *a, **k: None)
    monkeypatch.setattr(
        overnight_master, "detect_runtime_host",
        lambda policy: _live_host("critical"),
    )
    monkeypatch.setattr(overnight_master, "resolve_peer_settings", lambda *a, **k: _peer())

    result = overnight_master.execute_inline_workers(
        run,
        [
            {"worker": "local_static", "status": "dispatched", "job_id": "J1"},
            {"worker": "local_static", "status": "dispatched", "job_id": "J2"},
            {"worker": "local_static", "status": "dispatched", "job_id": "J3"},
        ],
        {"profile_name": "without_claude", "max_parallel_workers": 3},
        db=None,
    )

    assert len(result) == 3
    assert maximum == 1
    snapshot = (run / "STATE" / "last_dispatch_resource_snapshot.json").read_text(encoding="utf-8")
    assert '"memory_pressure": "critical"' in snapshot
    assert '"parallel_worker_cap": 1' in snapshot


def test_parallel_cap_fails_safe_when_pressure_unknown() -> None:
    assert overnight_master._parallel_worker_cap(5, "normal") == 5
    assert overnight_master._parallel_worker_cap(5, "warning") == 2
    assert overnight_master._parallel_worker_cap(5, "critical") == 1
    assert overnight_master._parallel_worker_cap(5, "unknown") == 1
