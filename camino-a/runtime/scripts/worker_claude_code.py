#!/usr/bin/env python3
"""Fail-closed Claude Code subscription worker for canonical slot 14.

The worker never uses ``ANTHROPIC_API_KEY``.  It verifies local Claude
subscription authentication, passes an explicit prompt to the CLI, requires a
structured result, and only emits ``status=ok`` for the exact clean slot-14
approval contract.  Corrections and incomplete evidence remain durable output
but cannot be mistaken for approval by the current bundle harvester.
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

from scripts.canon_loader import CanonError, load_canon
from scripts.run_multiaudit_cycle import (
    history_event,
    load_state,
    read_json,
    save_state,
    sha256_file,
    utc_now,
    write_json,
    write_output_manifest_and_done,
)
from scripts.candidate_updates import (
    CandidateUpdateError, candidate_source, create_candidate_update_archive,
    verify_candidate_binding,
)
from scripts.slot14_handoff import materialize_slot14_handoff


CLAUDE_ROUTE_ID = "claude_code_subscription_cli"
APPROVAL_VERDICT = "APPROVED_BY_CLAUDE"
ALLOWED_VERDICTS = {
    APPROVAL_VERDICT,
    "CORRECTIONS_APPLIED",
    "BLOCKED",
    "INSUFFICIENT_EVIDENCE",
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

CLAUDE_SLOT14_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "summary",
        "findings",
        "corrections_applied",
        "tests",
        "audit_request_sha256",
        "falsification_attempts",
        "independent_checks",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": sorted(ALLOWED_VERDICTS)},
        "summary": {"type": "string", "minLength": 1, "maxLength": 20000},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["id", "severity", "summary"],
                "properties": {
                    "id": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"],
                    },
                    "summary": {"type": "string"},
                    "file": {"type": "string"},
                },
            },
        },
        "corrections_applied": {"type": "boolean"},
        "tests": {"type": "array", "items": {"type": "string"}},
        "audit_request_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "falsification_attempts": {
            "type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1},
        },
        "independent_checks": {
            "type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1},
        },
    },
}


def load_claude_route(root: Path = ROOT, route_id: str = CLAUDE_ROUTE_ID) -> dict[str, Any]:
    """Load the exact CLI route from the validated canon."""
    bundle = load_canon(root)
    route = dict((bundle.routes.get("routes") or {}).get(route_id) or {})
    if not route:
        raise CanonError(f"claude_cli_route_missing:{route_id}")
    if route.get("executor_worker") != "claude_code":
        raise CanonError(f"claude_cli_route_bad_executor:{route_id}")
    if route.get("execution_mode") != "automatic_cli":
        raise CanonError(f"claude_cli_route_not_automatic:{route_id}")
    return route


def _resolve_cli(cli_command: str) -> str | None:
    if os.sep in cli_command or (os.altsep and os.altsep in cli_command):
        path = Path(cli_command).expanduser()
        return str(path.resolve()) if path.is_file() and os.access(str(path), os.X_OK) else None
    return shutil.which(cli_command)


def _sanitized_env(source: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    return env


def check_claude_auth(
    cli_command: str = "claude",
    *,
    source_env: dict[str, str] | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Verify local subscription/OAuth auth without exposing credential material."""
    original_env = dict(os.environ if source_env is None else source_env)
    if original_env.get("ANTHROPIC_API_KEY"):
        return {
            "ok": False,
            "status": "forbidden_api_key",
            "error": "ANTHROPIC_API_KEY is forbidden; Claude Code must use subscription auth",
        }
    cli = _resolve_cli(cli_command)
    if not cli:
        return {"ok": False, "status": "worker_missing", "error": "claude CLI not found"}
    try:
        cp = subprocess.run(
            [cli, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=_sanitized_env(original_env),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "auth_check_timeout", "error": "claude auth status timed out"}
    except OSError as exc:
        return {"ok": False, "status": "auth_check_failed", "error": f"{type(exc).__name__}:{exc}"}

    try:
        payload = json.loads(cp.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "ok": False,
            "status": "auth_check_invalid_json",
            "error": (cp.stderr or cp.stdout or "invalid auth response")[:500],
        }
    logged_in = bool(payload.get("loggedIn", payload.get("logged_in", False)))
    auth_method = str(payload.get("authMethod") or payload.get("auth_method") or "none")
    if cp.returncode != 0 or not logged_in:
        return {
            "ok": False,
            "status": "auth_missing",
            "logged_in": logged_in,
            "auth_method": auth_method,
            "error": "Claude Code subscription authentication is not active on this host",
        }
    if auth_method.lower().replace("-", "_") in {"api_key", "apikey"}:
        return {
            "ok": False,
            "status": "forbidden_auth_method",
            "logged_in": True,
            "auth_method": auth_method,
            "error": "API-key authentication is forbidden for this worker",
        }
    return {
        "ok": True,
        "status": "authenticated",
        "logged_in": True,
        "auth_method": auth_method,
        "api_provider": str(payload.get("apiProvider") or payload.get("api_provider") or "NO_CONSTA"),
        "cli": cli,
    }


def prepare_workspace(run_dir: Path) -> Path:
    """Copy the immutable candidate snapshot into an isolated Claude workspace."""
    ws = run_dir / "WORKSPACES" / "claude_code"
    if ws.is_symlink():
        raise RuntimeError("claude_workspace_symlink_rejected")
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True, exist_ok=True)
    snapshot = candidate_source(run_dir)
    if snapshot.exists():
        for item in snapshot.rglob("*"):
            if item.is_file() and not item.is_symlink():
                rel = item.relative_to(snapshot)
                dst = ws / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
    agents = ROOT / "generated" / "CLAUDE.md"
    if agents.exists():
        overlay = ws / ".camino_runtime"
        overlay.mkdir(exist_ok=True)
        shutil.copy2(agents, overlay / "CLAUDE.md")
    return ws


