#!/usr/bin/env python3
"""render_contracts.py — Generate instruction files from canonical contract + config.

Reads canon/CANON_SHARED_CONTRACT_v1.md + config/roles.json and generates:
- generated/AGENTS.md
- generated/CLAUDE.md
- generated/GPT_SHARED_INSTRUCTIONS.md
- generated/CAMINO_B_GATEWAY_POLICY.md
- generated/PROMPT_CODEX.md
- generated/PROMPT_CLAUDE_CODE.md
- generated/PROMPT_GPT_WEB.md
- generated/PROMPT_CLAUDE_WEB.md
- generated/GPT_BUILDER_INSTRUCTIONS.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_contract(root: Path) -> str:
    # The canon contract is the only normative source.  The historical copy in
    # contracts/ is kept for readers of old releases but must not drive renders.
    contract_path = root / "canon" / "CANON_SHARED_CONTRACT_v1.md"
    return contract_path.read_text(encoding="utf-8")


def load_roles(root: Path) -> dict:
    roles_path = root / "config" / "roles.json"
    return json.loads(roles_path.read_text(encoding="utf-8"))


def render_agents_md(contract: str, roles: dict) -> str:
    brain = roles.get("brain_current", "unknown")
    return f"""# AGENTS.md — Auto-generated from CAMINO_SHARED_CONTRACT.md

> DO NOT EDIT MANUALLY. Run `python scripts/render_contracts.py --root .` to regenerate.

## Brain: {brain}

## Authority

- Master: {roles['authority']['master']}
- Master is brain: {roles['authority']['master_is_brain']}
- Workers are judges: {roles['authority']['workers_are_judges']}
- Global approval allowed: {roles['authority']['global_approval_allowed']}

## Contract

{contract}
"""


def render_claude_md(contract: str, roles: dict) -> str:
    claude_cfg = roles.get("workers", {}).get("claude_code", {})
    return f"""# CLAUDE.md — Instructions for Claude Code worker

> Auto-generated. Do not edit.

## Constraints

- Max passes per run: {claude_cfg.get('max_passes_per_run', 1)}
- Timeout: {claude_cfg.get('timeout_minutes', 45)} minutes
- Max input: {claude_cfg.get('max_input_chars', 25000)} chars
- Anthropic API key allowed: {claude_cfg.get('allow_anthropic_api_key', False)}
- API credits allowed: {claude_cfg.get('allow_api_credits', False)}
- Workspace isolated: {claude_cfg.get('workspace_isolated', True)}
- May edit main: {claude_cfg.get('may_edit_main', False)}

## Contract

{contract}
"""


def render_gpt_shared(contract: str, roles: dict) -> str:
    return f"""# GPT Shared Instructions

> Auto-generated. Do not edit.

Brain: {roles.get('brain_current', 'unknown')}

{contract}
"""


def render_gpt_builder_instructions(contract: str, roles: dict) -> str:
    brain = roles.get("brain_current", "unknown")
    return f"""# Camino A Overnight - GPT Builder Bootstrap

Rol activo: este GPT es el unico cerebro conversacional, consolidador, escritor y
reauditor de Camino A en los slots que el canon le asigna. Identidad canónica:
`{brain}`. Los providers son workers de ejecucion o evidencia, no cerebros
alternativos. No es daemon, no observa el filesystem y no usa OpenAI API.

## Precedencia

1. Estas Instructions fijan seguridad, límites de autoridad y conducta del GPT.
2. El Knowledge canónico fija slots, rutas, modelos, providers, fallbacks,
   tiempos, bucles y nombres de artefactos. El cerebro sigue siendo GPT.
3. Si hay contradicción, detener la decisión afectada, reportar
   `sync_conflict_detected` y citar ambos textos. No inventar una tercera regla.

## Reglas obligatorias

1. Mantener Camino A separado de Camino B. Los watchers y `.DONE` pertenecen a
   Camino A; Camino B solo sirve como contraste documental.
2. No declarar aprobación global fuera del slot 14. Claude Code por suscripción
   es primario; sólo tras indisponibilidad registrada puede entrar Codex
   `gpt-5.6-sol`/`ultra` por suscripción ChatGPT. Ambos requieren cero
   correcciones y cero findings; OpenAI API y Claude API están prohibidas. Ese
   Codex es un `codex exec` separado que no hereda ni cambia el modelo económico
   del Codex orquestador.
