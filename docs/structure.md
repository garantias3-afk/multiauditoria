# Estructura del repositorio — multiauditoria

Resumen de directorios con notas rápidas. Para el mapa de código real y sus
dependencias, la fuente de verdad es el grafo de Graphify
(`graphify-out/graph.json`), no este archivo.

```text
multiauditoria/
  README.md                 - visión general y reglas de trabajo
  camino-a/                 - capa orquestadora
    runtime/                - runtime importable (1438 nodos de código)
      scripts/              - entrypoints y adaptadores (run_multiaudit_cycle.py,
                              overnight_master.py, slot14_handoff.py, ...)
      schemas/              - contratos / JSON schema
      canon/                - canon de rutas, slots y proveedores
      tests/                - suite del runtime
      bin/                  - ejecutables auxiliares
      VALIDATION_RESULTS.json
      RELEASE_MANIFEST.json
  camino-b/                 - SOLO documentación (0 archivos de código)
  apps/
    desktop/                - cliente Tauri v2 + React/TypeScript (312 nodos)
      src/                  - componentes, core (api/sse/recovery), estado, utils
      src-tauri/            - capa Rust de Tauri
      tests/                - suite del cliente
      mocks/                - servidor mock para tests de integración
  shared/                   - estado común, hilos, evidencia
    STATUS.md, RUNBOOK.md   - estado y procedimientos
    threads/                - hilos de trabajo
    audits/                 - auditorías (router-v5-r2, ...)
  docs/                     - arquitectura y diagrama generado
    architecture.md         - cómo se genera el diagrama + lectura del grafo
    architecture_diagram.mermaid  - GENERADO, no editar a mano
    TDD_SYSTEM_BLUEPRINT.md
  tools/
    find_duplicates.py      - detección de duplicados
    graph_to_mermaid.py     - genera el diagrama desde graphify-out/graph.json
```

Notas:

- `camino-a/runtime` contiene el runtime ejecutable. La regla de trabajo es que
  Camino B referencie ese runtime en lugar de copiar archivos; hoy `camino-b/`
  no tiene código, así que la regla no está siendo ejercida en ninguna dirección.
- `shared/` es la fuente única de verdad para hilos y evidencia.
- Graphify no detecta aristas entre `camino-a/runtime`, `apps/desktop` y `tools`:
  son tres bases de código aisladas dentro del mismo repositorio.
