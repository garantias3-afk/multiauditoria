# Camino B

Camino B concentra la ejecucion operativa, los puentes y los artefactos de trabajo.

Responsabilidades:

- correr tareas concretas
- generar artefactos de evidencia
- alojar puentes o adaptadores cuando hagan falta
- dejar logs o resultados utiles para la siguiente IA

Notas:

- Si una tarea no puede cerrarse con evidencia, se deja marcada como pendiente.
- Todo cambio relevante debe quedar listo para commit aislado.

## Componentes recuperados

El runtime es una sola unidad importable bajo `../camino-a/runtime/`. Los
componentes cuya responsabilidad operativa corresponde a Camino B son:

- `../camino-a/runtime/scripts/camino_b_slot14_bridge.py`
- `../camino-a/runtime/scripts/camino_b_gateway.py`
- `../camino-a/runtime/scripts/camino_b_outbound_agent.py`
- `../camino-a/runtime/scripts/run_camino_b_bridge_smoke.py`
- `../camino-a/runtime/bin/start_camino_b_gateway.sh`
- `../camino-a/runtime/bin/run_camino_b_agent.sh`
- `../camino-a/runtime/actions/CAMINO_B_SLOT14_BRIDGE_ACTIONS.v1.yaml`
- `../camino-a/runtime/actions/CAMINO_B_SLOT14_BRIDGE_DEPLOYMENT.md`
- `../camino-a/runtime/actions/CAMINO_B_GPT_BUILDER_INSTRUCTIONS.md`
- `../camino-a/runtime/schemas/camino_b_slot14_bridge.schema.json`
- `../camino-a/runtime/tests/test_camino_b_slot14_bridge.py`

No se duplican esos archivos aqui: dos copias editables crearian estados
divergentes entre Camino A y Camino B.

## Estado operativo

El backend local de Camino B esta implementado y su flujo HTTP completo fue
validado con un bundle real de Codex por suscripcion. La publicacion de la URL
HTTPS y la importacion de la spec en GPT Builder son pasos de entorno, no codigo
pendiente del runtime.
