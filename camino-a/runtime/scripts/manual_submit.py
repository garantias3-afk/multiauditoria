#!/usr/bin/env python3
"""Ingest one logical manual-audit submission as a verified worker bundle.

The CLI is intentionally a data-plane tool.  It accepts pasted text and several
attachments, validates every item, copies files without loading them wholly into
memory, and publishes the completed bundle atomically under the manual worker
lane.  The historical single ``--file`` invocation remains valid.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (  # noqa: E402
    assert_no_unredacted_secret, load_state,
    safe_slug,
    utc_now,
    utc_now_compact,
    write_output_manifest_and_done,
)
from scripts.state_db import StateDB  # noqa: E402
from scripts.quality_log import auditor_from_result, record_quality_event  # noqa: E402


TEXT_EXTENSIONS = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".py", ".csv"})
BINARY_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".pdf", ".zip"})
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | BINARY_EXTENSIONS

# The worker-bus validator has a 64 MiB hard ceiling per artifact. Larger
# inputs belong on the chunked Gateway data plane, not in a monolithic bundle.
# Operators may lower this limit, but cannot create a bundle the bus will reject.
BUS_FILE_HARD_LIMIT = 64 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = BUS_FILE_HARD_LIMIT
DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_ITEMS = 100
DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_ZIP_MEMBERS = 2000
COPY_CHUNK_BYTES = 1024 * 1024
SECRET_SCAN_OVERLAP = 4096

SAFE_OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SAFE_ROLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SHA256_RE = re.compile(r"^(?:sha256:)?([a-fA-F0-9]{64})$")


class SubmissionError(ValueError):
    """Expected fail-closed validation error."""


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SubmissionError("invalid_integer_env:%s" % name) from exc
    if value < minimum:
        raise SubmissionError("invalid_integer_env:%s" % name)
    return value


def _limits() -> dict[str, int]:
    configured_file = _env_int("CAMINO_MANUAL_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES)
    if configured_file > BUS_FILE_HARD_LIMIT:
        raise SubmissionError(
            "CAMINO_MANUAL_MAX_FILE_BYTES_exceeds_worker_bus_limit:%d>%d"
            % (configured_file, BUS_FILE_HARD_LIMIT)
        )
    return {
        "max_file_bytes": configured_file,
        "max_total_bytes": _env_int("CAMINO_MANUAL_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES),
        "max_items": _env_int("CAMINO_MANUAL_MAX_ITEMS", DEFAULT_MAX_ITEMS),
        "max_zip_uncompressed_bytes": _env_int(
            "CAMINO_MANUAL_MAX_ZIP_UNCOMPRESSED_BYTES", DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES
        ),
        "max_zip_members": _env_int("CAMINO_MANUAL_MAX_ZIP_MEMBERS", DEFAULT_MAX_ZIP_MEMBERS),
    }


def _normalise_sha256(value: str) -> str:
    match = SHA256_RE.fullmatch(str(value).strip())
    if not match:
        raise SubmissionError("candidate_sha256_invalid")
    return match.group(1).lower()


def _validate_role(value: str) -> str:
    value = str(value or "").strip()
    if not SAFE_ROLE.fullmatch(value):
        raise SubmissionError("artifact_role_invalid:%s" % value[:80])
    return value


def _parse_file_roles(values: Iterable[str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise SubmissionError("file_role_expected_PATH=ROLE:%s" % raw)
        key, role = raw.rsplit("=", 1)
        key = key.strip()
        if not key:
            raise SubmissionError("file_role_empty_path")
        role = _validate_role(role)
        roles[key] = role
        roles[str(Path(key).expanduser())] = role
        roles[Path(key).name] = role
    return roles


def _role_for_file(raw_path: str, suffix: str, overrides: dict[str, str]) -> str:
    for key in (raw_path, str(Path(raw_path).expanduser()), Path(raw_path).name):
        if key in overrides:
            return overrides[key]
    if suffix in {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}:
        return "manual_audit"
    if suffix == ".py":
        return "source_evidence"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image_evidence"
    if suffix == ".pdf":
        return "document_evidence"
    return "archive_evidence"


def _reject_path_argument(raw: str) -> Path:
    supplied = Path(raw).expanduser()
    if ".." in supplied.parts:
        raise SubmissionError("path_traversal_rejected:%s" % raw)
    absolute = supplied if supplied.is_absolute() else Path.cwd() / supplied
    # Check the leaf before resolve(), otherwise a symlink becomes invisible.
    if absolute.is_symlink():
        raise SubmissionError("symlink_rejected:%s" % raw)
    try:
        resolved = absolute.resolve(strict=True)
    except (OSError, FileNotFoundError) as exc:
        raise SubmissionError("file_not_found:%s" % raw) from exc
    if not resolved.is_file():
        raise SubmissionError("not_a_regular_file:%s" % raw)
    if resolved.is_symlink():
        raise SubmissionError("symlink_rejected:%s" % raw)
    return resolved


def _safe_destination_name(index: int, source_name: str, used: set[str]) -> str:
    source = Path(source_name)
    suffix = source.suffix.lower()
    stem = safe_slug(source.stem, fallback="attachment")[:150]
    candidate = "%03d_%s%s" % (index, stem, suffix)
    if not SAFE_OUTPUT_NAME.fullmatch(candidate):
        raise SubmissionError("unsafe_output_name:%s" % candidate)
    while candidate in used:
        candidate = "%03d_%s_%s%s" % (index, stem, uuid.uuid4().hex[:8], suffix)
    used.add(candidate)
    return candidate


def _mime_and_magic(path: Path, suffix: str) -> tuple[str, str]:
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as handle:
        head = handle.read(16)
    magic = "extension_only"
    if suffix == ".png":
        magic = "png"
        valid = head.startswith(b"\x89PNG\r\n\x1a\n")
        guessed = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        magic = "jpeg"
        valid = head.startswith(b"\xff\xd8\xff")
        guessed = "image/jpeg"
    elif suffix == ".webp":
        magic = "webp"
        valid = len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
        guessed = "image/webp"
    elif suffix == ".pdf":
        magic = "pdf"
        valid = head.startswith(b"%PDF-")
        guessed = "application/pdf"
    elif suffix == ".zip":
        magic = "zip"
        valid = head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
        guessed = "application/zip"
    else:
        known_binary = (
            head.startswith(b"%PDF-")
            or head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
            or head.startswith(b"\x89PNG\r\n\x1a\n")
            or head.startswith(b"\xff\xd8\xff")
            or (len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP")
        )
        valid = b"\x00" not in head and not known_binary
        if suffix == ".md":
            guessed = "text/markdown"
        elif suffix in TEXT_EXTENSIONS:
            guessed = guessed if guessed.startswith("text/") else "text/plain"
    if not valid:
        raise SubmissionError("mime_magic_mismatch:%s:%s" % (path.name, suffix))
    return guessed, magic


def _scan_text_stream(handle: BinaryIO, *, context: str) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    tail = ""
    try:
        while True:
            raw = handle.read(COPY_CHUNK_BYTES)
            if not raw:
                break
            text = decoder.decode(raw, final=False)
            sample = tail + text
            assert_no_unredacted_secret(sample, context=context, allow_fixture_hint=True)
            tail = sample[-SECRET_SCAN_OVERLAP:]
        final = decoder.decode(b"", final=True)
        assert_no_unredacted_secret(tail + final, context=context, allow_fixture_hint=True)
    except UnicodeDecodeError as exc:
        raise SubmissionError("text_not_utf8:%s" % context) from exc


def _scan_binary_bytes(path: Path, *, context: str) -> None:
    """Best-effort scan of literal tokens embedded in a binary container."""
    tail = ""
    with path.open("rb") as handle:
        while True:
            raw = handle.read(COPY_CHUNK_BYTES)
            if not raw:
                break
            text = raw.decode("latin-1", errors="ignore")
            sample = tail + text
            assert_no_unredacted_secret(sample, context=context, allow_fixture_hint=True)
            tail = sample[-SECRET_SCAN_OVERLAP:]


def _validate_zip(path: Path, limits: dict[str, int]) -> dict[str, Any]:
    total = 0
    count = 0
    try:
        with zipfile.ZipFile(str(path), "r") as archive:
            for info in archive.infolist():
                count += 1
                if count > limits["max_zip_members"]:
                    raise SubmissionError("zip_too_many_members:%s" % path.name)
                member = Path(info.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise SubmissionError("zip_path_traversal:%s:%s" % (path.name, info.filename))
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and stat.S_ISLNK(mode):
                    raise SubmissionError("zip_symlink_rejected:%s:%s" % (path.name, info.filename))
                if info.flag_bits & 0x1:
                    raise SubmissionError("zip_encrypted_rejected:%s:%s" % (path.name, info.filename))
                total += int(info.file_size)
                if total > limits["max_zip_uncompressed_bytes"]:
                    raise SubmissionError("zip_uncompressed_limit:%s" % path.name)
                suffix = member.suffix.lower()
                if not info.is_dir() and suffix in TEXT_EXTENSIONS:
                    with archive.open(info, "r") as member_handle:
                        _scan_text_stream(
                            member_handle,
                            context="manual_zip:%s:%s" % (path.name, info.filename),
                        )
    except zipfile.BadZipFile as exc:
        raise SubmissionError("invalid_zip:%s" % path.name) from exc
    return {"member_count": count, "uncompressed_bytes": total, "members_validated": True}


def _validate_source(path: Path, suffix: str, limits: dict[str, int]) -> tuple[str, str, dict[str, Any]]:
    size = path.stat().st_size
    if size <= 0:
        raise SubmissionError("empty_file:%s" % path.name)
    if size > limits["max_file_bytes"]:
        raise SubmissionError(
            "file_too_large:%s:%d>%d" % (path.name, size, limits["max_file_bytes"])
        )
    mime, magic = _mime_and_magic(path, suffix)
    detail: dict[str, Any] = {}
    if suffix in TEXT_EXTENSIONS:
        with path.open("rb") as handle:
            _scan_text_stream(handle, context="manual_file:%s" % path.name)
        if suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SubmissionError("invalid_json:%s" % path.name) from exc
    elif suffix == ".zip":
        _scan_binary_bytes(path, context="manual_binary:%s" % path.name)
        detail.update(_validate_zip(path, limits))
    else:
        _scan_binary_bytes(path, context="manual_binary:%s" % path.name)
    return mime, magic, detail


def _copy_and_hash(source: Path, destination: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as src, destination.open("xb") as dst:
        while True:
            chunk = src.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            dst.write(chunk)
            total += len(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    return digest.hexdigest(), total


def _write_text_artifact(path: Path, content: str) -> tuple[str, int]:
    if not content.strip():
        raise SubmissionError("pasted_text_empty")
    assert_no_unredacted_secret(content, context="manual_pasted_text", allow_fixture_hint=True)
    raw = content.encode("utf-8")
    with path.open("xb") as handle:
        view = memoryview(raw)
        for offset in range(0, len(view), COPY_CHUNK_BYTES):
            handle.write(view[offset : offset + COPY_CHUNK_BYTES])
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _record_quality(run_dir: Path, args: argparse.Namespace, submission: dict[str, Any], final_dir: Path) -> None:
    auditor = auditor_from_result(args.worker, {
        "worker_id": args.worker,
        "status": "manual_audit_ingested",
        "model_id": args.model_id or ("gpt_manual" if args.worker == "manual_gpt" else "claude_manual"),
        "provider_id": args.provider_id or ("chatgpt_plan" if args.worker == "manual_gpt" else "claude_plan_manual"),
        "provider_name": args.provider_name or ("ChatGPT" if args.worker == "manual_gpt" else "Claude"),
        "route_id": args.route_id or ("chatgpt_manual" if args.worker == "manual_gpt" else "claude_manual"),
        "route": args.route,
        "interface": args.interface,
        "cost_class": args.cost_class,
        "role": args.role,
    }, stage=args.stage)
    db = None
    try:
        db_path = run_dir / "STATE" / "state.sqlite"
        sqlite_is_local = True
        try:
            from scripts.drive_locator import assert_local_state_path, locate_drive

            drive_location = locate_drive(create=False)
            assert_local_state_path(db_path, drive_location)
        except ImportError:
            pass
        except Exception as exc:
            if str(exc).startswith("mutable_state_on_shared_drive_rejected:"):
                sqlite_is_local = False
            else:
                # Drive discovery is optional for local-only runs.  An invalid
                # Drive override must not cause us to open an existing DB that
                # may be on the shared mount.
                sqlite_is_local = not (
                    os.environ.get("CAMINO_SHARED_ROOT")
                    or os.environ.get("CAMINO_DRIVE_BUS_ROOT")
                )
        db = StateDB(db_path) if db_path.exists() and sqlite_is_local else None
        record_quality_event(
            run_dir,
            event="manual_audit_ingested",
            auditor=auditor,
            artifact={
                "bundle": str(final_dir),
                "submission_id": submission["submission_id"],
                "candidate_sha256": submission["candidate_sha256"],
                "items": submission["items"],
            },
            finding={
                "id": "manual_submission_%s" % submission["submission_id"],
                "type": "manual_audit_batch",
                "severity": "info",
                "summary": "Manual batch ingested from %s" % args.worker,
            },
            adjudication={"final_status": "PENDIENTE"},
            details={"stage": args.stage, "item_count": len(submission["items"])},
            audit_family="camino_a_manual_ingest",
            dedupe_key="manual_batch:%s" % submission["submission_sha256"],
            db=db,
        )
    finally:
        if db is not None:
            db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a verified manual audit batch")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--worker", required=True, choices=["manual_gpt", "manual_claude"])
    parser.add_argument("--stage", required=True, help="Stage name")
    parser.add_argument("--candidate-sha256", required=True, help="Expected candidate SHA-256")
    parser.add_argument(
        "--slot-id", default="",
        help="Canonical slot this evidence satisfies; defaults to cycle_state.current_slot",
    )
    parser.add_argument("--file", action="append", default=[], help="Attachment; repeatable")
    parser.add_argument("--text", action="append", default=[], help="Pasted audit text; repeatable")
    parser.add_argument("--text-file", action="append", default=[], help="UTF-8 text attachment; repeatable")
    parser.add_argument(
        "--file-role", action="append", default=[], metavar="PATH=ROLE",
        help="Override inferred artifact role for one attachment",
    )
    parser.add_argument(
        "--text-role", action="append", default=[],
        help="Role for each --text item in order (default manual_audit)",
    )
    parser.add_argument("--model-id", default="")
    parser.add_argument("--provider-id", default="")
    parser.add_argument("--provider-name", default="")
    parser.add_argument("--route-id", default="")
    parser.add_argument("--route", default="manual_submit")
    parser.add_argument("--interface", default="manual_batch")
    parser.add_argument("--cost-class", default="manual")
    parser.add_argument("--role", default="manual_auditor", help="Auditor role (legacy-compatible)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    staging_dir: Optional[Path] = None
    try:
        limits = _limits()
        candidate_sha256 = _normalise_sha256(args.candidate_sha256)
        run_dir = Path(args.run).expanduser().resolve()
        if not run_dir.is_dir() or run_dir.is_symlink():
            raise SubmissionError("run_dir_invalid:%s" % run_dir)
        if not SAFE_ROLE.fullmatch(str(args.stage)):
            raise SubmissionError("stage_invalid")
        state_slot = ""
        if (run_dir / "cycle_state.json").is_file() or (run_dir / "01_STATE" / "cycle_state.json").is_file():
            state_slot = str(load_state(run_dir).get("current_slot") or "")
        slot_id = str(args.slot_id or state_slot).strip()
        if slot_id and (not slot_id.isdigit() or not 1 <= int(slot_id) <= 14):
            raise SubmissionError("slot_id_invalid")

        raw_files = list(args.file) + list(args.text_file)
        if not raw_files and not args.text:
            raise SubmissionError("submission_has_no_items")
        if len(raw_files) + len(args.text) > limits["max_items"]:
            raise SubmissionError("submission_item_limit")
        if len(args.text_role) > len(args.text):
            raise SubmissionError("text_role_without_text")

        role_overrides = _parse_file_roles(args.file_role)
        worker_root = run_dir / "13_WORKER_BUS" / args.worker
        staging_root = worker_root / "STAGING"
        out_root = worker_root / "OUT"
        staging_root.mkdir(parents=True, exist_ok=True)
        out_root.mkdir(parents=True, exist_ok=True)

        submission_id = "%s_%s_%s" % (
            args.worker,
            utc_now_compact(),
            uuid.uuid4().hex[:12],
        )
        staging_dir = staging_root / submission_id
        final_dir = out_root / submission_id
        staging_dir.mkdir(mode=0o700)
        if final_dir.exists():
            raise SubmissionError("submission_collision")

        used_names: set[str] = set()
        items: list[dict[str, Any]] = []
        total_bytes = 0
        index = 0

        for raw_path in raw_files:
            index += 1
            source = _reject_path_argument(raw_path)
            assert_no_unredacted_secret(source.name, context="manual_filename", allow_fixture_hint=True)
            suffix = source.suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                raise SubmissionError("extension_disallowed:%s" % suffix)
            if raw_path in args.text_file and suffix not in TEXT_EXTENSIONS:
                raise SubmissionError("text_file_extension_invalid:%s" % suffix)
            mime, magic, validation = _validate_source(source, suffix, limits)
            output_name = _safe_destination_name(index, source.name, used_names)
            sha256, size = _copy_and_hash(source, staging_dir / output_name)
            total_bytes += size
            if total_bytes > limits["max_total_bytes"]:
                raise SubmissionError("submission_total_size_limit")
            items.append({
                "item_id": "item_%03d" % index,
                "kind": "text_file" if raw_path in args.text_file else "attachment",
                "source_name": source.name,
                "stored_name": output_name,
                "role": _role_for_file(raw_path, suffix, role_overrides),
                "mime_type": mime,
                "magic": magic,
                "extension": suffix,
                "size_bytes": size,
                "sha256": sha256,
                "secret_scan": "utf8_stream" if suffix in TEXT_EXTENSIONS else "literal_binary_stream",
                "validation": validation,
            })

        for text_index, content in enumerate(args.text, start=1):
            index += 1
            role = args.text_role[text_index - 1] if text_index <= len(args.text_role) else "manual_audit"
            role = _validate_role(role)
            output_name = _safe_destination_name(index, "pasted_text_%03d.md" % text_index, used_names)
            sha256, size = _write_text_artifact(staging_dir / output_name, content)
            if size > limits["max_file_bytes"]:
                raise SubmissionError("pasted_text_too_large:%d" % size)
            total_bytes += size
            if total_bytes > limits["max_total_bytes"]:
                raise SubmissionError("submission_total_size_limit")
            items.append({
                "item_id": "item_%03d" % index,
                "kind": "pasted_text",
                "source_name": "pasted_text_%03d" % text_index,
                "stored_name": output_name,
                "role": role,
                "mime_type": "text/markdown",
                "magic": "generated_utf8",
                "extension": ".md",
                "size_bytes": size,
                "sha256": sha256,
                "secret_scan": "in_memory_utf8",
                "validation": {},
            })

        digest_input = json.dumps(
            [{"sha256": item["sha256"], "role": item["role"], "stored_name": item["stored_name"]} for item in items],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        submission_sha256 = hashlib.sha256(digest_input).hexdigest()
        submission = {
            "schema_version": "camino_a_manual_submission.v2",
            "submission_id": submission_id,
            "submission_sha256": submission_sha256,
            "run_id": run_dir.name,
            "worker_id": args.worker,
            "stage": args.stage,
            "candidate_sha256": candidate_sha256,
            "slot_id": slot_id,
            "created_at_utc": utc_now(),
            "item_count": len(items),
            "total_bytes": total_bytes,
            "limits": limits,
            "items": items,
        }
        _write_json_atomic(staging_dir / "submission.json", submission)
        result = {
            "schema_version": "camino_a_manual_worker_result.v2",
            "worker_id": args.worker,
            "status": "manual_audit_ingested",
            "submission_id": submission_id,
            "submission_sha256": submission_sha256,
            "candidate_sha256": candidate_sha256,
            "slot_id": slot_id,
            "artifact_count": len(items),
            "artifacts": items,
        }
        _write_json_atomic(staging_dir / "result.json", result)

        listed_files = tuple([item["stored_name"] for item in items] + ["submission.json", "result.json"])
        staging_relative = str(staging_dir.relative_to(run_dir))
        write_output_manifest_and_done(
            run_dir,
            staging_relative,
            done_name="MANUAL_SUBMISSION.DONE",
            stage=args.stage,
            candidate_sha256=candidate_sha256,
            files=listed_files,
        )
        os.replace(str(staging_dir), str(final_dir))
        staging_dir = None
        _record_quality(run_dir, args, submission, final_dir)

        print(json.dumps({
            "status": "submitted",
            "submission_id": submission_id,
            "submission_sha256": submission_sha256,
            "item_count": len(items),
            "total_bytes": total_bytes,
            "bundle": str(final_dir),
        }, ensure_ascii=False, indent=2))
        return 0
    except (SubmissionError, SystemExit, OSError) as exc:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
