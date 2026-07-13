#!/usr/bin/env python3
"""Offline unit tests for portable Drive discovery and local state safety."""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.drive_locator import (
    DEFAULT_POLICY,
    DriveLocatorError,
    assert_local_state_path,
    locate_drive,
)


@contextmanager
def env_values(**updates):
    saved = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  PASS:", name)
    else:
        failed += 1
        print("  FAIL:", name, detail)


with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    provider = base / "CloudStorage" / "GoogleDrive-test@example"
    shared = provider / "CAMINO_A_SHARED"
    bus = shared / "AUDIT_BUS"
    bus.mkdir(parents=True)
    local = base / "local_staging"

    print("=== DRIVE 1: bounded discovery ===")
    with env_values(
        CAMINO_DRIVE_BUS_ROOT=None,
        CAMINO_SHARED_ROOT=None,
        CAMINO_LOCAL_STAGING_ROOT=local,
    ):
        location = locate_drive(
            policy_path=DEFAULT_POLICY,
            create=True,
            provider_roots=[provider],
        )
        check("discovery ready", location.ready, str(location.to_dict()))
        check("bus selected", Path(location.bus_root or "") == bus.resolve(), str(location.bus_root))
        check("state local", Path(location.local_state_root).is_relative_to(local.resolve()), location.local_state_root)
        check("SQLite explicitly forbidden", location.sqlite_on_shared_drive_allowed is False)
        try:
            assert_local_state_path(bus / "STATE/state.sqlite", location)
        except DriveLocatorError:
            rejected = True
        else:
            rejected = False
        check("SQLite on Drive rejected", rejected)
        try:
            assert_local_state_path(local / "state/state.sqlite", location)
        except DriveLocatorError:
            local_ok = False
        else:
            local_ok = True
        check("local SQLite accepted", local_ok)

    print("=== DRIVE 2: override precedence ===")
    direct = base / "direct_bus"
    direct.mkdir()
    other_shared = base / "other_shared"
    other_shared.mkdir()
    with env_values(
        CAMINO_DRIVE_BUS_ROOT=direct,
        CAMINO_SHARED_ROOT=other_shared,
        CAMINO_LOCAL_STAGING_ROOT=local,
    ):
        location = locate_drive(policy_path=DEFAULT_POLICY, create=True, provider_roots=[])
        check("direct bus wins", location.source == "CAMINO_DRIVE_BUS_ROOT", location.source)
        check("direct path exact", Path(location.bus_root or "") == direct.resolve(), str(location.bus_root))
        check("direct override ready", location.ready, str(location.to_dict()))

    print("=== DRIVE 3: ambiguity and unsafe staging ===")
    provider2 = base / "CloudStorage" / "GoogleDrive-other"
    (provider2 / "CAMINO_A_SHARED" / "AUDIT_BUS").mkdir(parents=True)
    with env_values(
        CAMINO_DRIVE_BUS_ROOT=None,
        CAMINO_SHARED_ROOT=None,
        CAMINO_LOCAL_STAGING_ROOT=local,
    ):
        location = locate_drive(policy_path=DEFAULT_POLICY, create=True, provider_roots=[provider, provider2])
        check("multiple roots fail closed", not location.ready and "multiple_shared_roots_use_override" in location.errors, str(location.to_dict()))
    with env_values(
        CAMINO_DRIVE_BUS_ROOT=None,
        CAMINO_SHARED_ROOT=shared,
        CAMINO_LOCAL_STAGING_ROOT=shared / "bad_state",
    ):
        location = locate_drive(policy_path=DEFAULT_POLICY, create=True, provider_roots=[])
        check("staging on Drive rejected", not location.ready and "local_staging_must_not_be_on_shared_drive" in location.errors, str(location.to_dict()))

    print("=== DRIVE 4: localized My Drive discovery and safe creation ===")
    localized_provider = base / "CloudStorage" / "GoogleDrive-localized"
    localized_my_drive = localized_provider / "Mi unidad"
    localized_my_drive.mkdir(parents=True)
    localized_local = base / "localized_staging"
    with env_values(
        CAMINO_DRIVE_BUS_ROOT=None,
        CAMINO_SHARED_ROOT=None,
        CAMINO_LOCAL_STAGING_ROOT=localized_local,
    ):
        missing = locate_drive(
            policy_path=DEFAULT_POLICY,
            create=False,
            provider_roots=[localized_provider],
        )
        check("localized missing root is not ready", not missing.ready, str(missing.to_dict()))
        created = locate_drive(
            policy_path=DEFAULT_POLICY,
            create=True,
            provider_roots=[localized_provider],
        )
        expected = localized_my_drive / "CAMINO_A_SHARED" / "AUDIT_BUS"
        check("localized root created only under Mi unidad", created.ready and Path(created.bus_root or "") == expected.resolve(), str(created.to_dict()))
        rediscovered = locate_drive(
            policy_path=DEFAULT_POLICY,
            create=False,
            provider_roots=[localized_provider],
        )
        check("localized root rediscovered", rediscovered.ready and Path(rediscovered.bus_root or "") == expected.resolve(), str(rediscovered.to_dict()))

print()
print("RESULTADO: %d passed, %d failed" % (passed, failed))
raise SystemExit(0 if failed == 0 else 1)
