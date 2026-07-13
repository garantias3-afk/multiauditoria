#!/usr/bin/env python3
"""start_overnight.py — Entry point for overnight audit runs.

Responsibilities:
- Parse target/run-label
- Create RUN_ID
- Snapshot the target
- Calculate target_manifest
- Create state.sqlite (via state_db)
- Render prompts from contract
- Insert initial jobs
- Launch or register master
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    utc_now, utc_now_compact, sha256_file, safe_slug,
    ensure_bus_dirs, save_state, write_json, read_json,
    BUS_DIRS,
)
from scripts.canon_loader import (
    load_canon, resolve_profile, canon_summary, copy_canon_snapshot, CanonError
)
from scripts.slot_runtime import build_slot_plan
from scripts.host_runtime import build_runtime_report, load_policy as load_host_policy
from scripts.candidate_updates import copy_candidate_tree, hash_candidate_tree


SNAPSHOT_EXCLUDED_DIRS = {".git", ".ssh", "__pycache__", ".pytest_cache", ".mypy_cache"}
SNAPSHOT_FORBIDDEN_NAMES = {
    ".env", ".netrc", "id_rsa", "id_ed25519", "credentials", "credentials.json",
    ".DS_Store",
}
SNAPSHOT_FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".mobileprovision"}


def create_run_id() -> str:
    return f"RUN_{utc_now_compact()}_{uuid.uuid4().hex[:5]}"


def snapshot_target(target_path: Path, run_dir: Path) -> dict:
    """Create a snapshot of the target directory."""
    snapshot_dir = run_dir / "INPUT" / "target_snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    skipped_files = []
    if target_path.is_file():
        if (
            target_path.name.lower() in SNAPSHOT_FORBIDDEN_NAMES
            or target_path.suffix.lower() in SNAPSHOT_FORBIDDEN_SUFFIXES
        ):
            raise ValueError("target_file_forbidden_from_snapshot")
        import shutil
        dst = snapshot_dir / target_path.name
        shutil.copy2(target_path, dst)
        manifest_files.append({
            "path": target_path.name,
            "sha256": sha256_file(dst),
            "size_bytes": dst.stat().st_size,
        })
    elif target_path.is_dir():
        import shutil
        for item in sorted(target_path.rglob("*")):
            rel = item.relative_to(target_path)
            if any(part in SNAPSHOT_EXCLUDED_DIRS for part in rel.parts):
                if item.is_file() or item.is_symlink():
                    skipped_files.append({"path": str(rel), "reason": "excluded_directory"})
                continue
            if item.is_symlink():
                skipped_files.append({"path": str(rel), "reason": "symlink_rejected"})
                continue
            if not item.is_file():
                continue
            if (
                item.name.lower() in SNAPSHOT_FORBIDDEN_NAMES
                or item.suffix.lower() in SNAPSHOT_FORBIDDEN_SUFFIXES
            ):
                skipped_files.append({"path": str(rel), "reason": "secret_filename"})
                continue
            dst = snapshot_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
            manifest_files.append({
                "path": str(rel),
                "sha256": sha256_file(dst),
                "size_bytes": dst.stat().st_size,
            })

    manifest = {
        "target_path": str(target_path),
        "snapshot_at": utc_now(),
        "files": manifest_files,
        "total_files": len(manifest_files),
        "skipped_files": skipped_files,
        "skipped_count": len(skipped_files),
    }
    write_json(run_dir / "INPUT" / "target_manifest.json", manifest)
    return manifest


def create_initial_state(run_dir: Path, run_id: str, target_sha256: str, brain: str, runtime_profile: dict | None = None, canon: dict | None = None, execution_context: dict | None = None) -> dict:
    """Create initial run state."""
    state = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "target_sha256": target_sha256,
        "brain_current": brain,
        "runtime_profile": runtime_profile or {},
        "runtime_profile_name": (runtime_profile or {}).get("profile_name", "legacy"),
        "canon_summary": canon or {},
        "execution_context": execution_context or {},
        "current_phase": "created",
        "candidate_sha256": target_sha256,
        "current_candidate_sha256": target_sha256,
        "candidate_version": "1.0",
        "current_candidate_version": "1.0",
        "iteration_number": 0,
        "current_slot": "1",
        "completed_slots": [],
        "provider_circuit_breakers": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "history": [],
        "worker_bus_results": [],
        "notifications_sent": {},
    }
    save_state(run_dir, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Start an overnight audit run")
    parser.add_argument("--target", required=True, help="Path to target file or directory")
    parser.add_argument("--run-label", default="", help="Optional run label")
    parser.add_argument("--brain", default="gpt_manual_or_configured", help="Brain to use")
    parser.add_argument(
        "--profile",
        choices=["with_claude", "without_claude", "sandbox_reference"],
        default=None,
        help="Runtime profile from CANON_RUNTIME_POLICY.v1.json",
    )
    parser.add_argument("--canon-dir", default=None, help="Optional directory containing CANON_* files")
    parser.add_argument("--runs-dir", default=str(ROOT / "CAMINO_RUNS"), help="Runs directory")
    parser.add_argument(
        "--execution-host", choices=["auto", "local", "macbook", "imac"],
        default="auto", help="Host requested for the mechanical coordinator",
    )
    parser.add_argument("--lmstudio-base-url", default="", help="Explicit LM Studio endpoint override")
    parser.add_argument("--shared-root", default="", help="Immutable Drive/Gateway exchange root override")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.exists():
        print(f"ERROR: target not found: {target}", file=sys.stderr)
        return 1

    try:
        canon_bundle = load_canon(ROOT, Path(args.canon_dir) if args.canon_dir else None)
        runtime_profile = resolve_profile(canon_bundle, args.profile)
        canon_info = canon_summary(canon_bundle, runtime_profile)
    except CanonError as e:
        print(f"ERROR: canon validation failed: {e}", file=sys.stderr)
        return 2

    host_env = dict(os.environ)
    if args.shared_root:
        host_env["CAMINO_DRIVE_BUS_ROOT"] = str(Path(args.shared_root).expanduser())
    try:
        execution_context = build_runtime_report(
            load_host_policy(),
            explicit_lmstudio_base_url=args.lmstudio_base_url,
            environ=host_env,
            execute_lmstudio_probe=(
                runtime_profile.get("profile_name") != "sandbox_reference"
                and not args.dry_run
            ),
        )
    except Exception as exc:
        print(f"ERROR: host runtime discovery failed: {exc}", file=sys.stderr)
        return 2
    local_role = str(execution_context.get("host", {}).get("role") or "generic")
    requested_host = args.execution_host
    if requested_host not in {"auto", "local", local_role}:
        print(
            f"ERROR: execution_host_mismatch: requested={requested_host}, local={local_role}. "
            "Launch on the requested host or use the configured peer runner.",
            file=sys.stderr,
        )
        return 2
    memory_pressure = str(
        execution_context.get("host", {}).get("memory", {}).get("pressure") or "unknown"
    )
    execution_context["selection"] = {
        "requested_host": requested_host,
        "selected_host": local_role,
        "local_memory_pressure": memory_pressure,
        "prefer_peer_for_non_lm": local_role == "macbook" and memory_pressure in {"warning", "critical"},
    }

    runs_dir = Path(args.runs_dir)
    run_id = create_run_id()
    if args.run_label:
        run_id = f"{run_id}_{safe_slug(args.run_label)}"

    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create directory structure
    ensure_bus_dirs(run_dir)
    for subdir in [
        "INPUT", "WORKSPACES/codex", "WORKSPACES/claude_code",
        "WORKSPACES/gateway", "WORKSPACES/merger",
        "MAILBOXES/codex/IN", "MAILBOXES/codex/OUT",
        "MAILBOXES/claude_code/IN", "MAILBOXES/claude_code/OUT",
        "MAILBOXES/gateway/IN", "MAILBOXES/gateway/OUT",
        "MAILBOXES/manual_gpt/IN", "MAILBOXES/manual_gpt/OUT",
        "MAILBOXES/manual_claude/IN", "MAILBOXES/manual_claude/OUT",
        "QUARANTINE/manual_submissions",
        "ACCEPTED", "REJECTED", "PATCHES", "REPORTS",
        "TEST_RESULTS", "QUALITY_LOG_PENDING", "90_QUALITY_LOG_DELTA",
        "FINAL", "DEBUG_BUNDLE", "STATE",
    ]:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Snapshot target
    try:
        manifest = snapshot_target(target, run_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR: target snapshot failed: {exc}", file=sys.stderr)
        return 2
    # The immutable seed and mutable current candidate are distinct.  Identity
    # is the deterministic file-tree hash, never a hash of timestamps or the
    # machine-specific source path in target_manifest.json.
    current_candidate = run_dir / "00_CANDIDATE"
    copy_candidate_tree(run_dir / "INPUT" / "target_snapshot", current_candidate)
    target_sha = hash_candidate_tree(current_candidate)
    manifest["candidate_sha256"] = target_sha
    write_json(run_dir / "INPUT" / "target_manifest.json", manifest)

    # Create state
    if args.dry_run:
        print(f"DRY_RUN: would create run {run_id} at {run_dir}")
        return 0

    copy_canon_snapshot(run_dir / "INPUT" / "canon_snapshot", canon_bundle)
    # Every entrypoint, including the direct start_overnight launcher, records
    # the exact immutable slot plan consumed by the master.  Previously only
    # run_multiaudit_cycle wrote this file, so direct launches silently fell
    # back to generic worker dispatch instead of the canonical 14-slot flow.
    slot_plan = build_slot_plan(canon_bundle, runtime_profile).to_serializable()
    write_json(run_dir / "CANON_SLOT_PLAN.json", slot_plan)
    state = create_initial_state(
        run_dir, run_id, target_sha, args.brain, runtime_profile, canon_info,
        execution_context,
    )

    # Write run config
    write_json(run_dir / "RUN_CONFIG.json", {
        "run_id": run_id,
        "target": str(target),
        "brain": args.brain,
        "runtime_profile": runtime_profile,
        "canon_summary": canon_info,
        "canon_slot_plan": "CANON_SLOT_PLAN.json",
        "execution_context": execution_context,
        "created_at": utc_now(),
        "dry_run": args.dry_run,
    })

    print(f"Run created: {run_id}")
    print(f"Directory: {run_dir}")
    print(f"Target snapshot: {len(manifest['files'])} files")
    print(f"Runtime profile: {runtime_profile.get('profile_name')} (claude_enabled={runtime_profile.get('claude_enabled')})")
    print(f"Canon: {canon_info.get('canon_version')} / {canon_info.get('route_count')} routes / {canon_info.get('slot_count')} slots")
    print(f"Execution host: {local_role} / {execution_context.get('host', {}).get('architecture_family')} / RAM pressure={memory_pressure}")
    print(f"LM Studio selection: {execution_context.get('lmstudio', {}).get('source')} -> {execution_context.get('lmstudio', {}).get('base_url')}")
    print(f"Next: run overnight_master.py --run {run_dir} --execute-workers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
