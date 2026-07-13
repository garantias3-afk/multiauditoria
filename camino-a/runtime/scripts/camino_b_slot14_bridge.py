#!/usr/bin/env python3
"""Local, fail-closed queue contract for Camino B slot 14.

The public Camino B Gateway is not implemented in this repository.  This
module therefore does not pretend to deploy an HTTPS Action backend.  It
implements the local half of the bridge that such a backend must drive:

* idempotent, candidate-bound review requests;
* an explicit ``awaiting_slot14_local_worker`` state;
* exclusive local claims for Claude CLI and the Codex subscription fallback;
* fallback gating on a hash-bound Claude availability failure;
* import and validation of a real worker bundle, manifest and ``*.DONE``;
* status/result receipts that never equate transport completion with approval.

The queue is intended to live on a local Mac filesystem.  A future outbound
agent may pull Gateway jobs into this queue and upload the resulting receipts.
Custom GPT Actions must never be pointed at this local filesystem directly.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_bundle import validate_bundle  # noqa: E402


REQUEST_SCHEMA = "camino_b_slot14_review_request.v1"
RECORD_SCHEMA = "camino_b_slot14_bridge_record.v1"
CLAIM_SCHEMA = "camino_b_slot14_claim_receipt.v1"
RESULT_SCHEMA = "camino_b_slot14_result_receipt.v1"

AWAITING = "awaiting_slot14_local_worker"
CLAIMED = "claimed"
COMPLETED = "completed"
BLOCKED = "blocked"

PRIMARY_ROUTE = "claude_code_subscription_cli"
FALLBACK_ROUTE = "codex_gpt_5_6_sol_ultra_subscription_cli"
ROUTE_WORKERS = {
    PRIMARY_ROUTE: "claude_code",
    FALLBACK_ROUTE: "codex_fallback",
}
ALLOWED_CLAUDE_FAILURES = frozenset({
    "auth_missing",
    "worker_missing",
    "auth_check_failed",
    "auth_check_invalid_json",
    "auth_check_timeout",
    "claude_cli_nonzero",
    "cli_execution_failed",
    "timeout",
    "claude_unavailable",
    "disabled_by_profile",
    "skipped_cli_missing",
})

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
HANDOFF_RE = re.compile(r"^B14_[a-f0-9]{32}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")


class BridgeError(RuntimeError):
    """Expected fail-closed bridge error with a stable machine code."""

    def __init__(self, code: str, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"status": "error", "error": self.code, **self.details}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise BridgeError("invalid_sha256", field=field)
    return text


def _require_safe_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not SAFE_ID_RE.fullmatch(text):
        raise BridgeError("invalid_identifier", field=field)
    return text


def _require_relative_ref(value: Any, field: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = Path(text)
    if (
        not text
        or len(text) > 500
        or path.is_absolute()
        or ".." in path.parts
        or any(ord(char) < 32 for char in text)
    ):
        raise BridgeError("invalid_relative_reference", field=field)
    return text


def _normalise_request(raw: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
    allowed = {
        "schema_version", "path_id", "run_id", "slot_id", "source_slot_id",
        "candidate_sha256", "prior_slots_complete", "request_path",
        "request_sha256", "slot14_audit_request_ref",
        "slot14_audit_request_sha256", "diff_path", "diff_sha256",
        "idempotency_key", "requested_at_utc", "metadata",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise BridgeError("request_unknown_fields", fields=unknown)
    if raw.get("schema_version") != REQUEST_SCHEMA:
        raise BridgeError("request_schema_version_invalid")
    if raw.get("path_id") != "camino_b":
        raise BridgeError("request_path_id_must_be_camino_b")
    if str(raw.get("slot_id") or "") != "14":
        raise BridgeError("request_slot_id_must_be_14")
    if str(raw.get("source_slot_id") or "") != "13":
        raise BridgeError("request_source_slot_id_must_be_13")
    if raw.get("prior_slots_complete") is not True:
        raise BridgeError("request_prior_slots_complete_required")

    run_id = _require_safe_id(raw.get("run_id"), "run_id")
    candidate = _require_sha256(raw.get("candidate_sha256"), "candidate_sha256")
    canonical_ref = raw.get("request_path")
    alias_ref = raw.get("slot14_audit_request_ref")
    if canonical_ref is None and alias_ref is None:
        raise BridgeError("slot14_audit_request_ref_required")
    if canonical_ref is not None and alias_ref is not None and str(canonical_ref) != str(alias_ref):
        raise BridgeError("slot14_audit_request_ref_alias_mismatch")
    request_ref = _require_relative_ref(
        canonical_ref if canonical_ref is not None else alias_ref,
        "slot14_audit_request_ref",
    )

    canonical_sha = raw.get("request_sha256")
    alias_sha = raw.get("slot14_audit_request_sha256")
    if canonical_sha is None and alias_sha is None:
        raise BridgeError("slot14_audit_request_sha256_required")
    if (
        canonical_sha is not None
        and alias_sha is not None
        and str(canonical_sha).lower() != str(alias_sha).lower()
    ):
        raise BridgeError("slot14_audit_request_sha256_alias_mismatch")
    request_sha = _require_sha256(
        canonical_sha if canonical_sha is not None else alias_sha,
        "slot14_audit_request_sha256",
    )
    diff_ref = _require_relative_ref(raw.get("diff_path"), "diff_path")
    diff_sha = _require_sha256(raw.get("diff_sha256"), "diff_sha256")

    key = str(raw.get("idempotency_key") or "").strip()
    if not IDEMPOTENCY_RE.fullmatch(key):
        raise BridgeError("idempotency_key_invalid")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise BridgeError("request_metadata_must_be_object")
    if len(_canonical_bytes(metadata)) > 16 * 1024:
        raise BridgeError("request_metadata_too_large")

    normalised = {
        "schema_version": REQUEST_SCHEMA,
        "path_id": "camino_b",
        "run_id": run_id,
        "slot_id": "14",
        "source_slot_id": "13",
        "candidate_sha256": candidate,
        "prior_slots_complete": True,
        "request_path": request_ref,
        "request_sha256": request_sha,
        "slot14_audit_request_ref": request_ref,
        "slot14_audit_request_sha256": request_sha,
        "diff_path": diff_ref,
        "diff_sha256": diff_sha,
        "metadata": metadata,
    }
    return normalised, key, _sha256_json(normalised)


class LocalSlot14Queue:
    """Atomic local queue used by the Camino B outbound bridge agent."""

    def __init__(self, root: Path | str) -> None:
        supplied = Path(root).expanduser()
        if supplied.exists() and supplied.is_symlink():
            raise BridgeError("queue_root_symlink_rejected")
        supplied.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = supplied.resolve()
        if self.root.is_symlink():
            raise BridgeError("queue_root_symlink_rejected")
        os.chmod(self.root, 0o700)
        (self.root / "jobs").mkdir(mode=0o700, exist_ok=True)
        (self.root / "keys").mkdir(mode=0o700, exist_ok=True)
        self._lock_path = self.root / ".queue.lock"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        import fcntl

        with self._lock_path.open("a+b") as handle:
            os.chmod(self._lock_path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _job_dir(self, handoff_id: str) -> Path:
        if not HANDOFF_RE.fullmatch(str(handoff_id)):
            raise BridgeError("handoff_id_invalid")
        return self.root / "jobs" / handoff_id

    @staticmethod
    def _atomic_write(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = path.parent / (".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
        try:
            with temp.open("xb") as handle:
                os.chmod(temp, mode)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temp), str(path))
        finally:
            temp.unlink(missing_ok=True)

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        self._atomic_write(
            path,
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n",
        )

    def _save_record(self, job_dir: Path, record: dict[str, Any]) -> None:
        record = dict(record)
        record.pop("record_sha256", None)
        record["record_sha256"] = _sha256_json(record)
        self._write_json(job_dir / "record.json", record)

    def _load_record(self, handoff_id: str) -> tuple[Path, dict[str, Any]]:
        job_dir = self._job_dir(handoff_id)
        record_path = job_dir / "record.json"
        if not record_path.is_file() or record_path.is_symlink():
            raise BridgeError("handoff_not_found")
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BridgeError("bridge_record_unreadable") from exc
        if record.get("schema_version") != RECORD_SCHEMA or record.get("handoff_id") != handoff_id:
            raise BridgeError("bridge_record_identity_invalid")
        expected = str(record.get("record_sha256") or "")
        unsealed = dict(record)
        unsealed.pop("record_sha256", None)
        if not SHA256_RE.fullmatch(expected) or not hmac.compare_digest(expected, _sha256_json(unsealed)):
            raise BridgeError("bridge_record_sha256_mismatch")
        return job_dir, record

    @staticmethod
    def _check_candidate(record: Mapping[str, Any], candidate_sha256: str) -> str:
        candidate = _require_sha256(candidate_sha256, "candidate_sha256")
        expected = str(record["request"]["candidate_sha256"])
        if not hmac.compare_digest(candidate, expected):
            raise BridgeError(
                "stale_candidate_sha256", expected_candidate_sha256=expected,
            )
        return candidate

    def request_review(self, request: Mapping[str, Any]) -> dict[str, Any]:
        normalised, idempotency_key, bridge_request_sha = _normalise_request(request)
        key_sha = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        handoff_seed = "\0".join((
            "camino_b", normalised["run_id"], normalised["candidate_sha256"], key_sha,
        )).encode("utf-8")
        handoff_id = "B14_" + hashlib.sha256(handoff_seed).hexdigest()[:32]
        key_path = self.root / "keys" / (key_sha + ".json")

        with self._locked():
            if key_path.exists():
                try:
                    key_record = json.loads(key_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise BridgeError("idempotency_index_unreadable") from exc
                if not hmac.compare_digest(str(key_record.get("bridge_request_sha256") or ""), bridge_request_sha):
                    raise BridgeError("idempotency_conflict")
                existing_id = str(key_record.get("handoff_id") or "")
                _, existing = self._load_record(existing_id)
                response = self._public_status(existing)
                response["idempotent_replay"] = True
                return response

            job_dir = self._job_dir(handoff_id)
            if job_dir.exists():
                _, existing = self._load_record(handoff_id)
                if not hmac.compare_digest(str(existing.get("bridge_request_sha256") or ""), bridge_request_sha):
                    raise BridgeError("handoff_collision")
            else:
                job_dir.mkdir(parents=True, mode=0o700)
                now = utc_now()
                record = {
                    "schema_version": RECORD_SCHEMA,
                    "handoff_id": handoff_id,
                    "status": AWAITING,
                    "revision": 1,
                    "created_at_utc": now,
                    "updated_at_utc": now,
                    "bridge_request_sha256": bridge_request_sha,
                    "idempotency_key_sha256": key_sha,
                    "request": normalised,
                    "claim": None,
                    "primary_failure": None,
                    "completion": None,
                }
                self._save_record(job_dir, record)
            self._write_json(key_path, {
                "schema_version": "camino_b_slot14_idempotency_index.v1",
                "handoff_id": handoff_id,
                "bridge_request_sha256": bridge_request_sha,
                "idempotency_key_sha256": key_sha,
            })
            _, stored = self._load_record(handoff_id)
            response = self._public_status(stored)
            response["idempotent_replay"] = False
            return response

    def get_status(self, handoff_id: str, candidate_sha256: str) -> dict[str, Any]:
        with self._locked():
            _, record = self._load_record(handoff_id)
            self._check_candidate(record, candidate_sha256)
            return self._public_status(record)

    def claim(
        self,
        handoff_id: str,
        candidate_sha256: str,
        *,
        worker_id: str,
        route_id: str,
        claim_id: str,
        host_id: str,
        lease_seconds: int = 1800,
    ) -> dict[str, Any]:
        worker_id = _require_safe_id(worker_id, "worker_id")
        route_id = _require_safe_id(route_id, "route_id")
        claim_id = _require_safe_id(claim_id, "claim_id")
        host_id = _require_safe_id(host_id, "host_id")
        if route_id not in ROUTE_WORKERS or ROUTE_WORKERS[route_id] != worker_id:
            raise BridgeError("claim_worker_route_mismatch")
        if not 60 <= int(lease_seconds) <= 86400:
            raise BridgeError("claim_lease_seconds_invalid")

        with self._locked():
            job_dir, record = self._load_record(handoff_id)
            candidate = self._check_candidate(record, candidate_sha256)
            current = record.get("claim")
            if record.get("status") == CLAIMED and isinstance(current, dict):
                same = (
                    current.get("claim_id") == claim_id
                    and current.get("worker_id") == worker_id
                    and current.get("route_id") == route_id
                    and current.get("host_id") == host_id
                )
                if not same:
                    raise BridgeError("job_already_claimed")
                secret_path = job_dir / ".claim_token"
                if not secret_path.is_file() or secret_path.is_symlink():
                    raise BridgeError("claim_token_missing")
                token = secret_path.read_text(encoding="utf-8").strip()
                return self._claim_response(record, token, idempotent=True)
            if record.get("status") != AWAITING:
                raise BridgeError("job_not_claimable", status=record.get("status"))
            primary_failure = record.get("primary_failure")
            if route_id == FALLBACK_ROUTE and not self._valid_primary_failure(record):
                raise BridgeError("fallback_requires_valid_claude_failure")
            if route_id == PRIMARY_ROUTE and primary_failure:
                raise BridgeError("primary_already_failed_fallback_required")

            token = secrets.token_urlsafe(32)
            token_sha = hashlib.sha256(token.encode("utf-8")).hexdigest()
            claimed_at = dt.datetime.now(dt.timezone.utc)
            expires_at = claimed_at + dt.timedelta(seconds=int(lease_seconds))
            receipt = {
                "schema_version": CLAIM_SCHEMA,
                "handoff_id": handoff_id,
                "claim_id": claim_id,
                "worker_id": worker_id,
                "route_id": route_id,
                "host_id": host_id,
                "run_id": record["request"]["run_id"],
                "slot_id": "14",
                "candidate_sha256": candidate,
                "bridge_request_sha256": record["bridge_request_sha256"],
                "slot14_audit_request_sha256": record["request"]["request_sha256"],
                "diff_sha256": record["request"]["diff_sha256"],
                "claimed_at_utc": claimed_at.isoformat(),
                "lease_expires_at_utc": expires_at.isoformat(),
            }
            receipt_sha = _sha256_json(receipt)
            record.update({
                "status": CLAIMED,
                "revision": int(record["revision"]) + 1,
                "updated_at_utc": utc_now(),
                "claim": {
                    **receipt,
                    "claim_token_sha256": token_sha,
                    "claim_receipt_sha256": receipt_sha,
                },
            })
            self._atomic_write(job_dir / ".claim_token", (token + "\n").encode("utf-8"))
            self._write_json(job_dir / "claim_receipt.json", {**receipt, "claim_receipt_sha256": receipt_sha})
            self._save_record(job_dir, record)
            return self._claim_response(record, token, idempotent=False)

    @staticmethod
    def _valid_primary_failure(record: Mapping[str, Any]) -> bool:
        failure = record.get("primary_failure")
        if not isinstance(failure, dict):
            return False
        request = record.get("request") or {}
        return (
            failure.get("route_id") == PRIMARY_ROUTE
            and failure.get("worker_id") == "claude_code"
            and failure.get("error_class") in ALLOWED_CLAUDE_FAILURES
            and failure.get("candidate_sha256") == request.get("candidate_sha256")
            and SHA256_RE.fullmatch(str(failure.get("bundle_receipt_sha256") or "")) is not None
        )

    @staticmethod
    def _claim_response(record: Mapping[str, Any], token: str, *, idempotent: bool) -> dict[str, Any]:
        claim = dict(record.get("claim") or {})
        claim.pop("claim_token_sha256", None)
        return {
            "status": CLAIMED,
            "claim": claim,
            "claim_token": token,
            "idempotent_replay": idempotent,
            "terminal_approval": False,
        }

    def complete(
        self,
        handoff_id: str,
        candidate_sha256: str,
        *,
        claim_token: str,
        bundle_dir: Path | str,
    ) -> dict[str, Any]:
        if not claim_token:
            raise BridgeError("claim_token_required")
        with self._locked():
            job_dir, record = self._load_record(handoff_id)
            candidate = self._check_candidate(record, candidate_sha256)
            if record.get("status") != CLAIMED or not isinstance(record.get("claim"), dict):
                raise BridgeError("job_not_claimed")
            expected_token_sha = str(record["claim"].get("claim_token_sha256") or "")
            actual_token_sha = hashlib.sha256(claim_token.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(expected_token_sha, actual_token_sha):
                raise BridgeError("claim_token_invalid")

            receipt, result, is_primary_failure = self._import_bundle(
                job_dir, Path(bundle_dir), record, candidate,
            )
            token_path = job_dir / ".claim_token"
            if is_primary_failure:
                failure = {
                    **receipt,
                    "error_class": str(result.get("error_class") or ""),
                    "status": str(result.get("status") or ""),
                }
                record.update({
                    "status": AWAITING,
                    "revision": int(record["revision"]) + 1,
                    "updated_at_utc": utc_now(),
                    "primary_failure": failure,
                    "claim": None,
                })
                self._write_json(job_dir / "primary_failure_receipt.json", failure)
                token_path.unlink(missing_ok=True)
                self._save_record(job_dir, record)
                response = self._public_status(record)
                response.update({"fallback_armed": True, "attempt_receipt": receipt})
                return response

            completion = {
                "schema_version": RESULT_SCHEMA,
                **receipt,
                "result": result,
                "transport_completed": True,
                "terminal_approval": False,
                "requires_terminal_gate_validation": True,
                "completed_at_utc": utc_now(),
            }
            completion_sha = _sha256_json(completion)
            completion["completion_receipt_sha256"] = completion_sha
            self._write_json(job_dir / "completion_receipt.json", completion)
            done_content = ("DONE " + completion_sha + "\n").encode("utf-8")
            self._atomic_write(job_dir / "CAMINO_B_SLOT14_BRIDGE.DONE", done_content)
            done_sha = hashlib.sha256(done_content).hexdigest()
            record.update({
                "status": COMPLETED,
                "revision": int(record["revision"]) + 1,
                "updated_at_utc": utc_now(),
                "completion": {
                    "completion_receipt_sha256": completion_sha,
                    "bridge_done_sha256": done_sha,
                    "bundle_receipt_sha256": receipt["bundle_receipt_sha256"],
                    "worker_id": receipt["worker_id"],
                    "route_id": receipt["route_id"],
                },
                "claim": None,
            })
            token_path.unlink(missing_ok=True)
            self._save_record(job_dir, record)
            return self.get_result_unlocked(job_dir, record)

    def _import_bundle(
        self,
        job_dir: Path,
        source: Path,
        record: Mapping[str, Any],
        candidate: str,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        if source.is_symlink() or not source.is_dir():
            raise BridgeError("worker_bundle_invalid_path")
        source = source.resolve()
        for item in source.rglob("*"):
            if item.is_symlink():
                raise BridgeError("worker_bundle_symlink_rejected")
            if item.is_dir() and item != source:
                raise BridgeError("worker_bundle_nested_directory_rejected")
            if not item.is_file() and not item.is_dir():
                raise BridgeError("worker_bundle_non_regular_entry")

        claim = dict(record["claim"])
        attempts = job_dir / "attempts"
        attempts.mkdir(mode=0o700, exist_ok=True)
        final = attempts / ("%04d_%s" % (int(record["revision"]), claim["claim_id"]))
        staging = attempts / (".%s.%s.staging" % (final.name, uuid.uuid4().hex))
        if final.exists():
            raise BridgeError("attempt_bundle_collision")
        try:
            staging.mkdir(mode=0o700)
            for item in source.iterdir():
                if not item.is_file() or item.is_symlink():
                    raise BridgeError("worker_bundle_entry_invalid")
                shutil.copy2(item, staging / item.name, follow_symlinks=False)
            validation = validate_bundle(
                staging, str(claim["worker_id"]), expected_candidate_sha256=candidate,
            )
            result_path = staging / "result.json"
            if not result_path.is_file() or result_path.is_symlink():
                raise BridgeError("worker_result_json_missing")
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BridgeError("worker_result_json_invalid") from exc
            expected_identity = {
                "run_id": record["request"]["run_id"],
                "slot_id": "14",
                "candidate_sha256": candidate,
                "worker_id": claim["worker_id"],
                "route_id": claim["route_id"],
            }
            for field, expected in expected_identity.items():
                if str(result.get(field) or "") != str(expected):
                    raise BridgeError(
                        "worker_result_identity_mismatch", field=field,
                        expected=str(expected), observed=str(result.get(field) or ""),
                    )
            if claim["route_id"] == FALLBACK_ROUTE:
                auth = result.get("auth") if isinstance(result.get("auth"), dict) else {}
                model_preflight = (
                    result.get("model_preflight")
                    if isinstance(result.get("model_preflight"), dict) else {}
                )
                fallback_identity_ok = (
                    result.get("model_id") == "gpt-5.6-sol"
                    and result.get("model_reasoning_effort") == "ultra"
                    and auth.get("ok") is True
                    and auth.get("auth_method") == "chatgpt_subscription"
                    and model_preflight.get("ok") is True
                    and model_preflight.get("model_id") == "gpt-5.6-sol"
                    and model_preflight.get("reasoning_effort") == "ultra"
                )
                if not fallback_identity_ok:
                    raise BridgeError("codex_fallback_subscription_identity_invalid")
            manifest = validation.get("manifest") or {}
            if str(manifest.get("run_id") or "") != str(record["request"]["run_id"]):
                raise BridgeError("worker_manifest_run_id_mismatch")
            error_class = str(result.get("error_class") or "")
            status = str(result.get("status") or "").lower()
            is_primary_failure = (
                claim["route_id"] == PRIMARY_ROUTE
                and status not in {"ok", "completed"}
                and error_class in ALLOWED_CLAUDE_FAILURES
            )
            violations = list(validation.get("violations") or [])
            if is_primary_failure:
                unexpected = [
                    item for item in violations
                    if not item.startswith("worker_non_success_status:")
                ]
                if unexpected:
                    raise BridgeError("worker_failure_bundle_invalid", violations=unexpected)
            elif not validation.get("valid"):
                raise BridgeError("worker_bundle_invalid", violations=violations)
            if status not in {"ok", "completed"} and not is_primary_failure:
                raise BridgeError("worker_non_success_not_accepted", status=status)

            os.replace(str(staging), str(final))
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        manifest_path = final / "OUTPUT_MANIFEST.json"
        if not manifest_path.is_file():
            manifests = [path for name in (
                "GPT_CODE_OUTPUT.MANIFEST.json", "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json",
            ) if (path := final / name).is_file()]
            if not manifests:
                raise BridgeError("worker_manifest_missing_after_import")
            manifest_path = manifests[0]
        done_files = sorted(final.glob("*.DONE"))
        if not done_files:
            raise BridgeError("worker_done_missing_after_import")
        file_receipts = [
            {"path": path.name, "sha256": _sha256_file(path), "size_bytes": path.stat().st_size}
            for path in sorted(final.iterdir()) if path.is_file()
        ]
        bundle_receipt_sha = _sha256_json(file_receipts)
        receipt = {
            "handoff_id": record["handoff_id"],
            "claim_id": claim["claim_id"],
            "run_id": record["request"]["run_id"],
            "slot_id": "14",
            "candidate_sha256": candidate,
            "worker_id": claim["worker_id"],
            "route_id": claim["route_id"],
            "bridge_request_sha256": record["bridge_request_sha256"],
            "slot14_audit_request_sha256": record["request"]["request_sha256"],
            "diff_sha256": record["request"]["diff_sha256"],
            "worker_result_sha256": _sha256_file(final / "result.json"),
            "worker_manifest_sha256": _sha256_file(manifest_path),
            "worker_done": [
                {"name": path.name, "sha256": _sha256_file(path)} for path in done_files
            ],
            "bundle_receipt_sha256": bundle_receipt_sha,
            "bundle_files": file_receipts,
            "queue_bundle_ref": str(final.relative_to(self.root)),
        }
        return receipt, result, is_primary_failure

    def get_result(self, handoff_id: str, candidate_sha256: str) -> dict[str, Any]:
        with self._locked():
            job_dir, record = self._load_record(handoff_id)
            self._check_candidate(record, candidate_sha256)
            return self.get_result_unlocked(job_dir, record)

    def get_result_unlocked(self, job_dir: Path, record: Mapping[str, Any]) -> dict[str, Any]:
        if record.get("status") != COMPLETED:
            return {
                **self._public_status(record),
                "result_ready": False,
            }
        completion_path = job_dir / "completion_receipt.json"
        done_path = job_dir / "CAMINO_B_SLOT14_BRIDGE.DONE"
        if not completion_path.is_file() or not done_path.is_file():
            raise BridgeError("bridge_completion_receipt_missing")
        try:
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BridgeError("bridge_completion_receipt_invalid") from exc
        expected_completion_sha = str(record["completion"]["completion_receipt_sha256"])
        unsealed = dict(completion)
        observed_completion_sha = str(unsealed.pop("completion_receipt_sha256", ""))
        if (
            not hmac.compare_digest(expected_completion_sha, observed_completion_sha)
            or not hmac.compare_digest(expected_completion_sha, _sha256_json(unsealed))
        ):
            raise BridgeError("bridge_completion_receipt_sha256_mismatch")
        if not hmac.compare_digest(
            str(record["completion"]["bridge_done_sha256"]), _sha256_file(done_path),
        ):
            raise BridgeError("bridge_done_sha256_mismatch")
        return {
            "status": COMPLETED,
            "handoff_id": record["handoff_id"],
            "candidate_sha256": record["request"]["candidate_sha256"],
            "result_ready": True,
            "transport_completed": True,
            "terminal_approval": False,
            "requires_terminal_gate_validation": True,
            "completion": completion,
        }

    @staticmethod
    def _public_status(record: Mapping[str, Any]) -> dict[str, Any]:
        request = record["request"]
        claim = record.get("claim")
        public_claim = None
        if isinstance(claim, dict):
            public_claim = {
                key: value for key, value in claim.items()
                if key != "claim_token_sha256"
            }
        fallback_armed = LocalSlot14Queue._valid_primary_failure(record)
        operator_action = None
        if record.get("status") == AWAITING:
            operator_action = (
                "start_codex_fallback_local_worker" if fallback_armed
                else "start_or_reauthenticate_claude_local_worker"
            )
        return {
            "status": record["status"],
            "handoff_id": record["handoff_id"],
            "run_id": request["run_id"],
            "slot_id": "14",
            "candidate_sha256": request["candidate_sha256"],
            "request_path": request["request_path"],
            "request_sha256": request["request_sha256"],
            "diff_path": request["diff_path"],
            "diff_sha256": request["diff_sha256"],
            "bridge_request_sha256": record["bridge_request_sha256"],
            "revision": record["revision"],
            "updated_at_utc": record["updated_at_utc"],
            "claim": public_claim,
            "fallback_armed": fallback_armed,
            "result_ready": record.get("status") == COMPLETED,
            "operator_action": operator_action,
            "terminal_approval": False,
            "requires_terminal_gate_validation": True,
        }


def _read_json_file(path: str) -> dict[str, Any]:
    supplied = Path(path).expanduser()
    if supplied.is_symlink() or not supplied.is_file():
        raise BridgeError("json_input_file_invalid")
    try:
        value = json.loads(supplied.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError("json_input_file_unreadable") from exc
    if not isinstance(value, dict):
        raise BridgeError("json_input_must_be_object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Camino B local slot-14 bridge queue")
    parser.add_argument("--queue-root", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request")
    request.add_argument("--request-json", required=True)
    for name in ("status", "result"):
        command = commands.add_parser(name)
        command.add_argument("--handoff-id", required=True)
        command.add_argument("--candidate-sha256", required=True)
    claim = commands.add_parser("claim")
    claim.add_argument("--handoff-id", required=True)
    claim.add_argument("--candidate-sha256", required=True)
    claim.add_argument("--worker-id", required=True)
    claim.add_argument("--route-id", required=True)
    claim.add_argument("--claim-id", required=True)
    claim.add_argument("--host-id", required=True)
    claim.add_argument("--lease-seconds", type=int, default=1800)
    complete = commands.add_parser("complete")
    complete.add_argument("--handoff-id", required=True)
    complete.add_argument("--candidate-sha256", required=True)
    complete.add_argument("--bundle", required=True)
    complete.add_argument("--claim-token-file", required=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        queue = LocalSlot14Queue(args.queue_root)
        if args.command == "request":
            result = queue.request_review(_read_json_file(args.request_json))
        elif args.command == "status":
            result = queue.get_status(args.handoff_id, args.candidate_sha256)
        elif args.command == "result":
            result = queue.get_result(args.handoff_id, args.candidate_sha256)
        elif args.command == "claim":
            result = queue.claim(
                args.handoff_id, args.candidate_sha256,
                worker_id=args.worker_id, route_id=args.route_id,
                claim_id=args.claim_id, host_id=args.host_id,
                lease_seconds=args.lease_seconds,
            )
        else:
            token_path = Path(args.claim_token_file).expanduser()
            if token_path.is_symlink() or not token_path.is_file():
                raise BridgeError("claim_token_file_invalid")
            token = token_path.read_text(encoding="utf-8").strip()
            result = queue.complete(
                args.handoff_id, args.candidate_sha256,
                claim_token=token, bundle_dir=args.bundle,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BridgeError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
