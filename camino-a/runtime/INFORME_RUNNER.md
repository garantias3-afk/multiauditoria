# INFORME — OT RUNNER + MIGRACION DE CONFIGURACION DE CAMINO_N

Estado terminal: **RUNNER_IMPLEMENTADO_ESPERANDO_REVISION** (pausa obligatoria OT sec 7).
Ejecutor: GLM via ZCode (`builtin:zai-coding-plan/GLM-5.2`).
Fecha: 2-ago-2026. ASCII sin acentos. Fallo cerrado.

Esta OT CONTINUA mi trabajo previo (no lo reemplaza). FASE 3 ya estaba hecha y
verde; esta corrida agrega FASE 1 (migracion de config) y FASE 2 (diagnostico de
camino_commons) y respeta la pausa obligatoria antes del smoke.

---

## 0. PRIMER ACTO — DECLARACION DE ESTADO (G12, OT sec 1)

La OT sec 1 dice "tres archivos sin trackear". **La realidad del arbol es otra**
(verificado contra `git cat-file HEAD:` y `git status`): hay **13 archivos sin
trackear, todos mios, todos intactos**. La OT se escribio sobre un snapshot
viejo. No silencio la diferencia.

| Archivo (camino-a/runtime/...) | Lineas | Estado | Nota |
|---|---|---|---|
| scripts/contradiccion.py | 221 | intacto, importa OK | uno de los 3 nombrados por la OT |
| scripts/defect_class.py | 125 | intacto, importa OK | uno de los 3 nombrados por la OT |
| INFORME_RUNNER.md | (este) | reescrito consolidando | uno de los 3 nombrados por la OT |
| **scripts/dispatch.py** | 331 | intacto | **HALLAZGO**: la OT sec 3 lo lista como "ya existe". FALSO: `git cat-file HEAD:camino-a/runtime/scripts/dispatch.py` -> NO existe. Es MIO. |
| **scripts/fallback_ladder.py** | 227 | intacto | **HALLAZGO idem**: OT sec 3 lo da por existente. Es MIO. |
| **scripts/loop_engine.py** | 271 | intacto | **HALLAZGO idem**: OT sec 3 lo da por existente. Es MIO. |
| scripts/tabla_loader.py | 345 | intacto | mio |
| scripts/resolve_root.py | 216 | intacto | mio |
| scripts/registro.py | 125 | intacto | mio |
| scripts/runner.py | 361 | intacto | mio |
| scripts/smoke_slot1.py | 211 | intacto | mio (NO corrido esta vez: pausa sec 7) |
| scripts/gen_camino_n_config.py | 224 | nuevo esta OT | FASE 1 M1/M2 |
| scripts/tests/ (5 archivos) | 58 tests | todos verdes | mios |
| config/camino_n.assignments.json | - | nuevo esta OT | FASE 1 M1, generado, no en canon/ |

Codigo genuinamente PRE-EXISTENTE (TRACKED at HEAD 45c29ad): `slot_runtime.py`,
`slot_execution.py`, `canon_loader.py`, `internal_loop_runner.py`,
`worker_codex_fallback.py`, `host_runtime.py`, `quality_log.py`, `drive_fuse.py`,
`run_multiaudit_cycle.py`, `overnight_master.py`, `start_overnight.py`,
`worker_gateway.py`. **Estos no los toque.**

### Dos realidades que contradicen a la OT y que no silencio
1. **Tabla NO esta en Intercambio** (OT sec 0 linea 20). `ls /Users/mariano/Intercambio/TABLA_CAMINO_N_v1.1.xlsx` -> No such file. Sigue solo en el repo `camino-n`. Use el repo (no pare por esto; la OT sec 0 lo autoriza).
2. **camino_commons no es un repo propio** (OT sec 0 lo llama "git local sin remoto"). Realidad: el repo es **MEGA_OT_WORK**; `camino_commons` es un subdirectorio TRACKED de ese repo. Sin remoto (confirmado). Detalle en FASE 2.

