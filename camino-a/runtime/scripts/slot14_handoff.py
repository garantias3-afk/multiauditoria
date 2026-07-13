#!/usr/bin/env python3
"""Hash-bound, differential handoff from canonical slot 13 to slot 14.

The handoff is deliberately transport-neutral.  Camino A can materialize it in
an isolated CLI workspace, while Camino B can carry the same request reference
and SHA through its Gateway bridge.  The JSON request is the authority; the
Markdown and bounded textual diff are derived review aids.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.candidate_updates import CandidateUpdateError, hash_candidate_tree


SCHEMA_VERSION = "camino_slot14_audit_request.v1"
REQUIRED_COMPLETED_SLOTS = tuple(str(value) for value in range(1, 14))
HANDOFF_RELATIVE_DIR = Path("STATE") / "slot14_handoff"
REQUEST_FILENAME = "SLOT_14_AUDIT_REQUEST.json"
MARKDOWN_FILENAME = "SLOT_14_AUDIT_REQUEST.md"
DIFF_FILENAME = "CANDIDATE_DIFF.diff"
DEFAULT_MAX_DIFF_CHARS = 60_000
DEFAULT_MAX_TEXT_FILE_BYTES = 512 * 1024
SHA256_RE_LENGTH = 64


class Slot14HandoffError(RuntimeError):
    """Raised when a slot-14 request cannot be built without ambiguity."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == SHA256_RE_LENGTH and all(ch in "0123456789abcdef" for ch in text)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise Slot14HandoffError(f"handoff_path_symlink_rejected:{path}")
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _require_exact_transition_state(run_dir: Path, state: Mapping[str, Any]) -> str:
    run_id = str(state.get("run_id") or "")
    if run_id != run_dir.name:
        raise Slot14HandoffError(
            f"run_id_mismatch:state={run_id or 'missing'}:directory={run_dir.name}"
        )
    completed = tuple(str(value) for value in (state.get("completed_slots") or []))
    if completed != REQUIRED_COMPLETED_SLOTS:
        raise Slot14HandoffError(
            "completed_slots_must_be_exactly_1_to_13_in_order"
        )
    return run_id


