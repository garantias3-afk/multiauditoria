#!/usr/bin/env python3
"""Pure unit tests for gateway fail-closed behavior (no sockets or real network)."""
from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.worker_gateway as gateway  # noqa: E402


passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", name)
    else:
        failed += 1
        print("  FAIL:", name, detail)


candidate_sha = "a" * 64
valid_response = {
    "status": "audited",
    "model_id": "unit-model",
    "provider_id": "unit-provider",
    "candidate_sha256": candidate_sha,
    "findings": [],
}

print("=== STRICT 1: audit response contract ===")
ok, response = gateway._validate_audit_response(True, {}, candidate_sha)
check("empty 2xx rejected", not ok and response.get("error") == "audit_response_invalid_status", str(response))
ok, response = gateway._validate_audit_response(True, valid_response, candidate_sha)
check("complete response accepted", ok, str(response))
ok, response = gateway._validate_audit_response(
    True, dict(valid_response, candidate_sha256="b" * 64), candidate_sha
)
check("wrong candidate echo rejected", not ok and "mismatch" in response.get("error", ""), str(response))

print("=== STRICT 1B: required provider internal loop ===")
loop_contract = {"required": True, "max_iterations": 10}
ok, response = gateway._validate_audit_response(
    True, valid_response, candidate_sha, slot_id="1",
    internal_loop_contract=loop_contract,
)
check("required loop cannot be omitted", not ok and response.get("error") == "audit_response_internal_loop_required", str(response))
external_loop = {
    "schema_version": "camino_internal_loop_result.v1",
    "slot_id": "1",
    "worker_id": "unit-provider-agent",
    "evidence_scope": "external_agentic_loop",
    "status": "clean_no_corrections",
    "iteration_count": 0,
    "max_internal_loops": 10,
    "iterations": [],
    "residual_debt": [],
}
ok, response = gateway._validate_audit_response(
    True, dict(valid_response, internal_loop=external_loop), candidate_sha,
    slot_id="1", internal_loop_contract=loop_contract,
)
check("bound external loop accepted", ok, str(response))
ok, response = gateway._validate_audit_response(
    True, dict(valid_response, internal_loop=dict(external_loop, evidence_scope="mechanical_reference_only")),
    candidate_sha, slot_id="1", internal_loop_contract=loop_contract,
)
check("local reference scope rejected", not ok and response.get("error") == "audit_response_internal_loop_scope_invalid", str(response))

print("=== STRICT 2: exact upload bytes and SHA confirmation ===")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    snapshot = root / "snapshot"
    snapshot.mkdir()
    content = (b"abcdef0123456789" * 100003) + b"tail"
    source = snapshot / "data.bin"
    source.write_bytes(content)
    encoded, streamed_sha, streamed_size = gateway._b64_and_sha(source)
    check("stream base64 exact", base64.b64decode(encoded) == content)
    check("stream SHA exact", streamed_sha == hashlib.sha256(content).hexdigest())
    check("stream size exact", streamed_size == len(content))
    entry = {"path": "data.bin", "sha256": streamed_sha, "size_bytes": len(content)}
    original_post = gateway._post_json
    try:
        gateway._post_json = lambda *args, **kwargs: (True, {"ok": True})
        ok, response = gateway._upload_needed_files(
            "http://127.0.0.1", "session", snapshot, [entry], {streamed_sha}, 1
        )
        check("missing server SHA rejected", not ok and "confirmation_missing" in response.get("error", ""), str(response))
        gateway._post_json = lambda *args, **kwargs: (True, {"ok": True, "sha256": streamed_sha})
        ok, response = gateway._upload_needed_files(
            "http://127.0.0.1", "session", snapshot, [entry], {streamed_sha}, 1
        )
        check("matching server SHA accepted", ok, str(response))
    finally:
        gateway._post_json = original_post

print("=== STRICT 3: large input requires declared chunk protocol ===")
with tempfile.TemporaryDirectory() as td:
    run = Path(td) / "RUN_TEST"
    snapshot = run / "INPUT" / "target_snapshot"
    snapshot.mkdir(parents=True)
    # Sparse creation avoids holding 11 MiB in the test process.
    with (snapshot / "large.bin").open("wb") as handle:
        handle.seek(11 * 1024 * 1024 - 1)
        handle.write(b"x")
    source = snapshot / "large.bin"
    entry = {
        "path": "large.bin",
        "sha256": gateway.sha256_file(source),
        "size_bytes": source.stat().st_size,
    }
    ok, response = gateway._upload_needed_files(
        "http://127.0.0.1", "session", snapshot, [entry], {entry["sha256"]}, 1,
        negotiation={"upload_protocols": ["single_input_v1"]},
    )
    check("large unsupported file fails", not ok, str(response))
    check("explicit insufficient_evidence", response.get("status") == "insufficient_evidence", str(response))

print("=== STRICT 4: URL and auth policy ===")
saved_key = os.environ.pop("CAMINO_B_GATEWAY_API_KEY", None)
saved_insecure = os.environ.pop("CAMINO_B_ALLOW_INSECURE_HTTP", None)
try:
    ok, reason = gateway.validate_gateway_url("http://127.0.0.1:1234", {})
    check("loopback HTTP allowed", ok, reason)
    ok, reason = gateway.validate_gateway_url("http://gateway.example", {})
    check("remote HTTP rejected", not ok and reason == "gateway_https_required", reason)
    ok, reason = gateway.validate_gateway_url("https://gateway.example", {})
    check("remote missing key rejected", not ok and reason == "missing_gateway_api_key", reason)
    os.environ["CAMINO_B_GATEWAY_API_KEY"] = "unit-test-key"
    ok, reason = gateway.validate_gateway_url("https://gateway.example", {})
    check("remote HTTPS with key accepted", ok, reason)
    check("auth header emitted", gateway._request_headers().get("X-API-Key") == "unit-test-key")
finally:
    if saved_key is None:
        os.environ.pop("CAMINO_B_GATEWAY_API_KEY", None)
    else:
        os.environ["CAMINO_B_GATEWAY_API_KEY"] = saved_key
    if saved_insecure is None:
        os.environ.pop("CAMINO_B_ALLOW_INSECURE_HTTP", None)
    else:
        os.environ["CAMINO_B_ALLOW_INSECURE_HTTP"] = saved_insecure

print()
print("RESULTADO: %d passed, %d failed" % (passed, failed))
raise SystemExit(0 if failed == 0 else 1)
