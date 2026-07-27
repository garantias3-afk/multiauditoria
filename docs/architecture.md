# Architecture — Multiauditoria

> Diagrama de arquitectura (Mermaid). Este archivo contiene el diagrama activo en formato Mermaid; un GitHub Action regenerará el SVG en docs/architecture_diagram.svg cuando se hagan cambios en los archivos relevantes.

**Estado:** Diagrama en mermaid activo y versionado en docs/architecture_diagram.mermaid. El workflow `.github/workflows/ci_update_mermaid.yml` genera y comitea el SVG automáticamente.

---

## Diagrama (Mermaid)

```mermaid
flowchart LR
  subgraph Repo["multiauditoria (repo)"]
    direction TB
    CA["camino-a\n(orquestador)"]
    CB["camino-b\n(ejecutor / puente)"]
    SH["shared\n(estado / evidencia)"]
    DOC["docs\n(TDD_SYSTEM_BLUEPRINT.md)"]
    TESTS["tests & validation\n(VALIDATION_RESULTS.json)"]
  end

  CA --> RUNTIME["camino-a/runtime\n(scripts, schemas, manifests, tests)"]
  RUNTIME -->|entrypoints| Scripts["run_multiaudit_cycle.py\novernight_master.py\nslot14_handoff.py ..."]
  RUNTIME --> Schemas["schemas/* (JSON schemas)"]
  RUNTIME --> Manifests["RELEASE_MANIFEST.json / bundles"]

  CB -.->|referencia / importa (NO duplicar)| RUNTIME
  CB -->|implementa| Gateway["Gateway HTTP / bridge / agents"]
  SH -->|lee / escribe| RUNTIME
  SH -->|lee / escribe| CB
  DOC -->|guía| CA
  DOC -->|guía| CB
  RUNTIME --> TESTS
  TESTS --> SH

  classDef repoStyle fill:#f8f9fa,stroke:#333,stroke-width:1px;
  class Repo repoStyle;
```

---

## Notas de uso y actualización

- El diagrama está embebido en este Markdown y también se mantiene como `docs/architecture_diagram.mermaid` (fuente canonical). La acción CI `ci_update_mermaid.yml` regenerará `docs/architecture_diagram.svg` desde ese archivo fuente cuando se hagan push a la rama por defecto.
- Si necesitas exportar manualmente el SVG localmente puedes usar:

```
# instalar mermaid-cli (Node.js)
npm install -g @mermaid-js/mermaid-cli
# generar svg
mmdc -i docs/architecture_diagram.mermaid -o docs/architecture_diagram.svg
```

- Para editar: modifica `docs/architecture_diagram.mermaid` o este bloque Mermaid y pushes; la acción CI actualizará el SVG automáticamente.

---

## Enlaces rápidos
- Fuente Mermaid: `docs/architecture_diagram.mermaid`
- Diagrama generado (SVG): `docs/architecture_diagram.svg` (se genera automáticamente en CI)
- Estructura del repo: `docs/structure.md`
- Informe resumido: `docs/summary_report.md`
