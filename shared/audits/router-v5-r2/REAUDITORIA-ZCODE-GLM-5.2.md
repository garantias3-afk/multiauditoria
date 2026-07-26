Ahora redactaré el informe de auditoría completo.

---

# REAUDITORÍA EXTERNA — ROUTER v5 R2

## 0. Declaración del auditor (exigida por la OT)

- **autor:** ZCode (agente de reauditoría externa, CLI).
- **modelo exacto:** `builtin:zai-coding-plan/GLM-5.2`. (Verificable por el entorno de ejecución; **no es** el modelo que produjo R2.)
- **puede ejecutar archivos:** **SÍ**. Python 3.9.6 (`/usr/bin/python3`, darwin arm64). Ejecuté íntegramente las 5 suites, el escaneo determinista y los 8 canarios nuevos.
- **alcance realmente revisado:** los 14 archivos del `ROUTER-V5-R2-REAUDITORIA-ZCODE-20260726.zip` (cotejados contra `MANIFEST-SHA256.txt`), más `CORPUS_CAMINO_A.zip` descomprimido (362 entradas, raíz `camino-a/`). Lectura completa de `router_v5_R1.py` (744 l.), `router_v5_R2.py` (851 l.), las 5 suites, `scan_corpus_v5.py` y `OT`/`INFORME`. No abrí ningún archivo fuera del zip ni del árbol temporal `/tmp/reaudit_R2`.
- **modo:** sólo lectura. **No modifiqué ningún archivo entregado** (verificado: los 13 hashes del manifiesto siguen coincidiendo tras la auditoría). Sólo **creé** un archivo nuevo — `canaries_zcode_reaudit_R2.py` (los 8 canarios Z01–Z08) — y todo el trabajo se hizo bajo `/tmp`.
- Implementadora R2: **Kimi Code**, modelo exacto **`NO_CONSTA`** (no hay marca interna verificable en `router_v5_R2.py` ni en el informe R2; sólo el campo declarativo en `INFORME-ROUTER-V5-K3-R2.md §1`). Confirmo esa declaración.
- Esta respuesta **no cierra DEUDA-3 ni declara aptitud de producción**; es evidencia para GPT/Codex.

---

## HECHOS (medidos directamente por mí)

### H1. Manifiesto íntegro
Los 13 hashes declarados en `MANIFEST-SHA256.txt` coinciden exactamente con los SHA-256 reales de los archivos (calculados con `shasum -a 256` y re-validados con `hashlib` en Python). El único archivo que no aparece es el propio `MANIFEST-SHA256.txt` (un hash no puede contenerse a sí mismo), lo cual es esperado.

### H2. Las 11 correcciones están en el motor R2
El `diff -u router_v5_R1.py router_v5_R2.py` (+107 líneas, 17 hunks) contiene exactamente los cambios descritos en `INFORME-ROUTER-V5-K3-R2.md §3`, mapeables uno-a-uno a los 11 defectos adjudicados y a R2-DET:

| # | defecto | ubicación en R2 (verificada) |
|---|---|---|
| R2-1 | `getattr(os,'system')` | `PythonAdapter.analyze` l. 499–514 (rama `bmod=="os" and attr.lower() in OSCMD_ATTRS` → `SEC-OSCMD`) |
| R2-2 | `asyncio.create_subprocess_shell` | l. 523–526 (`mod=="asyncio" and lf=="create_subprocess_shell"` → `SEC-SHELL`) |
| R2-3 | `yaml.load_all` | l. 529 (lista ampliada `("load","load_all","full_load","unsafe_load")`) |
| R2-4 | `YOUR_…_HERE` placeholder | `PLACEHOLDER` l. 146–149 (alternativa `your(_[a-z0-9]+)+_here`, anclada `^…$`, `re.I`) |
| R2-5 | secreto por subíndice | helper `_assign_target_name` l. 212–222; uso en `Assign`/`AnnAssign` l. 569–581 |
| R2-6 | `passphrase` | `SECRET_NAME` l. 143–145 (alternativa `passphrase` con `\b`) |
| R2-7 | `ssh host '…'` remoto | `ShellAdapter.SSH_REMOTE` l. 697; uso l. 702–705 |
| R2-8 | posición de comando shell | `strip_shell` splice `; ` l. 448–449, 451–452; `ShellAdapter.DANGEROUS` regex l. 709 |
| R2-9 | secreto en objeto JS | `JsTsAdapter.analyze` regex l. 651 (`["']?(\w+)["']?\s*[:=]…`) |
| R2-10 | `window['eval']` | `_strip_js(keep_ident_strings=)` l. 296–345; `GLOBAL_EVAL` l. 622; uso l. 633–643 |
| R2-11 | `.env` | `EnvAdapter` l. 723–736; registro en `_ADAPTERS[".env"]` l. 755 |
| R2-DET | determinismo | `for mod in sorted(st.modules())` l. 587 |

