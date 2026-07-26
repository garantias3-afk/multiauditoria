# Mapeo previo de integración — ROUTER v5 R2 en Camino A

## 0. Declaración del analista (exigida por la OT)

- **autor:** ZCode (analista técnico de sólo lectura).
- **modelo exacto:** `builtin:zai-coding-plan/GLM-5.2`.
- **alcance realmente inspeccionado:** `/Users/mariano/Documents/multiauditoria` (rama `main`, `git status` limpio salvo `deliverables/` y `shared/audits/` no rastreados, preservados). Leí `shared/STATUS.md`, `shared/RUNBOOK.md`, `README.md`, `docs/TDD_SYSTEM_BLUEPRINT.md` (§1.1–1.3, §6.2), `camino-b/README.md`. Inspeccioné `camino-a/runtime/`: los 5 JSON de `canon/`, las políticas de `config/` (`workers.plan.json`, `roles.json`, `path_roles.json`, `primary_brain_policy.json`), y los scripts clave (`overnight_master.py`, `run_multiaudit_cycle.py`, `slot_runtime.py`, `internal_loop_runner.py`, `worker_agentic_local.py`, `consolidate_results.py`, `primary_brain_adapter.py`, `validate_bundle.py`, `candidate_updates.py`, `peer_executor.py`, los wrappers `worker_codex.py`/`worker_claude_code.py`/`worker_gateway.py`/`worker_local_static.py`), los prompts de `generated/`, el `schemas/schemas.json` y un run real (`outputs/operational_runs/RUN_20260713_022749_eb68e_slot14_subscription_smoke/`). Búsqueda determinista (grep) de `router_v5|axes_of|axis_matrix|domain_rules_hash|num_ctx|65536|seis|six|taskcard|inventory|packet` en todo el repo (excl. `.git`, `node_modules`, `deliverables`). **No toqué archivos, no hice commits, no ejecuté canarios.**
- **Candidata aprobada verificada:** `/Users/mariano/KIMI_ROUTER_V5_OT/outputs/router_v5.py` — **NO LO ENCONTRÉ en esa ruta exacta** (la OT la escribe con un espacio `"kimi code"`; la ruta real con la que trabajé en la OT anterior es `/Users/mariano/kimi code/KIMI_ROUTER_V5_OT/outputs/router_v5.py`). Confirmo por el SHA esperado `771b67…e267c0` que es la R2 ya reauditada. Lo tomo como entrada válida sin re-leerlo (su contrato I/O ya está fijado por la reauditoría previa: `axes_of(rel_path, src) -> list[str]`, `route(rel_path, src, rules=DOMAIN_RULES) -> list[dict]`, `domain_rules_hash() -> str`).

---

## HECHOS (verificados con archivo/línea)

### H1. No existe ningún consumidor del router en el repositorio
Búsqueda `grep -rI "router_v5|axes_of|axis_matrix|domain_rules_hash"` en todo el repo (excl. `.git`/`node_modules`/`deliverables`): **0 coincidencias**. El router v5 R2 no es importado, referenciado ni invocado por ningún script, test, canon, política, schema o prompt de Camino A o Camino B.

### H2. El sistema no distribuye archivos por especialidad/eje
- **Inventario/candidate:** `candidate_updates.py:40` `candidate_source(run_dir)` retorna un **único** directorio snapshot (`00_CANDIDATE` o fallback `INPUT/target_snapshot`). No hay descomposición por eje.
- **Distribución a workers:** cada worker recibe **la totalidad** del snapshot. `worker_codex.py:55` `prepare_workspace` copia el snapshot completo en `WORKSPACES/codex/`; `dispatch_codex` (`overnight_master.py:514-521`) hace `shutil.copy2` de todo `candidate_source(run_dir).rglob("*")`. `peer_executor.py:392` `_snapshot_files` copia el snapshot entero para non-LM workers (con topes `snapshot_max_files=20000`, `snapshot_max_file_bytes=50MiB`). No existe noción de "worker de seguridad" vs "worker de contratos".
- **No hay TaskCards ni packets:** `grep "taskcard|task_card|inventario|inventory|packet|work_packet|assignment"` sólo halla `probe_live_routes.py:12` ("inventory" = inventario de rutas en seco, no de archivos) y `render_contracts.py` (render de prompts). El buzón del blueprint (`docs/TDD_SYSTEM_BLUEPRINT.md:681-699`) describe un **único artefacto** `target_snapshot` con `role:"target_source"` y un `routing` que elige `start_slot` — **no asigna archivos a workers**.

