#!/usr/bin/env python3
"""Subscription-only Codex fallback for the canonical slot 14.

Claude Code remains the primary reviewer.  This worker may run only after a
recorded Claude availability/auth/transport failure.  It invokes the locally
authenticated Codex CLI with the exact configured model (gpt-5.6-sol) and
reasoning effort (ultra), removes API credential variables, and fails closed
unless the structured review is clean and the workspace was not modified.
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
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canon_loader import CanonError, load_canon  # noqa: E402
from scripts.run_multiaudit_cycle import (  # noqa: E402
    history_event,
    load_state,
    read_json,
    save_state,
    sha256_file,
    utc_now,
    write_json,
    write_output_manifest_and_done,
)
from scripts.candidate_updates import (  # noqa: E402
    CandidateUpdateError, candidate_source, create_candidate_update_archive,
    verify_candidate_binding,
)
from scripts.slot14_handoff import materialize_slot14_handoff  # noqa: E402


ROUTE_ID = "codex_gpt_5_6_sol_ultra_subscription_cli"
APPROVAL_VERDICT = "APPROVED_BY_CODEX_FALLBACK"
ALLOWED_VERDICTS = {
    APPROVAL_VERDICT,
    "CORRECTIONS_APPLIED",
    "BLOCKED",
    "INSUFFICIENT_EVIDENCE",
}
ALLOWED_FALLBACK_TRIGGERS = {
    "claude_auth_missing",
    "claude_worker_missing",
    "claude_auth_check_failed",
    "claude_auth_check_timeout",
    "claude_cli_nonzero",
    "claude_cli_execution_failed",
    "claude_timeout",
    "claude_unavailable",
}
TRIGGER_ERROR_CLASSES = {
    "claude_auth_missing": {"auth_missing", "forbidden_auth_method", "forbidden_api_key"},
    "claude_worker_missing": {"worker_missing", "skipped_cli_missing"},
    "claude_auth_check_failed": {"auth_check_failed", "auth_check_invalid_json"},
    "claude_auth_check_timeout": {"auth_check_timeout"},
    "claude_cli_nonzero": {"claude_cli_nonzero"},
    "claude_cli_execution_failed": {"cli_execution_failed"},
    "claude_timeout": {"timeout"},
    "claude_unavailable": {"claude_unavailable", "disabled_by_profile"},
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
OPERATOR_ACTION_ERROR_CLASSES = {
    "auth_missing", "worker_missing", "forbidden_api_key", "auth_check_timeout",
    "auth_check_failed", "model_catalog_timeout", "model_catalog_failed",
    "model_catalog_invalid_json", "model_or_effort_unavailable", "timeout",
    "cli_execution_failed", "codex_cli_nonzero", "invalid_job", "invalid_handoff",
    "candidate_binding_failed",
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict", "summary", "findings", "corrections_applied", "tests",
        "audit_request_sha256", "falsification_attempts", "independent_checks",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": sorted(ALLOWED_VERDICTS)},
        "summary": {"type": "string", "minLength": 1, "maxLength": 20000},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                # Codex structured outputs require every object to be closed
                # and every declared property to be listed as required.  Use
                # an empty string when a finding has no applicable file.
                "required": ["id", "severity", "summary", "file"],
                "additionalProperties": False,
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


def load_route(root: Path = ROOT) -> dict[str, Any]:
    route = dict((load_canon(root).routes.get("routes") or {}).get(ROUTE_ID) or {})
    if not route:
        raise CanonError("codex_subscription_fallback_route_missing")
    required = {
        "executor_worker": "codex_fallback",
        "execution_mode": "automatic_cli_fallback",
        "model_id": "gpt-5.6-sol",
        "model_reasoning_effort": "ultra",
        "api_key_allowed": False,
        "process_isolation": "separate_codex_exec",
        "inherits_orchestrator_model": False,
        "self_model_switch": False,
    }
    if any(route.get(key) != value for key, value in required.items()):
        raise CanonError("codex_subscription_fallback_route_invalid")
    return route


def _resolve_cli(command: str) -> Optional[str]:
    if os.sep in command or (os.altsep and os.altsep in command):
        path = Path(command).expanduser()
        return str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
    return shutil.which(command)


def _sanitized_env(source: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def check_codex_subscription_auth(
    cli_command: str = "codex",
    *,
    source_env: Optional[Mapping[str, str]] = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    original = dict(os.environ if source_env is None else source_env)
    if original.get("OPENAI_API_KEY"):
        return {
            "ok": False,
            "status": "forbidden_api_key",
            "error": "OPENAI_API_KEY is forbidden; fallback requires ChatGPT subscription auth",
        }
    cli = _resolve_cli(cli_command)
    if not cli:
        return {"ok": False, "status": "worker_missing", "error": "codex CLI not found"}
    try:
        cp = subprocess.run(
            [cli, "login", "status"],
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds),
            env=_sanitized_env(original),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "auth_check_timeout", "error": "codex login status timed out"}
    except OSError as exc:
        return {"ok": False, "status": "auth_check_failed", "error": f"{type(exc).__name__}:{exc}"}
    public = (cp.stdout + "\n" + cp.stderr).strip()
    logged_in = cp.returncode == 0 and "logged in using chatgpt" in public.lower()
    if not logged_in:
        return {
            "ok": False,
            "status": "auth_missing",
            "error": "Codex ChatGPT subscription authentication is not active",
        }
    return {
        "ok": True,
        "status": "authenticated",
        "auth_method": "chatgpt_subscription",
        "cli": cli,
    }


def check_codex_model_capability(
    cli_command: str = "codex",
    *,
    model_id: str = "gpt-5.6-sol",
    reasoning_effort: str = "ultra",
    source_env: Optional[Mapping[str, str]] = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Fail closed unless the installed Codex catalog exposes model + effort.

    This is a local capability check.  It does not claim account quota or a
    successful review; the subsequent real ``codex exec`` remains authoritative.
    """
    cli = _resolve_cli(cli_command)
    if not cli:
        return {"ok": False, "status": "worker_missing", "error": "codex CLI not found"}
    try:
        cp = subprocess.run(
            [cli, "debug", "models", "--bundled"],
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds),
            env=_sanitized_env(source_env),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "status": "model_catalog_timeout",
            "error": "codex bundled model catalog timed out",
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "model_catalog_failed",
            "error": f"{type(exc).__name__}:{exc}",
        }
    if cp.returncode != 0:
        return {
            "ok": False,
            "status": "model_catalog_failed",
            "error": (cp.stderr or cp.stdout or "codex bundled model catalog failed")[:1000],
        }
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError:
        # Some builds may prepend a warning to stdout. Decode the first JSON
        # object/array without ever persisting the large catalog.
        stripped = cp.stdout.lstrip()
        starts = [pos for pos in (stripped.find("{"), stripped.find("[")) if pos >= 0]
        if not starts:
            return {
                "ok": False,
                "status": "model_catalog_invalid_json",
                "error": "codex bundled model catalog did not return JSON",
            }
        try:
            payload, _ = json.JSONDecoder().raw_decode(stripped[min(starts):])
        except json.JSONDecodeError:
            return {
                "ok": False,
                "status": "model_catalog_invalid_json",
                "error": "codex bundled model catalog returned invalid JSON",
            }
    models = payload.get("models") if isinstance(payload, dict) else payload
    if not isinstance(models, list):
        return {
            "ok": False,
            "status": "model_catalog_invalid_json",
            "error": "codex bundled model catalog has no models array",
        }
    selected = next(
        (item for item in models if isinstance(item, dict) and item.get("slug") == model_id),
        None,
    )
    levels = selected.get("supported_reasoning_levels") if isinstance(selected, dict) else []
    supported = {
        str(level.get("effort"))
        for level in levels or []
        if isinstance(level, dict) and level.get("effort")
    }
    if selected is None or reasoning_effort not in supported:
        return {
            "ok": False,
            "status": "model_or_effort_unavailable",
            "error": f"Codex catalog does not expose {model_id} with {reasoning_effort}",
            "catalog_source": "codex debug models --bundled",
            "model_id": model_id,
            "reasoning_effort": reasoning_effort,
        }
    return {
        "ok": True,
        "status": "model_capability_verified",
        "catalog_source": "codex debug models --bundled",
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
    }