### H3. Las suites externas NO fueron debilitadas
- `test_router_v5.py`, `adversarial_independent_v5.py`, `scan_corpus_v5.py` conservan **idéntico** SHA-256 al declarado por el informe R1 (coinciden con los hashes publicados en §9 del informe R2). Son inmutables.
- `canaries_k3_preexistentes.py` y `canaries_k3_adjudicated_v5.py` difieren **únicamente** en 1 caso de 20: K3-13, cuya expectativa pasa de `False` a `True`. Lo verifiqué programáticamente (AST `literal_eval` de la lista `CASES`): `(nombre, rel_path, fuente, eje)` idénticos en los 20; sólo el booleano de expectativa cambia en la tupla 12. No se eliminó ni relajó ningún otro caso.

### H4. Reproducción exacta de las 5 suites (router_v5 = R2, PYTHONPATH=outputs)
Layout de ejecución: `outputs/router_v5.py` = copia bit-idéntica de `router_v5_R2.py` (SHA `771b67…e267c0`), suites junto al router, `audit_k3/canaries_k3.py` dos niveles abajo (como espera su loader por ruta).

| # | suite | esperado OT | observado | exit |
|---|---|---|---|---|
| 1 | `test_router_v5.py` | 75/75 | **75 PASS / 0 FAIL** | 0 |
| 2 | `adversarial_independent_v5.py` | 21/21 | **21 PASS / 0 FAIL** | 0 |
| 3 | `audit_k3/canaries_k3.py` (originales) | 19/20, único FAIL = K3-13 | **19 PASS / 1 FAIL** (FAIL: K3-13, `contratos`, FP) | 1 |
| 4 | `canaries_k3_adjudicated_v5.py` | 20/20 | **20 PASS / 0 FAIL** | 0 |
| 5 | `canaries_zcode_regression_v5.py` | 13/15, sólo N04/N05 | **13 PASS / 2 FAIL** (FAIL: N04 y N05, ambos FN `seguridad`) | 1 |

Los resultados **coinciden uno-a-uno** con la tabla §2 del informe R2. K3-13 es el único FAIL de la suite original y se debe a `CTR-FORMAT` (`.json` ∈ `CONTRACT_EXTS`); N04/N05 son los FN de resolución dinámica documentados.

### H5. Las correcciones son reales (delta R1→R2 observable)
Ejecuté las tres suites K3/ZCode **también bajo R1** (sustituyendo `outputs/router_v5.py` por `router_v5_R1.py`):
- Bajo R1, la suite original K3 da **8 PASS / 12 FAIL**: fallan K3-03, K3-07, K3-08, K3-09, K3-10, K3-12, K3-13, K3-14, K3-15, K3-17, K3-18, K3-19 — los 11 defectos adjudicados (K3-13 = desacuerdo contractual; los otros 11 = las 10 correcciones R2-1…R2-10 más R2-11 vía K3-19).
- Bajo R2, sólo K3-13 sigue fallando (contrato). Por tanto cada corrección R2 elimina exactamente el FAIL que se le adjudica, sin introducir nuevos.

