# Deudas abiertas — multiauditoria

Relevado el 2026-07-27. Este archivo lista deuda técnica **conocida y no resuelta**.
No es una lista de tareas planificadas: es lo que se sabe que está mal o sin decidir.

Alcance: este repositorio es público. Las deudas que involucran repositorios
privados se registran allí, no acá.

---

## 1. Tres bases de código aisladas en un mismo repositorio

Graphify no detecta **ninguna arista** entre los módulos de código:

| Módulo | Nodos |
|---|---:|
| `camino-a/runtime` | 1438 |
| `apps/desktop` | 312 |
| `tools` | 4 |

`apps/desktop` y `camino-a/runtime` se comunican —si lo hacen— por HTTP/SSE en
tiempo de ejecución. Ese contrato no está documentado en ningún lado y el
análisis estático no puede verlo.

**Pendiente:** documentar el contrato de transporte entre el cliente Tauri y el
runtime, o dejar asentado que son proyectos independientes que comparten repo.

## 2. `camino-b/` no contiene código

Dos archivos, ambos documentación. La regla de trabajo "Camino B importa desde
`camino-a/runtime`, no duplica" está escrita pero no hay ninguna importación real
que la cumpla ni que la viole.

**Pendiente:** o se materializa `camino-b/` como código que importa del runtime,
o se elimina la regla y se documenta que Camino B es solo documentación.

## 3. Runtime duplicado entre repositorios

Seis archivos de `camino-a/runtime/scripts/` existen **byte a byte idénticos** en
otro repositorio del mismo autor:

```
state_db.py                     camino_b_gateway.py
overnight_master.py             camino_b_outbound_agent.py
camino_b_slot14_bridge.py       run_camino_b_bridge_smoke.py
```

No son un fork intencional documentado: son copias. Hoy no divergieron entre
esos dos repos, pero nada lo impide.

`tools/find_duplicates.py` detecta duplicados **dentro** de un repositorio. Esta
duplicación es **entre** repositorios y ninguna herramienta instalada la mira.

**Pendiente:** decidir cuál copia es canónica y cómo se distribuye (paquete
instalable, submódulo, o política explícita de sincronización).

## 4. `state_db.py` divergió en una tercera copia

Existe una tercera copia en otro repositorio privado que **no** es idéntica: es
más nueva y contiene una función de endurecimiento adicional que las copias de
este repositorio no tienen.

**Pendiente:** determinar si la divergencia fue deliberada. Si no lo fue,
sincronizar. Esta es la deuda de mayor prioridad de la lista.

## 5. Canarios de credenciales sintéticas

Los tests usan cadenas con forma de credencial (`sk-proj-…`, `AKIA…`) como
canarios para verificar que los detectores de secretos disparan. Ninguna es una
credencial real, pero los literales generaban alertas de secret scanning y podían
confundir a un lector.

Se reescribieron para armarse en tiempo de ejecución: el valor efectivo es
idéntico y los tests siguen pasando, pero el literal ya no está en el fuente.

**Regla:** no volver a escribir literales con forma de credencial en el código.
Si hace falta un canario nuevo, construirlo por concatenación.

## 6. No hay integración continua

Este repositorio no tiene `.github/workflows/`. Una versión anterior de
`docs/architecture.md` afirmaba que un workflow `ci_update_mermaid.yml` generaba
y comiteaba un SVG automáticamente; ese workflow nunca existió. La afirmación
fue eliminada.

**Pendiente:** decidir si se quiere CI. Nota: un bot que comitea a la rama por
defecto deja la copia local `behind` después de cada push.

## 7. Falla preexistente en los canarios K3

`shared/audits/router-v5-r2/audit_k3/canaries_k3.py` termina 19 PASS / 1 FAIL.
El caso que falla es `K3-13 clave 'properties' generica marca contratos`, un
falso positivo del eje `contratos`: un `.json` con marcador de schema alcanza el
umbral por regla crítica de formato.

Verificado que la falla es anterior a cualquier cambio reciente. Las otras suites
del mismo directorio pasan completas (75/0, 21/0, 20/0).

**Pendiente:** ajustar el umbral o la regla `CTR-FORMAT`, o reclasificar el
canario si el comportamiento es el deseado.

## 8. La documentación de estructura se mantiene a mano

`docs/architecture_diagram.mermaid` ahora se genera desde el grafo de Graphify
(`python3 tools/graph_to_mermaid.py`). `docs/structure.md` y la sección
`## Estructura` del `README.md` siguen escritas a mano y pueden volver a
desincronizarse.

**Pendiente:** derivar también `structure.md` del grafo, o borrar una de las tres
descripciones de estructura para que quede una sola fuente.

## 9. `shared/audits/` está en `.gitignore` pero tiene archivos versionados

El directorio aparece en `.gitignore` y sin embargo contiene 10 archivos
trackeados (las suites de auditoría de `router-v5-r2`). `.gitignore` no
desversiona lo ya versionado, así que el estado actual es: los archivos
existentes se siguen versionando y sus cambios se commitean, pero **cualquier
archivo nuevo en ese directorio queda invisible en silencio**, y `git add
shared/audits/` falla.

Es una trampa: un colaborador que agregue una auditoría nueva ahí va a creer que
la commiteó.

**Pendiente:** decidir si esas auditorías deben versionarse. Si sí, sacar el
patrón del `.gitignore`. Si no, desversionar las 10 explícitamente.
