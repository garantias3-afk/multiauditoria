# CAMINO A OVERNIGHT - KNOWLEDGE BUNDLE UNICO v1.3.21-slot14-handoff

Uso previsto: subir este unico Markdown como Knowledge del GPT Camino A.
Reemplaza bundles anteriores; no se deben conservar simultaneamente versiones
viejas como Knowledge activo.

## Alcance y precedencia

- Camino A es el flujo automatizado local. Camino B no hereda sus watchers.
- `brain_current` verificado al construir: `gpt_manual_or_configured`.
- GPT es el unico cerebro declarado; los providers de ejecucion no cambian esa autoridad.
- Las Instructions del GPT fijan seguridad y autoridad.
- Este bundle fija workflow, providers, fallbacks, tiempos y artefactos.
- Una contradiccion produce `sync_conflict_detected`; no se resuelve por
  conveniencia ni usando documentos legacy.
- Un GPT personalizado solo trabaja durante una conversacion activa. La
  ejecucion nocturna y los watchers pertenecen a infraestructura local.

## Manifest

```json
{
  "bundle_schema": "camino_a_knowledge_bundle.unico.v2",
  "bundle_version": "v1.3.21-slot14-handoff",
  "generated_utc": "2026-07-12T12:53:23.972627+00:00",
  "brain_current": "gpt_manual_or_configured",
  "source_count": 19,
  "source_manifest": [
    {
      "path": "generated/GPT_SHARED_INSTRUCTIONS.md",
      "bytes": 16142,
      "sha256": "a8ed3e5a5c2a8cd9c383b01a45e0f703f49da8f0fe115b8e5a3584ba261d0a0a"
    },
    {
      "path": "contracts/CAMINO_SHARED_CONTRACT.md",
      "bytes": 16049,
      "sha256": "c1341b03f3b1eec2854ad0330b268d0b9176a5992f342e71da91c64b816de5a8"
    },
    {
      "path": "contracts/CANON_ACTION_TRANSFER_POLICY_v1.md",
      "bytes": 4534,
      "sha256": "2622731f174830a393ffa40fa7c607e70bc2b225931db19e77aa5910d5880ca8"
    },
    {
      "path": "actions/CAMINO_A_CEREBRO_ACTIONS.v1.yaml",
      "bytes": 29570,
      "sha256": "8b9b04c39e6f3f2b8d137926c2cfad7ad0ce9763294d0e60d54a9a0ec46ef24b"
    },
    {
      "path": "actions/SOL56_ACTIONS_EVAL_PROTOCOL.md",
      "bytes": 3603,
      "sha256": "578a51a1f43f4e558ddac1ee13ba0dae3248d83a73c192d6a026e6854acb25fd"
    },
    {
      "path": "canon/CANON_SHARED_CONTRACT_v1.md",
      "bytes": 16049,
      "sha256": "c1341b03f3b1eec2854ad0330b268d0b9176a5992f342e71da91c64b816de5a8"
    },
    {
      "path": "canon/CANON_CHANGE_PROTOCOL_v1.md",
      "bytes": 2693,
      "sha256": "d1455540a67ad548986c98162ae2191860db1b0639f798e3b206ce8aa4774155"
    },
    {
      "path": "canon/CANON_PROVIDER_MODEL_ROUTES.v1.json",
      "bytes": 39729,
      "sha256": "541a10f2facd3be97761fb6028576d6dc22a1814eb6dd98bba74f999e3e6b2f8"
    },
    {
      "path": "canon/CANON_WORKFLOW_SLOTS.v1.json",
      "bytes": 19085,
      "sha256": "3569eb3b0f88a8f271a0e951cc88e6d6b8761d4e2a4a9396b1596cda5326db23"
    },
    {
      "path": "canon/CANON_RUNTIME_POLICY.v1.json",
      "bytes": 5258,
      "sha256": "7ee7020d085d1b6d44118c613c59e24a804add8d7813c59e6f439b4d34e92bd4"
    },
    {
      "path": "canon/CANON_PREAUDIT_DELIVERY.v1.json",
      "bytes": 4788,
      "sha256": "f00aa2fa6667805b74c1386a01723463bc26066b9a01982c5271c9df003a1aea"
    },
    {
      "path": "config/roles.json",
      "bytes": 3202,
      "sha256": "13495cddb5af3557ae7a93321350b3934ae3d599d640b7621f18cd6c6bb4375c"
    },
    {
      "path": "config/path_roles.json",
      "bytes": 1819,
      "sha256": "a74deb00de28da41a6d833f461a4df593a30b9fa981292c1e27c56eef9ac4f6a"
    },
    {
      "path": "config/host_runtime.policy.json",
      "bytes": 2801,
      "sha256": "4bafa419ea77c975028fed02c0dc4317af16a9bfc569a2b0994fa9859eb5a110"
    },
    {
      "path": "config/drive.policy.json",
      "bytes": 798,
      "sha256": "c9db6d49fcdc22e890be2c2ff0479d030941464b34ce4bc0ec71b965b824021e"
    },
    {
      "path": "config/primary_brain_policy.json",
      "bytes": 1859,
      "sha256": "8eabc628ede359ef4c432779d656786d75762c08e2b0129e887f94ec55b9ef5c"
    },
    {
      "path": "config/provider.policy.json",
      "bytes": 2546,
      "sha256": "bf70b9b0e572cae8565c9fdd79ca84963b58111e4780e086ec6571568d9d1eb8"
    },
    {
      "path": "QUICKSTART.md",
      "bytes": 5434,
      "sha256": "bdc7e5a2f15686fec3996727c3381956cf8072c80dc53acc038b4f73d2ac0cd9"
    },
    {
      "path": "RUNBOOK_CODEX.md",
      "bytes": 6101,
      "sha256": "cc206c5e8f4e0c1e00e9b5da045cb8c117e940105e335e099d20531fbea5e3b2"
    }
  ]
}
```

## SOURCE: generated/GPT_SHARED_INSTRUCTIONS.md

```markdown
# GPT Shared Instructions

> Auto-generated. Do not edit.

Brain: gpt_manual_or_configured

# Contrato compartido Camino A / Camino B v1

## Fuente de verdad

Los tres actores (GPT, Claude y Codex) deben leer el mismo canon:

- `CANON_PROVIDER_MODEL_ROUTES.v1.json`: identidad exacta de cada ruta.
- `CANON_WORKFLOW_SLOTS.v1.json`: orden, rol, ciclos y bucles.
- `CANON_CHANGE_PROTOCOL_v1.md`: procedimiento obligatorio de cambio.

Los contratos de Camino A y Camino B no pueden redefinir libremente modelos,
providers ni orden. Solo pueden referenciar `route_id` y `slot_id` canónicos.
Los roles por camino viven en `config/path_roles.json`; el motor mecánico de
estado no se confunde con el orquestador lógico ni con el cerebro.

## Autoridad por camino

- El único cerebro es GPT (`gpt_manual_or_configured`) en ambos caminos. Una
  salida sólo cuenta como decisión de GPT si existe evidencia recibida por el
  Gateway/Drive bus y validada por hash; ningún adapter local puede simularla.
- Camino A: Codex es el orquestador lógico; `overnight_master` es únicamente el
  motor mecánico de estado, leases, validación y empaquetado.
- Camino B: GPT es cerebro y orquestador lógico; el Gateway es transporte y
  autoridad mecánica del estado remoto, nunca un cerebro sustituto.
- Los providers, LM Studio, Claude y los workers aportan ejecución o evidencia.
  No alteran por sí solos el orden de slots ni sustituyen a GPT.

## Política de modelo GPT Cerebro

- La ruta preferida para Camino A Cerebro y Camino B Auditor Externo es
  `chatgpt_gpt_5_6_sol_actions_plan`: GPT-5.6 Sol, GPT personalizado con Actions,
  modo no-Pro y razonamiento High cuando esa superficie lo permita.
- La ruta permanece deshabilitada hasta verificar en cada GPT Builder que el
  modelo está disponible con Actions y completar un smoke Action real. Mientras
  el gate esté pendiente, `chatgpt_gpt_5_5_plan` continúa como fallback activo.
- La identidad del modelo no puede inferirse de una buena respuesta. Debe constar
  en la configuración/evidencia de Builder y en el gate canónico.
- Sol puede mejorar razonamiento y orquestación, pero no amplía límites de
  archivos, URLs temporales, timeouts ni disponibilidad del Gateway.
- Responses API, Programmatic Tool Calling y multi-agent de API no están activos
  en esta release. OpenAI API continúa prohibida.
- Esta política del GPT Cerebro es independiente del slot 14: allí Claude CLI es
  primario y Codex `gpt-5.6-sol`/`ultra` por suscripción ChatGPT es fallback.
- En Camino A, el Codex orquestador puede permanecer en un modelo económico y
  con razonamiento bajo. El fallback abre otro `codex exec` efímero, ignora la
  configuración del orquestador y fija explícitamente `gpt-5.6-sol`/`ultra`.
  No existe ni se necesita un autocambio del modelo de la tarea orquestadora.
- En Camino B, GPT Desktop conserva razonamiento High como cerebro y
  orquestador. Tampoco sustituye al revisor Codex CLI Ultra: debe solicitarlo a
  un worker local separado mediante un puente verificable del Gateway.

## Identidad obligatoria

Cada ejecución y log debe contener:

`slot_id + route_id + model_id + provider_id + provider_name + route + interface + cost_class + role`

Modelo y provider son identidades distintas. Un mismo modelo por otro provider
requiere otro `route_id`.

## Flujo

- Bucle grande: slots 1 a 14.
- Ciclo A: slots 1 a 3.
- Ciclo B: slots 4 a 6.
- Ciclo C: slots 7 a 10.
- Cierre final: slots 11 a 14.

Si un slot termina sin correcciones, avanza al siguiente. Si hay correcciones,
aplica `correction_policy`. Alcanzado el máximo de bucles, avanza aunque haya
habido correcciones, dejando deuda explícita y evidencia en el log. Solo el slot
14 puede terminar el proceso como aprobado. Claude Code por suscripción es la
ruta primaria; únicamente si queda registrada su indisponibilidad de auth/CLI/
transporte puede entrar Codex `gpt-5.6-sol` con razonamiento `ultra`, autenticado
por la suscripción ChatGPT. Ninguna de las dos rutas usa API keys. La aprobación
exige cero cambios, cero findings, SHA vigente y slots 1–13 completos.

## Transferencia adversarial de slot 13 a slot 14

- Cada candidato que alcance el slot 14 genera un pedido de auditoría nuevo,
  ligado por SHA-256 a `run_id`, al árbol candidato vigente y a un diff acotado
  contra `INPUT/target_snapshot`. No se reutiliza un pedido de otro candidato.
- El pedido resume evidencia de slots 1–13, pruebas ya ejecutadas, correcciones
  alegadas, deuda residual, archivos agregados/modificados/eliminados y
  dependencias de riesgo. Evita reenviar historiales completos para no quemar
  tokens, pero nunca omite deuda ni límites de evidencia.
- Las conclusiones previas se tratan como hipótesis no confiables. El revisor
  debe buscar evidencia que las contradiga, intentar refutar cada corrección,
  construir contraejemplos o pruebas negativas y comprobar al menos una
  invariante crítica de forma independiente. Un pass previo no prueba el cierre.
- Claude y el fallback Codex reciben exactamente el mismo pedido y diff. Deben
  reconocer su SHA en la salida; un pedido ausente, alterado, obsoleto o de otro
  candidato se rechaza antes de abrir el CLI y jamás puede aprobar.
- Si Claude no está disponible y tampoco puede iniciarse el `codex exec`
  separado por login, capacidad, cuota o transporte, el estado es
  `SLOT14_OPERATOR_ACTION_REQUIRED`. Cambiar el modelo del orquestador o del GPT
  Desktop no satisface este contrato y ningún resultado manual puede aprobar.

## Ciclo del candidato y promoción de correcciones

- `INPUT/target_snapshot` es el seed inmutable y `00_CANDIDATE` es el árbol
  vigente que todos los workers deben consumir. Antes de despachar se recalcula
  su SHA-256 de árbol; una discrepancia, symlink, secreto u omisión en un snapshot
  remoto detiene el worker y no genera evidencia aceptable.
- Una corrección sólo puede volver como árbol completo `candidate_update.zip`,
  nunca como overlay parcial. Resultado, manifest y `.DONE` deben quedar ligados
  exactamente a `run_id + job_id + slot_id + worker_id + source_candidate_sha256`
  y declarar el SHA-256 del árbol resultante y del ZIP.
- El motor valida rutas, duplicados, mayúsculas equivalentes, symlinks, cantidad,
  tamaños, hashes, secretos y cambio real antes de extraer. Un claim de corrección
  sin bundle válido no completa el slot.
- Por ronda se promueve como máximo una corrección válida. La promoción reemplaza
  `00_CANDIDATE` atómicamente, conserva historial, incrementa versión/iteración y
  reinicia el bucle grande en slot 1; los resultados restantes quedan ligados al
  SHA anterior y no pueden contaminar la nueva ronda.
- El paquete final contiene recursivamente el `00_CANDIDATE` vigente, nunca un
  árbol vacío inesperado. El gate terminal compara árbol actual, manifest,
  contenido del ZIP y hashes antes de permitir `closed`.
- La evidencia del GPT Cerebro debe referenciar fuentes reales del catálogo con
  SHA exacto y `synthetic=false`. JSON sin request, validación del adapter,
  manifest y `.DONE` no cuenta como decisión externa.

## Bucle interno agentic

Todo actor agentic de GPT, Codex o Claude ejecuta el bucle interno de 1 a 10
iteraciones únicamente cuando el slot declara `internal_loop.required=true`.
Los slots con `loop_type=external_slot_loop`, incluido el 14, usan sólo el límite
externo del slot y no crean versiones `.001`–`.010`. Cuando corresponde, cada
iteración interna contiene:
auditar, reparar o reescribir, testear, reauditar y decidir. Cada corrección usa
tercer numeral `.001` a `.010`. La salida contiene sólo la última versión, diff
acumulado desde el seed, historial de iteraciones, tests y reauditoría final.
Un estado limpio exige cero bugs y cero mejoras técnicas pendientes. Al agotar
10 iteraciones se entrega la última versión con deuda residual explícita, nunca
un cierre limpio. “Confirmado” o “detectado” no reemplaza “reparado” o
“reescrito”. El actor puede declarar que su ronda quedó sin nuevos hallazgos,
pero no alterar el flujo ni aprobar el proceso, salvo la autoridad de slot 14:
Claude primario o Codex por suscripción como fallback comprobado.

## Reglas especiales

- OpenRouter free ejecuta todas las rutas allowlistadas con sufijo `:free`; no hay
  fallback pago.
- Carrera Nemotron: NVIDIA directo y OpenRouter free arrancan en slot 1. Primer
  resultado válido gana; el otro se cancela o ignora. Blackbox pago entra en slot
  4 solo si no hubo ganador free.
- `blackbox_nemotron_ultra_paid` está configurado y conserva como evidencia el
  último probe registrado en el canon. Esto no garantiza disponibilidad actual.
  Usa exclusivamente
  `BLACKBOX_API_KEY`, `https://api.blackbox.ai/v1`, `/chat/completions` y
  `blackboxai/nvidia/nemotron-3-ultra`. GPT, Claude y Codex deben incluirlo en
  las llamadas del slot 4 cuando no exista ganador válido de las dos rutas
  Nemotron gratuitas; antes del gate deben respetar la política de disponibilidad
  vigente y nunca ejecutarlo en slot 1.
- MiMo: Token Plan primero, Xiaomi PAYG segundo, DeepInfra tercero y reservado.
  OpenRouter está prohibido para MiMo.
- Una cuota/suscripción agotada abre el circuit breaker para todo el provider
  durante la corrida. GLM no repite rutas del mismo provider como si fueran
  fallbacks independientes; usa el fallback gratuito/de plan definido en canon.
- El fallback del slot 14 es secuencial, no paralelo: primero
  `claude_code_subscription_cli`; sólo ante un fallo de disponibilidad registrado
  entra `codex_gpt_5_6_sol_ultra_subscription_cli`. Este último exige
  `codex login status` autenticado con ChatGPT, modelo `gpt-5.6-sol`, esfuerzo
  `ultra`, ejecución efímera y ausencia de `OPENAI_API_KEY`.
- GPT (`gpt_manual_or_configured`) es el unico cerebro del flujo. En los slots
  GPT actua como consolidador, escritor o reauditor segun el rol canonico.
  Codex y los providers API son infraestructura o workers de evidencia: nunca
  cerebros alternativos ni decisores por sustitucion automatica.
- Ningún actor edita el log append-only ni sus anchors a mano.

## Contrato de proveedores de Camino A

Camino A usa este canon de proveedores como fuente de verdad operativa. Cada
slot debe referenciar `provider_id` y `route_id` exactos. Si un mismo modelo
cambia de provider, se trata como otra ruta distinta y requiere otro
`route_id`.

### Grupos canónicos de Camino A

- `gemini_aistudio_free`
- `vertex_gemini_2_5_pro`
- `deepseek`
- `blackbox_free`
- `openrouter_free`
- `nvidia_nemotron_direct`
- `groq_gpt_oss_120b`
- `groq_llama_33_70b`
- `groq_qwen3_32b`
- `blackbox_intermediate`
- `deepinfra_qwen`
- `deepinfra_minimax`
- `deepinfra_kimi`
- `deepinfra_glm`
- `zai_glm`
- `moonshot_kimi`
- `chatgpt_plan`
- `claude_plan_manual`
- `lmstudio_macbook_bridge`

### Reglas de operación de proveedores

- `openrouter_free` ejecuta todos los modelos `:free` allowlistados y no puede
  caer en fallback pago.
- `nvidia_nemotron_direct` y `openrouter_free` pueden correr en carrera; el
  primer resultado válido gana.
- `blackbox_free` y `blackbox_intermediate` no comparten modelo como si fueran
  la misma ruta.
- `deepinfra_kimi`, `deepinfra_glm` y `zai_glm` se gobiernan por sus slots,
  presupuestos y fallbacks internos; la lentitud por sí sola no invalida una
  ronda si sigue habiendo heartbeat.
- `chatgpt_plan` escribe cuando el slot lo pide.
- `claude_plan_manual` es el revisor/cierre final sólo cuando el contrato lo
  permite.
- `lmstudio_macbook_bridge` usa LM Studio en la MacBook, local por loopback si
  el proceso se lanza allí o por bridge si se lanza desde la iMac. El endpoint
  se descubre/overridea mediante la política de host; no se fija una IP única
  dentro del canon. Su interfaz es OpenAI-compatible y su costo `local_free`.
- Los route_id LM Studio de tier 1 entran en slot 1 como auditores gratuitos
  locales. Los route_id tier 2 entran en slot 4 como apoyo intermedio local.
- Antes de llamar LM Studio se debe verificar `/v1/models`; si el endpoint no
  responde se registra `NO_CONSTA` o `lmstudio_unavailable_connection_refused`.
- Los modelos medianos LM Studio corren con máximo 2 concurrentes y sólo si el
  guard de RAM conserva el piso de seguridad configurado. La reserva se toma en
  el host que posee la RAM antes de cargar/generar y se mantiene con heartbeat.
  El Nemotron local de 70B es exclusivo de alta criticidad y no entra en slots
  generales.
- Deduplicación local/pago: una ruta LM Studio local gratuita sólo excluye una
  ruta paga si hay equivalencia exacta o sustancial de modelo, capacidad y rol.
  Misma familia no alcanza. `deepinfra_qwen3_coder_480b` no es duplicado de los
  Qwen locales 30B/32B y permanece activo en etapas distintas. Desde v1.3.18 sólo
  queda excluida de slots automáticos `blackbox_devstral_2`, reemplazada por
  `lmstudio_devstral_small_2507`.

### Regla de tiempo y heartbeat

- Una ronda puede durar horas si mantiene heartbeat y progreso.
- Timeout duro no debe matar un proceso vivo que aún está dentro de su
  presupuesto de slot.
- El criterio principal de vida es `heartbeat`, no sólo el reloj.
- Si no hay heartbeat ni progreso dentro del presupuesto, se falla cerrado.
- Los watchers pertenecen a Camino A y controlan la ida y vuelta de `.DONE`.

## Portabilidad iMac / MacBook y Drive

