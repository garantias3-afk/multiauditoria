#!/usr/bin/env python3
"""Exercise the Camino B HTTP Gateway with a real Slot 14 worker bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import tempfile
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.camino_b_gateway import BASE_PATH, create_server  # noqa: E402
from scripts.camino_b_slot14_bridge import (  # noqa: E402
    FALLBACK_ROUTE, PRIMARY_ROUTE, LocalSlot14Queue,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _http(url: str, key: str, *, payload: Optional[dict[str, Any]] = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"X-API-Key": key}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read())


def _primary_failure_bundle(root: Path, job: dict[str, Any]) -> Path:
    bundle = root / "claude_profile_failure"
    bundle.mkdir()
    attempt = dict(job.get("claude_attempt") or {})
    result = {
        "schema_version": "camino_slot14_worker_result.bridge_smoke.v1",
        "worker_id": "claude_code",
        "job_id": str(attempt.get("job_id") or "PROFILE_DISABLED"),
        "run_id": job["run_id"],
        "slot_id": "14",
        "candidate_sha256": job["candidate_sha256"],
        "route_id": PRIMARY_ROUTE,
        "status": str(attempt.get("status") or "disabled_by_profile"),
        "error_class": str(attempt.get("error_class") or "claude_unavailable"),
        "summary": "Claude route unavailable as recorded by the runtime profile.",
        "findings": [],
        "corrections_applied": False,
        "approval_eligible": False,
    }
    _write_json(bundle / "result.json", result)
    manifest = {
        "schema_version": "camino_a_output_manifest.v1",
        "run_id": job["run_id"],
        "stage": "slot_14_bridge_primary_availability",
        "candidate_sha256": job["candidate_sha256"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": [{
            "path": "result.json", "sha256": _sha(bundle / "result.json"),
            "size_bytes": (bundle / "result.json").stat().st_size,
        }],
    }
    _write_json(bundle / "OUTPUT_MANIFEST.json", manifest)
    (bundle / "CLAUDE_CODE_OUTPUT.DONE").write_text("DONE\n", encoding="utf-8")
    return bundle


def run_smoke(run_dir: Path, codex_bundle: Path) -> dict[str, Any]:
    job_path = run_dir / "13_WORKER_BUS" / "codex_fallback" / "IN" / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    request = {
        "schema_version": "camino_b_slot14_review_request.v1",
        "path_id": "camino_b",
        "run_id": job["run_id"],
        "slot_id": "14",
        "source_slot_id": "13",
        "candidate_sha256": job["candidate_sha256"],
        "prior_slots_complete": True,
        "request_path": job["request_path"],
        "request_sha256": job["request_sha256"],
        "slot14_audit_request_ref": job["request_path"],
        "slot14_audit_request_sha256": job["request_sha256"],
        "diff_path": job["diff_path"],
        "diff_sha256": job["diff_sha256"],
        "idempotency_key": "bridge-smoke-%s" % job["candidate_sha256"][:24],
        "metadata": {"source": "real_subscription_bundle_smoke"},
    }
    for ref, digest in ((job["request_path"], job["request_sha256"]), (job["diff_path"], job["diff_sha256"])):
        path = (run_dir / ref).resolve()
        if run_dir not in path.parents or _sha(path) != digest:
            raise RuntimeError("handoff file binding failed: %s" % ref)

    with tempfile.TemporaryDirectory(prefix="camino_b_bridge_smoke_") as temp_raw:
        temp = Path(temp_raw)
        queue_root = temp / "queue"
        api_key = secrets.token_urlsafe(32)
        server = create_server("127.0.0.1", 0, queue_root, api_key)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_port
        try:
            post_status, created = _http(base + BASE_PATH, api_key, payload=request)
            if post_status != 202:
                raise RuntimeError("Gateway did not accept request")
            queue = LocalSlot14Queue(queue_root)
            handoff = created["handoff_id"]
            candidate = request["candidate_sha256"]
            primary_claim = queue.claim(
                handoff, candidate, worker_id="claude_code", route_id=PRIMARY_ROUTE,
                claim_id="CLAIM_bridge_smoke_primary", host_id="local-smoke",
            )
            armed = queue.complete(
                handoff, candidate, claim_token=primary_claim["claim_token"],
                bundle_dir=_primary_failure_bundle(temp, job),
            )
            fallback_claim = queue.claim(
                handoff, candidate, worker_id="codex_fallback", route_id=FALLBACK_ROUTE,
                claim_id="CLAIM_bridge_smoke_fallback", host_id="local-smoke",
            )
            queue.complete(
                handoff, candidate, claim_token=fallback_claim["claim_token"],
                bundle_dir=codex_bundle,
            )
            status_code, status = _http(
                f"{base}{BASE_PATH}/{handoff}/status?candidate_sha256={candidate}", api_key,
            )
            result_code, result = _http(
                f"{base}{BASE_PATH}/{handoff}/result?candidate_sha256={candidate}", api_key,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    completion = dict(result.get("completion") or {})
    worker_result = dict(completion.get("result") or {})
    passed = (
        armed.get("fallback_armed") is True
        and status_code == 200 and result_code == 200
        and status.get("status") == "completed"
        and result.get("result_ready") is True
        and worker_result.get("model_id") == "gpt-5.6-sol"
        and worker_result.get("model_reasoning_effort") == "ultra"
        and (worker_result.get("auth") or {}).get("auth_method") == "chatgpt_subscription"
        and result.get("terminal_approval") is False
    )
    return {
        "schema_version": "camino_b_bridge_operational_smoke.v1",
        "passed": passed,
        "run_id": job["run_id"],
        "handoff_id": result.get("handoff_id"),
        "candidate_sha256": job["candidate_sha256"],
        "gateway_http_request_status": 202,
        "gateway_http_status_status": status_code,
        "gateway_http_result_status": result_code,
        "primary_failure_armed_fallback": armed.get("fallback_armed"),
        "bridge_status": result.get("status"),
        "transport_completed": result.get("transport_completed"),
        "terminal_approval": result.get("terminal_approval"),
        "requires_terminal_gate_validation": result.get("requires_terminal_gate_validation"),
        "worker_id": worker_result.get("worker_id"),
        "route_id": worker_result.get("route_id"),
        "model_id": worker_result.get("model_id"),
        "model_reasoning_effort": worker_result.get("model_reasoning_effort"),
        "auth_method": (worker_result.get("auth") or {}).get("auth_method"),
        "source_bundle_sha256": _sha(codex_bundle / "OUTPUT_MANIFEST.json"),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--codex-bundle", required=True)
    parser.add_argument("--evidence-out", default="")
    args = parser.parse_args(argv)
    report = run_smoke(Path(args.run).resolve(), Path(args.codex_bundle).resolve())
    if args.evidence_out:
        _write_json(Path(args.evidence_out).resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
