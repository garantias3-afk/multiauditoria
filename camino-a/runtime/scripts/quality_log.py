#!/usr/bin/env python3
"""quality_log.py — provider/model quality log integration for Camino A/B.

The quality log is append-friendly evidence for model/provider performance. It
is written for every material audit-related event in the canonical runtime:
worker execution/skips, bundle accepted/rejected, internal-loop iterations and
manual submissions. Each entry is persisted twice:

* RUN/90_QUALITY_LOG_DELTA/*.entry.json  (portable append-only delta files)
* RUN/STATE/state.sqlite::quality_log    (queryable structured index)

The entry_id is deterministic for a supplied ``dedupe_key`` so repeated harvests
or re-entry do not produce duplicate rows for the same observation.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def safe_slug(value: str, *, fallback: str = "event") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())[:120].strip("._-")
    return slug or fallback


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

QUALITY_DIR_NAME = "90_QUALITY_LOG_DELTA"
SCHEMA_VERSION = "ai_quality_log_entry.v1"


def stable_entry_id(run_id: str, event: str, dedupe_key: str | None = None) -> str:
    if dedupe_key:
        payload = f"{run_id}|{event}|{dedupe_key}".encode("utf-8", "replace")
        return "ql_" + hashlib.sha256(payload).hexdigest()[:32]
    return "ql_" + uuid.uuid4().hex


def _normalise_auditor(auditor: dict[str, Any] | None = None, *, worker_id: str = "unknown") -> dict[str, Any]:
    auditor = dict(auditor or {})
    # Canonical fields are always present; unknowns stay explicit, never hidden.
    return {
        "slot_id": str(auditor.get("slot_id") or "NO_CONSTA"),
        "route_id": str(auditor.get("route_id") or auditor.get("route") or "NO_CONSTA"),
        "model_id": str(auditor.get("model_id") or auditor.get("model") or "NO_CONSTA"),
        "provider_id": str(auditor.get("provider_id") or auditor.get("provider") or worker_id),
        "provider_name": str(auditor.get("provider_name") or auditor.get("provider") or worker_id),
        "route": str(auditor.get("route") or "worker_bus"),
        "interface": str(auditor.get("interface") or "NO_CONSTA"),
        "cost_class": str(auditor.get("cost_class") or "unknown"),
        "role": str(auditor.get("role") or auditor.get("stage") or "auditor"),
        "worker_id": str(auditor.get("worker_id") or worker_id),
    }


def auditor_from_result(worker_id: str, result: dict[str, Any] | None = None,
                        manifest: dict[str, Any] | None = None,
                        *, stage: str = "") -> dict[str, Any]:
    result = dict(result or {})
    manifest = dict(manifest or {})
    embedded = result.get("auditor") if isinstance(result.get("auditor"), dict) else {}
    base = {
        "worker_id": result.get("worker_id") or worker_id,
        "slot_id": result.get("slot_id") or embedded.get("slot_id") or manifest.get("slot_id"),
        "route_id": result.get("route_id") or embedded.get("route_id") or manifest.get("route_id"),
        "model_id": result.get("model_id") or embedded.get("model_id") or result.get("model"),
        "provider_id": result.get("provider_id") or embedded.get("provider_id") or result.get("provider"),
        "provider_name": result.get("provider_name") or embedded.get("provider_name") or result.get("provider"),
        "route": result.get("route") or embedded.get("route") or manifest.get("stage") or stage,
        "interface": result.get("interface") or embedded.get("interface"),
        "cost_class": result.get("cost_class") or embedded.get("cost_class"),
        "role": result.get("role") or embedded.get("role") or stage or "auditor",
    }
    # Honest local defaults.
    if worker_id == "local_static":
        base.update({
            "route_id": base.get("route_id") or "local_static_reference",
            "model_id": base.get("model_id") or "local_static_ruleset",
            "provider_id": base.get("provider_id") or "local_static",
            "provider_name": base.get("provider_name") or "Local Static Worker",
            "route": base.get("route") or "local_static",
            "interface": base.get("interface") or "local_process",
            "cost_class": base.get("cost_class") or "free_local",
            "role": base.get("role") or "local_static_auditor",
        })
    if worker_id == "agentic_local":
        base.update({
            "route_id": base.get("route_id") or "agentic_local_reference",
            "model_id": base.get("model_id") or "agentic-local-deterministic",
            "provider_id": base.get("provider_id") or "local_reference",
            "provider_name": base.get("provider_name") or "Local Reference Agentic Worker",
            "route": base.get("route") or "internal_loop_runner",
            "interface": base.get("interface") or "local_process",
            "cost_class": base.get("cost_class") or "free_local",
            "role": base.get("role") or "agentic_internal_loop_reference",
        })
    return _normalise_auditor(base, worker_id=worker_id)


def build_quality_entry(run_dir: Path, *, event: str, auditor: dict[str, Any] | None = None,
                        artifact: dict[str, Any] | None = None,
                        finding: dict[str, Any] | None = None,
                        adjudication: dict[str, Any] | None = None,
                        details: dict[str, Any] | None = None,
                        audit_family: str = "camino_a_canonical_runtime",
                        dedupe_key: str | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    worker_id = str((auditor or {}).get("worker_id") or "unknown")
    auditor_n = _normalise_auditor(auditor, worker_id=worker_id)
    entry_id = stable_entry_id(run_dir.name, event, dedupe_key)
    finding = dict(finding or {})
    adjudication = dict(adjudication or {})
    return {
        "schema_version": SCHEMA_VERSION,
        "entry_id": entry_id,
        "created_at_utc": utc_now(),
        "run_id": run_dir.name,
        "audit_family": audit_family,
        "artifact": dict(artifact or {}),
        "auditor": auditor_n,
        "finding": {
            "id": str(finding.get("id") or event),
            "type": str(finding.get("type") or "meta"),
            "severity": str(finding.get("severity") or "info"),
            "summary": str(finding.get("summary") or event),
        },
        "adjudication": {
            "final_status": str(adjudication.get("final_status") or "PENDIENTE"),
            **{k: v for k, v in adjudication.items() if k != "final_status"},
        },
        "write_actor": {"name": "canonical_runtime"},
        "details": dict(details or {}),
    }


def record_quality_entry(run_dir: Path, entry: dict[str, Any], db: Any | None = None) -> Path:
    run_dir = Path(run_dir)
    qdir = run_dir / QUALITY_DIR_NAME
    qdir.mkdir(parents=True, exist_ok=True)
    entry_id = str(entry.get("entry_id") or stable_entry_id(run_dir.name, str(entry.get("event") or "event")))
    # Avoid duplicate files for the same deterministic entry_id.
    # BUG-1 FIX: sólo se usa el glob con el entry_id completo (35 chars).
    # El fallback con entry_id[-8:] fue eliminado: coincidía con los últimos
    # 8 hex de cualquier entry_id y producía falsos positivos (dos eventos
    # distintos que comparten los últimos 8 hex chars → el segundo era
    # silenciosamente descartado sin escribir su archivo delta).
    existing = sorted(qdir.glob(f"*_{entry_id}.entry.json"))
    if existing:
        path = existing[0]
    else:
        slug = safe_slug(str(entry.get("finding", {}).get("id") or "quality_event"))
        path = qdir / f"{utc_now_compact()}_{slug}_{entry_id}.entry.json"
        write_json(path, entry)
    if db is not None:
        try:
            db.record_quality_entry(entry)
        except AttributeError:
            pass
    return path


def record_quality_event(run_dir: Path, *, event: str, auditor: dict[str, Any] | None = None,
                         artifact: dict[str, Any] | None = None,
                         finding: dict[str, Any] | None = None,
                         adjudication: dict[str, Any] | None = None,
                         details: dict[str, Any] | None = None,
                         audit_family: str = "camino_a_canonical_runtime",
                         dedupe_key: str | None = None,
                         db: Any | None = None) -> dict[str, Any]:
    entry = build_quality_entry(
        run_dir, event=event, auditor=auditor, artifact=artifact,
        finding=finding, adjudication=adjudication, details=details,
        audit_family=audit_family, dedupe_key=dedupe_key,
    )
    path = record_quality_entry(run_dir, entry, db=db)
    entry["delta_path"] = str(path.relative_to(run_dir))
    return entry


def load_result_json(bundle: Path) -> dict[str, Any]:
    p = Path(bundle) / "result.json"
    if not p.exists():
        return {}
    return read_json(p, {})
