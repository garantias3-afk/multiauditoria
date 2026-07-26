# INFORME ROUTER V5 — K3 R2 (corrección adjudicada de auditoría externa)

## 1. Identidad y procedencia

- **autor:** Kimi Code
- **modelo exacto:** NO_CONSTA (sin identificación interna verificable disponible)
- **entorno:** Kimi Code (CLI)
- **ronda:** ROUTER_V5_R2
- **fecha local:** 2026-07-26 12:34 -03
- **estado:** PENDIENTE_DE_REAUDITORIA_EXTERNA

Procedencia: esta ronda corrige los 11 defectos adjudicados como reales por
la auditoría externa K3 sobre la v5 persistida en R1
(`outputs/INFORME-ROUTER-V5-K3.md`). No es una auditoría final: se corrigen
causas en el motor (`outputs/router_v5.py`), no resultados esperados, y se
deja la evidencia para reauditoría externa. No se declara cierre de DEUDA-3
ni aptitud de producción.

Archivos escritos en esta ronda (conjunto exacto; nada más fue escrito):

- modificado: `outputs/router_v5.py` (motor; correcciones 1–11 + R2-DET)
- modificado: `outputs/axis_matrix_v5_current.json` (regenerado por el scan)
- creado: `outputs/canaries_k3_adjudicated_v5.py`
- creado: `outputs/canaries_zcode_regression_v5.py`
- creado: este informe

Inmutabilidad verificada: `outputs/test_router_v5.py`,
`outputs/adversarial_independent_v5.py` y `outputs/scan_corpus_v5.py`
conservan exactamente los SHA-256 publicados en el informe R1 (ver §9);
ningún archivo de `inputs/` ni de `outputs/audit_k3/` fue escrito.

## 2. HECHOS medidos

Ejecutado en este entorno, en el orden exigido por la OT R2:

| # | comando | esperado | observado | exit |
|---|---|---|---|---|
| 1 | `PYTHONPATH=outputs python3 outputs/test_router_v5.py` | 75/75 | `=== 75 PASS / 0 FAIL ===` | 0 |
| 2 | `PYTHONPATH=outputs python3 outputs/adversarial_independent_v5.py` | 21/21 | `21 PASS / 0 FAIL` | 0 |
| 3 | `PYTHONPATH=outputs python3 outputs/audit_k3/canaries_k3.py` | 19/20, único FAIL = K3-13 | `19 PASS / 1 FAIL` (FAIL: K3-13, kind=FP según su expectativa original) | 1 |
| 4 | `PYTHONPATH=outputs python3 outputs/canaries_k3_adjudicated_v5.py` | 20/20 | `20 PASS / 0 FAIL` | 0 |
| 5 | `PYTHONPATH=outputs python3 outputs/canaries_zcode_regression_v5.py` | ≥13/15, sólo N04/N05 | `13 PASS / 2 FAIL` (FAIL: N04 y N05, ambos FN) | 1 |
| 6 | `PYTHONPATH=outputs python3 outputs/scan_corpus_v5.py` | 148 archivos, matriz válida | `n=148`, matriz escrita | 0 |

Hechos adicionales medidos:

- **Determinismo del scan:** dos ejecuciones consecutivas produjeron SHA-256
  idéntico de la matriz (`2a9a0180…f7a4256b`, §9) y stdout idéntico. Una
  tercera ejecución con `PYTHONHASHSEED=12345` explícito produjo el mismo
  hash. (Antes del arreglo R2-DET, dos corridas daban hashes distintos:
  `b7f551c1…` vs `6d89773f…`.)
- **Diff de matriz R1→R2:** 0 archivos con cambio de asignación (ejes);
  0 con cambio de decisión o score; 4 filas difieren sólo en el ORDEN de la
  evidencia (mismo conjunto), explicado por R2-DET (§7).
- **Invariantes sobre la matriz R2:** 0 ejes fuera del registro declarado;
  0 archivos donde `volume_generalist` coexiste con ejes específicos;
  0 evidencias con `source` fuera del conjunto declarado; JSON válido;
  `domain_rules_hash` sin cambios (`45a984eb…4d77c06`, idéntico a R1 porque
  `DOMAIN_RULES` no se tocó).
- **Higiene de scripts:** los tres scripts v5 (`test_router_v5.py`,
  `adversarial_independent_v5.py`, `scan_corpus_v5.py`) no contienen
  `router_v4`, `axis_matrix_v4` ni rutas externas. Las dos únicas
  coincidencias de `/tmp/` son payloads de canarios preexistentes
  (`sudo rm -rf /tmp/x` dentro de strings de prueba, ya presentes en R1/v4).
  Los dos scripts nuevos importan únicamente `router_v5`.