- El mismo entrypoint puede lanzarse desde cualquiera de los dos equipos. Cada
  corrida registra `node_id`, arquitectura, memoria, endpoint LM seleccionado y
  peer disponible en `RUN_CONFIG.json`.
- SQLite/WAL y locks permanecen locales al coordinador. Google Drive transporta
  exclusivamente bundles inmutables terminados con manifest y `.DONE`; no se
  usa como base de datos activa ni como lock distribuido.
- En macOS el locator busca de forma acotada `CAMINO_A_SHARED/AUDIT_BUS` bajo
  `My Drive` o `Mi unidad` de cada provider Google Drive. Sólo crea la carpeta
  cuando existe exactamente una raíz reconocida; ante cuentas múltiples exige
  `CAMINO_SHARED_ROOT` o `CAMINO_DRIVE_BUS_ROOT` y falla cerrado.
- Si ambos equipos intentan coordinar la misma corrida, un lease remoto/atómico
  decide un único dueño. Sin lease fiable se falla cerrado y se pide elegir el
  host, en vez de permitir dos maestros.
- Bajo presión de RAM en la MacBook no se admiten nuevas cargas LM. Los trabajos
  no-LM pueden derivarse al iMac sólo si el peer autenticado responde; si no,
  quedan en cola o se ejecutan localmente dentro del límite explícito.
- La ejecución remota usa SSH por clave, `BatchMode` y host key estricta. Cada
  dirección necesita Remote Login activo y su clave dedicada; si una dirección
  no responde, se registra como peer no disponible y no se simula el offload.
- El GPT Cerebro usa Actions contra el Gateway. Drive queda detrás del Gateway
  como data plane/bus de bundles; no se habilita a la vez como App nativa del GPT,
  porque Apps y Actions son modos mutuamente excluyentes en el editor actual.
  Así la ubicación física iMac/MacBook es transparente para GPT.
- El Gateway de datos acepta inputs grandes sólo cuando negocia
  `chunked_input_v1`; el cliente transmite chunks acotados, verifica SHA por
  chunk y SHA/tamaño final. Sin esa capacidad declara evidencia insuficiente.

## Quality log obligatorio por auditoría

Cada evento material de auditoría debe registrar una entrada
`ai_quality_log_entry.v1` en:

- `90_QUALITY_LOG_DELTA/*.entry.json` dentro del run.
- tabla SQLite `quality_log` dentro de `STATE/state.sqlite`.

Eventos mínimos obligatorios:

- ejecución o skip de worker (`worker_execution_status`);
- bundle válido o inválido (`worker_bundle_validated` / `worker_bundle_rejected`);
- iteración de bucle interno agentic (`internal_loop_*`);
- auditoría manual ingresada (`manual_audit_ingested`).

Cada entrada debe contener identidad completa:

`slot_id + route_id + model_id + provider_id + provider_name + route + interface + cost_class + role + worker_id`.

Si un dato no consta, debe escribirse `NO_CONSTA`; no se deben inferir modelos o
providers inventados.
```

## SOURCE: contracts/CAMINO_SHARED_CONTRACT.md

```markdown
# Contrato compartido Camino A / Camino B v1

## Fuente de verdad

Los tres actores (GPT, Claude y Codex) deben leer el mismo canon:

- `CANON_PROVIDER_MODEL_ROUTES.v1.json`: identidad exacta de cada ruta.
- `CANON_WORKFLOW_SLOTS.v1.json`: orden, rol, ciclos y bucles.
- `CANON_CHANGE_PROTOCOL_v1.md`: procedimiento obligatorio de cambio.

Los contratos de Camino A y Camino B no pueden redefinir libremente modelos,
providers ni orden. Solo pueden referenciar `route_id` y `slot_id` canónicos.
Los roles por camino viven en `config/path_roles.json`; el motor mecánico de
estado no se confunde con el orquestador lógico ni con el cerebro.

## Autoridad por camino

- El único cerebro es GPT (`gpt_manual_or_configured`) en ambos caminos. Una
  salida sólo cuenta como decisión de GPT si existe evidencia recibida por el
  Gateway/Drive bus y validada por hash; ningún adapter local puede simularla.
- Camino A: Codex es el orquestador lógico; `overnight_master` es únicamente el
  motor mecánico de estado, leases, validación y empaquetado.
- Camino B: GPT es cerebro y orquestador lógico; el Gateway es transporte y
  autoridad mecánica del estado remoto, nunca un cerebro sustituto.
- Los providers, LM Studio, Claude y los workers aportan ejecución o evidencia.
  No alteran por sí solos el orden de slots ni sustituyen a GPT.

## Política de modelo GPT Cerebro

- La ruta preferida para Camino A Cerebro y Camino B Auditor Externo es
  `chatgpt_gpt_5_6_sol_actions_plan`: GPT-5.6 Sol, GPT personalizado con Actions,
  modo no-Pro y razonamiento High cuando esa superficie lo permita.
- La ruta permanece deshabilitada hasta verificar en cada GPT Builder que el
  modelo está disponible con Actions y completar un smoke Action real. Mientras
  el gate esté pendiente, `chatgpt_gpt_5_5_plan` continúa como fallback activo.
- La identidad del modelo no puede inferirse de una buena respuesta. Debe constar
  en la configuración/evidencia de Builder y en el gate canónico.
- Sol puede mejorar razonamiento y orquestación, pero no amplía límites de
  archivos, URLs temporales, timeouts ni disponibilidad del Gateway.
- Responses API, Programmatic Tool Calling y multi-agent de API no están activos
  en esta release. OpenAI API continúa prohibida.
- Esta política del GPT Cerebro es independiente del slot 14: allí Claude CLI es
  primario y Codex `gpt-5.6-sol`/`ultra` por suscripción ChatGPT es fallback.
- En Camino A, el Codex orquestador puede permanecer en un modelo económico y
  con razonamiento bajo. El fallback abre otro `codex exec` efímero, ignora la
  configuración del orquestador y fija explícitamente `gpt-5.6-sol`/`ultra`.
  No existe ni se necesita un autocambio del modelo de la tarea orquestadora.
- En Camino B, GPT Desktop conserva razonamiento High como cerebro y
  orquestador. Tampoco sustituye al revisor Codex CLI Ultra: debe solicitarlo a
  un worker local separado mediante un puente verificable del Gateway.

## Identidad obligatoria

Cada ejecución y log debe contener:

`slot_id + route_id + model_id + provider_id + provider_name + route + interface + cost_class + role`

Modelo y provider son identidades distintas. Un mismo modelo por otro provider
requiere otro `route_id`.

## Flujo

- Bucle grande: slots 1 a 14.
- Ciclo A: slots 1 a 3.
- Ciclo B: slots 4 a 6.
- Ciclo C: slots 7 a 10.
- Cierre final: slots 11 a 14.

Si un slot termina sin correcciones, avanza al siguiente. Si hay correcciones,
aplica `correction_policy`. Alcanzado el máximo de bucles, avanza aunque haya
habido correcciones, dejando deuda explícita y evidencia en el log. Solo el slot
14 puede terminar el proceso como aprobado. Claude Code por suscripción es la
ruta primaria; únicamente si queda registrada su indisponibilidad de auth/CLI/
transporte puede entrar Codex `gpt-5.6-sol` con razonamiento `ultra`, autenticado
por la suscripción ChatGPT. Ninguna de las dos rutas usa API keys. La aprobación
exige cero cambios, cero findings, SHA vigente y slots 1–13 completos.

## Transferencia adversarial de slot 13 a slot 14

- Cada candidato que alcance el slot 14 genera un pedido de auditoría nuevo,
  ligado por SHA-256 a `run_id`, al árbol candidato vigente y a un diff acotado
  contra `INPUT/target_snapshot`. No se reutiliza un pedido de otro candidato.
- El pedido resume evidencia de slots 1–13, pruebas ya ejecutadas, correcciones
  alegadas, deuda residual, archivos agregados/modificados/eliminados y
  dependencias de riesgo. Evita reenviar historiales completos para no quemar
  tokens, pero nunca omite deuda ni límites de evidencia.
- Las conclusiones previas se tratan como hipótesis no confiables. El revisor
  debe buscar evidencia que las contradiga, intentar refutar cada corrección,
  construir contraejemplos o pruebas negativas y comprobar al menos una
  invariante crítica de forma independiente. Un pass previo no prueba el cierre.
- Claude y el fallback Codex reciben exactamente el mismo pedido y diff. Deben
  reconocer su SHA en la salida; un pedido ausente, alterado, obsoleto o de otro
  candidato se rechaza antes de abrir el CLI y jamás puede aprobar.
- Si Claude no está disponible y tampoco puede iniciarse el `codex exec`
  separado por login, capacidad, cuota o transporte, el estado es
  `SLOT14_OPERATOR_ACTION_REQUIRED`. Cambiar el modelo del orquestador o del GPT
  Desktop no satisface este contrato y ningún resultado manual puede aprobar.

## Ciclo del candidato y promoción de correcciones

- `INPUT/target_snapshot` es el seed inmutable y `00_CANDIDATE` es el árbol
  vigente que todos los workers deben consumir. Antes de despachar se recalcula
  su SHA-256 de árbol; una discrepancia, symlink, secreto u omisión en un snapshot
  remoto detiene el worker y no genera evidencia aceptable.
- Una corrección sólo puede volver como árbol completo `candidate_update.zip`,
  nunca como overlay parcial. Resultado, manifest y `.DONE` deben quedar ligados
  exactamente a `run_id + job_id + slot_id + worker_id + source_candidate_sha256`
  y declarar el SHA-256 del árbol resultante y del ZIP.
- El motor valida rutas, duplicados, mayúsculas equivalentes, symlinks, cantidad,
  tamaños, hashes, secretos y cambio real antes de extraer. Un claim de corrección
  sin bundle válido no completa el slot.
- Por ronda se promueve como máximo una corrección válida. La promoción reemplaza
  `00_CANDIDATE` atómicamente, conserva historial, incrementa versión/iteración y
  reinicia el bucle grande en slot 1; los resultados restantes quedan ligados al
  SHA anterior y no pueden contaminar la nueva ronda.
- El paquete final contiene recursivamente el `00_CANDIDATE` vigente, nunca un
  árbol vacío inesperado. El gate terminal compara árbol actual, manifest,
  contenido del ZIP y hashes antes de permitir `closed`.
- La evidencia del GPT Cerebro debe referenciar fuentes reales del catálogo con
  SHA exacto y `synthetic=false`. JSON sin request, validación del adapter,
  manifest y `.DONE` no cuenta como decisión externa.

## Bucle interno agentic

Todo actor agentic de GPT, Codex o Claude ejecuta el bucle interno de 1 a 10
iteraciones únicamente cuando el slot declara `internal_loop.required=true`.
Los slots con `loop_type=external_slot_loop`, incluido el 14, usan sólo el límite
externo del slot y no crean versiones `.001`–`.010`. Cuando corresponde, cada
iteración interna contiene:
auditar, reparar o reescribir, testear, reauditar y decidir. Cada corrección usa
tercer numeral `.001` a `.010`. La salida contiene sólo la última versión, diff
acumulado desde el seed, historial de iteraciones, tests y reauditoría final.
Un estado limpio exige cero bugs y cero mejoras técnicas pendientes. Al agotar
10 iteraciones se entrega la última versión con deuda residual explícita, nunca
un cierre limpio. “Confirmado” o “detectado” no reemplaza “reparado” o
“reescrito”. El actor puede declarar que su ronda quedó sin nuevos hallazgos,
pero no alterar el flujo ni aprobar el proceso, salvo la autoridad de slot 14:
Claude primario o Codex por suscripción como fallback comprobado.

## Reglas especiales

- OpenRouter free ejecuta todas las rutas allowlistadas con sufijo `:free`; no hay
  fallback pago.
- Carrera Nemotron: NVIDIA directo y OpenRouter free arrancan en slot 1. Primer
  resultado válido gana; el otro se cancela o ignora. Blackbox pago entra en slot
  4 solo si no hubo ganador free.
- `blackbox_nemotron_ultra_paid` está configurado y conserva como evidencia el
  último probe registrado en el canon. Esto no garantiza disponibilidad actual.
  Usa exclusivamente
  `BLACKBOX_API_KEY`, `https://api.blackbox.ai/v1`, `/chat/completions` y
  `blackboxai/nvidia/nemotron-3-ultra`. GPT, Claude y Codex deben incluirlo en
  las llamadas del slot 4 cuando no exista ganador válido de las dos rutas
  Nemotron gratuitas; antes del gate deben respetar la política de disponibilidad
  vigente y nunca ejecutarlo en slot 1.
- MiMo: Token Plan primero, Xiaomi PAYG segundo, DeepInfra tercero y reservado.
  OpenRouter está prohibido para MiMo.
- Una cuota/suscripción agotada abre el circuit breaker para todo el provider
  durante la corrida. GLM no repite rutas del mismo provider como si fueran
  fallbacks independientes; usa el fallback gratuito/de plan definido en canon.
- El fallback del slot 14 es secuencial, no paralelo: primero
  `claude_code_subscription_cli`; sólo ante un fallo de disponibilidad registrado
  entra `codex_gpt_5_6_sol_ultra_subscription_cli`. Este último exige
  `codex login status` autenticado con ChatGPT, modelo `gpt-5.6-sol`, esfuerzo
  `ultra`, ejecución efímera y ausencia de `OPENAI_API_KEY`.
- GPT (`gpt_manual_or_configured`) es el unico cerebro del flujo. En los slots
  GPT actua como consolidador, escritor o reauditor segun el rol canonico.
  Codex y los providers API son infraestructura o workers de evidencia: nunca
  cerebros alternativos ni decisores por sustitucion automatica.
- Ningún actor edita el log append-only ni sus anchors a mano.

## Contrato de proveedores de Camino A

Camino A usa este canon de proveedores como fuente de verdad operativa. Cada
slot debe referenciar `provider_id` y `route_id` exactos. Si un mismo modelo
cambia de provider, se trata como otra ruta distinta y requiere otro
`route_id`.

### Grupos canónicos de Camino A

- `gemini_aistudio_free`
- `vertex_gemini_2_5_pro`
- `deepseek`
- `blackbox_free`
- `openrouter_free`
- `nvidia_nemotron_direct`
- `groq_gpt_oss_120b`
- `groq_llama_33_70b`
- `groq_qwen3_32b`
- `blackbox_intermediate`
- `deepinfra_qwen`
- `deepinfra_minimax`
- `deepinfra_kimi`
- `deepinfra_glm`
- `zai_glm`
- `moonshot_kimi`
- `chatgpt_plan`
- `claude_plan_manual`
- `lmstudio_macbook_bridge`

### Reglas de operación de proveedores

- `openrouter_free` ejecuta todos los modelos `:free` allowlistados y no puede
  caer en fallback pago.
- `nvidia_nemotron_direct` y `openrouter_free` pueden correr en carrera; el
  primer resultado válido gana.
- `blackbox_free` y `blackbox_intermediate` no comparten modelo como si fueran
  la misma ruta.
- `deepinfra_kimi`, `deepinfra_glm` y `zai_glm` se gobiernan por sus slots,
  presupuestos y fallbacks internos; la lentitud por sí sola no invalida una
  ronda si sigue habiendo heartbeat.
- `chatgpt_plan` escribe cuando el slot lo pide.
- `claude_plan_manual` es el revisor/cierre final sólo cuando el contrato lo
  permite.
- `lmstudio_macbook_bridge` usa LM Studio en la MacBook, local por loopback si
  el proceso se lanza allí o por bridge si se lanza desde la iMac. El endpoint
  se descubre/overridea mediante la política de host; no se fija una IP única
  dentro del canon. Su interfaz es OpenAI-compatible y su costo `local_free`.
- Los route_id LM Studio de tier 1 entran en slot 1 como auditores gratuitos
  locales. Los route_id tier 2 entran en slot 4 como apoyo intermedio local.
- Antes de llamar LM Studio se debe verificar `/v1/models`; si el endpoint no
  responde se registra `NO_CONSTA` o `lmstudio_unavailable_connection_refused`.
- Los modelos medianos LM Studio corren con máximo 2 concurrentes y sólo si el
  guard de RAM conserva el piso de seguridad configurado. La reserva se toma en
  el host que posee la RAM antes de cargar/generar y se mantiene con heartbeat.
  El Nemotron local de 70B es exclusivo de alta criticidad y no entra en slots
  generales.
- Deduplicación local/pago: una ruta LM Studio local gratuita sólo excluye una
  ruta paga si hay equivalencia exacta o sustancial de modelo, capacidad y rol.
  Misma familia no alcanza. `deepinfra_qwen3_coder_480b` no es duplicado de los
  Qwen locales 30B/32B y permanece activo en etapas distintas. Desde v1.3.18 sólo
  queda excluida de slots automáticos `blackbox_devstral_2`, reemplazada por
  `lmstudio_devstral_small_2507`.

### Regla de tiempo y heartbeat

- Una ronda puede durar horas si mantiene heartbeat y progreso.
- Timeout duro no debe matar un proceso vivo que aún está dentro de su
  presupuesto de slot.
- El criterio principal de vida es `heartbeat`, no sólo el reloj.
- Si no hay heartbeat ni progreso dentro del presupuesto, se falla cerrado.
- Los watchers pertenecen a Camino A y controlan la ida y vuelta de `.DONE`.

## Portabilidad iMac / MacBook y Drive

- El mismo entrypoint puede lanzarse desde cualquiera de los dos equipos. Cada
  corrida registra `node_id`, arquitectura, memoria, endpoint LM seleccionado y
  peer disponible en `RUN_CONFIG.json`.
- SQLite/WAL y locks permanecen locales al coordinador. Google Drive transporta
  exclusivamente bundles inmutables terminados con manifest y `.DONE`; no se
  usa como base de datos activa ni como lock distribuido.
- En macOS el locator busca de forma acotada `CAMINO_A_SHARED/AUDIT_BUS` bajo
  `My Drive` o `Mi unidad` de cada provider Google Drive. Sólo crea la carpeta
  cuando existe exactamente una raíz reconocida; ante cuentas múltiples exige
  `CAMINO_SHARED_ROOT` o `CAMINO_DRIVE_BUS_ROOT` y falla cerrado.
- Si ambos equipos intentan coordinar la misma corrida, un lease remoto/atómico
  decide un único dueño. Sin lease fiable se falla cerrado y se pide elegir el
  host, en vez de permitir dos maestros.
- Bajo presión de RAM en la MacBook no se admiten nuevas cargas LM. Los trabajos
  no-LM pueden derivarse al iMac sólo si el peer autenticado responde; si no,
  quedan en cola o se ejecutan localmente dentro del límite explícito.
- La ejecución remota usa SSH por clave, `BatchMode` y host key estricta. Cada
  dirección necesita Remote Login activo y su clave dedicada; si una dirección
  no responde, se registra como peer no disponible y no se simula el offload.
- El GPT Cerebro usa Actions contra el Gateway. Drive queda detrás del Gateway
  como data plane/bus de bundles; no se habilita a la vez como App nativa del GPT,
  porque Apps y Actions son modos mutuamente excluyentes en el editor actual.
  Así la ubicación física iMac/MacBook es transparente para GPT.
- El Gateway de datos acepta inputs grandes sólo cuando negocia
  `chunked_input_v1`; el cliente transmite chunks acotados, verifica SHA por
  chunk y SHA/tamaño final. Sin esa capacidad declara evidencia insuficiente.

## Quality log obligatorio por auditoría

Cada evento material de auditoría debe registrar una entrada
`ai_quality_log_entry.v1` en:

- `90_QUALITY_LOG_DELTA/*.entry.json` dentro del run.
- tabla SQLite `quality_log` dentro de `STATE/state.sqlite`.

Eventos mínimos obligatorios:

- ejecución o skip de worker (`worker_execution_status`);
- bundle válido o inválido (`worker_bundle_validated` / `worker_bundle_rejected`);
- iteración de bucle interno agentic (`internal_loop_*`);
- auditoría manual ingresada (`manual_audit_ingested`).

Cada entrada debe contener identidad completa:

`slot_id + route_id + model_id + provider_id + provider_name + route + interface + cost_class + role + worker_id`.

Si un dato no consta, debe escribirse `NO_CONSTA`; no se deben inferir modelos o
providers inventados.
```

## SOURCE: contracts/CANON_ACTION_TRANSFER_POLICY_v1.md

```markdown
# CANON_ACTION_TRANSFER_POLICY_v1 — Camino A Cerebro/Gateway

Estado: v1.3.21-slot14-handoff.

