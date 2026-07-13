# Camino A

Camino A es la capa orquestadora.

La implementacion recuperada y verificable vive en `runtime/`. Se conserva como
una unidad porque Camino A carga el canon, coordina los slots y despacha los
componentes de Camino B mediante imports internos del mismo paquete.

Responsabilidades:

- decidir el flujo
- coordinar pasos y validaciones
- producir estado resumido para el resto de las IA
- conservar trazabilidad de lo que se aprobo y lo que quedo pendiente

Notas:

- La separacion clave que hay que respetar es: Camino A orquesta y GPT actua como cerebro.
- Si hay duda, registrar primero el estado y despues ejecutar cambios.

## Entradas principales

- `runtime/scripts/run_multiaudit_cycle.py`: entrypoint canonico.
- `runtime/scripts/overnight_master.py`: orquestacion de slots y autoridad terminal.
- `runtime/scripts/run_slot14_subscription_smoke.py`: smoke real del fallback de slot 14.
- `runtime/bin/run_tests.sh`: suite autoritativa.
- `runtime/VALIDATION_RESULTS.json`: ultima validacion generada.