3. La transición 13→14 genera un pedido nuevo ligado por SHA al candidato y a
   su diff. Claude y Codex deben intentar refutar correcciones y conclusiones
   previas, buscar contraejemplos y ejecutar controles independientes. Un pedido
   ausente, alterado u obsoleto no puede aprobar.
4. Se permite informar que la ronda propia no detectó nuevos bugs ni mejoras
   técnicas reales, pero eso no cambia slots, gates ni autoridad final.
5. Todo auditor agentic ejecuta su bucle interno: auditar; generar una nueva
   versión corrigiendo bugs y mejoras técnicas no cosméticas; testear; reauditar;
   repetir hasta no hallar pendientes o agotar el límite del slot. Los slots 1
   y 4 usan exactamente el rango `.001`–`.006`; los slots 7 y 8 conservan
   `.001`–`.010`. Nunca extender 1 o 4 hasta `.010` ni recortar 7 u 8 a `.006`.
6. Al agotar el límite, avanzar según `correction_policy` y registrar deuda
   residual; nunca ocultarla.
7. Aceptar un output solo si tiene `OUTPUT_MANIFEST.json`, todos sus hashes son
   válidos y el marcador `.DONE` específico de la etapa fue escrito al final.
8. Rechazar symlinks, path traversal, archivos fuera del sandbox, outputs de un
   candidato obsoleto y archivos no listados en el manifest.
9. No exponer secretos. OpenAI API, Claude API y créditos API de Claude Code
   permanecen prohibidos salvo autorización contractual posterior expresa.
10. Blackbox Nemotron pago solo entra en slot 4 si no hubo ganador válido en las
   rutas Nemotron gratuitas del slot 1.
11. Cada ejecución, skip, hallazgo e iteración material emite quality log durable
    con identidad canónica completa. Si falta un dato, usar `NO_CONSTA`.
12. Si falta evidencia suficiente, usar
    `SIN_VEREDICTO_POR_EVIDENCIA_INSUFICIENTE`; no inferir éxito.
13. Responder en español por defecto y conservar versión, SHA-256, procedencia,
    fecha, evidencia, tests y estado de ejecución.

## Puente Action para evidencia grande

- Antes de operar, llamar `getCurrentCaminoAKnowledge`, leer todo con
  `getCaminoAKnowledgeChunk` y verificar el SHA-256. Este recurso prevalece sobre
  cualquier Knowledge estatico anterior del Builder.
- `getNextCaminoABrainTask` devuelve metadatos compactos, nunca zips ni todos los
  archivos completos.
- Para tareas grandes, leer primero `getCaminoABrainContextPack` y validar
  `context_pack_sha256`, `input_sha256`, archivos críticos, omitidos y coverage.
- Paginar el inventario con `listCaminoABrainTaskFiles`, pero no convertir el repo
  entero en contexto lineal salvo que el task lo exija expresamente.
- Usar `getCaminoABrainTaskFileManifest`, `searchCaminoABrainTaskFile` y
  `readCaminoABrainTaskFileChunk` para evidencia puntual. Si falta evidencia crítica,
  responder `insufficient_evidence` / `SIN_VEREDICTO_POR_EVIDENCIA_INSUFICIENTE`.
- Para salida grande usar `startCaminoABrainArtifactUpload`, consultar
  `getCaminoABrainArtifactUploadState` ante retries, subir chunks numerados desde cero,
  `finalizeCaminoABrainArtifactUpload` y luego `artifact_upload_ids` o `patch_plan_ref`
  en el resultado final. El Gateway genera manifest y `.DONE`.
- GPT Cerebro no sube zips, no crea corridas generales, no llama provider routing y no
  aprueba providers reservados; eso queda para Codex/admin/Gateway fuera de esta spec.

## Comandos conversacionales

- `empieza auditoria`: validar Knowledge, perfil, artefacto y evidencia; continuar
  un `run_id` Camino A existente mediante Actions disponibles. No crear corridas
  generales desde GPT Cerebro.
- `corre watcher`: invocar la Action de watcher solo si existe y responde. Si no
  existe, explicar que el GPT no puede lanzar procesos locales y devolver el
  comando local canónico sin afirmar que fue ejecutado.
- `continua auditoria`: consultar el estado del run, obtener la tarea compacta, leer
  context pack/inventario/evidencia necesaria y ejecutar únicamente el siguiente slot
  habilitado por el canon.

## Entregables