### H6. K3-13 pertenece a `contratos` por contrato arquitectónico
`_critical_path_rules` (l. 772–773): `if p.suffix in CONTRACT_EXTS: hits.append(("contratos","CTR-FORMAT",p.suffix))`, con `CONTRACT_EXTS ⊃ {".json"}` (l. 117). Verificado: `axes_of("ui_config.json", '{"name":"theme",...}')` → `['contratos']`, decisión `critical`, evidencia `CTR-FORMAT/.json`. Es independiente del contenido. La expectativa `contratos=False` del canario externo original es, por tanto, incompatible con el contrato vigente; el informe R2 no la "corrige" en el archivo original (lo deja en FAIL deliberado) y sólo ajusta la copia adjudicada. **Cumple el punto 5 de la OT.**

### H7. Escaneo determinista (punto 7 de la OT)
Layout: `outputs/inputs/camino-a/` (corpus descomprimido). `scan_corpus_v5.py` escribe `axis_matrix_v5_current.json`.
- `PYTHONHASHSEED=0` → SHA `2a9a0180…f7a4256b`
- `PYTHONHASHSEED=12345` → SHA `2a9a0180…f7a4256b` (**idéntico**)
- `diff` byte-a-byte de las dos matrices: **idéntico**. `stdout` también idéntico.
- El hash coincide con el `axis_matrix_v5_R2.json` **publicado** en el zip.
- Verificación adicional: también probé `seed=1` y `seed=99999` y `seed=aleatorio` → todas dan `2a9a0180…`. **R2 es determinista en 5 semillas.**
- `n=148` y **148 filas** en `rows` (coinciden).
- `domain_rules_hash = 45a984eb…4d77c06` (idéntico a R1 — `DOMAIN_RULES` intacta).

### H8. Determinismo R2-DET confirmado por contraste con R1
Regeneré la matriz **bajo R1** con varias semillas: el hash varía (`0f9e04…`, `c34f48…`, `68d967…`) y **ninguno** coincide con el `axis_matrix_v5_R1.json` publicado (`78fd…`), que fue generado con una semilla no registrada. Esto confirma empíricamente la afirmación del informe: R1 **no** era determinista; R2 **sí** (gracias a `sorted(st.modules())`).

### H9. Diff de matriz R1→R2 (punto 7 de la OT)
Sobre los 148 archivos, comparación fila a fila:
- **0** archivos con cambio de asignación de ejes.
- **0** archivos con cambio de decisión o score.
- **4** archivos difieren sólo en el **ORDEN** de la evidencia (mismo conjunto, misma decisión, mismo score):
  - `runtime/scripts/camino_b_gateway.py` (seguridad: `ssl`↔`hmac`)
  - `runtime/scripts/camino_b_slot14_bridge.py` (seguridad)
  - `runtime/scripts/peer_executor.py` (seguridad)
  - `runtime/tests/test_resource_scheduler.py` (concurrencia: `subprocess`↔`shlex`)

  Exactamente los 4 nombrados en el informe §7, y todos explicados por R2-DET (evidencia `import:*` ahora alfabética).

### H10. Invariantes sobre la matriz R2
- **0** ejes fuera del registro declarado (`{seguridad, concurrencia, tests_observabilidad, contratos, rendimiento_recursos, volume_generalist}`).
- **0** archivos donde `volume_generalist` coexiste con un eje específico.
- **0** evidencias con `source` fuera del conjunto declarado (`{critical_rule, content, ast, import, identifier, coverage}`).
- JSON válido (cargado sin excepción por `json.load`).

### H11. 8 canarios nuevos (punto 6 de la OT) — creados y ejecutados
Archivo creado: `canaries_zcode_reaudit_R2.py` (Z01–Z08), disjunto por `(rel_path, fuente)` y por nombre de los 76 casos existentes (21 + 20 + 20 + 15). Cada uno apunta a un borde distinto de una corrección R2:

