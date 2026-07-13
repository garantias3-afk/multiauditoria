# Estado recuperado

## Ultimo estado util

- `scripts/worker_codex_fallback.py`: el worker de fallback de Codex quedo ajustado para no leer desde stdin heredado y seguir el camino de suscripcion.
- `tests/test_codex_fallback.py`: se agrego una regresion que verifica que el worker use `stdin=subprocess.DEVNULL`.
- `scripts/run_slot14_subscription_smoke.py`: quedo como intento real pendiente en la ultima sesion recuperada; la ejecucion no se cerro con veredicto final en lo visto localmente.

## Pendientes inmediatos

- cerrar la corrida real de `slot14_subscription_smoke`
- subir este repo base a GitHub
- seguir con commits pequenos por cambio importante

## Ultimos 5 pedidos del usuario

1. Recuperar los cambios y archivos modificados hoy en MacBook e iMac.
2. Reconstituir el ultimo estado posible, dejando de lado lo antiguo.
3. Terminar lo inconcluso y decir que es.
4. Crear y subir `multiauditoria` en GitHub con la estructura Camino A, Camino B y shared.
5. Dar hilos para otras IA y commitear cada cambio importante.

