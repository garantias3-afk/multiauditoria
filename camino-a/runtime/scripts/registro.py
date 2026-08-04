"""registro.py — identity-complete quality-log recording (OT section 4 D5).

REUSES quality_log.record_quality_event (quality_log.py:184). Does NOT:
  - reduce the 10-field auditor schema (slot_id, route_id, model_id,
    provider_id, provider_name, route, interface, cost_class, role, worker_id)
    -> CONSERVED as-is, all defaulting to NO_CONSTA.
  - change stable_entry_id's dedup computation.

DECISION by Mariano (OT D5): option (a) + deuda. No cryptographic hash chain.
The runner keeps the existing dedup-only log and adds ONE optional field,
prev_entry_id, linking each entry to the previous one in the run for ordering
and traceability. The dedup hash is unchanged. The debt is recorded in the
report and here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# Reused, not reimplemented. Declared in the report with original path.
from scripts.quality_log import record_quality_event, stable_entry_id  # noqa: E402

# Hash-chain debt (decision a + prev_entry_id). See INFORME_RUNNER.md.
HASH_CHAIN_DEBT = (
    "DEUDA: el quality log NO encadena (no prev_hash/self_hash criptografico). "
    "Decision de Mariano: opcion (a) del OT D5 + campo prev_entry_id para "
    "trazabilidad/orden. El calculo dedup de stable_entry_id NO se modifica."
)


class RunRecorder:
    """Records quality-log entries for a run, threading prev_entry_id.

    Each call records one event with full identity and returns the entry dict
    (which includes its entry_id and the prev_entry_id of the prior call).
    """

    def __init__(self, run_dir: Path, *, audit_family: str = "camino_n_runner"):
        self.run_dir = Path(run_dir)
        self.audit_family = audit_family
        self._prev_entry_id: Optional[str] = None

    def record(
        self,
        *,
        event: str,
        auditor: Optional[dict[str, Any]] = None,
        artifact: Optional[dict[str, Any]] = None,
        finding: Optional[dict[str, Any]] = None,
        adjudication: Optional[dict[str, Any]] = None,
        details: Optional[dict[str, Any]] = None,
        dedupe_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record one event, reusing record_quality_event and adding prev_entry_id."""
        entry = record_quality_event(
            self.run_dir,
            event=event,
            auditor=auditor,
            artifact=artifact,
            finding=finding,
            adjudication=adjudication,
            details=details,
            audit_family=self.audit_family,
            dedupe_key=dedupe_key,
        )
        # Thread prev_entry_id WITHOUT altering the dedup hash. This is pure
        # metadata for ordering/provenance, recorded after the entry id is set.
        entry["prev_entry_id"] = self._prev_entry_id
        # Update the on-disk delta to include prev_entry_id. We append the
        # field to the already-written JSON without recomputing entry_id.
        delta_path = entry.get("delta_path")
        if delta_path:
            self._patch_delta(self.run_dir / delta_path, entry["prev_entry_id"])
        self._prev_entry_id = str(entry.get("entry_id") or "")
        return entry

    @staticmethod
    def _patch_delta(path: Path, prev_entry_id: Optional[str]) -> None:
        """Add prev_entry_id to an existing delta file in place.

        Uses the reused atomic-write primitive so the patch is crash-safe and
        does not leave a half-written delta. (drive_fuse.fuse_safe_write.)
        """
        import json
        from scripts.drive_fuse import fuse_safe_write
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        data["prev_entry_id"] = prev_entry_id
        fuse_safe_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    @property
    def last_entry_id(self) -> Optional[str]:
        return self._prev_entry_id


def build_auditor(
    *,
    route_id: str,
    model_id: str,
    provider_id: str,
    provider_name: str,
    cost_class: str,
    role: str,
    worker_id: str,
    slot_id: str,
    interface: str = "NO_CONSTA",
    route: str = "worker_bus",
) -> dict[str, Any]:
    """Build the 10-field auditor dict. All ten are required by the schema
    (quality_log._normalise_auditor); missing ones become NO_CONSTA, but the
    runner supplies them explicitly from the tabla so identity is complete."""
    return {
        "slot_id": str(slot_id or "NO_CONSTA"),
        "route_id": str(route_id or "NO_CONSTA"),
        "model_id": str(model_id or "NO_CONSTA"),
        "provider_id": str(provider_id or "NO_CONSTA"),
        "provider_name": str(provider_name or "NO_CONSTA"),
        "route": str(route or "worker_bus"),
        "interface": str(interface or "NO_CONSTA"),
        "cost_class": str(cost_class or "unknown"),
        "role": str(role or "auditor"),
        "worker_id": str(worker_id or "unknown"),
    }
