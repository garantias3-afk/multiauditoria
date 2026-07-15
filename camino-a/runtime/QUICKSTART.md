# Quickstart — Camino A/B v1.3.22 loops internos 1/4 acotados + portable dual host

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
