# ROUTER v5 R2 — checkpoint auditado

Este directorio preserva el mínimo reproducible del router semántico antes de
cualquier integración con Camino A/B.

## Estado

- Implementador: Kimi Code.
- Modelo exacto del implementador: `NO_CONSTA`.
- Reauditor externo: ZCode.
- Modelo exacto del reauditor: `builtin:zai-coding-plan/GLM-5.2`.
- Adjudicación: apto para integración controlada.
- No implica aptitud de producción ni integración efectuada.

## Resultados reproducidos

- `test_router_v5.py`: `75/75 PASS`.
- `adversarial_independent_v5.py`: `21/21 PASS`.
- `audit_k3/canaries_k3.py`: `19/20`; único desacuerdo K3-13.
- `canaries_k3_adjudicated_v5.py`: `20/20 PASS`; sólo cambia la expectativa
  de K3-13, manteniendo nombres, rutas, fuentes y ejes.
- `canaries_zcode_regression_v5.py`: `13/15`; N04/N05 quedan documentados
  como límites de resolución dinámica.
- Reauditoría ZCode adicional: ocho canarios nuevos Z01–Z08, `8/8 PASS`.

El archivo ejecutable temporal de Z01–Z08 no sobrevivió en `/tmp`. Sus
definiciones y resultados están preservados en
`REAUDITORIA-ZCODE-GLM-5.2.md`. No se afirma que exista una suite ejecutable
permanente para esos ocho casos.

## Contrato

El router clasifica archivos y emite evidencia, `volume_generalist`, obligación
transversal de correctitud y `domain_rules_hash`. No implementa TaskCards,
scheduling, agentes, concurrencia, fan-out, fan-in ni integración con Caminos.

El informe de mapeo previo de ZDesk se preserva en:

`../../threads/2026-07-26-ZDESK-MAPEO-PREVIO-ROUTER-V5-R2.md`

Su veredicto es `BLOQUEADO_POR_DECISION_ARQUITECTONICA`: el Camino A actual
orquesta slots y proveedores sobre el snapshot completo y todavía no consume
el router.

## Ejecución

Desde este directorio:

```bash
PYTHONPATH=. python3 test_router_v5.py
PYTHONPATH=. python3 adversarial_independent_v5.py
PYTHONPATH=. python3 audit_k3/canaries_k3.py
PYTHONPATH=. python3 canaries_k3_adjudicated_v5.py
PYTHONPATH=. python3 canaries_zcode_regression_v5.py
```

Los códigos distintos de cero de las suites original K3 y ZCode son esperados
únicamente si los fallos son exactamente K3-13 y N04/N05, respectivamente.

## Integridad SHA-256

```text
ab57917c61d866a73f6ea12c47c1e576b27a6fb9cbbe56b4446d63fbbefea0c2  INFORME-ROUTER-V5-K3-R2.md
daeb41ed0ce7b8e31dc272a9f93b9c6fc7656ff34df4a53b65815a7983e06720  REAUDITORIA-ZCODE-GLM-5.2.md
09679180e2e76c20dc2f2306000daa53929a2d837a1ad51b951fbe147f70576c  adversarial_independent_v5.py
2eb454eeed3d1fb9b7c752ae264a7a37eedde1879b2dd42c9970a7d84c4c208d  canaries_k3_adjudicated_v5.py
e15228b16c943f7dc52ceaf93922099d8a2d97083e00aa30a6fa7e08b47789ba  audit_k3/canaries_k3.py
a1c6b592444ab9411dfcbc9628d5a204daa1e56edcd9c0f346ec44125e8c0bb5  canaries_zcode_regression_v5.py
771b672781cc1da64ea1e941e2db323aaf1b06d9d169fec111306da9e0e267c0  router_v5.py
b677b3ee7acd154a200f191f9419809f616d28641a99e51e74314e144db62ad6  scan_corpus_v5.py
eabb3bf597520d6c08b1516676add2d712d14eb40ba23a745650fc75d9c707f0  test_router_v5.py
```
