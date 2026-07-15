#!/usr/bin/env python3
"""build_preaudit_package.py — Genera el paquete de preauditoría completo.

COMÚN CAMINO A Y B. Fuente de verdad: canon/CANON_PREAUDIT_DELIVERY.v1.json.

Entregables (contrato de 10 puntos):
  1.1 zip plano (sin carpetas; ideal ≤10 archivos, máx 50; si excede,
      avisa y pregunta salvo --force-flat / --no-flat)
  1.2 zip con subcarpetas (solo si hay subcarpetas o >50 archivos)
  1.3/6 PEDIDO_COPIAR_PEGAR.md (hilo listo para copiar/pegar)
  2   CONTEXTO_MINIMO_AUDITORIA.md (se incluye desde la fuente)
  3/8 MANIFEST_MINIMO_AUDITORIA.json con SHA-256 actualizado
  4   PEDIDO_AUDITORIAS_MANUALES.md (se incluye desde la fuente)
  5   CHANGELOG_CORRECCION_AUDITORIA.md (se incluye desde la fuente)
  9   INCLUIDOS_EXCLUIDOS.md
  10  INSTRUCCIONES_MULTIAGENTE.md (roles según multiagent_policy)

Uso:
  python3 scripts/build_preaudit_package.py \
      --source-dir . --output-dir OUT --version v1.3.12 \
      --audit-type sistema_completo [--agents 7] [--force-flat|--no-flat]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Selección minimalista: solo última versión + indispensables.
# ---------------------------------------------------------------------------
INCLUDE_DIRS = ("canon", "config", "contracts", "generated", "schemas", "scripts")
INCLUDE_TOP_LEVEL_SUFFIXES = (".md", ".json")
EXCLUDE_RULES = (
    ("__pycache__", "cache de Python"),
    (".pyc", "bytecode compilado"),
    (".pytest_cache", "cache de tests"),
    ("__MACOSX", "resource fork de macOS"),
    (".DS_Store", "metadata de macOS"),
    ("VALIDATION_RESULTS", "salida de validaciones previas (ruido histórico)"),
    ("KNOWLEDGE_BUNDLE_UNICO_v", "bundles históricos de versiones viejas"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_excluded(rel: str) -> str | None:
    for pattern, reason in EXCLUDE_RULES:
        if pattern in rel:
            return reason
    return None


def select_files(source: Path) -> tuple[list[Path], list[dict]]:
    """Devuelve (incluidos, excluidos_con_motivo) con criterio minimalista."""
    included: list[Path] = []
    excluded: list[dict] = []
    for item in sorted(source.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        rel = str(item.relative_to(source))
        reason = is_excluded(rel)
        if reason:
            excluded.append({"path": rel, "reason": reason})
            continue
        top = rel.split("/", 1)[0]
        if "/" in rel:
            if top in INCLUDE_DIRS:
                included.append(item)
            else:
                excluded.append({"path": rel, "reason": f"directorio '{top}' fuera del set mínimo"})
        else:
            if item.suffix in INCLUDE_TOP_LEVEL_SUFFIXES:
                included.append(item)
            else:
                excluded.append({"path": rel, "reason": "archivo top-level fuera del set mínimo"})
    return included, excluded


# ---------------------------------------------------------------------------
# Multiagente: asignación de roles según canon + tipo de auditoría.
# ---------------------------------------------------------------------------
AUDIT_TYPE_ROLE_PRIORITY = {
    # tipo de auditoría → role_ids priorizados en orden
    "sistema_completo": [
        "canon_slots_providers", "runtime_python", "seguridad_io",
        "packaging_preaudit", "gateway_archivos_grandes", "bucles_cierre",
        "adversarial_general", "estado_persistencia", "contratos_prompts",
        "costos_presupuesto", "concurrencia_procesos", "esquemas_validacion",
    ],
    "solo_canon": ["canon_slots_providers", "contratos_prompts",
                   "esquemas_validacion", "adversarial_general"],
    "solo_runtime": ["runtime_python", "estado_persistencia",
                     "concurrencia_procesos", "adversarial_general"],
    "solo_seguridad": ["seguridad_io", "gateway_archivos_grandes",
                       "runtime_python", "adversarial_general"],
    "solo_packaging": ["packaging_preaudit", "seguridad_io",
                       "esquemas_validacion", "adversarial_general"],
}

ROLE_SCOPE = {
    "canon_slots_providers": {
        "alcance": "canon/*.json, coherencia slots↔routes↔providers, aliases legacy",
        "archivos": ["canon/CANON_WORKFLOW_SLOTS.v1.json",
                     "canon/CANON_PROVIDER_MODEL_ROUTES.v1.json",
                     "canon/CANON_RUNTIME_POLICY.v1.json",
                     "canon/CANON_PREAUDIT_DELIVERY.v1.json"],
        "preguntas": ["¿Toda route referenciada por un slot existe y está activa?",
                      "¿Hay provider_id reutilizado como route_id?",
                      "¿Los bucles internos (slots 1,4,7,8) y de slot (3,6,10,11,12,13,14) están declarados sin contradicción?"],
    },
    "runtime_python": {
        "alcance": "scripts/*.py: lógica, excepciones, estados zombie, imports",
        "archivos": ["scripts/overnight_master.py", "scripts/slot_runtime.py",
                     "scripts/run_multiaudit_cycle.py", "scripts/internal_loop_runner.py"],
        "preguntas": ["¿Alguna fase puede quedar sin transición terminal?",
                      "¿Hay except que trague errores sin registrar evidencia?"],
    },
    "seguridad_io": {
        "alcance": "manifests, hashes, secrets, symlinks, path traversal, TOCTOU",
        "archivos": ["scripts/validate_bundle.py", "scripts/quality_log.py",
                     "scripts/hash_tree.py", "scripts/ast_analysis.py"],
        "preguntas": ["¿Todo copytree usa symlinks=False?",
                      "¿Puede un worker falsificar identidad o SHA?",
                      "¿La cadena de hashes del quality log es íntegra?"],
    },
    "packaging_preaudit": {
        "alcance": "generación del paquete limpio, criterio minimalista, reglas 1.1/1.2/1.3",
        "archivos": ["scripts/build_preaudit_package.py", "scripts/package_final.py",
                     "MANIFEST_MINIMO_AUDITORIA.json"],
        "preguntas": ["¿El zip plano respeta ideal≤10 / máx 50 con pregunta al exceder?",
                      "¿Los SHA-256 del manifest coinciden con los archivos reales?"],
    },
    "gateway_archivos_grandes": {
        "alcance": "worker_gateway: protocolo manifest-first, fallback gzip, límites de tamaño, TOCTOU",
        "archivos": ["scripts/worker_gateway.py", "scripts/test_gateway_protocol.py"],
        "preguntas": ["¿El fail-closed en TOCTOU se cumple sin bundle parcial?",
                      "¿El fallback C solo se habilita con 404/405/501?"],
    },
    "bucles_cierre": {
        "alcance": "bucle grande, bucles internos 1/4 .001-.006 y 7/8 .001-.010, cierre de corrida, aprobación slot 14",
        "archivos": ["canon/CANON_WORKFLOW_SLOTS.v1.json", "scripts/overnight_master.py",
                     "PEDIDO_AUDITORIAS_MANUALES.md"],
        "preguntas": ["¿Los slots 1/4 exigen .001-.006 y los slots 7/8 conservan .001-.010, también en el pedido manual ligado al slot?",
                      "¿Ninguna ruta permite aprobación global fuera del slot 14?"],
    },
    "adversarial_general": {
        "alcance": "todo el paquete, sin restricción: buscar lo que los roles específicos no vieron",
        "archivos": ["(todo el zip)"],
        "preguntas": ["¿Qué invariante implícito no está testeado?",
                      "¿Qué contradicción cruza dos módulos que nadie mira juntos?"],
    },
    "estado_persistencia": {
        "alcance": "SQLite, cycle_state.json, dual-write, migraciones",
        "archivos": ["scripts/state_db.py", "scripts/assert_run_state.py"],
        "preguntas": ["¿created_at/updated_at son coherentes?",
                      "¿La migración ALTER TABLE es idempotente?"],
    },
    "contratos_prompts": {
        "alcance": "generated/*.md, contracts/, consistencia documental con canon",
        "archivos": ["generated/GPT_SHARED_INSTRUCTIONS.md", "contracts/CAMINO_SHARED_CONTRACT.md"],
        "preguntas": ["¿Algún prompt generado contradice el canon vigente?"],
    },
    "costos_presupuesto": {
        "alcance": "cost_class, budget.policy, rutas pagas vs free",
        "archivos": ["config/budget.policy.json", "canon/CANON_PROVIDER_MODEL_ROUTES.v1.json"],
        "preguntas": ["¿Alguna ruta paga puede ejecutarse sin autorización requerida?"],
    },
    "concurrencia_procesos": {
        "alcance": "locks, watcher, subprocesos, reaping, señales",
        "archivos": ["scripts/overnight_master.py", "scripts/camino_a_worker_bus.py"],
        "preguntas": ["¿Puede haber doble watcher sobre la misma corrida?"],
    },
    "esquemas_validacion": {
        "alcance": "schemas/*.json, validación de entradas, jsonschema",
        "archivos": ["schemas/schemas.json", "canon/*.schema.json"],
        "preguntas": ["¿Todo JSON de entrada crítico tiene schema y se valida?"],
    },
}


def load_delivery_canon(source: Path) -> dict:
    p = source / "canon" / "CANON_PREAUDIT_DELIVERY.v1.json"
    if not p.exists():
        p = ROOT / "canon" / "CANON_PREAUDIT_DELIVERY.v1.json"
    return json.loads(p.read_text(encoding="utf-8"))


def choose_agents(canon: dict, audit_type: str, override: int | None) -> list[dict]:
    policy = canon["multiagent_policy"]
    catalog = {r["role_id"]: r for r in policy["role_catalog"]}
    priority = AUDIT_TYPE_ROLE_PRIORITY.get(audit_type,
                                            AUDIT_TYPE_ROLE_PRIORITY["sistema_completo"])
    max_par = int(policy["max_parallel_agents"])
    n = override if override is not None else (
        len(priority) if audit_type == "sistema_completo" and override is None
        and False else int(policy["default_agents"]))
    # Por defecto: default_agents (benchmark: 4 eficiente); sistema_completo
    # puede escalar por override explícito hasta max_parallel_agents.
    if override is not None:
        n = override
    n = max(1, min(n, max_par, len(priority)))
    agents = []
    for i, role_id in enumerate(priority[:n], start=1):
        role = catalog[role_id]
        scope = ROLE_SCOPE[role_id]
        agents.append({
            "agente": i,
            "role_id": role_id,
            "rol": role["name"],
            "alcance": scope["alcance"],
            "archivos_prioritarios": scope["archivos"],
            "preguntas_especificas": scope["preguntas"],
        })
    return agents


def render_multiagent_md(canon: dict, agents: list[dict], audit_type: str,
                         version: str) -> str:
    policy = canon["multiagent_policy"]
    snap = policy["benchmark_snapshot"]
    lines = [
        f"# INSTRUCCIONES MULTIAGENTE POR ROL — {version}",
        "",
        "COMÚN CAMINO A Y B. Fuente: `canon/CANON_PREAUDIT_DELIVERY.v1.json`.",
        "",
        f"- Tipo de auditoría: `{audit_type}`",
        f"- Agentes asignados: {len(agents)} (default {policy['default_agents']}, máximo {policy['max_parallel_agents']})",
        f"- Benchmark vigente ({snap['snapshot_utc']}): {snap['consensus']}. "
        f"Revisión obligatoria cada {snap['review_required_every_days']} días.",
        "- Regla: un rol por agente; el preauditor prioriza máxima eficiencia según tipo de auditoría y benchmarks.",
        "",
        "## Formato de salida común (obligatorio para todos los agentes)",
        "",
        "El definido en `PEDIDO_AUDITORIAS_MANUALES.md`: Auditor Card, Identidad canónica,",
        "Evidencia revisada, Hallazgos H-n, Contradicciones internas, Deuda residual,",
        "Veredicto de ronda. Sin aprobación global.",
        "",
        "## Reglas de bucle interno (obligatorias para todos los agentes)",
        "",
        "Respetar el límite del slot: slots 1/4 iteran .001 a .006; slots 7/8 iteran",
        ".001 a .010. Auditar → detectar bug/mejora/deuda → corregir o reescribir →",
        "testear/validar → reauditar la corrección → decidir si queda limpio dentro del",
        "alcance del rol. Un agente no ligado a esos slots conserva máximo .010.",
        "Entregar: última versión, diff acumulado, historial de iteraciones, tests,",
        "deuda residual, veredicto de ronda.",
        "",
    ]
    for a in agents:
        lines += [
            f"## Agente {a['agente']} — {a['rol']}",
            "",
            f"- rol: {a['rol']} (`{a['role_id']}`)",
            f"- alcance: {a['alcance']}",
            "- archivos prioritarios:",
        ]
        lines += [f"  - `{f}`" for f in a["archivos_prioritarios"]]
        lines.append("- preguntas específicas:")
        lines += [f"  - {q}" for q in a["preguntas_especificas"]]
        lines += [
            "- formato de salida común: el de `PEDIDO_AUDITORIAS_MANUALES.md`",
            "- reglas de bucle interno: límite específico del slot según sección anterior",
            "",
        ]
    return "\n".join(lines) + "\n"


def render_pedido_copiar_pegar(source: Path, version: str, flat_zip: str | None,
                               tree_zip: str | None) -> str:
    pedido_path = source / "PEDIDO_AUDITORIAS_MANUALES.md"
    if not pedido_path.exists():
        pedido_path = ROOT / "PEDIDO_AUDITORIAS_MANUALES.md"
    if not pedido_path.exists():
        pedido = ("(PEDIDO_AUDITORIAS_MANUALES.md no encontrado en la fuente "
                  "ni en el repo raíz — completar manualmente)")
    else:
        pedido = pedido_path.read_text(encoding="utf-8")
    header = [
        f"PEDIDO DE AUDITORÍA — PAQUETE {version} — LISTO PARA COPIAR/PEGAR",
        "",
        "Adjuntá a este mensaje el zip indicado y pegá todo lo que sigue.",
        f"- Zip plano (si aplica): {flat_zip or 'no generado (excede límite o rechazado)'}",
        f"- Zip con subcarpetas (si aplica): {tree_zip or 'no generado (idéntico al plano)'}",
        "",
        "----- COMIENZO DEL PEDIDO -----",
        "",
    ]
    footer = ["", "----- FIN DEL PEDIDO -----", ""]
    return "\n".join(header) + pedido + "\n".join(footer)


def build_flat_zip(files: list[Path], source: Path, out: Path) -> list[str]:
    """Zip plano: nombres aplanados con '__'. Devuelve lista de colisiones."""
    seen: dict[str, str] = {}
    collisions: list[str] = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            rel = str(f.relative_to(source))
            flat = rel.replace("/", "__")
            if flat in seen:
                collisions.append(f"{rel} vs {seen[flat]}")
                continue
            seen[flat] = rel
            zf.write(f, flat)
    return collisions


def build_tree_zip(files: list[Path], source: Path, out: Path) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, str(f.relative_to(source)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default=str(ROOT))
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--audit-type", default="sistema_completo",
                    choices=sorted(AUDIT_TYPE_ROLE_PRIORITY))
    ap.add_argument("--agents", type=int, default=None,
                    help="override de cantidad de agentes (máx 12)")
    ap.add_argument("--force-flat", action="store_true",
                    help="generar zip plano aunque exceda 50 archivos")
    ap.add_argument("--no-flat", action="store_true",
                    help="si excede 50, no generar plano (equivale a responder 'no')")
    args = ap.parse_args(argv)

    source = Path(args.source_dir).resolve()
    outdir = Path(args.output_dir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    canon = load_delivery_canon(source)
    limits = canon["deliverables"]["1_zip_limpio"]["1_1_zip_plano"]
    ideal, hard_max = int(limits["ideal_max_files"]), int(limits["hard_max_files"])

    included, excluded = select_files(source)
    n = len(included)
    has_subdirs = any("/" in str(f.relative_to(source)) for f in included)

    # --- Regla 1.1: zip plano ---
    flat_name = f"preauditoria_{args.version}_plano.zip"
    flat_path: Path | None = outdir / flat_name
    warn = ""
    if n > hard_max:
        warn = (f"AVISO: el paquete tiene {n} archivos y excede el máximo de "
                f"{hard_max} para zip plano.")
        if args.force_flat:
            decision = "el operador lo pidió igual (--force-flat)"
        elif args.no_flat:
            decision = "el operador lo rechazó (--no-flat); se entrega solo el zip con subcarpetas"
            flat_path = None
        elif sys.stdin.isatty():
            resp = input(f"{warn} ¿Generarlo igual? [s/N]: ").strip().lower()
            if resp in ("s", "si", "sí", "y", "yes"):
                decision = "el operador aceptó interactivamente"
            else:
                decision = "el operador lo rechazó interactivamente; se entrega solo el zip con subcarpetas"
                flat_path = None
        else:
            decision = ("sin terminal interactiva y sin --force-flat: NO se genera "
                        "el plano; usar --force-flat para forzarlo")
            flat_path = None
        print(f"{warn} → {decision}")
    collisions: list[str] = []
    if flat_path is not None:
        collisions = build_flat_zip(included, source, flat_path)
        if collisions:
            print(f"ERROR: colisiones de nombres al aplanar: {collisions}",
                  file=sys.stderr)
            return 2
        note = "" if n <= ideal else f" (supera el ideal de {ideal})"
        print(f"1.1 zip plano: {flat_path.name} — {n} archivos{note}")

    # --- Regla 1.2: zip con subcarpetas solo si aporta algo ---
    tree_path: Path | None = None
    if has_subdirs or n > hard_max:
        tree_path = outdir / f"preauditoria_{args.version}_subcarpetas.zip"
        build_tree_zip(included, source, tree_path)
        print(f"1.2 zip con subcarpetas: {tree_path.name}")
    else:
        print("1.2 omitido: sin subcarpetas y ≤50 archivos (sería idéntico al 1.1)")

    # --- 3/8: manifest SHA-256 actualizado ---
    manifest = {
        "schema_version": "preauditoria_manual_minimal_manifest.v3",
        "created_utc": utc_now(),
        "version": args.version,
        "audit_type": args.audit_type,
        "selection_policy": "ultima_version_only_indispensable_files_no_historical_noise",
        "file_count": n,
        "flat_zip": flat_path.name if flat_path else None,
        "tree_zip": tree_path.name if tree_path else None,
        "flat_limits": {"ideal": ideal, "hard_max": hard_max,
                        "exceeded": n > hard_max},
        "files": [{"path": str(f.relative_to(source)),
                   "bytes": f.stat().st_size,
                   "sha256": sha256_file(f)} for f in included],
        "excluded_rules": [f"{r[0]}: {r[1]}" for r in EXCLUDE_RULES],
    }
    (outdir / "MANIFEST_MINIMO_AUDITORIA.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("3/8 MANIFEST_MINIMO_AUDITORIA.json (SHA-256 actualizado)")

    # --- 9: incluidos/excluidos ---
    lines = [f"# INCLUIDOS / EXCLUIDOS — {args.version}", "",
             f"Incluidos: {n} archivos", ""]
    lines += [f"- `{f.relative_to(source)}`" for f in included]
    lines += ["", f"Excluidos: {len(excluded)} entradas", ""]
    lines += [f"- `{e['path']}` — {e['reason']}" for e in excluded[:200]]
    if len(excluded) > 200:
        lines.append(f"- … y {len(excluded) - 200} más bajo las mismas reglas")
    (outdir / "INCLUIDOS_EXCLUIDOS.md").write_text("\n".join(lines) + "\n",
                                                   encoding="utf-8")
    print("9 INCLUIDOS_EXCLUIDOS.md")

    # --- 10: instrucciones multiagente ---
    agents = choose_agents(canon, args.audit_type, args.agents)
    (outdir / "INSTRUCCIONES_MULTIAGENTE.md").write_text(
        render_multiagent_md(canon, agents, args.audit_type, args.version),
        encoding="utf-8")
    print(f"10 INSTRUCCIONES_MULTIAGENTE.md ({len(agents)} agentes, tipo {args.audit_type})")

    # --- 1.3/6: pedido copiar/pegar ---
    (outdir / "PEDIDO_COPIAR_PEGAR.md").write_text(
        render_pedido_copiar_pegar(source, args.version,
                                   flat_path.name if flat_path else None,
                                   tree_path.name if tree_path else None),
        encoding="utf-8")
    print("1.3/6 PEDIDO_COPIAR_PEGAR.md")

    # --- 2/4/5: copiar los docs fuente al paquete de salida ---
    for doc in ("CONTEXTO_MINIMO_AUDITORIA.md", "PEDIDO_AUDITORIAS_MANUALES.md",
                "CHANGELOG_CORRECCION_AUDITORIA.md"):
        src_doc = source / doc
        if src_doc.exists():
            (outdir / doc).write_text(src_doc.read_text(encoding="utf-8"),
                                      encoding="utf-8")
            print(f"copiado: {doc}")
        else:
            print(f"AVISO: falta {doc} en la fuente", file=sys.stderr)

    print(f"\nPaquete de preauditoría completo en: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
