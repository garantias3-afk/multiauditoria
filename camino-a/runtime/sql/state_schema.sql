-- Camino A Overnight — SQLite Schema
-- Run with: sqlite3 state.sqlite < state_schema.sql

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS run_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    event TEXT NOT NULL,
    data TEXT
);

CREATE TABLE IF NOT EXISTS worker_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ok','bug_found','patch_proposed','failed','timeout','quota_limited')),
    summary TEXT,
    artifacts TEXT,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS quality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    run_id TEXT NOT NULL,
    data TEXT NOT NULL,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_worker_results_worker ON worker_results(worker_id);
CREATE INDEX IF NOT EXISTS idx_quality_log_run ON quality_log(run_id);
