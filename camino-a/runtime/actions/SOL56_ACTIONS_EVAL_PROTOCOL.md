# Protocolo de activación y evaluación — GPT-5.6 Sol con Actions

## Alcance

Este protocolo se aplica a Camino A Cerebro y Camino B Auditor Externo. Cambiar
el modelo mejora potencialmente razonamiento, selección de herramientas y
seguimiento de estado; no modifica límites, timeouts ni transporte del Gateway.

La ruta canónica `chatgpt_gpt_5_6_sol_actions_plan` permanece
`disabled_pending_builder_verification` hasta que se cumplan ambos gates:

1. GPT Builder ofrece `GPT-5.6 Sol` en modo no-Pro con Actions activas. El
   operador confirmó el 2026-07-11 que Sol aparece con razonamiento High.
2. El GPT ejecuta un smoke Action real y conserva evidencia identificable.

GPT-5.5 permanece como fallback de despliegue mientras cualquiera de esos gates
no conste. Esta política no usa OpenAI API.

## Configuración objetivo

- Modelo: `GPT-5.6 Sol`.
- Superficie: GPT personalizado con Actions, no Apps.
- Modo Pro: prohibido mientras el GPT dependa de Actions.
- Razonamiento: High, si el selector de la superficie lo permite.
- Gateway: fail-closed; ningún cambio de modelo relaja hashes, manifests, `.DONE`
  o autoridad de slots.
- Slot 14: es una ruta distinta. Claude CLI continúa primario y Codex CLI
  `gpt-5.6-sol`/`ultra` por suscripción ChatGPT continúa como fallback.

## Gates de activación

Registrar como mínimo: nombre/ID del GPT, fecha UTC, modelo visible, modo no-Pro,
Action seleccionada, operación invocada, estado HTTP, `run_id` cuando aplique y
respuesta validada. Sólo entonces se cambia `builder_verification.status` a
`verified`, se completan `verified_at_utc` y `action_smoke_evidence`, y la ruta
puede pasar a `manual_or_action`.

Un chat que sólo responde texto, una captura sin resultado Action o un health sin
identidad/versiones no habilitan la ruta.

## Matriz mínima A/B

1. Health + Knowledge: `getGatewayHealth` y `getCurrentCaminoAKnowledge`.
2. Estado: consultar una corrida real y conservar `run_id`, fase y slot.
3. Tarea: obtener tarea y context pack; validar SHA e inventario.
4. Lectura: buscar un símbolo y leer al menos dos chunks con offsets contiguos.
5. Recuperación: repetir una lectura idempotente y continuar sin duplicar estado.
6. Evidencia insuficiente: provocar una referencia inválida y exigir fallo
   cerrado, sin aprobación.
7. Output grande: start/chunks/status/finalize y resultado ligado al upload.
8. Autoridad: intentar una operación fuera del slot/alcance y comprobar rechazo.
9. Bucles internos: verificar que Camino A Cerebro y Camino B Auditor Externo
   aplican `.001`–`.006` en slots 1/4 y `.001`–`.010` en slots 7/8, rechazando
   cualquier iteración que exceda el límite canónico del slot.

La activación exige que los casos aplicables pasen en Camino A y Camino B. Una
mejora subjetiva de redacción no sustituye esta matriz.

## Archivos adjuntos de la conversación

La spec vigente no expone un endpoint que reciba `openaiFileIdRefs`; por eso no
se declara operativa la subida directa de adjuntos del chat. Cuando exista el
handler server-side, debe descargar inmediatamente enlaces temporales, limitar
bytes, validar MIME/magic, sanear nombres, calcular SHA-256 sobre bytes, guardar
atómicamente y devolver manifest. Recién entonces se añade el parámetro exacto a
la spec y a esta matriz.

Mientras tanto, la ingesta multiformato verificada es `manual_submit.py` o el
data plane externo del Gateway. No se transportan ZIP grandes como Base64 inline.

Referencia oficial de archivos en GPT Actions:
https://developers.openai.com/api/docs/actions/sending-files

## Capacidades fuera de alcance

Programmatic Tool Calling, reasoning persistido, file inputs de Responses API y
multi-agent de API no se activan por seleccionar Sol en un GPT con Actions. No
forman parte de esta release y no autorizan uso de OpenAI API.