## Decisión consolidada

Camino A adopta el patrón **control-plane + context-plane para GPT Cerebro** y reserva el
**data-plane** a Codex/Gateway/filesystem. El esquema de Camino B se toma como base técnica,
pero no se copia completo al GPT Builder. La Action del GPT Cerebro debe ser mínima y no debe
exponer endpoints admin, provider routing, creación general de corridas, upload de zips ni
aprobación de providers reservados.

## Reglas normativas

1. GPT Cerebro no transfiere zips, repositorios ni artefactos binarios grandes por Actions.
2. Codex/Gateway materializa zips, snapshots, manifests, hash trees, builds, tests, paquetes finales y `.DONE`.
3. El primer insumo de una tarea grande es `context_pack`: file map, hashes, summaries, critical files, omitted files, coverage y recommended_reads.
4. GPT puede listar todo el inventario, pero no queda obligado a leer linealmente todos los bytes si el context pack declara cobertura suficiente.
5. GPT sólo lee archivos completos cuando son críticos o pequeños; para el resto usa manifest, search y chunk/range bajo demanda.
6. Si el context pack falta, omite archivos críticos sin razón, no cubre evidencia necesaria, o el SHA no coincide, el resultado permitido es `insufficient_evidence` / `SIN_VEREDICTO_POR_EVIDENCIA_INSUFICIENTE`.
7. Salidas chicas pueden ir inline. Límite recomendado: 32 KiB; límite duro de la spec: 32768 caracteres. Salidas mayores usan upload fragmentado.
8. Output preferido: `patch_plan`, unified diff chico o `artifact_upload_ids`; Gateway/Codex aplica parches, testea y arma zip final server-side.
9. Chunks de salida son idempotentes: mismo índice + mismo hash/contenido acepta duplicado; mismo índice + contenido distinto es `409 Conflict`.
10. `start` de upload para artefactos GPT-origin puede aceptar `size_bytes`/`assert_sha256` nulos; Gateway calcula `computed_sha256` al finalizar. Para artefactos Codex-origin se exige SHA/size upfront.
11. La Action del Cerebro no incluye `createAuditRun`, `uploadTargetFile`, `startExternalAudits`, `probeProvider`, `approveReservedProvider`, `resolveFinding`, ni ids `openai_api`/`anthropic_claude`.
12. Si el Gateway real mantiene endpoints admin por compatibilidad, deben quedar fuera de la spec del GPT Builder y protegidos por scopes/tokens admin.
13. OpenAI API y Claude API siguen prohibidas para workers. Cualquier ruta/provider que intente usarlas debe fallar cerrado y quedar registrado en quality log.
14. El Knowledge servido por Gateway sigue prevaleciendo sobre Knowledge estático del Builder.
15. Seleccionar GPT-5.6 Sol no cambia este contrato de transporte ni habilita
    por sí solo Responses API, Programmatic Tool Calling o multi-agent de API.
16. La spec actual no acepta adjuntos de conversación mediante
    `openaiFileIdRefs`. No se añadirá ese campo hasta que el Gateway implemente y
    pruebe descarga inmediata, límites, MIME/magic, nombres seguros, SHA-256 y
    persistencia atómica; hasta entonces se usa ingesta manual/data plane.

## Flujo de input grande

1. Codex/Gateway ingesta el zip o snapshot fuera de GPT.
2. Gateway calcula manifest, SHA por archivo, hash tree y context pack.
3. GPT llama health, Knowledge metadata/chunks, run status, next task y context pack.
4. GPT valida `input_sha256` + `context_pack_sha256`.
5. GPT usa `searchCaminoABrainTaskFile` y `readCaminoABrainTaskFileChunk` sólo sobre evidencia necesaria.
6. Si la cobertura no alcanza, GPT entrega `insufficient_evidence`, no una aprobación.

## Flujo de output grande

1. GPT produce hallazgos estructurados y patch plan.
2. Si el patch/report excede 32 KiB, usa `startCaminoABrainArtifactUpload`.
3. GPT sube chunks numerados desde 0, reanuda con `getCaminoABrainArtifactUploadState` si hay retry.
4. Gateway valida chunks y genera `computed_sha256` en finalize.
5. GPT llama `submitCaminoABrainTaskResult` con `context_pack_sha256`, `input_sha256`, `evidence_read`, findings y `artifact_upload_ids`.
6. Gateway valida tarea vigente, evidencia, manifest, secretos y `.DONE`.

## Compatibilidad Camino B

Camino B puede adoptar estos endpoints y reglas, pero no debe mezclar su servidor,
watcher ni autoridad mecánica de estado con Camino A. Ambos caminos conservan
la identidad canónica de GPT como cerebro; sólo Camino B le asigna además la
orquestación lógica. La sincronización aceptable es de canon/patrón/protocolo,
no de estado mutable ni de watchers.
```

## SOURCE: actions/CAMINO_A_CEREBRO_ACTIONS.v1.yaml

```markdown
openapi: 3.1.0
info:
  title: Camino A Cerebro Actions
  version: 1.3.21
  description: >-
    Minimal Action surface for GPT Cerebro Camino A. This spec is control-plane
    and context-plane only. Codex/Gateway remain the data-plane for zips,
    filesystem, provider dispatch, builds, tests, manifests and .DONE.
servers:
  - url: https://auditor.marianogrammatico.com.ar
security:
  - GatewayApiKey: []
tags:
  - name: Health
  - name: Knowledge
  - name: Brain