def _tree_index(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise Slot14HandoffError(f"tree_missing_or_symlink:{root}")
    index: dict[str, dict[str, Any]] = {}
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if item.is_symlink():
            raise Slot14HandoffError(f"tree_symlink_rejected:{relative}")
        if not item.is_file():
            continue
        index[relative] = {
            "sha256": _sha256_file(item),
            "size_bytes": item.stat().st_size,
        }
    return index


def _build_file_manifest(
    baseline: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    manifest: dict[str, list[dict[str, Any]]] = {
        "added": [], "modified": [], "deleted": [], "unchanged": [],
    }
    for path in sorted(set(baseline) | set(candidate)):
        before = baseline.get(path)
        after = candidate.get(path)
        if before is None:
            manifest["added"].append({
                "path": path,
                "candidate_sha256": after["sha256"],
                "candidate_size_bytes": after["size_bytes"],
            })
        elif after is None:
            manifest["deleted"].append({
                "path": path,
                "baseline_sha256": before["sha256"],
                "baseline_size_bytes": before["size_bytes"],
            })
        elif before["sha256"] != after["sha256"]:
            manifest["modified"].append({
                "path": path,
                "baseline_sha256": before["sha256"],
                "baseline_size_bytes": before["size_bytes"],
                "candidate_sha256": after["sha256"],
                "candidate_size_bytes": after["size_bytes"],
            })
        else:
            manifest["unchanged"].append({
                "path": path,
                "sha256": after["sha256"],
                "size_bytes": after["size_bytes"],
            })
    return manifest


def _read_text_for_diff(path: Path, max_bytes: int) -> tuple[str | None, str | None]:
    if not path.is_file():
        return "", None
    size = path.stat().st_size
    if size > max_bytes:
        return None, f"oversize:{size}>{max_bytes}"
    content = path.read_bytes()
    if b"\x00" in content:
        return None, "binary_nul"
    try:
        return content.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "not_utf8"


def _bounded_text_diff(
    baseline_root: Path,
    candidate_root: Path,
    manifest: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    baseline_sha256: str,
    candidate_sha256: str,
    max_chars: int,
    max_text_file_bytes: int,
) -> tuple[str, list[str], list[dict[str, str]]]:
    if max_chars < 1024:
        raise Slot14HandoffError("max_diff_chars_must_be_at_least_1024")
    header = (
        "# Bounded candidate diff for slot 14\n"
        f"# baseline_sha256={baseline_sha256}\n"
        f"# candidate_sha256={candidate_sha256}\n"
        "# The JSON file manifest is authoritative when a textual diff is omitted.\n\n"
    )
    included: list[str] = []
    omitted: list[dict[str, str]] = []
    blocks: list[str] = []
    used = len(header)
    footer_reserve = 256

    changed = [
        (status, entry)
        for status in ("added", "modified", "deleted")
        for entry in manifest.get(status, [])
    ]
    for status, entry in changed:
        relative = str(entry["path"])
        before_path = baseline_root / relative
        after_path = candidate_root / relative
        before, before_error = _read_text_for_diff(before_path, max_text_file_bytes)
        after, after_error = _read_text_for_diff(after_path, max_text_file_bytes)
        error = before_error or after_error
        if error:
            marker = f"# TEXT_DIFF_OMITTED {json.dumps(relative, ensure_ascii=False)} reason={error}\n"
            omitted.append({"path": relative, "reason": error})
            if used + len(marker) + footer_reserve <= max_chars:
                blocks.append(marker)
                used += len(marker)
            continue

        safe_label = json.dumps(relative, ensure_ascii=False)
        block = "".join(difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=f"baseline/{safe_label}",
            tofile=f"candidate/{safe_label}",
            lineterm="\n",
        ))
        if block and not block.endswith("\n"):
            block += "\n"
        if used + len(block) + footer_reserve <= max_chars:
            blocks.append(block)
            used += len(block)
            included.append(relative)
        else:
            omitted.append({"path": relative, "reason": "global_diff_budget"})

    footer = (
        "\n# Diff coverage\n"
        f"# included_textual_paths={len(included)}\n"
        f"# omitted_textual_paths={len(omitted)}\n"
        "# Consult SLOT_14_AUDIT_REQUEST.json for the complete file manifest and omission reasons.\n"
    )
    result = header + "".join(blocks) + footer
    if len(result) > max_chars:
        # This can only happen with an unusually small budget and keeps the
        # artifact honest instead of silently exceeding its declared bound.
        marker = "\n# TRUNCATED_TO_DECLARED_MAX_DIFF_CHARS\n"
        result = result[: max_chars - len(marker)] + marker
    return result, included, omitted


def _compact_prior_evidence(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in state.get("history") or []:
        if not isinstance(event, Mapping) or event.get("event") != "canonical_slot_completed":
            continue
        slot_id = str(event.get("slot_id") or "")
        if slot_id not in REQUIRED_COMPLETED_SLOTS:
            continue
        compact: list[dict[str, Any]] = []
        for raw in (event.get("evidence") or [])[:16]:
            if not isinstance(raw, Mapping):
                continue
            compact.append({
                key: raw.get(key)
                for key in (
                    "lane", "bundle", "route_id", "status",
                    "findings_count", "residual_debt_count",
                    "candidate_sha256",
                )
                if raw.get(key) is not None
            })
        latest[slot_id] = {
            "slot_id": slot_id,
            "completed_at_utc": str(event.get("at") or "NO_CONSTA"),
            "evidence": compact,
            "evidence_count": len(event.get("evidence") or []),
            "note": (
                "Prior evidence is an indexed claim, not proof for slot 14."
                if compact else
                "Slot completed without indexed external evidence; do not infer coverage."
            ),
        }
    return [
        latest.get(slot_id, {
            "slot_id": slot_id,
            "completed_at_utc": "NO_CONSTA",
            "evidence": [],
            "evidence_count": 0,
            "note": "No compact prior-evidence record found; do not infer coverage.",
        })
        for slot_id in REQUIRED_COMPLETED_SLOTS
    ]


def _compact_residual_risks(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for raw in (state.get("residual_debt") or [])[:100]:
        if not isinstance(raw, Mapping):
            continue
        routes = raw.get("routes") if isinstance(raw.get("routes"), list) else []
        risks.append({
            "slot_id": str(raw.get("slot_id") or "NO_CONSTA"),
            "role": str(raw.get("role") or "NO_CONSTA"),
            "reason": str(raw.get("reason") or "NO_CONSTA"),
            "routes": [str(value) for value in routes[:16]],
            "recorded_at_utc": str(raw.get("recorded_at_utc") or "NO_CONSTA"),
        })
    return risks


def _render_markdown(request: Mapping[str, Any]) -> str:
    summary = request["diff_summary"]
    manifest = request["file_manifest"]
    changed_paths = [
        str(item["path"])
        for status in ("added", "modified", "deleted")
        for item in manifest[status]
    ]
    listed = changed_paths[:200]
    lines = [
        "# Slot 14 — pedido diferencial adversarial",
        "",
        "> El objetivo es intentar refutar que el candidato esté listo para cerrar; no confirmar una conclusión previa.",
        "",
        "## Identidad vinculante",
        "",
        f"- run_id: `{request['run_id']}`",
        f"- path_id: `{request['path_id']}`",
        f"- source_slot_id: `13`",
        f"- slot_id: `14`",
        f"- baseline_candidate_sha256: `{request['baseline_candidate_sha256']}`",
        f"- candidate_sha256: `{request['candidate_sha256']}`",
        f"- diff_sha256: `{request['artifacts']['diff']['sha256']}`",
        "",
        "## Diferencia desde el seed inmutable",
        "",
        f"- added: {summary['added']}",
        f"- modified: {summary['modified']}",
        f"- deleted: {summary['deleted']}",
        f"- unchanged: {summary['unchanged']}",
        f"- diff textual acotado: `{request['artifacts']['diff']['path']}`",
        "",
        "### Rutas cambiadas",
        "",
    ]
    lines.extend(f"- `{path}`" for path in listed)
    if len(changed_paths) > len(listed):
        lines.append(f"- ... {len(changed_paths) - len(listed)} rutas adicionales constan en el JSON")
    if not changed_paths:
        lines.append("- Ninguna; confirmar frescura de evidencia y riesgos residuales.")

    lines += [
        "",
        "## Metodología obligatoria anti-sesgo",
        "",
        "1. Antes de tomar como válidos los veredictos previos, formular al menos tres hipótesis falsables de fallo.",
        "2. Tratar cada resultado previo como claim no confiable hasta ligarlo por SHA o reproducirlo.",
        "3. Buscar contraejemplos en cambios, dependientes directos y fronteras de autoridad/hash/auth/fallback.",
        "4. Ejecutar al menos un control negativo relevante; registrar resultado y evidencia.",
        "5. Separar OBSERVADO, INFERIDO y NO_PROBADO. Una ausencia de evidencia obliga INSUFFICIENT_EVIDENCE.",
        "6. No aprobar si queda una hipótesis sin resolver, un riesgo residual bloqueante o una exclusión material.",
        "",
        "## Alcance económico de tokens",
        "",
        "- Revisar todos los added/modified/deleted y sus dependientes directos.",
        "- Reusar recibos previos sólo por identidad/hash; no repetir suites estables salvo impacto transversal o evidencia obsoleta.",
        "- Revalidar siempre autoridad terminal, binding run/slot/candidate, manifest/DONE, prohibición de API y orden Claude→fallback.",
        "- Los archivos unchanged son de menor prioridad, no prueba de corrección; muestrear fronteras de alto riesgo.",
        "- Excluir paquetes históricos, caches y logs crudos no referenciados por el índice de evidencia.",
        "",
        "## Evidencia ya recorrida (no constituye verdad)",
        "",
        "| Slot | Registros | Nota |",
        "|---:|---:|---|",
    ]
    for item in request["prior_evidence_index"]:
        lines.append(f"| {item['slot_id']} | {item['evidence_count']} | {item['note']} |")
    lines += [
        "",
        "## Riesgos residuales declarados",
        "",
    ]
    risks = request["residual_risks"]
    if risks:
        lines.extend(
            f"- slot {item['slot_id']}: {item['reason']}" for item in risks[:50]
        )
    else:
        lines.append("- Ninguno registrado; esto no equivale a riesgo cero.")
    lines += [
        "",
        "## Salida mínima",
        "",
        "Devolver exactamente el esquema del worker: audit_request_sha256, verdict, summary, findings, corrections_applied, tests, falsification_attempts e independent_checks. Cada falsification_attempt debe incluir hipótesis, intento, resultado y evidencia; independent_checks debe incluir al menos un control negativo. En summary separar OBSERVADO/INFERIDO/NO_PROBADO y declarar evidencia consultada, exclusiones efectivas y riesgo residual. Sólo una revisión limpia, independiente y ligada al SHA puede aprobar.",
        "",
    ]
    return "\n".join(lines)


def _relative_artifact(path: Path, run_dir: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _receipt_from_paths(run_dir: Path) -> dict[str, Any]:
    handoff = run_dir / HANDOFF_RELATIVE_DIR
    request_path = handoff / REQUEST_FILENAME
    markdown_path = handoff / MARKDOWN_FILENAME
    diff_path = handoff / DIFF_FILENAME
    request_sha = _sha256_file(request_path)
    return {
        "request_path": _relative_artifact(request_path, run_dir),
        "request_sha256": request_sha,
        "diff_path": _relative_artifact(diff_path, run_dir),
        "diff_sha256": _sha256_file(diff_path),
        "markdown_path": _relative_artifact(markdown_path, run_dir),
        "markdown_sha256": _sha256_file(markdown_path),
        # Camino B bridge aliases. If both alias and canonical fields are sent,
        # validation requires them to be identical.
        "slot14_audit_request_ref": _relative_artifact(request_path, run_dir),
        "slot14_audit_request_sha256": request_sha,
        "source_slot_id": "13",
        "slot_id": "14",
        "prior_slots_complete": True,
    }


def ensure_slot14_handoff(
    run_dir: Path,
    state: Mapping[str, Any],
    *,
    path_id: str = "camino_a",
    max_diff_chars: int = DEFAULT_MAX_DIFF_CHARS,
    max_text_file_bytes: int = DEFAULT_MAX_TEXT_FILE_BYTES,
) -> dict[str, Any]:
    """Create or reuse the immutable request for the exact slot-13→14 state."""
    run_dir = Path(run_dir).resolve()
    run_id = _require_exact_transition_state(run_dir, state)
    if path_id not in {"camino_a", "camino_b"}:
        raise Slot14HandoffError(f"path_id_invalid:{path_id}")

    baseline_root = run_dir / "INPUT" / "target_snapshot"
    candidate_root = run_dir / "00_CANDIDATE"
    if (run_dir / "INPUT").is_symlink() or (run_dir / "STATE").is_symlink():
        raise Slot14HandoffError("run_control_directory_symlink_rejected")
    try:
        baseline_sha = hash_candidate_tree(baseline_root)
        candidate_sha = hash_candidate_tree(candidate_root)
    except CandidateUpdateError as exc:
        raise Slot14HandoffError(str(exc)) from exc
    expected_candidate = str(state.get("current_candidate_sha256") or "").lower()
    if not _is_sha256(expected_candidate) or expected_candidate != candidate_sha:
        raise Slot14HandoffError(
            f"candidate_tree_sha256_mismatch:actual={candidate_sha}:expected={expected_candidate}"
        )

    handoff_dir = run_dir / HANDOFF_RELATIVE_DIR
    if handoff_dir.is_symlink():
        raise Slot14HandoffError("handoff_directory_symlink_rejected")
    request_path = handoff_dir / REQUEST_FILENAME
    if request_path.is_file() and not request_path.is_symlink():
        try:
            existing = json.loads(request_path.read_text(encoding="utf-8"))
            existing_receipt = _receipt_from_paths(run_dir)
            probe_job = {
                **existing_receipt,
                "run_id": run_id,
                "candidate_sha256": candidate_sha,
            }
            ok, _, _ = validate_slot14_handoff_binding(run_dir, probe_job)
            if ok and existing.get("path_id") == path_id:
                return existing_receipt
        except (OSError, ValueError, KeyError):
            pass

    baseline_index = _tree_index(baseline_root)
    candidate_index = _tree_index(candidate_root)
    manifest = _build_file_manifest(baseline_index, candidate_index)
    diff_text, included_paths, omitted_paths = _bounded_text_diff(
        baseline_root,
        candidate_root,
        manifest,
        baseline_sha256=baseline_sha,
        candidate_sha256=candidate_sha,
        max_chars=max_diff_chars,
        max_text_file_bytes=max_text_file_bytes,
    )
    diff_bytes = diff_text.encode("utf-8")
    diff_path = handoff_dir / DIFF_FILENAME
    _atomic_write(diff_path, diff_bytes)

    request: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "run_id": run_id,
        "path_id": path_id,
        "source_slot_id": "13",
        "slot_id": "14",
        "prior_slots_complete": True,
        "completed_slots": list(REQUIRED_COMPLETED_SLOTS),
        "baseline_policy": "INPUT/target_snapshot_vs_00_CANDIDATE",
        "baseline_candidate_sha256": baseline_sha,
        "candidate_sha256": candidate_sha,
        "diff_summary": {
            status: len(manifest[status])
            for status in ("added", "modified", "deleted", "unchanged")
        },
        "file_manifest": manifest,
        "text_diff_coverage": {
            "max_chars": max_diff_chars,
            "max_text_file_bytes": max_text_file_bytes,
            "included_paths": included_paths,
            "omitted_paths": omitted_paths,
        },
        "prior_evidence_index": _compact_prior_evidence(state),
        "residual_risks": _compact_residual_risks(state),
        "scope": {
            "must_review": [
                "all added, modified and deleted paths",
                "direct dependants of changed paths",
                "residual risks and missing prior evidence",
                "terminal authority and run/slot/candidate/hash bindings",
                "subscription-only Claude primary and Codex fallback order",
            ],
            "deprioritized_not_trusted": [
                "unchanged low-risk files outside changed dependency boundaries",
                "historical packages, caches and unreferenced raw logs",
                "stable tests unrelated to the diff unless a cross-cutting invariant changed",
            ],
        },
        "anti_confirmation_methodology": {
            "objective": "attempt_to_falsify_closure_readiness",
            "prior_results_are_claims_not_truth": True,
            "minimum_falsifiable_hypotheses": 3,
            "minimum_negative_controls": 1,
            "require_counterexample_search": True,
            "require_observed_inferred_unverified_separation": True,
            "require_unresolved_hypotheses_forbid_approval": True,
            "missing_evidence_verdict": "INSUFFICIENT_EVIDENCE",
        },
        "required_output": [
            "audit_request_sha256",
            "verdict",
            "summary",
            "falsification_attempts",
            "independent_checks",
            "tests",
            "findings",
            "corrections_applied",
        ],
        "required_output_semantics": {
            "falsification_attempts": "Each entry states a falsifiable hypothesis, attempt, outcome and evidence.",
            "independent_checks": "At least one entry is a relevant negative control with outcome and evidence.",
            "summary": "Separate OBSERVED, INFERRED and UNTESTED; include evidence read, effective exclusions and residual risk.",
        },
        "artifacts": {
            "diff": {
                "path": _relative_artifact(diff_path, run_dir),
                "sha256": _sha256_bytes(diff_bytes),
                "size_bytes": len(diff_bytes),
            },
        },
    }
    markdown = _render_markdown(request).encode("utf-8")
    markdown_path = handoff_dir / MARKDOWN_FILENAME
    _atomic_write(markdown_path, markdown)
    request["artifacts"]["markdown"] = {
        "path": _relative_artifact(markdown_path, run_dir),
        "sha256": _sha256_bytes(markdown),
        "size_bytes": len(markdown),
    }
    request_bytes = (
        json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write(request_path, request_bytes)
    return _receipt_from_paths(run_dir)


def _resolve_job_binding(job: Mapping[str, Any]) -> tuple[str, str, str, str]:
    request_path = str(job.get("request_path") or "")
    request_alias = str(job.get("slot14_audit_request_ref") or "")
    request_sha = str(job.get("request_sha256") or "").lower()
    request_sha_alias = str(job.get("slot14_audit_request_sha256") or "").lower()
    if request_path and request_alias and request_path != request_alias:
        raise Slot14HandoffError("request_path_alias_mismatch")
    if request_sha and request_sha_alias and request_sha != request_sha_alias:
        raise Slot14HandoffError("request_sha256_alias_mismatch")
    request_path = request_path or request_alias
    request_sha = request_sha or request_sha_alias
    diff_path = str(job.get("diff_path") or "")
    diff_sha = str(job.get("diff_sha256") or "").lower()
    if not request_path or not _is_sha256(request_sha):
        raise Slot14HandoffError("request_path_or_sha256_missing")
    if not diff_path or not _is_sha256(diff_sha):
        raise Slot14HandoffError("diff_path_or_sha256_missing")
    return request_path, request_sha, diff_path, diff_sha


def _exact_artifact_path(run_dir: Path, value: str, filename: str) -> Path:
    expected_relative = (HANDOFF_RELATIVE_DIR / filename).as_posix()
    if value != expected_relative:
        raise Slot14HandoffError(f"artifact_path_invalid:{value}")
    raw_base = run_dir / HANDOFF_RELATIVE_DIR
    if (run_dir / "STATE").is_symlink() or raw_base.is_symlink():
        raise Slot14HandoffError("handoff_directory_symlink_rejected")
    base = raw_base.resolve()
    path = run_dir / value
    if path.is_symlink() or not path.is_file():
        raise Slot14HandoffError(f"artifact_missing_or_symlink:{value}")
    resolved = path.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise Slot14HandoffError(f"artifact_path_escape:{value}") from exc
    return resolved


def validate_slot14_handoff_binding(
    run_dir: Path,
    job: Mapping[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Validate path, hashes, run and current candidate for a dispatched job."""
    try:
        run_dir = Path(run_dir).resolve()
        request_ref, expected_request_sha, diff_ref, expected_diff_sha = _resolve_job_binding(job)
        request_path = _exact_artifact_path(run_dir, request_ref, REQUEST_FILENAME)
        diff_path = _exact_artifact_path(run_dir, diff_ref, DIFF_FILENAME)
        if _sha256_file(request_path) != expected_request_sha:
            raise Slot14HandoffError("request_sha256_mismatch")
        if _sha256_file(diff_path) != expected_diff_sha:
            raise Slot14HandoffError("diff_sha256_mismatch")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or request.get("schema_version") != SCHEMA_VERSION:
            raise Slot14HandoffError("request_schema_invalid")
        if str(job.get("run_id") or "") != run_dir.name:
            raise Slot14HandoffError("job_run_id_mismatch")
        if str(job.get("source_slot_id") or "") != "13":
            raise Slot14HandoffError("job_source_slot_id_mismatch")
        if str(job.get("slot_id") or "") != "14":
            raise Slot14HandoffError("job_slot_id_mismatch")
        if job.get("prior_slots_complete") is not True:
            raise Slot14HandoffError("job_prior_slots_complete_required")
        if request.get("run_id") != run_dir.name:
            raise Slot14HandoffError("request_run_id_mismatch")
        if request.get("path_id") not in {"camino_a", "camino_b"}:
            raise Slot14HandoffError("request_path_id_invalid")
        if request.get("source_slot_id") != "13" or request.get("slot_id") != "14":
            raise Slot14HandoffError("request_transition_invalid")
        if request.get("prior_slots_complete") is not True:
            raise Slot14HandoffError("request_prior_slots_complete_missing")
        if tuple(str(value) for value in request.get("completed_slots") or []) != REQUIRED_COMPLETED_SLOTS:
            raise Slot14HandoffError("request_completed_slots_invalid")

        candidate_sha = str(job.get("candidate_sha256") or "").lower()
        if not _is_sha256(candidate_sha) or request.get("candidate_sha256") != candidate_sha:
            raise Slot14HandoffError("job_request_candidate_sha256_mismatch")
        actual_candidate = hash_candidate_tree(run_dir / "00_CANDIDATE")
        if actual_candidate != candidate_sha:
            raise Slot14HandoffError("candidate_tree_sha256_mismatch")
        actual_baseline = hash_candidate_tree(run_dir / "INPUT" / "target_snapshot")
        if request.get("baseline_candidate_sha256") != actual_baseline:
            raise Slot14HandoffError("baseline_tree_sha256_mismatch")

        artifacts = request.get("artifacts")
        if not isinstance(artifacts, dict):
            raise Slot14HandoffError("request_artifacts_invalid")
        diff_meta = artifacts.get("diff")
        markdown_meta = artifacts.get("markdown")
        if not isinstance(diff_meta, dict) or not isinstance(markdown_meta, dict):
            raise Slot14HandoffError("request_artifacts_invalid")
        if diff_meta.get("path") != diff_ref or diff_meta.get("sha256") != expected_diff_sha:
            raise Slot14HandoffError("request_diff_binding_mismatch")
        markdown_path = _exact_artifact_path(
            run_dir, str(markdown_meta.get("path") or ""), MARKDOWN_FILENAME,
        )
        if not _is_sha256(markdown_meta.get("sha256")) or _sha256_file(markdown_path) != markdown_meta.get("sha256"):
            raise Slot14HandoffError("markdown_sha256_mismatch")

        expected_manifest = _build_file_manifest(
            _tree_index(run_dir / "INPUT" / "target_snapshot"),
            _tree_index(run_dir / "00_CANDIDATE"),
        )
        if request.get("file_manifest") != expected_manifest:
            raise Slot14HandoffError("request_file_manifest_mismatch")
        expected_summary = {
            status: len(expected_manifest[status])
            for status in ("added", "modified", "deleted", "unchanged")
        }
        if request.get("diff_summary") != expected_summary:
            raise Slot14HandoffError("request_diff_summary_mismatch")
        coverage = request.get("text_diff_coverage")
        if not isinstance(coverage, dict):
            raise Slot14HandoffError("request_text_diff_coverage_invalid")
        try:
            regenerated_diff, included, omitted = _bounded_text_diff(
                run_dir / "INPUT" / "target_snapshot",
                run_dir / "00_CANDIDATE",
                expected_manifest,
                baseline_sha256=actual_baseline,
                candidate_sha256=actual_candidate,
                max_chars=int(coverage.get("max_chars")),
                max_text_file_bytes=int(coverage.get("max_text_file_bytes")),
            )
        except (TypeError, ValueError) as exc:
            raise Slot14HandoffError("request_text_diff_coverage_invalid") from exc
        if (
            _sha256_bytes(regenerated_diff.encode("utf-8")) != expected_diff_sha
            or coverage.get("included_paths") != included
            or coverage.get("omitted_paths") != omitted
        ):
            raise Slot14HandoffError("request_text_diff_content_mismatch")
        methodology = request.get("anti_confirmation_methodology")
        if not isinstance(methodology, dict) or (
            methodology.get("prior_results_are_claims_not_truth") is not True
            or int(methodology.get("minimum_falsifiable_hypotheses") or 0) < 3
            or int(methodology.get("minimum_negative_controls") or 0) < 1
            or methodology.get("require_counterexample_search") is not True
        ):
            raise Slot14HandoffError("anti_confirmation_methodology_invalid")
        return True, "ok", request
    except (CandidateUpdateError, json.JSONDecodeError, OSError, Slot14HandoffError) as exc:
        return False, str(exc), {}


def materialize_slot14_handoff(
    run_dir: Path,
    workspace: Path,
    job: Mapping[str, Any],
) -> tuple[bool, str]:
    """Copy the validated request bundle into an isolated worker overlay."""
    ok, reason, request = validate_slot14_handoff_binding(run_dir, job)
    if not ok:
        return False, reason
    workspace = Path(workspace)
    if not workspace.is_dir() or workspace.is_symlink():
        return False, "workspace_missing_or_symlink"
    overlay_root = workspace / ".camino_runtime"
    if overlay_root.is_symlink():
        return False, "materialization_overlay_symlink"
    destination = overlay_root / "slot14_handoff"
    if destination.is_symlink():
        return False, "materialization_destination_symlink"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    run_dir = Path(run_dir).resolve()
    copies = (
        (run_dir / str(job.get("request_path") or job.get("slot14_audit_request_ref")), REQUEST_FILENAME),
        (run_dir / str(job.get("diff_path")), DIFF_FILENAME),
        (run_dir / str(request["artifacts"]["markdown"]["path"]), MARKDOWN_FILENAME),
    )
    try:
        for source, name in copies:
            if source.is_symlink() or not source.is_file():
                return False, f"materialization_source_invalid:{name}"
            shutil.copy2(source, destination / name)
        if _sha256_file(destination / REQUEST_FILENAME) != str(
            job.get("request_sha256") or job.get("slot14_audit_request_sha256")
        ).lower():
            return False, "materialized_request_sha256_mismatch"
        if _sha256_file(destination / DIFF_FILENAME) != str(job.get("diff_sha256") or "").lower():
            return False, "materialized_diff_sha256_mismatch"
        return True, "ok"
    except OSError as exc:
        return False, f"materialization_failed:{type(exc).__name__}:{exc}"


__all__ = [
    "DIFF_FILENAME",
    "MARKDOWN_FILENAME",
    "REQUEST_FILENAME",
    "SCHEMA_VERSION",
    "Slot14HandoffError",
    "ensure_slot14_handoff",
    "materialize_slot14_handoff",
    "validate_slot14_handoff_binding",
]