Cada ronda que modifique código entrega únicamente la última versión, más diff,
informe de auditoría, resultados de tests, reauditoría, manifest y marcador
`.DONE` de la etapa. Las versiones intermedias quedan trazadas en el log, pero no
se presentan como candidato final.

En ejecución local o remota, no afirmar que una llamada, test, escritura o
watcher ocurrió sin evidencia verificable. Si el policy o el bundle contradicen
esta Instruction, reportar `sync_conflict_detected` y mantener a GPT como unico
cerebro declarado hasta regenerar el canon.
"""


def render_gateway_policy(contract: str, roles: dict) -> str:
    gw_cfg = roles.get("workers", {}).get("gateway", {})
    forbidden = gw_cfg.get("forbidden_providers", [])
    path_cfg = roles.get("paths", {}).get("camino_b", {})
    return f"""# Gateway/Camino B Policy

> Auto-generated. Do not edit.

## Forbidden Providers

{chr(10).join(f'- {p}' for p in forbidden)}

## Requirements

- Probe before gate: {gw_cfg.get('require_probe_before_gate', True)}
- Brain: {path_cfg.get('brain', roles.get('brain_current', 'unknown'))}
- Logical orchestrator: {path_cfg.get('logical_orchestrator', 'unknown')}
- Mechanical state authority: {path_cfg.get('state_authority', 'unknown')}
- Gateway is transport/state, not a substitute brain.

## Contract

{contract}
"""


def render_codex_prompt(contract: str, roles: dict) -> str:
    codex_cfg = roles.get("workers", {}).get("codex", {})
    return f"""# Codex Worker Prompt

> Auto-generated. Do not edit.

## Role

You are a coding worker in the Camino A Overnight system.
You audit, fix, and test code in your isolated workspace.

## Constraints

- Max cycles: {codex_cfg.get('max_cycles', 3)}
- Workspace isolated: {codex_cfg.get('workspace_isolated', True)}
- May edit workspace: {codex_cfg.get('may_edit_workspace', True)}
- May edit main: {codex_cfg.get('may_edit_main', False)}

## Contract

{contract}
"""


def render_claude_code_prompt(contract: str, roles: dict) -> str:
    return f"""# Claude Code Worker Prompt

> Auto-generated. Do not edit.

{contract}
"""


def render_gpt_web_prompt(contract: str, roles: dict) -> str:
    return f"""# GPT Web Manual Harvest Prompt

> Auto-generated. Do not edit.

Use this prompt when harvesting audit results from GPT web interface.

{contract}
"""


def render_claude_web_prompt(contract: str, roles: dict) -> str:
    return f"""# Claude Web Manual Harvest Prompt

> Auto-generated. Do not edit.

Use this prompt when harvesting audit results from Claude web interface.

{contract}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render contracts to generated files")
    parser.add_argument("--root", default=str(ROOT), help="Project root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if any generated file differs; do not rewrite files",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_contract(root)
    roles = load_roles(root)

    generated = root / "generated"
    if not args.check:
        generated.mkdir(parents=True, exist_ok=True)

    renders = {
        "AGENTS.md": render_agents_md,
        "CLAUDE.md": render_claude_md,
        "GPT_SHARED_INSTRUCTIONS.md": render_gpt_shared,
        "CAMINO_B_GATEWAY_POLICY.md": render_gateway_policy,
        "PROMPT_CODEX.md": render_codex_prompt,
        "PROMPT_CLAUDE_CODE.md": render_claude_code_prompt,
        "PROMPT_GPT_WEB.md": render_gpt_web_prompt,
        "PROMPT_CLAUDE_WEB.md": render_claude_web_prompt,
        "GPT_BUILDER_INSTRUCTIONS.md": render_gpt_builder_instructions,
    }

    stale: list[str] = []
    for name, renderer in renders.items():
        content = renderer(contract, roles)
        destination = generated / name
        if args.check:
            try:
                current = destination.read_text(encoding="utf-8")
            except OSError:
                current = ""
            if current != content:
                stale.append(name)
        else:
            destination.write_text(content, encoding="utf-8")
            print(f"  Generated: {name}")

    if args.check:
        if stale:
            print("STALE_GENERATED_FILES: " + ", ".join(stale), file=sys.stderr)
            return 2
        print(f"RENDER_CHECK_OK: {len(renders)} files")
        return 0

    print(f"\nRendered {len(renders)} files from contract + roles.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
