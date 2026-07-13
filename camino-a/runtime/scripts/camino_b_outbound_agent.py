#!/usr/bin/env python3
"""Consume Camino B Slot 14 jobs with subscription-only local workers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.camino_b_slot14_bridge import (  # noqa: E402
    AWAITING, FALLBACK_ROUTE, PRIMARY_ROUTE, BridgeError, LocalSlot14Queue,
)

FALLBACK_TRIGGERS = {
    "auth_missing": "claude_auth_missing",
    "forbidden_auth_method": "claude_auth_missing",
    "forbidden_api_key": "claude_auth_missing",
    "worker_missing": "claude_worker_missing",
    "skipped_cli_missing": "claude_worker_missing",
    "auth_check_failed": "claude_auth_check_failed",
    "auth_check_invalid_json": "claude_auth_check_failed",
    "auth_check_timeout": "claude_auth_check_timeout",
    "claude_cli_nonzero": "claude_cli_nonzero",
    "cli_execution_failed": "claude_cli_execution_failed",
    "timeout": "claude_timeout",
    "claude_unavailable": "claude_unavailable",
    "disabled_by_profile": "claude_unavailable",
}


def _run_dir(runs_root: Path, status: Mapping[str, Any]) -> Path:
    run_id = str(status.get("run_id") or "")
    candidate = (runs_root / run_id).resolve()
    if runs_root.resolve() not in candidate.parents or not candidate.is_dir() or candidate.is_symlink():
        raise BridgeError("agent_run_directory_missing", run_id=run_id)
    return candidate


def _latest_bundle(run_dir: Path, worker_id: str, before: set[Path]) -> Path:
    output_root = run_dir / "13_WORKER_BUS" / worker_id / "OUT"
    after = {item.resolve() for item in output_root.iterdir() if item.is_dir() and not item.is_symlink()}
    created = sorted(after - before, key=lambda item: item.stat().st_mtime_ns)
    if len(created) != 1:
        raise BridgeError("agent_worker_bundle_count_invalid", count=len(created))
    return created[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_job(run_dir: Path, worker_id: str, context: Mapping[str, Any]) -> Path:
    request = dict(context["request"])
    for field in ("request_path", "diff_path"):
        source = (run_dir / str(request[field])).resolve()
        if run_dir not in source.parents or not source.is_file() or source.is_symlink():
            raise BridgeError("agent_handoff_file_invalid", field=field)
        expected = str(request["request_sha256" if field == "request_path" else "diff_sha256"])
        if _sha256(source) != expected:
            raise BridgeError("agent_handoff_sha256_mismatch", field=field)
    job = {
        "job_id": "JOB_camino_b_%s" % uuid.uuid4().hex,
        "run_id": request["run_id"],
        "worker_id": worker_id,
        "slot_id": "14",
        "candidate_sha256": request["candidate_sha256"],
        "prior_slots_complete": True,
        "request_path": request["request_path"],
        "request_sha256": request["request_sha256"],
        "audit_request_sha256": request["request_sha256"],
        "slot14_audit_request_ref": request["request_path"],
        "slot14_audit_request_sha256": request["request_sha256"],
        "diff_path": request["diff_path"],
        "diff_sha256": request["diff_sha256"],
    }
    if worker_id == "claude_code":
        job.update({"task": "slot14_final_review", "route_id": PRIMARY_ROUTE})
    else:
        failure = dict(context.get("primary_failure") or {})
        error_class = str(failure.get("error_class") or "")
        trigger = FALLBACK_TRIGGERS.get(error_class)
        done = list(failure.get("worker_done") or [])
        if not trigger or not done:
            raise BridgeError("agent_primary_failure_context_invalid")
        job.update({
            "task": "slot14_subscription_fallback",
            "route_id": FALLBACK_ROUTE,
            "fallback_trigger": trigger,
            "claude_attempt": {
                "worker_id": "claude_code",
                "job_id": str(failure.get("claim_id") or "BRIDGE_PRIMARY_ATTEMPT"),
                "run_id": request["run_id"],
                "slot_id": "14",
                "candidate_sha256": request["candidate_sha256"],
                "status": str(failure.get("status") or "blocked"),
                "approval_eligible": False,
                "error_class": error_class,
                "output_manifest_sha256": failure.get("worker_manifest_sha256"),
                "done_marker": str(done[0].get("name") or ""),
                "bundle": "bridge://%s/primary-attempt" % failure.get("handoff_id"),
                "source": "camino_b_bridge",
            },
        })
    inbox = run_dir / "13_WORKER_BUS" / worker_id / "IN"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / "job.json"
    temp = inbox / (".job.%s.tmp" % uuid.uuid4().hex)
    temp.write_text(json.dumps(job, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temp), str(path))
    return path


def _invoke_worker(run_dir: Path, worker_id: str, *, timeout_seconds: int) -> Path:
    output_root = run_dir / "13_WORKER_BUS" / worker_id / "OUT"
    output_root.mkdir(parents=True, exist_ok=True)
    before = {item.resolve() for item in output_root.iterdir() if item.is_dir()}
    script = ROOT / "scripts" / (
        "worker_claude_code.py" if worker_id == "claude_code" else "worker_codex_fallback.py"
    )
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        subprocess.run(
            [sys.executable, str(script), "--run", str(run_dir)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=max(60, timeout_seconds), env=env, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("agent_worker_timeout", worker_id=worker_id) from exc
    return _latest_bundle(run_dir, worker_id, before)


def process_job(
    queue: LocalSlot14Queue, status: Mapping[str, Any], runs_root: Path,
    *, host_id: str, timeout_seconds: int = 3900,
) -> dict[str, Any]:
    if status.get("status") != AWAITING:
        return dict(status)
    run_dir = _run_dir(runs_root, status)
    route_id = FALLBACK_ROUTE if status.get("fallback_armed") else PRIMARY_ROUTE
    worker_id = "codex_fallback" if route_id == FALLBACK_ROUTE else "claude_code"
    context = queue.get_agent_context(
        str(status["handoff_id"]), str(status["candidate_sha256"]),
    )
    _write_job(run_dir, worker_id, context)
    claim = queue.claim(
        str(status["handoff_id"]), str(status["candidate_sha256"]),
        worker_id=worker_id, route_id=route_id,
        claim_id="CLAIM_%s" % uuid.uuid4().hex,
        host_id=host_id, lease_seconds=min(86400, max(60, timeout_seconds + 300)),
    )
    bundle = _invoke_worker(run_dir, worker_id, timeout_seconds=timeout_seconds)
    return queue.complete(
        str(status["handoff_id"]), str(status["candidate_sha256"]),
        claim_token=str(claim["claim_token"]), bundle_dir=bundle,
    )


def run_once(queue: LocalSlot14Queue, runs_root: Path, *, host_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    queue.requeue_expired_claims()
    for status in queue.list_jobs(statuses={AWAITING}):
        current = process_job(queue, status, runs_root, host_id=host_id)
        results.append(current)
        if current.get("status") == AWAITING and current.get("fallback_armed"):
            results.append(process_job(queue, current, runs_root, host_id=host_id))
    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Camino B subscription worker agent")
    parser.add_argument("--queue-root", default=os.environ.get("CAMINO_B_QUEUE_ROOT", ""))
    parser.add_argument("--runs-root", default=os.environ.get("CAMINO_B_RUNS_ROOT", ""))
    parser.add_argument("--host-id", default=socket.gethostname().split(".", 1)[0])
    args = parser.parse_args(argv)
    if not args.queue_root or not args.runs_root:
        parser.error("--queue-root and --runs-root (or matching environment variables) are required")
    try:
        results = run_once(
            LocalSlot14Queue(args.queue_root), Path(args.runs_root).expanduser().resolve(),
            host_id=args.host_id,
        )
        print(json.dumps({"status": "ok", "processed": len(results), "results": results}, ensure_ascii=False))
        return 0
    except BridgeError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
