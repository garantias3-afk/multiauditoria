#!/usr/bin/env python3
"""Offline contract test for the GPT Cerebro Action surface.

The path set mirrors the public gateway's declared ``implemented_paths``.  This
does not replace a credentialed live smoke, but prevents the previously observed
context-pack/manifest/search drift from returning.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "actions" / "CAMINO_A_CEREBRO_ACTIONS.v1.yaml"

REQUIRED_OPERATION_IDS = {
    "getGatewayHealth",
    "getCurrentCaminoAKnowledge",
    "getCaminoAKnowledgeChunk",
    "getCaminoARunStatus",
    "getNextCaminoABrainTask",
    "getCaminoABrainContextPack",
    "listCaminoABrainTaskFiles",
    "getCaminoABrainTaskFileManifest",
    "searchCaminoABrainTaskFile",
    "readCaminoABrainTaskFileChunk",
    "startCaminoABrainArtifactUpload",
    "getCaminoABrainArtifactUploadState",
    "uploadCaminoABrainArtifactChunk",
    "finalizeCaminoABrainArtifactUpload",
    "submitCaminoABrainTaskResult",
}

EXPECTED_PATHS = {
    "/health",
    "/camino-a/knowledge/current",
    "/camino-a/knowledge/current/chunk",
    "/camino-a/runs/{run_id}/status",
    "/camino-a/runs/{run_id}/brain/tasks/next",
    "/camino-a/runs/{run_id}/context-pack",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/files",
    "/camino-a/runs/{run_id}/files/{file_id}/manifest",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/files/{file_id}",
    "/camino-a/runs/{run_id}/files/{file_id}/search",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/start",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/{upload_id}",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/{upload_id}/chunks",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/{upload_id}/finalize",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/result",
}

FORBIDDEN_STRINGS = {
    "createAuditRun",
    "uploadTargetFile",
    "/sandbox/upload",
    "startExternalAudits",
    "approveReservedProvider",
    "resolveFinding",
    "anthropic_claude",
    "openai_api",
    "api.openai.com",
    "api.anthropic.com",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/context-pack",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/files/{file_id}/manifest",
    "/camino-a/runs/{run_id}/brain/tasks/{task_id}/files/{file_id}/search",
}


def _run_id_pattern(text: str) -> str:
    match = re.search(
        r"RunId:\s*.*?pattern:\s*'([^']+)'",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("RunId pattern absent")
    return match.group(1)


def _invalid_plain_scalar_colons(text: str) -> list[int]:
    """Catch YAML plain scalars containing the forbidden ``: `` sequence.

    This is intentionally small and dependency-free. Inline maps/arrays, quoted
    scalars and block scalars are excluded; their colons are valid YAML.
    """
    bad: list[int] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#") or ": " not in stripped:
            continue
        key, value = stripped.split(": ", 1)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or not value:
            continue
        if value.startswith(("'", '"', "{", "[", ">", "|")):
            continue
        if ": " in value:
            bad.append(line_number)
    return bad


def main() -> int:
    text = SPEC.read_text(encoding="utf-8")
    ops = set(re.findall(r"operationId:\s*([A-Za-z0-9_]+)", text))
    path_lines = [line.strip() for line in text.splitlines() if line.startswith("  /")]
    paths = {line[:-1] if line.endswith(":") else line for line in path_lines}
    failures = []

    missing = sorted(REQUIRED_OPERATION_IDS - ops)
    extra_paths = sorted(paths - EXPECTED_PATHS)
    missing_paths = sorted(EXPECTED_PATHS - paths)
    forbidden = sorted(item for item in FORBIDDEN_STRINGS if item in text)
    if missing:
        failures.append("missing operationIds: %s" % missing)
    if extra_paths or missing_paths:
        failures.append("path drift: missing=%s extra=%s" % (missing_paths, extra_paths))
    if forbidden:
        failures.append("forbidden/stale strings present: %s" % forbidden)
    if "content: {type: string, maxLength: 32768}" not in text:
        failures.append("inline artifact limit 32768 not found")
    invalid_plain_scalars = _invalid_plain_scalar_colons(text)
    if invalid_plain_scalars:
        failures.append(
            "YAML plain scalars contain invalid colon-space at lines: %s"
            % invalid_plain_scalars
        )
    if re.search(r"-\s*\{\$ref:\s*['\"]#/components/parameters/", text):
        failures.append(
            "component parameter refs are forbidden: GPT Builder skips those functions; "
            "inline every path parameter"
        )

    try:
        run_id_re = re.compile(_run_id_pattern(text))
    except (ValueError, re.error) as exc:
        failures.append("invalid RunId pattern: %s" % exc)
    else:
        valid_ids = [
            "RUN_20260710_165033_67488",
            "RUN_20260710_165033_44f72_canon_multiaudit",
            "RUN_20260710_165033_abcde_prueba-con_guion",
            "RUN_20260710_165033_abcde_-leading-hyphen",
        ]
        invalid_ids = [
            "RUN_20260710_165033",
            "RUN_20260710_165033_deadbeef",
            "RUN_20260710_165033_abcde_../escape",
        ]
        if any(run_id_re.fullmatch(item) is None for item in valid_ids):
            failures.append("RunId pattern rejects runtime-generated IDs")
        if any(run_id_re.fullmatch(item) is not None for item in invalid_ids):
            failures.append("RunId pattern accepts invalid IDs")

    if failures:
        print("CEREBRO_ACTIONS_CONTRACT_FAIL")
        for failure in failures:
            print(" -", failure)
        return 1
    print("CEREBRO_ACTIONS_CONTRACT_OK")
    print("operation_ids=%d paths=%d" % (len(ops), len(paths)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