def _validate_job(job: Mapping[str, Any]) -> Optional[str]:
    if not str(job.get("run_id") or "").strip():
        return "job_run_id_required"
    if str(job.get("slot_id") or "") != "14":
        return "job_slot_id_must_be_14"
    if not SHA256_RE.fullmatch(str(job.get("candidate_sha256") or "").lower()):
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
    trigger = str(job.get("fallback_trigger") or "")
    if trigger not in ALLOWED_FALLBACK_TRIGGERS:
        return "fallback_trigger_not_allowed"
    primary = job.get("claude_attempt")
    if not isinstance(primary, dict) or primary.get("approval_eligible") is True:
        return "recorded_nonapproving_claude_attempt_required"
    if primary.get("worker_id") != "claude_code":
        return "claude_attempt_worker_mismatch"
    if str(primary.get("run_id") or "") != str(job.get("run_id") or ""):
        return "claude_attempt_run_mismatch"
    if str(primary.get("slot_id") or "") != "14":
        return "claude_attempt_slot_mismatch"
    if str(primary.get("candidate_sha256") or "") != str(job.get("candidate_sha256") or ""):
        return "claude_attempt_candidate_mismatch"
    if str(primary.get("error_class") or "") not in TRIGGER_ERROR_CLASSES.get(trigger, set()):
        return "claude_attempt_trigger_error_mismatch"
    if not str(primary.get("job_id") or "").strip():
        return "claude_attempt_job_id_required"
    durable = (
        SHA256_RE.fullmatch(str(primary.get("output_manifest_sha256") or "").lower())
        and str(primary.get("done_marker") or "").endswith(".DONE")
        and bool(str(primary.get("bundle") or "").strip())
    )
    recorded_unavailable = (
        primary.get("source") in {"runtime_profile", "master_inline_execution"}
        and trigger in {"claude_unavailable", "claude_worker_missing"}
    )
    if not durable and not recorded_unavailable:
        return "claude_attempt_durable_evidence_required"
    return None


