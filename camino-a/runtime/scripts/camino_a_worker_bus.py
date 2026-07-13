"""camino_a_worker_bus.py — Real implementation of worker bus.

Manages isolated worker workspaces, mailboxes, output validation,
secret scanning, and result reconciliation.

Functions imported by run_multiaudit_cycle.py:
  - prepare_worker_bus(run_dir)
  - scan_worker_outputs(run_dir)
  - recover_worker_bus_archives(run_dir)
  - reconcile_recorded_outputs(run_dir, state)
  - list_pending_outputs(run_dir, state)
  - assert_safe_generated_name(name, run_dir)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUS_VERSION = "camino_a_worker_bus.v2"

WORKER_IDS = (
    "codex", "claude_code", "codex_fallback", "gateway", "local_static",
    "manual_gpt", "manual_claude", "lmstudio_bridge",
)

MAX_GENERATED_NAME_LEN = 200
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.py$")

# Extended secret patterns — same set as monolith R10 SECRET-03
SECRET_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"ghp_[0-9A-Za-z]{20,}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?[^\s'\"]{12,}"),
    re.compile(r"glpat-[A-Za-z0-9\-]{20,}"),
    re.compile(r"sk_live_[A-Za-z0-9]{20,}"),
    re.compile(r"sk_test_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"hvs\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}"),
    re.compile(r"-----BEGIN[ A-Z]*(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)(?:postgres|mysql|mongodb)(?:\+\w+)?:\/\/[^\s]{8,}"),
    re.compile(r"xapp-[A-Za-z0-9\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}"),
)

SECRET_FIXTURE_HINT = re.compile(
    r"(?i)\b(dummy|fake|example|fixture|simulad[ao]|simulada|test[_-]?only|valor[ _-]?falso)\b"
)

MAX_OUTPUT_FILE_BYTES = 64 * 1024 * 1024  # 64 MiB; larger data uses chunked gateway protocol
SECRET_SCAN_CHUNK_CHARS = 1024 * 1024
SECRET_SCAN_OVERLAP_CHARS = 4096

SCANNABLE_EXTENSIONS = frozenset({
    ".json", ".md", ".txt", ".py", ".yaml", ".yml",
    ".env", ".pem", ".key", ".crt", ".conf", ".cfg", ".ini", ".toml",
    ".sh", ".bash", ".zsh", ".fish",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_error_text(exc: BaseException) -> str:
    """Redact potential secrets from error messages."""
    text = f"{type(exc).__name__}: {exc}"
    for pat in SECRET_PATTERNS:
        text = pat.sub("<REDACTED>", text)
    return text[:500]


def _normalize_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# ---------------------------------------------------------------------------
# Secret scanning
# ---------------------------------------------------------------------------

def _secret_token_for_entropy(match_text: str) -> str:
    token = re.split(r"[:=]\s*['\"]?", str(match_text), maxsplit=1)[-1].strip()
    token = re.sub(r"(?i)^(sk-proj-|sk-|ghp_|xox[baprs]-|AKIA|AIza|glpat-|github_pat_|sk_live_|sk_test_|hvs\.|SG\.)", "", token)
    return re.sub(r"[^A-Za-z0-9]", "", token)


def _looks_like_low_entropy_fixture(match_text: str) -> bool:
    token = _secret_token_for_entropy(match_text)
    if len(token) < 16:
        return False
    return len(set(token)) <= 4


def _secret_match_allowed(sample: str, start: int, end: int, match_text: str) -> bool:
    lo = max(0, start - 80)
    hi = min(len(sample), end + 80)
    context = sample[lo:hi]
    return bool(SECRET_FIXTURE_HINT.search(context) and _looks_like_low_entropy_fixture(match_text))


def assert_no_secret(text: str, *, context: str, allow_fixture: bool = False) -> None:
    """Raise SystemExit if unredacted secret found in text."""
    sample = str(text)
    for pat in SECRET_PATTERNS:
        for m in pat.finditer(sample):
            if allow_fixture and _secret_match_allowed(sample, m.start(), m.end(), m.group(0)):
                continue
            raise SystemExit(f"secret_detected:{context}")


def scan_file_for_secrets(path: Path, *, context: str, allow_fixture: bool = False) -> None:
    """Scan a file for unredacted secrets."""
    if path.stat().st_size > MAX_OUTPUT_FILE_BYTES:
        raise SystemExit(f"output_file_too_large:{path.name}:{path.stat().st_size}")
    if path.suffix.lower() in SCANNABLE_EXTENSIONS:
        # Stream large text artifacts so validation does not make an unbounded
        # second in-memory copy.  The overlap is larger than every configured
        # secret token form, preserving cross-chunk detection.
        tail = ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            while True:
                text = handle.read(SECRET_SCAN_CHUNK_CHARS)
                if not text:
                    break
                sample = tail + text
                assert_no_secret(sample, context=context, allow_fixture=allow_fixture)
                tail = sample[-SECRET_SCAN_OVERLAP_CHARS:]
        if tail:
            assert_no_secret(tail, context=context, allow_fixture=allow_fixture)


def scan_directory_for_secrets(directory: Path, *, context: str) -> list[str]:
    """Scan all files in directory for secrets. Returns list of violations."""
    violations = []
    for item in sorted(directory.rglob("*")):
        if item.is_file() and not item.is_symlink():
            if item.suffix.lower() in SCANNABLE_EXTENSIONS:
                try:
                    scan_file_for_secrets(item, context=f"{context}/{item.name}", allow_fixture=True)
                except SystemExit as e:
                    violations.append(str(e))
    return violations


# ---------------------------------------------------------------------------
# Name safety
# ---------------------------------------------------------------------------

def assert_safe_generated_name(name: str, run_dir: Path | None = None) -> None:
    """Validate that a generated file name is safe.

    Rules:
    - Must end in .py
    - Must match SAFE_NAME_RE (alphanumeric + . _ -, starts with alphanumeric)
    - No path separators
    - No ..
    - Max 200 chars
    - NFC normalized
    """
    name = _normalize_nfc(str(name).strip())
    if not name:
        raise SystemExit("generated_name_empty")
    if len(name) > MAX_GENERATED_NAME_LEN:
        raise SystemExit(f"generated_name_too_long:{len(name)}")
    if "/" in name or "\\" in name:
        raise SystemExit(f"generated_name_has_separator:{name}")
    if ".." in name:
        raise SystemExit(f"generated_name_has_traversal:{name}")
    if not SAFE_NAME_RE.match(name):
        raise SystemExit(f"generated_name_unsafe:{name}")
    if not name.endswith(".py"):
        raise SystemExit(f"generated_name_not_py:{name}")
    # Check it's not a known dangerous name
    dangerous = {"__init__.py", "setup.py", "conftest.py", "manage.py"}
    if name.lower() in dangerous:
        raise SystemExit(f"generated_name_dangerous:{name}")


# ---------------------------------------------------------------------------
# Worker bus management
# ---------------------------------------------------------------------------

def prepare_worker_bus(run_dir: Path) -> None:
    """Create worker bus directory structure with IN/OUT mailboxes."""
    bus = run_dir / "13_WORKER_BUS"
    bus.mkdir(parents=True, exist_ok=True)
    for worker_id in WORKER_IDS:
        for subdir in ("IN", "OUT"):
            d = bus / worker_id / subdir
            d.mkdir(parents=True, exist_ok=True)
    # Version marker
    version_file = bus / ".bus_version"
    version_file.write_text(BUS_VERSION, encoding="utf-8")


def _read_manifest(out_dir: Path) -> dict | None:
    """Read OUTPUT_MANIFEST.json from a directory if valid."""
    for name in ("OUTPUT_MANIFEST.json", "GPT_CODE_OUTPUT.MANIFEST.json",
                 "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json"):
        p = out_dir / name
        if p.exists() and p.is_file() and not p.is_symlink():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return None


def _validate_output_bundle(out_dir: Path, worker_id: str) -> dict:
    """Validate an output bundle from a worker.

    Returns validation result dict with status and details.
    """
    result = {
        "worker_id": worker_id,
        "dir": str(out_dir),
        "status": "unknown",
        "files": [],
        "violations": [],
    }

    # Check for DONE marker
    done_files = list(out_dir.glob("*.DONE"))
    if not done_files:
        result["status"] = "incomplete"
        result["violations"].append("no_DONE_marker")
        return result

    # Check for manifest
    manifest = _read_manifest(out_dir)
    if manifest is None:
        result["status"] = "invalid"
        result["violations"].append("no_manifest")
        return result

    # Validate manifest fields
    run_id = manifest.get("run_id", "")
    stage = manifest.get("stage", "")
    files = manifest.get("files", [])

    if not isinstance(files, list):
        result["status"] = "invalid"
        result["violations"].append("files_not_list")
        return result

    # NEW-BUG-D fix (v1.2.0-iter3): an empty `files: []` manifest is
    # NOT valid evidence. A bundle with only DONE + MANIFEST and zero
    # actual content files bypasses the accepted_evidence gate. Reject
    # explicitly.
    if len(files) == 0:
        result["status"] = "invalid"
        result["violations"].append("empty_manifest_files")
        return result

    # Validate each file
    seen_paths: set[str] = set()
    for entry in files:
        rel = str(entry.get("path") or entry.get("name") or "")
        rel = _normalize_nfc(rel)
        pp = Path(rel)

        if not rel or pp.is_absolute() or ".." in pp.parts or pp.name != rel:
            result["violations"].append(f"unsafe_path:{rel}")
            continue

        # NEW (v1.2.0-iter3, audit P07): reject duplicate paths in manifest.
        # The monolith's validate_output_manifest() already does this via
        # `by_path` dict; the worker-bus variant did not. Same fix here.
        if rel in seen_paths:
            result["violations"].append(f"duplicate_path:{rel}")
            continue
        seen_paths.add(rel)

        target = out_dir / rel
        if target.is_symlink():
            result["violations"].append(f"symlink:{rel}")
            continue

        if not target.is_file():
            result["violations"].append(f"missing:{rel}")
            continue

        size = target.stat().st_size
        if size > MAX_OUTPUT_FILE_BYTES:
            result["violations"].append(f"too_large:{rel}:{size}")
            continue

        # SHA verification. F-2 fix: a manifest entry that OMITS `sha256`
        # previously skipped content integrity entirely (existence + size +
        # secret-scan only). The canonical producer
        # (write_output_manifest_and_done) ALWAYS emits a sha256 per file, so a
        # missing/empty sha256 is either a malformed or a tampered manifest and
        # must be rejected — content is the evidence, and unverified content is
        # not evidence.
        expected_sha = str(entry.get("sha256") or "").strip()
        if not expected_sha:
            result["violations"].append(f"missing_sha256:{rel}")
            continue
        actual_sha = _sha256_file(target)
        if actual_sha.lower() != expected_sha.lower():
            result["violations"].append(f"sha_mismatch:{rel}")
            continue

        # Secret scan
        try:
            scan_file_for_secrets(target, context=f"{worker_id}/{rel}", allow_fixture=True)
        except SystemExit as e:
            result["violations"].append(str(e))
            continue

        result["files"].append({"path": rel, "size": size})

    # Check for unlisted files / dangerous entries (NEW-BUG-B fix, v1.2.0-iter2)
    #
    # v1.1 only flagged `actual.is_file()` unlisted entries, which let
    # symlinks-to-directories slip through. v1.2.0-iter2 flags:
    #   - any symlink (file OR directory)
    #   - any directory (bundle must be flat — no nested dirs allowed)
    #   - any non-regular file (FIFO, socket, device)
    #   - any unlisted regular file
    known_manifest_names = {"OUTPUT_MANIFEST.json", "GPT_CODE_OUTPUT.MANIFEST.json",
                            "GPT_CODE_OUTPUT_MANIFEST.json", "MANIFEST.json"}
    for done_f in done_files:
        known_manifest_names.add(done_f.name)

    listed_names = {e.get("path") or e.get("name") for e in files}
    for actual in out_dir.iterdir():
        if actual.name in known_manifest_names:
            continue
        if actual.is_symlink():
            result["violations"].append(f"symlink_unlisted:{actual.name}")
            continue
        if actual.is_dir():
            result["violations"].append(f"unlisted_directory:{actual.name}")
            continue
        if not actual.is_file():
            # FIFO, socket, device, broken entry
            result["violations"].append(f"non_regular_entry:{actual.name}")
            continue
        if actual.name not in listed_names:
            result["violations"].append(f"unlisted_file:{actual.name}")

    result["status"] = "valid" if not result["violations"] else "invalid"
    return result


def scan_worker_outputs(run_dir: Path) -> list[dict[str, Any]]:
    """Scan all worker OUT directories for completed results.

    Returns list of validated output records.
    """
    results = []
    bus = run_dir / "13_WORKER_BUS"
    if not bus.exists():
        return results

    for worker_dir in sorted(bus.iterdir()):
        if not worker_dir.is_dir() or worker_dir.name.startswith("."):
            continue

        worker_id = worker_dir.name
        out_dir = worker_dir / "OUT"
        if not out_dir.exists():
            continue

        for item in sorted(out_dir.iterdir()):
            if not item.is_dir() or item.is_symlink():
                continue

            validation = _validate_output_bundle(item, worker_id)
            record = {
                "worker_id": worker_id,
                "bundle_dir": str(item),
                "validation": validation,
                "scanned_at": _utc_now(),
            }

            # Read result.json if present
            result_json = item / "result.json"
            if result_json.exists() and result_json.is_file():
                try:
                    record["result"] = json.loads(result_json.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

            results.append(record)

    return results


def list_pending_outputs(run_dir: Path, state: dict) -> list[dict]:
    """List outputs that haven't been processed yet."""
    all_outputs = scan_worker_outputs(run_dir)
    recorded_ids = set(state.get("worker_bus_recorded_ids", []))

    pending = []
    for output in all_outputs:
        bundle_id = f"{output['worker_id']}:{Path(output['bundle_dir']).name}"
        if bundle_id not in recorded_ids:
            pending.append(output)

    return pending