def _validate_slot14_job(job: dict[str, Any]) -> str | None:
    if str(job.get("slot_id") or "") != "14":
        return "job_slot_id_must_be_14"
    candidate_sha = str(job.get("candidate_sha256") or "").lower()
    if not SHA256_RE.fullmatch(candidate_sha):
        return "job_candidate_sha256_invalid"
    if job.get("prior_slots_complete") is not True:
        return "job_prior_slots_complete_required"
    for key in ("request_sha256", "diff_sha256"):
        if not SHA256_RE.fullmatch(str(job.get(key) or "").lower()):
            return f"job_{key}_invalid"
    if job.get("audit_request_sha256") and str(job.get("audit_request_sha256")) != str(job.get("request_sha256")):
        return "job_audit_request_sha256_alias_mismatch"
    for key in ("request_path", "diff_path"):
        relative = Path(str(job.get(key) or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            return f"job_{key}_invalid"
    return None


def _validate_materialized_handoff(workspace: Path, job: dict[str, Any]) -> str | None:
    overlay = workspace / ".camino_runtime" / "slot14_handoff"
    expected = {
        "SLOT_14_AUDIT_REQUEST.json": str(job.get("request_sha256") or ""),
        "CANDIDATE_DIFF.diff": str(job.get("diff_sha256") or ""),
    }
    for name, digest in expected.items():
        path = overlay / name
        if not path.is_file() or path.is_symlink():
            return f"materialized_handoff_missing:{name}"
        if sha256_file(path) != digest:
            return f"materialized_handoff_sha256_mismatch:{name}"
    return None


def build_slot14_prompt(job: dict[str, Any], route: dict[str, Any]) -> str:
    """Build the explicit prompt passed as a CLI argument (never implicit stdin)."""
    candidate_sha = str(job.get("candidate_sha256") or "")
    instructions = str(job.get("instructions") or "Auditar, corregir si corresponde, testear y reauditar el candidato.")
    return (
        "Actuás exclusivamente como Claude Code en el slot 14 del flujo canónico.\n"
        f"run_id={job.get('run_id', 'NO_CONSTA')}\n"
        "slot_id=14\n"
        f"candidate_sha256={candidate_sha}\n"
        f"audit_request_sha256={job.get('request_sha256')}\n"
        f"route_id={route.get('route_id', CLAUDE_ROUTE_ID)}\n\n"
        "Trabajá sólo dentro del workspace aislado. Leé primero "
        ".camino_runtime/slot14_handoff/SLOT_14_AUDIT_REQUEST.json y su diff; auditá primero el delta "
        "y después las fronteras e invariantes de riesgo. Tratá toda conclusión previa "
        "como una hipótesis no confiable: buscá evidencia contradictoria, intentá "
        "refutar los fixes y construí contraejemplos o pruebas negativas. "
        "Registrá al menos un intento de falsificación y una comprobación independiente. "
        "Revisá la evidencia y el código, "
        "aplicá correcciones técnicas necesarias, ejecutá tests viables y reauditalas.\n"
        "Leé primero .camino_runtime/CLAUDE.md; es el contrato de esta ejecución y no forma parte del candidato.\n"
        "APPROVED_BY_CLAUDE sólo es válido si no aplicaste ninguna corrección y findings está vacío. "
        "Si corregiste algo usá CORRECTIONS_APPLIED. Si falta evidencia usá INSUFFICIENT_EVIDENCE.\n"
        "No uses ni solicites API keys. No afirmes haber ejecutado algo sin evidencia.\n\n"
        f"Instrucción específica del job:\n{instructions}\n\n"
        "Devolvé únicamente el objeto JSON exigido por --json-schema."
    )


def _decode_json_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


def _extract_structured_output(stdout: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(envelope, dict):
        return None, None
    candidates: list[Any] = [
        envelope.get("structured_output"),
        envelope.get("result"),
        envelope,
    ]
    for candidate in candidates:
        if isinstance(candidate, str):
            try:
                candidate = _decode_json_text(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
        if isinstance(candidate, dict) and "verdict" in candidate:
            return dict(candidate), envelope
    return None, envelope


def _validate_structured_output(payload: dict[str, Any]) -> str | None:
    verdict = str(payload.get("verdict") or "")
    if verdict not in ALLOWED_VERDICTS:
        return "invalid_verdict"
    if not isinstance(payload.get("summary"), str) or not payload.get("summary", "").strip():
        return "summary_required"
    if not isinstance(payload.get("findings"), list):
        return "findings_must_be_array"
    if not isinstance(payload.get("corrections_applied"), bool):
        return "corrections_applied_must_be_boolean"
    if not isinstance(payload.get("tests"), list) or not all(isinstance(v, str) for v in payload["tests"]):
        return "tests_must_be_string_array"
    if not SHA256_RE.fullmatch(str(payload.get("audit_request_sha256") or "").lower()):
        return "audit_request_sha256_invalid"
    for key in ("falsification_attempts", "independent_checks"):
        values = payload.get(key)
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v.strip() for v in values):
            return f"{key}_must_be_nonempty_string_array"
    if verdict == APPROVAL_VERDICT and (payload["corrections_applied"] or payload["findings"]):
        return "invalid_approval_claim_with_corrections_or_findings"
    if verdict == "CORRECTIONS_APPLIED" and payload["corrections_applied"] is not True:
        return "corrections_verdict_requires_corrections_applied"
    return None


def _base_result(job: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    return {
        "worker_id": "claude_code",
        "job_id": str(job.get("job_id") or ""),
        "run_id": str(job.get("run_id") or ""),
        "slot_id": str(job.get("slot_id") or "NO_CONSTA"),
        "source_slot_id": str(job.get("source_slot_id") or ""),
        "prior_slots_complete": job.get("prior_slots_complete") is True,
        "candidate_sha256": str(job.get("candidate_sha256") or ""),
        "request_path": str(job.get("request_path") or ""),
        "request_sha256": str(job.get("request_sha256") or ""),
        "diff_path": str(job.get("diff_path") or ""),
        "diff_sha256": str(job.get("diff_sha256") or ""),
        "audit_request_path": str(job.get("request_path") or ""),
        "audit_request_sha256": str(job.get("request_sha256") or ""),
        "audit_diff_path": str(job.get("diff_path") or ""),
        "audit_diff_sha256": str(job.get("diff_sha256") or ""),
        "status": "failed",
        "route_id": str(route.get("route_id") or CLAUDE_ROUTE_ID),
        "model_id": str(route.get("model_id") or route.get("model_alias") or "NO_CONSTA"),
        "model_id_actual": "NO_CONSTA",
        "provider_id": str(route.get("provider_id") or "claude_code_subscription"),
        "provider_name": str(route.get("provider_name") or "Claude Code"),
        "route": str(route.get("route") or "local_cli_subscription"),
        "interface": str(route.get("interface") or "claude_cli"),
        "cost_class": str(route.get("cost_class") or "included_in_plan"),
        "role": str(route.get("role") or "final_corrector_writer_and_only_approver"),
        "execution_mode": str(route.get("execution_mode") or "automatic_cli"),
        "verdict": "NO_VERDICT",
        "approval_eligible": False,
        "corrections_applied": False,
        "findings": [],
        "tests": [],
        "falsification_attempts": [],
        "independent_checks": [],
        "summary": "Claude Code did not produce a validated slot-14 result.",
        "passes": 0,
        "artifacts": [],
        "changed_artifacts": [],
        "exit_code": None,
    }


def run_claude_code(
    workspace: Path,
    timeout_minutes: int = 45,
    max_input_chars: int = 25000,
    *,
    job: dict[str, Any] | None = None,
    route: dict[str, Any] | None = None,
    cli_command: str = "claude",
    source_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute one canonical slot-14 CLI review with structured output."""
    job = dict(job or {})
    route = dict(route or load_claude_route())
    result = _base_result(job, route)

    job_error = _validate_slot14_job(job)
    if job_error:
        result.update({"error_class": "invalid_job", "error": job_error})
        return result

    handoff_error = _validate_materialized_handoff(workspace, job)
    if handoff_error:
        result.update({"error_class": "invalid_handoff", "error": handoff_error})
        return result

    auth = check_claude_auth(cli_command, source_env=source_env)
    result["auth"] = {k: v for k, v in auth.items() if k != "cli"}
    if not auth.get("ok"):
        if auth.get("status") == "worker_missing":
            result["status"] = "worker_missing"
        result.update({"error_class": str(auth.get("status") or "auth_failed"), "error": auth.get("error")})
        return result

    prompt = build_slot14_prompt(job, route)
    if len(prompt) > max_input_chars:
        result.update({"error_class": "prompt_too_large", "error": f"prompt has {len(prompt)} chars; max={max_input_chars}"})
        return result

    model_alias = str(route.get("model_alias") or route.get("model_id") or "opus")
    max_turns = max(1, int(route.get("max_turns") or 20))
    cli = str(auth["cli"])
    cmd = [
        cli,
        "--print",
        "--output-format", "json",
        "--json-schema", json.dumps(CLAUDE_SLOT14_OUTPUT_SCHEMA, separators=(",", ":")),
        "--model", model_alias,
        "--max-turns", str(max_turns),
        "--permission-mode", str(route.get("permission_mode") or "acceptEdits"),
        "--no-session-persistence",
    ]
    fallback_alias = str(route.get("fallback_model_alias") or "").strip()
    if fallback_alias:
        cmd.extend(["--fallback-model", fallback_alias])
    cmd.append(prompt)

    before = _workspace_hashes(workspace)
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_minutes * 60,
            env=_sanitized_env(source_env),
        )
    except subprocess.TimeoutExpired as exc:
        result.update({
            "error_class": "timeout",
            "error": f"timeout after {timeout_minutes}m",
            "_raw_stdout": exc.stdout or "",
            "_raw_stderr": exc.stderr or "",
        })
        return result
    except OSError as exc:
        result.update({"error_class": "cli_execution_failed", "error": f"{type(exc).__name__}:{exc}"})
        return result

    result.update({
        "passes": 1,
        "exit_code": cp.returncode,
        "_raw_stdout": cp.stdout,
        "_raw_stderr": cp.stderr,
    })
    after = _workspace_hashes(workspace)
    result["changed_artifacts"] = [
        {"path": path, "before_sha256": before.get(path), "after_sha256": after.get(path)}
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    ]
    # A non-approving review may still have corrected files. Preserve their
    # hashes as evidence even though the bundle must not count as approval.
    _collect_workspace_artifacts(workspace, result)
    if cp.returncode != 0:
        result.update({
            "error_class": "claude_cli_nonzero",
            "error": (cp.stderr or cp.stdout or "Claude CLI failed")[:1000],
        })
        return result

    structured, envelope = _extract_structured_output(cp.stdout)
    if envelope:
        actual_model = envelope.get("model") or envelope.get("model_id")
        if actual_model:
            result["model_id_actual"] = str(actual_model)
    if structured is None:
        result.update({"error_class": "structured_output_missing", "error": "Claude CLI returned no schema-valid JSON object"})
        return result
    validation_error = _validate_structured_output(structured)
    if not validation_error and str(structured.get("audit_request_sha256") or "") != str(job.get("request_sha256") or ""):
        validation_error = "audit_request_sha256_ack_mismatch"
    result["structured_output"] = structured
    result.update({
        "verdict": str(structured.get("verdict") or "NO_VERDICT"),
        "summary": str(structured.get("summary") or ""),
        "findings": list(structured.get("findings") or []),
        "corrections_applied": bool(structured.get("corrections_applied")),
        "tests": list(structured.get("tests") or []),
        "falsification_attempts": list(structured.get("falsification_attempts") or []),
        "independent_checks": list(structured.get("independent_checks") or []),
    })
    if validation_error:
        result.update({"error_class": "invalid_structured_output", "error": validation_error})
        return result

    # Fail closed with the current master: only a genuinely clean approval may
    # have status=ok.  Corrections/blockers remain recorded but cannot let the
    # lane-only terminal check close the run by mistake.
    if result["verdict"] != APPROVAL_VERDICT:
        result.update({
            "error_class": "not_approved",
            "error": "slot 14 did not produce a clean approval; restart or manual action required",
        })
        return result

    if result["changed_artifacts"]:
        result.update({
            "error_class": "workspace_changed_during_approval",
            "error": "clean approval cannot modify the isolated workspace",
        })
        return result

    result["status"] = "ok"
    result["approval_eligible"] = True

    return result


def _collect_workspace_artifacts(workspace: Path, result: dict[str, Any]) -> None:
    max_files = 500
    max_bytes = 10 * 1024 * 1024
    for item in sorted(workspace.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        if len(result["artifacts"]) >= max_files:
            result["artifacts_truncated"] = True
            break
        size = item.stat().st_size
        if size > max_bytes:
            continue
        result["artifacts"].append({
            "path": str(item.relative_to(workspace)),
            "sha256": sha256_file(item),
            "size_bytes": size,
        })


def _workspace_hashes(workspace: Path) -> dict[str, str]:
    ignored = {".git", "__pycache__", ".pytest_cache"}
    values: dict[str, str] = {}
    for item in sorted(workspace.rglob("*")):
        relative = item.relative_to(workspace)
        if item.is_symlink():
            values[str(relative)] = "NODE:SYMLINK"
            continue
        if not item.is_file():
            continue
        if any(part in ignored for part in relative.parts):
            continue
        values[str(relative)] = sha256_file(item)
    return values


def write_bundle(run_dir: Path, job: dict[str, Any], result: dict[str, Any], workspace: Path) -> Path:
    """Persist complete CLI output plus the normalized approval record."""
    out_dir = (
        run_dir / "13_WORKER_BUS" / "claude_code" / "OUT"
        / f"claude_code_{utc_now().replace(':', '-')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if (
        result.get("verdict") == "CORRECTIONS_APPLIED"
        and result.get("corrections_applied") is True
        and bool(result.get("changed_artifacts"))
    ):
        try:
            result["candidate_update"] = create_candidate_update_archive(
                workspace, out_dir,
                source_candidate_sha256=str(job.get("candidate_sha256") or ""),
                worker_id="claude_code", slot_id="14",
            )
        except CandidateUpdateError as exc:
            result["candidate_update_error"] = str(exc)

    raw_stdout = str(result.get("_raw_stdout") or "")
    raw_stderr = str(result.get("_raw_stderr") or "")
    public_result = {k: v for k, v in result.items() if not k.startswith("_")}
    write_json(out_dir / "result.json", public_result)
    (out_dir / "claude_code_stdout.txt").write_text(raw_stdout, encoding="utf-8")
    (out_dir / "claude_code_stderr.txt").write_text(raw_stderr, encoding="utf-8")
    write_json(out_dir / "claude_code_structured_output.json", public_result.get("structured_output") or {})

    report_lines = [
        "# Claude Code slot 14 report",
        "",
        f"- Run: `{run_dir.name}`",
        f"- Slot: `{public_result.get('slot_id')}`",
        f"- Candidate: `{public_result.get('candidate_sha256')}`",
        f"- Status: `{public_result.get('status')}`",
        f"- Verdict: `{public_result.get('verdict')}`",
        f"- Approval eligible: `{public_result.get('approval_eligible')}`",
        f"- Corrections applied: `{public_result.get('corrections_applied')}`",
        f"- Findings: `{len(public_result.get('findings') or [])}`",
        f"- Exit code: `{public_result.get('exit_code')}`",
        "",
        "## Summary",
        "",
        str(public_result.get("summary") or "No summary."),
    ]
    if public_result.get("error"):
        report_lines += ["", "## Error", "", str(public_result["error"])]
    (out_dir / "claude_code_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    files = [
        "result.json",
        "claude_code_stdout.txt",
        "claude_code_stderr.txt",
        "claude_code_structured_output.json",
        "claude_code_report.md",
    ]
    if (out_dir / "candidate_update.zip").is_file():
        files.append("candidate_update.zip")
    write_output_manifest_and_done(
        run_dir,
        str(out_dir.relative_to(run_dir)),
        done_name="CLAUDE_CODE_OUTPUT.DONE",
        stage="slot_14_final_review",
        candidate_sha256=str(job.get("candidate_sha256") or ""),
        files=tuple(files),
    )
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code subscription worker for slot 14")
    parser.add_argument("--run", required=True, help="Run directory")
    parser.add_argument("--timeout-minutes", type=int, default=45)
    parser.add_argument("--max-input-chars", type=int, default=25000)
    parser.add_argument("--claude-cli", default=os.environ.get("CLAUDE_CLI", "claude"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
        return 2
    try:
        route = load_claude_route()
    except CanonError as exc:
        print(f"CANON_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 2

    inbox = run_dir / "13_WORKER_BUS" / "claude_code" / "IN"
    job = read_json(inbox / "job.json", {}) if (inbox / "job.json").exists() else {}
    if args.dry_run:
        print(json.dumps({
            "status": "dry_run",
            "worker": "claude_code",
            "route_id": route.get("route_id"),
            "job_slot_id": job.get("slot_id"),
        }, indent=2))
        return 0

    workspace = prepare_workspace(run_dir)
    bound, binding = verify_candidate_binding(
        run_dir, str(job.get("candidate_sha256") or ""),
    )
    if not bound:
        result = _base_result(job, route)
        result.update({
            "error_class": "candidate_binding_failed", "error": binding,
        })
    else:
        handoff_ok, handoff_reason = materialize_slot14_handoff(run_dir, workspace, job)
        if not handoff_ok:
            result = _base_result(job, route)
            result.update({"error_class": "invalid_handoff", "error": handoff_reason})
        else:
            result = run_claude_code(
                workspace,
                args.timeout_minutes,
                args.max_input_chars,
                job=job,
                route=route,
                cli_command=args.claude_cli,
            )
    bundle_dir = write_bundle(run_dir, job, result, workspace)
    public_result = {k: v for k, v in result.items() if not k.startswith("_")}
    public_result["output_bundle"] = str(bundle_dir.relative_to(run_dir))

    state = load_state(run_dir)
    history_event(state, "claude_code_slot14_done", **public_result)
    save_state(run_dir, state)
    print(json.dumps(public_result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "ok" and result.get("approval_eligible") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