### H3. La unidad de orquestación es el SLOT, no el eje
- `canon/CANON_WORKFLOW_SLOTS.v1.json:23-35`: `big_loop.slots = [1..14]`, agrupados en ciclos A=[1,2,3], B=[4,5,6], C=[7,8,9,10], FINAL=[11,12,13,14].
- `slot_runtime.py:34-54` `SlotSpec` y `SlotPlan`: el plan se construye **canónicamente** desde `CANON_WORKFLOW_SLOTS` + `CANON_RUNTIME_POLICY` (HARD RULE §10/§11: "NO hardcoded list of slots/providers/models"). Cada slot tiene `role`, `routes`, `fallback_chain`, `loops`, `correction_policy`, `internal_loop`.
- Los roles de slot (`docs/TDD_SYSTEM_BLUEPRINT.md:41-56`) son funcionales (auditor inicial paralelo, harvest manual, consolidator, writer, gate, corrector, aprobador slot 14), **no por eje de dominio**.

### H4. Los workers son wrappers de CLI/API por proveedor, no por especialidad
- `config/workers.plan.json`: 5 entries — `codex` (CLI), `claude_code` (CLI), `gateway` (API), `manual_gpt`, `manual_claude`.
- En tiempo de ejecución hay **8 lanes** en el bus: `13_WORKER_BUS/{codex, claude_code, gateway, local_static, lmstudio_bridge, codex_fallback, manual_gpt, manual_claude}/` (verificado en el run real). `local_static`, `lmstudio_bridge` y `codex_fallback` se suman en `overnight_master.py` (`dispatch_local_static:886`, `dispatch_lmstudio:654`, `dispatch_codex_fallback:774`).
- Cada worker consume `13_WORKER_BUS/<worker>/IN/job.json` y produce `OUT/<bundle>/{OUTPUT_MANIFEST.json, result.json, *.DONE}`.

### H5. "Seis trabajadores" y `num_ctx=65536` no existen como tales
- Búsqueda `grep "\bseis\b|\bsix\b"`: sólo aparece la cadena de versión `v1.3.22-slot1-slot4-six-loops` (en `canon/*.v1.json`, `package_release.py:34`, `build_gpt_knowledge_bundle.py:44`). STATUS.md:36-38 aclara: *"slots 1 y 4: máximo `6`, versiones `candidate.001`–`candidate.006`"*. Es decir, **"six" = seis iteraciones del bucle interno de los slots 1 y 4**, no seis workers.
- Búsqueda `grep "num_ctx"`: **0 coincidencias** en todo el repo. Búsqueda `grep "65536"`: sólo `package_release.py:72` (chunk I/O `f.read(65536)`), un `node_modules` y dos artefactos ajenos en `deliverables/`. **`num_ctx=65536` no está materializado en ningún componente** de Camino A.

### H6. "Obligatoriedad transversal de correctitud" es un concepto del router, no de Camino A
- Búsqueda `grep "correctness_obligation|transversal"` en `scripts/`: **0 coincidencias** en código Camino A; la única de `transversal` está en `slot14_handoff.py:352` (prosa de un prompt). `correctness_obligation` es un campo que produce **el router** (`route()` en R2, lo vimos en la reauditoría: cada membership lleva `"correctness_obligation":True`).
- Lo más cercano en Camino A: `internal_loop_contract` (`CANON_WORKFLOW_SLOTS.v1.json:32` `agentic_internal_loop`) y `correctness` implícita vía `validate_slot_evidence` + `_slot_internal_loop_satisfied` (`overnight_master.py:235-256`).

### H7. `domain_rules_hash` no existe en Camino A
Búsqueda `grep "domain_rules_hash"`: 0. La trazabilidad de Camino A es por `candidate_sha256` (job binding en `harvest_workers`, `overnight_master.py:1308-1353`) y `canon_version` (`camino_shared_canon.v1.3.22-slot1-slot4-six-loops`). El router aporta `domain_rules_hash` (`45a984eb…`) pero **nadie lo consume** hoy.

### H8. Los prompts se construyen en dos lugares, ambos sobre el snapshot completo
- `_build_lmstudio_slot_prompt` (`overnight_master.py:594-651`): arma un markdown con **todos** los archivos del snapshot bajo un techo de `max_chars=200000`, con sección `## Coverage` (`included_files`/`omitted_files`). Es el único punto donde existe una noción de "cobertura".
- Prompts de wrapper: `worker_codex.py`/`worker_claude_code.py` pasan el workspace al CLI; los prompts base están en `generated/PROMPT_*.md` (auto-generados por `render_contracts.py`, incluyen el contrato compartido Camino A/B). El adaptador del cerebro (`primary_brain_adapter.py`) construye `BRAIN_TASK_REQUEST.json` por stage (consolidation/code_generation/post_code_review/closure).

