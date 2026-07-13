# Hilos de IA

Usa estos archivos como punto de partida para continuar trabajo entre agentes.

Regla:

- un cambio importante = un commit
- no mezclar correcciones grandes en un solo paso
- siempre anotar el estado final antes de pasar el turno

## Ubicacion del repo

- Ruta local: `/Users/mariano/Documents/multiauditoria`
- Repo GitHub: `garantias3-afk/multiauditoria`
- Rama activa: `main`

## Regla de sincronizacion

- leer `shared/STATUS.md` antes de tocar cualquier archivo
- despues de cada cambio relevante, actualizar `shared/STATUS.md`
- si aparece evidencia nueva, registrar el ultimo comando y el resultado
- si una IA termina su turno, dejar claro que parte del repo toco

## Orden de trabajo

1. Confirmar si la tarea pertenece a Camino A, Camino B o shared.
2. Revisar el estado mas reciente, no el historico antiguo.
3. Hacer el cambio mas chico posible.
4. Commit separado por reforma importante.
5. Cerrar el turno con el estado y el siguiente paso exacto.
