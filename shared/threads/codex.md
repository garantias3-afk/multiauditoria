# Hilo para Codex

Ubicacion:

- repo local: `/Users/mariano/Documents/multiauditoria`
- repo GitHub: `garantias3-afk/multiauditoria`
- rama: `main`

Objetivo:

- ejecutar cambios concretos y dejar evidencia operativa
- tomar la tarea mas chica que destrabe la siguiente
- cerrar corridas con resultado real, no con supuestos

Antes de cambiar algo:

- leer `shared/STATUS.md`
- leer `shared/RUNBOOK.md`
- revisar si la tarea pertenece a Camino A, Camino B o shared
- confirmar que el cambio sea el siguiente paso mas chico posible

Forma de trabajo:

- cada cambio importante va en commit separado
- si una corrida falla, guardar la causa y el ultimo estado
- no mezclar recuperacion con refactor grande en el mismo paso
- actualizar `shared/STATUS.md` al cerrar
- si hace falta cambiar de modelo, parar en este punto y dejar la pista lista
