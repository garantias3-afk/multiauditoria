from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.host_runtime import (
    build_runtime_report,
    collect_memory_snapshot,
    detect_host,
    lmstudio_candidates,
    parse_vm_stat,
    resolve_drive_settings,
    resolve_lmstudio_endpoint,
    resolve_peer_settings,
)


GIB = 1024 ** 3
ROOT = Path(__file__).resolve().parents[1]


def policy():
    return {
        "schema_version": "camino_host_runtime_policy.v1",
        "host_detection": {
            "role_env": "CAMINO_HOST_ROLE",
            "allowed_roles": ["auto", "imac", "macbook", "generic"],
        },
        "lmstudio": {
            "base_url_env": "LMSTUDIO_BASE_URL",
            "loopback_urls_env": "LMSTUDIO_LOOPBACK_URLS",
            "bridge_urls_env": "LMSTUDIO_BRIDGE_URLS",
            "loopback_urls": ["http://127.0.0.1:1234/v1", "http://localhost:1234/v1"],
            "bridge_urls": ["http://10.0.0.1:1234/v1"],
            "api_key_env": "LMSTUDIO_API_KEY",
            "api_key_fallback_literal": "lm-studio",
            "probe_timeout_seconds": 0.1,
        },
        "drive": {
            "root_env": "CAMINO_DRIVE_BUS_ROOT",
            "root_default": "",
            "require_existing": False,
            "require_writable": False,
        },
        "peer": {
            "enabled_env": "CAMINO_PEER_ENABLED",
            "url_env": "CAMINO_PEER_URL",
            "ssh_host_env": "CAMINO_PEER_SSH_HOST",
            "role_env": "CAMINO_PEER_ROLE",
            "default_enabled": False,
            "transport": "ssh",
            "connect_timeout_seconds": 5,
        },
        "resource_scheduler": {
            "critical_available_fraction": 0.08,
            "warning_available_fraction": 0.15,
        },
    }


def command_runner(responses):
    def run(args, timeout):
        return responses.get(tuple(args), "")

    return run


def test_parse_vm_stat_uses_declared_page_size():
    text = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100.
Pages inactive:                           200.
"""
    page_size, pages = parse_vm_stat(text)
    assert page_size == 16384
    assert pages["pages free"] == 100
    assert pages["pages inactive"] == 200


def test_memory_pressure_supplies_total_when_sysctl_is_restricted():
    responses = {
        ("sysctl", "-n", "hw.memsize"): "",
        ("vm_stat",): "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 1048576.\n",
        ("memory_pressure", "-Q"): (
            "The system has 8589934592 (2097152 pages with a page size of 4096).\n"
            "System-wide memory free percentage: 50%"
        ),
    }
    snapshot = collect_memory_snapshot(
        policy(), command_runner=command_runner(responses), system_name="Darwin", clock=lambda: 1.0,
    )
    assert snapshot.total_bytes == 8 * GIB
    assert snapshot.available_bytes == 4 * GIB
    assert snapshot.available_fraction == 0.5
    assert snapshot.pressure == "normal"


def test_detects_native_apple_silicon_macbook_and_memory():
    responses = {
        ("sysctl", "-n", "hw.model"): "MacBookPro18,3",
        ("sysctl", "-n", "hw.optional.arm64"): "1",
        ("sysctl", "-in", "sysctl.proc_translated"): "0",
        ("sysctl", "-n", "hw.memsize"): str(16 * GIB),
        ("vm_stat",): """Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free: 1048576.
