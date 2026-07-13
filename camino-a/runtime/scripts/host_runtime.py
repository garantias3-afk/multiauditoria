#!/usr/bin/env python3
"""Portable host/runtime discovery for Camino A.

This module is deliberately independent from the canonical orchestrator.  It
detects the machine that is executing the process, reports conservative memory
information, resolves LM Studio with the precedence override -> loopback ->
bridge, and exposes local Drive/peer settings without embedding machine-specific
paths in the shared canon.

The public functions accept injected environments, command runners and probe
functions so unit tests never need a real socket or a particular Mac model.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_POLICY_PATH = ROOT / "config" / "host_runtime.policy.json"
POLICY_SCHEMA_VERSION = "camino_host_runtime_policy.v1"

CommandRunner = Callable[[Sequence[str], float], str]
EndpointProbe = Callable[[str, float, str], Dict[str, Any]]


class HostRuntimeError(RuntimeError):
    """Invalid local runtime policy or discovery input."""


@dataclass(frozen=True)
class MemorySnapshot:
    total_bytes: int
    available_bytes: int
    available_fraction: float
    pressure: str
    source: str
    captured_at_epoch: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_policy(path: Optional[Path] = None) -> Dict[str, Any]:
    policy_path = Path(path or DEFAULT_POLICY_PATH).expanduser().resolve()
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HostRuntimeError("cannot_read_host_runtime_policy:%s:%s" % (policy_path, exc))
    if data.get("schema_version") != POLICY_SCHEMA_VERSION:
        raise HostRuntimeError("bad_host_runtime_policy_schema_version")
    for section in ("host_detection", "lmstudio", "drive", "peer", "resource_scheduler"):
        if not isinstance(data.get(section), dict):
            raise HostRuntimeError("host_runtime_policy_missing_section:%s" % section)
    return data


def _default_command_runner(args: Sequence[str], timeout: float) -> str:
    cp = subprocess.run(
        list(args), capture_output=True, text=True, timeout=max(0.1, float(timeout)),
        check=False,
    )
    if cp.returncode != 0:
        return ""
    return cp.stdout.strip()


def _command_text(runner: CommandRunner, args: Sequence[str], timeout: float = 2.0) -> str:
    try:
        value = runner(args, timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return ""
    except Exception:
        return ""
    return str(value or "").strip()


def _positive_int(value: Any) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def parse_vm_stat(text: str) -> Tuple[int, Dict[str, int]]:
    """Return ``(page_size, pages_by_key)`` from macOS ``vm_stat`` output."""
    page_size = 4096
    match = re.search(r"page size of\s+(\d+)\s+bytes", text or "", re.IGNORECASE)
    if match:
        page_size = _positive_int(match.group(1)) or page_size
    pages: Dict[str, int] = {}
    for raw in (text or "").splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        number = re.sub(r"[^0-9]", "", value)
        if number:
            pages[key.strip().lower()] = int(number)
    return page_size, pages


def _mac_available_bytes(vm_stat_text: str) -> int:
    page_size, pages = parse_vm_stat(vm_stat_text)
    # Conservative reclaimable set.  Wired/active/compressed pages are not
    # treated as immediately available for a new model load.
    keys = (
        "pages free",
        "pages inactive",
        "pages speculative",
    )
    return page_size * sum(max(0, pages.get(key, 0)) for key in keys)


def _sysconf_memory() -> Tuple[int, int]:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
        available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
        return max(0, total), max(0, available)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0, 0


def _pressure_free_percent(text: str) -> Optional[float]:
    match = re.search(r"free percentage\s*:\s*([0-9]+(?:\.[0-9]+)?)%", text or "", re.IGNORECASE)
    if not match:
        return None
    return max(0.0, min(100.0, float(match.group(1))))


def _system_profiler_hardware(text: str) -> Dict[str, Any]:
    """Parse the small SPHardwareDataType JSON document without localization assumptions."""
    try:
        payload = json.loads(text or "{}")
        rows = payload.get("SPHardwareDataType") if isinstance(payload, dict) else None
        row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    except (json.JSONDecodeError, TypeError, IndexError):
        row = {}
    memory_text = str(row.get("physical_memory") or "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(TB|GB|MB)", memory_text, re.IGNORECASE)
    total_bytes = 0
    if match:
        multipliers = {"MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
        total_bytes = int(float(match.group(1)) * multipliers[match.group(2).upper()])
    return {
        "total_bytes": total_bytes,
        "hardware_model": row.get("machine_model") or row.get("model_identifier"),
        "machine_name": row.get("machine_name"),
        "chip_type": row.get("chip_type"),
    }


def _pressure_total_bytes(text: str) -> int:
    match = re.search(r"system has\s+(\d+)\s*\(", text or "", re.IGNORECASE)
    return _positive_int(match.group(1)) if match else 0


def collect_memory_snapshot(
    policy: Optional[Mapping[str, Any]] = None,
    command_runner: Optional[CommandRunner] = None,
    system_name: Optional[str] = None,
    clock: Callable[[], float] = time.time,
) -> MemorySnapshot:
    """Collect a conservative, dependency-free memory snapshot."""
    runner = command_runner or _default_command_runner
    scheduler = dict((policy or {}).get("resource_scheduler", policy or {}))
    critical_fraction = float(scheduler.get("critical_available_fraction", 0.08))
    warning_fraction = float(scheduler.get("warning_available_fraction", 0.15))
    system = str(system_name or platform.system())

    total = 0
    available = 0
    source_parts: List[str] = []
    if system == "Darwin":
        total = _positive_int(_command_text(runner, ["sysctl", "-n", "hw.memsize"]))
        if total:
            source_parts.append("sysctl_hw_memsize")
        if not total:
            profiler = _system_profiler_hardware(
                _command_text(runner, ["system_profiler", "SPHardwareDataType", "-json"], timeout=5.0)
            )
            total = int(profiler.get("total_bytes") or 0)
            if total:
                source_parts.append("system_profiler_physical_memory")
        vm_text = _command_text(runner, ["vm_stat"])
        available = _mac_available_bytes(vm_text) if vm_text else 0
        if available:
            source_parts.append("vm_stat_conservative")

    fallback_total, fallback_available = _sysconf_memory()
    if not total:
        total = fallback_total
        if total:
            source_parts.append("sysconf_total")
    if not available:
        available = fallback_available
        if available:
            source_parts.append("sysconf_available")

    pressure_text = _command_text(runner, ["memory_pressure", "-Q"]) if system == "Darwin" else ""
    if not total and pressure_text:
        total = _pressure_total_bytes(pressure_text)
        if total:
            source_parts.append("memory_pressure_total")
    free_percent = _pressure_free_percent(pressure_text)
    if not available and total and free_percent is not None:
        available = int(total * free_percent / 100.0)
        source_parts.append("memory_pressure_percentage")

    if total > 0:
        available = min(max(0, available), total)
        fraction = float(available) / float(total)
        if fraction <= critical_fraction:
            pressure = "critical"
        elif fraction <= warning_fraction:
            pressure = "warning"
        else:
            pressure = "normal"
    else:
        fraction = 0.0
        pressure = "unknown"

    return MemorySnapshot(
        total_bytes=total,
        available_bytes=available,
        available_fraction=fraction,
        pressure=pressure,
        source="+".join(source_parts) if source_parts else "unavailable",
        captured_at_epoch=float(clock()),
    )


def _platform_values(platform_info: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    supplied = dict(platform_info or {})
    return {
        "system": supplied.get("system", platform.system()),
        "machine": supplied.get("machine", platform.machine()),
        "processor": supplied.get("processor", platform.processor()),
        "hostname": supplied.get("hostname", socket.gethostname()),
    }


def detect_host(
    policy: Optional[Mapping[str, Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
    command_runner: Optional[CommandRunner] = None,
    platform_info: Optional[Mapping[str, str]] = None,
    clock: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """Detect host role, native capabilities and memory without relying on names."""
    effective_policy = dict(policy or load_policy())
    env = dict(os.environ if environ is None else environ)
    runner = command_runner or _default_command_runner
    values = _platform_values(platform_info)
    is_darwin = values["system"] == "Darwin"

    hardware_model = _command_text(runner, ["sysctl", "-n", "hw.model"]) if is_darwin else ""
    profiler_hardware: Dict[str, Any] = {}
    if is_darwin and not hardware_model:
        profiler_hardware = _system_profiler_hardware(
            _command_text(runner, ["system_profiler", "SPHardwareDataType", "-json"], timeout=5.0)
        )
        hardware_model = str(profiler_hardware.get("hardware_model") or profiler_hardware.get("machine_name") or "")
    arm64_capable = _command_text(runner, ["sysctl", "-n", "hw.optional.arm64"]) if is_darwin else ""
    translated_text = _command_text(runner, ["sysctl", "-in", "sysctl.proc_translated"]) if is_darwin else ""
    translated = translated_text == "1"
    machine_lower = values["machine"].lower()
    apple_silicon = bool(is_darwin and (machine_lower in {"arm64", "aarch64"} or arm64_capable == "1"))
    if apple_silicon:
        architecture_family = "apple_silicon"
    elif machine_lower in {"x86_64", "amd64", "i386", "i686"}:
        architecture_family = "intel"
    else:
        architecture_family = machine_lower or "unknown"

    host_cfg = effective_policy.get("host_detection", {})
    role_env = str(host_cfg.get("role_env", "CAMINO_HOST_ROLE"))
    requested_role = str(env.get(role_env, "auto") or "auto").strip().lower()
    allowed_roles = set(str(x) for x in host_cfg.get("allowed_roles", ["auto", "imac", "macbook", "generic"]))
    if requested_role not in allowed_roles:
        requested_role = "auto"
    identity_text = (hardware_model + " " + values["hostname"]).lower()
    if requested_role != "auto":
        role = requested_role
        role_source = "environment"
    elif "macbook" in identity_text:
        role = "macbook"
        role_source = "hardware_model_or_hostname"
    elif "imac" in identity_text:
        role = "imac"
        role_source = "hardware_model_or_hostname"
    else:
        role = "generic"
        role_source = "portable_default"

    memory = collect_memory_snapshot(
        effective_policy, command_runner=runner, system_name=values["system"], clock=clock,
    )
    return {
        "hostname": values["hostname"],
        "system": values["system"],
        "machine": values["machine"],
        "processor": values["processor"],
        "hardware_model": hardware_model or None,
        "chip_type": profiler_hardware.get("chip_type") if profiler_hardware else None,
        "role": role,
        "role_source": role_source,
        "architecture_family": architecture_family,
        "apple_silicon": apple_silicon,
        "translated_under_rosetta": translated,
        "memory": memory.to_dict(),
    }


def _normalize_base_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "http://" + url
    return url.rstrip("/")


def _url_list(value: Any) -> List[str]:
    if isinstance(value, str):
        raw = re.split(r"[,\n]", value)
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = []
    return [url for url in (_normalize_base_url(str(x)) for x in raw) if url]


def lmstudio_candidates(
    policy: Mapping[str, Any],
    explicit_base_url: str = "",
    environ: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, str]]:
    env = dict(os.environ if environ is None else environ)
    cfg = policy.get("lmstudio", {})
    candidates: List[Dict[str, str]] = []
    if explicit_base_url:
        candidates.append({"base_url": _normalize_base_url(explicit_base_url), "source": "override"})
    env_override = str(env.get(str(cfg.get("base_url_env", "LMSTUDIO_BASE_URL")), "") or "")
    if env_override:
        candidates.append({"base_url": _normalize_base_url(env_override), "source": "override"})

    loopback_env = str(env.get(str(cfg.get("loopback_urls_env", "LMSTUDIO_LOOPBACK_URLS")), "") or "")
    loopbacks = _url_list(loopback_env) if loopback_env else _url_list(cfg.get("loopback_urls", []))
    candidates.extend({"base_url": url, "source": "loopback"} for url in loopbacks)

    bridge_env = str(env.get(str(cfg.get("bridge_urls_env", "LMSTUDIO_BRIDGE_URLS")), "") or "")
    bridges = _url_list(bridge_env) if bridge_env else _url_list(cfg.get("bridge_urls", []))
    candidates.extend({"base_url": url, "source": "bridge"} for url in bridges)

    result: List[Dict[str, str]] = []
    seen = set()
    for item in candidates:
        url = item["base_url"]
        if url and url not in seen:
            seen.add(url)
            result.append(item)
    return result


def _extract_model_ids(body: Any) -> List[str]:
    ids = set()
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        for item in body["data"]:
            if isinstance(item, dict):
                value = item.get("id") or item.get("model") or item.get("name")
                if isinstance(value, str) and value:
                    ids.add(value)
    return sorted(ids)


def probe_lmstudio_endpoint(base_url: str, timeout: float, api_key: str) -> Dict[str, Any]:
    """Probe one OpenAI-compatible LM Studio endpoint without leaking its key."""
    url = _normalize_base_url(base_url) + "/models"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=max(0.1, float(timeout))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw else {}
            models = _extract_model_ids(body)
            valid_shape = isinstance(body, dict) and isinstance(body.get("data"), list)
            return {
                "ok": bool(200 <= int(response.status) < 300 and valid_shape),
                "http_status": int(response.status),
                "error": None if valid_shape else "invalid_models_response_shape",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "model_ids": models,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "http_status": int(exc.code),
            "error": "http_%s" % exc.code,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "model_ids": [],
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "http_status": None,
            "error": "url_error:%s" % exc.reason,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "model_ids": [],
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "http_status": None,
            "error": "%s:%s" % (type(exc).__name__, exc),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "model_ids": [],
        }


def resolve_lmstudio_endpoint(
    policy: Mapping[str, Any],
    explicit_base_url: str = "",
    environ: Optional[Mapping[str, str]] = None,
    probe: Optional[EndpointProbe] = None,
    execute_probe: bool = True,
) -> Dict[str, Any]:
    """Resolve LM Studio in strict override -> loopback -> bridge order."""
    env = dict(os.environ if environ is None else environ)
    cfg = policy.get("lmstudio", {})
    candidates = lmstudio_candidates(policy, explicit_base_url, env)
    if not candidates:
        return {"status": "unconfigured", "available": False, "base_url": None, "source": None, "attempts": []}
    if not execute_probe:
        first = candidates[0]
        return {
            "status": "not_probed",
            "available": False,
            "base_url": first["base_url"],
            "source": first["source"],
            "attempts": [],
            "candidates": candidates,
        }

    timeout = float(cfg.get("probe_timeout_seconds", 2.0))
    key_env = str(cfg.get("api_key_env", "LMSTUDIO_API_KEY"))
    api_key = str(env.get(key_env) or cfg.get("api_key_fallback_literal", "lm-studio"))
    probe_fn = probe or probe_lmstudio_endpoint
    attempts: List[Dict[str, Any]] = []
    for candidate in candidates:
        try:
            result = dict(probe_fn(candidate["base_url"], timeout, api_key) or {})
        except Exception as exc:
            result = {"ok": False, "error": "probe_exception:%s:%s" % (type(exc).__name__, exc)}
        attempt = {
            "base_url": candidate["base_url"],
            "source": candidate["source"],
            "ok": bool(result.get("ok")),
            "http_status": result.get("http_status"),
            "error": result.get("error"),
            "elapsed_ms": result.get("elapsed_ms"),
            "model_ids": list(result.get("model_ids") or []),
        }
        attempts.append(attempt)
        if attempt["ok"]:
            return {
                "status": "available",
                "available": True,
                "base_url": candidate["base_url"],
                "source": candidate["source"],
                "model_ids": attempt["model_ids"],
                "attempts": attempts,
            }
    return {
        "status": "unavailable",
        "available": False,
        "base_url": None,
        "source": None,
        "model_ids": [],
        "attempts": attempts,
    }


def _env_bool(value: Any, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def resolve_drive_settings(policy: Mapping[str, Any], environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    cfg = policy.get("drive", {})
    raw = str(env.get(str(cfg.get("root_env", "CAMINO_DRIVE_BUS_ROOT"))) or cfg.get("root_default", "") or "")
    if not raw:
        if not bool(cfg.get("auto_discover", False)):
            return {"configured": False, "status": "unconfigured", "root": None, "exists": False, "writable": False}
        try:
            from scripts.drive_locator import locate_drive

            policy_path = Path(str(cfg.get("drive_policy_path") or "config/drive.policy.json"))
            if not policy_path.is_absolute():
                policy_path = ROOT / policy_path
            location = locate_drive(
                policy_path=policy_path,
                create=False,
                environ=env,
            )
        except Exception as exc:
            return {
                "configured": False,
                "status": "discovery_error",
                "root": None,
                "exists": False,
                "writable": False,
                "source": "macos_google_drive_discovery",
                "errors": ["%s:%s" % (type(exc).__name__, exc)],
            }
        if location.ready:
            status = "ok"
        elif location.errors:
            status = "discovery_failed_closed"
        elif location.shared_root_exists:
            status = "bus_missing"
        else:
            status = "unconfigured"
        return {
            "configured": bool(location.shared_root),
            "status": status,
            "root": location.bus_root,
            "exists": location.bus_root_exists,
            "writable": location.shared_root_writable,
            "source": location.source,
            "shared_root": location.shared_root,
            "warnings": list(location.warnings),
            "errors": list(location.errors),
        }
    root = Path(raw).expanduser()
    exists = root.is_dir()
    writable = bool(exists and os.access(str(root), os.W_OK))
    if bool(cfg.get("require_existing")) and not exists:
        status = "missing"
    elif bool(cfg.get("require_writable")) and not writable:
        status = "not_writable"
    else:
        status = "ok" if exists else "configured_not_checked"
    return {"configured": True, "status": status, "root": str(root), "exists": exists, "writable": writable}


def resolve_peer_settings(
    policy: Mapping[str, Any],
    environ: Optional[Mapping[str, str]] = None,
    local_role: str = "",
) -> Dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    cfg = policy.get("peer", {})
    enabled = _env_bool(env.get(str(cfg.get("enabled_env", "CAMINO_PEER_ENABLED"))), bool(cfg.get("default_enabled", False)))
    url = str(env.get(str(cfg.get("url_env", "CAMINO_PEER_URL")), "") or "").strip()
    role_key = str(local_role or "generic")
    role_hosts = cfg.get("ssh_hosts_by_local_role", {})
    role_peers = cfg.get("peer_roles_by_local_role", {})
    identity_files = cfg.get("ssh_identity_files_by_local_role", {})
    ssh_host = str(
        env.get(str(cfg.get("ssh_host_env", "CAMINO_PEER_SSH_HOST")), "")
        or (role_hosts.get(role_key) if isinstance(role_hosts, dict) else "")
        or ""
    ).strip()
    role = str(
        env.get(str(cfg.get("role_env", "CAMINO_PEER_ROLE")), "")
        or (role_peers.get(role_key) if isinstance(role_peers, dict) else "")
        or ""
    ).strip()
    identity_file = str(
        env.get(str(cfg.get("ssh_identity_file_env", "CAMINO_PEER_SSH_IDENTITY")), "")
        or (identity_files.get(role_key) if isinstance(identity_files, dict) else "")
        or ""
    ).strip()
    remote_root = str(
        env.get(str(cfg.get("remote_root_env", "CAMINO_PEER_REMOTE_ROOT")), "")
        or cfg.get("remote_root_default", ".camino/peer-runtime")
        or ""
    ).strip()
    remote_python = str(
        env.get(str(cfg.get("python_env", "CAMINO_PEER_PYTHON")), "")
        or cfg.get("python_default", "python3")
        or "python3"
    ).strip()
    configured = bool(url or ssh_host)
    if enabled and not configured:
        status = "enabled_but_unconfigured"
    elif enabled:
        status = "configured_not_probed"
    else:
        status = "disabled"
    return {
        "enabled": enabled,
        "configured": configured,
        "status": status,
        "transport": str(cfg.get("transport", "ssh")),
        "url": url or None,
        "ssh_host": ssh_host or None,
        "ssh_identity_file": str(Path(identity_file).expanduser()) if identity_file else None,
        "ssh_identity_exists": bool(identity_file and Path(identity_file).expanduser().is_file()),
        "remote_root": remote_root,
        "python": remote_python,
        "role": role or None,
        "connect_timeout_seconds": int(cfg.get("connect_timeout_seconds", 5)),
        "command_timeout_seconds": int(cfg.get("command_timeout_seconds", 900)),
    }


def build_runtime_report(
    policy: Optional[Mapping[str, Any]] = None,
    explicit_lmstudio_base_url: str = "",
    environ: Optional[Mapping[str, str]] = None,
    command_runner: Optional[CommandRunner] = None,
    platform_info: Optional[Mapping[str, str]] = None,
    probe: Optional[EndpointProbe] = None,
    execute_lmstudio_probe: bool = True,
) -> Dict[str, Any]:
    effective_policy = dict(policy or load_policy())
    env = dict(os.environ if environ is None else environ)
    host = detect_host(effective_policy, env, command_runner, platform_info)
    return {
        "schema_version": "camino_host_runtime_report.v1",
        "host": host,
        "lmstudio": resolve_lmstudio_endpoint(
            effective_policy, explicit_lmstudio_base_url, env, probe, execute_lmstudio_probe,
        ),
        "drive": resolve_drive_settings(effective_policy, env),
        "peer": resolve_peer_settings(effective_policy, env, str(host.get("role") or "")),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Detect Camino host capabilities and LM Studio topology")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--lmstudio-base-url", default="")
    parser.add_argument("--no-lmstudio-probe", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit one machine-readable JSON report")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        policy = load_policy(Path(args.policy))
        report = build_runtime_report(
            policy,
            explicit_lmstudio_base_url=args.lmstudio_base_url,
            execute_lmstudio_probe=not args.no_lmstudio_probe,
        )
    except HostRuntimeError as exc:
        error = {"schema_version": "camino_host_runtime_report.v1", "status": "configuration_error", "error": str(exc)}
        print(json.dumps(error, ensure_ascii=False, indent=2))
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        host = report["host"]
        lm = report["lmstudio"]
        memory = host["memory"]
        print("Host: %s (%s, %s)" % (host["hostname"], host["role"], host["architecture_family"]))
        print("RAM: %.1f/%.1f GiB available; pressure=%s" % (
            memory["available_bytes"] / float(1024 ** 3), memory["total_bytes"] / float(1024 ** 3), memory["pressure"],
        ))
        print("LM Studio: %s%s" % (lm["status"], " at " + str(lm.get("base_url")) if lm.get("base_url") else ""))
        print("Drive: %s" % report["drive"]["status"])
        print("Peer: %s" % report["peer"]["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
