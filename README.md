# multiauditoria

Repo base para coordinar Camino A, Camino B y el material compartido entre GPT, GLM, Claude y Codex.

## Estructura

- `camino-a/`: orquestacion y control del flujo.
- `camino-b/`: ejecucion, puente y materiales operativos.
- `shared/`: estado comun, hilos de IA y pendientes de recuperacion.

## Estado actual recuperado

- El repo local estaba vacio y sin commits.
- El repo GitHub existe como `garantias3-afk/multiauditoria` y tambien estaba vacio.
- Lo ultimo inconcluso recuperado fue el intento real de `run_slot14_subscription_smoke.py --max-attempts 1`, que quedo pedido pero no cerrado en la sesion.
- El ultimo fix confirmado en los artefactos del otro workspace fue cerrar `stdin` con `subprocess.DEVNULL` en el worker de fallback de Codex y agregar la regresion correspondiente.

## Regla de trabajo

- Cada cambio importante se cierra con commit.
- Los hilos de IA se guardan en `shared/threads/`.
- Camino A mantiene la capa orquestadora.
- Camino B mantiene la capa ejecutora o puente.

