from __future__ import annotations

import json
import os
import hashlib
import subprocess
from pathlib import Path

import scripts.worker_codex_fallback as codex_worker
from scripts.worker_codex_fallback import (
    APPROVAL_VERDICT,
    OUTPUT_SCHEMA,
    check_codex_model_capability,
    check_codex_subscription_auth,
    load_route,
    run_codex_fallback,
    update_operator_action_marker,
)


REQUEST_BYTES = b'{"schema_version":"camino_slot14_audit_request.v1"}\n'
DIFF_BYTES = b"bounded diff fixture\n"


def _materialize_handoff(workspace: Path) -> None:
    overlay = workspace / ".camino_runtime" / "slot14_handoff"
    overlay.mkdir(parents=True, exist_ok=True)
    (overlay / "SLOT_14_AUDIT_REQUEST.json").write_bytes(REQUEST_BYTES)
    (overlay / "CANDIDATE_DIFF.diff").write_bytes(DIFF_BYTES)


def _fake_cli(tmp_path: Path) -> tuple[Path, Path]:
    cli = tmp_path / "fake_codex"
    log = tmp_path / "args.json"
    cli.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
if sys.argv[1:3] == ["login", "status"]:
    print("Logged in using ChatGPT")
    raise SystemExit(0)
if sys.argv[1:] == ["debug", "models", "--bundled"]:
    mode = os.environ.get("FAKE_CODEX_CATALOG", "ok")
    if mode == "nonzero":
        print("catalog failed", file=sys.stderr)
        raise SystemExit(7)
    if mode == "invalid":
        print("not-json")
        raise SystemExit(0)
    model = "other-model" if mode == "model_missing" else "gpt-5.6-sol"
    effort = "xhigh" if mode == "ultra_missing" else "ultra"
    print(json.dumps({"models": [{
        "slug": model,
        "supported_reasoning_levels": [{"effort": effort}],
    }]}))
    raise SystemExit(0)
