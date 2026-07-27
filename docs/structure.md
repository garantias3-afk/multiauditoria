# Estructura del repositorio — multiauditoria

Este documento resume los principales directorios y archivos del repositorio, con notas rápidas sobre su propósito.

```text
multiauditoria/
  README.md                 - visión general y reglas de trabajo
  camino-a/                 - capa orquestadora
    README.md
    runtime/                - runtime importable: scripts, schemas, manifests, tests
      scripts/              - entrypoints y adaptadores (run_multiaudit_cycle.py, overnight_master.py, slot14_handoff.py, etc.)
      schemas/              - contratos / JSON schema
      actions/              - acciones / instrucciones de despliegue
      VALIDATION_RESULTS.json
      RELEASE_MANIFEST.json
  camino-b/                 - ejecución operativa / puente (documenta sus componentes, pero no duplica código)
    README.md
  shared/                   - estado común, hilos/threads, evidencia, RUNBOOK.md, STATUS.md
  docs/                     - blueprint técnico (TDD_SYSTEM_BLUEPRINT.md) y diagramas
  tools/                    - utilidades (find_duplicates.py)
```

Notas:
- Camino A contiene el runtime ejecutable; Camino B debe importar desde allí en lugar de copiar archivos.
- shared/ es la fuente única de verdad para hilos/evidencia.
- docs/ contiene la blueprint técnica y el diagrama mermaid activo.

