from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from scripts.camino_b_gateway import BASE_PATH, create_server


API_KEY = "test-camino-b-key-0123456789"
CANDIDATE = "a" * 64


def _request() -> dict:
    return {
        "schema_version": "camino_b_slot14_review_request.v1",
        "path_id": "camino_b",
        "run_id": "RUN_gateway_test",
        "slot_id": "14",
        "source_slot_id": "13",
        "candidate_sha256": CANDIDATE,
        "prior_slots_complete": True,
        "request_path": "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json",
        "request_sha256": "b" * 64,
        "slot14_audit_request_ref": "STATE/slot14_handoff/SLOT_14_AUDIT_REQUEST.json",
        "slot14_audit_request_sha256": "b" * 64,
        "diff_path": "STATE/slot14_handoff/CANDIDATE_DIFF.diff",
        "diff_sha256": "c" * 64,
        "idempotency_key": "gateway-test-key-0001",
    }


def _call(url: str, *, method: str = "GET", payload: Optional[dict] = None, key: str = API_KEY):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"X-API-Key": key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_gateway_request_status_result_and_auth(tmp_path: Path) -> None:
    server = create_server("127.0.0.1", 0, tmp_path / "queue", API_KEY)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        health_status, health = _call(base + "/healthz", key="")
        assert health_status == 200
        assert health["deployment"] == "local_backend_ready"

        unauthorized, error = _call(base + BASE_PATH, method="POST", payload=_request(), key="wrong")
        assert unauthorized == 401
        assert error["error"] == "unauthorized"

        created_status, created = _call(base + BASE_PATH, method="POST", payload=_request())
        assert created_status == 202
        assert created["status"] == "awaiting_slot14_local_worker"
        handoff = created["handoff_id"]

        status_code, status = _call(
            f"{base}{BASE_PATH}/{handoff}/status?candidate_sha256={CANDIDATE}"
        )
        assert status_code == 200
        assert status["handoff_id"] == handoff
        assert status["terminal_approval"] is False

        result_code, result = _call(
            f"{base}{BASE_PATH}/{handoff}/result?candidate_sha256={CANDIDATE}"
        )
        assert result_code == 200
        assert result["result_ready"] is False

        stale_code, stale = _call(
            f"{base}{BASE_PATH}/{handoff}/status?candidate_sha256={'f' * 64}"
        )
        assert stale_code == 409
        assert stale["error"] == "stale_candidate_sha256"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
