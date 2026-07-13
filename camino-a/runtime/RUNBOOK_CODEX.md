# RUNBOOK_CODEX — operación verificable v1.3.21 slot 14 handoff

El canon vive en `canon/`. Camino A usa Codex como orquestador lógico, GPT como
cerebro y `overnight_master` como motor mecánico. Camino B usa GPT como cerebro
y orquestador; Gateway conserva transporte/estado. Ningún adapter local puede
fabricar evidencia GPT.

## Preflight

```bash
bin/run_tests.sh
python3 scripts/host_runtime.py --json
python3 scripts/drive_locator.py --require-shared --json
python3 scripts/peer_executor.py --probe-only --json
claude auth status
codex login status
python3 scripts/worker_lmstudio.py --list --json
```

Interpretación estricta:

- `auth_missing`, `connection refused`, `peer_unavailable` y credencial Gateway
  ausente son estados reales; no equivalen a disponibilidad.
- Un smoke `sandbox_reference` sólo prueba mecánica.
- `without_claude` sigue usando Codex suscripción como fallback final; si no
  produce revisión limpia, queda listo para revisión humana, no “aprobado”.

## Lanzamiento canónico

```bash
python3 scripts/run_multiaudit_cycle.py \
  --input /ruta/proyecto \
  --runs-dir ./CAMINO_RUNS \
  --canon-profile with_claude \
  --execute-workers \
  --watch-interval-seconds 2 \
  --watch-timeout-minutes 480 \
  --max-iterations 3
```

La corrida registra host, Apple Silicon/Intel, memoria conservadora, endpoint
LM, Drive/peer, canon y plan de 14 slots. En producción el maestro despacha el
slot vigente, valida `slot_id + candidate_sha256`, aplica fallbacks en orden y
no consolida hasta completar el plan. Cada slot respeta su propio campo `loops`;
el flag global `--max-iterations` sólo cubre compatibilidad legacy.

## Candidato mutable, seed inmutable

- `INPUT/target_snapshot` conserva la entrada original.
- `00_CANDIDATE` es el único árbol vigente que consumen los workers.
- Toda corrección debe incluir el árbol completo en `candidate_update.zip` y
  ligarse a run/job/slot/worker/SHA, manifest y `.DONE`.
- La promoción es atómica, conserva historial y reinicia slots 1→14. Una
  corrección inválida o parcial no avanza el slot.
- El cierre vuelve a hashear árbol, manifest y ZIP; un candidato vacío inesperado
  o distinto del vigente impide `closed`.

## RAM y paralelismo

- Reserva atómica SQLite local al host LM.
- Piso: máximo entre 8 GiB y 15% de RAM total.
- Presión crítica: denegar cargas.
- Medianos: máximo 2 simultáneos.
- Pesado/`heavy_exclusive`: uno y sin otros modelos.
- Lease con heartbeat y TTL para recuperar procesos caídos.
- Endpoint bridge: ejecutar el guard/worker por SSH en el host LM; nunca medir
  la RAM del equipo equivocado.

## GPT cerebro y reanudación

Los slots GPT producen `BRAIN_TASK_REQUEST.json`. Sólo una respuesta externa
`camino_gpt_brain_result.v1`, con `synthetic=false`, evidencia no vacía y
coincidencia exacta de run/stage/slot/candidate puede materializar `.DONE`.

Una corrida detenida en `waiting_external_gpt_brain_slot_N` se reanuda al volver
a ejecutar el maestro después de recibir esa evidencia. Una respuesta vieja o
de otro slot se rechaza.

## Slot 14

Claude Code es primario. El fallback Codex se arma únicamente después de
`auth_missing`, CLI ausente, timeout o fallo de transporte de Claude. Usa:

- ruta `codex_gpt_5_6_sol_ultra_subscription_cli`;
- modelo `gpt-5.6-sol`;
- `model_reasoning_effort=ultra`;
- `codex login status` = ChatGPT;
- preflight local `codex debug models --bundled` confirma modelo y esfuerzo;
- ejecución efímera, sandbox `workspace-write`, sin OpenAI API.

Si cualquiera corrige archivos, no aprueba y el flujo debe reiniciarse según el
canon. Sólo una revisión limpia del slot 14 puede cerrar.

## Drive/Gateway/Actions

- Actions es control/context plane del GPT Cerebro.
- Drive está detrás del Gateway; no se combina como App del mismo GPT.
- Estado mutable siempre local; Drive sólo bundles cerrados.
- La spec vigente es `actions/CAMINO_A_CEREBRO_ACTIONS.v1.yaml`.
- Outputs GPT grandes usan start/chunks/status/finalize.
- Inputs de datos grandes usan manifest-first y `chunked_input_v1` si el Gateway
  lo anuncia. Sin soporte, fallan como evidencia insuficiente.
- La spec actual no tiene un handler `openaiFileIdRefs`; adjuntos directos de la
  conversación no están verificados y usan ingesta manual/data plane.
- El locator macOS busca `CAMINO_A_SHARED/AUDIT_BUS` bajo `My Drive` y
  `Mi unidad`; sólo crea con una raíz inequívoca. Con varias cuentas se debe fijar
  `CAMINO_SHARED_ROOT` o `CAMINO_DRIVE_BUS_ROOT`.

Primera inicialización:

```bash
python3 scripts/drive_locator.py --create --require-shared --json
```

El conector Drive y un montaje local no sustituyen el roundtrip del Gateway: para
declararlo operativo hay que escribir, leer y validar un bundle desde ambos Macs.

## Activación Sol en Camino A/B

La ruta `chatgpt_gpt_5_6_sol_actions_plan` es preferida pero permanece
`disabled_pending_builder_verification`. Activarla exige verificar Sol no-Pro
con Actions en ambos GPT Builder y guardar evidencia de un smoke Action real,
según `actions/SOL56_ACTIONS_EVAL_PROTOCOL.md`. Hasta entonces el plan filtra Sol
y conserva `chatgpt_gpt_5_5_plan`; una respuesta textual no prueba el modelo.

## Evidencia manual multiformato

`manual_submit.py` acepta múltiples textos/archivos en una sola submission,
valida extensión/magic/MIME/SHA, secretos, symlinks, ZIP traversal/bombas y
publica atómicamente. El límite por artefacto es 64 MiB; para más tamaño se usa
el Gateway fragmentado.

## Cierre y auditoría

Antes de cerrar se exige: cero jobs pendientes, cero bundles incompletos,
evidencia aceptada, evidencia GPT externa en perfiles productivos, aprobación
limpia de slot 14 si corresponde y coherencia SHA del ZIP final. Toda excepción
de finalización deja `blocked`, nunca un estado zombie o éxito sintético.

## Empaquetado

```bash
python3 scripts/render_contracts.py --root .
python3 scripts/build_gpt_knowledge_bundle.py
python3 scripts/package_release.py --root . --out ./dist
```

Conservar el SHA-256 impreso y `VALIDATION_RESULTS.json` como evidencia de la
release.
