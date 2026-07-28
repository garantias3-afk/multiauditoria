# Arquitectura — multiauditoria

> **El diagrama de este documento se genera automáticamente desde Graphify.**
> No se edita a mano. Fuente: `graphify-out/graph.json` → `docs/architecture_diagram.mermaid`.

## Cómo se genera

Graphify reconstruye `graphify-out/graph.json` en cada `git commit` / `checkout`
(hook ya instalado; el grafo es local y está gitignoreado). Para regenerar el
diagrama a partir de ese grafo:

```bash
python3 tools/graph_to_mermaid.py
```

Si `graphify-out/` no existe todavía en la máquina donde estás trabajando:

```bash
graphify extract . --code-only
```

**No hay CI que regenere un SVG.** Una versión anterior de este documento
afirmaba que `.github/workflows/ci_update_mermaid.yml` generaba y comiteaba
`docs/architecture_diagram.svg` automáticamente. Ese workflow nunca existió en
el repositorio. Si en algún momento se decide agregarlo, tener en cuenta que un
bot que comitea a la rama por defecto deja la copia local `behind` después de
cada push; es una decisión a tomar explícitamente, no algo a heredar de esta
documentación.

## Diagrama

El diagrama vigente está en [`architecture_diagram.mermaid`](architecture_diagram.mermaid),
con los contadores de nodos y el commit de generación en las líneas de comentario
del encabezado.

## Lo que el grafo muestra hoy

Graphify no detecta **ninguna arista entre los módulos de código** del repo. Hay
tres bases de código aisladas conviviendo en el mismo repositorio:

| Módulo | Nodos | Qué es |
|---|---:|---|
| `camino-a/runtime` | 1438 | Runtime ejecutable: `scripts/`, `tests/`, `schemas/`, `canon/`, `bin/` |
| `apps/desktop` | 312 | Cliente Tauri v2 + React/TypeScript |
| `tools` | 4 | `find_duplicates.py` |

Consecuencias que conviene tener presentes al leer cualquier diagrama de este repo:

- **`camino-b/` no aporta código.** Contiene solamente documentación. La regla
  "camino-b importa desde camino-a/runtime, no duplica" está documentada pero no
  hay ninguna importación real que la implemente ni que la viole.
- **`shared/`** es estado, hilos y evidencia (más algunos scripts de auditoría
  bajo `shared/audits/`), no un componente en tiempo de ejecución.
- **`apps/desktop` y `camino-a/runtime` no se referencian entre sí.** Se comunican,
  si lo hacen, por HTTP/SSE en tiempo de ejecución — un acoplamiento que el
  análisis estático no ve y que ningún diagrama derivado del grafo va a mostrar.
  Cualquier diagrama que dibuje esa flecha la está afirmando sin evidencia.
