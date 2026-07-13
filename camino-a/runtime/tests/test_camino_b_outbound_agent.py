import hashlib
from pathlib import Path

from scripts import camino_b_outbound_agent as agent
from scripts.camino_b_slot14_bridge import LocalSlot14Queue


def test_agent_processes_primary_then_fallback(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "RUN_agent_test"
    run_dir.mkdir(parents=True)
    handoff = run_dir / "STATE" / "slot14_handoff"
    handoff.mkdir(parents=True)
    request_file = handoff / "SLOT_14_AUDIT_REQUEST.json"
    diff_file = handoff / "CANDIDATE_DIFF.diff"
    request_file.write_text("request\n", encoding="utf-8")
    diff_file.write_text("diff\n", encoding="utf-8")
    queue = LocalSlot14Queue(tmp_path / "queue")
    request = {
        "schema_version": "camino_b_slot14_review_request.v1",
        "path_id": "camino_b",
        "run_id": run_dir.name,
        "slot_id": "14",
        "source_slot_id": "13",
        "candidate_sha256": "a" * 64,
        "prior_slots_complete": True,
        "request_path": "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json",
        "request_sha256": hashlib.sha256(request_file.read_bytes()).hexdigest(),
        "slot14_audit_request_ref": "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json",
        "slot14_audit_request_sha256": hashlib.sha256(request_file.read_bytes()).hexdigest(),
        "diff_path": "STATE/slot14_handoff/CANDIDATE_DIFF.diff",
        "diff_sha256": hashlib.sha256(diff_file.read_bytes()).hexdigest(),
        "idempotency_key": "agent-test-key-0001",
    }
    created = queue.request_review(request)
    calls = []

    def fake_worker(_run_dir, worker_id, *, timeout_seconds):
        calls.append(worker_id)
        return tmp_path / worker_id

    def fake_complete(handoff_id, candidate_sha256, *, claim_token, bundle_dir):
        if Path(bundle_dir).name == "claude_code":
            return {**created, "status": "awaiting_slot14_local_worker", "fallback_armed": True}
        return {**created, "status": "completed", "result_ready": True}

    monkeypatch.setattr(agent, "_invoke_worker", fake_worker)
    monkeypatch.setattr(queue, "get_agent_context", lambda *args: {"request": request, "primary_failure": {
        "error_class": "auth_missing", "claim_id": "CLAIM_primary",
        "status": "blocked", "worker_manifest_sha256": "d" * 64,
        "worker_done": [{"name": "CLAUDE_CODE_OUTPUT.DONE"}],
        "handoff_id": created["handoff_id"],
    }})
    monkeypatch.setattr(queue, "claim", lambda *args, **kwargs: {"claim_token": "test-token"})
    monkeypatch.setattr(queue, "complete", fake_complete)
    results = agent.run_once(queue, runs_root, host_id="test-host")

    assert calls == ["claude_code", "codex_fallback"]
    assert results[-1]["status"] == "completed"