### Decisiones sec 2 — ya implementadas, NO reabiertas
- **Cadena de hash (D5):** opcion (a) + `prev_entry_id`. Sin cadena criptografica; dedup de `stable_entry_id` intacto; `prev_entry_id` da orden/deteccion de huecos. Deuda en `registro.HASH_CHAIN_DEBT`.
- **Tabla vs canon (sec 8):** clasificar primero. ASIGNACION -> gana tabla, sigue, artefacto `CONTRADICCION_TABLA_VS_CANON`. REGLA -> gana canon, `RUNNER_BLOCKED_CONTRADICCION`, sube a Mariano. Caso zai_glm (renombres v2 no subidos a canon) = ASIGNACION, no detiene.

---

## 1. IDENTIDAD Y RAIZ (G1)

- Host: `iMac-de-mariano.local` (iMac18,3). `detect_host()` reusado (no reescrito).
- `INTERCAMBIO_ROOT` resuelta y VERIFICADA una sola vez, congelada: `/Users/mariano/Intercambio`. Ambos marcadores presentes.

---

## 2. FASE 1 — MIGRACION DE CONFIGURACION (M1, M2, M3) — NUEVO

### M1 + M2: generador tabla -> JSON (determinista, round-trip)
- Nuevo: `scripts/gen_camino_n_config.py`. Reusa `tabla_loader.load_tabla` (no re-parsea la xlsx).
- Formato: espeja `CANON_WORKFLOW_SLOTS.v1.json` (`slots`: cycle/role/loops/correction_policy/routes) + `config/provider.policy.json`. **Destino `config/camino_n.assignments.json`, NO en `canon/`** (prohibicion sec 10: no mezclar CAMINO_N en el canon compartido).
- **Determinismo (G5):** sin timestamps, claves ordenadas, listas derivadas ordenadas por (step, orden, route_id). **Verificado end-to-end sobre la tabla real**: dos generaciones -> sha256 identico `7898b2cd915b644a1abed62ea9323d67eb0d3929985854e88e38170bbaf7f3d9`. 7 tests en `test_gen_config_roundtrip.py`.
- Salida: 13 slots, 43 modelos, cycles `{A:[1,2,3], B:[4,5,6], C:[7,8,9,10], FINAL:[11,12,14]}`.
- **Observacion (no error):** la tabla no tiene slot 13 en ninguna de sus dos hojas (`CAMINO_N_v1_1` ni `CAMINO_N`); el paso va 12 -> 14. La proyeccion lo refleja fielmente. Si slot 13 deberia existir, es un asunto de la tabla, no del generador.

### M3: registrar CAMINO_N como camino disponible — HALLAZGO, no invencion
La OT M3 dice: "si esa distincion no existe todavia, decilo: es un hallazgo".
**HALLAZGO:** NO existe ningun mecanismo "Camino A vs B vs N". Lo unico
selector-like es `profiles` en `CANON_RUNTIME_POLICY.v1.json`, y es sobre
**disponibilidad de Claude** (`with_claude`/`without_claude`/`sandbox_reference`),
no sobre identidad de Camino. Las unicas cadenas `camino_n` en el arbol estan en
mis archivos nuevos. **Hoy CAMINO_N es pura configuracion (tabla + JSON
proyectado), sin registro en el runtime.** No invente un mecanismo (prohibido).

**Propuesta (sin ejecutar, para tu decision):**
- (a) Anadir un perfil `camino_n` en `CANON_RUNTIME_POLICY.v1.json` que el runner
  seleccione, dejando el canon compartido intacto. Minimo impacto, encaja en el
  mecanismo existente.
- (b) Que `config/camino_n.assignments.json` baste y el runner lo cargue por
  nombre (`runner.py --camino camino_n`) sin tocar el canon. Mas simple aun;
  el "camino" es solo un archivo de asignaciones.