paths:
  /health:
    get:
      operationId: getGatewayHealth
      tags: [Health]
      summary: Public gateway health, version and declared bridge limits.
      security: []
      responses:
        '200':
          description: Gateway is alive.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/HealthResponse'}
  /camino-a/knowledge/current:
    get:
      operationId: getCurrentCaminoAKnowledge
      tags: [Knowledge]
      summary: Read canonical shared Knowledge metadata and SHA-256.
      responses:
        '200':
          description: Current Knowledge metadata.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoAKnowledgeMetadata'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/Conflict'}
        '503': {$ref: '#/components/responses/AuthNotConfigured'}
  /camino-a/knowledge/current/chunk:
    get:
      operationId: getCaminoAKnowledgeChunk
      tags: [Knowledge]
      summary: Read one bounded canonical Knowledge text fragment.
      parameters:
        - in: query
          name: offset
          required: false
          schema: {type: integer, minimum: 0, default: 0}
        - in: query
          name: max_chars
          required: false
          schema: {type: integer, minimum: 1000, maximum: 24000, default: 12000}
      responses:
        '200':
          description: Knowledge fragment.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/TextChunk'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/Conflict'}
        '416': {$ref: '#/components/responses/RangeNotSatisfiable'}
  /camino-a/runs/{run_id}/status:
    get:
      operationId: getCaminoARunStatus
      tags: [Brain]
      summary: Read unified watcher and GPT brain task status.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
      responses:
        '200':
          description: Unified Camino A status.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoARunStatus'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
  /camino-a/runs/{run_id}/brain/tasks/next:
    get:
      operationId: getNextCaminoABrainTask
      tags: [Brain]
      summary: Read compact metadata for the next canonical Camino A brain task.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
      responses:
        '200':
          description: Current task or completed stage.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainTaskEnvelope'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
  /camino-a/runs/{run_id}/context-pack:
    get:
      operationId: getCaminoABrainContextPack
      tags: [Brain]
      summary: >-
        Read a bounded, SHA-identified context pack: file map, hashes, summaries,
        critical files, omitted files and recommended reads. This is the normal
        first input for large tasks.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: query
          name: mode
          required: false
          schema: {type: string, enum: [minimal, standard, deep, diff_focus, manual_audits_focus, code_focus], default: standard}
        - in: query
          name: max_chars
          required: false
          schema: {type: integer, minimum: 4000, maximum: 64000, default: 24000}
      responses:
        '200':
          description: Auditable context pack.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainContextPack'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/files:
    get:
      operationId: listCaminoABrainTaskFiles
      tags: [Brain]
      summary: List a bounded page of task input-file metadata.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
        - in: query
          name: cursor
          required: false
          schema: {type: integer, minimum: 0, default: 0}
        - in: query
          name: limit
          required: false
          schema: {type: integer, minimum: 1, maximum: 50, default: 20}
      responses:
        '200':
          description: File metadata page.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainTaskFilePage'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
  /camino-a/runs/{run_id}/files/{file_id}/manifest:
    get:
      operationId: getCaminoABrainTaskFileManifest
      tags: [Brain]
      summary: "Read file metadata only: path, sha256, size, line count, language, role and criticality."
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: file_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{24}$'}
      responses:
        '200':
          description: Single file manifest.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainTaskFileManifest'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/files/{file_id}:
    get:
      operationId: readCaminoABrainTaskFileChunk
      tags: [Brain]
      summary: Read one bounded text chunk from a task input file.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
        - in: path
          name: file_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{24}$'}
        - in: query
          name: offset
          required: false
          schema: {type: integer, minimum: 0, default: 0}
        - in: query
          name: max_chars
          required: false
          schema: {type: integer, minimum: 1000, maximum: 24000, default: 12000}
      responses:
        '200':
          description: Bounded file chunk.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainTaskFileChunk'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
        '416': {$ref: '#/components/responses/RangeNotSatisfiable'}
  /camino-a/runs/{run_id}/files/{file_id}/search:
    get:
      operationId: searchCaminoABrainTaskFile
      tags: [Brain]
      summary: Search inside one task input file and return bounded matches with offsets/line numbers.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: file_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{24}$'}
        - in: query
          name: q
          required: true
          schema: {type: string, minLength: 1, maxLength: 200}
        - in: query
          name: regex
          required: false
          schema: {type: boolean, default: false}
        - in: query
          name: max_matches
          required: false
          schema: {type: integer, minimum: 1, maximum: 100, default: 20}
      responses:
        '200':
          description: Bounded search result.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainFileSearchResult'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
        '422': {$ref: '#/components/responses/ValidationError'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/start:
    post:
      operationId: startCaminoABrainArtifactUpload
      x-openai-isConsequential: true
      tags: [Brain]
      summary: Start an idempotent chunked upload for one GPT-origin text output artifact.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/CaminoABrainArtifactUploadStart'}
      responses:
        '200':
          description: Upload initialized or resumed.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainArtifactUploadState'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/Conflict'}
        '422': {$ref: '#/components/responses/ValidationError'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/{upload_id}:
    get:
      operationId: getCaminoABrainArtifactUploadState
      tags: [Brain]
      summary: Read upload state for idempotent resume after retries or crash.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
        - in: path
          name: upload_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{24}$'}
      responses:
        '200':
          description: Upload state.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainArtifactUploadState'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '404': {$ref: '#/components/responses/NotFound'}
        '409': {$ref: '#/components/responses/Conflict'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/{upload_id}/chunks:
    post:
      operationId: uploadCaminoABrainArtifactChunk
      x-openai-isConsequential: true
      tags: [Brain]
      summary: Upload one idempotent bounded text chunk.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
        - in: path
          name: upload_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{24}$'}
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/CaminoABrainArtifactChunk'}
      responses:
        '200':
          description: Chunk accepted or duplicate accepted if same hash/content.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainArtifactChunkAccepted'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/Conflict'}
        '413': {$ref: '#/components/responses/PayloadTooLarge'}
        '422': {$ref: '#/components/responses/ValidationError'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/artifacts/{upload_id}/finalize:
    post:
      operationId: finalizeCaminoABrainArtifactUpload
      x-openai-isConsequential: true
      tags: [Brain]
      summary: Verify chunks, compute/compare SHA-256 and finalize one uploaded artifact.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
        - in: path
          name: upload_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{24}$'}
      responses:
        '200':
          description: Artifact finalized.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainArtifactUploadState'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/Conflict'}
        '422': {$ref: '#/components/responses/ValidationError'}
  /camino-a/runs/{run_id}/brain/tasks/{task_id}/result:
    post:
      operationId: submitCaminoABrainTaskResult
      x-openai-isConsequential: true
      tags: [Brain]
      summary: Submit GPT brain result; Gateway validates evidence and writes manifest/DONE.
      parameters:
        - in: path
          name: run_id
          required: true
          schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
        - in: path
          name: task_id
          required: true
          schema: {type: string, pattern: '^[a-f0-9]{32}$'}
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/CaminoABrainTaskResult'}
      responses:
        '200':
          description: Result accepted and materialized.
          content:
            application/json:
              schema: {$ref: '#/components/schemas/CaminoABrainResultAccepted'}
        '400': {$ref: '#/components/responses/BadRequest'}
        '401': {$ref: '#/components/responses/Unauthorized'}
        '409': {$ref: '#/components/responses/Conflict'}
        '413': {$ref: '#/components/responses/PayloadTooLarge'}
        '422': {$ref: '#/components/responses/ValidationError'}
components:
  securitySchemes:
    GatewayApiKey:
      type: apiKey
      in: header
      name: X-API-Key
  parameters:
    RunId:
      in: path
      name: run_id
      required: true
      schema: {type: string, pattern: '^RUN_[0-9]{8}_[0-9]{6}_[a-f0-9]{5}(?:_[A-Za-z0-9-][A-Za-z0-9_-]{0,199})?$'}
    TaskId:
      in: path
      name: task_id
      required: true
      schema: {type: string, pattern: '^[a-f0-9]{32}$'}
    FileId:
      in: path
      name: file_id
      required: true
      schema: {type: string, pattern: '^[a-f0-9]{24}$'}
    UploadId:
      in: path
      name: upload_id
      required: true
      schema: {type: string, pattern: '^[a-f0-9]{24}$'}
  responses:
    BadRequest:
      description: Bad request.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    Unauthorized:
      description: Missing or invalid X-API-Key.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    NotFound:
      description: Resource not found.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    Conflict:
      description: Invalid run state, stale task, hash mismatch or resource conflict.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    PayloadTooLarge:
      description: Request or file too large.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    RangeNotSatisfiable:
      description: Offset outside document.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    ValidationError:
      description: Validation error.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
    AuthNotConfigured:
      description: Gateway API key not configured; fail-closed.
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Error'}
  schemas:
    Error:
      type: object
      properties:
        detail: {type: string}
        code: {type: string}
    HealthResponse:
      type: object
      required: [status, gateway_version]
      properties:
        status: {type: string}
        gateway_version: {type: string}
        bridge_version: {type: string}
        limits:
          type: object
          additionalProperties: true
    CaminoAKnowledgeMetadata:
      type: object
      required: [schema_version, bundle_version, file, sha256, size_bytes, total_chars, brain_current, source_count, max_chunk_chars, delivery]
      properties:
        schema_version: {type: string}
        bundle_version: {type: string}
        file: {type: string}
        sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        size_bytes: {type: integer}
        total_chars: {type: integer}
        brain_current: {type: string}
        source_count: {type: integer}
        max_chunk_chars: {type: integer}
        delivery: {type: string}
    TextChunk:
      type: object
      required: [bundle_version, sha256, offset, next_offset, complete, content, chunk_sha256]
      properties:
        bundle_version: {type: string}
        sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        offset: {type: integer}
        next_offset: {type: integer}
        complete: {type: boolean}
        content: {type: string, maxLength: 24000}
        chunk_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
    CaminoABrainContextPack:
      type: object
      required: [schema_version, run_id, task_id, input_sha256, context_pack_sha256, file_map, critical_files, omitted_files, coverage]
      properties:
        schema_version: {type: string}
        run_id: {type: string}
        task_id: {type: string}
        input_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        context_pack_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        file_map:
          type: array
          items: {$ref: '#/components/schemas/CaminoABrainTaskFileManifest'}
        critical_files:
          type: array
          items: {type: string}
        omitted_files:
          type: array
          items:
            type: object
            required: [path, reason]
            properties:
              path: {type: string}
              reason: {type: string}
              sha256: {type: string}
              size_bytes: {type: integer}
        recommended_reads:
          type: array
          items: {type: string}
        risk_indicators:
          type: array
          items: {type: string}
        coverage:
          type: object
          required: [total_files, represented_files, omitted_files, critical_files_covered]
          properties:
            total_files: {type: integer}
            represented_files: {type: integer}
            omitted_files: {type: integer}
            critical_files_covered: {type: boolean}
    CaminoABrainTaskFileManifest:
      type: object
      required: [file_id, path, sha256, size_bytes, total_chars]
      properties:
        file_id: {type: string}
        path: {type: string}
        sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        size_bytes: {type: integer}
        total_chars: {type: integer}
        line_count: {type: integer}
        language: {type: string}
        role: {type: string}
        critical: {type: boolean}
        summary: {type: string}
        symbol_index:
          type: array
          items: {type: string}
    CaminoABrainTaskFilePage:
      type: object
      required: [run_id, task_id, input_sha256, files, complete, total_files]
      properties:
        run_id: {type: string}
        task_id: {type: string}
        input_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        files:
          type: array
          items: {$ref: '#/components/schemas/CaminoABrainTaskFileManifest'}
        next_cursor: {type: [integer, 'null']}
        complete: {type: boolean}
        total_files: {type: integer}
    CaminoABrainTaskFileChunk:
      allOf:
        - {$ref: '#/components/schemas/CaminoABrainTaskFileManifest'}
        - type: object
          required: [offset, next_offset, complete, content, chunk_sha256]
          properties:
            offset: {type: integer}
            next_offset: {type: integer}
            complete: {type: boolean}
            content: {type: string, maxLength: 24000}
            chunk_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
    CaminoABrainFileSearchResult:
      type: object
      required: [file_id, q, matches, total_matches, truncated]
      properties:
        file_id: {type: string}
        q: {type: string}
        matches:
          type: array
          items:
            type: object
            required: [line_number, char_offset, preview]
            properties:
              line_number: {type: integer}
              char_offset: {type: integer}
              preview: {type: string}
              context_before: {type: string}
              context_after: {type: string}
        total_matches: {type: integer}
        truncated: {type: boolean}
    CaminoABrainTask:
      type: object
      required: [task_id, run_id, slot_id, stage, input_sha256, required_artifacts, done_marker, file_count, total_size_bytes, file_delivery]
      properties:
        task_id: {type: string}
        run_id: {type: string}
        slot_id: {type: string, pattern: '^(?:[1-9]|1[0-4])$'}
        stage: {type: string}
        phase: {type: string}
        input_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        context_pack_required: {type: boolean, default: true}
        candidate_version: {type: [string, 'null']}
        candidate_sha256: {type: [string, 'null']}
        required_output_dir: {type: string}
        required_artifacts:
          type: array
          items: {type: string}
        done_marker: {type: string}
        instructions: {type: string}
        file_count: {type: integer}
        total_size_bytes: {type: integer}
        file_delivery: {type: string}
    CaminoABrainTaskEnvelope:
      type: object
      required: [run_id, state, phase]
      properties:
        run_id: {type: string}
        state: {type: string}
        phase: {type: string}
        task:
          oneOf:
            - {$ref: '#/components/schemas/CaminoABrainTask'}
            - {type: 'null'}
    CaminoABrainArtifact:
      type: object
      required: [name, content]
      properties:
        name: {type: string, maxLength: 200}
        content: {type: string, maxLength: 32768}
        sha256: {type: string, pattern: '^(sha256:)?[a-f0-9]{64}$'}
        base_sha256: {type: string, pattern: '^(sha256:)?[a-f0-9]{64}$'}
        base_path: {type: string}
    CaminoABrainArtifactUploadStart:
      type: object
      required: [name]
      properties:
        name: {type: string, maxLength: 200}
        artifact_kind: {type: string, enum: [patch_plan, unified_diff, new_file, full_rewrite, report], default: report}
        size_bytes: {type: [integer, 'null'], minimum: 1, maximum: 67108864}
        assert_sha256: {type: [string, 'null'], pattern: '^(sha256:)?[a-f0-9]{64}$'}
        total_chunks: {type: [integer, 'null'], minimum: 1, maximum: 99999}
        content_type: {type: string, default: text/plain}
        idempotency_key: {type: string, maxLength: 200}
        base_sha256: {type: [string, 'null'], pattern: '^(sha256:)?[a-f0-9]{64}$'}
        base_path: {type: [string, 'null']}
    CaminoABrainArtifactChunk:
      type: object
      required: [index, content]
      properties:
        index: {type: integer, minimum: 0, maximum: 99999}
        content: {type: string, maxLength: 24000}
        chunk_sha256: {type: [string, 'null'], pattern: '^[a-f0-9]{64}$'}
    CaminoABrainArtifactUploadState:
      type: object
      required: [upload_id, task_id, name, finalized]
      properties:
        upload_id: {type: string}
        task_id: {type: string}
        name: {type: string}
        size_bytes: {type: [integer, 'null']}
        assert_sha256: {type: [string, 'null']}
        computed_sha256: {type: [string, 'null']}
        finalized: {type: boolean}
        finalized_utc: {type: string}
        max_chunk_chars: {type: integer}
        chunks_received:
          type: array
          items: {type: integer}
        chunks_missing:
          type: array
          items: {type: integer}
        next_chunk_index: {type: [integer, 'null']}
        received_bytes: {type: integer}
    CaminoABrainArtifactChunkAccepted:
      type: object
      required: [upload_id, index, chunk_sha256, received_bytes]
      properties:
        upload_id: {type: string}
        index: {type: integer}
        duplicate: {type: boolean}
        chunk_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        received_bytes: {type: integer}
    CaminoABrainTaskResult:
      type: object
      required: [slot_id, status, context_pack_sha256, input_sha256, evidence_read]
      properties:
        slot_id: {type: string, pattern: '^(?:[1-9]|1[0-4])$'}
        status:
          type: string
          enum: [completed, code_required, no_new_findings, insufficient_evidence]
        context_pack_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        input_sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
        evidence_read:
          type: array
          items:
            type: object
            required: [file_id, sha256]
            properties:
              file_id: {type: string, pattern: '^[a-f0-9]{24}$'}
              sha256: {type: string, pattern: '^[a-f0-9]{64}$'}
              ranges_read:
                type: array
                items:
                  type: array
                  items: {type: integer}
        findings:
          type: array
          items:
            type: object
            required: [id, severity, summary]
            properties:
              id: {type: string}
              severity: {type: string, enum: [BLOCKER, HIGH, MEDIUM, LOW, INFO]}
              file_id: {type: string}
              file_path: {type: string}
              summary: {type: string}
        artifacts:
          type: array
          maxItems: 20
          items: {$ref: '#/components/schemas/CaminoABrainArtifact'}
        artifact_upload_ids:
          type: array
          maxItems: 20
          items: {type: string, pattern: '^[a-f0-9]{24}$'}
        patch_plan_ref:
          type: object
          additionalProperties: true
        summary: {type: string, maxLength: 20000}
        candidate_version: {type: string, maxLength: 100}
        candidate_sha256: {type: string, pattern: '^(sha256:)?[a-f0-9]{64}$'}
    CaminoABrainResultAccepted:
      type: object
      required: [run_id, task_id, state, manifest, done_marker]
      properties:
        run_id: {type: string}
        task_id: {type: string}
        state: {type: string}
        manifest: {type: string}
        done_marker: {type: string}
    CaminoARunStatus:
      type: object
      required: [run_id, current_phase, task_state, quality_hash_chain_ok]
      properties:
        run_id: {type: string}
        current_phase: {type: string}
        watcher_status: {type: string}
        primary_brain_status: {type: string}
        next_action: {type: string}
        task_state: {type: string}
        task_id: {type: [string, 'null']}
        current_slot: {type: [string, 'null'], pattern: '^(?:[1-9]|1[0-4])$'}
        completed_slots:
          type: array
          items: {type: string, pattern: '^(?:[1-9]|1[0-4])$'}
        manual_audits_received: {type: integer}
        quality_hash_chain_ok: {type: boolean}
```

## SOURCE: actions/SOL56_ACTIONS_EVAL_PROTOCOL.md

```markdown
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
```

## SOURCE: canon/CANON_SHARED_CONTRACT_v1.md

```markdown
# Contrato compartido Camino A / Camino B v1

## Fuente de verdad

Los tres actores (GPT, Claude y Codex) deben leer el mismo canon:

- `CANON_PROVIDER_MODEL_ROUTES.v1.json`: identidad exacta de cada ruta.
- `CANON_WORKFLOW_SLOTS.v1.json`: orden, rol, ciclos y bucles.
- `CANON_CHANGE_PROTOCOL_v1.md`: procedimiento obligatorio de cambio.

Los contratos de Camino A y Camino B no pueden redefinir libremente modelos,
providers ni orden. Solo pueden referenciar `route_id` y `slot_id` canónicos.
Los roles por camino viven en `config/path_roles.json`; el motor mecánico de
estado no se confunde con el orquestador lógico ni con el cerebro.

## Autoridad por camino

- El único cerebro es GPT (`gpt_manual_or_configured`) en ambos caminos. Una
  salida sólo cuenta como decisión de GPT si existe evidencia recibida por el
  Gateway/Drive bus y validada por hash; ningún adapter local puede simularla.
- Camino A: Codex es el orquestador lógico; `overnight_master` es únicamente el
  motor mecánico de estado, leases, validación y empaquetado.
- Camino B: GPT es cerebro y orquestador lógico; el Gateway es transporte y
  autoridad mecánica del estado remoto, nunca un cerebro sustituto.
- Los providers, LM Studio, Claude y los workers aportan ejecución o evidencia.
  No alteran por sí solos el orden de slots ni sustituyen a GPT.

## Política de modelo GPT Cerebro

- La ruta preferida para Camino A Cerebro y Camino B Auditor Externo es
  `chatgpt_gpt_5_6_sol_actions_plan`: GPT-5.6 Sol, GPT personalizado con Actions,
  modo no-Pro y razonamiento High cuando esa superficie lo permita.
- La ruta permanece deshabilitada hasta verificar en cada GPT Builder que el
  modelo está disponible con Actions y completar un smoke Action real. Mientras
  el gate esté pendiente, `chatgpt_gpt_5_5_plan` continúa como fallback activo.
- La identidad del modelo no puede inferirse de una buena respuesta. Debe constar
  en la configuración/evidencia de Builder y en el gate canónico.
- Sol puede mejorar razonamiento y orquestación, pero no amplía límites de
  archivos, URLs temporales, timeouts ni disponibilidad del Gateway.
- Responses API, Programmatic Tool Calling y multi-agent de API no están activos
  en esta release. OpenAI API continúa prohibida.
- Esta política del GPT Cerebro es independiente del slot 14: allí Claude CLI es
  primario y Codex `gpt-5.6-sol`/`ultra` por suscripción ChatGPT es fallback.
- En Camino A, el Codex orquestador puede permanecer en un modelo económico y
  con razonamiento bajo. El fallback abre otro `codex exec` efímero, ignora la
  configuración del orquestador y fija explícitamente `gpt-5.6-sol`/`ultra`.
  No existe ni se necesita un autocambio del modelo de la tarea orquestadora.
- En Camino B, GPT Desktop conserva razonamiento High como cerebro y
  orquestador. Tampoco sustituye al revisor Codex CLI Ultra: debe solicitarlo a
  un worker local separado mediante un puente verificable del Gateway.

## Identidad obligatoria

Cada ejecución y log debe contener:

`slot_id + route_id + model_id + provider_id + provider_name + route + interface + cost_class + role`

Modelo y provider son identidades distintas. Un mismo modelo por otro provider
requiere otro `route_id`.

## Flujo

- Bucle grande: slots 1 a 14.
- Ciclo A: slots 1 a 3.
- Ciclo B: slots 4 a 6.
- Ciclo C: slots 7 a 10.
- Cierre final: slots 11 a 14.

Si un slot termina sin correcciones, avanza al siguiente. Si hay correcciones,
aplica `correction_policy`. Alcanzado el máximo de bucles, avanza aunque haya
habido correcciones, dejando deuda explícita y evidencia en el log. Solo el slot
14 puede terminar el proceso como aprobado. Claude Code por suscripción es la
ruta primaria; únicamente si queda registrada su indisponibilidad de auth/CLI/
transporte puede entrar Codex `gpt-5.6-sol` con razonamiento `ultra`, autenticado
por la suscripción ChatGPT. Ninguna de las dos rutas usa API keys. La aprobación
exige cero cambios, cero findings, SHA vigente y slots 1–13 completos.

## Transferencia adversarial de slot 13 a slot 14

- Cada candidato que alcance el slot 14 genera un pedido de auditoría nuevo,
  ligado por SHA-256 a `run_id`, al árbol candidato vigente y a un diff acotado
  contra `INPUT/target_snapshot`. No se reutiliza un pedido de otro candidato.
- El pedido resume evidencia de slots 1–13, pruebas ya ejecutadas, correcciones
  alegadas, deuda residual, archivos agregados/modificados/eliminados y
  dependencias de riesgo. Evita reenviar historiales completos para no quemar
  tokens, pero nunca omite deuda ni límites de evidencia.
- Las conclusiones previas se tratan como hipótesis no confiables. El revisor
  debe buscar evidencia que las contradiga, intentar refutar cada corrección,
  construir contraejemplos o pruebas negativas y comprobar al menos una
  invariante crítica de forma independiente. Un pass previo no prueba el cierre.
- Claude y el fallback Codex reciben exactamente el mismo pedido y diff. Deben
  reconocer su SHA en la salida; un pedido ausente, alterado, obsoleto o de otro
  candidato se rechaza antes de abrir el CLI y jamás puede aprobar.
- Si Claude no está disponible y tampoco puede iniciarse el `codex exec`
  separado por login, capacidad, cuota o transporte, el estado es
  `SLOT14_OPERATOR_ACTION_REQUIRED`. Cambiar el modelo del orquestador o del GPT
  Desktop no satisface este contrato y ningún resultado manual puede aprobar.

## Ciclo del candidato y promoción de correcciones

- `INPUT/target_snapshot` es el seed inmutable y `00_CANDIDATE` es el árbol
  vigente que todos los workers deben consumir. Antes de despachar se recalcula
  su SHA-256 de árbol; una discrepancia, symlink, secreto u omisión en un snapshot
  remoto detiene el worker y no genera evidencia aceptable.
- Una corrección sólo puede volver como árbol completo `candidate_update.zip`,
  nunca como overlay parcial. Resultado, manifest y `.DONE` deben quedar ligados
  exactamente a `run_id + job_id + slot_id + worker_id + source_candidate_sha256`
  y declarar el SHA-256 del árbol resultante y del ZIP.
- El motor valida rutas, duplicados, mayúsculas equivalentes, symlinks, cantidad,
  tamaños, hashes, secretos y cambio real antes de extraer. Un claim de corrección
  sin bundle válido no completa el slot.
- Por ronda se promueve como máximo una corrección válida. La promoción reemplaza
  `00_CANDIDATE` atómicamente, conserva historial, incrementa versión/iteración y
  reinicia el bucle grande en slot 1; los resultados restantes quedan ligados al
  SHA anterior y no pueden contaminar la nueva ronda.
- El paquete final contiene recursivamente el `00_CANDIDATE` vigente, nunca un
  árbol vacío inesperado. El gate terminal compara árbol actual, manifest,
  contenido del ZIP y hashes antes de permitir `closed`.
- La evidencia del GPT Cerebro debe referenciar fuentes reales del catálogo con
  SHA exacto y `synthetic=false`. JSON sin request, validación del adapter,
  manifest y `.DONE` no cuenta como decisión externa.

## Bucle interno agentic

Todo actor agentic de GPT, Codex o Claude ejecuta el bucle interno de 1 a 10
iteraciones únicamente cuando el slot declara `internal_loop.required=true`.
Los slots con `loop_type=external_slot_loop`, incluido el 14, usan sólo el límite
externo del slot y no crean versiones `.001`–`.010`. Cuando corresponde, cada
iteración interna contiene:
auditar, reparar o reescribir, testear, reauditar y decidir. Cada corrección usa
tercer numeral `.001` a `.010`. La salida contiene sólo la última versión, diff
acumulado desde el seed, historial de iteraciones, tests y reauditoría final.
Un estado limpio exige cero bugs y cero mejoras técnicas pendientes. Al agotar
10 iteraciones se entrega la última versión con deuda residual explícita, nunca
un cierre limpio. “Confirmado” o “detectado” no reemplaza “reparado” o
“reescrito”. El actor puede declarar que su ronda quedó sin nuevos hallazgos,
pero no alterar el flujo ni aprobar el proceso, salvo la autoridad de slot 14:
Claude primario o Codex por suscripción como fallback comprobado.

## Reglas especiales

- OpenRouter free ejecuta todas las rutas allowlistadas con sufijo `:free`; no hay
  fallback pago.
- Carrera Nemotron: NVIDIA directo y OpenRouter free arrancan en slot 1. Primer
  resultado válido gana; el otro se cancela o ignora. Blackbox pago entra en slot
  4 solo si no hubo ganador free.
- `blackbox_nemotron_ultra_paid` está configurado y conserva como evidencia el
  último probe registrado en el canon. Esto no garantiza disponibilidad actual.
  Usa exclusivamente
  `BLACKBOX_API_KEY`, `https://api.blackbox.ai/v1`, `/chat/completions` y
  `blackboxai/nvidia/nemotron-3-ultra`. GPT, Claude y Codex deben incluirlo en
  las llamadas del slot 4 cuando no exista ganador válido de las dos rutas
  Nemotron gratuitas; antes del gate deben respetar la política de disponibilidad
  vigente y nunca ejecutarlo en slot 1.
- MiMo: Token Plan primero, Xiaomi PAYG segundo, DeepInfra tercero y reservado.
  OpenRouter está prohibido para MiMo.
- Una cuota/suscripción agotada abre el circuit breaker para todo el provider
  durante la corrida. GLM no repite rutas del mismo provider como si fueran
  fallbacks independientes; usa el fallback gratuito/de plan definido en canon.
- El fallback del slot 14 es secuencial, no paralelo: primero
  `claude_code_subscription_cli`; sólo ante un fallo de disponibilidad registrado
  entra `codex_gpt_5_6_sol_ultra_subscription_cli`. Este último exige
  `codex login status` autenticado con ChatGPT, modelo `gpt-5.6-sol`, esfuerzo
  `ultra`, ejecución efímera y ausencia de `OPENAI_API_KEY`.
- GPT (`gpt_manual_or_configured`) es el unico cerebro del flujo. En los slots
  GPT actua como consolidador, escritor o reauditor segun el rol canonico.
  Codex y los providers API son infraestructura o workers de evidencia: nunca
  cerebros alternativos ni decisores por sustitucion automatica.
- Ningún actor edita el log append-only ni sus anchors a mano.

## Contrato de proveedores de Camino A

Camino A usa este canon de proveedores como fuente de verdad operativa. Cada
slot debe referenciar `provider_id` y `route_id` exactos. Si un mismo modelo
cambia de provider, se trata como otra ruta distinta y requiere otro
`route_id`.

### Grupos canónicos de Camino A

- `gemini_aistudio_free`
- `vertex_gemini_2_5_pro`
- `deepseek`
- `blackbox_free`
- `openrouter_free`
- `nvidia_nemotron_direct`
- `groq_gpt_oss_120b`
- `groq_llama_33_70b`
- `groq_qwen3_32b`
- `blackbox_intermediate`
- `deepinfra_qwen`
- `deepinfra_minimax`
- `deepinfra_kimi`
- `deepinfra_glm`
- `zai_glm`
- `moonshot_kimi`
- `chatgpt_plan`
- `claude_plan_manual`
- `lmstudio_macbook_bridge`

### Reglas de operación de proveedores

- `openrouter_free` ejecuta todos los modelos `:free` allowlistados y no puede
  caer en fallback pago.
- `nvidia_nemotron_direct` y `openrouter_free` pueden correr en carrera; el
  primer resultado válido gana.
- `blackbox_free` y `blackbox_intermediate` no comparten modelo como si fueran
  la misma ruta.
- `deepinfra_kimi`, `deepinfra_glm` y `zai_glm` se gobiernan por sus slots,
  presupuestos y fallbacks internos; la lentitud por sí sola no invalida una
  ronda si sigue habiendo heartbeat.
- `chatgpt_plan` escribe cuando el slot lo pide.
- `claude_plan_manual` es el revisor/cierre final sólo cuando el contrato lo
  permite.
- `lmstudio_macbook_bridge` usa LM Studio en la MacBook, local por loopback si
  el proceso se lanza allí o por bridge si se lanza desde la iMac. El endpoint
  se descubre/overridea mediante la política de host; no se fija una IP única
  dentro del canon. Su interfaz es OpenAI-compatible y su costo `local_free`.
- Los route_id LM Studio de tier 1 entran en slot 1 como auditores gratuitos
  locales. Los route_id tier 2 entran en slot 4 como apoyo intermedio local.
- Antes de llamar LM Studio se debe verificar `/v1/models`; si el endpoint no
  responde se registra `NO_CONSTA` o `lmstudio_unavailable_connection_refused`.
- Los modelos medianos LM Studio corren con máximo 2 concurrentes y sólo si el
  guard de RAM conserva el piso de seguridad configurado. La reserva se toma en
  el host que posee la RAM antes de cargar/generar y se mantiene con heartbeat.
  El Nemotron local de 70B es exclusivo de alta criticidad y no entra en slots
  generales.
- Deduplicación local/pago: una ruta LM Studio local gratuita sólo excluye una
  ruta paga si hay equivalencia exacta o sustancial de modelo, capacidad y rol.
  Misma familia no alcanza. `deepinfra_qwen3_coder_480b` no es duplicado de los
  Qwen locales 30B/32B y permanece activo en etapas distintas. Desde v1.3.18 sólo
  queda excluida de slots automáticos `blackbox_devstral_2`, reemplazada por
  `lmstudio_devstral_small_2507`.

### Regla de tiempo y heartbeat

- Una ronda puede durar horas si mantiene heartbeat y progreso.
- Timeout duro no debe matar un proceso vivo que aún está dentro de su
  presupuesto de slot.
- El criterio principal de vida es `heartbeat`, no sólo el reloj.
- Si no hay heartbeat ni progreso dentro del presupuesto, se falla cerrado.
- Los watchers pertenecen a Camino A y controlan la ida y vuelta de `.DONE`.

## Portabilidad iMac / MacBook y Drive

- El mismo entrypoint puede lanzarse desde cualquiera de los dos equipos. Cada
  corrida registra `node_id`, arquitectura, memoria, endpoint LM seleccionado y
  peer disponible en `RUN_CONFIG.json`.
- SQLite/WAL y locks permanecen locales al coordinador. Google Drive transporta
  exclusivamente bundles inmutables terminados con manifest y `.DONE`; no se
  usa como base de datos activa ni como lock distribuido.
- En macOS el locator busca de forma acotada `CAMINO_A_SHARED/AUDIT_BUS` bajo
  `My Drive` o `Mi unidad` de cada provider Google Drive. Sólo crea la carpeta
  cuando existe exactamente una raíz reconocida; ante cuentas múltiples exige
  `CAMINO_SHARED_ROOT` o `CAMINO_DRIVE_BUS_ROOT` y falla cerrado.
- Si ambos equipos intentan coordinar la misma corrida, un lease remoto/atómico
  decide un único dueño. Sin lease fiable se falla cerrado y se pide elegir el
  host, en vez de permitir dos maestros.
- Bajo presión de RAM en la MacBook no se admiten nuevas cargas LM. Los trabajos
  no-LM pueden derivarse al iMac sólo si el peer autenticado responde; si no,
  quedan en cola o se ejecutan localmente dentro del límite explícito.
- La ejecución remota usa SSH por clave, `BatchMode` y host key estricta. Cada
  dirección necesita Remote Login activo y su clave dedicada; si una dirección
  no responde, se registra como peer no disponible y no se simula el offload.
- El GPT Cerebro usa Actions contra el Gateway. Drive queda detrás del Gateway
  como data plane/bus de bundles; no se habilita a la vez como App nativa del GPT,
  porque Apps y Actions son modos mutuamente excluyentes en el editor actual.
  Así la ubicación física iMac/MacBook es transparente para GPT.
- El Gateway de datos acepta inputs grandes sólo cuando negocia
  `chunked_input_v1`; el cliente transmite chunks acotados, verifica SHA por
  chunk y SHA/tamaño final. Sin esa capacidad declara evidencia insuficiente.

## Quality log obligatorio por auditoría

Cada evento material de auditoría debe registrar una entrada
`ai_quality_log_entry.v1` en:

- `90_QUALITY_LOG_DELTA/*.entry.json` dentro del run.
- tabla SQLite `quality_log` dentro de `STATE/state.sqlite`.

Eventos mínimos obligatorios:

- ejecución o skip de worker (`worker_execution_status`);
- bundle válido o inválido (`worker_bundle_validated` / `worker_bundle_rejected`);
- iteración de bucle interno agentic (`internal_loop_*`);
- auditoría manual ingresada (`manual_audit_ingested`).

Cada entrada debe contener identidad completa:

`slot_id + route_id + model_id + provider_id + provider_name + route + interface + cost_class + role + worker_id`.

Si un dato no consta, debe escribirse `NO_CONSTA`; no se deben inferir modelos o
providers inventados.
```

## SOURCE: canon/CANON_CHANGE_PROTOCOL_v1.md

```markdown
# Protocolo canónico de cambios v1

## Alcance

Este protocolo rige cualquier cambio de roles, slots, rutas, fallbacks,
contratos, esquemas, transporte, políticas de RAM o autoridad de Camino A y
Camino B. Evita que prompts, Knowledge, runtime y paquete publicado diverjan.

## Secuencia obligatoria

1. Modificar primero las fuentes normativas bajo `canon/` y las políticas
   estructuradas bajo `config/`; nunca corregir sólo un archivo generado.
2. Mantener idéntico `canon_version` en rutas, slots y runtime. Un cambio que
   afecte autoridad, identidad o ejecución debe incrementar la versión.
3. Sincronizar `contracts/CAMINO_SHARED_CONTRACT.md` con el contrato canónico y
   regenerar los nueve archivos de `generated/` mediante
   `scripts/render_contracts.py`.
4. Validar ambos perfiles productivos y el perfil de sandbox con
   `scripts/canon_loader.py`; referencias inexistentes o rutas deshabilitadas
   sin fallback independiente fallan cerrado.
5. Reconstruir `CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.md` y su manifest desde la
   lista cerrada de fuentes. Verificar versión, tamaño, SHA-256 y hashes de cada
   fuente antes de publicar.
6. Ejecutar la suite completa, el smoke mecánico y las pruebas operativas que
   el cambio permita. Separar siempre evidencia simulada, sandbox y live.
7. Registrar deudas y dependencias externas como `FALLÓ` o `NO PROBADO`; nunca
   promoverlas a `VERIFICADO` por inferencia.
8. Empaquetar sólo después de los checks de sincronía. El manifest de release y
   el sidecar SHA-256 son la autoridad del ZIP entregado.

## Reglas de seguridad

- OpenAI API y Claude API permanecen prohibidas mientras el canon no cambie de
  forma explícita; las suscripciones CLI no se sustituyen con claves API.
- SQLite, WAL, locks y leases son locales. Drive transporta sólo bundles
  inmutables cerrados; un cambio de esta regla requiere un diseño de consenso
  y pruebas de doble coordinador.
- Las rutas remotas requieren identidad de host estricta, clave dedicada,
  `BatchMode` y guard de recursos ejecutado en el host que posee la RAM.
- Slot 14 conserva orden secuencial: Claude CLI primario; Codex por suscripción
  sólo después de indisponibilidad de Claude registrada.
- Un output sólo cuenta si liga run, slot y SHA del candidato y pasa manifest,
  hashes, secretos, cambios de workspace y autoridad terminal.

## Criterio de cierre del cambio

El cambio queda integrado sólo cuando canon, contratos, generados, Knowledge,
tests y manifest coinciden. La disponibilidad de servicios externos se declara
por separado y exige prueba viva; un paquete coherente no demuestra por sí solo
operación productiva de extremo a extremo.
```

## SOURCE: canon/CANON_PROVIDER_MODEL_ROUTES.v1.json

```json
{
  "schema_version": "canon_provider_model_routes.v1",
  "canon_version": "camino_shared_canon.v1.3.21-slot14-handoff",
  "updated_utc": "2026-07-11T00:00:00Z",
  "identity_fields": [
    "slot_id",
    "route_id",
    "model_id",
    "provider_id",
    "provider_name",
    "route",
    "interface",
    "cost_class",
    "role"
  ],
  "default_deny": true,
  "routes": {
    "gemini_aistudio_3_5_flash": {
      "route_id": "gemini_aistudio_3_5_flash",
      "provider_id": "gemini_aistudio_free",
      "provider_name": "Google AI Studio",
      "model_id": "gemini-3.5-flash",
      "route": "gemini_developer_api",
      "interface": "native_generate_content",
      "cost_class": "free_quota",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "gemini_aistudio_3_1_pro": {
      "route_id": "gemini_aistudio_3_1_pro",
      "provider_id": "gemini_aistudio_free",
      "provider_name": "Google AI Studio",
      "model_id": "gemini-3.1-pro",
      "route": "gemini_developer_api",
      "interface": "native_generate_content",
      "cost_class": "free_quota",
      "status": "fallback_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "gemini_aistudio_3_0_pro": {
      "route_id": "gemini_aistudio_3_0_pro",
      "provider_id": "gemini_aistudio_free",
      "provider_name": "Google AI Studio",
      "model_id": "gemini-3.0-pro",
      "route": "gemini_developer_api",
      "interface": "native_generate_content",
      "cost_class": "free_quota",
      "status": "fallback_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "gemini_aistudio_2_5_pro": {
      "route_id": "gemini_aistudio_2_5_pro",
      "provider_id": "gemini_aistudio_free",
      "provider_name": "Google AI Studio",
      "model_id": "gemini-2.5-pro",
      "route": "gemini_developer_api",
      "interface": "native_generate_content",
      "cost_class": "free_quota",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "gemini_aistudio_2_5_flash": {
      "route_id": "gemini_aistudio_2_5_flash",
      "provider_id": "gemini_aistudio_free",
      "provider_name": "Google AI Studio",
      "model_id": "gemini-2.5-flash",
      "route": "gemini_developer_api",
      "interface": "native_generate_content",
      "cost_class": "free_quota",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "vertex_gemini_2_5_pro": {
      "route_id": "vertex_gemini_2_5_pro",
      "provider_id": "vertex_gemini_2_5",
      "provider_name": "Google Vertex AI",
      "model_id": "gemini-2.5-pro",
      "route": "vertex_adc",
      "interface": "native_generate_content",
      "cost_class": "vertex_credit",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "vertex_gemini_2_5_flash": {
      "route_id": "vertex_gemini_2_5_flash",
      "provider_id": "vertex_gemini_2_5",
      "provider_name": "Google Vertex AI",
      "model_id": "gemini-2.5-flash",
      "route": "vertex_adc",
      "interface": "native_generate_content",
      "cost_class": "vertex_credit",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "vertex_gemini_2_5_flash_lite": {
      "route_id": "vertex_gemini_2_5_flash_lite",
      "provider_id": "vertex_gemini_2_5",
      "provider_name": "Google Vertex AI",
      "model_id": "gemini-2.5-flash-lite",
      "route": "vertex_adc",
      "interface": "native_generate_content",
      "cost_class": "vertex_credit",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "deepseek_v4_flash": {
      "route_id": "deepseek_v4_flash",
      "provider_id": "deepseek",
      "provider_name": "DeepSeek API",
      "model_id": "deepseek-v4-flash",
      "route": "api_key",
      "interface": "openai_compatible",
      "cost_class": "cheap_direct",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "deepseek_v4_pro": {
      "route_id": "deepseek_v4_pro",
      "provider_id": "deepseek",
      "provider_name": "DeepSeek API",
      "model_id": "deepseek-v4-pro",
      "route": "api_key",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "deepseek_chat_legacy": {
      "route_id": "deepseek_chat_legacy",
      "provider_id": "deepseek",
      "provider_name": "DeepSeek API",
      "model_id": "deepseek-chat",
      "route": "api_key",
      "interface": "openai_compatible",
      "cost_class": "cheap_direct",
      "status": "legacy_alias",
      "reserved": false,
      "agentic": false
    },
    "deepseek_reasoner_legacy": {
      "route_id": "deepseek_reasoner_legacy",
      "provider_id": "deepseek",
      "provider_name": "DeepSeek API",
      "model_id": "deepseek-reasoner",
      "route": "api_key",
      "interface": "openai_compatible",
      "cost_class": "cheap_direct",
      "status": "legacy_alias",
      "reserved": false,
      "agentic": false
    },
    "blackbox_grok_code_fast_free": {
      "route_id": "blackbox_grok_code_fast_free",
      "provider_id": "blackbox_free",
      "provider_name": "Blackbox",
      "model_id": "blackboxai/x-ai/grok-code-fast-1:free",
      "route": "blackbox_free",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "blackbox_minimax_m2_5_free": {
      "route_id": "blackbox_minimax_m2_5_free",
      "provider_id": "blackbox_free",
      "provider_name": "Blackbox",
      "model_id": "blackboxai/minimax/minimax-free",
      "route": "blackbox_free",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "probe_required",
      "reserved": false,
      "agentic": false,
      "max_prompt_tokens_est": 180000
    },
    "openrouter_qwen_coder_free": {
      "route_id": "openrouter_qwen_coder_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "qwen/qwen3-coder:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "openrouter_nemotron_free": {
      "route_id": "openrouter_nemotron_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "nvidia/nemotron-3-ultra-550b-a55b:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "openrouter_nemotron_free_legacy": {
      "route_id": "openrouter_nemotron_free_legacy",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "nvidia/nemotron-3-ultra:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "legacy_alias",
      "reserved": false,
      "agentic": false
    },
    "openrouter_gpt_oss_120b_free": {
      "route_id": "openrouter_gpt_oss_120b_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "openai/gpt-oss-120b:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "openrouter_llama_33_70b_free": {
      "route_id": "openrouter_llama_33_70b_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "meta-llama/llama-3.3-70b-instruct:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "configured",
      "reserved": false,
      "agentic": false,
      "max_prompt_tokens_est": 65000,
      "quarantine_status": "context_budget_gate"
    },
    "openrouter_qwen3_next_free": {
      "route_id": "openrouter_qwen3_next_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "qwen/qwen3-next:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "openrouter_hermes_3_405b_free": {
      "route_id": "openrouter_hermes_3_405b_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "nousresearch/hermes-3-llama-3.1-405b:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "openrouter_gemma_4_31b_free": {
      "route_id": "openrouter_gemma_4_31b_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "google/gemma-4-31b-it:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "openrouter_gemma_4_26b_free": {
      "route_id": "openrouter_gemma_4_26b_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "google/gemma-4-26b-a4b-it:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "openrouter_nemotron_nano_omni_30b_free": {
      "route_id": "openrouter_nemotron_nano_omni_30b_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "openrouter_nex_n2_pro_free": {
      "route_id": "openrouter_nex_n2_pro_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "nex-agi/nex-n2-pro:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "openrouter_laguna_m1_free": {
      "route_id": "openrouter_laguna_m1_free",
      "provider_id": "openrouter_free",
      "provider_name": "OpenRouter",
      "model_id": "poolside/laguna-m.1:free",
      "route": "openrouter",
      "interface": "openai_compatible",
      "cost_class": "free",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "nvidia_nemotron_ultra_direct": {
      "route_id": "nvidia_nemotron_ultra_direct",
      "provider_id": "nvidia_nemotron_direct",
      "provider_name": "NVIDIA direct",
      "model_id": "nvidia/nemotron-3-ultra-550b-a55b",
      "route": "nvidia_api",
      "interface": "openai_compatible",
      "cost_class": "free_or_credit",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "nvidia_nemotron_ultra_direct_short": {
      "route_id": "nvidia_nemotron_ultra_direct_short",
      "provider_id": "nvidia_nemotron_direct",
      "provider_name": "NVIDIA direct",
      "model_id": "nvidia/nemotron-3-ultra",
      "route": "nvidia_api",
      "interface": "openai_compatible",
      "cost_class": "free_or_credit",
      "status": "legacy_alias",
      "reserved": false,
      "agentic": false
    },
    "nvidia_nemotron_ultra_direct_bare": {
      "route_id": "nvidia_nemotron_ultra_direct_bare",
      "provider_id": "nvidia_nemotron_direct",
      "provider_name": "NVIDIA direct",
      "model_id": "nemotron-3-ultra",
      "route": "nvidia_api",
      "interface": "openai_compatible",
      "cost_class": "free_or_credit",
      "status": "legacy_alias",
      "reserved": false,
      "agentic": false
    },
    "groq_gpt_oss_120b": {
      "route_id": "groq_gpt_oss_120b",
      "provider_id": "groq_gpt_oss_120b",
      "provider_name": "Groq",
      "model_id": "openai/gpt-oss-120b",
      "route": "groq_api",
      "interface": "openai_compatible",
      "cost_class": "free_quota",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "groq_llama_33_70b": {
      "route_id": "groq_llama_33_70b",
      "provider_id": "groq_llama_33_70b",
      "provider_name": "Groq",
      "model_id": "llama-3.3-70b-versatile",
      "route": "groq_api",
      "interface": "openai_compatible",
      "cost_class": "free_quota",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "groq_qwen3_32b": {
      "route_id": "groq_qwen3_32b",
      "provider_id": "groq_qwen3_32b",
      "provider_name": "Groq",
      "model_id": "qwen/qwen3-32b",
      "route": "groq_api",
      "interface": "openai_compatible",
      "cost_class": "free_quota",
      "status": "configured",
      "reserved": false,
      "agentic": false
    },
    "vertex_gemini_3_1_pro": {
      "route_id": "vertex_gemini_3_1_pro",
      "provider_id": "vertex_gemini_3",
      "provider_name": "Google Vertex AI",
      "model_id": "gemini-3.1-pro",
      "route": "vertex_adc",
      "interface": "native_generate_content",
      "cost_class": "vertex_credit_or_intermediate",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "vertex_gemini_3_0_pro": {
      "route_id": "vertex_gemini_3_0_pro",
      "provider_id": "vertex_gemini_3",
      "provider_name": "Google Vertex AI",
      "model_id": "gemini-3.0-pro",
      "route": "vertex_adc",
      "interface": "native_generate_content",
      "cost_class": "vertex_credit_or_intermediate",
      "status": "fallback_requires_live_listing",
      "reserved": false,
      "agentic": false
    },
    "vertex_gemini_3_1_pro_preview_execution": {
      "route_id": "vertex_gemini_3_1_pro_preview_execution",
      "provider_id": "vertex_gemini_3_1_pro_preview",
      "provider_name": "Google Vertex AI",
      "model_id": "gemini-3.1-pro-preview",
      "route": "vertex_generate_content",
      "interface": "native_generate_content",
      "cost_class": "paid_credit",
      "status": "model_id_requires_live_listing",
      "reserved": false,
      "agentic": true
    },
    "gemini_aistudio_highest_execution": {
      "route_id": "gemini_aistudio_highest_execution",
      "provider_id": "gemini_aistudio_highest",
      "provider_name": "Google AI Studio",
      "model_id": "gemini-3.5-flash",
      "route": "google_ai_studio_generate_content",
      "interface": "native_generate_content",
      "cost_class": "plan_or_free",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "blackbox_nemotron_ultra_paid": {
      "route_id": "blackbox_nemotron_ultra_paid",
      "provider_id": "blackbox_intermediate",
      "provider_name": "Blackbox",
      "model_id": "blackboxai/nvidia/nemotron-3-ultra",
      "route": "blackbox_paid",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "configured",
      "reserved": false,
      "agentic": false,
      "credential_env": "BLACKBOX_API_KEY",
      "base_url": "https://api.blackbox.ai/v1",
      "endpoint": "/chat/completions",
      "active_call_policy": "slot_4_only_without_valid_free_nemotron_winner",
      "probe_verified_utc": "2026-07-02T12:30:43Z"
    },
    "blackbox_trinity_large_thinking": {
      "route_id": "blackbox_trinity_large_thinking",
      "provider_id": "blackbox_intermediate",
      "provider_name": "Blackbox",
      "model_id": "blackboxai/arcee-ai/trinity-large-thinking",
      "route": "blackbox_paid",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "probe_required",
      "reserved": false,
      "agentic": false
    },
    "blackbox_devstral_2": {
      "route_id": "blackbox_devstral_2",
      "provider_id": "blackbox_intermediate",
      "provider_name": "Blackbox",
      "model_id": "blackboxai/mistral/devstral-2",
      "route": "blackbox_paid",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "excluded_paid_duplicate_local_available",
      "reserved": false,
      "agentic": false,
      "excluded_by_local_route_id": "lmstudio_devstral_small_2507",
      "active_call_policy": "excluded_from_automatic_slots_when_lmstudio_available",
      "notes": " Excluded from automatic slots by v1.3.17: local LM Studio route has priority."
    },
    "deepinfra_qwen3_coder_480b": {
      "route_id": "deepinfra_qwen3_coder_480b",
      "provider_id": "deepinfra_qwen",
      "provider_name": "DeepInfra",
      "model_id": "Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "configured",
      "reserved": false,
      "agentic": false,
      "active_call_policy": "auto_allowed_paid_intermediate_distinct_capacity_not_duplicate_of_local_30b",
      "notes": "Restored in v1.3.18: Qwen3 Coder 480B is not equivalent to local 30B/32B models. Same family is not enough for paid exclusion when parameter scale/capability differs materially."
    },
    "xiaomi_mimo_token_plan_agentic": {
      "route_id": "xiaomi_mimo_token_plan_agentic",
      "provider_id": "xiaomi_mimo_token_plan_agentic",
      "provider_name": "Xiaomi MiMo Token Plan",
      "model_id": "mimo-v2.5-pro",
      "route": "xiaomi_token_plan_openclaw_agent",
      "interface": "openclaw_agent",
      "cost_class": "prepaid_token_plan",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "xiaomi_mimo_payg_agentic": {
      "route_id": "xiaomi_mimo_payg_agentic",
      "provider_id": "xiaomi_mimo_payg_agentic",
      "provider_name": "Xiaomi MiMo API",
      "model_id": "mimo-v2.5-pro",
      "route": "xiaomi_payg_openclaw_agent",
      "interface": "openclaw_agent",
      "cost_class": "paid_payg",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "deepinfra_mimo_manual": {
      "route_id": "deepinfra_mimo_manual",
      "provider_id": "deepinfra_mimo_manual",
      "provider_name": "DeepInfra",
      "model_id": "XiaomiMiMo/MiMo-V2.5-Pro",
      "route": "deepinfra_openai_compatible_manual",
      "interface": "openai_compatible",
      "cost_class": "paid_manual",
      "status": "configured",
      "reserved": true,
      "agentic": true
    },
    "deepinfra_minimax_m2_7": {
      "route_id": "deepinfra_minimax_m2_7",
      "provider_id": "deepinfra_minimax",
      "provider_name": "DeepInfra",
      "model_id": "MiniMaxAI/MiniMax-M2.7",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "deepinfra_minimax_m2_5": {
      "route_id": "deepinfra_minimax_m2_5",
      "provider_id": "deepinfra_minimax",
      "provider_name": "DeepInfra",
      "model_id": "MiniMaxAI/MiniMax-M2.5",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid_intermediate",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "deepinfra_kimi_k2_7_code": {
      "route_id": "deepinfra_kimi_k2_7_code",
      "provider_id": "deepinfra_kimi",
      "provider_name": "DeepInfra",
      "model_id": "moonshotai/Kimi-K2.7-Code",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "zai_glm_5_2": {
      "route_id": "zai_glm_5_2",
      "provider_id": "zai_glm",
      "provider_name": "Z.ai",
      "model_id": "glm-5.2",
      "route": "subscription_flat",
      "interface": "openai_compatible",
      "cost_class": "flat_subscription",
      "status": "disabled_quota",
      "disabled_reason": "subscription_credit_exhausted",
      "reserved": false,
      "agentic": true
    },
    "zai_glm_5_1": {
      "route_id": "zai_glm_5_1",
      "provider_id": "zai_glm",
      "provider_name": "Z.ai",
      "model_id": "glm-5.1",
      "route": "subscription_flat",
      "interface": "openai_compatible",
      "cost_class": "flat_subscription",
      "status": "disabled_quota",
      "disabled_reason": "subscription_credit_exhausted",
      "reserved": false,
      "agentic": true
    },
    "zai_glm_5": {
      "route_id": "zai_glm_5",
      "provider_id": "zai_glm",
      "provider_name": "Z.ai",
      "model_id": "glm-5",
      "route": "subscription_flat",
      "interface": "openai_compatible",
      "cost_class": "flat_subscription",
      "status": "disabled_quota",
      "disabled_reason": "subscription_credit_exhausted",
      "reserved": false,
      "agentic": true
    },
    "deepinfra_glm_5_2": {
      "route_id": "deepinfra_glm_5_2",
      "provider_id": "deepinfra_glm",
      "provider_name": "DeepInfra",
      "model_id": "zai-org/GLM-5.2",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "deepinfra_glm_5_1": {
      "route_id": "deepinfra_glm_5_1",
      "provider_id": "deepinfra_glm",
      "provider_name": "DeepInfra",
      "model_id": "zai-org/GLM-5.1",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "deepinfra_glm_5": {
      "route_id": "deepinfra_glm_5",
      "provider_id": "deepinfra_glm",
      "provider_name": "DeepInfra",
      "model_id": "zai-org/GLM-5",
      "route": "api_paid",
      "interface": "openai_compatible",
      "cost_class": "paid",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "zai_glm_5_0": {
      "route_id": "zai_glm_5_0",
      "provider_id": "zai_glm",
      "provider_name": "Z.ai",
      "model_id": "glm-5.0",
      "route": "subscription_flat",
      "interface": "openai_compatible",
      "cost_class": "flat_subscription",
      "status": "disabled_quota",
      "disabled_reason": "subscription_credit_exhausted",
      "reserved": false,
      "agentic": true
    },
    "zai_glm_5_turbo": {
      "route_id": "zai_glm_5_turbo",
      "provider_id": "zai_glm",
      "provider_name": "Z.ai",
      "model_id": "glm-5-turbo",
      "route": "subscription_flat",
      "interface": "openai_compatible",
      "cost_class": "flat_subscription",
      "status": "disabled_quota",
      "disabled_reason": "subscription_credit_exhausted",
      "reserved": false,
      "agentic": true
    },
    "moonshot_kimi_k2_6": {
      "route_id": "moonshot_kimi_k2_6",
      "provider_id": "moonshot_kimi",
      "provider_name": "Moonshot",
      "model_id": "kimi-k2.6",
      "route": "api_key_free_or_flat",
      "interface": "openai_compatible",
      "cost_class": "free_or_flat",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "moonshot_kimi_k2_5": {
      "route_id": "moonshot_kimi_k2_5",
      "provider_id": "moonshot_kimi",
      "provider_name": "Moonshot",
      "model_id": "kimi-k2.5",
      "route": "api_key_free_or_flat",
      "interface": "openai_compatible",
      "cost_class": "free_or_flat",
      "status": "configured",
      "reserved": false,
      "agentic": true
    },
    "chatgpt_gpt_5_6_sol_actions_plan": {
      "route_id": "chatgpt_gpt_5_6_sol_actions_plan",
      "provider_id": "chatgpt_plan",
      "provider_name": "ChatGPT",
      "model_id": "gpt-5.6-sol",
      "route": "chatgpt_custom_gpt_actions",
      "interface": "interactive_plan",
      "cost_class": "plan",
      "status": "disabled_pending_builder_verification",
      "reserved": false,
      "agentic": true,
      "surface": "custom_gpt_actions",
      "required_mode": "non_pro",
      "preferred_reasoning_level": "high",
      "actions_required": true,
      "api_key_allowed": false,
      "availability_gate": "builder_model_picker_and_live_action_smoke",
      "builder_verification": {
        "status": "camino_a_verified_camino_b_pending",
        "model_picker_evidence": "gpt_builder_live_inspection_2026-07-12",
        "visible_model_id": "gpt-5.6-sol",
        "visible_reasoning_level": "high",
        "verified_at_utc": null,
        "action_smoke_evidence": null,
        "gpts": {
          "camino_a_cerebro": {
            "gpt_id": "g-6a4306681a108191b269fb88b9386669",
            "builder_model": "GPT-5.6 Thinking",
            "reasoning_level": "high",
            "published": true,
            "action_operation_count": 15,
            "action_smoke": {
              "verified_at_utc": "2026-07-12T03:08:41Z",
              "conversation_id": "6a530414-77ec-83e9-af65-8c128666f4f1",
              "operations": [
                "getGatewayHealth",
                "getCurrentCaminoAKnowledge"
              ],
              "status": "ok",
              "gateway_version": "1.2.20",
              "remote_bundle_version": "v1.3.15-corrected",
              "remote_bundle_sha256": "64e163fd6582dc5b5a83d36c531a5a42f604184a261e93aa5fae2c71c39cfb8f",
              "remote_bundle_size_bytes": 116796,
              "remote_source_count": 14,
              "knowledge_sync": "mismatch_with_local_v1.3.21"
            }
          },
          "camino_b_auditor_externo": {
            "gpt_id": "g-6a3df87bbf988191babfd1b82ed88a1f",
            "builder_model_before_change": "none",
            "builder_model_available": "GPT-5.6 Thinking",
            "published": false,
            "action_operation_count": 25,
            "action_smoke": null,
            "blocker": "browser_security_policy_persisted_after_explicit_user_revocation",
            "last_builder_retry_utc": "2026-07-12T12:53:04Z",
            "last_builder_retry_result": "read_snapshot_succeeded_then_write_controls_rejected_before_any_change"
          }
        }
      },
      "fallback_route_id": "chatgpt_gpt_5_5_plan"
    },
    "chatgpt_gpt_5_5_plan": {
      "route_id": "chatgpt_gpt_5_5_plan",
      "provider_id": "chatgpt_plan",
      "provider_name": "ChatGPT",
      "model_id": "gpt-5.5",
      "route": "chatgpt_ui_or_gpt_action",
      "interface": "interactive_plan",
      "cost_class": "plan",
      "status": "manual_or_action",
      "reserved": false,
      "agentic": true
    },
    "claude_opus_4_8_extra_plan": {
      "route_id": "claude_opus_4_8_extra_plan",
      "provider_id": "claude_plan_manual",
      "provider_name": "Claude",
      "model_id": "claude-opus-4.8-extra",
      "route": "claude_ui_or_shared_bus",
      "interface": "interactive_plan",
      "cost_class": "plan",
      "status": "manual_or_shared_bus",
      "reserved": false,
      "agentic": true
    },
    "claude_code_subscription_cli": {
      "route_id": "claude_code_subscription_cli",
      "provider_id": "claude_code_subscription",
      "provider_name": "Claude Code",
      "model_id": "opus",
      "route": "local_cli_subscription",
      "interface": "claude_cli",
      "cost_class": "included_in_plan",
      "status": "configured",
      "reserved": false,
      "agentic": true,
      "role": "final_corrector_writer_and_only_approver",
      "executor_worker": "claude_code",
      "execution_mode": "automatic_cli",
      "auth_probe": "claude auth status",
      "auth_method": "claude_subscription_oauth",
      "api_key_allowed": false,
      "model_alias": "opus",
      "fallback_model_alias": "sonnet",
      "permission_mode": "acceptEdits",
      "max_turns": 20
    },
    "codex_gpt_5_6_sol_ultra_subscription_cli": {
      "route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
      "provider_id": "codex_chatgpt_subscription",
      "provider_name": "Codex CLI (ChatGPT subscription)",
      "model_id": "gpt-5.6-sol",
      "route": "local_cli_subscription",
      "interface": "codex_cli",
      "cost_class": "included_in_chatgpt_plan",
      "status": "configured",
      "reserved": false,
      "agentic": true,
      "role": "slot_14_final_reviewer_fallback",
      "executor_worker": "codex_fallback",
      "execution_mode": "automatic_cli_fallback",
      "auth_probe": "codex login status",
      "auth_method": "chatgpt_subscription",
      "api_key_allowed": false,
      "model_reasoning_effort": "ultra",
      "process_isolation": "separate_codex_exec",
      "inherits_orchestrator_model": false,
      "self_model_switch": false,
      "fallback_only_after": "claude_code_subscription_cli_unavailable",
      "unavailable_policy": "fail_closed_operator_action_required",
      "manual_or_desktop_result_may_approve": false,
      "sandbox_mode": "workspace-write",
      "approval_policy": "never",
      "ephemeral": true
    },
    "lmstudio_qwen3_coder_30b_a3b": {
      "route_id": "lmstudio_qwen3_coder_30b_a3b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "qwen3-coder-30b-a3b-instruct",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_code_auditor_first_sweep",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_qwen25_coder_32b": {
      "route_id": "lmstudio_qwen25_coder_32b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "qwen2.5-coder-32b-instruct",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_python_precision_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_qwen25_coder_32b_abliterated": {
      "route_id": "lmstudio_qwen25_coder_32b_abliterated",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "qwen2.5-coder-32b-instruct-abliterated",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_blunt_code_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_deepseek_r1_distill_qwen_32b": {
      "route_id": "lmstudio_deepseek_r1_distill_qwen_32b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "deepseek-r1-distill-qwen-32b",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_adversarial_reasoner",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_qwq_32b": {
      "route_id": "lmstudio_qwq_32b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "qwen/qwq-32b",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_reasoning_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_qwen36_27b": {
      "route_id": "lmstudio_qwen36_27b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "qwen3.6-27b",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_swe_bench_leader_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_devstral_small_2507": {
      "route_id": "lmstudio_devstral_small_2507",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "devstral-small-2507",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_agentic_multistep_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_codestral_22b": {
      "route_id": "lmstudio_codestral_22b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "codestral-22b-v0.1",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_multilanguage_code_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_mistral_small_3_2_24b": {
      "route_id": "lmstudio_mistral_small_3_2_24b",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "mistral-small-3.2-24b-instruct-2506",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "probe_required",
      "reserved": false,
      "agentic": true,
      "role": "local_free_general_review_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "auto_allowed_when_lmstudio_available",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the RAM guard runs on the host that owns model memory."
    },
    "lmstudio_nemotron_70b_high_criticality": {
      "route_id": "lmstudio_nemotron_70b_high_criticality",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "llama-3.1-nemotron-70b-instruct-hf",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "configured_special",
      "reserved": false,
      "agentic": true,
      "role": "local_free_high_criticality_exclusive_auditor",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "heavy_exclusive",
      "active_call_policy": "manual_or_high_criticality_only_exclusive_no_other_lmstudio_models_loaded",
      "notes": "Portable LM Studio route: resolves loopback first, then bridge; the heavy tier is exclusive and the RAM guard runs on the model host."
    },
    "lmstudio_gemma_3_27b_vision_ocr": {
      "route_id": "lmstudio_gemma_3_27b_vision_ocr",
      "provider_id": "lmstudio_macbook_bridge",
      "provider_name": "LM Studio MacBook Thunderbolt Bridge",
      "model_id": "gemma-3-27b-it",
      "route": "lmstudio_openai_compatible",
      "interface": "openai_compatible",
      "cost_class": "local_free",
      "status": "configured_special",
      "reserved": false,
      "agentic": false,
      "role": "local_free_vision_ocr_specialist",
      "base_url_source": "config/host_runtime.policy.json",
      "api_key_env": "LMSTUDIO_API_KEY",
      "api_key_fallback_literal": "lm-studio",
      "transport": "auto_loopback_or_guarded_ssh_peer",
      "ram_tier": "medium",
      "active_call_policy": "vision_or_ocr_only_not_general_code_review",
      "notes": "Portable LM Studio vision route; use only for image/OCR evidence and run the RAM guard on the model host."
    }
  }
}
```

## SOURCE: canon/CANON_WORKFLOW_SLOTS.v1.json

```json
{
  "schema_version": "canon_workflow_slots.v1",
  "canon_version": "camino_shared_canon.v1.3.21-slot14-handoff",
  "updated_utc": "2026-07-11T00:00:00Z",
  "big_loop": {
    "name": "bucle_grande",
    "slots": [
      1,
      2,
      3,
      4,
      5,
      6,
      7,
      8,
      9,
      10,
      11,
      12,
      13,
      14
    ]
  },
  "cycles": {
    "A": [
      1,
      2,
      3
    ],
    "B": [
      4,
      5,
      6
    ],
    "C": [
      7,
      8,
      9,
      10
    ],
    "FINAL": [
      11,
      12,
      13,
      14
    ]
  },
  "general_rules": {
    "without_corrections": "advance_to_next_slot",
    "with_corrections": "apply_slot_correction_policy",
    "loop_limit_reached": "advance_with_explicit_residual_debt",
    "approval": "slot_14_claude_or_codex_subscription_fallback_only_without_corrections_or_findings",
    "agentic_internal_loop": "audit_patch_reaudit_repeat",
    "internal_loop_contract": "COMUN_CAMINO_A_Y_B: todo auditor IA con bucle interno obligatorio (slots 1, 4, 7, 8) debe iterar versiones .001 a .010: genera versión, la reaudita, genera la siguiente; secuencia obligatoria por iteración: auditar -> detectar bug/mejora/deuda -> corregir o reescribir -> testear/validar -> reauditar la corrección -> decidir si queda limpio dentro del alcance del slot. Termina al no encontrar nuevos hallazgos en su alcance o al llegar a .010. Entrega: última versión, diff acumulado, historial de iteraciones, tests, deuda residual, veredicto de ronda. El veredicto de ronda nunca es aprobación global.",
    "external_slot_loops": "COMUN_CAMINO_A_Y_B: slots 3, 6, 10, 11, 12, 13, 14 iteran por bucle de slot con conteo definido en el campo 'loops' de cada slot; no usan el bucle interno .001-.010.",
    "lmstudio_bridge_rules": {
      "provider_id": "lmstudio_macbook_bridge",
      "base_url_source": "config/host_runtime.policy.json",
      "interface": "openai_compatible",
      "api_key": "literal_lm-studio_or_LMSTUDIO_API_KEY",
      "model_ram_guard_must_run_on_lmstudio_host": true,
      "tier1_slot": "1",
      "tier2_slot": "4",
      "medium_concurrency_limit": 2,
      "heavy_exclusive_route": "lmstudio_nemotron_70b_high_criticality",
      "heavy_exclusive_policy": "not_in_general_slots; run one at a time only when explicitly selected for high criticality",
      "vision_route": "lmstudio_gemma_3_27b_vision_ocr",
      "vision_policy": "not_general_code_review; use only for images/OCR evidence",
      "availability_check": "GET /v1/models before dispatch; no invented model IDs"
    },
    "local_paid_duplicate_policy": {
      "rule": "local_free LM Studio routes have priority only over exact or substantially equivalent paid routes",
      "same_family_is_not_duplicate": true,
      "material_capacity_difference_keeps_both": true,
      "qwen_480b_rule": "deepinfra_qwen3_coder_480b remains active because Qwen 480B is materially different from local Qwen 30B/32B",
      "functional_paid_duplicates_excluded": {
        "blackbox_devstral_2": "lmstudio_devstral_small_2507"
      },
      "scope": "automatic slots only; route records remain in canon for traceability/manual future authorization"
    }
  },
  "legacy_runtime_aliases": {
    "1": "1",
    "3": "4",
    "4": "6",
    "5": "7.consolidator",
    "6": "7.writer",
    "7": "8",
    "8": "10_11.support",
    "9": "10_11.mimo",
    "10": "12",
    "11": "16.minimax",
    "12": "16.kimi",
    "13": "13_14",
    "14": "reserved_claude"
  },
  "slots": {
    "1": {
      "cycle": "A",
      "role": "parallel_initial_auditors",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [
        "gemini_aistudio_3_5_flash",
        "vertex_gemini_2_5_pro",
        "deepseek_v4_flash",
        "blackbox_grok_code_fast_free",
        "blackbox_minimax_m2_5_free",
        "openrouter_qwen_coder_free",
        "openrouter_nemotron_free",
        "openrouter_gpt_oss_120b_free",
        "openrouter_llama_33_70b_free",
        "openrouter_gemma_4_31b_free",
        "openrouter_gemma_4_26b_free",
        "openrouter_nemotron_nano_omni_30b_free",
        "openrouter_nex_n2_pro_free",
        "openrouter_laguna_m1_free",
        "nvidia_nemotron_ultra_direct",
        "groq_gpt_oss_120b",
        "groq_llama_33_70b",
        "groq_qwen3_32b",
        "lmstudio_qwen3_coder_30b_a3b",
        "lmstudio_qwen25_coder_32b",
        "lmstudio_qwen25_coder_32b_abliterated",
        "lmstudio_deepseek_r1_distill_qwen_32b",
        "lmstudio_qwq_32b",
        "lmstudio_qwen36_27b"
      ],
      "special": {
        "openrouter": "run_all_allowlisted_suffix_free_no_paid_fallback",
        "nemotron_race": [
          "nvidia_nemotron_ultra_direct",
          "openrouter_nemotron_free"
        ],
        "nemotron_first_valid_wins": true,
        "lmstudio_free_local_batch": {
          "routes": [
            "lmstudio_qwen3_coder_30b_a3b",
            "lmstudio_qwen25_coder_32b",
            "lmstudio_qwen25_coder_32b_abliterated",
            "lmstudio_deepseek_r1_distill_qwen_32b",
            "lmstudio_qwq_32b",
            "lmstudio_qwen36_27b"
          ],
          "endpoint_source": "config/host_runtime.policy.json",
          "requires_lmstudio_listen_on_all_interfaces": true,
          "medium_model_concurrency_limit": 2,
          "never_parallelize_with_heavy_exclusive": true,
          "on_connection_refused": "skip_explicit_no_consta_do_not_fail_silently"
        }
      },
      "internal_loop": {
        "required": true,
        "loop_type": "internal_agentic",
        "max_iterations": 10,
        "version_suffixes": "candidate.001 hasta candidate.010",
        "mandatory_sequence": [
          "auditar",
          "detectar bug/mejora/deuda",
          "corregir o reescribir",
          "testear / validar",
          "reauditar la corrección",
          "decidir si queda limpio dentro del alcance del slot"
        ],
        "iteration_rule": "la IA genera versión .001, la reaudita, genera .002, la reaudita, y así sucesivamente hasta quedar limpia dentro de su alcance o llegar a .010",
        "stop_conditions": [
          "sin nuevos hallazgos dentro del alcance del slot",
          "alcanzada la iteración .010"
        ],
        "delivery_requirements": [
          "última versión corregida",
          "diff acumulado",
          "historial de iteraciones (.001 a .NNN)",
          "tests sugeridos o ejecutados",
          "deuda residual explícita",
          "veredicto de ronda (sin aprobación global)"
        ]
      }
    },
    "2": {
      "cycle": "A",
      "role": "manual_harvest",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [],
      "internal_loop": {
        "required": false,
        "loop_type": "none"
      }
    },
    "3": {
      "cycle": "A",
      "role": "consolidator_and_writer",
      "loops": 5,
      "correction_policy": "BLOCKING_WITHIN_LIMIT",
      "routes": [
        "chatgpt_gpt_5_6_sol_actions_plan"
      ],
      "fallback_chain": [
        "chatgpt_gpt_5_5_plan"
      ],
      "special": {
        "brain_stage": "primary_consolidation"
      },
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    },
    "4": {
      "cycle": "B",
      "role": "intermediate_parallel_auditors",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [
        "deepseek_v4_pro",
        "vertex_gemini_3_1_pro",
        "blackbox_minimax_m2_5_free",
        "blackbox_trinity_large_thinking",
        "deepinfra_qwen3_coder_480b",
        "lmstudio_devstral_small_2507",
        "lmstudio_codestral_22b",
        "lmstudio_mistral_small_3_2_24b"
      ],
      "special": {
        "blackbox_nemotron_enters_only_without_free_winner": "blackbox_nemotron_ultra_paid",
        "lmstudio_local_intermediate_batch": {
          "routes": [
            "lmstudio_devstral_small_2507",
            "lmstudio_codestral_22b",
            "lmstudio_mistral_small_3_2_24b"
          ],
          "medium_model_concurrency_limit": 2,
          "on_connection_refused": "skip_explicit_no_consta_do_not_fail_silently"
        },
        "paid_duplicate_local_priority": {
          "excluded_paid_routes": {
            "blackbox_devstral_2": "lmstudio_devstral_small_2507"
          },
          "not_excluded_distinct_capacity": {
            "deepinfra_qwen3_coder_480b": "Qwen3 Coder 480B remains active; local Qwen 30B/32B are different-capacity models"
          },
          "rule": "local route only excludes a paid route when model/capability is substantially equivalent; same family alone is insufficient",
          "manual_override": "requires explicit user authorization and canon change"
        }
      },
      "internal_loop": {
        "required": true,
        "loop_type": "internal_agentic",
        "max_iterations": 10,
        "version_suffixes": "candidate.001 hasta candidate.010",
        "mandatory_sequence": [
          "auditar",
          "detectar bug/mejora/deuda",
          "corregir o reescribir",
          "testear / validar",
          "reauditar la corrección",
          "decidir si queda limpio dentro del alcance del slot"
        ],
        "iteration_rule": "la IA genera versión .001, la reaudita, genera .002, la reaudita, y así sucesivamente hasta quedar limpia dentro de su alcance o llegar a .010",
        "stop_conditions": [
          "sin nuevos hallazgos dentro del alcance del slot",
          "alcanzada la iteración .010"
        ],
        "delivery_requirements": [
          "última versión corregida",
          "diff acumulado",
          "historial de iteraciones (.001 a .NNN)",
          "tests sugeridos o ejecutados",
          "deuda residual explícita",
          "veredicto de ronda (sin aprobación global)"
        ]
      }
    },
    "5": {
      "cycle": "B",
      "role": "consolidator",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [
        "deepseek_v4_pro"
      ],
      "internal_loop": {
        "required": false,
        "loop_type": "none"
      }
    },
    "6": {
      "cycle": "B",
      "role": "writer",
      "loops": 3,
      "correction_policy": "BLOCKING_WITHIN_LIMIT",
      "routes": [
        "chatgpt_gpt_5_6_sol_actions_plan"
      ],
      "fallback_chain": [
        "chatgpt_gpt_5_5_plan"
      ],
      "special": {
        "brain_stage": "code_generation"
      },
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    },
    "7": {
      "cycle": "C",
      "role": "glm_gate",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [
        "zai_glm_5_1"
      ],
      "fallback_chain": [
        "lmstudio_qwen3_coder_30b_a3b",
        "chatgpt_gpt_5_6_sol_actions_plan",
        "chatgpt_gpt_5_5_plan"
      ],
      "special": {
        "brain_stage": "post_code_review",
        "provider_circuit_breaker": {
          "provider_id": "zai_glm",
          "trip_on": [
            "subscription_credit_exhausted",
            "quota_limited",
            "payment_required",
            "http_402",
            "http_429"
          ],
          "scope": "run",
          "skip_remaining_provider_routes": true
        },
        "fallback_policy": "first_enabled_independent_free_or_plan_route"
      },
      "internal_loop": {
        "required": true,
        "loop_type": "internal_agentic",
        "max_iterations": 10,
        "version_suffixes": "candidate.001 hasta candidate.010",
        "mandatory_sequence": [
          "auditar",
          "detectar bug/mejora/deuda",
          "corregir o reescribir",
          "testear / validar",
          "reauditar la corrección",
          "decidir si queda limpio dentro del alcance del slot"
        ],
        "iteration_rule": "la IA genera versión .001, la reaudita, genera .002, la reaudita, y así sucesivamente hasta quedar limpia dentro de su alcance o llegar a .010",
        "stop_conditions": [
          "sin nuevos hallazgos dentro del alcance del slot",
          "alcanzada la iteración .010"
        ],
        "delivery_requirements": [
          "última versión corregida",
          "diff acumulado",
          "historial de iteraciones (.001 a .NNN)",
          "tests sugeridos o ejecutados",
          "deuda residual explícita",
          "veredicto de ronda (sin aprobación global)"
        ]
      }
    },
    "8": {
      "cycle": "C",
      "role": "agentic_support_auditors",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [
        "deepinfra_minimax_m2_7",
        "deepinfra_qwen3_coder_480b",
        "lmstudio_qwen3_coder_30b_a3b",
        "lmstudio_qwen25_coder_32b",
        "lmstudio_devstral_small_2507"
      ],
      "internal_loop": {
        "required": true,
        "loop_type": "internal_agentic",
        "max_iterations": 10,
        "version_suffixes": "candidate.001 hasta candidate.010",
        "mandatory_sequence": [
          "auditar",
          "detectar bug/mejora/deuda",
          "corregir o reescribir",
          "testear / validar",
          "reauditar la corrección",
          "decidir si queda limpio dentro del alcance del slot"
        ],
        "iteration_rule": "la IA genera versión .001, la reaudita, genera .002, la reaudita, y así sucesivamente hasta quedar limpia dentro de su alcance o llegar a .010",
        "stop_conditions": [
          "sin nuevos hallazgos dentro del alcance del slot",
          "alcanzada la iteración .010"
        ],
        "delivery_requirements": [
          "última versión corregida",
          "diff acumulado",
          "historial de iteraciones (.001 a .NNN)",
          "tests sugeridos o ejecutados",
          "deuda residual explícita",
          "veredicto de ronda (sin aprobación global)"
        ]
      },
      "special": {
        "paid_duplicate_local_priority": {
          "excluded_paid_routes": {
            "blackbox_devstral_2": "lmstudio_devstral_small_2507"
          },
          "not_excluded_distinct_capacity": {
            "deepinfra_qwen3_coder_480b": "Qwen3 Coder 480B remains active; local Qwen 30B/32B are different-capacity models"
          },
          "rule": "local route only excludes a paid route when model/capability is substantially equivalent; same family alone is insufficient",
          "manual_override": "requires explicit user authorization and canon change"
        }
      }
    },
    "9": {
      "cycle": "C",
      "role": "agentic_consolidator",
      "loops": null,
      "correction_policy": "NO_BLOQUEA",
      "routes": [
        "xiaomi_mimo_token_plan_agentic"
      ],
      "fallback_chain": [
        "xiaomi_mimo_payg_agentic",
        "deepinfra_mimo_manual"
      ],
      "internal_loop": {
        "required": false,
        "loop_type": "none"
      }
    },
    "10": {
      "cycle": "C",
      "role": "gpt_writer",
      "loops": 3,
      "correction_policy": "BLOCKING_WITHIN_LIMIT",
      "routes": [
        "chatgpt_gpt_5_6_sol_actions_plan"
      ],
      "fallback_chain": [
        "chatgpt_gpt_5_5_plan"
      ],
      "special": {
        "brain_stage": "code_generation"
      },
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    },
    "11": {
      "cycle": "FINAL",
      "role": "minimax_corrector_writer",
      "loops": 4,
      "correction_policy": "BLOCKING_WITHIN_LIMIT",
      "routes": [
        "deepinfra_minimax_m2_7"
      ],
      "fallback_chain": [
        "deepinfra_minimax_m2_5"
      ],
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    },
    "12": {
      "cycle": "FINAL",
      "role": "kimi_corrector_writer",
      "loops": 4,
      "correction_policy": "BLOCKING_WITHIN_LIMIT",
      "routes": [
        "deepinfra_kimi_k2_7_code"
      ],
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    },
    "13": {
      "cycle": "FINAL",
      "role": "glm_corrector_writer",
      "loops": 4,
      "correction_policy": "BLOCKING_WITHIN_LIMIT",
      "routes": [
        "zai_glm_5_2"
      ],
      "request_rule": "one_request_per_slot_with_internal_fallbacks",
      "fallback_chain": [
        "lmstudio_qwen3_coder_30b_a3b",
        "chatgpt_gpt_5_6_sol_actions_plan",
        "chatgpt_gpt_5_5_plan"
      ],
      "special": {
        "brain_stage": "closure",
        "provider_circuit_breaker": {
          "provider_id": "zai_glm",
          "trip_on": [
            "subscription_credit_exhausted",
            "quota_limited",
            "payment_required",
            "http_402",
            "http_429"
          ],
          "scope": "run",
          "skip_remaining_provider_routes": true
        },
        "fallback_policy": "first_enabled_independent_free_or_plan_route",
        "paid_fallbacks_authorized": false
      },
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    },
    "14": {
      "cycle": "FINAL",
      "role": "final_corrector_writer_and_only_approver",
      "loops": 3,
      "correction_policy": "RESTART_BIG_LOOP_IF_CORRECTED_WITHIN_LIMIT",
      "routes": [
        "claude_code_subscription_cli"
      ],
      "fallback_chain": [
        "codex_gpt_5_6_sol_ultra_subscription_cli"
      ],
      "executor_worker": "claude_code",
      "execution_mode": "automatic_cli",
      "approval_contract": {
        "verdict": "APPROVED_BY_CLAUDE_OR_CODEX_SUBSCRIPTION_FALLBACK",
        "primary_verdict": "APPROVED_BY_CLAUDE",
        "fallback_verdict": "APPROVED_BY_CODEX_FALLBACK",
        "fallback_route_id": "codex_gpt_5_6_sol_ultra_subscription_cli",
        "fallback_requires_primary_unavailable": true,
        "requires_slot_id": "14",
        "requires_no_corrections": true,
        "requires_no_findings": true,
        "requires_current_candidate_sha256": true,
        "requires_prior_slots_complete": true,
        "corrections_action": "restart_big_loop"
      },
      "terminal_if_no_corrections": "APPROVED_BY_CLAUDE_OR_CODEX_SUBSCRIPTION_FALLBACK",
      "internal_loop": {
        "required": false,
        "loop_type": "external_slot_loop",
        "note": "este slot itera por bucle de slot (campo 'loops'), no por bucle interno .001-.010"
      }
    }
  }
}
```

## SOURCE: canon/CANON_RUNTIME_POLICY.v1.json

```json
{
  "schema_version": "canon_runtime_policy.v1",
  "canon_version": "camino_shared_canon.v1.3.21-slot14-handoff",
  "updated_utc": "2026-07-11T00:00:00Z",
  "default_profile": "with_claude",
  "profiles": {
    "with_claude": {
      "description": "Claude participa como worker/slot manual o Claude Code si está disponible; nunca por API prohibida.",
      "claude_enabled": true,
      "final_without_claude": false,
      "terminal_without_claude_reason": null,
      "enabled_workers": [
        "local_static",
        "codex",
        "gateway",
        "claude_code",
        "codex_fallback",
        "manual_gpt",
        "manual_claude",
        "lmstudio_bridge"
      ],
      "required_final_review": "claude_or_manual_final_slot_when_available",
      "terminal_if_claude_missing": "waiting_manual_claude_final_review",
      "auto_execute_workers": false,
      "require_gpt_brain_evidence": true
    },
    "without_claude": {
      "description": "Perfil sin Claude: Codex gpt-5.6-sol ultra por suscripción ocupa el fallback del slot 14; nunca usa OpenAI API.",
      "claude_enabled": false,
      "final_without_claude": true,
      "terminal_without_claude_reason": "ready_for_human_final_review",
      "enabled_workers": [
        "local_static",
        "codex",
        "gateway",
        "manual_gpt",
        "codex_fallback",
        "lmstudio_bridge"
      ],
      "disabled_workers": [
        "claude_code",
        "manual_claude"
      ],
      "required_final_review": "codex_subscription_fallback_or_human_final_review",
      "auto_execute_workers": false,
      "require_gpt_brain_evidence": true
    },
    "sandbox_reference": {
      "description": "Smoke mecánico explícito: sólo auditor estático local, sin Claude y sin pretender evidencia del GPT cerebro.",
      "claude_enabled": false,
      "final_without_claude": true,
      "terminal_without_claude_reason": "reference_smoke_complete",
      "enabled_workers": [
        "local_static"
      ],
      "disabled_workers": [
        "codex",
        "gateway",
        "claude_code",
        "codex_fallback",
        "manual_gpt",
        "manual_claude",
        "lmstudio_bridge"
      ],
      "required_final_review": "mechanical_smoke_only",
      "auto_execute_workers": true,
      "require_gpt_brain_evidence": false
    }
  },
  "api_policy": {
    "forbidden_api_providers": [
      "anthropic_api",
      "claude_api",
      "openai_api"
    ],
    "forbidden_env_vars_for_workers": [
      "ANTHROPIC_API_KEY",
      "OPENAI_API_KEY"
    ],
    "allow_paid_credit": false,
    "default_deny": true,
    "lmstudio_bridge": {
      "allowed": true,
      "provider_id": "lmstudio_macbook_bridge",
      "api_key_is_not_secret_when_literal_lm_studio": true,
      "forbidden_to_use_openai_api": true,
      "forbidden_to_use_claude_api": true
    }
  },
  "heartbeat_policy": {
    "heartbeat_interval_seconds": 600,
    "heartbeat_grace_seconds": 1800,
    "long_run_probe_every_minutes": 30,
    "fallout_if_no_progress_minutes": 180,
    "fallout_if_no_heartbeat_minutes": 60,
    "manual_harvest_window_minutes": 720,
    "late_manual_audit_policy": "reject_if_candidate_sha_mismatch"
  },
  "slot_defaults": {
    "slot_budget_hours": 8,
    "max_internal_loops": 3,
    "strict_loop_limit": true,
    "advance_with_explicit_residual_debt": true
  },
  "worker_limits": {
    "codex": {
      "max_cycles": 3,
      "timeout_minutes": 120,
      "gate_required": false
    },
    "gateway": {
      "max_cycles": 1,
      "timeout_minutes": 180,
      "gate_required": false
    },
    "claude_code": {
      "max_cycles": 1,
      "timeout_minutes": 45,
      "gate_required": false,
      "allow_api_credits": false,
      "allow_anthropic_api_key": false
    },
    "codex_fallback": {
      "max_cycles": 1,
      "timeout_minutes": 60,
      "gate_required": false,
      "allow_openai_api_key": false,
      "subscription_auth_only": true,
      "fallback_only_after_claude_unavailable": true
    },
    "manual_gpt": {
      "max_cycles": 1,
      "timeout_minutes": 720,
      "gate_required": false
    },
    "manual_claude": {
      "max_cycles": 1,
      "timeout_minutes": 720,
      "gate_required": false
    },
    "lmstudio_bridge": {
      "max_concurrent_medium_models": 2,
      "max_concurrent_heavy_models": 1,
      "heavy_is_exclusive": true,
      "timeout_minutes": 180,
      "heartbeat_minutes": 10,
      "base_url_source": "config/host_runtime.policy.json",
      "connection_refused_status": "lmstudio_unavailable_connection_refused",
      "do_not_treat_unavailable_as_model_failure": true
    }
  },
  "terminal_policy": {
    "require_accepted_evidence": true,
    "reject_stale_candidate": true,
    "allow_without_claude_terminal_state": "ready_for_human_final_review",
    "allow_with_claude_missing_terminal_state": "waiting_manual_claude_final_review",
    "only_slot_14_can_approve_when_claude_enabled": true,
    "slot_14_subscription_approval_order": [
      "claude_code",
      "codex_fallback"
    ],
    "minimum_valid_evidence_workers": [
      "local_static",
      "codex",
      "gateway",
      "manual_gpt",
      "manual_claude",
      "claude_code",
      "codex_fallback"
    ]
  }
}
```

## SOURCE: canon/CANON_PREAUDIT_DELIVERY.v1.json

```json
{
 "schema_version": "canon_preaudit_delivery.v1",
 "canon_version": "camino_shared_canon.v1.3.21-slot14-handoff",
 "updated_utc": "2026-07-11T00:00:00Z",
 "applies_to": ["camino_a", "camino_b"],
 "scope_note": "COMUN_CAMINO_A_Y_B: este contrato rige la entrega de preauditoría en ambos caminos. Cualquier modificación en (1) sistema de slots, (2) pedido/sistema de preauditoría, o (3) proceso de bucles, debe reflejarse simultáneamente en ambos caminos. Ningún GPT debe interpretar este archivo como exclusivo de su camino.",
 "deliverables": {
  "1_zip_limpio": {
   "definition": "sin archivos de auditorías viejas ni innecesarios; solo lo mínimo indispensable de la última versión; criterio minimalista: nada puede faltar, nada puede sobrar",
   "1_1_zip_plano": {
    "description": "zip plano sin carpetas ni directorios; nombres aplanados",
    "ideal_max_files": 10,
    "hard_max_files": 50,
    "on_exceed_hard_max": "avisar al operador humano y preguntar si igual lo quiere; si no lo quiere, entregar solo el zip 1.2",
    "flatten_separator": "__"
   },
   "1_2_zip_con_subcarpetas": {
    "description": "zip con estructura de subcarpetas si existen; mismo criterio minimalista; sin máximo de archivos",
    "skip_condition": "si no hay subcarpetas y hay 50 archivos o menos, no se entrega porque sería idéntico al 1.1"
   },
   "1_3_hilo_copiar_pegar": {
    "description": "texto listo para copiar y pegar con el pedido de auditoría completo"
   }
  },
  "2_contexto_minimo": "CONTEXTO_MINIMO_AUDITORIA.md",
  "3_manifest_minimo": "MANIFEST_MINIMO_AUDITORIA.json",
  "4_pedido_auditorias": "PEDIDO_AUDITORIAS_MANUALES.md",
  "5_changelog": "CHANGELOG_CORRECCION_AUDITORIA.md",
  "6_pedido_copiar_pegar": "PEDIDO_COPIAR_PEGAR.md (mismo contenido que 1.3, como archivo)",
  "7_zip_plano_o_semiplano": "cubierto por 1.1/1.2 según reglas de conteo y estructura",
  "8_manifest_sha256": "manifest con SHA-256 actualizado de cada archivo incluido",
  "9_lista_incluidos_excluidos": "INCLUIDOS_EXCLUIDOS.md con cada archivo incluido y cada regla/archivo excluido con motivo",
  "10_instrucciones_multiagente": "INSTRUCCIONES_MULTIAGENTE.md generado según multiagent_policy"
 },
 "multiagent_policy": {
  "description": "el preauditor decide la cantidad de agentes por auditoría priorizando máxima eficiencia, según el tipo de auditoría y el estado de los benchmarks de eficiencia multirol de los últimos 3 meses",
  "benchmark_snapshot": {
   "snapshot_utc": "2026-07-05",
   "consensus": "4 roles de multiagente es bastante eficiente para auditorías generales",
   "review_required_every_days": 90,
   "review_rule": "el preauditor debe revisar benchmarks vigentes antes de asignar roles; si el snapshot tiene más de 90 días, la revisión es obligatoria y este archivo debe actualizarse"
  },
  "default_agents": 4,
  "max_parallel_agents": 12,
  "one_role_per_agent": true,
  "role_catalog": [
   {"role_id": "canon_slots_providers", "name": "Canon / slots / providers"},
   {"role_id": "runtime_python", "name": "Runtime Python"},
   {"role_id": "seguridad_io", "name": "Seguridad IO / manifests / hashes / secrets"},
   {"role_id": "packaging_preaudit", "name": "Packaging / preauditoría limpia"},
   {"role_id": "gateway_archivos_grandes", "name": "Gateway / archivos grandes / chunks"},
   {"role_id": "bucles_cierre", "name": "Bucles / cierre / aprobación"},
   {"role_id": "adversarial_general", "name": "Auditor adversarial general"},
   {"role_id": "estado_persistencia", "name": "Estado / SQLite / persistencia"},
   {"role_id": "contratos_prompts", "name": "Contratos / prompts generados / consistencia documental"},
   {"role_id": "costos_presupuesto", "name": "Costos / presupuesto / cost_class"},
   {"role_id": "concurrencia_procesos", "name": "Concurrencia / procesos / locks"},
   {"role_id": "esquemas_validacion", "name": "Esquemas JSON / validación de datos"}
  ],
  "per_agent_instruction_fields": [
   "rol",
   "alcance",
   "archivos prioritarios",
   "preguntas específicas",
   "formato de salida común",
   "reglas de bucle interno"
  ],
  "assignment_rule": "asignar exactamente un rol del catálogo a cada agente; nunca exceder max_parallel_agents; con auditoría acotada usar menos agentes; con auditoría de sistema completo escalar hasta lo que el tipo de auditoría justifique"
 },
 "internal_loop_contract_ref": {
  "source_of_truth": "canon/CANON_WORKFLOW_SLOTS.v1.json -> general_rules.internal_loop_contract",
  "summary": "slots 1, 4, 7, 8: bucle interno obligatorio .001-.010 (auditar -> detectar -> corregir -> testear -> reauditar -> decidir); slots 3, 6, 10, 11, 12, 13, 14: bucle de slot con conteo en campo 'loops'; toda IA externa manual también itera .001-.010 según PEDIDO_AUDITORIAS_MANUALES.md"
 }
}
```

## SOURCE: config/roles.json

```json
{
  "schema_version": "2.0",
  "brain_current": "gpt_manual_or_configured",
  "authority": {
    "state_engine": "overnight_master",
    "state_engine_is_brain": false,
    "master": "overnight_master",
    "master_is_brain": false,
    "workers_are_judges": false,
    "global_approval_allowed": false
  },
  "paths": {
    "camino_a": {
      "brain": "gpt_manual_or_configured",
      "logical_orchestrator": "codex",
      "orchestrator_model_policy": {
        "selection_mode": "operator_selected",
        "model_tier_preference": "low",
        "reasoning_preference": "low",
        "cost_preference": "low",
        "fixed_model_id": null,
        "self_model_switch_for_slot_14": false
      },
      "slot_14_reviewer_process": "independent_codex_cli",
      "state_authority": "overnight_master",
      "transport": "gateway_and_drive_bus",
      "gpt_must_supply_decision_evidence": true
    },
    "camino_b": {
      "brain": "gpt_manual_or_configured",
      "logical_orchestrator": "gpt_manual_or_configured",
      "orchestrator_model_policy": {
        "selection_mode": "gpt_desktop",
        "reasoning_level": "high",
        "fixed_model_id": null,
        "self_model_switch_for_slot_14": false
      },
      "slot_14_reviewer_process": "independent_codex_cli",
      "state_authority": "camino_b_gateway",
      "transport": "gateway",
      "gpt_must_supply_decision_evidence": true
    }
  },
  "workers": {
    "codex": {
      "enabled": true,
      "max_cycles": 3,
      "workspace_isolated": true,
      "may_edit_workspace": true,
      "may_edit_main": false
    },
    "claude_code": {
      "enabled": true,
      "max_passes_per_run": 1,
      "timeout_minutes": 45,
      "max_input_chars": 25000,
      "allow_anthropic_api_key": false,
      "allow_api_credits": false,
      "workspace_isolated": true,
      "may_edit_main": false
    },
    "codex_fallback": {
      "enabled": true,
      "slot_id": "14",
      "fallback_only": true,
      "model_id": "gpt-5.6-sol",
      "model_reasoning_effort": "ultra",
      "process_isolation": "separate_codex_exec",
      "inherits_orchestrator_model": false,
      "self_model_switch": false,
      "unavailable_policy": "fail_closed_operator_action_required",
      "manual_or_desktop_result_may_approve": false,
      "auth_method": "chatgpt_subscription",
      "allow_openai_api_key": false,
      "workspace_isolated": true,
      "may_edit_main": false
    },
    "gateway": {
      "enabled": true,
      "forbidden_providers": [
        "openai_api",
        "anthropic_api",
        "claude_api"
      ],
      "require_probe_before_gate": true
    },
    "manual_gpt": {
      "enabled": true,
      "manual_only": true
    },
    "manual_claude": {
      "enabled": true,
      "manual_only": true
    }
  },
  "retry_policy": {
    "transient_max_retries": 2,
    "quota_max_retries": 0,
    "auth_max_retries": 0,
    "contract_error_max_retries": 0,
    "worker_timeout_max_retries": 1
  },
  "terminal_policy": {
    "require_no_canonical_pending_jobs": true,
    "require_no_incomplete_out_bundles": true,
    "require_no_live_child_processes": true,
    "require_final_zip_manifest": true
  }
}
```

## SOURCE: config/path_roles.json

```json
{
  "schema_version": "camino_path_roles.v1",
  "brain": "gpt_manual_or_configured",
  "paths": {
    "camino_a": {
      "logical_orchestrator": "codex",
      "orchestrator_model_policy": {
        "selection_mode": "operator_selected",
        "model_tier_preference": "low",
        "reasoning_preference": "low",
        "cost_preference": "low",
        "fixed_model_id": null,
        "self_model_switch_for_slot_14": false
      },
      "slot_14_reviewer_process": "independent_codex_cli",
      "mechanical_state_engine": "overnight_master",
      "brain_decides_content": true,
      "codex_coordinates_execution": true,
      "gateway_is_transport_only": true
    },
    "camino_b": {
      "logical_orchestrator": "gpt_manual_or_configured",
      "orchestrator_model_policy": {
        "selection_mode": "gpt_desktop",
        "reasoning_level": "high",
        "fixed_model_id": null,
        "self_model_switch_for_slot_14": false
      },
      "slot_14_reviewer_process": "independent_codex_cli",
      "mechanical_state_engine": "camino_b_gateway",
      "brain_decides_content": true,
      "gpt_coordinates_execution": true,
      "gateway_is_transport_only": true
    }
  },
  "invariants": {
    "state_engine_is_not_brain": true,
    "provider_is_not_brain": true,
    "no_synthetic_gpt_evidence": true,
    "only_slot_14_clean_subscription_reviewer_may_approve": true,
    "slot_14_primary": "claude_code_subscription_cli",
    "slot_14_fallback": "codex_gpt_5_6_sol_ultra_subscription_cli",
    "slot_14_fallback_requires_primary_unavailable": true,
    "slot_14_fallback_process_isolation": "separate_codex_exec",
    "slot_14_fallback_inherits_orchestrator_model": false,
    "slot_14_self_model_switch": false,
    "slot_14_unavailable_policy": "fail_closed_operator_action_required"
  }
}
```

## SOURCE: config/host_runtime.policy.json

```json
{
  "schema_version": "camino_host_runtime_policy.v1",
  "host_detection": {
    "role_env": "CAMINO_HOST_ROLE",
    "allowed_roles": [
      "auto",
      "imac",
      "macbook",
      "generic"
    ]
  },
  "lmstudio": {
    "base_url_env": "LMSTUDIO_BASE_URL",
    "loopback_urls_env": "LMSTUDIO_LOOPBACK_URLS",
    "bridge_urls_env": "LMSTUDIO_BRIDGE_URLS",
    "loopback_urls": [
      "http://127.0.0.1:1234/v1",
      "http://localhost:1234/v1"
    ],
    "bridge_urls": [
      "http://10.0.0.1:1234/v1"
    ],
    "models_path": "/models",
    "api_key_env": "LMSTUDIO_API_KEY",
    "api_key_fallback_literal": "lm-studio",
    "probe_timeout_seconds": 2.0,
    "request_timeout_seconds": 180,
    "request_ttl_seconds": 1800,
    "max_parallel_requests": 2,
    "require_authoritative_memory_guard": true
  },
  "drive": {
    "root_env": "CAMINO_DRIVE_BUS_ROOT",
    "root_default": "",
    "auto_discover": true,
    "drive_policy_path": "config/drive.policy.json",
    "require_existing": false,
    "require_writable": false
  },
  "peer": {
    "enabled_env": "CAMINO_PEER_ENABLED",
    "url_env": "CAMINO_PEER_URL",
    "ssh_host_env": "CAMINO_PEER_SSH_HOST",
    "ssh_identity_file_env": "CAMINO_PEER_SSH_IDENTITY",
    "remote_root_env": "CAMINO_PEER_REMOTE_ROOT",
    "remote_root_default": ".camino/peer-runtime",
    "python_env": "CAMINO_PEER_PYTHON",
    "python_default": "python3",
    "role_env": "CAMINO_PEER_ROLE",
    "default_enabled": true,
    "transport": "ssh",
    "connect_timeout_seconds": 5,
    "command_timeout_seconds": 900,
    "bootstrap_max_file_bytes": 10485760,
    "snapshot_max_file_bytes": 52428800,
    "snapshot_max_files": 20000,
    "ssh_hosts_by_local_role": {
      "macbook": "mariano@10.0.0.2",
      "imac": "mariano@10.0.0.1"
    },
    "peer_roles_by_local_role": {
      "macbook": "imac",
      "imac": "macbook"
    },
    "ssh_identity_files_by_local_role": {
      "macbook": "~/.ssh/id_ed25519_camino",
      "imac": "~/.ssh/id_ed25519_camino"
    }
  },
  "resource_scheduler": {
    "state_dir_env": "CAMINO_RESOURCE_STATE_DIR",
    "state_dir_default": "~/.camino/runtime",
    "database_name": "lmstudio_resource_reservations.sqlite",
    "minimum_headroom_bytes": 8589934592,
    "minimum_headroom_fraction": 0.15,
    "critical_available_fraction": 0.08,
    "warning_available_fraction": 0.15,
    "deny_pressure_levels": [
      "critical"
    ],
    "max_concurrent_medium": 2,
    "max_concurrent_heavy": 1,
    "heavy_is_exclusive": true,
    "reservation_ttl_seconds": 1800,
    "heartbeat_interval_seconds": 30,
    "poll_interval_seconds": 1.0,
    "default_wait_seconds": 0,
    "estimated_peak_bytes_by_tier": {
      "medium": 21474836480,
      "heavy": 60129542144,
      "heavy_exclusive": 60129542144
    }
  }
}
```

## SOURCE: config/drive.policy.json

```json
{
  "schema_version": "camino_a_drive_policy.v1",
  "purpose": "Locate a shared artifact bus without embedding either Mac's home path in canon.",
  "override_precedence": [
    "CAMINO_DRIVE_BUS_ROOT",
    "CAMINO_SHARED_ROOT",
    "macos_google_drive_discovery"
  ],
  "shared_root_directory_name": "CAMINO_A_SHARED",
  "bus_relative_path": "AUDIT_BUS",
  "workspace_marker": ".camino_shared_root.json",
  "macos_cloud_storage_directory": "Library/CloudStorage",
  "macos_provider_prefixes": [
    "GoogleDrive"
  ],
  "macos_my_drive_directory_names": [
    "My Drive",
    "Mi unidad"
  ],
  "local_staging_app_name": "CaminoA",
  "sqlite_on_shared_drive_allowed": false,
  "mutable_state_on_shared_drive_allowed": false,
  "shared_drive_payload_policy": "immutable_bundle_manifest_done_only"
}
```

## SOURCE: config/primary_brain_policy.json

```json
{
  "schema_version": "primary_brain_policy.v4.gateway_actions_external_evidence",
  "brain_current": "gpt_manual_or_configured",
  "brain_is_unique": true,
  "automatic_mode": false,
  "dispatch_mode": "gpt_active_conversation_via_gateway_actions",
  "evidence_mode": "external_validated_only",
  "synthetic_adapter_forbidden": true,
  "drive_access_mode": "gateway_data_plane",
  "gpt_surface_mode": "actions_not_apps",
  "model_policy": {
    "preferred_route_id": "chatgpt_gpt_5_6_sol_actions_plan",
    "preferred_model_id": "gpt-5.6-sol",
    "surface": "custom_gpt_actions",
    "preferred_reasoning_level": "high",
    "required_mode": "non_pro",
    "actions_required": true,
    "api_key_allowed": false,
    "availability_gate": "builder_model_picker_and_live_action_smoke",
    "fallback_route_id": "chatgpt_gpt_5_5_plan",
    "responses_api_active": false,
    "openai_api_forbidden": true
  },
  "max_short_iterations": 7,
  "max_total_iterations": 50,
  "timeout_per_stage_seconds": 300,
  "forbidden_brains": [
    "mimo_gateway",
    "vertex_gemini_3_1_pro_preview",
    "gemini_aistudio_highest",
    "codex",
    "claude"
  ],
  "require_manifest_for_response": true,
  "max_response_size_bytes": 1048576,
  "stages": {
    "primary_consolidation": {
      "output_dir": "31_GPT_PRIMARY_OUTPUT",
      "done_name": "PRIMARY_BRAIN_RESPONSE.DONE",
      "max_input_chars": 50000
    },
    "code_generation": {
      "output_dir": "40_GPT_CODE_OUTPUT",
      "done_name": "GPT_CODE_OUTPUT.DONE",
      "max_input_chars": 30000
    },
    "post_code_review": {
      "output_dir": "61_GPT_ITERATION_OUTPUT",
      "done_name": "GPT_ITERATION_OUTPUT.DONE",
      "max_input_chars": 50000
    },
    "closure": {
      "output_dir": "70_FINAL_GPT_CLOSURE",
      "done_name": "FINAL_GPT_CLOSURE.DONE",
      "max_input_chars": 20000
    }
  }
}
```

## SOURCE: config/provider.policy.json

```json
{
  "allowed_providers": [],
  "disable_on_401": true,
  "disable_on_403": true,
  "disable_on_404_model": true,
  "forbidden_providers": [
    "openai_api",
    "anthropic_api",
    "claude_api"
  ],
  "live_probe": {
    "active_probe_requires_cli_flag": "--active-probe",
    "allowed_provider_families": [
      "openrouter",
      "blackbox",
      "gemini",
      "vertex",
      "lmstudio"
    ],
    "credential_envs_by_family": {
      "blackbox": [
        "BLACKBOX_API_KEY",
        "BLACKBOX_TOKEN"
      ],
      "gemini": [
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_AI_STUDIO_API_KEY"
      ],
      "openrouter": [
        "OPENROUTER_API_KEY"
      ],
      "vertex": [
        "VERTEX_ACCESS_TOKEN",
        "GOOGLE_OAUTH_ACCESS_TOKEN",
        "GCLOUD_ACCESS_TOKEN",
        "gcloud auth print-access-token"
      ],
      "lmstudio": [
        "LMSTUDIO_API_KEY",
        "literal:lm-studio"
      ]
    },
    "default_execute_external_calls": false,
    "execute_requires_cli_flag": "--execute",
    "forbidden_api_providers": [
      "openai_api",
      "anthropic_api",
      "claude_api"
    ],
    "forbidden_env_vars": [
      "OPENAI_API_KEY",
      "ANTHROPIC_API_KEY"
    ],
    "listing_endpoints": {
      "blackbox": "https://api.blackbox.ai/v1/models",
      "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
      "openrouter": "https://openrouter.ai/api/v1/models",
      "vertex": "https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/publishers/google/models",
      "lmstudio": "resolved_by_host_runtime"
    },
    "paid_active_probe_requires_cli_flag": "--allow-paid",
    "result_contract": "missing credentials/network/auth/model_absent are explicit statuses; never convert them to availability",
    "schema_version": "camino_a_live_probe_policy.v1",
    "lmstudio_connection_refused_policy": "explicit_skip_no_consta_check_lmstudio_listen_on_0_0_0_0"
  },
  "max_429_retries": 1,
  "probe_timeout_seconds": 10,
  "require_probe_before_gate": true,
  "retry_on_429": true,
  "gateway_security": {
    "api_key_env": "CAMINO_B_GATEWAY_API_KEY",
    "api_key_header": "X-API-Key",
    "https_required_for_remote": true,
    "insecure_http_override_env": "CAMINO_B_ALLOW_INSECURE_HTTP",
    "allowed_hosts_override_env": "CAMINO_B_GATEWAY_ALLOWED_HOSTS",
    "audit_response_requires": [
      "status",
      "model_id",
      "provider_id",
      "candidate_sha256",
      "findings"
    ]
  },
  "schema_version": "1.1"
}
```

## SOURCE: QUICKSTART.md

```markdown
# Quickstart — Camino A/B v1.3.21 handoff adversarial + portable dual host

## 1. Verificación mecánica

```bash
bin/run_tests.sh
bin/launch_sandbox.sh --json
```

El smoke esperado termina en `reference_smoke_complete`. Es una comprobación
mecánica; no se presenta como auditoría GPT ni como aprobación de producción.

## 2. Corrida real desde cualquiera de los dos Mac

```bash
python3 scripts/run_multiaudit_cycle.py \
  --input /ruta/proyecto \
  --runs-dir ./CAMINO_RUNS \
  --canon-profile with_claude \
  --execute-workers \
  --watch-timeout-minutes 480 \
  --max-iterations 3
```

El entrypoint detecta host/arquitectura/RAM, guarda `CANON_SLOT_PLAN.json` y el
maestro consume realmente los slots 1→14. Camino A: Codex orquesta y GPT es el
cerebro. Camino B: GPT es cerebro y orquestador. El motor de estado no sustituye
a ninguno. En modo canónico, el presupuesto de reintentos sale de `loops` de
cada slot; `--max-iterations` queda sólo como fallback para planes legacy.

Si el GPT cerebro todavía no entregó el resultado del slot vigente, la corrida
se detiene honestamente como `waiting_external_gpt_brain_slot_N`. Materializá la
respuesta mediante Gateway Actions o:

```bash
python3 scripts/primary_brain_adapter.py \
  --run-dir CAMINO_RUNS/RUN_xxx \
  --stage primary_consolidation \
  --slot-id 3 \
  --response-file /ruta/respuesta_gpt.json
```

Al volver a lanzar el maestro, valida run/slot/SHA/evidencia y reanuda.

`INPUT/target_snapshot` queda inmutable. El árbol que realmente evoluciona es
`00_CANDIDATE`: una corrección sólo se promueve si llega como
`candidate_update.zip` completo, ligado al SHA vigente, y entonces el maestro
reinicia el plan en slot 1. El ZIP final se rechaza si ese árbol está vacío,
desincronizado o no coincide con su manifest.

## 3. LM Studio y stopper de RAM

La resolución es override → loopback → bridge. No hay IP fija en las rutas:

```bash
python3 scripts/host_runtime.py --json
python3 scripts/worker_lmstudio.py --list --json
```

El guard SQLite corre en el host que posee la RAM. Reserva antes de generar,
mantiene heartbeat/TTL, admite como máximo 2 modelos medianos y hace exclusivo
el tier pesado. Con presión crítica no carga otro modelo. Si LM Studio está en
el otro Mac, el worker se ejecuta allí por SSH estricto; un guard remoto no se
finge desde el coordinador.

## 4. SSH bidireccional

Cada Mac necesita Remote Login, una clave dedicada y el peer opuesto en
`config/host_runtime.policy.json`.

```bash
python3 scripts/peer_executor.py --probe-only --json
```

MacBook→iMac usa `mariano@10.0.0.2`; iMac→MacBook usa
`mariano@10.0.0.1`. Un fallo queda explícito y no habilita offload ficticio.

Si `systemsetup` informa que necesita Full Disk Access: en el Mac receptor abrir
Configuración del Sistema → Privacidad y seguridad → Acceso total al disco,
habilitar Terminal, cerrarlo y abrirlo de nuevo. Luego ejecutar y verificar:

```bash
sudo systemsetup -setremotelogin on
sudo systemsetup -getremotelogin
```

## 5. Slot 14: Claude y fallback Codex

Orden obligatorio:

1. `claude_code_subscription_cli` mediante `claude auth status`.
2. Sólo si Claude queda registrado como no disponible: Codex CLI por
   suscripción ChatGPT, modelo `gpt-5.6-sol`, razonamiento `ultra`.

```bash
claude auth login
claude auth status
codex login status
```

`ANTHROPIC_API_KEY` y `OPENAI_API_KEY` están prohibidas. Codex fallback sólo
puede aprobar en slot 14 con slots 1–13 completos, SHA vigente, cero cambios y
cero findings. Antes de invocar la revisión, el worker comprueba además que el
catálogo local del CLI expone exactamente `gpt-5.6-sol` con `ultra`; si no, falla
cerrado.

## 6. GPT-5.6 Sol en los GPT Cerebro

Camino A y Camino B prefieren Sol no-Pro con Actions y razonamiento High. La
ruta está deshabilitada hasta verificar el selector de ambos GPT Builder y un
smoke Action real; mientras tanto se conserva GPT-5.5. No uses modo Pro ni
interpretes las capacidades de Responses API como si fueran Actions. El
protocolo completo está en `actions/SOL56_ACTIONS_EVAL_PROTOCOL.md`.

## 7. Drive, GPT Actions y archivos grandes

El GPT Cerebro conserva Actions; Drive queda detrás del Gateway como data plane
porque el Builder no permite Apps y Actions simultáneamente. SQLite/WAL/locks
son locales; Drive sólo transporta bundles inmutables con manifest y `.DONE`.

Inicialización portable del bus (descubre `My Drive` o `Mi unidad` sin fijar el
usuario; ante más de una cuenta exige override explícito):

```bash
python3 scripts/drive_locator.py --create --require-shared --json
```

La carga manual acepta texto pegado y adjuntos repetibles `.md/.txt/.json/.yaml/
.yml/.py/.csv/.png/.jpg/.jpeg/.webp/.pdf/.zip`, hasta 64 MiB por artefacto:

```bash
bin/manual_submit.sh --run CAMINO_RUNS/RUN_xxx --worker manual_gpt \
  --stage external_audit --slot-id 2 --candidate-sha256 SHA64 \
  --text 'Auditoría pegada' --file informe.pdf --file evidencia.py
```

Inputs Gateway mayores a 10 MiB usan `chunked_input_v1` con SHA por chunk y
SHA/tamaño final. Si el servidor no anuncia esa capacidad, el cliente devuelve
`insufficient_evidence`; nunca omite silenciosamente el archivo.

La Action vigente todavía no recibe adjuntos directos del chat mediante
`openaiFileIdRefs`. La ingesta multiformato comprobada es la manual/data plane;
no se declara equivalente hasta desplegar y probar el handler server-side.
```

## SOURCE: RUNBOOK_CODEX.md

```markdown
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
```