def prepare_workspace(run_dir: Path) -> Path:
    workspace = run_dir / "WORKSPACES" / "codex_fallback"
    if workspace.is_symlink():
        raise RuntimeError("codex_fallback_workspace_symlink_rejected")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    snapshot = candidate_source(run_dir)
    for item in sorted(snapshot.rglob("*")) if snapshot.exists() else []:
        if item.is_file() and not item.is_symlink():
            destination = workspace / item.relative_to(snapshot)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
    agents = ROOT / "generated" / "AGENTS.md"
    if agents.is_file():
        overlay = workspace / ".camino_runtime"
        overlay.mkdir(exist_ok=True)
        shutil.copy2(agents, overlay / "AGENTS.md")
    return workspace


def _validate_materialized_handoff(workspace: Path, job: Mapping[str, Any]) -> Optional[str]:
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


def _base_result(job: Mapping[str, Any], route: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "worker_id": "codex_fallback",
        "job_id": str(job.get("job_id") or ""),
        "run_id": str(job.get("run_id") or ""),
        "slot_id": "14",
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
        "route_id": ROUTE_ID,
        "model_id": str(route.get("model_id") or "gpt-5.6-sol"),
        "model_reasoning_effort": str(route.get("model_reasoning_effort") or "ultra"),
        "process_isolation": str(route.get("process_isolation") or "separate_codex_exec"),
        "inherits_orchestrator_model": bool(route.get("inherits_orchestrator_model", False)),
        "self_model_switch": bool(route.get("self_model_switch", False)),
        "provider_id": "codex_chatgpt_subscription",
        "provider_name": "Codex CLI (ChatGPT subscription)",
        "route": "local_cli_subscription",
        "interface": "codex_cli",
        "cost_class": "included_in_chatgpt_plan",
        "role": "slot_14_final_reviewer_fallback",
        "fallback_trigger": str(job.get("fallback_trigger") or ""),
        "claude_attempt": dict(job.get("claude_attempt") or {}),
        "verdict": "NO_VERDICT",
        "approval_eligible": False,
        "corrections_applied": False,
        "findings": [],
        "tests": [],
        "falsification_attempts": [],
        "independent_checks": [],
        "summary": "Codex subscription fallback did not produce a validated clean review.",
        "changed_artifacts": [],
        "exit_code": None,
    }


