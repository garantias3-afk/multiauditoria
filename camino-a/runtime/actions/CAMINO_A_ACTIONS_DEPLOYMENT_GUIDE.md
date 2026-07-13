# CAMINO_A_ACTIONS_DEPLOYMENT_GUIDE v1.3.21 Slot 14 Handoff

## Estado

Esta guía acompaña `CAMINO_A_CEREBRO_ACTIONS.v1.yaml`. La spec es mínima para
GPT Builder y no reemplaza el Gateway server real. La ruta Sol queda deshabilitada
en canon hasta completar el gate de Builder y el smoke Action.

## Pasos Builder — Camino A y Camino B

1. Abrir el GPT Builder de Camino A Cerebro y luego el de Camino B Auditor
   Externo.
2. Mantener Actions; no activar Apps ni modo Pro.
3. Si el selector ofrece GPT-5.6 Sol compatible con Actions, elegir Sol no-Pro y
   razonamiento High cuando la superficie lo permita. Si no aparece, conservar
   el modelo vigente y dejar el gate Sol pendiente.
4. Borrar la Action dummy `postman-echo.com` si existe.
5. Crear/editar Action y pegar `actions/CAMINO_A_CEREBRO_ACTIONS.v1.yaml` en el
   GPT correspondiente. No inventar una spec Camino B si su Gateway usa otra.
6. Configurar autenticación `X-API-Key`.
7. No pegar endpoints admin/provider en los GPT.
8. Actualizar Knowledge o asegurar que Gateway sirva:
   - `CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.md`
   - Versión: `v1.3.21-slot14-handoff`
   - SHA-256: `d9cba15bfc6bbe5d44ac974db9e774871b3050063e187ed078db593a4a8623ca`

## Smoke obligatorio antes de activar Sol

En Preview, ejecutar:

```text
Prueba operativa sin auditorías: llama getGatewayHealth y getCurrentCaminoAKnowledge. Responde únicamente status, gateway_version, bundle_version, sha256, size_bytes y source_count.
```

Si existe una corrida activa:

```text
Llama getCaminoARunStatus, getNextCaminoABrainTask y getCaminoABrainContextPack. Devuelve run_id, current_phase, task_state, task_id, input_sha256, context_pack_sha256, total_files, critical_files y omitted_files.
```

Guardar nombre/ID del GPT, fecha UTC, modelo visible, operación Action, estado y
respuesta validada. Repetir en Camino A y B. Sólo entonces completar
`builder_verification` en canon y cambiar la ruta Sol a `manual_or_action`.

## Condición de sincronización

No marcar `knowledge_current_matches_gateway=true` hasta que
`getCurrentCaminoAKnowledge.bundle_version` devuelva
`v1.3.21-slot14-handoff` y su `sha256` sea
`d9cba15bfc6bbe5d44ac974db9e774871b3050063e187ed078db593a4a8623ca`.

## Archivos y fallback fail-closed

Si falta `getCaminoABrainContextPack` en el Gateway vivo, el GPT puede operar en
modo legacy sólo para lectura acotada, pero debe reportar
`context_pack_missing` y no declarar auditoría completa sobre paquetes grandes.
Si el Gateway no anuncia `chunked_input_v1`, inputs mayores a 10 MiB fallan como
`insufficient_evidence`; no deben truncarse ni declararse subidos.

La spec actual no acepta adjuntos de conversación mediante `openaiFileIdRefs`.
No declarar esa subida operativa hasta que exista el handler server-side y pase
el protocolo `actions/SOL56_ACTIONS_EVAL_PROTOCOL.md`. Mientras tanto se usa la
ingesta manual/data plane ya validada.