## 3. Correcciones 1–11 (causas, con ubicación)

Todas en `outputs/router_v5.py`. Se conservaron los tratamientos correctos
preexistentes (loaders seguros por origen real, comillas simples inertes en
local, placeholders previos, fallback para desconocidas).

| # | defecto | corrección en el motor | ubicación |
|---|---|---|---|
| 1 | `getattr(os, 'system')(c)` no detectado | La rama `getattr(...)(...)` se generaliza: si el módulo base resuelve a `os` y el atributo está en `OSCMD_ATTRS` → `SEC-OSCMD`; se conserva el caso `builtins`+`DYNEXEC` → `SEC-DYNEXEC` | `PythonAdapter.analyze`, líneas 498–512 |
| 2 | `asyncio.create_subprocess_shell(c)` no detectado | Nueva regla: `mod == "asyncio" and lf == "create_subprocess_shell"` → `SEC-SHELL`. El eje `concurrencia` legítimo se conserva | `PythonAdapter.analyze`, líneas 523–526 |
| 3 | `yaml.load_all(s)` sin loader no evaluado | `"load_all"` se añade a la regla C2-C5; el criterio de loader seguro por origen real (V3) se aplica igual (`yaml.load_all(s, Loader=yaml.SafeLoader)` no dispara, verificado) | `PythonAdapter.analyze`, línea 529 |
| 4 | `YOUR_API_KEY_HERE` tomado por secreto | `PLACEHOLDER` acepta la forma anclada `your(_[a-z0-9]+)+_here` (regex completo sigue anclado con `^…$`; no basta con contener `YOUR` o `HERE`) | `PLACEHOLDER`, líneas 146–149 |
| 5 | `cfg['password'] = 'hunter2'` no detectado | Nuevo helper `_assign_target_name`: el destino de una asignación puede ser `Name`, `Attribute` o clave literal de `Subscript`; se aplica a `Assign` y `AnnAssign`. El valor sigue exigiendo constante con pinta de secreto (un f-string no dispara) | líneas 212–221 y 570–576 |
| 6 | `passphrase` fuera de SECRET_NAME | `passphrase` añadido al alternado con límites de palabra | `SECRET_NAME`, línea 144 |
| 7 | `ssh host 'curl … \| sh'` invisible | Excepción acotada a `ssh`: el comando remoto entre comillas simples se extrae (`SSH_REMOTE`), se analiza con `strip_shell` y se concatena al código. Las comillas simples ordinarias siguen inertes localmente | `ShellAdapter`, líneas 694–705 |
| 8 | `echo curl is a network tool` disparaba `SEC-NET` | Los tokens peligrosos sólo cuentan en posición de comando: `(?:^|[|;&(`]|\$\()\s*token(?:\s|$)`. Las sustituciones `$(…)`/backticks dentro de comillas dobles se reemiten prefijadas con `;` para conservar su posición de comando (`echo "$(curl …)"` sigue disparando) | `strip_shell`, líneas 411–414 y splices; `ShellAdapter`, líneas 708–709 |
| 9 | `{ "password": "hunter2" }` en JS no detectado | La regex de secreto JS admite clave entrecomillada: `["']?(\w+)["']?\s*[:=]\s*['"]([^'"]+)['"]`, sobre la vista sin comentarios | `JsTsAdapter.analyze`, líneas 650–651 |
| 10 | `window['eval'](x)` / `globalThis['eval'](x)` no detectados | Nueva vista `_strip_js(..., keep_ident_strings=True)`: conserva sólo strings que son un único identificador (`window['eval']` → `window[ eval ]`); sobre ella, `GLOBAL_EVAL` marca `SEC-DYNEXEC`. No dispara por comentarios, strings arbitrarios ni regex literales (verificado con casos dedicados) | `_strip_js` líneas 296–310, 340–343, 371; `JsTsAdapter` líneas 620–622, 631–642 |
| 11 | `app.env` con `PASSWORD=hunter2real` caía a residual | Nuevo `EnvAdapter` acotado para `.env`: pares `KEY=VALUE`; sólo secreto literal (nombre en `SECRET_NAME` + valor con pinta) evidencia `SEC-LITERAL`. Las extensiones desconocidas siguen en `FallbackAdapter` | líneas 723–730; registro en `_ADAPTERS`, línea 755 |

Cambio adicional de ingeniería (no es una de las 11; exigido por la OT R2
"scan dos veces, hash idéntico"):

- **R2-DET — determinismo de evidencia:** `st.modules()` es un `set` de
  strings y su iteración depende de `PYTHONHASHSEED`, lo que hacía que el
  orden de la evidencia `import:*` (y por tanto los bytes de la matriz)
  variara entre procesos. Se itera `sorted(st.modules())`. No cambia ejes,
  decisiones ni scores; sólo el orden de emisión de evidencia.
  (`PythonAdapter.analyze`, líneas 583–587.)

## 4. Resultados de todas las suites

| suite | resultado | detalle |
|---|---|---|
| Legada `test_router_v5.py` | **75/75 PASS** | sin cambios respecto de R1 |
| Canarios declarados `adversarial_independent_v5.py` | **21/21 PASS** | sin cambios respecto de R1 |
| Canarios externos originales `audit_k3/canaries_k3.py` | **19 PASS / 1 FAIL** | único FAIL: K3-13 (desacuerdo contractual esperado, §5) |
| Canarios adjudicados `canaries_k3_adjudicated_v5.py` | **20/20 PASS** | §5 |
| Regresión ZCode `canaries_zcode_regression_v5.py` | **13/15 PASS** | N04 y N05 FN documentados (§6); el script sale con código 1 ante cualquier discrepancia, por diseño de la OT |
| Scan `scan_corpus_v5.py` | **148 archivos** | matriz regenerada, determinista (§2, §7) |

Detalle ZCode (13 PASS): N01, N02, N03, N06, N07, N08, N09, N10, N11, N12,
N13, N14, N15. (2 FAIL): N04, N05.

## 5. Tratamiento explícito de K3-13

Caso: `ui_config.json` → `{"name":"theme","properties":{"color":"red","size":3}}`.

Decisión contractual aplicada: **incluye `contratos`**. `.json` ∈
`CONTRACT_EXTS` y genera la regla crítica `CTR-FORMAT` independientemente
del contenido; no se intentó sacar el caso de `contratos` de ningún modo.

- `outputs/audit_k3/canaries_k3.py` **no se modificó**: sigue esperando
  `contratos=False` y por tanto sigue marcando K3-13 como FAIL
  (resultado observado: `19 PASS / 1 FAIL`, exit 1). Es el único FAIL y es
  el desacuerdo contractual esperado.
- `outputs/canaries_k3_adjudicated_v5.py` copia los 20 casos y cambia
  únicamente la expectativa de K3-13 a `True`. Verificación programática de
  la copia: difiere exactamente 1 tupla de las 20; la diferencia es sólo el
  booleano de expectativa (`False → True`); `(nombre, rel_path, fuente, eje)`
  idénticos. Resultado: `20 PASS / 0 FAIL`, exit 0.

## 6. N04/N05: límites pendientes (no resueltos)

- **N04** `sp = __import__('subprocess'); sp.run(c, shell=True)` → FN.
- **N05** `m = importlib.import_module('os'); getattr(m,'system')(c)` → FN.

Ambos requieren resolver el módulo que devuelve una llamada (`__import__`,
`importlib.import_module`) e introducirlo en la tabla de símbolos: es
resolución dinámica, fuera del alcance de esta ronda según la propia OT.
No se encontró una corrección segura y acotada que los resuelva sin
regresiones, y no se amplió el alcance deliberadamente. Quedan como límites
documentados: la suite ZCode da 13/15 con exit 1, que es el estado esperado
mientras estos dos casos sigan pendientes.

## 7. Cambios en la matriz (`axis_matrix_v5_current.json`, R1 → R2)

Comparación fila a fila sobre los 148 archivos (misma raíz
`inputs/camino-a`):

- **Asignaciones (ejes por archivo): 0 cambios.** Ningún archivo gana ni
  pierde ejes. Es consistente con el análisis previo del corpus: ninguno de
  los 148 archivos contiene los patrones de las 11 correcciones (sin
  `getattr(os,…)`, `create_subprocess_shell`, `yaml.load*`, placeholders
  `YOUR_*_HERE`, claves `passphrase`, `ssh`, `.js`, ni `.env` escaneados; el
  único subíndice con clave sensible del corpus,
  `headers["Authorization"] = f"Bearer {token}"` en
  `runtime/scripts/probe_live_routes.py`, tiene valor f-string, no
  constante, y correctamente no dispara).
- **Decisiones y scores: 0 cambios.**
- **4 filas con el mismo conjunto de evidencia en distinto orden**, todas
  explicadas por R2-DET (iteración ordenada del set de módulos):
  `runtime/scripts/camino_b_gateway.py` (seguridad),
  `runtime/scripts/camino_b_slot14_bridge.py` (seguridad),
  `runtime/scripts/peer_executor.py` (seguridad),
  `runtime/tests/test_resource_scheduler.py` (concurrencia).
- **Secciones agregadas idénticas** a R1: `n=148`, `mean=1.135`,
  `histogram={"1":131,"2":14,"3":3}`, `axis_counts` (concurrencia 7,
  contratos 58, rendimiento_recursos 3, seguridad 29, tests_observabilidad
  39, volume_generalist 32), `by_extension`, `decisions`, `top_evidence`,
  `residuals`, `domain_rules_hash=45a984eb…4d77c06`.

## 8. Riesgos residuales

Nuevos o modificados por esta ronda:

- **R2-7 (ssh):** la extracción cubre `ssh … 'comando'` con comillas simples
  al inicio de una línea lógica. No cubre comando remoto entre comillas
  dobles (`ssh host "cmd"`) ni un `ssh` en medio de una pipeline. FN acotado.
- **R2-8 (posición de comando):** las palabras clave de shell no actúan como
  separadores; en `if x; then curl …`, `curl` queda tras `then ` y no se
  marca. FN acotado y consciente: se prefiere no disparar sobre prosa.
- **R2-10 (eval global por corchete):** la vista conserva strings que son un
  único identificador; un caso artificioso como `'window'['eval'](x)`
  (subíndice sobre un literal) sería FP teórico. No se resuelven escapes
  unicode dentro del string (`'ev\u0061l'`).
- **R2-4 (placeholders):** se reconoce la forma `YOUR_..._HERE` además de
  las preexistentes; otras convenciones de placeholder pueden seguir
  marcándose como secreto.
- **R2-11 (.env):** el soporte es exactamente para el sufijo `.env`;
  archivos tipo `.env.example` o nombres compuestos no reciben tratamiento
  especial (siguen en fallback). `inputs/…/config/camino_b.env.example` no
  entra en el scan (sufijo `.example`).
- **R2-DET:** el orden de la evidencia `import:*` pasa a ser alfabético;
  consumidores que dependieran del orden anterior (azaroso) deben tratar la
  evidencia como conjunto.

Heredados de R1 que siguen vigentes: regex JS vs división (heurística del
token previo); `shell=` con variable no constante no evaluado; shadowing
sólo a nivel módulo; dicts anidados más allá de un nivel en argumentos no
inspeccionados; si el stripping JS/shell no es confiable, las reglas
críticas de ejecución se omiten por diseño (queda la vía de señales
débiles); claves con sufijo tipo `api_key_env` no se consideran nombre de
secreto (trade-off de los límites de palabra de V6).

## 9. Hashes (SHA-256)

Archivos escritos en esta ronda:

```text
771b672781cc1da64ea1e941e2db323aaf1b06d9d169fec111306da9e0e267c0  outputs/router_v5.py
2a9a018046401d2b6a8d4c129cad1b60bb23754575b1e7a7081a137af7a4256b  outputs/axis_matrix_v5_current.json
2eb454eeed3d1fb9b7c752ae264a7a37eedde1879b2dd42c9970a7d84c4c208d  outputs/canaries_k3_adjudicated_v5.py
a1c6b592444ab9411dfcbc9628d5a204daa1e56edcd9c0f346ec44125e8c0bb5  outputs/canaries_zcode_regression_v5.py
```

(El hash de este informe no puede contenerse a sí mismo; se entrega en el
mensaje de cierre de la ronda.)

Inmutables verificados contra los hashes publicados en R1 (coinciden):

```text
eabb3bf597520d6c08b1516676add2d712d14eb40ba23a745650fc75d9c707f0  outputs/test_router_v5.py
09679180e2e76c20dc2f2306000daa53929a2d837a1ad51b951fbe147f70576c  outputs/adversarial_independent_v5.py
b677b3ee7acd154a200f191f9419809f616d28641a99e51e74314e144db62ad6  outputs/scan_corpus_v5.py
```

## 10. Estado

**PENDIENTE_DE_REAUDITORIA_EXTERNA.**

No se declara cierre de DEUDA-3 ni aptitud de producción. La ronda deja:
motor corregido con las 11 correcciones adjudicadas (+ R2-DET de
determinismo), suite legada 75/75, canarios declarados 21/21, canarios
externos originales 19/20 con K3-13 como único desacuerdo contractual,
suite adjudicada 20/20, regresión ZCode 13/15 con N04/N05 como límites
documentados, matriz de 148 archivos determinista y trazable, y diff de
asignaciones R1→R2 vacío. Todo queda preparado para verificación y
adjudicación por reauditoría externa.
