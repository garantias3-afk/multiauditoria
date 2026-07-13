#!/usr/bin/env python3
"""state_db.py — SQLite WAL state/audit log management.

v1.2.0 — B-3 fix.

The previous version was decorative: only `run_state` (kv) and `events`
existed, and the master only wrote a couple of keys at startup. The
state machine continued to live in `cycle_state.json`.

This version introduces the full relational schema mandated by the
audit contract:

    runs(run_id, label, target_sha256, state, brain_current,
         created_at, updated_at, terminal_reason)
    jobs(job_id, run_id, worker_id, stage, candidate_sha256,
         status, priority, created_at, updated_at)
    attempts(attempt_id, job_id, worker_id, started_at, ended_at,
             status, exit_code, timeout_seconds, error_class)
    outputs(output_id, job_id, attempt_id, path, payload_sha256,
            manifest_sha256, validation_status, rejected_reason,
            created_at)
    events(event_id, run_id, ts, level, component, event_type,
           details_json)
    terminal_checks(run_id, check_name, status, details_json, ts)

The master MUST call `update_run_state()` on every phase transition
and `record_terminal_check()` before declaring success. In this release,
`cycle_state.json` remains the execution state file while SQLite is the
structured audit/terminal-check authority. Attempts and outputs are populated
by the master and output records are idempotent by path.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

# End-of-file marker for run_state_value JSON
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    label TEXT,
    target_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    brain_current TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_reason TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    candidate_sha256 TEXT,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    exit_code INTEGER,
    timeout_seconds INTEGER,
    error_class TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
);

CREATE TABLE IF NOT EXISTS outputs (
    output_id TEXT PRIMARY KEY,
    job_id TEXT,
    attempt_id TEXT,
    path TEXT NOT NULL,
    payload_sha256 TEXT,
    manifest_sha256 TEXT,
    validation_status TEXT NOT NULL,
    rejected_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(job_id),
    FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id)
);
-- BUG-4 FIX: columna updated_at agregada. El UPDATE en record_output()
-- pisaba created_at con el timestamp actual, destruyendo el registro de
-- cuándo fue observado el bundle por primera vez. Ahora created_at es
-- inmutable y updated_at se actualiza en cada re-observación.
-- ALTER TABLE para bases existentes (idempotente vía IGNORE):
-- (SQLite no soporta IF NOT EXISTS en ALTER; se maneja con try/except en init.)


CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    component TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details_json TEXT
);

CREATE TABLE IF NOT EXISTS terminal_checks (
    run_id TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT,
    ts TEXT NOT NULL,
    PRIMARY KEY(run_id, check_name)
);

CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_attempts_job ON attempts(job_id);
CREATE INDEX IF NOT EXISTS idx_outputs_job ON outputs(job_id);
CREATE INDEX IF NOT EXISTS idx_outputs_validation ON outputs(validation_status);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS quality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    run_id TEXT NOT NULL,
    data TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quality_log_run ON quality_log(run_id);
"""


