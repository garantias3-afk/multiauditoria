#!/usr/bin/env python3
"""Build the single Camino A GPT Knowledge file from canonical sources."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCES = (
    "generated/GPT_SHARED_INSTRUCTIONS.md",
    "contracts/CAMINO_SHARED_CONTRACT.md",
    "contracts/CANON_ACTION_TRANSFER_POLICY_v1.md",
    "actions/CAMINO_A_CEREBRO_ACTIONS.v1.yaml",
    "actions/SOL56_ACTIONS_EVAL_PROTOCOL.md",
    "canon/CANON_SHARED_CONTRACT_v1.md",
    "canon/CANON_CHANGE_PROTOCOL_v1.md",
    "canon/CANON_PROVIDER_MODEL_ROUTES.v1.json",
    "canon/CANON_WORKFLOW_SLOTS.v1.json",
    "canon/CANON_RUNTIME_POLICY.v1.json",
    "canon/CANON_PREAUDIT_DELIVERY.v1.json",
    "config/roles.json",
    "config/path_roles.json",
    "config/host_runtime.policy.json",
    "config/drive.policy.json",
    "config/primary_brain_policy.json",
    "config/provider.policy.json",
    "QUICKSTART.md",
    "RUNBOOK_CODEX.md",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--version", default="v1.3.22-slot1-slot4-six-loops")
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate CURRENT version, source hashes and content hash without rewriting",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else root
    output_dir.mkdir(parents=True, exist_ok=True)
    publish_current = output_dir == root
    suffix = args.version.replace(".", "_")
    md_path = output_dir / f"CAMINO_A_OVERNIGHT_KNOWLEDGE_BUNDLE_UNICO_{suffix}.md"
    zip_path = output_dir / f"CAMINO_A_OVERNIGHT_KNOWLEDGE_BUNDLE_UNICO_{suffix}.zip"
    current_path = root / "CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.md"
    current_manifest_path = root / "CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.manifest.json"

    manifest = []
    sections = []
    for relative in SOURCES:
        path = root / relative
        raw = path.read_bytes()
        manifest.append({
            "path": relative,
            "bytes": len(raw),
            "sha256": sha256(raw),
        })
        language = "json" if path.suffix == ".json" else "markdown"
        sections.append(
            f"## SOURCE: {relative}\n\n"
            f"```{language}\n{raw.decode('utf-8').rstrip()}\n```\n"
        )

    brain = json.loads(
        (root / "config/roles.json").read_text(encoding="utf-8")
    )["brain_current"]
    if args.check:
        errors: list[str] = []
        try:
            current_manifest = json.loads(current_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            current_manifest = {}
            errors.append(f"current_manifest_unreadable:{type(exc).__name__}")
        if current_manifest.get("bundle_version") != args.version:
            errors.append("bundle_version_mismatch")
        if current_manifest.get("brain_current") != brain:
            errors.append("brain_current_mismatch")
        if current_manifest.get("source_manifest") != manifest:
            errors.append("source_manifest_mismatch")
        try:
            current_raw = current_path.read_bytes()
        except OSError as exc:
            current_raw = b""
            errors.append(f"current_unreadable:{type(exc).__name__}")
        if current_manifest.get("sha256") != sha256(current_raw):
            errors.append("current_sha256_mismatch")
        if current_manifest.get("size_bytes") != len(current_raw):
            errors.append("current_size_mismatch")
        try:
            versioned_raw = md_path.read_bytes()
        except OSError as exc:
            versioned_raw = b""
            errors.append(f"versioned_markdown_unreadable:{type(exc).__name__}")
        if versioned_raw != current_raw:
            errors.append("versioned_markdown_mismatch")
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                names = archive.namelist()
                zipped_raw = archive.read(md_path.name) if names == [md_path.name] else b""
                if names != [md_path.name]:
                    errors.append("versioned_zip_members_invalid")
                if zipped_raw != current_raw:
                    errors.append("versioned_zip_content_mismatch")
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            errors.append(f"versioned_zip_unreadable:{type(exc).__name__}")
        print(json.dumps({
            "status": "ok" if not errors else "stale",
            "bundle_version": args.version,
            "source_count": len(manifest),
            "errors": errors,
        }, indent=2, ensure_ascii=False))
        return 0 if not errors else 2

    doc_manifest = {
        "bundle_schema": "camino_a_knowledge_bundle.unico.v2",
        "bundle_version": args.version,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "brain_current": brain,
        "source_count": len(manifest),
        "source_manifest": manifest,
    }
    header = f"""# CAMINO A OVERNIGHT - KNOWLEDGE BUNDLE UNICO {args.version}

Uso previsto: subir este unico Markdown como Knowledge del GPT Camino A.
Reemplaza bundles anteriores; no se deben conservar simultaneamente versiones
viejas como Knowledge activo.

## Alcance y precedencia

- Camino A es el flujo automatizado local. Camino B no hereda sus watchers.
- `brain_current` verificado al construir: `{brain}`.
- GPT es el unico cerebro declarado; los providers de ejecucion no cambian esa autoridad.
- Las Instructions del GPT fijan seguridad y autoridad.
- Este bundle fija workflow, providers, fallbacks, tiempos y artefactos.
- Una contradiccion produce `sync_conflict_detected`; no se resuelve por
  conveniencia ni usando documentos legacy.
- Un GPT personalizado solo trabaja durante una conversacion activa. La
  ejecucion nocturna y los watchers pertenecen a infraestructura local.

## Manifest

```json
{json.dumps(doc_manifest, indent=2, ensure_ascii=False)}
```

"""
    bundle_text = header + "\n".join(sections)
    md_path.write_text(bundle_text, encoding="utf-8")
    if publish_current:
        current_path.write_text(bundle_text, encoding="utf-8")
        current_manifest_path.write_text(json.dumps({
            "schema_version": "camino_a_knowledge_current.v1",
            "bundle_version": args.version,
            "file": current_path.name,
            "size_bytes": len(bundle_text.encode("utf-8")),
            "sha256": sha256(bundle_text.encode("utf-8")),
            "generated_utc": doc_manifest["generated_utc"],
            "brain_current": brain,
            "source_manifest": manifest,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(md_path, arcname=md_path.name)

    print(json.dumps({
        "markdown": str(md_path),
        "markdown_sha256": sha256(md_path.read_bytes()),
        "zip": str(zip_path),
        "zip_sha256": sha256(zip_path.read_bytes()),
        "current": str(current_path) if publish_current else None,
        "current_sha256": sha256(current_path.read_bytes()) if publish_current else None,
        "current_manifest": str(current_manifest_path) if publish_current else None,
        "brain_current": brain,
        "source_count": len(manifest),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