| canario | borde apuntado | esperado | observado |
|---|---|---|---|
| Z01 | R2-1: `getattr(os,'popen')` (`popen` ∈ `OSCMD_ATTRS`, no cubierto antes) | `seguridad=True` | PASS |
| Z02 | R2-2: `create_subprocess_exec` **no** debe ser SEC-SHELL (sólo concurrencia) | `seguridad=False` | PASS |
| Z03 | R2-3: `yaml.load_all(...,Loader=yaml.BaseLoader)` es seguro por origen | `seguridad=False` | PASS |
| Z04 | R2-5: subíndice anidado `cfg['auth']['token']=…` (slice externo = `'token'`) | `seguridad=True` | PASS |
| Z05 | R2-6+R2-9: `passphrase` en JS con clave entre comillas dobles | `seguridad=True` | PASS |
| Z06 | R2-7: `ssh -i key host 'wget …'` con opciones antes del host | `seguridad=True` | PASS |
| Z07 | R2-8: `(curl …)` subshell dispara; `mycurl` (palabra compuesta) no | `seguridad=True` | PASS |
| Z08 | R2-11: `.env` con `PASSWORD=hunter2 # comment` (valor antes de `#`) | `seguridad=True` | PASS |

**Resultado: 8 PASS / 0 FAIL** (exit 0).

### H12. No hallazgos de bordes nuevos que rompan el contrato
Probé adicionalmente (fuera de los 8 canarios, como exploración de bordes) variantes por cada corrección: alias de módulo (`import os as o`), atributo dinámico (`getattr(os, n)`), `create_subprocess_exec`, loaders seguros/espurios, placeholders en mayúsculas/minúsculas y con varios segmentos, subíndices con clave variable/entera/anidada, `passphrase` con sufijo, `ssh` midpipe y comillas dobles, posición de comando (`|`, `;`, `&&`, backtick, `$()`, subshell, indentación, `;curl` sin espacio, `mycurl`/`curlx`), clave JS en comentario/counter/placeholder, `window['Eval']`/`this['eval']`/concat dinámica, y `.env` con placeholder/counter/numérico/vacío/`.env.example`. **Todas las FN adicionales que observé coinciden con las ya declaradas en el informe §8** (R2-7 ssh midpipe/doble-comilla, R2-8 `then curl`, R2-10 mayúsculas/`this`/concat/unicode, R2-4 otras convenciones, R2-11 `.env.example`). **No encontré FP nuevos** más allá de un caso teórico ya declarado (`globalThis.window['eval']`, que dispara por la sub-expresión `window[eval]` — sigue siendo eval global, así que la señal es legítima, no un FP real).

---

## INFERENCIAS (deducidas de los hechos, con la lógica explícita)

- **I1.** Las correcciones están en el **motor** y no en los resultados esperados: el diff R1→R2 muestra cambios de código (regex, helper, nueva rama, nuevo adapter) y los resultados de las suites bajo R1 muestran los 12 FAIL que desaparecen bajo R2 — es decir, el motor cambió de comportamiento, no se retocaron esperados.
- **I2.** Las correcciones son **acotadas y dirigidas**: cada hunco del diff corresponde a un único defecto; no hay cambios colaterales al motor fuera de los 11 + R2-DET. El `domain_rules_hash` idéntico R1=R2 confirma que `DOMAIN_RULES` no se tocó.
- **I3.** R2-DET es una corrección **pura de orden** (no de semántica): la evidencia de los 4 archivos que cambian entre R1 y R2 tiene el mismo conjunto, misma decisión y mismo score; sólo varía el orden alfabético de la evidencia `import:*`. La función `axes_of` (que opera sobre conjuntos) es insensible a ese cambio.
- **I4.** K3-13 es un **desacuerdo contractual legítimo**, no un defecto: `.json` siempre genera `CTR-FORMAT` por sufijo, con independencia del contenido. Reabrirlo requeriría cambiar `CONTRACT_EXTS` o la regla `CTR-FORMAT`, i.e. cambiar el contrato arquitectónico. La OT explícitamente no lo pide.
- **I5.** N04/N05 son **límites dinámicos genuinos**: ambos requieren resolver el módulo que devuelve una llamada (`__import__`, `importlib.import_module`) e introducirlo en la tabla de símbolos. Eso es análisis interprocedural/dinámico, fuera del alcance declarado de R2. La OT punto 8 sólo los reabre como bloqueantes si se aporta "impacto arquitectónico concreto y una corrección acotada sin análisis interprocedural general"; no aporto tal corrección (no existe una obvia y segura), así que **no los reabro como bloqueantes**.
- **I6.** Las correcciones **no introdujeron regresiones** en las 5 suites existentes ni en los 8 canarios de borde nuevos: bajo R2, 75/75 + 21/21 + 20/20 (adjudicada) + 8/8 (ZCode-reaudit) PASS, y los FAIL restantes (K3-13, N04, N05) son exactamente los esperados/especificados.
- **I7.** El informe R2 es **fiel** a lo medido: los 6 comandos de su §2, los hashes de §9, los 4 archivos con reorder de §7 y los riesgos residuales de §8 coinciden con mi reproducción independiente.

