#!/usr/bin/env python3
"""probe_live_routes.py — D1 live route listing/probe for Camino A.

Purpose
-------
Resolve D1 honestly: routes marked as `probe_required`,
`model_id_requires_live_listing`, or `fallback_requires_live_listing` need a
live provider check before anybody treats the model_id as available.

Safety contract
---------------
- Default mode is dry/runless inventory. No network call happens unless
  `--execute` is passed.
- Claude API and OpenAI API providers are hard-blocked from canon/runtime/policy
  and from conservative URL/name heuristics.
- API keys are never printed, persisted or included in reports.
- Missing credentials, missing project config, network errors and auth failures
  are explicit statuses, not availability.
- Active chat probes can cost money, so they require both `--execute` and
  `--active-probe`. Paid/non-free active probes additionally require
  `--allow-paid`.

Supported live checks
---------------------
- OpenRouter: GET /models, optional POST /chat/completions active probe.
- Blackbox OpenAI-compatible endpoint: GET /models, optional POST
  /chat/completions active probe.
- LM Studio OpenAI-compatible endpoint over the MacBook Thunderbolt bridge:
  GET /models, optional POST /chat/completions active probe.
- Google AI Studio Gemini Developer API: GET v1beta/models, optional
  generateContent active probe.
- Google Vertex AI publisher models: REST listing with ADC/gcloud token or an
  explicit access-token env var; optional generateContent active probe.

This script intentionally does not install SDKs; it uses only stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canon_loader import load_canon, read_json  # noqa: E402
from scripts.host_runtime import load_policy as load_host_policy, resolve_lmstudio_endpoint  # noqa: E402

PENDING_STATUSES = {
    "probe_required",
    "model_id_requires_live_listing",
    "fallback_requires_live_listing",
}

DEFAULT_FORBIDDEN_PROVIDERS = {
    "openai_api",
    "anthropic_api",
    "claude_api",
}
DEFAULT_FORBIDDEN_ENV_VARS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
}
FORBIDDEN_NAME_TOKENS = ("openai api", "api.openai.com", "anthropic", "claude api")

DEFAULT_ENDPOINTS = {
    "openrouter": os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    "blackbox": os.environ.get("BLACKBOX_BASE_URL", "https://api.blackbox.ai/v1"),
    "lmstudio": os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
    "lmstudio_api_key": os.environ.get("LMSTUDIO_API_KEY", "lm-studio"),
    "gemini": os.environ.get("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
    "vertex_location": os.environ.get("VERTEX_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1",
}


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status: int | None
    body: Any
    error: str | None
    elapsed_ms: int


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_provider_policy(root: Path) -> dict[str, Any]:
    p = root / "config" / "provider.policy.json"
    return read_json(p) if p.exists() else {}


def forbidden_sets(root: Path) -> tuple[set[str], set[str]]:
    policy = load_provider_policy(root)
    providers = set(policy.get("forbidden_providers") or []) | DEFAULT_FORBIDDEN_PROVIDERS
    envs = DEFAULT_FORBIDDEN_ENV_VARS
    try:
        bundle = load_canon(root)
        api = bundle.runtime_policy.get("api_policy", {})
        providers |= set(api.get("forbidden_api_providers") or [])
        envs |= set(api.get("forbidden_env_vars_for_workers") or [])
    except Exception:
        # The probe script must be able to report canon failures separately.
        pass
    return providers, envs


def route_forbidden(route: dict[str, Any], forbidden_providers: set[str]) -> tuple[bool, str]:
    provider_id = str(route.get("provider_id", "")).lower()
    provider_name = str(route.get("provider_name", "")).lower()
    route_name = str(route.get("route", "")).lower()
    model_id = str(route.get("model_id", "")).lower()
    route_id = str(route.get("route_id", "")).lower()

    if provider_id in forbidden_providers:
        return True, f"forbidden_provider_id:{provider_id}"
    # Conservative defense-in-depth. Model strings may contain `openai/` on
    # non-OpenAI providers (e.g. Groq/OpenRouter gpt-oss); do NOT ban those by
    # model_id alone. Ban only provider/route/url identities that are the API.
    haystack = " ".join([provider_id, provider_name, route_name, route_id])
    for token in FORBIDDEN_NAME_TOKENS:
        if token in haystack:
            return True, f"forbidden_provider_token:{token}"
    return False, ""


def pending_routes(root: Path) -> list[dict[str, Any]]:
    bundle = load_canon(root)
    out: list[dict[str, Any]] = []
    for rid, route in sorted((bundle.routes.get("routes") or {}).items()):
        status = str(route.get("status") or "")
        if status in PENDING_STATUSES:
            r = dict(route)
            r["route_id"] = rid
            out.append(r)
    return out


def env_present(names: Iterable[str]) -> str | None:
    for n in names:
        if os.environ.get(n):
            return n
    return None


def env_value(names: Iterable[str]) -> tuple[str | None, str | None]:
    for n in names:
        v = os.environ.get(n)
        if v:
            return n, v
    return None, None


def http_json(method: str, url: str, *, token: str | None = None,
              api_key_header: str | None = None, body: dict[str, Any] | None = None,
              timeout: int = 20, extra_headers: dict[str, str] | None = None) -> HttpResult:
    start = time.time()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key_header:
        name, value = api_key_header.split(":", 1)
        headers[name] = value
    if extra_headers:
        headers.update(extra_headers)
    raw = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=raw, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(text) if text else {}
            except json.JSONDecodeError:
                parsed = {"non_json_preview": text[:500]}
            return HttpResult(True, int(resp.status), parsed, None, int((time.time() - start) * 1000))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")[:500]
        return HttpResult(False, int(exc.code), {"body_preview": text}, f"http_{exc.code}", int((time.time() - start) * 1000))
    except urllib.error.URLError as exc:
        return HttpResult(False, None, {}, f"url_error:{exc.reason}", int((time.time() - start) * 1000))
    except Exception as exc:
        return HttpResult(False, None, {}, f"{type(exc).__name__}:{exc}", int((time.time() - start) * 1000))


def route_family(route: dict[str, Any]) -> str:
    provider_id = str(route.get("provider_id", "")).lower()
    route_name = str(route.get("route", "")).lower()
    provider_name = str(route.get("provider_name", "")).lower()
    if provider_id.startswith("openrouter") or route_name == "openrouter":
        return "openrouter"
    if provider_id.startswith("blackbox") or "blackbox" in provider_name or route_name.startswith("blackbox"):
        return "blackbox"
    if provider_id.startswith("lmstudio") or route_name.startswith("lmstudio") or "lm studio" in provider_name:
        return "lmstudio"
    if provider_id.startswith("gemini_aistudio") or "ai studio" in provider_name or "google_ai_studio" in route_name or "gemini_developer" in route_name:
        return "gemini"
    if provider_id.startswith("vertex") or "vertex" in provider_name or route_name.startswith("vertex"):
        return "vertex"
    return "unknown"


def model_variants(model_id: str) -> set[str]:
    m = model_id.strip()
    variants = {m, m.lower()}
    if "/" in m:
        variants.add(m.split("/")[-1])
        variants.add(m.split("/")[-1].lower())
    if not m.startswith("models/"):
        variants.add("models/" + m)
        variants.add(("models/" + m).lower())
    return variants


def extract_model_ids(body: Any, family: str) -> set[str]:
    ids: set[str] = set()
    if isinstance(body, dict):
        data = body.get("data") if family in {"openrouter", "blackbox", "lmstudio"} else body.get("models")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                for key in ("id", "name", "model"):
                    val = item.get(key)
                    if isinstance(val, str) and val:
                        ids.add(val)
                        ids.add(val.lower())
                        if "/" in val:
                            ids.add(val.split("/")[-1])
                            ids.add(val.split("/")[-1].lower())
    return ids


def has_model(model_id: str, listed: set[str]) -> bool:
    return bool(model_variants(model_id) & listed)


def list_openrouter(timeout: int) -> dict[str, Any]:
    key_name, key = env_value(["OPENROUTER_API_KEY"])
    headers = {"HTTP-Referer": "https://chatgpt.local/camino-a", "X-Title": "Camino A D1 Probe"}
    r = http_json("GET", DEFAULT_ENDPOINTS["openrouter"].rstrip("/") + "/models",
                  token=key, timeout=timeout, extra_headers=headers)
    return {
        "provider_family": "openrouter",
        "credential_env_present": key_name,
        "listing_ok": r.ok,
        "http_status": r.status,
        "error": r.error,
        "elapsed_ms": r.elapsed_ms,
        "model_ids": sorted(extract_model_ids(r.body, "openrouter")) if r.ok else [],
    }


def list_blackbox(timeout: int) -> dict[str, Any]:
    key_name, key = env_value(["BLACKBOX_API_KEY", "BLACKBOX_TOKEN"])
    if not key:
        return {"provider_family": "blackbox", "credential_env_present": None,
                "listing_ok": False, "error": "missing_credential:BLACKBOX_API_KEY"}
    r = http_json("GET", DEFAULT_ENDPOINTS["blackbox"].rstrip("/") + "/models",
                  token=key, timeout=timeout)
    return {
        "provider_family": "blackbox",
        "credential_env_present": key_name,
        "listing_ok": r.ok,
        "http_status": r.status,
        "error": r.error,
        "elapsed_ms": r.elapsed_ms,
        "model_ids": sorted(extract_model_ids(r.body, "blackbox")) if r.ok else [],
    }


def list_lmstudio(timeout: int) -> dict[str, Any]:
    explicit = os.environ.get("LMSTUDIO_BASE_URL", "")
    resolved = resolve_lmstudio_endpoint(
        load_host_policy(), explicit_base_url=explicit, execute_probe=True,
    )
    attempts = list(resolved.get("attempts") or [])
    last = attempts[-1] if attempts else {}
    return {
        "provider_family": "lmstudio",
        "credential_env_present": "LMSTUDIO_API_KEY" if os.environ.get("LMSTUDIO_API_KEY") else "literal:lm-studio",
        "listing_ok": bool(resolved.get("available")),
        "http_status": last.get("http_status"),
        "error": None if resolved.get("available") else (last.get("error") or "all_host_runtime_candidates_failed"),
        "elapsed_ms": sum(int(item.get("elapsed_ms") or 0) for item in attempts),
        "base_url": resolved.get("base_url"),
        "endpoint_source": resolved.get("source"),
        "attempts": attempts,
        "model_ids": sorted(resolved.get("model_ids") or []),
    }


def list_gemini(timeout: int) -> dict[str, Any]:
    key_name, key = env_value(["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_STUDIO_API_KEY"])
    if not key:
        return {"provider_family": "gemini", "credential_env_present": None,
                "listing_ok": False, "error": "missing_credential:GEMINI_API_KEY|GOOGLE_API_KEY"}
    url = DEFAULT_ENDPOINTS["gemini"].rstrip("/") + "/models?" + urllib.parse.urlencode({"key": key})
    r = http_json("GET", url, timeout=timeout)
    return {
        "provider_family": "gemini",
        "credential_env_present": key_name,
        "listing_ok": r.ok,
        "http_status": r.status,
        "error": r.error,
        "elapsed_ms": r.elapsed_ms,
        "model_ids": sorted(extract_model_ids(r.body, "gemini")) if r.ok else [],
    }


def gcloud_access_token(timeout: int) -> tuple[str | None, str | None]:
    name, token = env_value(["VERTEX_ACCESS_TOKEN", "GOOGLE_OAUTH_ACCESS_TOKEN", "GCLOUD_ACCESS_TOKEN"])
    if token:
        return name, token
    if not shutil.which("gcloud"):
        return None, None
    try:
        cp = subprocess.run(["gcloud", "auth", "print-access-token"],
                            check=False, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    except Exception:
        return None, None
    tok = cp.stdout.strip()
    if cp.returncode == 0 and tok:
        return "gcloud_auth_print_access_token", tok
    return None, None


def list_vertex(timeout: int) -> dict[str, Any]:
    project = (os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
               or os.environ.get("GCLOUD_PROJECT") or os.environ.get("GCP_PROJECT"))
    location = DEFAULT_ENDPOINTS["vertex_location"]
    token_source, token = gcloud_access_token(timeout)
    if not project:
        return {"provider_family": "vertex", "credential_env_present": token_source,
                "listing_ok": False, "error": "missing_project:VERTEX_PROJECT|GOOGLE_CLOUD_PROJECT",
                "location": location}
    if not token:
        return {"provider_family": "vertex", "credential_env_present": None,
                "listing_ok": False, "error": "missing_adc_or_access_token",
                "project": project, "location": location}
    url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/"
           f"{urllib.parse.quote(project)}/locations/{urllib.parse.quote(location)}"
           "/publishers/google/models")
    r = http_json("GET", url, token=token, timeout=timeout)
    return {
        "provider_family": "vertex",
        "credential_env_present": token_source,
        "listing_ok": r.ok,
        "http_status": r.status,
        "error": r.error,
        "elapsed_ms": r.elapsed_ms,
        "project": project,
        "location": location,
        "model_ids": sorted(extract_model_ids(r.body, "gemini")) if r.ok else [],
    }


def active_probe(route: dict[str, Any], family: str, timeout: int, allow_paid: bool) -> dict[str, Any]:
    model = str(route.get("model_id") or "")
    cost_class = str(route.get("cost_class") or "")
    if not allow_paid and not any(x in cost_class for x in ("free", "quota", "credit", "plan")):
        return {"active_probe_ok": False, "error": "paid_probe_requires_allow_paid"}
    if family in {"openrouter", "blackbox", "lmstudio"}:
        if family == "openrouter":
            key_names = ["OPENROUTER_API_KEY"]
            key_name, key = env_value(key_names)
            if not key:
                return {"active_probe_ok": False, "error": f"missing_credential:{'|'.join(key_names)}"}
        elif family == "blackbox":
            key_names = ["BLACKBOX_API_KEY", "BLACKBOX_TOKEN"]
            key_name, key = env_value(key_names)
            if not key:
                return {"active_probe_ok": False, "error": f"missing_credential:{'|'.join(key_names)}"}
        else:
            key_name, key = ("LMSTUDIO_API_KEY", os.environ["LMSTUDIO_API_KEY"]) if os.environ.get("LMSTUDIO_API_KEY") else ("literal:lm-studio", DEFAULT_ENDPOINTS["lmstudio_api_key"])
        if family == "lmstudio":
            resolved = resolve_lmstudio_endpoint(
                load_host_policy(),
                explicit_base_url=os.environ.get("LMSTUDIO_BASE_URL", ""),
                execute_probe=True,
            )
            if not resolved.get("available"):
                return {"active_probe_ok": False, "error": "lmstudio_unavailable",
                        "attempts": resolved.get("attempts", [])}
            base = str(resolved["base_url"]).rstrip("/")
        else:
            base = DEFAULT_ENDPOINTS[family].rstrip("/")
        body = {"model": model, "messages": [{"role": "user", "content": "pong"}], "max_tokens": 1, "temperature": 0}
        r = http_json("POST", base + "/chat/completions", token=key, body=body, timeout=timeout)
        return {"active_probe_ok": r.ok, "http_status": r.status, "error": r.error,
                "elapsed_ms": r.elapsed_ms, "credential_env_present": key_name}
    if family == "gemini":
        key_name, key = env_value(["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_STUDIO_API_KEY"])
        if not key:
            return {"active_probe_ok": False, "error": "missing_credential:GEMINI_API_KEY|GOOGLE_API_KEY"}
        model_name = model if model.startswith("models/") else "models/" + model
        url = DEFAULT_ENDPOINTS["gemini"].rstrip("/") + f"/{model_name}:generateContent?" + urllib.parse.urlencode({"key": key})
        body = {"contents": [{"parts": [{"text": "pong"}]}], "generationConfig": {"maxOutputTokens": 1, "temperature": 0}}
        r = http_json("POST", url, body=body, timeout=timeout)
        return {"active_probe_ok": r.ok, "http_status": r.status, "error": r.error,
                "elapsed_ms": r.elapsed_ms, "credential_env_present": key_name}
    if family == "vertex":
        project = (os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
                   or os.environ.get("GCLOUD_PROJECT") or os.environ.get("GCP_PROJECT"))
        location = DEFAULT_ENDPOINTS["vertex_location"]
        token_source, token = gcloud_access_token(timeout)
        if not project:
            return {"active_probe_ok": False, "error": "missing_project:VERTEX_PROJECT|GOOGLE_CLOUD_PROJECT"}
        if not token:
            return {"active_probe_ok": False, "error": "missing_adc_or_access_token"}
        model_name = urllib.parse.quote(model, safe="")
        url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{urllib.parse.quote(project)}"
               f"/locations/{urllib.parse.quote(location)}/publishers/google/models/{model_name}:generateContent")
        body = {"contents": [{"role": "user", "parts": [{"text": "pong"}]}],
                "generationConfig": {"maxOutputTokens": 1, "temperature": 0}}
        r = http_json("POST", url, token=token, body=body, timeout=timeout)
        return {"active_probe_ok": r.ok, "http_status": r.status, "error": r.error,
                "elapsed_ms": r.elapsed_ms, "credential_env_present": token_source,
                "project": project, "location": location}
    return {"active_probe_ok": False, "error": f"unsupported_family:{family}"}


def write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        f"# D1 live route probe report — {report['schema_version']}",
        "",
        f"- generated_utc: `{report['generated_utc']}`",
        f"- execute: `{report['execute']}`",
        f"- active_probe: `{report['active_probe']}`",
        f"- allow_paid: `{report['allow_paid']}`",
        f"- pending_routes: `{report['summary']['pending_routes']}`",
        f"- listed_available: `{report['summary']['listed_available']}`",
        f"- active_probe_ok: `{report['summary']['active_probe_ok']}`",
        f"- blocked_forbidden: `{report['summary']['blocked_forbidden']}`",
        f"- missing_credentials_or_config: `{report['summary']['missing_credentials_or_config']}`",
        f"- errors: `{report['summary']['errors']}`",
        "",
        "## Provider listing results",
        "",
    ]
    for fam, item in sorted(report.get("provider_listings", {}).items()):
        lines += [
            f"### {fam}",
            "",
            f"- listing_ok: `{item.get('listing_ok')}`",
            f"- http_status: `{item.get('http_status')}`",
            f"- error: `{item.get('error')}`",
            f"- credential_env_present: `{item.get('credential_env_present')}`",
            f"- model_count: `{len(item.get('model_ids') or [])}`",
            "",
        ]
    lines += ["## Route decisions", ""]
    for r in report.get("routes", []):
        lines += [
            f"### {r['route_id']}",
            "",
            f"- provider_id: `{r.get('provider_id')}`",
            f"- model_id: `{r.get('model_id')}`",
            f"- source_status: `{r.get('source_status')}`",
            f"- family: `{r.get('family')}`",
            f"- decision: `{r.get('decision')}`",
            f"- reason: `{r.get('reason')}`",
            f"- active_probe_ok: `{(r.get('active_probe') or {}).get('active_probe_ok')}`",
            "",
        ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_report(root: Path, execute: bool, active: bool, allow_paid: bool, timeout: int) -> dict[str, Any]:
    routes = pending_routes(root)
    forbidden_providers, forbidden_envs = forbidden_sets(root)
    env_forbidden_present = sorted(name for name in forbidden_envs if os.environ.get(name))
    report: dict[str, Any] = {
        "schema_version": "camino_a_d1_live_route_probe.v1",
        "generated_utc": utc_now(),
        "root": str(root),
        "execute": execute,
        "active_probe": active,
        "allow_paid": allow_paid,
        "forbidden_providers": sorted(forbidden_providers),
        "forbidden_env_vars_present": env_forbidden_present,
        "provider_listings": {},
        "routes": [],
        "summary": {},
    }
    if env_forbidden_present:
        # Do not fail the whole script: report and still avoid those APIs. The
        # preflight may be stricter; this script is an audit/probe tool.
        report["forbidden_env_note"] = "Forbidden env vars are present but will not be used."

    families_needed = sorted({route_family(r) for r in routes})
    if execute:
        for fam in families_needed:
            if fam == "openrouter":
                report["provider_listings"][fam] = list_openrouter(timeout)
            elif fam == "blackbox":
                report["provider_listings"][fam] = list_blackbox(timeout)
            elif fam == "lmstudio":
                report["provider_listings"][fam] = list_lmstudio(timeout)
            elif fam == "gemini":
                report["provider_listings"][fam] = list_gemini(timeout)
            elif fam == "vertex":
                report["provider_listings"][fam] = list_vertex(timeout)
            else:
                report["provider_listings"][fam] = {"provider_family": fam, "listing_ok": False, "error": "unsupported_family"}
    else:
        for fam in families_needed:
            report["provider_listings"][fam] = {"provider_family": fam, "listing_ok": False, "error": "dry_run_no_external_call"}

    for route in routes:
        family = route_family(route)
        blocked, block_reason = route_forbidden(route, forbidden_providers)
        listing = report["provider_listings"].get(family, {})
        listed = set(listing.get("model_ids") or [])
        model_id = str(route.get("model_id") or "")
        row = {
            "route_id": route.get("route_id"),
            "provider_id": route.get("provider_id"),
            "provider_name": route.get("provider_name"),
            "model_id": model_id,
            "source_status": route.get("status"),
            "cost_class": route.get("cost_class"),
            "family": family,
        }
        if blocked:
            row.update({"decision": "blocked_forbidden", "reason": block_reason})
        elif not execute:
            row.update({"decision": "pending_not_executed", "reason": "dry_run"})
        elif not listing.get("listing_ok"):
            err = str(listing.get("error") or "listing_failed")
            if err.startswith("missing_"):
                decision = "missing_credentials_or_config"
            else:
                decision = "listing_error"
            row.update({"decision": decision, "reason": err})
        elif has_model(model_id, listed):
            row.update({"decision": "listed_available", "reason": "model_id_found_in_live_listing"})
        else:
            row.update({"decision": "not_found_in_listing", "reason": "model_id_absent_from_live_listing"})

        if active and execute and not blocked and row["decision"] in {"listed_available", "not_found_in_listing", "listing_error", "missing_credentials_or_config"}:
            ap = active_probe(route, family, timeout, allow_paid)
            row["active_probe"] = ap
            if ap.get("active_probe_ok"):
                row["decision"] = "active_probe_ok"
                row["reason"] = "model_responded_to_minimal_generation_probe"
        report["routes"].append(row)

    summary = {
        "pending_routes": len(routes),
        "listed_available": sum(1 for r in report["routes"] if r.get("decision") == "listed_available"),
        "active_probe_ok": sum(1 for r in report["routes"] if r.get("decision") == "active_probe_ok"),
        "blocked_forbidden": sum(1 for r in report["routes"] if r.get("decision") == "blocked_forbidden"),
        "missing_credentials_or_config": sum(1 for r in report["routes"] if r.get("decision") == "missing_credentials_or_config"),
        "not_found_in_listing": sum(1 for r in report["routes"] if r.get("decision") == "not_found_in_listing"),
        "errors": sum(1 for r in report["routes"] if r.get("decision") in {"listing_error"}),
        "pending_not_executed": sum(1 for r in report["routes"] if r.get("decision") == "pending_not_executed"),
    }
    report["summary"] = summary
    return report


def self_test() -> int:
    assert has_model("gemini-3.1-pro", {"models/gemini-3.1-pro"})
    assert has_model("nvidia/foo:free", {"nvidia/foo:free"})
    assert has_model("blackboxai/mistral/devstral-2", {"devstral-2", "x"})
    assert route_family({"provider_id": "openrouter_free", "route": "openrouter"}) == "openrouter"
    assert route_family({"provider_id": "vertex_gemini_3", "route": "vertex_adc"}) == "vertex"
    assert route_family({"provider_id": "lmstudio_macbook_bridge", "route": "lmstudio_openai_compatible"}) == "lmstudio"
    blocked, why = route_forbidden({"provider_id": "openai_api", "route_id": "x"}, {"openai_api"})
    assert blocked and why.startswith("forbidden_provider_id")
    not_blocked, _ = route_forbidden({"provider_id": "groq_gpt_oss_120b", "model_id": "openai/gpt-oss-120b", "route": "groq_api"}, {"openai_api"})
    assert not not_blocked
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D1 live route listing/probe for Camino A")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--execute", action="store_true", help="perform external listing calls")
    parser.add_argument("--active-probe", action="store_true", help="perform minimal generation probes where possible")
    parser.add_argument("--allow-paid", action="store_true", help="allow active probes for paid/intermediate routes")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    report = build_report(root, args.execute, args.active_probe, args.allow_paid, args.timeout)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else root / "reports"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"D1_LIVE_ROUTE_PROBE_{stamp}.json"
    md_path = out_dir / f"D1_LIVE_ROUTE_PROBE_{stamp}.md"
    json_dump(json_path, report)
    write_markdown_report(md_path, report)
    result = {"json": str(json_path), "markdown": str(md_path), "summary": report["summary"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Exit non-zero only if forbidden route would have been probed. Missing keys
    # are expected operational information and should not break validation.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
