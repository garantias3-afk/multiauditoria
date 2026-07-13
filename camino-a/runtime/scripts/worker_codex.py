#!/usr/bin/env python3
"""worker_codex.py — Codex CLI worker wrapper. PLUG-AND-PLAY.

Reads job from IN, prepares workspace, executes Codex CLI,
writes manifest+DONE bundle to OUT.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_multiaudit_cycle import (
    sha256_file, utc_now, read_json, write_json,
    write_output_manifest_and_done, save_state, load_state,
    history_event, assert_file_has_no_unredacted_secret,
)
from scripts.candidate_updates import candidate_source, verify_candidate_binding


AUDITABLE_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".txt", ".sh",
    ".toml", ".ini", ".cfg", ".patch", ".diff",
}


def _auditable_workspace_file(path: Path, workspace: Path) -> bool:
    rel = path.relative_to(workspace)
    return (
        path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in AUDITABLE_SUFFIXES
        and "__pycache__" not in rel.parts
        and not any(part.startswith(".") for part in rel.parts)
    )


def _flat_bundle_name(index: int, relative_path: str) -> str:
    flattened = relative_path.replace("/", "__").replace("\\", "__")
    flattened = re.sub(r"[^A-Za-z0-9._-]+", "_", flattened).strip("._")
    if not flattened:
        flattened = "artifact"
    return f"artifact_{index:04d}_{flattened[:180]}"


def prepare_workspace(run_dir: Path) -> Path:
    """Prepare one fresh isolated workspace without following symlinks."""
    run_dir = Path(run_dir)
    if run_dir.is_symlink():
        raise RuntimeError("codex_run_dir_symlink_rejected")

    workspace_root = run_dir / "WORKSPACES"
    if workspace_root.is_symlink():
        raise RuntimeError("codex_workspaces_root_symlink_rejected")
    if workspace_root.exists() and not workspace_root.is_dir():
        raise RuntimeError("codex_workspaces_root_not_directory")
    workspace_root.mkdir(parents=True, exist_ok=True)

    ws = workspace_root / "codex"
    if ws.is_symlink():
        raise RuntimeError("codex_workspace_symlink_rejected")
    if ws.exists():
        if not ws.is_dir():
            raise RuntimeError("codex_workspace_not_directory")
        # rmtree removes links contained in the workspace; it does not follow
        # them. Recreating the directory prevents stale files from a previous
        # Codex attempt from entering the next result bundle.
        shutil.rmtree(ws)
    ws.mkdir(parents=False, exist_ok=False)

    # Copy target snapshot
    input_root = run_dir / "INPUT"
    if input_root.is_symlink():
        raise RuntimeError("codex_input_root_symlink_rejected")
    snapshot = candidate_source(run_dir)
    if snapshot.is_symlink():
        raise RuntimeError("codex_snapshot_symlink_rejected")
    if snapshot.exists():
        if not snapshot.is_dir():
            raise RuntimeError("codex_snapshot_not_directory")
        # Validate the complete source tree before copying any byte. Silently
        # skipping a link would make the audited snapshot differ from the
        # declared candidate without an explicit failure.
        for item in snapshot.rglob("*"):
            if item.is_symlink():
                raise RuntimeError("codex_snapshot_symlink_rejected")
        for item in snapshot.rglob("*"):
            if item.is_file():
                rel = item.relative_to(snapshot)
                dst = ws / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)

    # Inject AGENTS.md
    agents = ROOT / "generated" / "AGENTS.md"
    if agents.is_symlink():
        raise RuntimeError("codex_agents_symlink_rejected")
    if agents.is_file():
        overlay = ws / ".camino_runtime"
        overlay.mkdir(exist_ok=True)
        shutil.copy2(agents, overlay / "AGENTS.md")

    return ws


def run_codex(workspace: Path, max_cycles: int = 3, timeout_minutes: int = 120) -> dict:
    """Execute Codex CLI in the workspace."""
    result = {
        "worker_id": "codex",
        "status": "ok",
        "route_id": "codex_cli_local",
        "model_id": "codex_cli",
        "provider_id": "codex_cli",
        "provider_name": "Codex CLI",
        "route": "local_cli",
        "interface": "cli",
        "cost_class": "plan_or_local",
        "role": "infrastructure_worker",
        "cycles": 0,
        "artifacts": [],
    }

    if os.environ.get("CAMINO_DISABLE_CODEX_WORKER") == "1":
        result["status"] = "codex_not_found"
        result["error"] = "Codex worker disabled explicitly for deterministic sandbox execution"
        return result

    prompt_path = ROOT / "generated" / "PROMPT_CODEX.md"
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else (
        "Act as the bounded Camino A coding worker. Inspect, patch, and test the "
        "isolated workspace. Do not approve the global process."
    )
    command = [
        os.environ.get("CODEX_CLI", "codex"),
        "--ask-for-approval", "never",
        "--sandbox", "workspace-write",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-",
    ]
    worker_env = {
        key: value for key, value in os.environ.items()
        if key not in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
    }

    for cycle in range(max_cycles):
        try:
            cp = subprocess.run(
                command,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                input=prompt,
                env=worker_env,
                timeout=timeout_minutes * 60,
            )
            result["cycles"] = cycle + 1
            if cp.returncode != 0:
                result["status"] = "failed"
                result["error"] = cp.stderr[:500]
                break
        except FileNotFoundError:
            result["status"] = "codex_not_found"
            result["error"] = "codex CLI not found in PATH"
            break
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            result["error"] = f"timeout after {timeout_minutes}m"
            break

    # Collect artifacts (RESIL-04: cap at 500, skip oversized)
    _MAX_ARTIFACTS = 500
    _MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
    for item in sorted(workspace.rglob("*")):
        if _auditable_workspace_file(item, workspace):
            if len(result["artifacts"]) >= _MAX_ARTIFACTS:
                result["artifacts_truncated"] = True
                break
            size = item.stat().st_size
            if size > _MAX_ARTIFACT_BYTES:
                continue
            result["artifacts"].append({
                "path": str(item.relative_to(workspace)),
                "sha256": sha256_file(item),
                "size_bytes": size,
            })

    return result


def run_codex_worker(run_dir: Path, dry_run: bool = False) -> dict:
    """Full codex worker lifecycle: read job → prepare → execute → write bundle."""
    # Read job from IN
    inbox = run_dir / "13_WORKER_BUS" / "codex" / "IN"
    job_file = inbox / "job.json"

    if not job_file.is_file() or job_file.is_symlink():
        return {"status": "no_job", "error": "No job.json in codex/IN"}

    job = read_json(job_file, {})

    if dry_run:
        return {"status": "dry_run", "worker": "codex", "job": job}
    bound, binding = verify_candidate_binding(
        run_dir, str(job.get("candidate_sha256") or ""),
    )
    if not bound:
        return {"worker_id": "codex", "status": "failed", "error": binding}

    # Prepare workspace
    ws = prepare_workspace(run_dir)

    # Execute
    max_cycles = job.get("max_cycles", 3)
    timeout = job.get("timeout_minutes", 120)
    result = run_codex(ws, max_cycles, timeout)
    result.update({
        "job_id": str(job.get("job_id") or ""),
        "run_id": str(job.get("run_id") or run_dir.name),
        "slot_id": str(job.get("slot_id") or ""),
        "candidate_sha256": str(job.get("candidate_sha256") or ""),
    })

    # Write output bundle
    out_dir = run_dir / "13_WORKER_BUS" / "codex" / "OUT" / f"codex_result_{utc_now().replace(':', '-')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # The output-manifest contract is intentionally flat. Preserve original
    # workspace paths in an explicit index while keeping every listed artifact
    # as a basename-only file that the shared validator can scan fail-closed.
    artifact_files = []
    artifact_index = []
    for index, record in enumerate(result.get("artifacts", []), start=1):
        original = str(record["path"])
        source = ws / original
        if not _auditable_workspace_file(source, ws):
            raise RuntimeError("codex_artifact_missing_or_symlink")
        bundle_name = _flat_bundle_name(index, original)
        shutil.copy2(source, out_dir / bundle_name)
        artifact_files.append(bundle_name)
        artifact_index.append({
            "original_path": original,
            "bundle_name": bundle_name,
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
        })

    write_json(out_dir / "ARTIFACT_INDEX.json", {"artifacts": artifact_index})
    artifact_files.append("ARTIFACT_INDEX.json")
    result["artifact_index"] = artifact_index

    # Write result.json
    write_json(out_dir / "result.json", result)

    # Write manifest + DONE
    all_files = ("result.json",) + tuple(artifact_files) if artifact_files else ("result.json",)
    # Only include files that exist in the bundle
    existing_files = tuple(f for f in all_files if (out_dir / f).exists())

    if existing_files:
        write_output_manifest_and_done(
            run_dir, str(out_dir.relative_to(run_dir)),
            done_name="CODEX_OUTPUT.DONE",
            stage="codex_audit",
            candidate_sha256=job.get("candidate_sha256", ""),
            files=existing_files,
        )

    result["output_bundle"] = str(out_dir.relative_to(run_dir))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex worker")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--max-cycles", type=int, default=3)
    parser.add_argument("--timeout-minutes", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    state = load_state(run_dir)

    result = run_codex_worker(run_dir, dry_run=args.dry_run)

    history_event(state, "codex_worker_done", status=result.get("status"))
    save_state(run_dir, state)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in ("ok", "dry_run", "codex_not_found") else 1


if __name__ == "__main__":
    sys.exit(main())
