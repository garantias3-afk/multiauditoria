# multiauditoria

Repo base para coordinar Camino A, Camino B y el material compartido entre GPT, GLM, Claude y Codex.

## Estructura

- `camino-a/`: orquestacion y control del flujo.
- `camino-b/`: ejecucion, puente y materiales operativos.
- `shared/`: estado comun, hilos de IA y pendientes de recuperacion.

## Estado actual recuperado

- El runtime recuperado esta versionado en `camino-a/runtime/`.
- Camino B conserva sus componentes dentro del runtime importable y su indice en `camino-b/README.md`.
- El fallback de slot 14 cierra `stdin`, usa Codex por suscripcion y conserva el binding de evidencia previa por SHA.
- La corrida real `RUN_20260713_022749_eb68e_slot14_subscription_smoke` cerro limpia.
- La suite autoritativa termino con `106 passed` y `RUN_TESTS_OK`.

## Regla de trabajo

- Cada cambio importante se cierra con commit.
- Los hilos de IA se guardan en `shared/threads/`.
- Camino A mantiene la capa orquestadora.
- Camino B mantiene la capa ejecutora o puente.