class StateDB:
    """SQLite WAL-backed authoritative state store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        # BUG-4 FIX: migración idempotente para bases existentes que no tienen
        # la columna updated_at en outputs. ALTER TABLE falla silenciosamente
        # si la columna ya existe (la versión nueva la tiene desde el DDL).
        try:
            self.conn.execute("ALTER TABLE outputs ADD COLUMN updated_at TEXT")
            self.conn.commit()
        except Exception:
            pass  # columna ya existe o tabla aún no creada: ambos son OK
        self.conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    def upsert_run(self, run_id: str, *, target_sha256: str, state: str,
                   label: str = "", brain_current: str = "",
                   terminal_reason: str | None = None) -> None:
        """Insert or update the run row.

        NEW-BUG-C fix (v1.2.0-iter2): on conflict we COALESCE the new
        terminal_reason with the existing one so re-entry (which calls
        upsert_run with terminal_reason=None) does NOT clobber an
        already-set terminal_reason like 'closed_success'.
        """
        now = _utc_now()
        self.conn.execute(
            """INSERT INTO runs (run_id, label, target_sha256, state, brain_current,
                                 created_at, updated_at, terminal_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                 label = excluded.label,
                 state = excluded.state,
                 brain_current = excluded.brain_current,
                 updated_at = excluded.updated_at,
                 terminal_reason = COALESCE(excluded.terminal_reason, runs.terminal_reason)
            """,
            (run_id, label, target_sha256, state, brain_current,
             now, now, terminal_reason),
        )
        self.conn.commit()

    def update_run_state(self, run_id: str, state: str,
                         terminal_reason: str | None = None) -> None:
        now = _utc_now()
        self.conn.execute(
            """UPDATE runs SET state = ?, updated_at = ?,
               terminal_reason = COALESCE(?, terminal_reason)
               WHERE run_id = ?""",
            (state, now, terminal_reason, run_id),
        )
        self.conn.commit()

    def get_run_state(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    def insert_job(self, *, run_id: str, worker_id: str, stage: str,
                   candidate_sha256: str = "", status: str = "pending",
                   priority: int = 0, job_id: str | None = None) -> str:
        job_id = job_id or f"JOB_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        self.conn.execute(
            """INSERT INTO jobs (job_id, run_id, worker_id, stage,
                                 candidate_sha256, status, priority,
                                 created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, run_id, worker_id, stage, candidate_sha256,
             status, priority, now, now),
        )
        self.conn.commit()
        return job_id

    def update_job_status(self, job_id: str, status: str) -> None:
        now = _utc_now()
        self.conn.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
            (status, now, job_id),
        )
        self.conn.commit()

    def list_jobs(self, run_id: str, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? AND status = ? ORDER BY created_at",
                (run_id, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_pending_jobs(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE run_id = ? AND status IN ('pending','dispatched','running')",
            (run_id,),
        ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    # attempts
    # ------------------------------------------------------------------
    def record_attempt(self, *, job_id: str, worker_id: str,
                       started_at: str, ended_at: str | None = None,
                       status: str = "running", exit_code: int | None = None,
                       timeout_seconds: int | None = None,
                       error_class: str | None = None,
                       attempt_id: str | None = None) -> str:
        attempt_id = attempt_id or f"ATT_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """INSERT INTO attempts (attempt_id, job_id, worker_id,
                                     started_at, ended_at, status,
                                     exit_code, timeout_seconds, error_class)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (attempt_id, job_id, worker_id, started_at, ended_at,
             status, exit_code, timeout_seconds, error_class),
        )
        self.conn.commit()
        return attempt_id

    # ------------------------------------------------------------------
    # outputs
    # ------------------------------------------------------------------
    def record_output(self, *, path: str, job_id: str = "", attempt_id: str = "",
                      payload_sha256: str = "", manifest_sha256: str = "",
                      validation_status: str = "unknown",
                      rejected_reason: str | None = None,
                      output_id: str | None = None) -> str:
        """Record an output idempotently by path.

        v1.3.2 closes the duplicate-output residual risk. Harvest and
        consolidating may both observe the same bundle; the DB now updates the
        existing row for ``path`` instead of appending duplicates. This keeps
        the table useful as an audit index without changing the public schema.
        """
        now = _utc_now()
        existing = self.conn.execute(
            "SELECT output_id FROM outputs WHERE path = ? ORDER BY created_at DESC LIMIT 1",
            (path,),
        ).fetchone()
        if existing:
            oid = str(existing["output_id"])
            # BUG-4 FIX: se usaba created_at = ? en el UPDATE, pisando el
            # timestamp original de primera observación. Corregido a
            # updated_at = ? para preservar created_at intacto.
            self.conn.execute(
                """UPDATE outputs SET job_id = COALESCE(?, job_id),
                                      attempt_id = COALESCE(?, attempt_id),
                                      payload_sha256 = COALESCE(NULLIF(?, ''), payload_sha256),
                                      manifest_sha256 = COALESCE(NULLIF(?, ''), manifest_sha256),
                                      validation_status = ?,
                                      rejected_reason = COALESCE(?, rejected_reason),
                                      updated_at = ?
                   WHERE output_id = ?""",
                (job_id or None, attempt_id or None, payload_sha256, manifest_sha256,
                 validation_status, rejected_reason, now, oid),
            )
            self.conn.commit()
            return oid

        output_id = output_id or f"OUT_{uuid.uuid4().hex[:12]}"
        # Pass None for empty job_id / attempt_id so SQLite FK accepts them.
        # updated_at se inicializa igual que created_at en INSERT; diverge en updates.
        self.conn.execute(
            """INSERT INTO outputs (output_id, job_id, attempt_id, path,
                                    payload_sha256, manifest_sha256,
                                    validation_status, rejected_reason,
                                    created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (output_id, job_id or None, attempt_id or None, path,
             payload_sha256, manifest_sha256, validation_status,
             rejected_reason, now, now),
        )
        self.conn.commit()
        return output_id

    def latest_job_for_worker(self, run_id: str, worker_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM jobs WHERE run_id = ? AND worker_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (run_id, worker_id),
        ).fetchone()
        return dict(row) if row else None

    def latest_attempt_for_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT * FROM attempts WHERE job_id = ?
               ORDER BY started_at DESC LIMIT 1""",
            (job_id,),
        ).fetchone()
        return dict(row) if row else None

    def count_outputs(self, run_id: str = "", validation_status: str = "valid") -> int:
        # outputs has no run_id column; join via jobs if run_id provided
        if run_id:
            row = self.conn.execute(
                """SELECT COUNT(*) AS c FROM outputs o
                   LEFT JOIN jobs j ON o.job_id = j.job_id
                   WHERE j.run_id = ? AND o.validation_status = ?""",
                (run_id, validation_status),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM outputs WHERE validation_status = ?",
                (validation_status,),
            ).fetchone()
        return int(row["c"]) if row else 0


    # ------------------------------------------------------------------
    # quality_log
    # ------------------------------------------------------------------
    def record_quality_entry(self, entry: dict[str, Any]) -> str:
        """Insert/update a canonical AI quality log entry.

        The delta JSON files are the portable append-only stream; this table is
        the queryable index. entry_id is unique so re-harvest/re-entry remains
        idempotent.
        """
        entry_id = str(entry.get("entry_id") or "")
        run_id = str(entry.get("run_id") or "")
        if not entry_id or not run_id:
            raise ValueError("quality_log entry requires entry_id and run_id")
        self.conn.execute(
            """INSERT INTO quality_log (entry_id, run_id, data)
               VALUES (?, ?, ?)
               ON CONFLICT(entry_id) DO UPDATE SET
                 run_id = excluded.run_id,
                 data = excluded.data""",
            (entry_id, run_id, json.dumps(entry, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return entry_id

    def list_quality_entries(self, run_id: str = "", limit: int = 1000) -> list[dict[str, Any]]:
        if run_id:
            rows = self.conn.execute(
                "SELECT data FROM quality_log WHERE run_id = ? ORDER BY id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM quality_log ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r["data"]))
            except Exception:
                pass
        return out

    def count_quality_entries(self, run_id: str = "") -> int:
        if run_id:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM quality_log WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM quality_log").fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def event(self, event_type: str, *, run_id: str = "", component: str = "master",
              level: str = "info", details: Any = None) -> None:
        now = _utc_now()
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        self.conn.execute(
            """INSERT INTO events (run_id, ts, level, component, event_type, details_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id or None, now, level, component, event_type, details_json),
        )
        self.conn.commit()

    def get_events(self, run_id: str = "", limit: int = 100) -> list[dict]:
        if run_id:
            rows = self.conn.execute(
                """SELECT * FROM events WHERE run_id = ?
                   ORDER BY event_id DESC LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY event_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # terminal_checks
    # ------------------------------------------------------------------
    def record_terminal_check(self, run_id: str, check_name: str, status: str,
                              details: Any = None) -> None:
        now = _utc_now()
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        self.conn.execute(
            """INSERT INTO terminal_checks (run_id, check_name, status, details_json, ts)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id, check_name) DO UPDATE SET
                 status = excluded.status,
                 details_json = excluded.details_json,
                 ts = excluded.ts""",
            (run_id, check_name, status, details_json, now),
        )
        self.conn.commit()

    def list_terminal_checks(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM terminal_checks WHERE run_id = ? ORDER BY check_name",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def all_terminal_checks_pass(self, run_id: str) -> tuple[bool, list[dict]]:
        """Return (all_pass, failing_checks).

        NEW-BUG-A fix (v1.2.0-iter2): a check with status='skipped'
        does NOT count as failing. Only 'fail' (and any unknown status
        other than 'pass'/'skipped') counts as failing.
        """
        rows = self.list_terminal_checks(run_id)
        if not rows:
            return False, [{"check_name": "<none>", "status": "missing",
                            "details_json": "no terminal checks recorded"}]
        failing = [r for r in rows if r["status"] not in ("pass", "skipped")]
        return len(failing) == 0, failing

    # ------------------------------------------------------------------
    # journal_mode introspection
    # ------------------------------------------------------------------
    def journal_mode(self) -> str:
        row = self.conn.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]) if row else "unknown"

    # ------------------------------------------------------------------
    # legacy kv compat (for older code paths that still call db.set/get)
    # ------------------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        """Legacy kv interface — kept for backward compatibility."""
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS run_state_kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        now = _utc_now()
        self.conn.execute(
            """INSERT INTO run_state_kv (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = excluded.updated_at""",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        self.conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        try:
            row = self.conn.execute(
                "SELECT value FROM run_state_kv WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.OperationalError:
            return default
        if row is None:
            return default
        return json.loads(row[0])


def _utc_now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()
