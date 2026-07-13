#!/usr/bin/env python3
"""Portable Google Drive/bus discovery with local mutable-state staging.

The shared drive is an exchange surface for immutable bundles only.  SQLite,
WAL files, locks and other mutable run state must stay below ``local_state_root``.
No username, account name or machine-specific absolute path is stored in canon.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "drive.policy.json"


class DriveLocatorError(ValueError):
    """Configuration or safety failure."""


@dataclass
class DriveLocation:
    source: str
    shared_root: Optional[str]
    bus_root: Optional[str]
    local_staging_root: str
    local_state_root: str
    ready: bool
    shared_root_exists: bool
    bus_root_exists: bool
    shared_root_writable: bool
    sqlite_on_shared_drive_allowed: bool = False
    mutable_state_on_shared_drive_allowed: bool = False
    shared_drive_payload_policy: str = "immutable_bundle_manifest_done_only"
    candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    policy_file: str = str(DEFAULT_POLICY)
    platform: str = field(default_factory=platform.system)
    host: str = field(default_factory=socket.gethostname)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriveLocatorError("drive_policy_invalid:%s" % path) from exc
    required = {
        "shared_root_directory_name",
        "bus_relative_path",
        "macos_cloud_storage_directory",
        "macos_provider_prefixes",
        "macos_my_drive_directory_names",
    }
    missing = sorted(required - set(data))
    if missing:
        raise DriveLocatorError("drive_policy_missing:%s" % ",".join(missing))
    if data.get("sqlite_on_shared_drive_allowed") is not False:
        raise DriveLocatorError("drive_policy_must_forbid_sqlite_on_shared_drive")
    return data


def _expanded_absolute(raw: str, *, name: str) -> Path:
    raw = str(raw or "").strip()
    if not raw:
        raise DriveLocatorError("empty_path:%s" % name)
    path = Path(raw).expanduser()
    if ".." in path.parts:
        raise DriveLocatorError("path_traversal:%s" % name)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _macos_provider_roots(policy: dict[str, Any], *, home: Optional[Path] = None) -> list[Path]:
    if platform.system() != "Darwin" and home is None:
        return []
    home = home or Path.home()
    cloud = home / str(policy["macos_cloud_storage_directory"])
    if not cloud.is_dir():
        return []
    prefixes = tuple(str(item) for item in policy["macos_provider_prefixes"])
    roots: list[Path] = []
    try:
        entries = sorted(cloud.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return []
    for entry in entries:
        if entry.is_dir() and not entry.is_symlink() and entry.name.startswith(prefixes):
            roots.append(entry.resolve(strict=False))
    return roots


def discover_candidates(
    policy: dict[str, Any], *, home: Optional[Path] = None, provider_roots: Optional[Iterable[Path]] = None
) -> list[Path]:
    """Return bounded candidates without recursively walking a whole Drive."""
    roots = list(provider_roots) if provider_roots is not None else _macos_provider_roots(policy, home=home)
    shared_name = str(policy["shared_root_directory_name"])
    marker = str(policy.get("workspace_marker") or ".camino_shared_root.json")
    marked: list[Path] = []
    named: list[Path] = []
    my_drive_names = tuple(str(item) for item in policy["macos_my_drive_directory_names"])
    for provider in roots:
        if (provider / marker).is_file():
            marked.append(provider)
        bases = [provider]
        for directory_name in my_drive_names:
            base = provider / directory_name
            if base.is_dir() and not base.is_symlink():
                bases.append(base)
        for base in bases:
            candidate = base / shared_name
            if candidate.is_dir() and not candidate.is_symlink():
                if (candidate / marker).is_file():
                    marked.append(candidate)
                else:
                    named.append(candidate)
    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in marked + named:
        key = str(candidate.resolve(strict=False))
        if key not in seen:
            ordered.append(candidate.resolve(strict=False))
            seen.add(key)
    return ordered


def discover_creation_parents(
    policy: dict[str, Any], *, home: Optional[Path] = None,
    provider_roots: Optional[Iterable[Path]] = None,
) -> list[Path]:
    """Return safe, bounded parents where a missing shared root may be created.

    Google Drive for macOS places user files below a localized ``My Drive``
    directory.  Creation is permitted only when exactly one provider and one
    recognized, real (non-symlink) My Drive directory are visible.  Ambiguity
    is never resolved by guessing an account or locale.
    """
    roots = list(provider_roots) if provider_roots is not None else _macos_provider_roots(policy, home=home)
    names = tuple(str(item) for item in policy["macos_my_drive_directory_names"])
    parents: list[Path] = []
    for provider in roots:
        for directory_name in names:
            candidate = provider / directory_name
            if candidate.is_dir() and not candidate.is_symlink():
                parents.append(candidate.resolve(strict=False))
    unique: list[Path] = []
    seen: set[str] = set()
    for parent in parents:
        key = str(parent)
        if key not in seen:
            unique.append(parent)
            seen.add(key)
    return unique


def _default_local_staging(
    policy: dict[str, Any], *, environ: Optional[dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    env = os.environ if environ is None else environ
    override = env.get("CAMINO_LOCAL_STAGING_ROOT", "").strip()
    if override:
        return _expanded_absolute(override, name="CAMINO_LOCAL_STAGING_ROOT")
    app_name = str(policy.get("local_staging_app_name") or "CaminoA")
    if platform.system() == "Darwin":
        return ((home or Path.home()) / "Library" / "Caches" / app_name / "staging").resolve(strict=False)
    xdg_cache = env.get("XDG_CACHE_HOME", "").strip()
    cache = Path(xdg_cache).expanduser() if xdg_cache else (home or Path.home()) / ".cache"
    return (cache / app_name / "staging").resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _writable_directory(path: Path) -> bool:
    if not path.is_dir():
        return False
    return os.access(str(path), os.R_OK | os.W_OK | os.X_OK)


def locate_drive(
    *, policy_path: Path = DEFAULT_POLICY, create: bool = False,
    home: Optional[Path] = None, provider_roots: Optional[Iterable[Path]] = None,
    environ: Optional[dict[str, str]] = None,
) -> DriveLocation:
    policy = _load_policy(policy_path)
    env = os.environ if environ is None else environ
    normalized_provider_roots = list(provider_roots) if provider_roots is not None else None
    candidates: list[Path] = []
    warnings: list[str] = []
    errors: list[str] = []

    direct_bus = env.get("CAMINO_DRIVE_BUS_ROOT", "").strip()
    shared_override = env.get("CAMINO_SHARED_ROOT", "").strip()
    source = "not_found"
    shared_root: Optional[Path] = None
    bus_root: Optional[Path] = None

    if direct_bus:
        source = "CAMINO_DRIVE_BUS_ROOT"
        bus_root = _expanded_absolute(direct_bus, name=source)
        # The direct override identifies the exact shared boundary.  Treating
        # its parent as shared could incorrectly classify unrelated local state.
        shared_root = bus_root
        candidates = [shared_root]
    elif shared_override:
        source = "CAMINO_SHARED_ROOT"
        shared_root = _expanded_absolute(shared_override, name=source)
        bus_root = shared_root / str(policy["bus_relative_path"])
        candidates = [shared_root]
    else:
        candidates = discover_candidates(
            policy, home=home, provider_roots=normalized_provider_roots,
        )
        if len(candidates) == 1:
            source = "macos_google_drive_discovery"
            shared_root = candidates[0]
            bus_root = shared_root / str(policy["bus_relative_path"])
        elif len(candidates) > 1:
            errors.append("multiple_shared_roots_use_override")
        else:
            creation_parents = discover_creation_parents(
                policy, home=home, provider_roots=normalized_provider_roots,
            )
            if create and len(creation_parents) == 1:
                source = "macos_google_drive_discovery_create"
                shared_root = creation_parents[0] / str(policy["shared_root_directory_name"])
                bus_root = shared_root / str(policy["bus_relative_path"])
                candidates = [shared_root]
            elif len(creation_parents) > 1:
                errors.append("multiple_my_drive_roots_use_override")
            else:
                warnings.append("google_drive_shared_root_not_found")

    local_staging = _default_local_staging(policy, environ=dict(env), home=home)
    local_state = local_staging / "state"
    if shared_root is not None and _is_within(local_staging, shared_root):
        errors.append("local_staging_must_not_be_on_shared_drive")

    if create:
        try:
            local_staging.mkdir(parents=True, exist_ok=True)
            local_state.mkdir(parents=True, exist_ok=True)
            if shared_root is not None:
                shared_root.mkdir(parents=True, exist_ok=True)
            if bus_root is not None:
                bus_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            errors.append("directory_create_failed:%s" % type(exc).__name__)

    shared_exists = bool(shared_root is not None and shared_root.is_dir())
    bus_exists = bool(bus_root is not None and bus_root.is_dir())
    writable = bool(shared_root is not None and _writable_directory(shared_root))
    if shared_root is not None and not shared_exists:
        errors.append("shared_root_missing")
    if bus_root is not None and not bus_exists:
        warnings.append("bus_root_missing_use_create")
    if shared_exists and not writable:
        errors.append("shared_root_not_writable")
    if not _writable_directory(local_staging):
        if create:
            errors.append("local_staging_not_writable")
        else:
            warnings.append("local_staging_missing_use_create")

    return DriveLocation(
        source=source,
        shared_root=str(shared_root) if shared_root is not None else None,
        bus_root=str(bus_root) if bus_root is not None else None,
        local_staging_root=str(local_staging),
        local_state_root=str(local_state),
        ready=bool(shared_exists and bus_exists and writable and not errors),
        shared_root_exists=shared_exists,
        bus_root_exists=bus_exists,
        shared_root_writable=writable,
        shared_drive_payload_policy=str(
            policy.get("shared_drive_payload_policy") or "immutable_bundle_manifest_done_only"
        ),
        candidates=[str(item) for item in candidates],
        warnings=warnings,
        errors=errors,
        policy_file=str(policy_path.resolve(strict=False)),
    )


def assert_local_state_path(path: Path, location: DriveLocation) -> None:
    """Fail closed if a SQLite/state path points into the shared exchange tree."""
    candidate = Path(path).expanduser().resolve(strict=False)
    for raw in (location.shared_root, location.bus_root):
        if raw and _is_within(candidate, Path(raw)):
            raise DriveLocatorError("mutable_state_on_shared_drive_rejected:%s" % candidate)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Locate the portable Camino A Drive bus")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--require-shared", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable diagnostic")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        location = locate_drive(policy_path=Path(args.policy), create=args.create)
    except DriveLocatorError as exc:
        payload = {"ready": False, "errors": [str(exc)]}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    payload = location.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("source=%s" % location.source)
        print("bus_root=%s" % (location.bus_root or "NOT_FOUND"))
        print("local_state_root=%s" % location.local_state_root)
        print("ready=%s" % str(location.ready).lower())
    if args.require_shared and not location.ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
