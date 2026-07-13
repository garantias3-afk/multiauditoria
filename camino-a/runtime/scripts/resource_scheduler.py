#!/usr/bin/env python3
"""Atomic local resource reservations for LM Studio work.

SQLite ``BEGIN IMMEDIATE`` transactions serialize competing launchers on the
same machine.  Every reservation is bounded by a TTL and checked against both
configured concurrency limits and a fresh conservative memory snapshot.

This guard is authoritative only when its database and memory probe run on the
machine that owns the LM Studio RAM.  A remote caller should execute this worker
on that machine (for example through the configured peer transport), rather than
placing this SQLite database on a network/Drive filesystem.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.host_runtime import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    MemorySnapshot,
    collect_memory_snapshot,
    load_policy,
)


MemoryProvider = Callable[[], Any]


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    owner: str
    route_id: str
    tier: str
    tier_class: str
    bytes_reserved: int
    created_at: float
    expires_at: float
    ttl_seconds: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReservationDecision:
    granted: bool
    reason: str
    reservation: Optional[Reservation]
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "granted": self.granted,
            "reason": self.reason,
            "reservation": self.reservation.to_dict() if self.reservation else None,
            "details": self.details,
        }


class ResourceScheduler:
    """Local, process-safe LM Studio capacity guard."""

    def __init__(
        self,
        policy: Optional[Mapping[str, Any]] = None,
        db_path: Optional[Path] = None,
        memory_provider: Optional[MemoryProvider] = None,
        environ: Optional[Mapping[str, str]] = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = dict(policy or load_policy())
        self.config = dict(self.policy.get("resource_scheduler", self.policy))
        self.environ = dict(os.environ if environ is None else environ)
        self.clock = clock
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.memory_provider = memory_provider or (lambda: collect_memory_snapshot(self.policy))
        self.db_path = Path(db_path or self._default_db_path()).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _default_db_path(self) -> Path:
        state_env = str(self.config.get("state_dir_env", "CAMINO_RESOURCE_STATE_DIR"))
        state_dir = str(self.environ.get(state_env) or self.config.get("state_dir_default", "~/.camino/runtime"))
        database_name = str(self.config.get("database_name", "lmstudio_resource_reservations.sqlite"))
        return Path(state_dir).expanduser() / database_name

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _initialize_database(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    tier_class TEXT NOT NULL,
                    bytes_reserved INTEGER NOT NULL CHECK(bytes_reserved > 0),
                    state TEXT NOT NULL CHECK(state IN ('active','released','expired')),
                    created_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    released_at REAL,
                    release_reason TEXT,
                    memory_total_bytes INTEGER NOT NULL,
                    memory_available_bytes INTEGER NOT NULL,
                    memory_pressure TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reservations_active
                    ON reservations(state, expires_at, tier_class);
                CREATE INDEX IF NOT EXISTS idx_reservations_route
                    ON reservations(route_id, created_at);
                """
            )

    def _memory_dict(self) -> Dict[str, Any]:
        value = self.memory_provider()
        if isinstance(value, MemorySnapshot):
            result = value.to_dict()
        elif isinstance(value, Mapping):
            result = dict(value)
        else:
            result = {}
        total = max(0, int(result.get("total_bytes") or 0))
        available = max(0, int(result.get("available_bytes") or 0))
        available = min(available, total) if total else available
        fraction = float(result.get("available_fraction") or (float(available) / total if total else 0.0))
        return {
            "total_bytes": total,
            "available_bytes": available,
            "available_fraction": fraction,
            "pressure": str(result.get("pressure") or "unknown").lower(),
            "source": str(result.get("source") or "injected_or_unknown"),
        }

    @staticmethod
    def _tier_class(tier: str) -> str:
        value = str(tier or "").strip().lower()
        if value in {"heavy", "heavy_exclusive"} or value.startswith("heavy"):
            return "heavy"
        if value == "medium" or value.startswith("medium"):
            return "medium"
        return "unknown"

    def estimated_bytes(self, tier: str) -> int:
        estimates = self.config.get("estimated_peak_bytes_by_tier", {})
        value = estimates.get(str(tier).lower()) if isinstance(estimates, Mapping) else None
        if value is None and self._tier_class(tier) == "heavy" and isinstance(estimates, Mapping):
            value = estimates.get("heavy") or estimates.get("heavy_exclusive")
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _headroom_bytes(self, total_bytes: int) -> int:
        fixed = max(0, int(self.config.get("minimum_headroom_bytes", 0)))
        fraction = max(0.0, float(self.config.get("minimum_headroom_fraction", 0.0)))
        return max(fixed, int(total_bytes * fraction))

    @staticmethod
    def _expire_locked(conn: sqlite3.Connection, now: float) -> int:
        cursor = conn.execute(
            """UPDATE reservations
               SET state='expired', released_at=?, release_reason='ttl_expired'
               WHERE state='active' AND expires_at <= ?""",
            (now, now),
        )
        return int(cursor.rowcount or 0)

    def cleanup_expired(self) -> int:
        now = float(self.clock())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            count = self._expire_locked(conn, now)
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def try_reserve(
        self,
        route_id: str,
        tier: str,
        bytes_required: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        owner: str = "",
    ) -> ReservationDecision:
        now = float(self.clock())
        tier_class = self._tier_class(tier)
        requested = int(bytes_required if bytes_required is not None else self.estimated_bytes(tier))
        ttl = int(ttl_seconds if ttl_seconds is not None else self.config.get("reservation_ttl_seconds", 1800))
        ttl = max(1, ttl)
        owner_value = str(owner or "pid:%s" % os.getpid())
        if tier_class == "unknown":
            return ReservationDecision(False, "unknown_ram_tier", None, {"tier": tier})
        if requested <= 0:
            return ReservationDecision(False, "memory_estimate_missing", None, {"tier": tier})

        memory = self._memory_dict()
        total = memory["total_bytes"]
        available = memory["available_bytes"]
        if total <= 0 or available <= 0:
            return ReservationDecision(False, "memory_metrics_unavailable", None, {"memory": memory})
        deny_pressure = set(str(x).lower() for x in self.config.get("deny_pressure_levels", ["critical"]))
        if memory["pressure"] in deny_pressure:
            return ReservationDecision(False, "memory_pressure_%s" % memory["pressure"], None, {"memory": memory})

        headroom = self._headroom_bytes(total)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_locked(conn, now)
            rows = conn.execute(
                """SELECT tier_class, bytes_reserved FROM reservations
                   WHERE state='active' AND expires_at > ?""",
                (now,),
            ).fetchall()
            active_count = len(rows)
            medium_count = sum(1 for row in rows if row["tier_class"] == "medium")
            heavy_count = sum(1 for row in rows if row["tier_class"] == "heavy")
            reserved_total = sum(int(row["bytes_reserved"]) for row in rows)
            max_medium = max(0, int(self.config.get("max_concurrent_medium", 2)))
            max_heavy = max(0, int(self.config.get("max_concurrent_heavy", 1)))
            exclusive = bool(self.config.get("heavy_is_exclusive", True))

            reason = ""
            if tier_class == "medium" and heavy_count and exclusive:
                reason = "heavy_reservation_active"
            elif tier_class == "medium" and medium_count >= max_medium:
                reason = "medium_concurrency_limit"
            elif tier_class == "heavy" and exclusive and active_count:
                reason = "heavy_requires_exclusive_access"
            elif tier_class == "heavy" and heavy_count >= max_heavy:
                reason = "heavy_concurrency_limit"
            elif reserved_total + requested > max(0, total - headroom):
                reason = "reservation_capacity_exceeded"
            elif available - requested < headroom:
                reason = "insufficient_available_memory"

            details = {
                "memory": memory,
                "headroom_bytes": headroom,
                "requested_bytes": requested,
                "active_reservations": active_count,
                "active_medium": medium_count,
                "active_heavy": heavy_count,
                "active_reserved_bytes": reserved_total,
            }
            if reason:
                conn.rollback()
                return ReservationDecision(False, reason, None, details)

            reservation = Reservation(
                reservation_id="RES_%s" % uuid.uuid4().hex,
                owner=owner_value,
                route_id=str(route_id),
                tier=str(tier),
                tier_class=tier_class,
                bytes_reserved=requested,
                created_at=now,
                expires_at=now + ttl,
                ttl_seconds=ttl,
            )
            conn.execute(
                """INSERT INTO reservations (
                       reservation_id, owner, route_id, tier, tier_class,
                       bytes_reserved, state, created_at, heartbeat_at, expires_at,
                       memory_total_bytes, memory_available_bytes, memory_pressure
                   ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
                (
                    reservation.reservation_id, reservation.owner, reservation.route_id,
                    reservation.tier, reservation.tier_class, reservation.bytes_reserved,
                    now, now, reservation.expires_at, total, available, memory["pressure"],
                ),
            )
            conn.commit()
            return ReservationDecision(True, "reserved", reservation, details)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def acquire(
        self,
        route_id: str,
        tier: str,
        bytes_required: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        owner: str = "",
        wait_seconds: Optional[float] = None,
    ) -> ReservationDecision:
        wait = float(wait_seconds if wait_seconds is not None else self.config.get("default_wait_seconds", 0))
        deadline = self.monotonic() + max(0.0, wait)
        last = self.try_reserve(route_id, tier, bytes_required, ttl_seconds, owner)
        while not last.granted and self.monotonic() < deadline:
            interval = max(0.01, float(self.config.get("poll_interval_seconds", 1.0)))
            self.sleeper(min(interval, max(0.0, deadline - self.monotonic())))
            last = self.try_reserve(route_id, tier, bytes_required, ttl_seconds, owner)
        return last

    def heartbeat(self, reservation: Reservation) -> bool:
        now = float(self.clock())
        expires = now + max(1, int(reservation.ttl_seconds))
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_locked(conn, now)
            cursor = conn.execute(
                """UPDATE reservations SET heartbeat_at=?, expires_at=?
                   WHERE reservation_id=? AND state='active'""",
                (now, expires, reservation.reservation_id),
            )
            conn.commit()
            return int(cursor.rowcount or 0) == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release(self, reservation: Reservation, reason: str = "completed") -> bool:
        now = float(self.clock())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """UPDATE reservations
                   SET state='released', released_at=?, release_reason=?
                   WHERE reservation_id=? AND state='active'""",
                (now, str(reason), reservation.reservation_id),
            )
            conn.commit()
            return int(cursor.rowcount or 0) == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def active_reservations(self) -> List[Dict[str, Any]]:
        self.cleanup_expired()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT reservation_id, owner, route_id, tier, tier_class,
                          bytes_reserved, created_at, heartbeat_at, expires_at
                   FROM reservations WHERE state='active' ORDER BY created_at"""
            ).fetchall()
        return [dict(row) for row in rows]

    def status(self) -> Dict[str, Any]:
        active = self.active_reservations()
        return {
            "schema_version": "camino_resource_scheduler_status.v1",
            "database": str(self.db_path),
            "memory": self._memory_dict(),
            "limits": {
                "max_concurrent_medium": int(self.config.get("max_concurrent_medium", 2)),
                "max_concurrent_heavy": int(self.config.get("max_concurrent_heavy", 1)),
                "heavy_is_exclusive": bool(self.config.get("heavy_is_exclusive", True)),
            },
            "active_reservations": active,
        }

    @contextmanager
    def maintain(self, reservation: Reservation) -> Iterator[Reservation]:
        """Heartbeat a granted lease in the background and always release it."""
        stop = threading.Event()
        interval = max(
            0.1,
            min(
                float(self.config.get("heartbeat_interval_seconds", 30)),
                max(0.1, reservation.ttl_seconds / 3.0),
            ),
        )

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    if not self.heartbeat(reservation):
                        return
                except Exception:
                    return

        thread = threading.Thread(target=beat, name="reservation-heartbeat", daemon=True)
        thread.start()
        release_reason = "completed"
        try:
            yield reservation
        except BaseException:
            release_reason = "exception"
            raise
        finally:
            stop.set()
            thread.join(timeout=min(1.0, interval + 0.1))
            self.release(reservation, reason=release_reason)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the local LM Studio resource guard")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--db", default="")
    parser.add_argument("--cleanup-expired", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    scheduler = ResourceScheduler(
        load_policy(Path(args.policy)), db_path=Path(args.db) if args.db else None,
    )
    cleaned = scheduler.cleanup_expired() if args.cleanup_expired else 0
    result = scheduler.status()
    result["expired_cleaned"] = cleaned
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Guard DB: %s" % result["database"])
        print("Pressure: %s" % result["memory"]["pressure"])
        print("Active reservations: %s" % len(result["active_reservations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