### H9. Consolidación y cobertura
- `consolidate_results.py:25-65` `consolidate(run_dir)`: lee `ACCEPTED/*.json`, los ordena (`bug_found` → `patch_proposed` → resto), y deja el `merger` workspace. **No computa cobertura por eje**; la "cobertura" existente es la del prompt LM Studio (H8) y la mecánica de slots completados (`_complete_slot`, `overnight_master.py:460-472`).
- La consolidación de evidencia por slot: `valid_slot_bus_evidence` (`overnight_master.py:361-417`) valida bundles del bus; `harvest_workers` (l. 1264) recolecta `accepted`/`rejected`/`pending`.

### H10. Camino A y Camino B comparten un único runtime importable
`camino-b/README.md:14-19`: *"El runtime es una sola unidad importable bajo `../camino-a/runtime/`"*. Los componentes de Camino B (`camino_b_gateway.py`, `camino_b_slot14_bridge.py`, `camino_b_outbound_agent.py`) viven **físicamente** dentro de `camino-a/runtime/scripts/`. La separación A/B es **lógica/contractual** (vía `config/path_roles.json`), no física. Cualquier cambio en `camino-a/runtime/scripts/` toca el árbol compartido.

### H11. No hay "punto de conexión inequívoco" para `axes_of()`/`route()`
Por H1–H9, ninguna función existente recibe `(rel_path, src)` y produce una decisión que alguien consuma como asignación a un worker. Los candidatos que recorren `axes_of`/`route` naturalmente serían: `_build_lmstudio_slot_prompt` (que ya itera `snapshot.rglob("*")`), `prepare_workspace` de los wrappers, o `consolidate_results`. **Ninguno hoy usa el eje para particionar trabajo.**

### H12. `volume_generalist` no existe como concepto en Camino A
Búsqueda `grep "volume_generalist"`: 0. Es el eje residual del router; en Camino A el equivalente más cercano es el slot/ciclo "A" de auditores iniciales paralelos, pero la semántica es distinta.

---

## INFERENCIAS (deducidas de los hechos)

- **I1.** Copiar `router_v5.py` al repo **no integra nada**: por H1, no hay importador. "Integración" requiere decidir primero **qué rol semántico** cumple la clasificación por ejes en un sistema que hoy orquesta por slot y por proveedor.
- **I2.** El modelo mental de la OT ("seis trabajadores por especialidad", "TaskCards", "packets", "distribución de archivos por eje", "num_ctx=65536") **no coincide** con la arquitectura real (H2–H5). Ese modelo describe una variante **no construida** (probablemente la variante content-first/prefix-sharing que la propia OT descarta al final). De ahí que la OT advierta "no asumas que copiar `router_v5.py` basta".
- **I3.** Hay dos roles **posibles** y **excluyentes** para el router en Camino A, y la elección es una decisión arquitectónica, no técnica:
  - **(α) Particionado de inventario:** crear TaskCards por eje y asignarlas a workers especializados. Requiere **nuevos** componentes (inventory builder, dispatcher por eje, TaskCard schema) y **rompe** la invariante "cada worker ve el snapshot completo" (H2). Esto reabre la variante descartada.
  - **(β) Enriquecimiento de prompts/evidencia:** invocar `axes_of()`/`route()` **sin** particionar — sólo para etiquetar el snapshot con su mezcla de ejes y añadir la "obligación transversal de correctitud" al prompt de cada slot. Requiere un único punto de inserción en `_build_lmstudio_slot_prompt` (H8) y/u 80 en el adaptador del cerebro, **sin** tocar el bus ni los workers.
