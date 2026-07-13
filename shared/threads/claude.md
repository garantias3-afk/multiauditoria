# Hilo para Claude

Ubicacion:

- repo local: `/Users/mariano/Documents/multiauditoria`
- repo GitHub: `garantias3-afk/multiauditoria`
- rama: `main`

Objetivo:

- revisar consistencia, contratos y regresiones
- detectar desalineaciones entre Camino A, Camino B y shared
- pedir evidencia si una corrida no queda cerrada

Antes de cambiar algo:

- leer `shared/STATUS.md`
- leer `shared/RUNBOOK.md`
- revisar los README de Camino A y Camino B
- validar que no se rompa la separacion orquestador/cerebro

Forma de trabajo:

- una correccion = un commit
- registrar pruebas o evidencia
- dejar una nota clara si no se pudo cerrar
- al terminar, volver a `shared/STATUS.md`
- no mezclar analisis historico con una reforma nueva