def reconcile_recorded_outputs(run_dir: Path, state: dict | None = None, *, recorded_job_ids: set | None = None) -> dict | list:
    """Reconcile worker bus outputs with state.

    Supports two call signatures:
      - reconcile_recorded_outputs(run_dir, state) — new style
      - reconcile_recorded_outputs(run_dir, recorded_job_ids=recorded) — monolith compat

    Returns dict (new style) or list of events (compat).
    """
    # Compat: monolith passes recorded_job_ids= as keyword
    if recorded_job_ids is not None and state is None:
        # Return list of events for compat
        all_outputs = scan_worker_outputs(run_dir)
        events = []
        for output in all_outputs:
            bundle_id = f"{output['worker_id']}:{Path(output['bundle_dir']).name}"
            if bundle_id not in recorded_job_ids:
                events.append({
                    "worker_id": output["worker_id"],
                    "bundle_dir": output["bundle_dir"],
                    "validation_status": output["validation"]["status"],
                    "event_type": "new_output",
                })
        return events

    # New style: state dict
    if state is None:
        state = {}
    state.setdefault("worker_bus_version", BUS_VERSION)
    state.setdefault("worker_bus_recorded_ids", [])
    state.setdefault("worker_bus_results", [])

    pending = list_pending_outputs(run_dir, state)
    recorded = state["worker_bus_recorded_ids"]
    results = state["worker_bus_results"]

    new_count = 0
    for output in pending:
        bundle_id = f"{output['worker_id']}:{Path(output['bundle_dir']).name}"
        recorded.append(bundle_id)

        summary = {
            "worker_id": output["worker_id"],
            "bundle_dir": output["bundle_dir"],
            "validation_status": output["validation"]["status"],
            "violations": output["validation"].get("violations", []),
            "file_count": len(output["validation"].get("files", [])),
            "scanned_at": output["scanned_at"],
        }

        if "result" in output:
            summary["result_status"] = output["result"].get("status", "unknown")

        results.append(summary)
        new_count += 1

    if len(results) > 200:
        state["worker_bus_results"] = results[-200:]
    if len(recorded) > 1000:
        state["worker_bus_recorded_ids"] = recorded[-1000:]

    return {"new_outputs": new_count, "total_recorded": len(recorded)}


def recover_worker_bus_archives(run_dir: Path) -> dict:
    """Recover archived worker bus outputs back to OUT directories.

    Used when re-processing after failures.
    """
    archive_dir = run_dir / "90_ARCHIVE_MANUAL_CONTEXT"
    if not archive_dir.exists():
        return {"recovered": 0}

    recovered = 0
    for item in sorted(archive_dir.iterdir()):
        if not item.is_dir():
            continue
        # Check if it's a worker output archive
        worker_id = item.name.split("_")[0] if "_" in item.name else ""
        if worker_id in WORKER_IDS:
            target = run_dir / "13_WORKER_BUS" / worker_id / "OUT" / item.name
            if not target.exists():
                shutil.copytree(str(item), str(target), symlinks=False)
                recovered += 1

    return {"recovered": recovered}


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()