- **I4.** Por la regla explícita de la OT ("no reabrir content-first/prefix-sharing"), la variante (α) queda descartada por construcción. La única integración coherente con las invariantes exigidas es **(β)**.
- **I5.** Aun en (β), el punto exacto de invocación depende de una decisión: ¿el enriquecimiento se hace en el **prompt** (sólo LM Studio y los prompts generados), en el **adaptador del cerebro** (`primary_brain_adapter.collect_input_for_stage`), o en el **consolidador** (`consolidate_results`)? Los tres son legítimos y producen efectos distintos. Sin esa decisión, no hay "punto de conexión inequívoco".
- **I6.** La trazabilidad por `domain_rules_hash` (H7) exige **registrar** el hash en el run (p. ej. en `RUN_CONFIG.json` o en el `OUTPUT_MANIFEST`) para que sea auditable; hoy no hay campo para él. Es un cambio de schema menor pero necesario en cualquier variante.
- **I7.** La integración **no toca Camino B** en ninguna de las dos variantes: el router opera sobre el snapshot del candidato (Camino A), y Camino B es transporte/ejecución (`path_roles.json`: `gateway_is_transport_only:true`). La separación lógica A/B se preserva.

---

## Decisiones todavía faltantes

1. **[DECISIÓN BLOQUEANTE, ÚNICA]** ¿Qué rol debe cumplir el router en Camino A?
   - **(α)** Particionado de inventario por eje (crea TaskCards, especializa workers) — **descartado** por la OT (reabre content-first/prefix-sharing).
   - **(β)** Enriquecimiento de prompts/evidencia sin particionado (etiqueta el snapshot con ejes + obligación de correctitud, sin tocar el bus) — **única coherente** con las invariantes.
   - **(γ)** Sólo trazabilidad/observabilidad: registrar `axes_of` y `domain_rules_hash` en el run como metadato, sin afectar prompts ni dispatch.

   Sin esta decisión no se puede fijar el punto de invocación (I5), el formato de I/O, ni los archivos a tocar.

2. **[Derivada de (β) si se elige]** ¿Dónde se inyecta el enriquecimiento — prompt LM Studio, adaptador del cerebro, consolidador, o los tres?

3. **[Derivada]** ¿La obligación transversal de correctitud debe propagarse a **todos** los slots o sólo a los de tipo "auditor"/"consolidator"?

4. **[Derivada]** ¿`volume_generalist` debe mapearse a algún slot/ciclo existente (p. ej. ciclo A) o queda como etiqueta puramente informativa?

---

## Diagrama textual

### Flujo actual (Camino A, verificado)

```
                  ┌──────────────────────────────────────────┐
                  │  camino.robot_inbox.v1 (buzón)            │
                  │  artifact: target_snapshot (ÚNICO)        │   docs/TDD_SYSTEM_BLUEPRINT.md:681-699
                  │  routing: { start_slot, forbidden_* }     │
                  └───────────────────┬──────────────────────┘
                                      ▼
        ┌─────────────────────────────────────────────────┐
        │ run_multiaudit_cycle.py (entrypoint, sin política)│  run_multiaudit_cycle.py:1-27
        │  canon_loader → slot_runtime.build_slot_plan     │
        └───────────────────┬─────────────────────────────┘
                            ▼
        ┌──────────────────────────────────────────────────┐
        │ overnight_master.py (state engine, fase: created │
        │   → manual_window → running → consolidating →    │   overnight_master.py:95-103
        │   testing → finalizing → closed)                 │
        │                                                  │
        │  Por cada slot en big_loop [1..14]:              │
        │   • dispatch_<worker> escribe job.json en         │   dispatch_codex:505, dispatch_gateway:554,
        │     13_WORKER_BUS/<worker>/IN/                   │   dispatch_lmstudio:654, dispatch_claude_code:817,
        │   • cada worker recibe el snapshot COMPLETO      │   dispatch_local_static:886, dispatch_codex_fallback:774
        │     (candidate_source → 00_CANDIDATE)            │   candidate_updates.py:40
        │   • execute_inline_workers / peer_executor        │   overnight_master.py:1028, peer_executor.py:392
        │   • harvest_workers + validate_bundle            │   overnight_master.py:1264, validate_bundle.py
        │   • valid_slot_bus_evidence / _complete_slot      │   overnight_master.py:361, 460
        └───────────────────┬──────────────────────────────┘
                            ▼
        ┌──────────────────────────────────────────────────┐
        │ consolidate_results.py  →  ACCEPTED/*.json        │  consolidate_results.py:25
        │ package_final.py        →  dist/*.zip             │
        │ slot 14 (claude_code | codex_fallback) = único     │  docs/TDD_SYSTEM_BLUEPRINT.md:37,56
        │   aprobador terminal                             │
        └──────────────────────────────────────────────────┘

   Workers (8 lanes, NO especializados por eje):
     codex · claude_code · gateway · local_static · lmstudio_bridge ·
     codex_fallback · manual_gpt · manual_claude

   Ausencias verificadas:  router_v5 · axes_of · axis_matrix ·
     domain_rules_hash · num_ctx=65536 · TaskCards · packets ·
     "seis trabajadores por eje"
```

