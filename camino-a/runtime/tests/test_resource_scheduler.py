from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from scripts.resource_scheduler import ResourceScheduler


def policy():
    return {
        "schema_version": "camino_host_runtime_policy.v1",
        "resource_scheduler": {
            "minimum_headroom_bytes": 100,
            "minimum_headroom_fraction": 0.10,
            "deny_pressure_levels": ["critical"],
            "max_concurrent_medium": 2,
            "max_concurrent_heavy": 1,
            "heavy_is_exclusive": True,
            "reservation_ttl_seconds": 30,
            "heartbeat_interval_seconds": 0.1,
            "poll_interval_seconds": 0.01,
            "default_wait_seconds": 0,
            "estimated_peak_bytes_by_tier": {
                "medium": 200,
                "heavy": 600,
                "heavy_exclusive": 600,
            },
        },
    }


def memory(total=1000, available=900, pressure="normal"):
    return {
        "total_bytes": total,
        "available_bytes": available,
        "available_fraction": float(available) / total if total else 0.0,
        "pressure": pressure,
        "source": "test",
    }


def scheduler(tmp_path, memory_value=None, clock=None):
    value = memory_value or memory()
    return ResourceScheduler(
        policy(),
        db_path=tmp_path / "guard.sqlite",
        memory_provider=lambda: dict(value),
        clock=clock or (lambda: 100.0),
    )


def test_medium_limit_is_atomic_and_release_reopens_capacity(tmp_path):
    guard = scheduler(tmp_path)
    one = guard.try_reserve("r1", "medium")
    two = guard.try_reserve("r2", "medium")
    three = guard.try_reserve("r3", "medium")
    assert one.granted is True
    assert two.granted is True
    assert three.granted is False
    assert three.reason == "medium_concurrency_limit"
    assert len(guard.active_reservations()) == 2
    assert guard.release(one.reservation) is True
    replacement = guard.try_reserve("r3", "medium")
    assert replacement.granted is True


def test_heavy_is_exclusive_in_both_directions(tmp_path):
    guard = scheduler(tmp_path)
    heavy = guard.try_reserve("heavy", "heavy_exclusive")
    assert heavy.granted is True
    medium = guard.try_reserve("medium", "medium")
    assert medium.granted is False
    assert medium.reason == "heavy_reservation_active"
    guard.release(heavy.reservation)

    first_medium = guard.try_reserve("medium", "medium")
    blocked_heavy = guard.try_reserve("heavy", "heavy")
    assert first_medium.granted is True
    assert blocked_heavy.granted is False
    assert blocked_heavy.reason == "heavy_requires_exclusive_access"


def test_headroom_and_pressure_fail_closed(tmp_path):
    low_memory = scheduler(tmp_path / "low", memory(total=1000, available=250))
    decision = low_memory.try_reserve("r", "medium")
    assert decision.granted is False
    assert decision.reason == "insufficient_available_memory"

    critical = scheduler(tmp_path / "critical", memory(total=1000, available=900, pressure="critical"))
    decision = critical.try_reserve("r", "medium")
    assert decision.granted is False
    assert decision.reason == "memory_pressure_critical"


def test_unknown_tier_and_missing_metrics_are_honest(tmp_path):
    guard = scheduler(tmp_path / "unknown")
    assert guard.try_reserve("r", "mystery").reason == "unknown_ram_tier"

    unavailable = scheduler(tmp_path / "unavailable", memory(total=0, available=0, pressure="unknown"))
    decision = unavailable.try_reserve("r", "medium")
    assert decision.granted is False
    assert decision.reason == "memory_metrics_unavailable"


def test_ttl_expires_abandoned_reservation(tmp_path):
    now = [10.0]
    guard = scheduler(tmp_path, clock=lambda: now[0])
    decision = guard.try_reserve("r1", "medium", ttl_seconds=5)
    assert decision.granted is True
    now[0] = 16.0
    assert guard.cleanup_expired() == 1
    assert guard.active_reservations() == []
    replacement = guard.try_reserve("r2", "medium", ttl_seconds=5)
    assert replacement.granted is True


def test_maintain_context_releases_even_after_work(tmp_path):
    guard = scheduler(tmp_path)
    decision = guard.try_reserve("r", "medium", ttl_seconds=2)
    assert decision.granted is True
    with guard.maintain(decision.reservation):
        assert len(guard.active_reservations()) == 1
    assert guard.active_reservations() == []


def test_concurrent_callers_never_exceed_two_medium_reservations(tmp_path):
    guard = scheduler(tmp_path)
    barrier = threading.Barrier(10)

    def compete(index):
        barrier.wait()
        return guard.try_reserve("route-%s" % index, "medium")

    with ThreadPoolExecutor(max_workers=10) as pool:
        decisions = list(pool.map(compete, range(10)))
    assert sum(1 for decision in decisions if decision.granted) == 2
    assert len(guard.active_reservations()) == 2
    assert all(
        decision.granted or decision.reason == "medium_concurrency_limit"
        for decision in decisions
    )