- **Mi recomendacion: (b).** El perfil de runtime policy no modela "que camino
  corre"; modela "que workers/Claude estan disponibles". Mezclar ahi una
  identidad de Camino seria sobrecargar el mecanismo. Cargar el JSON por nombre
  es lo mas fiel al diseno actual. Pero es tu decision.

---

## 3. FASE 2 — camino_commons: DIAGNOSTICO + PROPUESTA (C1-C3), SIN EJECUCION

**No movi ni copie nada.** Esto es diagnostico y propuesta.

### C1 + C3 (verificado)
- El repositorio es **`MEGA_OT_WORK`** (`/Users/mariano/Intercambio/MEGA_OT_WORK/.git`).
  `camino_commons` es un **subdirectorio TRACKED** de ese repo (no un repo
  propio: no tiene `.git` propio). Corrijo la OT sec 0 al respecto.
- **Sin remoto**: `git -C MEGA_OT_WORK remote -v` -> vacio. Confirmado.
- **HEAD (punto de retorno):** `e0d4592` ("R5: 7 defects corregidos..."). Rama `l6-r5-remediation`.
- **Arbol:** limpio ahora (`git status --short` vacio). Nota: en una de mis
  lecturas aparecio un ` M ledger.py` transitorio que ya no esta; dejo
  constancia para que no sorprenda si se reproduce (probablemente indice stale).
- `camino_commons`: 136K, 7 modulos + `__init__.py` (adapters, cost_class, envelope, identity, ingest, ledger, reason_codes). Ya es un paquete autocontenido.

### C2 — propuesta (NO ejecutada)
**Dependencias medidas:** multiauditoria **NO** importa `camino_commons` (lo
verifique: cero imports). Los unicos dependientes estan **dentro de MEGA_OT_WORK**
(MANIFEST.txt, tests/conftest.py, test_cost_class, test_ingest, test_ledger,
ESTADO_L0.md, salida_rojo_L4.txt). Eso es central para decidir:

- **(a) camino_commons como paquete dentro de multiauditoria.**
  - Pro: lo usa el runtime que corre (multiauditoria), y "el artefacto mas
    critico y menos protegido" pasaria a tener remoto + sincronia en ambas
    maquinas. Es autocontenido (paquete con `__init__.py`), encaja limpio.
  - Con: sus tests y el resto de L6 (que SI dependen de el) se quedarian en
    MEGA_OT_WORK sin remoto. Habria que decidir si el paquete viaja solo.
- **(b) MEGA_OT_WORK completo a su propio repo remoto.**
  - Pro: conserva la coherencia (camino_commons + sus tests L6 + MANIFEST +
    ESTADO_L0 viajan juntos). Un solo remoto cubre todo el artefacto critico.
  - Con: mas superficie (incluye cosas que quizas no quieren remoto publico).
- **Mi recomendacion: (b).** La razon es que `camino_commons` y sus tests L6
  son inseparables en la practica (los tests son la unica verificacion del
  paquete). Separar el paquete de sus tests en (a) deja los tests sin remoto y
  sin proteccion. Pero repito: es tu decision; no ejecuto nada.

---

## 4. FASE 3 — EL RUNNER (R1-R6) — YA HECHO Y VERDE (no repetido)

Reusado (con ruta original, G3/G11):
- Escritura atomica: `drive_fuse.fuse_safe_write` (`drive_fuse.py:40`). Reusada en fallback_ladder, registro, loop_engine, gen_camino_n_config.
- Deteccion de host: `host_runtime.detect_host` (`host_runtime.py:258`).
- Quality log + dedup: `quality_log.record_quality_event` (`quality_log.py:184`), `stable_entry_id` (`:54`).
- Patrones: `canon_loader` (espejado en tabla_loader y gen_camino_n_config), `restart_big_loop` (`overnight_master.py:453`, adaptado en loop_engine.decide_largo), `internal_loop_runner` (`:299`/`:166`).