### Flujo propuesto — variante (β) [sólo si se decide]

```
                ┌────────────────────────────────────────────┐
                │ NUEVO: router_facade.py                     │
                │   axes_of(rel, src) / route(rel, src)       │
                │   + domain_rules_hash() snapshot por run    │
                │   (envuelve router_v5.py sin tocar el motor)│
                └───────────────┬─────────────────────────────┘
                                │ (lectura, sin particionar)
            ┌───────────────────┼───────────────────────┐
            ▼                   ▼                       ▼
   _build_lmstudio_slot_prompt  primary_brain_adapter   consolidate_results
   (overnight_master.py:594)    collect_input_for_stage  (consolidate_results.py:25)
            │                   (primary_brain_adapter.py)
            ▼                   ▼                       ▼
   prompt enriquecido con       BRAIN_TASK_REQUEST      manifest con
   "## Cobertura por ejes"      con obligación          domain_rules_hash +
   + obligación transversal     transversal de          mezcla de ejes del
   de correctitud               correctitud             candidato

   SIN tocar: 13_WORKER_BUS, wrappers worker_*, peer_executor,
              slot_runtime, canon (slot/provider/model),
              Camino B (gateway/bridge/outbound).
```

---

## Plan de parche archivo por archivo (esqueleto — no es código)

**Precondición:** debe estar resuelta la DECISIÓN BLOQUEANTE (β o γ). Lo siguiente asume **(β)** (la única coherente con las invariantes). Si se elige **(γ)**, sólo aplica la fila "trazabilidad".

| archivo | acción | cambio (descripción, no código) |
|---|---|---|
| `camino-a/runtime/scripts/router_v5.py` | **NUEVO** | Copia bit-idéntica de la candidata aprobada (SHA `771b67…e267c0`). No se modifica. |
| `camino-a/runtime/scripts/router_facade.py` | **NUEVO imprescindible** | Envoltorio delgado: itera `candidate_source(run_dir).rglob("*")`, llama `axes_of`/`route`, agrega `domain_rules_hash`, expone `summarize_axes(run_dir) -> dict` y `obligation_text(run_dir) -> str`. Aísla al resto del repo de la API del router. |
| `camino-a/runtime/scripts/overnight_master.py` | **modificar** (1 punto) | En `_build_lmstudio_slot_prompt` (l. 594-651): agregar una sección `## Cobertura por ejes` y la obligación transversal, vía `router_facade`. Es el único punto donde ya existe una noción de cobertura. |
| `camino-a/runtime/scripts/primary_brain_adapter.py` | **modificar** (1 punto, opcional) | En `collect_input_for_stage`: añadir el resumen de ejes y la obligación al `BRAIN_TASK_REQUEST.json`. |
| `camino-a/runtime/scripts/consolidate_results.py` | **modificar** (1 punto, opcional) | Registrar `domain_rules_hash` y la mezcla de ejes en el manifiesto de consolidación. |
| `camino-a/runtime/scripts/render_contracts.py` | **modificar** (opcional) | Para que la obligación transversal quede persistida en `generated/PROMPT_*.md` y no sólo en el prompt runtime. |
| `camino-a/runtime/schemas/schemas.json` | **modificar** | Añadir campos opcionales `domain_rules_hash` y `axis_summary` al `output_manifest.schema.json` (compat hacia atrás). |
| Camino B (`camino_b_*`, `path_roles.json` camino_b) | **SIN CAMBIOS** | Por I7. |

**Archivos nuevos imprescindibles:** `router_v5.py` + `router_facade.py` (2). Todo lo demás es modificación puntual.

---

## Pruebas mínimas y comandos

**Conservar íntegramente (no tocar):** las 21 suites existentes bajo `camino-a/runtime/tests/` (112 passed vigente según STATUS.md), en particular `test_canonical_master_slots.py`, `test_all_canonical_internal_loops.py`, `test_parallel_workers.py`, `test_workspace_isolation.py`, `test_release_hygiene.py` — protegen las invariantes que la OT exige mantener.

**Pruebas mínimas de integración a agregar (3):**
1. `tests/test_router_facade.py` — dado un run con un snapshot fixture, `summarize_axes` retorna los ejes esperados y `domain_rules_hash` es estable.
2. Extensión de `tests/test_canonical_master_slots.py` (o nuevo `test_slot_prompt_has_axis_coverage.py`) — el prompt LM Studio de un slot incluye la sección de cobertura por ejes y la obligación transversal, sin exceder `max_chars`.
3. `tests/test_consolidate_domain_hash.py` — el manifiesto de consolidación lleva `domain_rules_hash` y es trazable.

