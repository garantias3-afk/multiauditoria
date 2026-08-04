"""exception_registro.py — the EXCEPTION REGISTRY record (OT sec 4 / E1).

11 fixed, bounded fields. The excerpt is HARD-CAPPED at 512 bytes (OT sec 4:
"NO NEGOCIABLE. Sin el, un solo archivo malformado se come el presupuesto de
contexto de la noche"). `found` carries path/size/hash/HTTP-code, NEVER content.
In FASE 1: resolution=NONE, handler_tried="" (we instrument, we do not repair).
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

EXCERPT_MAX_BYTES = 512  # OT sec 4 — hard cap, not negotiable.
TRUNCATED_MARKER = "[...TRUNCATED @512B...]"

# FASE values (OT sec 4 line 101).
FASES = ("despacho", "recoleccion", "validacion", "escritura", "gate")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate_excerpt(text: Any) -> str:
    """Cap at EXCERPT_MAX_BYTES (in BYTES, not chars) and mark truncation.

    The cap is in bytes because that's what bounds context/token cost. We
    encode utf-8, slice bytes, and re-decode safely.
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    b = s.encode("utf-8", errors="replace")
    if len(b) <= EXCERPT_MAX_BYTES:
        return s
    # Leave room for the marker within the cap.
    marker_b = TRUNCATED_MARKER.encode("utf-8")
    keep = EXCERPT_MAX_BYTES - len(marker_b)
    if keep <= 0:
        return TRUNCATED_MARKER[:EXCERPT_MAX_BYTES]
    sliced = b[:keep].decode("utf-8", errors="replace")
    return sliced + TRUNCATED_MARKER


def _found_for(path: Optional[Path], http_code: Optional[int]) -> str:
    """Describe WHAT was found (path/size/hash/http code), NEVER content.

    This is the §4 `found` field: ruta, tamano, hash, codigo HTTP. Content is
    excluded on purpose — that's what `excerpt` (capped) is for.
    """
    parts: list[str] = []
    if path is not None:
        try:
            p = Path(path)
            parts.append(f"path={p}")
            if p.exists():
                st = p.stat()
                parts.append(f"size={st.st_size}")
                # A cheap, stable fingerprint of the bytes, not the bytes.
                h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                parts.append(f"sha256_16={h}")
            else:
                parts.append("exists=false")
        except Exception as e:
            parts.append(f"path_inspect_error={type(e).__name__}")
    if http_code is not None:
        parts.append(f"http={int(http_code)}")
    return " ".join(parts) if parts else "NO_CONSTA"


@dataclass(frozen=True)
class ExceptionRegistro:
    """One observed exception. 11 fields (OT E1), all bounded."""
    exception_id: str            # uuid
    timestamp: str               # ISO UTC
    slot: str
    puesto: str
    route_id: str
    fase: str                    # one of FASES
    clase: str                   # from exception_taxonomy.CLASSES
    expected: str                # what the runner expected
    found: str                   # path/size/hash/http — never content
    excerpt: str                 # capped at 512 bytes, marked if truncated
    handler_tried: str = ""      # empty in FASE 1 (we do not repair)
    resolution: str = "NONE"     # NONE in FASE 1
    raw_condition: str = ""      # preserved when clase == UNMAPPED_CONDITION

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self.exception_id,
            "timestamp": self.timestamp,
            "slot": self.slot,
            "puesto": self.puesto,
            "route_id": self.route_id,
            "fase": self.fase,
            "clase": self.clase,
            "expected": self.expected,
            "found": self.found,
            "excerpt": self.excerpt,
            "excerpt_bytes": len(self.excerpt.encode("utf-8", errors="replace")),
            "handler_tried": self.handler_tried,
            "resolution": self.resolution,
            "raw_condition": self.raw_condition,
        }


def build_registro(
    *,
    slot: str,
    puesto: str,
    route_id: str,
    fase: str,
    clase: str,
    expected: str,
    excerpt: Any,
    found_path: Optional[Path] = None,
    http_code: Optional[int] = None,
    raw_condition: str = "",
    handler_tried: str = "",
    resolution: str = "NONE",
) -> ExceptionRegistro:
    """Build a registro with the excerpt cap and content-free `found`.

    In FASE 1 the caller passes handler_tried="" and resolution="NONE" (the
    defaults): we instrument, we do not repair.
    """
    if fase not in FASES:
        # fase is a controlled vocabulary; an unknown value is a bug in the
        # caller, but we never let it crash the instrumentation path. Record it.
        fase = f"UNKNOWN({fase})"
    return ExceptionRegistro(
        exception_id=str(uuid.uuid4()),
        timestamp=_utc_now(),
        slot=str(slot or "NO_CONSTA"),
        puesto=str(puesto or "NO_CONSTA"),
        route_id=str(route_id or "NO_CONSTA"),
        fase=fase,
        clase=str(clase or "UNMAPPED_CONDITION"),
        expected=str(expected or "NO_CONSTA"),
        found=_found_for(found_path, http_code),
        excerpt=_truncate_excerpt(excerpt),
        handler_tried=handler_tried,
        resolution=resolution,
        raw_condition=raw_condition,
    )


# Sanity: the 11 named fields are exactly the OT sec 4 set.
EXPECTED_FIELDS = (
    "exception_id", "timestamp", "slot", "puesto", "route_id", "fase",
    "clase", "expected", "found", "excerpt", "handler_tried",
)