---

## HIPÓTESIS (no verificadas directamente; señaladas como tales)

- **Hp1.** La marca interna del modelo R2 es **NO_CONSTA** por diseño del entregable (no hay watermark ni metadato). No puedo verificar la identidad "Kimi Code" más allá del campo declarativo del informe; lo tomo como afirmación del autor, no como hecho verificado.
- **Hp2.** El `axis_matrix_v5_R1.json` publicado fue **probablemente** generado con un `PYTHONHASHSEED` no registrado y un Python posiblemente distinto al mío (3.9.6). Bajo mi R1 con seed 0/1/12345 no reproduje ese hash exacto, aunque sí el mismo *contenido* (mismos ejes/decisiones/scores/conjunto de evidencia). Si un consumidor exige reproducibilidad bit-exacta de R1, esto es una **debilidad documental de R1**, no de R2; R2 sí es reproducible bit-exacto.
- **Hp3.** Los FN residuales declarados (ssh midpipe/doble-comilla, `then curl`, `window['Eval']`, `this['eval']`, concat dinámica, `.env.example`) son **probablemente** aceptables para el uso previsto (detección de señales, no verificación formal), pero su aceptabilidad final es una decisión de producto (GPT/Codex), no de esta auditoría.
- **Hp4.** No realicé fuzzing amplio ni benchmarks (la OT los prohíbe explícitamente). Por tanto, **no puedo descartar** FP/FN raros fuera de los bordes explorados; mi confianza se circunscribe a los bordes probados.

---

## Fallos nuevos encontrados

**Ninguno reproducible.** No aporto ningún fallo nuevo con caso mínimo que rompa el contrato vigente. Los únicos "fallos" observados (K3-13, N04, N05) son los ya declarados y especificados por la OT/Informe, no hallazgos de esta auditoría.

---

## Pruebas restantes sugeridas (sólo las imprescindibles)

- Ninguna imprescindible para decidir adjudicación. Opcional, si GPT/Codex lo desea: (a) reabrir formalmente N04/N05 sólo si alguien propone una corrección acotada y segura; (b) registrar el `PYTHONHASHSEED` y versión de Python con los que se generó R1, para trazabilidad documental.

---

## VEREDICTO

De los tres permitidos por la OT, y con el alcance efectivamente revisado:

## `APTO_PARA_ADJUDICACION_GPT`

**Fundamentación acotada:** manifiesto íntegro; las 11 correcciones + R2-DET están en el motor y son reales (delta R1→R2 observable); las 5 suites se reproducen exactamente como especifica la OT (75/75, 21/21, 19/20 con K3-13 único desacuerdo contractual, 20/20, 13/15 con sólo N04/N05); matriz determinista en 5 semillas con `n=148`, 0 cambios de ejes/decisiones/scores R1→R2 (sólo 4 reordenamientos de evidencia explicados), 0 invariantes violadas; 8 canarios nuevos de borde disjuntos dan 8/8 PASS; sin FP/FN nuevos más allá de los declarados; sin regresiones; suites externas no debilitadas. No cierro DEUDA-3 ni declaro aptitud de producción — eso queda fuera de esta auditoría, como manda la OT.

---

**Notas operativas:**
- El archivo nuevo `canaries_zcode_reaudit_R2.py` quedó en `/tmp/reaudit_R2/canaries_zcode_reaudit_R2.py` (y una copia en `/tmp/reaudit_R2/outputs/`). No está en el zip ni modifies nada entregado; si lo querés preservar, copialo a tu repositorio.
- Todos los comandos se ejecutaron con `PYTHONPATH=outputs` y `outputs/router_v5.py` = `router_v5_R2.py` bit-idéntico, según el punto 3 de la OT.