**Comandos:**
- Suite del router (pre-integración, sin tocar el repo): ya ejecutada en la OT anterior (75/75, 21/21, etc.).
- Suite Camino A: `cd camino-a/runtime && ./bin/run_tests.sh` (STATUS.md: `110 passed`, `RUN_TESTS_OK`).
- Smoke de integración mínimo: `python3 scripts/run_multiaudit_cycle.py --canon-profile sandbox_reference --dry-run` para verificar que el plan de slots y la fase `running` no rompen.

---

## Cómo se mantienen las invariantes (en la variante β)

| invariante exigida | cómo se mantiene |
|---|---|
| seis trabajadores | **N/A**: por H5 no existen "seis trabajadores"; existen 8 lanes por proveedor. La integración β **no los toca**. (Si la OT significa "seis iteraciones de slots 1/4", esas iteraciones están en el canon y tampoco se tocan.) |
| `num_ctx=65536` | **N/A**: por H5 no existe en el repo. No se introduce ni se elimina. Si la OT exige materializarlo, es **otra decisión arquitectónica** separada (¿en qué route/wrapper?). |
| paralelismo existente | `_parallel_worker_cap`/`execute_inline_workers` (`overnight_master.py:1013, 1028`) intactos; el router es lectura pura. |
| `volume_generalist` como cobertura residual | el router ya lo emite como eje residual; en β se reporta en el resumen sin asignarle un slot. |
| obligación transversal de correctitud | se inyecta como **texto** en el prompt LM Studio y/o el `BRAIN_TASK_REQUEST`; el campo `correctness_obligation` del router la fundamenta. |
| trazabilidad por `domain_rules_hash` | se registra en el manifiesto de consolidación / `RUN_CONFIG.json` (cambio de schema optativo). |
| Camino A como orquestador | β no altera `overnight_master` como state engine ni a Codex como orquestador lógico (`path_roles.json`). |
| Camino B sin cambios | β no toca `camino_b_*` ni la entrada `camino_b` de `path_roles.json`. |

---

## Riesgos de integración

- **R1 (alto, bloqueante):** la OT mezcla un modelo mental ("seis trabajadores", TaskCards, packets, `num_ctx`) que **no existe** en el repo. Cualquier integración que asuma ese modelo rompería silenciosamente las invariantes reales. La DECISIÓN BLOQUEANTE debe resolver la disonancia antes de escribir nada.
- **R2 (medio):** copiar `router_v5.py` sin envoltorio acopla a Camino A la API completa del router; un `router_facade` es imprescindible para contener el acoplamiento y poder re-auditar el motor sin reauditar Camino A.
- **R3 (medio):** en β, el enriquecimiento del prompt consume presupuesto de contexto (`max_chars=200000` en `_build_lmstudio_slot_prompt`); el resumen de ejes debe ser acotado o descontará archivos del snapshot.
- **R4 (bajo):** el `domain_rules_hash` sólo es trazable si se registra en un artifact versionado; si se omite, la invariante de trazabilidad queda nominal.
- **R5 (bajo):** al compartir árbol físico (`camino-a/runtime/scripts/`), un descuido podría tocar componentes de Camino B; el plan β los deja explícitamente fuera.

---

## VEREDICTO

De los dos permitidos:

## `BLOQUEADO_POR_DECISION_ARQUITECTONICA`

**Única decisión necesaria:** elegir el **rol semántico** del router en Camino A entre (α) particionado por eje [descartado por la propia OT: reabre content-first/prefix-sharing], (β) enriquecimiento de prompts/evidencia sin particionado [única coherente con las invariantes], o (γ) sólo trazabilidad/observabilidad.

**Motivo del bloqueo, en una frase:** por H1 no existe consumidor del router; por H2–H5 el modelo de workers es por proveedor/slot, no por eje, y conceptos de la OT ("seis trabajadores", `num_ctx=65536`, TaskCards, packets) no están materializados; por H11 no hay punto de conexión inequívoco para `axes_of()`/`route()` — el punto exacto depende de cuál de (β)/(γ) se decima. Esa elección es arquitectónica (afecta prompts, schema y adaptador del cerebro) y no es decidible por análisis técnico solo.

No escribí código ni archivos. Me detengo aquí.