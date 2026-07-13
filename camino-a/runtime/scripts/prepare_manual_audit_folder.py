"""prepare_manual_audit_folder.py — Real implementation.

Prepares the manual audit folder with templates, index tracking,
and auditoria adversarial generation.

Functions imported by run_multiaudit_cycle.py:
  - prepare(folder, description, clean=True) -> manifest dict
  - write_auditoria_adversarial(manual_folder, candidate_file, script_version, candidate_sha) -> dict
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return slug[:200] or "manual"


# ---------------------------------------------------------------------------
# prepare() — called as prepare_manual_audit_folder()
# ---------------------------------------------------------------------------

def prepare(
    folder: Path,
    description: str = "",
    *,
    clean: bool = False,
) -> dict[str, Any]:
    """Prepare manual audit folder with structure and templates.

    Args:
        folder: Path to the manual audit folder
        description: Description of what to audit
        clean: If True, remove existing contents first

    Returns:
        Manifest dict with folder info
    """
    if clean and folder.exists():
        # Don't delete the folder itself, just contents
        for item in list(folder.iterdir()):
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()

    folder.mkdir(parents=True, exist_ok=True)

    # Create index
    index_path = folder / "AUDITORIAS_MANUALES_RECIBIDAS.md"
    if not index_path.exists():
        index_path.write_text(
            f"# Auditorías Manuales Recibidas\n\n"
            f"Creado: {_utc_now()}\n\n"
            f"## Instrucciones\n\n"
            f"1. Colocar archivos `.md` o `.txt` con auditorías en esta carpeta\n"
            f"2. El watcher los detectará automáticamente\n"
            f"3. Formato esperado: ver `TEMPLATE.md`\n\n"
            f"## Recibidas\n\n",
            encoding="utf-8",
        )

    # Create template
    template_path = folder / "TEMPLATE.md"
    if not template_path.exists():
        template_path.write_text(
            f"# Auditoría Manual\n\n"
            f"## Metadata\n\n"
            f"- **Audit ID:** (auto-generado si se omite)\n"
            f"- **Author:** (tu nombre o modelo)\n"
            f"- **Model:** (modelo usado, ej: gpt-4, claude-3-opus)\n"
            f"- **Date:** {_utc_now()[:10]}\n\n"
            f"## Contexto\n\n"
            f"{description or '(describir qué se audita)'}\n\n"
            f"## Hallazgos\n\n"
            f"- (hallazgo 1)\n"
            f"- (hallazgo 2)\n\n"
            f"## Severidad\n\n"
            f"- CRITICAL / HIGH / MEDIUM / LOW\n\n"
            f"## Veredicto\n\n"
            f"BLOQUEADO / OBSERVACIONES_NO_BLOQUEANTES / SIN_VEREDICTO_POR_EVIDENCIA_INSUFICIENTE\n\n"
            f"## Evidencia\n\n"
            f"```\n(código, logs, etc.)\n```\n",
            encoding="utf-8",
        )

    # Create adversarial template
    adv_path = folder / "auditoria_adversarial.md"
    if not adv_path.exists():
        adv_path.write_text(
            f"# Auditoría Adversarial\n\n"
            f"> Buscar: bugs, vulnerabilidades, fallas de diseño, "
            f"mejoras técnicas reales.\n\n"
            f"## Hallazgos\n\n"
            f"- (agregar hallazgos aquí)\n\n"
            f"## Pruebas\n\n"
            f"```bash\n# comandos para reproducir\n```\n\n"
            f"## Veredicto\n\n"
            f"OBSERVACIONES_NO_BLOQUEANTES\n",
            encoding="utf-8",
        )

    # Build manifest
    manifest_files = []
    for item in sorted(folder.rglob("*")):
        if item.is_file() and not item.is_symlink():
            rel = str(item.relative_to(folder))
            manifest_files.append({
                "path": rel,
                "sha256": _sha256_file(item),
                "size_bytes": item.stat().st_size,
            })

    manifest = {
        "folder": str(folder),
        "description": description,
        "prepared_at": _utc_now(),
        "files": manifest_files,
        "total_files": len(manifest_files),
    }

    # Write manifest
    (folder / "FOLDER_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return manifest


# ---------------------------------------------------------------------------
# write_auditoria_adversarial()
# ---------------------------------------------------------------------------

def write_auditoria_adversarial(
    manual_folder: Path,
    candidate_file: Path,
    script_version: str,
    candidate_sha: str,
) -> dict[str, Any]:
    """Generate an adversarial audit document for a candidate.

    Args:
        manual_folder: Where to write the audit doc
        candidate_file: Path to the candidate being audited
        script_version: Version string
        candidate_sha: SHA-256 of the candidate

    Returns:
        Dict with audit metadata
    """
    manual_folder.mkdir(parents=True, exist_ok=True)

    audit_id = f"adversarial_{_safe_slug(candidate_file.stem)}_{candidate_sha[:12]}"

    # Read candidate preview (first 200 lines)
    preview_lines = []
    try:
        if candidate_file.exists():
            with candidate_file.open("r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= 200:
                        preview_lines.append(f"... ({candidate_file.stat().st_size} bytes total)")
                        break
                    preview_lines.append(line.rstrip())
    except OSError:
        preview_lines.append("(no se pudo leer el candidato)")

    preview = "\n".join(preview_lines)

    content = f"""# Auditoría Adversarial — {candidate_file.name}

## Metadata

- **Audit ID:** {audit_id}
- **Generated:** {_utc_now()}
- **Script Version:** {script_version}
- **Candidate SHA:** {candidate_sha}
- **Candidate File:** {candidate_file}

## Instrucciones

Este documento fue generado automáticamente como plantilla para una auditoría
adversarial del candidato. Complete los hallazgos y veredicto.

## Candidato (preview — primeras 200 líneas)

```python
{preview}
```

## Checklist de auditoría

- [ ] **Bugs confirmados** — ¿Hay errores funcionales?
- [ ] **Vulnerabilidades** — ¿Hay agujeros de seguridad?
- [ ] **Path traversal** — ¿Se validan bien las rutas?
- [ ] **Symlinks** — ¿Se rechazan symlinks?
- [ ] **Secretos** — ¿Pueden filtrarse secretos?
- [ ] **TOCTOU** — ¿Hay race conditions?
- [ ] **Resource limits** — ¿Se previene DoS?
- [ ] **API prohibida** — ¿Se usa Claude/OpenAI API?
- [ ] **Manifest** — ¿Se valida correctamente?
- [ ] **Tests** — ¿Hay tests suficientes?

## Hallazgos

- (agregar hallazgos aquí)

## Severidad

- CRITICAL / HIGH / MEDIUM / LOW

## Veredicto

BLOQUEADO / OBSERVACIONES_NO_BLOQUEANTES / SIN_VEREDICTO_POR_EVIDENCIA_INSUFICIENTE

## Evidencia

```
(código, logs, pruebas de concepto)
```
"""

    dst = manual_folder / f"{audit_id}.md"
    dst.write_text(content, encoding="utf-8")

    # Update index
    index_path = manual_folder / "AUDITORIAS_MANUALES_RECIBIDAS.md"
    if index_path.exists():
        with index_path.open("a", encoding="utf-8") as f:
            f.write(f"- [{audit_id}]({dst.name}) — {_utc_now()[:10]}\n")

    return {
        "audit_id": audit_id,
        "path": str(dst),
        "sha256": _sha256_file(dst),
        "size_bytes": dst.stat().st_size,
        "candidate_sha": candidate_sha,
        "candidate_file": str(candidate_file),
        "script_version": script_version,
        "generated_at": _utc_now(),
    }