Pages inactive: 1048576.
Pages speculative: 262144.
Pages purgeable: 262144.
""",
        ("memory_pressure", "-Q"): "System-wide memory free percentage: 62%",
    }
    result = detect_host(
        policy(),
        environ={},
        command_runner=command_runner(responses),
        platform_info={"system": "Darwin", "machine": "arm64", "processor": "arm", "hostname": "portable"},
        clock=lambda: 123.0,
    )
    assert result["role"] == "macbook"
    assert result["apple_silicon"] is True
    assert result["architecture_family"] == "apple_silicon"
    assert result["translated_under_rosetta"] is False
    assert result["memory"]["total_bytes"] == 16 * GIB
    # Purgeable is intentionally not added because macOS may report it as a
    # subset of another page class; the guard must not double-count capacity.
    assert result["memory"]["available_bytes"] == 9 * GIB
    assert result["memory"]["pressure"] == "normal"


def test_detects_rosetta_and_explicit_host_role():
    responses = {
        ("sysctl", "-n", "hw.model"): "MacBookPro18,3",
        ("sysctl", "-n", "hw.optional.arm64"): "1",
        ("sysctl", "-in", "sysctl.proc_translated"): "1",
        ("sysctl", "-n", "hw.memsize"): str(8 * GIB),
        ("vm_stat",): "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 1048576.\n",
        ("memory_pressure", "-Q"): "System-wide memory free percentage: 50%",
    }
    result = detect_host(
        policy(),
        environ={"CAMINO_HOST_ROLE": "imac"},
        command_runner=command_runner(responses),
        platform_info={"system": "Darwin", "machine": "x86_64", "processor": "i386", "hostname": "host"},
    )
    assert result["role"] == "imac"
    assert result["role_source"] == "environment"
    assert result["apple_silicon"] is True
    assert result["translated_under_rosetta"] is True


def test_lmstudio_candidate_order_is_override_loopback_bridge():
    candidates = lmstudio_candidates(
        policy(),
        explicit_base_url="http://override:1234/v1/",
        environ={"LMSTUDIO_BASE_URL": "http://env-override:1234/v1"},
    )
    assert [(item["source"], item["base_url"]) for item in candidates] == [
        ("override", "http://override:1234/v1"),
        ("override", "http://env-override:1234/v1"),
        ("loopback", "http://127.0.0.1:1234/v1"),
        ("loopback", "http://localhost:1234/v1"),
        ("bridge", "http://10.0.0.1:1234/v1"),
    ]


def test_endpoint_resolution_falls_through_without_real_sockets():
    calls = []

    def fake_probe(url, timeout, api_key):
        calls.append(url)
        if url == "http://10.0.0.1:1234/v1":
            return {"ok": True, "http_status": 200, "model_ids": ["model-a"], "elapsed_ms": 3}
        return {"ok": False, "error": "connection_refused", "model_ids": []}

    result = resolve_lmstudio_endpoint(
        policy(),
        explicit_base_url="http://override:1234/v1",
        environ={},
        probe=fake_probe,
    )
    assert result["status"] == "available"
    assert result["source"] == "bridge"
    assert result["base_url"] == "http://10.0.0.1:1234/v1"
    assert result["model_ids"] == ["model-a"]
    assert calls == [
        "http://override:1234/v1",
        "http://127.0.0.1:1234/v1",
        "http://localhost:1234/v1",
        "http://10.0.0.1:1234/v1",
    ]


def test_drive_and_peer_settings_are_environment_driven(tmp_path):
    env = {
        "CAMINO_DRIVE_BUS_ROOT": str(tmp_path),
        "CAMINO_PEER_ENABLED": "true",
        "CAMINO_PEER_SSH_HOST": "peer-alias",
        "CAMINO_PEER_ROLE": "imac",
    }
    drive = resolve_drive_settings(policy(), env)
    peer = resolve_peer_settings(policy(), env)
    assert drive == {
        "configured": True,
        "status": "ok",
        "root": str(tmp_path),
        "exists": True,
        "writable": True,
    }
    assert peer["enabled"] is True
    assert peer["configured"] is True
    assert peer["ssh_host"] == "peer-alias"
    assert peer["role"] == "imac"
    assert peer["status"] == "configured_not_probed"


def test_direct_cli_can_import_drive_locator_without_pythonpath(tmp_path):
    cp = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "host_runtime.py"),
         "--json", "--no-lmstudio-probe"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=30,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["drive"]["status"] != "discovery_error"


def test_full_report_uses_injected_probe_and_commands(tmp_path):
    responses = {
        ("sysctl", "-n", "hw.model"): "iMac20,2",
        ("sysctl", "-n", "hw.optional.arm64"): "0",
        ("sysctl", "-in", "sysctl.proc_translated"): "0",
        ("sysctl", "-n", "hw.memsize"): str(32 * GIB),
        ("vm_stat",): "Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 2097152.\n",
        ("memory_pressure", "-Q"): "System-wide memory free percentage: 25%",
    }

    def probe(url, timeout, api_key):
        return {"ok": url.startswith("http://127.0.0.1"), "http_status": 200, "model_ids": ["local"]}

    report = build_runtime_report(
        policy(),
        environ={"CAMINO_DRIVE_BUS_ROOT": str(tmp_path)},
        command_runner=command_runner(responses),
        platform_info={"system": "Darwin", "machine": "x86_64", "hostname": "iMac", "processor": "intel"},
        probe=probe,
    )
    assert report["host"]["role"] == "imac"
    assert report["host"]["architecture_family"] == "intel"
    assert report["lmstudio"]["source"] == "loopback"
    assert report["drive"]["status"] == "ok"
