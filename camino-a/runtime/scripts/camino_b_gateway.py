#!/usr/bin/env python3
"""Minimal fail-closed HTTP Gateway for Camino B slot 14 Actions."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import ssl
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.camino_b_slot14_bridge import BridgeError, LocalSlot14Queue  # noqa: E402

MAX_REQUEST_BYTES = 64 * 1024
BASE_PATH = "/v1/camino-b/slot14/reviews"


def _error_status(code: str) -> int:
    if code == "handoff_not_found":
        return HTTPStatus.NOT_FOUND
    if code in {
        "stale_candidate_sha256", "idempotency_conflict", "handoff_collision",
        "bridge_record_sha256_mismatch", "bridge_completion_receipt_sha256_mismatch",
        "bridge_done_sha256_mismatch",
    }:
        return HTTPStatus.CONFLICT
    return HTTPStatus.BAD_REQUEST


def build_handler(queue: LocalSlot14Queue, api_key: str) -> type[BaseHTTPRequestHandler]:
    class CaminoBGatewayHandler(BaseHTTPRequestHandler):
        server_version = "CaminoBGateway/1.0"

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            supplied = self.headers.get("X-API-Key", "")
            if supplied and hmac.compare_digest(supplied, api_key):
                return True
            self._send(HTTPStatus.UNAUTHORIZED, {"status": "error", "error": "unauthorized"})
            return False

        def _candidate(self, query: str) -> str:
            values = parse_qs(query, keep_blank_values=True).get("candidate_sha256", [])
            if len(values) != 1:
                raise BridgeError("candidate_sha256_query_required")
            return values[0]

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path == "/healthz":
                self._send(HTTPStatus.OK, {
                    "status": "ok", "service": "camino_b_slot14_gateway",
                    "deployment": "local_backend_ready",
                })
                return
            if not self._authorized():
                return
            parts = parsed.path.strip("/").split("/")
            try:
                if len(parts) != 6 or "/" + "/".join(parts[:4]) != BASE_PATH:
                    raise BridgeError("route_not_found")
                handoff_id, operation = parts[4], parts[5]
                candidate = self._candidate(parsed.query)
                if operation == "status":
                    payload = queue.get_status(handoff_id, candidate)
                elif operation == "result":
                    payload = queue.get_result(handoff_id, candidate)
                else:
                    raise BridgeError("route_not_found")
                self._send(HTTPStatus.OK, payload)
            except BridgeError as exc:
                self._send(_error_status(exc.code), exc.to_dict())

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != BASE_PATH:
                self._send(HTTPStatus.NOT_FOUND, {"status": "error", "error": "route_not_found"})
                return
            if not self._authorized():
                return
            try:
                length_text = self.headers.get("Content-Length", "")
                if not length_text.isdigit():
                    raise BridgeError("content_length_required")
                length = int(length_text)
                if length < 2 or length > MAX_REQUEST_BYTES:
                    raise BridgeError("request_body_size_invalid", max_bytes=MAX_REQUEST_BYTES)
                if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                    raise BridgeError("content_type_must_be_application_json")
                try:
                    payload = json.loads(self.rfile.read(length))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BridgeError("request_json_invalid") from exc
                if not isinstance(payload, dict):
                    raise BridgeError("request_json_must_be_object")
                self._send(HTTPStatus.ACCEPTED, queue.request_review(payload))
            except BridgeError as exc:
                self._send(_error_status(exc.code), exc.to_dict())

        def log_message(self, fmt: str, *args: Any) -> None:
            # Query strings contain candidate hashes; keep access logs opt-in.
            if os.environ.get("CAMINO_B_GATEWAY_ACCESS_LOG") == "1":
                super().log_message(fmt, *args)

    return CaminoBGatewayHandler


def create_server(
    host: str, port: int, queue_root: Path | str, api_key: str,
) -> ThreadingHTTPServer:
    if len(api_key) < 24:
        raise ValueError("CAMINO_B_GATEWAY_API_KEY must contain at least 24 characters")
    queue = LocalSlot14Queue(queue_root)
    return ThreadingHTTPServer((host, port), build_handler(queue, api_key))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Camino B slot-14 Actions Gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--queue-root", default=os.environ.get("CAMINO_B_QUEUE_ROOT", ""))
    parser.add_argument("--api-key", default=os.environ.get("CAMINO_B_GATEWAY_API_KEY", ""))
    parser.add_argument("--tls-cert", default="")
    parser.add_argument("--tls-key", default="")
    args = parser.parse_args(argv)
    if not args.queue_root or not args.api_key:
        parser.error("--queue-root and --api-key (or matching environment variables) are required")
    server = create_server(args.host, args.port, args.queue_root, args.api_key)
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert and --tls-key must be supplied together")
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scheme = "https" if args.tls_cert else "http"
    print(json.dumps({
        "status": "listening", "url": f"{scheme}://{args.host}:{server.server_port}",
        "queue_root": str(Path(args.queue_root).expanduser().resolve()),
    }))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
