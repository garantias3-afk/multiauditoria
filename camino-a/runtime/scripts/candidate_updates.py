#!/usr/bin/env python3
"""Safe current-candidate lifecycle and correction promotion.

``INPUT/target_snapshot`` is the immutable seed. ``00_CANDIDATE`` is the
current, mutable-by-promotion candidate consumed by workers and packaged at the
end. A worker may propose a complete replacement only through a hash-bound
``candidate_update.zip`` declared in its result and output manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from scripts.camino_a_worker_bus import (
    SCANNABLE_EXTENSIONS, SECRET_SCAN_CHUNK_CHARS, SECRET_SCAN_OVERLAP_CHARS,
    assert_no_secret,
)


UPDATE_SCHEMA = "camino_candidate_update.v1"
RUNTIME_OVERLAY = ".camino_runtime"
DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024


class CandidateUpdateError(RuntimeError):
    pass


def candidate_source(run_dir: Path) -> Path:
    """Return the current candidate, with compatibility fallback for old runs."""
    run_dir = Path(run_dir)
    current = run_dir / "00_CANDIDATE"
    if current.is_dir() and not current.is_symlink():
        return current
    return run_dir / "INPUT" / "target_snapshot"


def _candidate_files(root: Path, *, exclude_runtime_overlay: bool = False) -> list[Path]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise CandidateUpdateError("candidate_root_missing_or_symlink")
    files: list[Path] = []
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root)
        if exclude_runtime_overlay and relative.parts and relative.parts[0] == RUNTIME_OVERLAY:
            continue
        if item.is_symlink():
            raise CandidateUpdateError(f"candidate_symlink_rejected:{relative}")
        if item.is_file():
            files.append(item)
    return files


def hash_candidate_tree(root: Path, *, exclude_runtime_overlay: bool = False) -> str:
    """Hash file paths and bytes; empty directories do not affect identity."""
    digest = hashlib.sha256()
    root = Path(root)
    for item in _candidate_files(root, exclude_runtime_overlay=exclude_runtime_overlay):
        relative = item.relative_to(root).as_posix()
        file_digest = hashlib.sha256()
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(chunk)
        digest.update(f"F:{relative}:{file_digest.hexdigest()}\n".encode("utf-8"))
    return digest.hexdigest()


def copy_candidate_tree(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    _candidate_files(source)
    if destination.is_symlink():
        raise CandidateUpdateError("candidate_destination_symlink")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=False)


def verify_candidate_binding(run_dir: Path, expected_sha256: str) -> tuple[bool, str]:
    try:
        actual = hash_candidate_tree(candidate_source(run_dir))
    except CandidateUpdateError as exc:
        return False, str(exc)
    expected = str(expected_sha256 or "").lower()
    if actual != expected:
        return False, f"candidate_tree_sha256_mismatch:actual={actual}:expected={expected}"
    return True, actual


def scan_candidate_for_secrets(root: Path) -> list[str]:
    """Streaming secret scan without treating large source files as output."""
    violations: list[str] = []
    root = Path(root)
    for item in _candidate_files(root):
        if item.suffix.lower() not in SCANNABLE_EXTENSIONS:
            continue
        tail = ""
        try:
            with item.open("r", encoding="utf-8", errors="replace") as handle:
                while True:
                    text = handle.read(SECRET_SCAN_CHUNK_CHARS)
                    if not text:
                        break
                    sample = tail + text
                    assert_no_secret(
                        sample, context=f"candidate/{item.relative_to(root)}",
                        allow_fixture=True,
                    )
                    tail = sample[-SECRET_SCAN_OVERLAP_CHARS:]
                if tail:
                    assert_no_secret(
                        tail, context=f"candidate/{item.relative_to(root)}",
                        allow_fixture=True,
                    )
        except (OSError, SystemExit) as exc:
            violations.append(str(exc))
    return violations


def create_candidate_update_archive(
    workspace: Path,
    bundle_dir: Path,
    *,
    source_candidate_sha256: str,
    worker_id: str,
    slot_id: str,
) -> dict[str, Any]:
    """Create a complete, overlay-free candidate archive from a worker workspace."""
    workspace = Path(workspace)
    bundle_dir = Path(bundle_dir)
    files = _candidate_files(workspace, exclude_runtime_overlay=True)
    max_files = int(os.environ.get("CAMINO_CANDIDATE_MAX_FILES", DEFAULT_MAX_FILES))
    max_file = int(os.environ.get("CAMINO_CANDIDATE_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES))
    max_total = int(os.environ.get("CAMINO_CANDIDATE_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES))
    if len(files) > max_files:
        raise CandidateUpdateError("candidate_update_file_limit")
    total = 0
    for item in files:
        size = item.stat().st_size
        if size > max_file:
            raise CandidateUpdateError(f"candidate_update_file_too_large:{item.name}")
        total += size
        if total > max_total:
            raise CandidateUpdateError("candidate_update_total_too_large")
    candidate_sha = hash_candidate_tree(workspace, exclude_runtime_overlay=True)
    if candidate_sha == str(source_candidate_sha256):
        raise CandidateUpdateError("candidate_update_has_no_content_change")
    archive = bundle_dir / "candidate_update.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as handle:
        for item in files:
            relative = item.relative_to(workspace).as_posix()
            handle.write(item, relative)
    archive_sha = _sha256_file(archive)
    return {
        "schema_version": UPDATE_SCHEMA,
        "source_candidate_sha256": str(source_candidate_sha256),
        "candidate_sha256": candidate_sha,
        "archive_path": archive.name,
        "archive_sha256": archive_sha,
        "file_count": len(files),
        "total_bytes": total,
        "worker_id": str(worker_id),
        "slot_id": str(slot_id),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(value: str) -> tuple[PurePosixPath, str]:
    if not value or "\\" in value or "\x00" in value:
        raise CandidateUpdateError("candidate_update_unsafe_zip_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise CandidateUpdateError("candidate_update_zip_traversal")
    normalized = unicodedata.normalize("NFC", path.as_posix()).strip("/")
    normalized_path = PurePosixPath(normalized)
    if not normalized or normalized_path.parts[0] == RUNTIME_OVERLAY:
        raise CandidateUpdateError("candidate_update_reserved_path")
    return normalized_path, normalized.casefold()


def _extract_verified_archive(archive: Path, destination: Path) -> dict[str, Any]:
    max_files = int(os.environ.get("CAMINO_CANDIDATE_MAX_FILES", DEFAULT_MAX_FILES))
    max_file = int(os.environ.get("CAMINO_CANDIDATE_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES))
    max_total = int(os.environ.get("CAMINO_CANDIDATE_MAX_TOTAL_BYTES", DEFAULT_MAX_TOTAL_BYTES))
    seen: set[str] = set()
    total = 0
    count = 0
    with zipfile.ZipFile(archive, "r") as handle:
        for member in handle.infolist():
            path, folded = _safe_member_name(member.filename)
            if folded in seen:
                raise CandidateUpdateError("candidate_update_duplicate_zip_path")
            seen.add(folded)
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise CandidateUpdateError("candidate_update_zip_symlink")
            if member.is_dir():
                (destination / Path(*path.parts)).mkdir(parents=True, exist_ok=True)
                continue
            count += 1
            if count > max_files:
                raise CandidateUpdateError("candidate_update_file_limit")
            if member.file_size > max_file:
                raise CandidateUpdateError("candidate_update_file_too_large")
            total += int(member.file_size)
            if total > max_total:
                raise CandidateUpdateError("candidate_update_total_too_large")
            target = destination / Path(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            remaining = int(member.file_size)
            with handle.open(member, "r") as source, target.open("xb") as output:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise CandidateUpdateError("candidate_update_truncated_member")
                    output.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise CandidateUpdateError("candidate_update_member_size_mismatch")
    return {"file_count": count, "total_bytes": total}


def validate_candidate_update_bundle(
    run_dir: Path,
    bundle_dir: Path,
    result: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    expected_slot_id: str,
) -> tuple[Path, dict[str, Any]]:
    """Validate and extract a correction proposal without mutating run state."""
    run_dir = Path(run_dir).resolve()
    bundle_dir = Path(bundle_dir).resolve()
    update = result.get("candidate_update")
    if not isinstance(update, dict) or update.get("schema_version") != UPDATE_SCHEMA:
        raise CandidateUpdateError("candidate_update_metadata_missing_or_invalid")
    current_sha = str(state.get("current_candidate_sha256") or "")
    if str(result.get("run_id") or "") != run_dir.name:
        raise CandidateUpdateError("candidate_update_run_mismatch")
    if str(result.get("slot_id") or "") != str(expected_slot_id):
        raise CandidateUpdateError("candidate_update_slot_mismatch")
    if str(result.get("candidate_sha256") or "") != current_sha:
        raise CandidateUpdateError("candidate_update_result_source_mismatch")
    if str(update.get("source_candidate_sha256") or "") != current_sha:
        raise CandidateUpdateError("candidate_update_source_mismatch")
    result_identity = str(result.get("worker_id") or result.get("brain") or "")
    if str(update.get("worker_id") or "") != result_identity:
        raise CandidateUpdateError("candidate_update_worker_mismatch")
    if str(update.get("slot_id") or "") != str(expected_slot_id):
        raise CandidateUpdateError("candidate_update_metadata_slot_mismatch")
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    corrections_applied = (
        result.get("corrections_applied") is True
        or decision.get("corrections_applied") is True
    )
    verdict = str(result.get("verdict") or decision.get("verdict") or "")
    if not corrections_applied or verdict != "CORRECTIONS_APPLIED":
        raise CandidateUpdateError("candidate_update_correction_claim_required")
    relative = Path(str(update.get("archive_path") or ""))
    if relative.is_absolute() or len(relative.parts) != 1 or relative.name != "candidate_update.zip":
        raise CandidateUpdateError("candidate_update_archive_path_invalid")
    archive = bundle_dir / relative
    if not archive.is_file() or archive.is_symlink():
        raise CandidateUpdateError("candidate_update_archive_missing_or_symlink")
    if _sha256_file(archive) != str(update.get("archive_sha256") or ""):
        raise CandidateUpdateError("candidate_update_archive_sha_mismatch")
    manifest = json.loads((bundle_dir / "OUTPUT_MANIFEST.json").read_text(encoding="utf-8"))
    listed = {str(item.get("path") or "") for item in manifest.get("files", []) if isinstance(item, dict)}
    if relative.name not in listed:
        raise CandidateUpdateError("candidate_update_archive_not_in_manifest")
    state_dir = run_dir / "STATE"
    state_dir.mkdir(parents=True, exist_ok=True)
    extracted = Path(tempfile.mkdtemp(prefix="candidate_update_", dir=state_dir))
    try:
        metrics = _extract_verified_archive(archive, extracted)
        if metrics["file_count"] != int(update.get("file_count") or -1):
            raise CandidateUpdateError("candidate_update_file_count_mismatch")
        if metrics["total_bytes"] != int(update.get("total_bytes") or -1):
            raise CandidateUpdateError("candidate_update_total_bytes_mismatch")
        actual_sha = hash_candidate_tree(extracted)
        if actual_sha != str(update.get("candidate_sha256") or ""):
            raise CandidateUpdateError("candidate_update_tree_sha_mismatch")
        if actual_sha == current_sha:
            raise CandidateUpdateError("candidate_update_no_content_change")
        secret_violations = scan_candidate_for_secrets(extracted)
        if secret_violations:
            raise CandidateUpdateError("candidate_update_secret_detected")
        return extracted, dict(update)
    except Exception:
        shutil.rmtree(extracted, ignore_errors=True)
        raise


def promote_candidate_update(
    run_dir: Path,
    extracted: Path,
    update: Mapping[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Atomically replace ``00_CANDIDATE`` and reset the 14-slot big loop."""
    run_dir = Path(run_dir).resolve()
    extracted = Path(extracted).resolve()
    current = run_dir / "00_CANDIDATE"
    old_source = candidate_source(run_dir)
    actual_old_sha = hash_candidate_tree(old_source)
    expected_old_sha = str(state.get("current_candidate_sha256") or "")
    if actual_old_sha != expected_old_sha:
        raise CandidateUpdateError("current_candidate_tree_drift")
    actual_new_sha = hash_candidate_tree(extracted)
    if actual_new_sha != str(update.get("candidate_sha256") or ""):
        raise CandidateUpdateError("candidate_update_tree_changed_before_promotion")

    history_root = run_dir / "CANDIDATES" / "history"
    history_root.mkdir(parents=True, exist_ok=True)
    iteration = int(state.get("iteration_number") or 0) + 1
    history = history_root / f"candidate_{iteration - 1:03d}_{actual_old_sha[:12]}"
    if not history.exists():
        copy_candidate_tree(old_source, history)
    staging = run_dir / f".candidate_staging_{uuid.uuid4().hex}"
    copy_candidate_tree(extracted, staging)
    rollback = run_dir / f".candidate_rollback_{uuid.uuid4().hex}"
    try:
        if current.exists():
            current.rename(rollback)
        staging.rename(current)
    except Exception:
        if not current.exists() and rollback.exists():
            rollback.rename(current)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(rollback, ignore_errors=True)
    shutil.rmtree(extracted, ignore_errors=True)

    state["current_candidate_sha256"] = actual_new_sha
    state["candidate_sha256"] = actual_new_sha
    state["iteration_number"] = iteration
    state["current_candidate_version"] = f"1.{iteration:03d}"
    state["candidate_version"] = state["current_candidate_version"]
    state["completed_slots"] = []
    state["current_slot"] = "1"
    for key in (
        "slot_attempts", "slot_route_phase", "slot_inflight_job_ids",
        "slot14_claude_failure", "internal_loop", "internal_loops",
    ):
        state.pop(key, None)
    loop_root = run_dir / "INTERNAL_LOOP"
    if loop_root.is_symlink():
        raise CandidateUpdateError("internal_loop_root_symlink")
    if loop_root.exists():
        shutil.rmtree(loop_root)
    record = {
        "schema_version": "camino_candidate_promotion.v1",
        "iteration": iteration,
        "previous_candidate_sha256": actual_old_sha,
        "candidate_sha256": actual_new_sha,
        "candidate_version": state["current_candidate_version"],
        "worker_id": update.get("worker_id"),
        "slot_id": update.get("slot_id"),
        "archive_sha256": update.get("archive_sha256"),
    }
    promotions = run_dir / "CANDIDATES" / "promotions"
    promotions.mkdir(parents=True, exist_ok=True)
    path = promotions / f"promotion_{iteration:03d}_{actual_new_sha[:12]}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["record_path"] = str(path.relative_to(run_dir))
    return record