def _validate_output(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return "structured_output_not_object"
    if payload.get("verdict") not in ALLOWED_VERDICTS:
        return "invalid_verdict"
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
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
    if payload["verdict"] == APPROVAL_VERDICT and (payload["corrections_applied"] or payload["findings"]):
        return "invalid_approval_with_corrections_or_findings"
    if payload["verdict"] == "CORRECTIONS_APPLIED" and payload["corrections_applied"] is not True:
        return "corrections_verdict_requires_corrections"
    return None


def run_codex_fallback(
    workspace: Path,
    job: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    cli_command: str = "codex",
    source_env: Optional[Mapping[str, str]] = None,
    timeout_minutes: int = 60,
) -> dict[str, Any]:
    result = _base_result(job, route)
    job_error = _validate_job(job)
    if job_error:
        result.update({"error_class": "invalid_job", "error": job_error})
        return result
    handoff_error = _validate_materialized_handoff(workspace, job)
    if handoff_error:
        result.update({"error_class": "invalid_handoff", "error": handoff_error})
        return result
    auth = check_codex_subscription_auth(cli_command, source_env=source_env)
    result["auth"] = {key: value for key, value in auth.items() if key != "cli"}
    if not auth.get("ok"):
        result.update({"error_class": str(auth.get("status")), "error": auth.get("error")})
        return result

    model_preflight = check_codex_model_capability(
        str(auth["cli"]),
        model_id=str(route["model_id"]),
        reasoning_effort=str(route["model_reasoning_effort"]),
        source_env=source_env,
    )
    result["model_preflight"] = model_preflight
    if not model_preflight.get("ok"):
        result.update({
            "error_class": str(model_preflight.get("status")),
            "error": model_preflight.get("error"),
        })
        return result

    before = _workspace_hashes(workspace)
    state_dir = workspace.parent.parent / "STATE" / "codex_fallback"
    state_dir.mkdir(parents=True, exist_ok=True)
    schema_path = state_dir / "slot14_output.schema.json"
    output_path = state_dir / "slot14_last_message.json"
    write_json(schema_path, OUTPUT_SCHEMA)
    output_path.unlink(missing_ok=True)
    prompt = (
        "Actuás únicamente como fallback de Claude Code en el slot 14. "
        "La autenticación debe ser la suscripción ChatGPT del CLI, nunca OpenAI API.\n"
        f"run_id={job.get('run_id')}\nslot_id=14\n"
        f"candidate_sha256={job.get('candidate_sha256')}\n"
        f"audit_request_sha256={job.get('request_sha256')}\n"
        f"fallback_trigger={job.get('fallback_trigger')}\n\n"
        "Leé primero .camino_runtime/slot14_handoff/SLOT_14_AUDIT_REQUEST.json y su diff. Auditá "
        "primero el delta y luego las fronteras e invariantes de riesgo. Tratá cada "
        "conclusión previa como hipótesis no confiable: buscá evidencia contradictoria, "
        "intentá refutar fixes y construí contraejemplos o pruebas negativas. Registrá "
        "al menos un intento de falsificación y una comprobación independiente. "
        "Revisá el workspace aislado, ejecutá pruebas razonables y reauditalo. "
        "Leé .camino_runtime/AGENTS.md como contrato de ejecución; no lo modifiques. "
        "APPROVED_BY_CODEX_FALLBACK sólo es válido si no modificaste ningún archivo y findings está vacío. "
        "Si corregís algo, devolvé CORRECTIONS_APPLIED; eso reinicia el bucle y no aprueba. "
        "No afirmes acciones sin evidencia. Devolvé sólo el JSON del esquema."
    )
    cli = str(auth["cli"])
    # ``--ask-for-approval`` is a top-level Codex option.  Current CLIs reject
    # it when placed after ``exec`` even though several other options are
    # accepted in both positions.
    command = [
        cli, "--ask-for-approval", "never", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--model", str(route["model_id"]),
        "--config", 'model_reasoning_effort="%s"' % route["model_reasoning_effort"],
        "--sandbox", "workspace-write",
        "--output-schema", str(schema_path),
        "--output-last-message", str(output_path),
        "--cd", str(workspace),
        prompt,
    ]
    try:
        cp = subprocess.run(
            command,
            # A persistent orchestrator may keep its own stdin pipe open.
            # Codex otherwise treats that pipe as additional prompt input and
            # waits forever, so the subscription worker must be explicitly
            # non-interactive.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=max(1, timeout_minutes) * 60,
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
    if cp.returncode != 0:
        result.update({"error_class": "codex_cli_nonzero", "error": (cp.stderr or cp.stdout or "Codex CLI failed")[:1000]})
        return result
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.update({"error_class": "structured_output_missing", "error": f"{type(exc).__name__}:{exc}"})
        return result
    validation_error = _validate_output(payload)
    if not validation_error and str(payload.get("audit_request_sha256") or "") != str(job.get("request_sha256") or ""):
        validation_error = "audit_request_sha256_ack_mismatch"
    result["structured_output"] = payload
    result.update({
        "verdict": str(payload.get("verdict") or "NO_VERDICT"),
        "summary": str(payload.get("summary") or ""),
        "findings": list(payload.get("findings") or []),
        "corrections_applied": bool(payload.get("corrections_applied")),
        "tests": list(payload.get("tests") or []),
        "falsification_attempts": list(payload.get("falsification_attempts") or []),
        "independent_checks": list(payload.get("independent_checks") or []),
    })
    if validation_error:
        result.update({"error_class": "invalid_structured_output", "error": validation_error})
        return result
    if result["verdict"] != APPROVAL_VERDICT:
        result.update({"error_class": "not_approved", "error": "Codex fallback did not produce a clean approval"})
        return result
    if result["changed_artifacts"]:
        result.update({"error_class": "workspace_changed_during_approval", "error": "clean approval cannot modify workspace"})
        return result
    result["status"] = "ok"
    result["approval_eligible"] = True
    return result


def write_bundle(
    run_dir: Path, job: Mapping[str, Any], result: dict[str, Any], workspace: Path,
) -> Path:
    out_dir = run_dir / "13_WORKER_BUS" / "codex_fallback" / "OUT" / f"codex_fallback_{utc_now().replace(':', '-')}"
    out_dir.mkdir(parents=True, exist_ok=False)
    if (
        result.get("verdict") == "CORRECTIONS_APPLIED"
        and result.get("corrections_applied") is True
        and bool(result.get("changed_artifacts"))
    ):
        try:
            result["candidate_update"] = create_candidate_update_archive(
                workspace, out_dir,
                source_candidate_sha256=str(job.get("candidate_sha256") or ""),
                worker_id="codex_fallback", slot_id="14",
            )
        except CandidateUpdateError as exc:
            result["candidate_update_error"] = str(exc)
    public = {key: value for key, value in result.items() if not key.startswith("_")}
    write_json(out_dir / "result.json", public)
    (out_dir / "codex_stdout.txt").write_text(str(result.get("_raw_stdout") or ""), encoding="utf-8")
    (out_dir / "codex_stderr.txt").write_text(str(result.get("_raw_stderr") or ""), encoding="utf-8")
    report = (
        "# Codex subscription fallback — slot 14\n\n"
        f"- Status: `{public.get('status')}`\n"
        f"- Verdict: `{public.get('verdict')}`\n"
        f"- Model: `{public.get('model_id')}`\n"
        f"- Reasoning: `{public.get('model_reasoning_effort')}`\n"
        f"- Trigger: `{public.get('fallback_trigger')}`\n"
        f"- Approval eligible: `{public.get('approval_eligible')}`\n"
        f"- Corrections: `{public.get('corrections_applied')}`\n"
        f"- Findings: `{len(public.get('findings') or [])}`\n\n"
        f"## Summary\n\n{public.get('summary') or 'No summary.'}\n"
    )
    (out_dir / "codex_fallback_report.md").write_text(report, encoding="utf-8")
    files = ["result.json", "codex_stdout.txt", "codex_stderr.txt", "codex_fallback_report.md"]
    if (out_dir / "candidate_update.zip").is_file():
        files.append("candidate_update.zip")
    write_output_manifest_and_done(
        run_dir,
        str(out_dir.relative_to(run_dir)),
        done_name="CODEX_FALLBACK_OUTPUT.DONE",
        stage="slot_14_codex_subscription_fallback",
        candidate_sha256=str(job.get("candidate_sha256") or ""),
        files=tuple(files),
    )
    return out_dir


def update_operator_action_marker(
    run_dir: Path, job: Mapping[str, Any], result: Mapping[str, Any],
) -> Path | None:
    """Persist a safe, durable recovery notice for subscription worker failures."""
    marker = run_dir / "STATE" / "SLOT14_OPERATOR_ACTION_REQUIRED.json"
    error_class = str(result.get("error_class") or "")
    if result.get("status") == "ok" and result.get("approval_eligible") is True:
        marker.unlink(missing_ok=True)
        return None
    if error_class not in OPERATOR_ACTION_ERROR_CLASSES:
        return None
    write_json(marker, {
        "schema_version": "camino_slot14_operator_action.v1",
        "status": "SLOT14_OPERATOR_ACTION_REQUIRED",
        "run_id": str(job.get("run_id") or run_dir.name),
        "job_id": str(job.get("job_id") or ""),
        "slot_id": "14",
        "candidate_sha256": str(job.get("candidate_sha256") or ""),
        "audit_request_sha256": str(job.get("request_sha256") or ""),
        "route_id": ROUTE_ID,
        "model_id": "gpt-5.6-sol",
        "model_reasoning_effort": "ultra",
        "process_isolation": "separate_codex_exec",
        "error_class": error_class,
        "safe_error": f"subscription worker unavailable ({error_class})",
        "required_action": (
            "Repair Codex ChatGPT subscription login, CLI/model capability, quota or "
            "transport, then resume this same run. Do not change the orchestrator model."
        ),
        "manual_or_desktop_result_may_approve": False,
        "created_at": utc_now(),
    })
    return marker


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Codex ChatGPT-subscription fallback for slot 14")
    parser.add_argument("--run", required=True)
    parser.add_argument("--codex-cli", default=os.environ.get("CODEX_CLI", "codex"))
    parser.add_argument("--timeout-minutes", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        print("ERROR: run directory not found", file=sys.stderr)
        return 2
    try:
        route = load_route()
    except CanonError as exc:
        print(f"CANON_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 2
    job = read_json(run_dir / "13_WORKER_BUS" / "codex_fallback" / "IN" / "job.json", {})
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "route_id": ROUTE_ID, "job": job}, indent=2))
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
            result = run_codex_fallback(
                workspace,
                job,
                route,
                cli_command=args.codex_cli,
                timeout_minutes=args.timeout_minutes,
            )
    bundle = write_bundle(run_dir, job, result, workspace)
    marker = update_operator_action_marker(run_dir, job, result)
    public = {key: value for key, value in result.items() if not key.startswith("_")}
    public["output_bundle"] = str(bundle.relative_to(run_dir))
    if marker is not None:
        public["operator_action_marker"] = str(marker.relative_to(run_dir))
    state = load_state(run_dir)
    history_event(state, "codex_subscription_fallback_done", **public)
    save_state(run_dir, state)
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" and result.get("approval_eligible") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