Path(os.environ["FAKE_CODEX_ARGS_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
args = sys.argv[1:]
out = Path(args[args.index("--output-last-message") + 1])
out.write_text(os.environ["FAKE_CODEX_OUTPUT"], encoding="utf-8")
print(json.dumps({"type": "turn.completed"}))
""",
        encoding="utf-8",
    )
    cli.chmod(0o700)
    return cli, log


def _job() -> dict:
    return {
        "job_id": "JOB_codex_fallback_test",
        "run_id": "RUN_20260710_120000_abc12",
        "slot_id": "14",
        "source_slot_id": "13",
        "candidate_sha256": "a" * 64,
        "prior_slots_complete": True,
        "request_path": "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json",
        "request_sha256": hashlib.sha256(REQUEST_BYTES).hexdigest(),
        "diff_path": "STATE/slot14_handoff/CANDIDATE_DIFF.diff",
        "diff_sha256": hashlib.sha256(DIFF_BYTES).hexdigest(),
        "fallback_trigger": "claude_auth_missing",
        "claude_attempt": {
            "worker_id": "claude_code",
            "job_id": "JOB_claude_primary_test",
            "run_id": "RUN_20260710_120000_abc12",
            "slot_id": "14",
            "candidate_sha256": "a" * 64,
            "status": "failed",
            "approval_eligible": False,
            "error_class": "auth_missing",
            "bundle": "13_WORKER_BUS/claude_code/OUT/test",
            "output_manifest_sha256": "b" * 64,
            "done_marker": "CLAUDE_CODE_OUTPUT.DONE",
        },
    }


def _payload(**updates) -> dict:
    value = {
        "verdict": APPROVAL_VERDICT,
        "summary": "Revisión limpia con pruebas registradas.",
        "findings": [],
        "corrections_applied": False,
        "tests": ["python -m pytest -q"],
        "audit_request_sha256": hashlib.sha256(REQUEST_BYTES).hexdigest(),
        "falsification_attempts": ["Intenté refutar el fix con un caso negativo."],
        "independent_checks": ["Verifiqué una invariante crítica por una ruta separada."],
    }
    value.update(updates)
    return value


def test_codex_fallback_uses_exact_subscription_model_and_ultra(
    tmp_path: Path, monkeypatch,
) -> None:
    cli, log = _fake_cli(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _materialize_handoff(workspace)
    (workspace / "sample.py").write_text("x = 1\n", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "FAKE_CODEX_ARGS_LOG": str(log),
        "FAKE_CODEX_OUTPUT": json.dumps(_payload()),
    }
    real_run = subprocess.run
    exec_stdin = []

    def recording_run(command, *args, **kwargs):
        if "exec" in command:
            exec_stdin.append(kwargs.get("stdin"))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(codex_worker.subprocess, "run", recording_run)
    result = run_codex_fallback(workspace, _job(), load_route(), cli_command=str(cli), source_env=env)
    assert result["status"] == "ok"
    assert result["approval_eligible"] is True
    assert result["model_preflight"] == {
        "ok": True,
        "status": "model_capability_verified",
        "catalog_source": "codex debug models --bundled",
        "model_id": "gpt-5.6-sol",
        "reasoning_effort": "ultra",
    }
    args = json.loads(log.read_text(encoding="utf-8"))
    assert args[:4] == ["--ask-for-approval", "never", "exec", "--ephemeral"]
    assert args[args.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="ultra"' in args
    assert "--ephemeral" in args
    assert "--sandbox" in args and args[args.index("--sandbox") + 1] == "workspace-write"
    assert exec_stdin == [subprocess.DEVNULL]


def test_codex_output_schema_closes_nested_finding_object() -> None:
    finding = OUTPUT_SCHEMA["properties"]["findings"]["items"]
    assert finding["additionalProperties"] is False
    assert set(finding["required"]) == set(finding["properties"])


def test_codex_fallback_requires_recorded_claude_failure(tmp_path: Path) -> None:
    cli, _ = _fake_cli(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    job = _job()
    job.pop("fallback_trigger")
    result = run_codex_fallback(workspace, job, load_route(), cli_command=str(cli), source_env={})
    assert result["status"] == "failed"
    assert result["error"] == "fallback_trigger_not_allowed"


def test_codex_fallback_rejects_api_key_and_corrections(tmp_path: Path) -> None:
    cli, log = _fake_cli(tmp_path)
    auth = check_codex_subscription_auth(str(cli), source_env={"OPENAI_API_KEY": "dummy-secret-value-1234567890"})
    assert auth["status"] == "forbidden_api_key"

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _materialize_handoff(workspace)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "FAKE_CODEX_ARGS_LOG": str(log),
        "FAKE_CODEX_OUTPUT": json.dumps(_payload(verdict="CORRECTIONS_APPLIED", corrections_applied=True)),
    }
    result = run_codex_fallback(workspace, _job(), load_route(), cli_command=str(cli), source_env=env)
    assert result["status"] == "failed"
    assert result["approval_eligible"] is False


def test_codex_model_preflight_fails_closed_before_exec(tmp_path: Path) -> None:
    cli, log = _fake_cli(tmp_path)
    base_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "FAKE_CODEX_ARGS_LOG": str(log),
        "FAKE_CODEX_OUTPUT": json.dumps(_payload()),
    }
    for mode, expected_status in (
        ("model_missing", "model_or_effort_unavailable"),
        ("ultra_missing", "model_or_effort_unavailable"),
        ("invalid", "model_catalog_invalid_json"),
        ("nonzero", "model_catalog_failed"),
    ):
        log.unlink(missing_ok=True)
        env = {**base_env, "FAKE_CODEX_CATALOG": mode}
        workspace = tmp_path / f"workspace_{mode}"
        workspace.mkdir()
        _materialize_handoff(workspace)
        result = run_codex_fallback(
            workspace, _job(), load_route(), cli_command=str(cli), source_env=env,
        )
        assert result["status"] == "failed"
        assert result["error_class"] == expected_status
        assert not log.exists(), mode


def test_codex_model_capability_summary_does_not_expose_catalog(tmp_path: Path) -> None:
    cli, _ = _fake_cli(tmp_path)
    result = check_codex_model_capability(
        str(cli),
        source_env={"OPENAI_API_KEY": "must-not-be-forwarded"},
    )
    assert result["ok"] is True
    assert set(result) == {
        "ok", "status", "catalog_source", "model_id", "reasoning_effort",
    }


def test_operator_marker_is_fail_closed_and_never_requests_model_switch(tmp_path: Path) -> None:
    run = tmp_path / _job()["run_id"]
    (run / "STATE").mkdir(parents=True)
    failure = {
        "status": "failed",
        "approval_eligible": False,
        "error_class": "auth_missing",
        "error": "secret-looking-detail-must-not-be-copied",
    }
    marker = update_operator_action_marker(run, _job(), failure)
    assert marker is not None and marker.is_file()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["status"] == "SLOT14_OPERATOR_ACTION_REQUIRED"
    assert payload["manual_or_desktop_result_may_approve"] is False
    assert payload["process_isolation"] == "separate_codex_exec"
    assert "Do not change the orchestrator model" in payload["required_action"]
    assert "secret-looking" not in marker.read_text(encoding="utf-8")

    assert update_operator_action_marker(
        run, _job(), {"status": "ok", "approval_eligible": True},
    ) is None
    assert not marker.exists()
