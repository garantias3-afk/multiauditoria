# Estado recuperado

## Estado cerrado actual

- Runtime recuperado en `camino-a/runtime/` con 124 archivos de release.
- Contratos, scripts, schemas, Actions GPT, prompts generados, tests y evidencia seleccionada estan versionados en el repo.
- Blueprint tecnico para fork arquitectonico agregado en `docs/TDD_SYSTEM_BLUEPRINT.md`.
- El worker de fallback usa `stdin=subprocess.DEVNULL` y Codex por suscripcion.
- El handoff conserva `candidate_sha256` en la evidencia compacta de slots previos.
- El flujo canonico promueve bundles validados a `ACCEPTED/` antes de consultar la autoridad terminal.
- Suite autoritativa: `110 passed` y `RUN_TESTS_OK`.
- Release verificable regenerada con 132 archivos y los entrypoints de Camino B.
- Smoke real final: `terminal_clean_codex_fallback=true`.
- Camino B: bridge, actions, schema y pruebas incluidos en el runtime recuperado.
- Camino B local terminado: Gateway HTTP, agente saliente, cola, fallback secuencial y smoke operativo incluidos.

## Estado de preparacion para ejecucion

- repo local: `/Users/mariano/Documents/multiauditoria`
- repo GitHub: `garantias3-afk/multiauditoria`
- rama actual: `main`
- commit de evidencia publicado: `0f0d65d`
- estado remoto: publicado en `origin/main`
- archivo de referencia para correr la siguiente sesion: `shared/RUNBOOK.md`

## Secuencia recomendada para trabajos pendientes

1. Arrancar por la pendiente que ya tenga mayor evidencia previa.
2. Cerrar cada cambio o corrida con una nota en este archivo.
3. Si el cambio afecta Camino A, anotar el motivo antes de tocar Camino B.
4. Si el cambio afecta Camino B, registrar evidencia operativa y resultado.
5. Si una corrida queda abierta, dejar el ultimo comando exacto y el motivo.

## Pendientes inmediatos

- mantener commits pequenos por cambio importante
- no queda codigo funcional pendiente para el backend local de Camino B
- GPT Builder fue actualizado en Chrome y devolvio `GPT actualizado` para `auditor externo`
- el host configurado `https://camino-b-ultimo.marianogrammatico.com.ar` respondio en el smoke del Builder con `getGatewayHealth` y `status: ok`
- el smoke del Builder reporto `gateway_version: 1.2.20`, `context packs: supported`, `file search: supported` y `file manifests: supported`
- la publicacion HTTPS y la Action del Builder quedaron verificadas con smoke real desde Chrome

## Evidencia operativa del cierre

- comando: `python3 scripts/run_slot14_subscription_smoke.py --max-attempts 1`
- run: `RUN_20260713_022749_eb68e_slot14_subscription_smoke`
- ruta: `camino-a/runtime/outputs/operational_runs/RUN_20260713_022749_eb68e_slot14_subscription_smoke`
- resultado: bundle aceptado, cero rechazados, cero findings
- autoridad terminal: `terminal_clean_codex_fallback=true`
- accion de operador: `false`
- evidencia versionada: `shared/evidence/2026-07-12-slot14-subscription-smoke.json`

## Evidencia operativa Camino B

- comando: `python3 scripts/run_camino_b_bridge_smoke.py --run ... --codex-bundle ...`
- handoff: `B14_c60ef8dfc78daff75f929da2b48f4c2d`
- HTTP: request `202`, status `200`, result `200`
- resultado: fallback armado, transporte completado, recibo Sol/Ultra por suscripcion validado
- autoridad: `terminal_approval=false` y `requires_terminal_gate_validation=true`
- evidencia versionada: `shared/evidence/2026-07-12-camino-b-bridge-smoke.json`

## Prueba real automatizada 2026-07-13

- se saltearon los pasos manuales y se ejecutó `./bin/run_tests.sh` fuera del
  sandbox: `110 passed`, `RUN_TESTS_OK`
- Camino A probó `22` rutas pendientes: `9` respondieron con generación real en
  LM Studio, `5` quedaron listadas en OpenRouter sin credencial para generar,
  `7` quedaron sin credenciales/configuración y `1` no apareció en el listado;
  no hubo errores de red ni rutas prohibidas ejecutadas
- transporte de archivos por HTTP local real: lote chico multiformato (`md`,
  `json`, `yaml`, `csv`, `png`, `pdf`, `zip`) aprobado por uploads individuales;
  lote grande de `11534346` bytes aprobado por `chunked_input_v1` en `4` chunks
- Camino B local probó POST `202`, status `200`, result `200`, fallback
  Claude→Codex, `gpt-5.6-sol/ultra` por suscripción y recibo validado; quedó
  correctamente `terminal_approval=false`
- HTTPS público responde por `/health` con Gateway `1.2.20`, context packs,
  file search y file manifests soportados
- pendiente externo confirmado: el host público devuelve `404` para
  `/v1/camino-b/slot14/reviews`; los handlers slot 14 sólo están verificados en
  el Gateway local y aún deben publicarse en el reverse proxy y en la spec
  completa de Actions
- evidencia: `shared/evidence/2026-07-13-camino-a-b-real-test.json`

## Ultimos 5 pedidos del usuario

1. Recuperar los cambios y archivos modificados hoy en MacBook e iMac.
2. Reconstituir el ultimo estado posible, dejando de lado lo antiguo.
3. Terminar lo inconcluso y decir que es.
4. Crear y subir `multiauditoria` en GitHub con la estructura Camino A, Camino B y shared.
5. Dar hilos para otras IA y commitear cada cambio importante.

## Notas para la siguiente sesion

- antes de cambiar el modelo, leer `shared/RUNBOOK.md`
- al retomar Camino A o Camino B, empezar por el estado mas reciente, no por el historico completo
- cada IA debe volver a este archivo despues de cualquier cambio importante
