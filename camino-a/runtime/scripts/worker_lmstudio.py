#!/usr/bin/env python3
"""Real, resource-guarded LM Studio route worker.

The worker lists the selected LM Studio server before dispatch, resolves models
from canonical ``route_id`` records, performs real OpenAI-compatible chat calls,
and caps the request pool at two.  Every request needs a live local resource
reservation with heartbeat/TTL.

For a bridge endpoint, the default is fail-closed because a guard measuring the
iMac cannot protect RAM on the MacBook.  Run this worker on the LM Studio host
(directly or through the configured peer transport), or explicitly attest an
authoritative guard with ``--memory-guard-authoritative``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.host_runtime import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    load_policy,
    resolve_lmstudio_endpoint,
)
from scripts.resource_scheduler import ResourceScheduler  # noqa: E402
from scripts.candidate_updates import verify_candidate_binding  # noqa: E402


ROUTES_PATH = ROOT / "canon" / "CANON_PROVIDER_MODEL_ROUTES.v1.json"


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_routes(path: Path = ROUTES_PATH) -> Dict[str, Dict[str, Any]]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("cannot_read_routes:%s:%s" % (path, exc))
    routes = document.get("routes")
    if not isinstance(routes, dict):
        raise RuntimeError("canonical_routes_missing")
    return {str(key): dict(value) for key, value in routes.items() if isinstance(value, dict)}


def _is_lmstudio_route(route: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(route.get(key, "")).lower()
        for key in ("provider_id", "provider_name", "route", "interface")
    )
    return "lmstudio" in text or "lm studio" in text


def _model_variants(model_id: str) -> Set[str]:
    value = str(model_id or "").strip()
    variants = {value.lower()}
    if "/" in value:
        variants.add(value.rsplit("/", 1)[-1].lower())
    if value.lower().startswith("models/"):
        variants.add(value[7:].lower())
    return {item for item in variants if item}


def model_is_listed(model_id: str, listed: Sequence[str]) -> bool:
    target = _model_variants(model_id)
    available: Set[str] = set()
    for item in listed:
        available.update(_model_variants(str(item)))
    return bool(target & available)


def _is_loopback_url(base_url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(base_url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _chat_completion(
    base_url: str,
    api_key: str,
    model_id: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    request_ttl_seconds: int,
    timeout_seconds: int,
) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    body: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max(1, int(max_tokens)),
        "temperature": float(temperature),
        "stream": False,
    }
    if request_ttl_seconds > 0:
        # LM Studio accepts TTL as an OpenAI-compatible extension when JIT model
        # loading is enabled.  The resource lease has an independent TTL too.
        body["ttl"] = int(request_ttl_seconds)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            choices = parsed.get("choices") if isinstance(parsed, dict) else None
            content = None
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = message.get("content")
            if not isinstance(content, str):
                return {
                    "status": "invalid_response",
                    "http_status": int(response.status),
                    "error": "missing_choices_message_content",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
            return {
                "status": "completed",
                "http_status": int(response.status),
                "content": content,
                "finish_reason": choices[0].get("finish_reason"),
                "usage": parsed.get("usage") if isinstance(parsed, dict) else None,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
    except urllib.error.HTTPError as exc:
        preview = exc.read().decode("utf-8", errors="replace")[:1000]
        return {
            "status": "http_error",
            "http_status": int(exc.code),
            "error": "http_%s" % exc.code,
            "body_preview": preview,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except urllib.error.URLError as exc:
        return {
            "status": "transport_error",
            "http_status": None,
            "error": "url_error:%s" % exc.reason,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except TimeoutError:
        return {
            "status": "timeout",
            "http_status": None,
            "error": "request_timeout",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "transport_or_decode_error",
            "http_status": None,
            "error": "%s:%s" % (type(exc).__name__, exc),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


def _execute_route(
    route_id: str,
    route: Mapping[str, Any],
    scheduler: ResourceScheduler,
    base_url: str,
    api_key: str,
    listed_models: Sequence[str],
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    request_ttl_seconds: int,
    reservation_ttl_seconds: int,
    timeout_seconds: int,
    wait_seconds: float,
) -> Dict[str, Any]:
    model_id = str(route.get("model_id") or "")
    tier = str(route.get("ram_tier") or "")
    result: Dict[str, Any] = {
        "route_id": route_id,
        "model_id": model_id,
        "provider_id": route.get("provider_id"),
        "ram_tier": tier,
    }
    if not _is_lmstudio_route(route):
        result.update({"status": "route_not_lmstudio", "error": "provider_or_interface_is_not_lmstudio"})
        return result
    if not model_id:
        result.update({"status": "route_invalid", "error": "model_id_missing"})
        return result
    if not model_is_listed(model_id, listed_models):
        result.update({"status": "model_not_listed", "error": "model_id_absent_from_live_listing"})
        return result

    explicit_estimate = route.get("estimated_peak_ram_bytes")
    bytes_required = int(explicit_estimate) if isinstance(explicit_estimate, int) and explicit_estimate > 0 else None
    decision = scheduler.acquire(
        route_id=route_id,
        tier=tier,
        bytes_required=bytes_required,
        ttl_seconds=reservation_ttl_seconds,
        owner="lmstudio_worker:%s" % os.getpid(),
        wait_seconds=wait_seconds,
    )
    result["resource_decision"] = decision.to_dict()
    if not decision.granted or decision.reservation is None:
        result.update({"status": "memory_deferred", "error": decision.reason})
        return result

    with scheduler.maintain(decision.reservation):
        chat = _chat_completion(
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            request_ttl_seconds=request_ttl_seconds,
            timeout_seconds=timeout_seconds,
        )
    result.update(chat)
    result["reservation_id"] = decision.reservation.reservation_id
    return result


def run_worker(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    try:
        policy = load_policy(Path(args.policy))
        routes = load_routes(Path(args.routes))
    except Exception as exc:
        return 2, {"status": "configuration_error", "error": str(exc), "results": []}

    endpoint = resolve_lmstudio_endpoint(
        policy,
        explicit_base_url=args.endpoint,
        execute_probe=True,
    )
    if not endpoint.get("available"):
        return 2, {
            "status": "lmstudio_unavailable",
            "error": "no_lmstudio_endpoint_responded",
            "endpoint": endpoint,
            "results": [],
        }
    if args.list:
        return 0, {
            "status": "listed",
            "endpoint": {key: endpoint.get(key) for key in ("base_url", "source", "status")},
            "model_ids": endpoint.get("model_ids", []),
            "results": [],
        }

    if not args.route_id:
        return 2, {"status": "configuration_error", "error": "at_least_one_route_id_required", "results": []}
    if not args.prompt and not args.prompt_file:
        return 2, {"status": "configuration_error", "error": "prompt_or_prompt_file_required", "results": []}
    if args.prompt_file:
        try:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        except Exception as exc:
            return 2, {"status": "configuration_error", "error": "cannot_read_prompt_file:%s" % exc, "results": []}
    else:
        prompt = str(args.prompt)

    missing = [route_id for route_id in args.route_id if route_id not in routes]
    if missing:
        return 2, {
            "status": "route_not_found",
            "error": "unknown_route_ids",
            "route_ids": missing,
            "results": [],
        }

    base_url = str(endpoint["base_url"])
    lm_cfg = policy.get("lmstudio", {})
    authoritative = _is_loopback_url(base_url) or bool(args.memory_guard_authoritative)
    if bool(lm_cfg.get("require_authoritative_memory_guard", True)) and not authoritative:
        return 2, {
            "status": "memory_guard_not_authoritative",
            "error": "bridge_endpoint_requires_guard_running_on_lmstudio_host",
            "endpoint": {"base_url": base_url, "source": endpoint.get("source")},
            "peer_action": "execute worker_lmstudio.py on the LM Studio host through the configured peer transport",
            "results": [],
        }

    scheduler = ResourceScheduler(
        policy,
        db_path=Path(args.guard_db) if args.guard_db else None,
    )
    key_env = str(lm_cfg.get("api_key_env", "LMSTUDIO_API_KEY"))
    api_key = str(os.environ.get(key_env) or lm_cfg.get("api_key_fallback_literal", "lm-studio"))
    configured_pool = max(1, int(lm_cfg.get("max_parallel_requests", 2)))
    pool_size = min(2, configured_pool, max(1, int(args.pool_size)))
    request_ttl = int(args.request_ttl_seconds if args.request_ttl_seconds is not None else lm_cfg.get("request_ttl_seconds", 1800))
    reservation_ttl = int(args.reservation_ttl_seconds if args.reservation_ttl_seconds is not None else policy.get("resource_scheduler", {}).get("reservation_ttl_seconds", 1800))
    timeout = int(args.timeout_seconds if args.timeout_seconds is not None else lm_cfg.get("request_timeout_seconds", 180))
    listed_models = list(endpoint.get("model_ids") or [])

    ordered_results: List[Optional[Dict[str, Any]]] = [None] * len(args.route_id)
    with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="lmstudio") as executor:
        futures: Dict[Future, int] = {}
        for index, route_id in enumerate(args.route_id):
            future = executor.submit(
                _execute_route,
                route_id,
                routes[route_id],
                scheduler,
                base_url,
                api_key,
                listed_models,
                prompt,
                args.system_prompt,
                args.max_tokens,
                args.temperature,
                request_ttl,
                reservation_ttl,
                timeout,
                args.wait_seconds,
            )
            futures[future] = index
        for future in as_completed(futures):
            index = futures[future]
            try:
                ordered_results[index] = future.result()
            except Exception as exc:
                route_id = args.route_id[index]
                ordered_results[index] = {
                    "route_id": route_id,
                    "status": "worker_exception",
                    "error": "%s:%s" % (type(exc).__name__, exc),
                }

    results = [item for item in ordered_results if item is not None]
    completed = sum(1 for item in results if item.get("status") == "completed")
    if completed == len(results) and results:
        status = "ok"
        exit_code = 0
    elif completed:
        status = "partial"
        exit_code = 2
    else:
        status = "failed"
        exit_code = 2
    return exit_code, {
        "schema_version": "camino_lmstudio_worker_result.v1",
        "status": status,
        "endpoint": {"base_url": base_url, "source": endpoint.get("source")},
        "pool_size": pool_size,
        "request_ttl_seconds": request_ttl,
        "reservation_ttl_seconds": reservation_ttl,
        "completed": completed,
        "requested": len(results),
        "results": results,
    }


def _safe_prompt_file(run_dir: Path, value: str) -> str:
    if not value:
        return ""
    raw = Path(value).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (run_dir / raw).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError:
        raise ValueError("prompt_file_outside_run")
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("prompt_file_missing_or_symlink")
    return str(candidate)


def _bus_args_from_job(base: argparse.Namespace, run_dir: Path, job: Mapping[str, Any]) -> argparse.Namespace:
    route_ids = job.get("route_ids")
    if isinstance(route_ids, str):
        route_values = [route_ids]
    elif isinstance(route_ids, list):
        route_values = [str(value) for value in route_ids if str(value).strip()]
    else:
        one = str(job.get("route_id") or "").strip()
        route_values = [one] if one else []
    values = dict(vars(base))
    values.update({
        "route_id": route_values,
        "prompt": str(job.get("prompt") or base.prompt or ""),
        "prompt_file": _safe_prompt_file(run_dir, str(job.get("prompt_file") or base.prompt_file or "")),
        "system_prompt": str(job.get("system_prompt") or base.system_prompt or ""),
        "max_tokens": int(job.get("max_tokens") or base.max_tokens),
        "temperature": float(job.get("temperature") if job.get("temperature") is not None else base.temperature),
        "request_ttl_seconds": job.get("request_ttl_seconds", base.request_ttl_seconds),
        "reservation_ttl_seconds": job.get("reservation_ttl_seconds", base.reservation_ttl_seconds),
        "timeout_seconds": job.get("timeout_seconds", base.timeout_seconds),
        "wait_seconds": float(job.get("wait_seconds") if job.get("wait_seconds") is not None else base.wait_seconds),
        "pool_size": min(2, max(1, int(job.get("pool_size") or base.pool_size))),
        "endpoint": str(job.get("endpoint") or base.endpoint or ""),
        "list": False,
    })
    return argparse.Namespace(**values)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _decode_json_object(text: str) -> Dict[str, Any] | None:
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _valid_external_loop(payload: Any, slot_id: str, contract: Mapping[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schema_version") != "camino_internal_loop_result.v1":
        return False
    if str(payload.get("slot_id") or "") != str(slot_id):
        return False
    if str(payload.get("evidence_scope") or "") != "external_agentic_loop":
        return False
    if str(payload.get("worker_id") or "") in {
        "", "agentic_local", "local_static", "reference_local_agentic",
    }:
        return False
    if payload.get("status") not in {"clean", "clean_no_corrections", "residual_debt"}:
        return False
    try:
        count = int(payload.get("iteration_count") or 0)
        recorded_max = int(payload.get("max_internal_loops") or 0)
        allowed_max = int(contract.get("max_iterations") or 10)
    except (TypeError, ValueError):
        return False
    iterations = payload.get("iterations")
    if (
        count < 0 or recorded_max < 1 or recorded_max > allowed_max
        or count > recorded_max or not isinstance(iterations, list)
        or len(iterations) != count
    ):
        return False
    debt = payload.get("residual_debt")
    if payload.get("status") == "residual_debt" and not debt:
        return False
    if payload.get("status") in {"clean", "clean_no_corrections"} and debt:
        return False
    return True


def _report_markdown(report: Mapping[str, Any], run_id: str, slot_id: str) -> str:
    lines = [
        "# LM Studio bridge attempt",
        "",
        "- Run: `%s`" % run_id,
        "- Slot: `%s`" % (slot_id or "unknown"),
        "- Status: `%s`" % report.get("status", "unknown"),
        "- Completed: `%s/%s`" % (report.get("completed", 0), report.get("requested", 0)),
        "- Approval authority: `false`",
        "",
        "## Routes",
        "",
    ]
    results = report.get("results") if isinstance(report.get("results"), list) else []
    if not results:
        lines.append("- No route produced real model output.")
    for item in results:
        if isinstance(item, dict):
            lines.append("- `%s`: `%s`" % (item.get("route_id", "unknown"), item.get("status", "unknown")))
    return "\n".join(lines).rstrip() + "\n"


def _write_completed_bundle(
    run_dir: Path,
    report: Dict[str, Any],
    candidate_sha: str,
    slot_id: str,
) -> Path:
    out_dir = run_dir / "13_WORKER_BUS" / "lmstudio_bridge" / "OUT" / ("lmstudio_%s" % _utc_stamp())
    out_dir.mkdir(parents=True, exist_ok=False)
    report["worker_id"] = "lmstudio_bridge"
    report["provider_id"] = "lmstudio_macbook_bridge"
    report["provider_name"] = "LM Studio guarded runtime"
    report["interface"] = "openai_compatible"
    report["cost_class"] = "local_free"
    report["role"] = "slot_scoped_local_model_auditor"
    report["slot_id"] = slot_id
    report["candidate_sha256"] = candidate_sha
    report["global_approval"] = False
    report["evidence_scope"] = "worker_output_only"
    result_path = out_dir / "result.json"
    report_path = out_dir / "lmstudio_report.md"
    _write_json(result_path, report)
    report_path.write_text(_report_markdown(report, run_dir.name, slot_id), encoding="utf-8")
    files = []
    for path in (result_path, report_path):
        files.append({"path": path.name, "sha256": _sha256_file(path), "size_bytes": path.stat().st_size})
    manifest = {
        "schema_version": "camino_a_output_manifest.v1",
        "run_id": run_dir.name,
        "stage": "lmstudio_route_audit",
        "candidate_sha256": candidate_sha,
        "files": files,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json(out_dir / "OUTPUT_MANIFEST.json", manifest)
    done = out_dir / "LMSTUDIO_OUTPUT.DONE"
    with done.open("w", encoding="utf-8") as handle:
        handle.write("DONE\n")
        handle.flush()
        os.fsync(handle.fileno())
    return out_dir


def _write_non_approving_attempt(
    run_dir: Path,
    report: Dict[str, Any],
    candidate_sha: str,
    slot_id: str,
) -> Path:
    """Persist honest negative evidence outside OUT, with no manifest/DONE."""
    attempt_dir = run_dir / "REPORTS" / "lmstudio_attempts"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    stem = "lmstudio_attempt_%s" % _utc_stamp()
    report["worker_id"] = "lmstudio_bridge"
    report["slot_id"] = slot_id
    report["candidate_sha256"] = candidate_sha
    report["global_approval"] = False
    report["accepted_evidence_eligible"] = False
    report["evidence_scope"] = "availability_or_capacity_attempt_only"
    path = attempt_dir / (stem + ".json")
    _write_json(path, report)
    (attempt_dir / (stem + ".md")).write_text(
        _report_markdown(report, run_dir.name, slot_id), encoding="utf-8",
    )
    return path


def run_bus_worker(base_args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    run_dir = Path(base_args.run).expanduser().resolve()
    if not run_dir.is_dir():
        return 2, {"status": "configuration_error", "error": "run_dir_not_found", "results": []}
    job_path = run_dir / "13_WORKER_BUS" / "lmstudio_bridge" / "IN" / "job.json"
    if not job_path.is_file() or job_path.is_symlink():
        return 2, {"status": "no_job", "error": "lmstudio_bridge_job_missing", "results": []}
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if not isinstance(job, dict):
            raise ValueError("job_not_object")
        args = _bus_args_from_job(base_args, run_dir, job)
    except Exception as exc:
        return 2, {"status": "configuration_error", "error": "invalid_bus_job:%s" % exc, "results": []}
    bound, binding = verify_candidate_binding(
        run_dir, str(job.get("candidate_sha256") or ""),
    )
    if not bound:
        return 2, {
            "status": "insufficient_evidence",
            "error": "candidate_binding_failed:%s" % binding,
            "results": [],
        }

    exit_code, report = run_worker(args)
    candidate_sha = str(job.get("candidate_sha256") or job.get("candidate_sha") or "")
    slot_id = str(job.get("slot_id") or "")
    report["context_coverage"] = dict(job.get("context_coverage") or {})
    report["slot_role"] = str(job.get("slot_role") or "")
    report["job_id"] = str(job.get("job_id") or "")
    report["run_id"] = str(job.get("run_id") or run_dir.name)
    report["internal_loop_contract"] = dict(job.get("internal_loop_contract") or {})
    real_results = [
        item for item in report.get("results", [])
        if isinstance(item, dict) and item.get("status") == "completed" and isinstance(item.get("content"), str)
    ]
    report["real_completed_results"] = len(real_results)
    contract = dict(job.get("internal_loop_contract") or {})
    if contract.get("required") is True and real_results:
        structured = []
        for item in real_results:
            payload = _decode_json_object(str(item.get("content") or ""))
            if (
                isinstance(payload, dict)
                and payload.get("corrections_applied") is not True
                and _valid_external_loop(payload.get("internal_loop"), slot_id, contract)
            ):
                structured.append(payload)
        if structured:
            selected = structured[0]
            report["internal_loop"] = selected["internal_loop"]
            report["findings"] = list(selected.get("findings") or [])
            report["summary"] = str(selected.get("summary") or "LM Studio audit completed.")
            report["tests"] = list(selected.get("tests") or [])
            report["verdict"] = str(selected.get("verdict") or "ROUND_COMPLETE")
            report["corrections_applied"] = False
        else:
            report["status"] = "insufficient_evidence"
            report["error"] = "required_external_internal_loop_missing_or_invalid"
            real_results = []
    if real_results:
        bundle = _write_completed_bundle(run_dir, report, candidate_sha, slot_id)
        report["output_bundle"] = str(bundle.relative_to(run_dir))
    else:
        attempt = _write_non_approving_attempt(run_dir, report, candidate_sha, slot_id)
        report["attempt_evidence"] = str(attempt.relative_to(run_dir))
        report["accepted_evidence_eligible"] = False
    return exit_code, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run canonical LM Studio routes with a local RAM guard")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--routes", default=str(ROUTES_PATH))
    parser.add_argument("--run", default="", help="consume the lmstudio_bridge worker-bus job from this run")
    parser.add_argument("--route-id", action="append", default=[])
    parser.add_argument("--list", action="store_true", help="list the selected LM Studio endpoint and exit")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--system-prompt", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--request-ttl-seconds", type=int, default=None)
    parser.add_argument("--reservation-ttl-seconds", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    parser.add_argument("--pool-size", type=int, default=2)
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--guard-db", default="")
    parser.add_argument("--memory-guard-authoritative", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    exit_code, report = run_bus_worker(args) if args.run else run_worker(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("LM Studio worker: %s" % report.get("status"))
        if report.get("error"):
            print("Error: %s" % report["error"])
        for item in report.get("results", []):
            print("- %s: %s" % (item.get("route_id"), item.get("status")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