Lo escrito de cero (esta y la OT previa): resolve_root, tabla_loader, contradiccion, fallback_ladder, dispatch, defect_class, loop_engine, registro, runner, smoke_slot1, gen_camino_n_config + tests.

Para tu revision sec 7:
- **Test de resolve_root con raiz falsa (G2):** `test_rejects_root_with_correct_name_but_no_markers` (el caso que fallo el 1-ago: dir "Intercambio" sin marcadores -> RECHAZADA).
- **Tests de las 3 condiciones de R4 (G6):** `test_no_disponible_fallback_enters`, `test_corrio_y_fallo_fallback_stops`, `test_escribio_pero_no_pasa_gate_is_loop_material`.

---

## 5. GATES G1-G12

| Gate | Estado | Evidencia |
|---|---|---|
| G1  Raiz verificada con marcadores, host declarado | VERDE | iMac-de-mariano, `/Users/mariano/Intercambio`. |
| G2  resolve_root + test raiz-con-nombre-sin-marcadores | VERDE | `test_rejects_root_with_correct_name_but_no_markers`. |
| G3  fuse_safe_write reusado, ruta declarada | VERDE | `drive_fuse.py:40`. |
| G4  Cero asignaciones hardcodeadas | VERDE | Todo viene de la tabla; cambiar un modelo = una celda. |
| **G5**  Round-trip del generador: dos corridas, sha256 identico | VERDE | `7898b2cd...`, 7 tests, verificado sobre tabla real. |
| G6  3 condiciones de R4, un test cada una | VERDE | test_fallback_ladder.py. |
| G7  3 niveles de bucle, contadores persistentes | VERDE | test_loop_engine.py (R1/R2/R3). |
| G8  Destino del bucle mediano sale de la clase | VERDE | test_mediano_a/b_goes_to_*. |
| G9  10 campos conservados + prev_entry_id | VERDE | Smoke previo confirmo 10 campos; prev_entry_id en registro.py. |
| G10 Contradiccion clasificada segun sec 2 (no a ojo) | VERDE | contradiccion.py (ASIGNACION/REGLA mecanico). |
| G11 Cero modulos reescritos que funcionaban | VERDE | Solo reuse + codigo nuevo en archivos nuevos. |
| **G12** Tus 3 archivos integrados o estado declarado | VERDE | Esta seccion 0: 13 archivos declarados + correccion del "ya existe". |

**Todos los gates en verde.** Estado: `RUNNER_IMPLEMENTADO_ESPERANDO_REVISION`.

---

## 6. PAUSA OBLIGATORIA (OT sec 7)

NO arranque el smoke (FASE 4). Espero tu revision sobre:
1. Generador tabla -> JSON + round-trip (G5).
2. Hallazgo M3 (no hay mecanismo A/B/N) + mi recomendacion (b).
3. Propuesta C2 de camino_commons + mi recomendacion (b).
4. Declaracion de los 13 archivos + correccion del "ya existe".

---

## 7. VERIFICACION FINAL

```
58 tests verdes (51 previos + 7 de round-trip).
HEAD multiauditoria: 45c29ad (sin commit/push/merge/reset).
config/camino_n.assignments.json generado, sha256 7898b2cd... determinista.
camino_commons: NO movido, NO copiado (solo diagnostico).
```

## 8. DEUDAS DECLARADAS
1. **Hash chain (D5):** (a) + `prev_entry_id`. Deuda registrada.
2. **Canon viejo:** renombres zai_glm v2 no subidos a canon/. Se clasifican ASIGNACION y la corrida sigue; deuda P0 de actualizar `canon/` fuera de esta OT.
3. **M3 / C2:** propuestas sin ejecutar, esperan tu decision.
4. **Production Invoker:** `GatewayInvoker.__call__` (runner.py) levanta `NotImplementedError` hasta cablearse contra `worker_gateway`. Contrato y semantica NO_DISPONIBLE/CORRIO_Y_FALLO ya fijados y testeados.

FIN.
