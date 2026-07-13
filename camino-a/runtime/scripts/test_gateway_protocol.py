#!/usr/bin/env python3
"""Pure protocol tests for manifest-first and legacy gateway flows.

The transport is injected at the JSON boundary, so the suite uses no sockets or
real network while still exercising manifest negotiation, deduplication,
base64 integrity, fallback selection, TOCTOU and strict audit validation.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.worker_gateway as gateway  # noqa: E402


JOB = {"run_id": "RUN_TEST", "job_id": "J1", "candidate_sha256": "a" * 64}
passed = failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", name)
    else:
        failed += 1
        print("  FAIL:", name, detail)


def make_run_dir(td: Path, files: dict[str, bytes]) -> Path:
    run = td / "RUN_TEST"
    snapshot = run / "INPUT" / "target_snapshot"
    snapshot.mkdir(parents=True)
    for relative, content in files.items():
        path = snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return run


def audit_response(body: dict[str, Any], model: str = "mock-model") -> dict[str, Any]:
    return {
        "status": "audited",
        "mode": body.get("mode"),
        "model_id": model,
        "provider_id": "mock-provider",
        "candidate_sha256": body.get("candidate_sha256"),
        "findings": [],
    }


class ManifestTransport:
    def __init__(self, mutate_path: Optional[Path] = None) -> None:
        self.cache: set[str] = set()
        self.manifests: list[dict[str, Any]] = []
        self.uploads: list[str] = []
        self.chunk_counts: list[int] = []
        self.chunk_buffers: dict[str, list[bytes]] = {}
        self.chunk_meta: dict[str, dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []
        self.calls: list[tuple[str, bool]] = []
        self.mutate_path = mutate_path

    def __call__(self, url: str, body: dict, timeout: int, *, gzip_body: bool = False):
        self.calls.append((url.rsplit("/", 1)[-1], gzip_body))
        if url.endswith("/manifest"):
            self.manifests.append(body)
            needed = [item["sha256"] for item in body["files"] if item["sha256"] not in self.cache]
            if self.mutate_path is not None:
                self.mutate_path.write_bytes(b"MUTATED CONTENT\n")
            return True, {
                "session_id": "SESSION_TEST", "needed": needed,
                "upload_protocols": ["single_input_v1", "chunked_input_v1"],
                "max_raw_chunk_bytes": 3 * 1024 * 1024,
            }
        if url.endswith("/upload"):
            content = base64.b64decode(body["content_b64"])
            actual = hashlib.sha256(content).hexdigest()
            self.uploads.append(body["path"])
            self.cache.add(actual)
            return True, {"sha256": actual}
        if url.endswith("/upload/chunked/start"):
            upload_id = "UPLOAD_%d" % (len(self.chunk_buffers) + 1)
            self.chunk_buffers[upload_id] = []
            self.chunk_meta[upload_id] = body
            self.uploads.append(body["path"])
            return True, {"upload_id": upload_id}
        if "/upload/chunked/" in url and url.endswith("/chunks"):
            upload_id = body["upload_id"]
            raw = base64.b64decode(body["content_b64"])
            self.chunk_buffers[upload_id].append(raw)
            return True, {"chunk_sha256": hashlib.sha256(raw).hexdigest()}
        if "/upload/chunked/" in url and url.endswith("/finalize"):
            upload_id = body["upload_id"]
            content = b"".join(self.chunk_buffers[upload_id])
            actual = hashlib.sha256(content).hexdigest()
            self.cache.add(actual)
            self.chunk_counts.append(len(self.chunk_buffers[upload_id]))
            return True, {"sha256": actual, "size_bytes": len(content)}
        if url.endswith("/audit"):
            self.audits.append(body)
            return True, audit_response(body)
        return False, {"error": "unexpected_url"}


class LegacyTransport:
    def __init__(self, manifest_error: str = "http_404", audit_payload: Optional[dict] = None) -> None:
        self.manifest_error = manifest_error
        self.audit_payload = audit_payload
        self.audits: list[dict[str, Any]] = []
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, url: str, body: dict, timeout: int, *, gzip_body: bool = False):
        self.calls.append((url.rsplit("/", 1)[-1], gzip_body))
        if url.endswith("/manifest"):
            return False, {"error": self.manifest_error}
        if url.endswith("/audit"):
            self.audits.append(body)
            return True, self.audit_payload if self.audit_payload is not None else audit_response(body, "legacy-model")
        return False, {"error": "unexpected_url"}


original_post = gateway._post_json
try:
    print("=== TEST 1: manifest-first + cache por hash ===")
    transport = ManifestTransport()
    gateway._post_json = transport
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"a.py": b"print(1)\n", "b.md": b"# doc\n"})
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("first call ok", ok, str(response))
        check("mode manifest_first", response.get("mode") == "manifest_first", str(response))
        check("two files uploaded", transport.uploads == ["a.py", "b.md"], str(transport.uploads))
        check("manifest has no content", all(
            "content_b64" not in item for item in transport.manifests[0]["files"]
        ))
        before = len(transport.uploads)
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("second call ok", ok, str(response))
        check("second call deduplicated", len(transport.uploads) == before, str(transport.uploads))

    print("=== TEST 2: legacy fallback completo + gzip flag ===")
    legacy = LegacyTransport()
    gateway._post_json = legacy
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"x.py": b"x = 42\n"})
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("legacy call ok", ok, str(response))
        check("mode full_payload", response.get("mode") == "full_payload", str(response))
        payload = legacy.audits[0]
        check("full payload contains base64", bool(payload["candidate_files"][0]["content_b64"]))
        check("manifest and audit requested gzip", legacy.calls == [("manifest", True), ("audit", True)], str(legacy.calls))

    print("=== TEST 3: archivo grande => upload chunked bounded ===")
    chunked = ManifestTransport()
    gateway._post_json = chunked
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"small.py": b"ok\n"})
        with (run / "INPUT/target_snapshot/big.bin").open("wb") as handle:
            handle.seek(11 * 1024 * 1024 - 1)
            handle.write(b"x")
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("large chunked call ok", ok, str(response))
        check("large file uploaded", "big.bin" in chunked.uploads, str(chunked.uploads))
        check("large file split into chunks", chunked.chunk_counts == [4], str(chunked.chunk_counts))

    print("=== TEST 4: TOCTOU aborta antes del upload/audit ===")
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"victim.py": b"original\n"})
        victim = run / "INPUT/target_snapshot/victim.py"
        mutating = ManifestTransport(mutate_path=victim)
        gateway._post_json = mutating
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("TOCTOU rejected", not ok and "toctou_snapshot_changed" in response.get("error", ""), str(response))
        check("no upload/audit after mutation", not mutating.uploads and not mutating.audits, str(mutating.calls))

    print("=== TEST 5: error real de manifest no usa fallback ===")
    server_error = LegacyTransport(manifest_error="http_500")
    gateway._post_json = server_error
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"y.py": b"y = 1\n"})
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("500 propagated", not ok and response.get("error") == "http_500", str(response))
        check("audit not called", not server_error.audits)

    print("=== TEST 6: respuesta audit inválida falla cerrado ===")
    invalid_audit = LegacyTransport(audit_payload={})
    gateway._post_json = invalid_audit
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"z.py": b"z = 1\n"})
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("empty audit rejected", not ok and response.get("error") == "audit_response_invalid_status", str(response))

    print("=== TEST 7: manifest no puede pedir hash desconocido ===")

    class UnknownHashTransport(ManifestTransport):
        def __call__(self, url, body, timeout, *, gzip_body=False):
            if url.endswith("/manifest"):
                return True, {"session_id": "SESSION_TEST", "needed": ["f" * 64]}
            return super().__call__(url, body, timeout, gzip_body=gzip_body)

    unknown = UnknownHashTransport()
    gateway._post_json = unknown
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {"q.py": b"q = 1\n"})
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("unknown hash rejected", not ok and response.get("error") == "manifest_negotiation_unknown_needed_hash", str(response))

    print("=== TEST 8: gateway sin protocolo chunked falla cerrado ===")

    class NoChunkTransport(ManifestTransport):
        def __call__(self, url, body, timeout, *, gzip_body=False):
            if url.endswith("/manifest"):
                needed = [item["sha256"] for item in body["files"]]
                return True, {"session_id": "SESSION_TEST", "needed": needed,
                              "upload_protocols": ["single_input_v1"]}
            return super().__call__(url, body, timeout, gzip_body=gzip_body)

    no_chunk = NoChunkTransport()
    gateway._post_json = no_chunk
    with tempfile.TemporaryDirectory() as td:
        run = make_run_dir(Path(td), {})
        with (run / "INPUT/target_snapshot/large.bin").open("wb") as handle:
            handle.seek(11 * 1024 * 1024 - 1)
            handle.write(b"x")
        ok, response = gateway.call_gateway("https://mock.invalid", JOB, run)
        check("missing chunk protocol rejected", not ok, str(response))
        check("missing chunk protocol explicit", response.get("status") == "insufficient_evidence", str(response))
finally:
    gateway._post_json = original_post

print()
print("RESULTADO: %d passed, %d failed" % (passed, failed))
raise SystemExit(0 if failed == 0 else 1)
