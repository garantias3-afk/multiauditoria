"""canon_plumbing.py — canonical policy-free plumbing layer for Camino A/B.

This module is the single import target for the canonical runtime
(run_multiaudit_cycle.py, workers and tests) when they need policy-free
mechanical helpers: state IO, hashing, JSON utils, secret scanning,
output-manifest (de)serialization, worker-bus dirs and watcher locks.

DESIGN (why re-export instead of move):
  The legacy monolith's live helpers are interlinked by a long transitive
  closure (state init → manual inbox → watcher launchd → ...). Physically
  moving only the consumed names would either break internal references or drag
  ~48 functions and 12 constants into this file, diluting the goal. So this
  facade re-exports exactly the policy-free public surface the canonical runtime
  consumes, and the monolith stays as the implementation source until a full
  test-backed physical partition is available.

THIS MODULE OWNS NO POLICY. None of the re-exported helpers know anything
about slots, providers, models, fallbacks or terminal rules.
"""
from __future__ import annotations

# Single import from the monolith's policy-free plumbing section.
# Any addition here MUST be a mechanical helper (IO/hash/secret/manifest/lock),
# never a slot/provider/terminal-rule function.
from scripts.run_multiaudit_cycle_legacy import (  # noqa: F401
    # worker-bus layout
    BUS_DIRS,
    ensure_bus_dirs,
    reap_children,
    # time + hashing + slug
    sha256_file,
    utc_now,
    utc_now_compact,
    safe_slug,
    # json state
    read_json,
    write_json,
    save_state,
    load_state,
    history_event,
    # output manifest (de)serialization
    validate_output_manifest,
    write_output_manifest_and_done,
    # secret scanning
    assert_no_unredacted_secret,
    assert_file_has_no_unredacted_secret,
    redact_secrets_text,
    # watcher locks
    acquire_watcher_lock,
    release_watcher_lock,
    # process + env helpers
    _sanitized_env,
    run,
    # quality log delta (manual audit ingestion plumbing)
    record_quality_log_delta,
    # local notification (macOS) — plumbing, not policy
    send_local_notification,
)

__all__ = [
    "BUS_DIRS", "ensure_bus_dirs", "reap_children",
    "sha256_file", "utc_now", "utc_now_compact", "safe_slug",
    "read_json", "write_json", "save_state", "load_state", "history_event",
    "validate_output_manifest", "write_output_manifest_and_done",
    "assert_no_unredacted_secret", "assert_file_has_no_unredacted_secret",
    "redact_secrets_text",
    "acquire_watcher_lock", "release_watcher_lock",
    "_sanitized_env", "run",
    "record_quality_log_delta", "send_local_notification",
]
