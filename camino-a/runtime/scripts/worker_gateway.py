#!/usr/bin/env python3
"""worker_gateway.py — Gateway/Camino B worker (B-4 fix, v1.2.0).

HONEST BEHAVIOR:

A "real" Gateway calls an external provider (Camino B API) and gets an
independent audit. The list of allowed providers comes from
`config/provider.policy.json`. The `forbidden_providers` set excludes
Claude API and OpenAI API by contract.

This worker:
  1. Reads the job from `13_WORKER_BUS/gateway/IN/job.json`.
  2. Reads the current candidate from `00_CANDIDATE` (legacy seed fallback).
  3. Checks `provider.policy.json` for any configured provider endpoint
     (env var `CAMINO_B_GATEWAY_URL` or `gateway_url` field in policy).
  4. If a real provider is configured AND not in `forbidden_providers`:
       - probe the endpoint
       - if probe ok, POST the candidate and harvest the response
       - write a valid bundle (manifest + DONE)
  5. If no real provider is configured OR probe fails OR provider is
     forbidden: write a `NOT_IMPLEMENTED.json` marker (NOT a bundle)
     and exit with status `not_implemented`.

This worker NEVER silently produces a fake "ok" bundle from local
analysis. Local analysis is now `worker_local_static.py` (a separate,
honestly-named worker that does NOT count as an external auditor).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    sha256_file, utc_now, read_json, write_json,
    save_state, load_state, history_event,
    write_output_manifest_and_done,
)
from scripts.candidate_updates import candidate_source, verify_candidate_binding
from scripts.candidate_updates import UPDATE_SCHEMA


FORBIDDEN_DEFAULT = ("openai_api", "anthropic_api", "claude_api")
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
AUDIT_OK_STATUSES = frozenset({"audited", "completed"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def load_provider_policy(root: Path = ROOT) -> dict:
    return read_json(root / "config" / "provider.policy.json", {})


def get_gateway_url(policy: dict) -> str:
    """Return the configured gateway URL, or empty string if none."""
    env_url = os.environ.get("CAMINO_B_GATEWAY_URL", "").strip()
    if env_url:
        return env_url
    return str(policy.get("gateway_url", "")).strip()


def is_forbidden(provider_id: str, policy: dict) -> bool:
    forbidden = set(policy.get("forbidden_providers", FORBIDDEN_DEFAULT))
    return provider_id in forbidden


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def _gateway_api_key() -> str:
    return os.environ.get("CAMINO_B_GATEWAY_API_KEY", "").strip()


def _request_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    key = _gateway_api_key()
    if key:
        header_name = os.environ.get("CAMINO_B_GATEWAY_API_KEY_HEADER", "X-API-Key").strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", header_name):
            raise ValueError("invalid_gateway_api_key_header")
        headers[header_name] = key
    return headers


def validate_gateway_url(url: str, policy: Optional[dict] = None) -> tuple[bool, str]:
    """Require a credential-free HTTPS base URL (HTTP only for loopback/opt-in)."""
    import urllib.parse

    try:
        parsed = urllib.parse.urlsplit(str(url).strip())
    except ValueError:
        return False, "gateway_url_parse_error"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "gateway_url_invalid"
    if parsed.username or parsed.password:
        return False, "gateway_url_userinfo_rejected"
    if parsed.query or parsed.fragment:
        return False, "gateway_url_query_or_fragment_rejected"
    host = parsed.hostname.lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not loopback and not _truthy_env("CAMINO_B_ALLOW_INSECURE_HTTP"):
        return False, "gateway_https_required"
    allowed_raw = os.environ.get("CAMINO_B_GATEWAY_ALLOWED_HOSTS", "").strip()
    allowed = {part.strip().lower() for part in allowed_raw.split(",") if part.strip()}
    if not allowed and policy:
        allowed = {str(part).strip().lower() for part in policy.get("allowed_gateway_hosts", []) if str(part).strip()}
    if allowed and host not in allowed:
        return False, "gateway_host_not_allowlisted"
    if not loopback and not _gateway_api_key():
        return False, "missing_gateway_api_key"
    return True, "ok"


def probe_provider(url: str, policy: dict) -> tuple[bool, str]:
    """Probe the gateway endpoint. Returns (ok, message).

    This implementation uses urllib (stdlib) so we don't add a requests
    dependency. The probe is a HEAD or GET /healthz on the gateway URL.
    On 401/403/404 the probe fails; on 429 we report rate-limited but
    still treat as "available" for one retry.
    """
    if not url:
        return False, "no_gateway_url_configured"
    try:
        import urllib.request
        import urllib.error
        # Build a /healthz probe URL
        probe_url = url.rstrip("/") + "/healthz"
        req = urllib.request.Request(probe_url, method="GET", headers=_request_headers())
        timeout = int(policy.get("probe_timeout_seconds", 10))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            if status in (200, 204, 404):  # 404 means "no healthz but server up"
                return True, f"probe_ok_status_{status}"
            return False, f"probe_bad_status_{status}"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return True, "probe_429_rate_limited_but_available"
        if e.code in (401, 403):
            return False, f"probe_auth_failed_{e.code}"
        if e.code == 404:
            return True, "probe_404_no_healthz"
        return False, f"probe_http_error_{e.code}"
    except urllib.error.URLError as e:
        return False, f"probe_url_error:{e.reason}"
    except Exception as e:
        return False, f"probe_exception:{type(e).__name__}"


def call_gateway(url: str, job: dict, run_dir: Path,
                 timeout_seconds: int = 60) -> tuple[bool, dict]:
    """Envía el candidato al gateway. Protocolo en dos niveles:

    NIVEL A — manifest-first (preferido):
      1. POST {url}/manifest con la lista de archivos (path + sha256 + size),
         SIN contenido. El servidor responde con los hashes que NO tiene
         cacheados ("needed") y un session_id.
      2. Se suben SOLO los archivos needed, uno por request, con re-hash
         TOCTOU inmediatamente antes de cada upload. Si el archivo cambió
         entre manifest y upload → abort total (fail-closed, sin bundle
         parcial: un bundle sobre snapshot inconsistente es peor que ninguno).
      3. POST {url}/audit con mode=manifest_first + session_id → respuesta
         de auditoría.
      Entre iteraciones del big loop la mayoría de los archivos no cambia,
      así que las iteraciones 2+ transfieren solo los diffs reales.

    NIVEL C — fallback (servidor legacy que no implementa /manifest):
      Si /manifest responde 404/405/501, se usa el POST /audit clásico con
      payload completo, pero gzip-comprimido (Content-Encoding: gzip) y con
      presupuesto total acotado. Los .py/.md comprimen 4-6x.

    Devuelve (ok, response_dict). Nunca produce evidencia parcial.
    """
    snapshot = candidate_source(run_dir)
    if not snapshot.exists():
        return False, {"error": "no_current_candidate"}

    entries, skipped = _collect_snapshot_manifest(snapshot)
    if skipped:
        return False, {
            "status": "insufficient_evidence",
            "error": "insufficient_evidence:skipped_files",
            "skipped_files": skipped,
        }
    if not entries:
        return False, {"error": "snapshot_empty"}

    base = {
        "run_id": job.get("run_id", run_dir.name),
        "job_id": job.get("job_id", ""),
        "candidate_sha256": job.get("candidate_sha256", ""),
        "slot_id": str(job.get("slot_id") or ""),
        "requested_route_ids": list(job.get("route_ids") or []),
        "slot_role": str(job.get("slot_role") or ""),
        "internal_loop_contract": dict(job.get("internal_loop_contract") or {}),
        "candidate_update_contract": {
            "schema_version": UPDATE_SCHEMA,
            "rule": "If corrections_applied is true, return a complete candidate_update.zip as archive_b64 with source and resulting tree SHA-256; otherwise omit candidate_update.",
            "archive_format": "zip",
            "archive_field": "archive_b64",
            "max_response_bytes": _MAX_GATEWAY_RESPONSE_BYTES,
        },
    }

    # --- NIVEL A: negociación de manifest ---
    nego_ok, nego = _negotiate_manifest(url, base, entries, skipped,
                                        timeout_seconds)
    if nego_ok:
        session_id = str(nego.get("session_id") or "")
        needed = nego.get("needed")
        if not session_id or not isinstance(needed, list):
            return False, {"error": "manifest_negotiation_malformed_response"}

        declared_hashes = {str(entry["sha256"]).lower() for entry in entries}
        needed_set = {str(h).lower() for h in needed}
        if any(not SHA256_RE.fullmatch(item) for item in needed_set):
            return False, {"error": "manifest_negotiation_invalid_needed_hash"}
        if not needed_set.issubset(declared_hashes):
            return False, {"error": "manifest_negotiation_unknown_needed_hash"}
        up_ok, up_err = _upload_needed_files(
            url, session_id, snapshot, entries, needed_set, timeout_seconds,
            negotiation=nego,
        )
        if not up_ok:
            # Fail-closed: TOCTOU o upload fallido → sin bundle. NO caer a
            # fallback C acá: el snapshot ya demostró ser inestable o el
            # servidor ya aceptó el manifest; reintentar con full payload
            # duplicaría estado en el servidor.
            return False, up_err

        audit_body = dict(base)
        audit_body.update({
            "schema_version": "camino_b_audit_request.v2",
            "mode": "manifest_first",
            "session_id": session_id,
            "file_count": len(entries),
            "skipped_files": skipped,
        })
        ok, response = _post_json(url.rstrip("/") + "/audit", audit_body,
                                  timeout_seconds, gzip_body=False)
        return _validate_audit_response(
            ok, response, str(base["candidate_sha256"]),
            slot_id=str(base.get("slot_id") or ""),
            internal_loop_contract=base.get("internal_loop_contract") or {},
        )

    if not nego.get("fallback_allowed"):
        # Error real de red/servidor en /manifest (no un "no implementado"):
        # propagar el error, no enmascarar con fallback.
        return False, nego

    # --- NIVEL C: fallback full payload + gzip ---
    payload = dict(base)
    payload["schema_version"] = "camino_b_audit_request.v2"
    payload["mode"] = "full_payload"
    payload["candidate_files"] = []
    payload["skipped_files"] = []

    if sum(int(entry["size_bytes"]) for entry in entries) > _MAX_GATEWAY_TOTAL_BYTES:
        return False, {
            "status": "insufficient_evidence",
            "error": "insufficient_evidence:total_payload_budget_exceeded",
            "total_size_bytes": sum(int(entry["size_bytes"]) for entry in entries),
            "max_total_bytes": _MAX_GATEWAY_TOTAL_BYTES,
        }

    total_budget = _MAX_GATEWAY_TOTAL_BYTES
    consumed = 0
    for e in entries:
        item = snapshot / e["path"]
        if consumed + e["size_bytes"] > total_budget:
            return False, {
                "status": "insufficient_evidence",
                "error": "insufficient_evidence:total_payload_budget_exceeded",
                "path": e["path"],
            }
        try:
            # TOCTOU: re-hash antes de leer para el payload.
            actual = sha256_file(item)
            if actual.lower() != e["sha256"].lower():
                return False, {"error": f"toctou_snapshot_changed:{e['path']}"}
            content_b64, streamed_sha, streamed_size = _b64_and_sha(item)
            if not hmac.compare_digest(streamed_sha, e["sha256"].lower()) or streamed_size != int(e["size_bytes"]):
                return False, {"error": f"toctou_snapshot_changed_during_read:{e['path']}"}
            payload["candidate_files"].append({
                "path": e["path"],
                "sha256": e["sha256"],
                "size_bytes": e["size_bytes"],
                "content_b64": content_b64,
            })
            consumed += e["size_bytes"]
        except OSError as exc:
            return False, {"error": f"snapshot_read_failed:{e['path']}:{type(exc).__name__}"}

    ok, response = _post_json(url.rstrip("/") + "/audit", payload,
                              timeout_seconds, gzip_body=True)
    return _validate_audit_response(
        ok, response, str(base["candidate_sha256"]),
        slot_id=str(base.get("slot_id") or ""),
        internal_loop_contract=base.get("internal_loop_contract") or {},
    )


# Límites del protocolo gateway. El per-file está alineado con
# MAX_OUTPUT_FILE_BYTES del resto del pipeline; el total acota el peor caso
# del fallback full-payload (pre-compresión).
_MAX_GATEWAY_SINGLE_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_GATEWAY_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB hard safety ceiling
_GATEWAY_UPLOAD_CHUNK_BYTES = 3 * 1024 * 1024
_MAX_GATEWAY_TOTAL_BYTES = 64 * 1024 * 1024  # 64 MiB de contenido total (solo fallback C)
_MAX_GATEWAY_RESPONSE_BYTES = 2 * 1024 * 1024
# Status HTTP que significan "el servidor no implementa /manifest" y
# habilitan el fallback C. Cualquier otro error NO habilita fallback.
_MANIFEST_NOT_SUPPORTED_CODES = (404, 405, 501)


def _collect_snapshot_manifest(snapshot: Path) -> tuple[list[dict], list[dict]]:
    """Recorre el snapshot y devuelve (entries, skipped).

    entries: [{path, sha256, size_bytes}] — sin contenido, solo identidad.
    skipped: archivos que exceden el límite per-file, reportados explícitamente
             para que el servidor sepa qué NO va a recibir (evidencia honesta).
    """
    entries: list[dict] = []
    skipped: list[dict] = []
    for item in sorted(snapshot.rglob("*")):
        if item.is_symlink():
            skipped.append({
                "path": str(item.relative_to(snapshot)),
                "reason": "symlink_rejected",
            })
            continue
        if not item.is_file():
            continue
        try:
            size = item.stat().st_size
            rel = str(item.relative_to(snapshot))
            if size > _MAX_GATEWAY_FILE_BYTES:
                skipped.append({"path": rel, "size_bytes": size,
                                "reason": "file_too_large_for_gateway"})
                continue
            entries.append({"path": rel, "sha256": sha256_file(item),
                            "size_bytes": size})
        except OSError as exc:
            skipped.append({
                "path": str(item.relative_to(snapshot)),
                "reason": "file_stat_or_hash_failed:%s" % type(exc).__name__,
            })
    return entries, skipped


def _negotiate_manifest(url: str, base: dict, entries: list[dict],
                        skipped: list[dict],
                        timeout_seconds: int) -> tuple[bool, dict]:
    """POST {url}/manifest. Devuelve (ok, response).

    ok=True  → el servidor implementa manifest-first; response tiene
               session_id + needed.
    ok=False → response['fallback_allowed']=True si el servidor respondió
               404/405/501 (no implementa el protocolo); False si fue un
               error real que debe propagarse.
    """
    body = dict(base)
    body.update({
        "schema_version": "camino_b_manifest_negotiation.v1",
        "files": entries,
        "skipped_files": skipped,
    })
    ok, resp = _post_json(url.rstrip("/") + "/manifest", body,
                          timeout_seconds, gzip_body=True)
    if ok:
        return True, resp
    err = str(resp.get("error", ""))
    for code in _MANIFEST_NOT_SUPPORTED_CODES:
        if err.startswith(f"http_{code}"):
            return False, {"fallback_allowed": True, "error": err}
    return False, {"fallback_allowed": False, "error": err,
                   "body": resp.get("body", "")}


def _upload_needed_files(url: str, session_id: str, snapshot: Path,
                         entries: list[dict], needed_set: set[str],
                         timeout_seconds: int,
                         negotiation: Optional[dict] = None) -> tuple[bool, dict]:
    """Sube solo los archivos cuyo sha256 está en needed_set.

    Fail-closed en TOCTOU: si el hash actual del archivo difiere del hash
    declarado en el manifest, se aborta la sesión completa. También aborta
    si el servidor rechaza un upload. Nunca deja la sesión a medio subir
    sin reportarlo.
    """
    upload_url = url.rstrip("/") + "/upload"
    for e in entries:
        if e["sha256"].lower() not in needed_set:
            continue  # el servidor ya lo tiene cacheado por hash
        item = snapshot / e["path"]
        try:
            actual = sha256_file(item)
        except OSError as exc:
            return False, {"error": f"toctou_file_vanished:{e['path']}:{type(exc).__name__}"}
        if actual.lower() != e["sha256"].lower():
            return False, {"error": f"toctou_snapshot_changed:{e['path']}"}
        if int(e["size_bytes"]) > _MAX_GATEWAY_SINGLE_UPLOAD_BYTES:
            large_ok, large_result = _upload_large_file_chunked(
                url, session_id, item, e, timeout_seconds,
                negotiation=negotiation or {},
            )
            if not large_ok:
                return False, large_result
            continue
        content_b64, streamed_sha, streamed_size = _b64_and_sha(item)
        if not hmac.compare_digest(streamed_sha, e["sha256"].lower()) or streamed_size != int(e["size_bytes"]):
            return False, {"error": f"toctou_snapshot_changed_during_read:{e['path']}"}
        body = {
            "schema_version": "camino_b_file_upload.v1",
            "session_id": session_id,
            "path": e["path"],
            "sha256": e["sha256"],
            "size_bytes": e["size_bytes"],
            "content_b64": content_b64,
        }
        ok, resp = _post_json(upload_url, body, timeout_seconds,
                              gzip_body=True)
        if not ok:
            return False, {"error": f"upload_failed:{e['path']}:{resp.get('error', 'unknown')}"}
        # El servidor debe confirmar el hash recibido (integridad end-to-end).
        server_sha = str(resp.get("sha256") or "").lower()
        if not SHA256_RE.fullmatch(server_sha):
            return False, {"error": f"upload_sha_confirmation_missing:{e['path']}"}
        if not hmac.compare_digest(server_sha, e["sha256"].lower()):
            return False, {"error": f"upload_sha_mismatch:{e['path']}:server={server_sha}"}
    return True, {}


def _upload_large_file_chunked(
    url: str,
    session_id: str,
    item: Path,
    entry: dict,
    timeout_seconds: int,
    *,
    negotiation: dict,
) -> tuple[bool, dict]:
    """Upload one large input using bounded, resumable chunk requests.

    The gateway must explicitly advertise ``chunked_input_v1`` during manifest
    negotiation.  Absence never falls back to a huge one-shot JSON body.
    """
    protocols = {str(value) for value in (negotiation.get("upload_protocols") or [])}
    if "chunked_input_v1" not in protocols:
        return False, {
            "status": "insufficient_evidence",
            "error": "insufficient_evidence:gateway_chunked_input_not_supported",
            "path": entry.get("path"),
            "size_bytes": entry.get("size_bytes"),
        }
    advertised = negotiation.get("max_raw_chunk_bytes")
    chunk_bytes = _GATEWAY_UPLOAD_CHUNK_BYTES
    if isinstance(advertised, int) and advertised > 0:
        chunk_bytes = min(chunk_bytes, advertised)
    chunk_bytes = max(64 * 1024, min(chunk_bytes, _MAX_GATEWAY_SINGLE_UPLOAD_BYTES))
    size = int(entry["size_bytes"])
    total_chunks = (size + chunk_bytes - 1) // chunk_bytes
    start_body = {
        "schema_version": "camino_b_chunked_input_start.v1",
        "session_id": session_id,
        "path": entry["path"],
        "sha256": entry["sha256"],
        "size_bytes": size,
        "raw_chunk_bytes": chunk_bytes,
        "total_chunks": total_chunks,
    }
    ok, response = _post_json(
        url.rstrip("/") + "/upload/chunked/start", start_body,
        timeout_seconds, gzip_body=True,
    )
    if not ok:
        return False, {"error": "chunked_upload_start_failed:%s" % response.get("error", "unknown")}
    upload_id = str(response.get("upload_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", upload_id):
        return False, {"error": "chunked_upload_invalid_upload_id"}

    digest = hashlib.sha256()
    total_read = 0
    with item.open("rb") as handle:
        for index in range(total_chunks):
            raw = handle.read(chunk_bytes)
            if not raw and size:
                return False, {"error": "chunked_upload_unexpected_eof", "index": index}
            digest.update(raw)
            chunk_sha = hashlib.sha256(raw).hexdigest()
            body = {
                "schema_version": "camino_b_chunked_input_chunk.v1",
                "session_id": session_id,
                "upload_id": upload_id,
                "index": index,
                "offset": total_read,
                "raw_size_bytes": len(raw),
                "chunk_sha256": chunk_sha,
                "content_b64": base64.b64encode(raw).decode("ascii"),
            }
            ok, response = _post_json(
                url.rstrip("/") + f"/upload/chunked/{upload_id}/chunks",
                body, timeout_seconds, gzip_body=True,
            )
            if not ok:
                return False, {"error": "chunked_upload_chunk_failed", "index": index,
                               "detail": response.get("error", "unknown")}
            echoed = str(response.get("chunk_sha256") or "").lower()
            if not SHA256_RE.fullmatch(echoed) or not hmac.compare_digest(echoed, chunk_sha):
                return False, {"error": "chunked_upload_chunk_sha_mismatch", "index": index}
            total_read += len(raw)
    if total_read != size or not hmac.compare_digest(digest.hexdigest(), str(entry["sha256"]).lower()):
        return False, {"error": "toctou_snapshot_changed_during_chunked_read"}
    finalize_body = {
        "schema_version": "camino_b_chunked_input_finalize.v1",
        "session_id": session_id,
        "upload_id": upload_id,
        "sha256": entry["sha256"],
        "size_bytes": size,
        "total_chunks": total_chunks,
    }
    ok, response = _post_json(
        url.rstrip("/") + f"/upload/chunked/{upload_id}/finalize",
        finalize_body, timeout_seconds, gzip_body=True,
    )
    if not ok:
        return False, {"error": "chunked_upload_finalize_failed:%s" % response.get("error", "unknown")}
    server_sha = str(response.get("sha256") or "").lower()
    server_size = response.get("size_bytes")
    if not SHA256_RE.fullmatch(server_sha) or not hmac.compare_digest(server_sha, str(entry["sha256"]).lower()):
        return False, {"error": "chunked_upload_final_sha_mismatch"}
    if not isinstance(server_size, int) or server_size != size:
        return False, {"error": "chunked_upload_final_size_mismatch"}
    return True, {"upload_id": upload_id, "chunks": total_chunks, "sha256": server_sha}


def _validate_audit_response(
    ok: bool, response: dict, expected_candidate_sha256: str, *,
    slot_id: str = "", internal_loop_contract: Optional[dict] = None,
) -> tuple[bool, dict]:
    """Reject ambiguous 2xx JSON before it can become accepted evidence."""
    if not ok:
        return False, response
    if not isinstance(response, dict):
        return False, {"error": "audit_response_not_object"}
    status = str(response.get("status") or "").strip().lower()
    if status not in AUDIT_OK_STATUSES:
        return False, {"error": "audit_response_invalid_status", "status": status}
    model_id = str(response.get("model_id") or "").strip()
    provider_id = str(response.get("provider_id") or "").strip()
    if not model_id or model_id.upper() == "NO_CONSTA":
        return False, {"error": "audit_response_missing_model_id"}
    if not provider_id or provider_id.upper() == "NO_CONSTA":
        return False, {"error": "audit_response_missing_provider_id"}
    findings = response.get("findings")
    if not isinstance(findings, list):
        return False, {"error": "audit_response_findings_not_list"}
    if any(not isinstance(item, dict) for item in findings):
        return False, {"error": "audit_response_finding_not_object"}
    for item in findings:
        if not str(item.get("severity") or "").strip():
            return False, {"error": "audit_response_finding_missing_severity"}
        if not str(item.get("description") or item.get("summary") or "").strip():
            return False, {"error": "audit_response_finding_missing_description"}
    artifacts = response.get("artifacts", [])
    if not isinstance(artifacts, list):
        return False, {"error": "audit_response_artifacts_not_list"}
    echoed = str(response.get("candidate_sha256") or "").strip().lower()
    expected = str(expected_candidate_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(expected):
        return False, {"error": "audit_request_candidate_sha256_invalid"}
    if not SHA256_RE.fullmatch(echoed):
        return False, {"error": "audit_response_missing_candidate_sha256"}
    if not hmac.compare_digest(echoed, expected):
        return False, {"error": "audit_response_candidate_sha256_mismatch"}
    contract = internal_loop_contract or {}
    if contract.get("required") is True:
        loop = response.get("internal_loop")
        if not isinstance(loop, dict):
            return False, {"error": "audit_response_internal_loop_required"}
        if loop.get("schema_version") != "camino_internal_loop_result.v1":
            return False, {"error": "audit_response_internal_loop_bad_schema"}
        if str(loop.get("slot_id") or "") != str(slot_id or ""):
            return False, {"error": "audit_response_internal_loop_slot_mismatch"}
        if str(loop.get("evidence_scope") or "") != "external_agentic_loop":
            return False, {"error": "audit_response_internal_loop_scope_invalid"}
        if str(loop.get("worker_id") or "") in {
            "", "agentic_local", "local_static", "reference_local_agentic",
        }:
            return False, {"error": "audit_response_internal_loop_worker_invalid"}
        if loop.get("status") not in {"clean", "clean_no_corrections", "residual_debt"}:
            return False, {"error": "audit_response_internal_loop_status_invalid"}
        try:
            iterations = int(loop.get("iteration_count") or 0)
            recorded_max = int(loop.get("max_internal_loops") or 0)
            allowed_max = int(contract.get("max_iterations") or 10)
        except (TypeError, ValueError):
            return False, {"error": "audit_response_internal_loop_counts_invalid"}
        records = loop.get("iterations")
        if (
            iterations < 0 or recorded_max < 1 or recorded_max > allowed_max
            or iterations > recorded_max or not isinstance(records, list)
            or len(records) != iterations
        ):
            return False, {"error": "audit_response_internal_loop_counts_invalid"}
        debt = loop.get("residual_debt")
        if loop.get("status") == "residual_debt" and not debt:
            return False, {"error": "audit_response_internal_loop_debt_missing"}
        if loop.get("status") in {"clean", "clean_no_corrections"} and debt:
            return False, {"error": "audit_response_internal_loop_debt_inconsistent"}
    corrections = response.get("corrections_applied") is True
    verdict = str(response.get("verdict") or "")
    if corrections or verdict == "CORRECTIONS_APPLIED":
        update = response.get("candidate_update")
        if not isinstance(update, dict) or update.get("schema_version") != UPDATE_SCHEMA:
            return False, {"error": "audit_response_candidate_update_required"}
        if not isinstance(update.get("archive_b64"), str) or not update.get("archive_b64"):
            return False, {"error": "audit_response_candidate_update_archive_required"}
        if str(update.get("source_candidate_sha256") or "") != expected:
            return False, {"error": "audit_response_candidate_update_source_mismatch"}
        candidate_sha = str(update.get("candidate_sha256") or "").lower()
        archive_sha = str(update.get("archive_sha256") or "").lower()
        if not SHA256_RE.fullmatch(candidate_sha) or not SHA256_RE.fullmatch(archive_sha):
            return False, {"error": "audit_response_candidate_update_sha_invalid"}
    return True, response


def _materialize_gateway_candidate_update(
    response: dict, out_dir: Path, *, slot_id: str,
) -> dict[str, Any] | None:
    raw_update = response.get("candidate_update")
    if not isinstance(raw_update, dict):
        return None
    encoded = raw_update.get("archive_b64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("candidate_update_archive_b64_missing")
    try:
        content = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("candidate_update_archive_b64_invalid") from exc
    if len(content) > _MAX_GATEWAY_RESPONSE_BYTES:
        raise ValueError("candidate_update_archive_too_large_for_gateway_response")
    archive_sha = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(archive_sha, str(raw_update.get("archive_sha256") or "").lower()):
        raise ValueError("candidate_update_archive_sha_mismatch")
    archive = out_dir / "candidate_update.zip"
    archive.write_bytes(content)
    public = {key: value for key, value in raw_update.items() if key != "archive_b64"}
    public.update({
        "archive_path": archive.name,
        "archive_sha256": archive_sha,
        "worker_id": "gateway",
        "slot_id": str(slot_id),
    })
    return public


def _post_json(full_url: str, body: dict, timeout_seconds: int,
               *, gzip_body: bool = False) -> tuple[bool, dict]:
    """POST JSON con gzip opcional. Devuelve (ok, parsed_response)."""
    try:
        import urllib.request
        import urllib.error
        raw = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(_request_headers())
        if gzip_body:
            import gzip as _gzip
            raw = _gzip.compress(raw, compresslevel=6)
            headers["Content-Encoding"] = "gzip"
        req = urllib.request.Request(full_url, data=raw, method="POST",
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            response_raw = resp.read(_MAX_GATEWAY_RESPONSE_BYTES + 1)
            if len(response_raw) > _MAX_GATEWAY_RESPONSE_BYTES:
                return False, {"error": "gateway_response_too_large"}
            text = response_raw.decode("utf-8", errors="replace")
            try:
                return True, json.loads(text)
            except json.JSONDecodeError:
                return False, {"error": f"invalid_json_response:{text[:200]}"}
    except urllib.error.HTTPError as e:
        return False, {"error": f"http_{e.code}",
                       "body": e.read(501).decode("utf-8", "replace")[:500]}
    except Exception as e:
        return False, {"error": f"{type(e).__name__}:{e}"}


def _b64_and_sha(path: Path) -> tuple[str, str, int]:
    """Incrementally encode and hash the exact bytes placed in the request."""
    out = io.StringIO()
    carry = b""
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            chunk = carry + chunk
            complete = len(chunk) - (len(chunk) % 3)
            if complete:
                out.write(base64.b64encode(chunk[:complete]).decode("ascii"))
            carry = chunk[complete:]
        if carry:
            out.write(base64.b64encode(carry).decode("ascii"))
    return out.getvalue(), digest.hexdigest(), total


def _b64(path: Path) -> str:
    """Compatibility wrapper used by older callers/tests."""
    return _b64_and_sha(path)[0]


def run_gateway(run_dir: Path, dry_run: bool = False) -> dict:
    """Run gateway worker: real provider call OR NOT_IMPLEMENTED.

    Returns a result dict. If `result['status'] == 'not_implemented'`,
    no bundle is produced and the master MUST NOT count this worker as
    an external auditor.
    """
    inbox = run_dir / "13_WORKER_BUS" / "gateway" / "IN"
    job_file = inbox / "job.json"
    if not job_file.exists():
        return {"status": "no_job", "error": "No job.json in gateway/IN"}

    job = read_json(job_file, {})

    if dry_run:
        return {"status": "dry_run", "worker": "gateway", "job": job}
    bound, binding = verify_candidate_binding(
        run_dir, str(job.get("candidate_sha256") or ""),
    )
    if not bound:
        return _emit_insufficient_evidence(
            run_dir, job, {"error": f"candidate_binding_failed:{binding}"},
        )

    policy = load_provider_policy()
    gw_url = get_gateway_url(policy)

    # If no real provider configured → NOT_IMPLEMENTED (honest).
    if not gw_url:
        return _emit_not_implemented(run_dir, job,
                                     reason="no_gateway_url_configured")

    url_ok, url_reason = validate_gateway_url(gw_url, policy)
    if not url_ok:
        return _emit_not_implemented(run_dir, job,
                                     reason=f"gateway_url_rejected:{url_reason}")

    # GW-BUG-3 FIX: el código anterior tenía 3 checks hardcodeados para
    # openai/anthropic/claude. Si la política sumaba un 4to provider
    # forbidden, el check no lo cubría. Ahora se itera forbidden_providers
    # completo y se extrae la keyword de cada provider_id para comparar
    # contra la URL (heurística de mejor esfuerzo; la política es la fuente
    # de verdad, el check de URL es defensa adicional).
    _forbidden_set = set(policy.get("forbidden_providers", FORBIDDEN_DEFAULT))
    _url_lower = gw_url.lower()
    for _fp in _forbidden_set:
        # Extraer keyword del provider_id: "openai_api" → "openai",
        # "anthropic_api" → "anthropic", "deepseek_api" → "deepseek", etc.
        _keyword = _fp.split("_")[0].lower()
        if _keyword and len(_keyword) >= 4 and _keyword in _url_lower:
            return _emit_not_implemented(run_dir, job,
                                         reason=f"forbidden_provider:{_fp}")

    # Probe
    probe_ok, probe_msg = probe_provider(gw_url, policy)
    if not probe_ok:
        return _emit_not_implemented(run_dir, job,
                                     reason=f"probe_failed:{probe_msg}")

    # Real call
    call_ok, response = call_gateway(gw_url, job, run_dir)
    if not call_ok:
        if response.get("status") == "insufficient_evidence" or str(response.get("error", "")).startswith("insufficient_evidence:"):
            return _emit_insufficient_evidence(run_dir, job, response)
        return _emit_not_implemented(
            run_dir, job,
            reason=f"gateway_call_failed:{response.get('error', 'unknown')}",
        )

    # Write a real bundle from the gateway response
    out_dir = (run_dir / "13_WORKER_BUS" / "gateway" / "OUT"
               / f"gateway_result_{utc_now().replace(':', '-')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        candidate_update = _materialize_gateway_candidate_update(
            response, out_dir, slot_id=str(job.get("slot_id") or ""),
        )
    except ValueError as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        return _emit_insufficient_evidence(
            run_dir, job, {"error": f"invalid_candidate_update:{exc}"},
        )

    result = {
        "worker_id": "gateway",
        "job_id": str(job.get("job_id") or ""),
        "run_id": str(job.get("run_id") or run_dir.name),
        "status": "ok",
        "slot_id": str(job.get("slot_id") or ""),
        "candidate_sha256": str(job.get("candidate_sha256") or ""),
        "requested_route_ids": list(job.get("route_ids") or []),
        "route_id": str(response.get("route_id") or "camino_b_gateway_runtime"),
        "model_id": str(response.get("model_id") or "NO_CONSTA"),
        "provider_id": str(response.get("provider_id") or "camino_b_gateway"),
        "provider_name": str(response.get("provider_name") or "Camino B Gateway"),
        "route": "camino_b_gateway",
        "interface": "gateway_http",
        "cost_class": str(response.get("cost_class") or "gateway_policy"),
        "role": "external_gateway_auditor",
        "provider": "camino_b_real",
        "provider_url": gw_url,
        "findings": response.get("findings", []),
        "artifacts": response.get("artifacts", []),
        "internal_loop": response.get("internal_loop"),
        "verdict": str(response.get("verdict") or "ROUND_COMPLETE"),
        "corrections_applied": response.get("corrections_applied") is True,
        "summary": str(response.get("summary") or "Gateway audit completed."),
        "tests": list(response.get("tests") or []),
        "raw_response_sha256": sha256_of_text(json.dumps(response, sort_keys=True)),
    }
    if candidate_update is not None:
        result["candidate_update"] = candidate_update
    write_json(out_dir / "result.json", result)

    report_lines = [
        "# Gateway Audit Report (real provider)",
        "",
        f"Run: {run_dir.name}",
        f"Provider: {gw_url}",
        f"Time: {utc_now()}",
        "",
        f"## Findings ({len(result['findings'])})",
    ]
    for f in result["findings"]:
        report_lines.append(f"- **{f.get('severity','?')}** "
                            f"[{f.get('file','?')}] {f.get('description','?')}")
    (out_dir / "gateway_report.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8",
    )

    write_output_manifest_and_done(
        run_dir, str(out_dir.relative_to(run_dir)),
        done_name="GATEWAY_OUTPUT.DONE",
        stage="gateway_audit",
        candidate_sha256=job.get("candidate_sha256", ""),
        files=(
            "result.json", "gateway_report.md",
            *(("candidate_update.zip",) if candidate_update is not None else ()),
        ),
    )

    result["output_dir"] = str(out_dir)
    result["output_bundle"] = str(out_dir.relative_to(run_dir))
    return result


def _emit_not_implemented(run_dir: Path, job: dict, reason: str) -> dict:
    """Write a NOT_IMPLEMENTED.json marker (NOT a valid bundle)."""
    inbox = run_dir / "13_WORKER_BUS" / "gateway" / "OUT"
    inbox.mkdir(parents=True, exist_ok=True)
    marker = inbox / "NOT_IMPLEMENTED.json"
    write_json(marker, {
        "schema_version": "camino_a_not_implemented.v1",
        "worker_id": "gateway",
        "status": "not_implemented",
        "reason": reason,
        "recorded_at_utc": utc_now(),
        "run_id": job.get("run_id", run_dir.name),
        "job_id": job.get("job_id", ""),
        "note": ("Gateway worker is configured to be honest: no real "
                 "provider URL is configured, so no bundle is produced. "
                 "This worker MUST NOT count as an external auditor."),
    })
    return {
        "worker_id": "gateway",
        "status": "not_implemented",
        "reason": reason,
        "marker_path": str(marker),
    }


def _emit_insufficient_evidence(run_dir: Path, job: dict, details: dict) -> dict:
    """Record an honest non-bundle marker when the complete input was not sent."""
    inbox = run_dir / "13_WORKER_BUS" / "gateway" / "OUT"
    inbox.mkdir(parents=True, exist_ok=True)
    marker = inbox / "INSUFFICIENT_EVIDENCE.json"
    write_json(marker, {
        "schema_version": "camino_a_insufficient_evidence.v1",
        "worker_id": "gateway",
        "status": "insufficient_evidence",
        "reason": str(details.get("error") or "input_incomplete"),
        "details": details,
        "recorded_at_utc": utc_now(),
        "run_id": job.get("run_id"),
        "job_id": job.get("job_id", ""),
        "note": "No audit bundle was produced because some input evidence was omitted.",
    })
    return {
        "worker_id": "gateway",
        "status": "insufficient_evidence",
        "reason": str(details.get("error") or "input_incomplete"),
        "marker_path": str(marker),
    }


def sha256_of_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Gateway worker (honest)")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    state = load_state(run_dir)
    result = run_gateway(run_dir, dry_run=args.dry_run)
    history_event(state, "gateway_worker_done", status=result.get("status"))
    save_state(run_dir, state)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Exit codes:
    #   0  = ok (real provider called successfully)
    #   0  = not_implemented (honest, expected when no provider configured)
    #   0  = insufficient_evidence (honest non-bundle marker)
    #   1  = real failure (probe/call error after provider was configured)
    #   2  = no_job
    status = result.get("status")
    if status in ("ok", "not_implemented", "insufficient_evidence", "dry_run"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
