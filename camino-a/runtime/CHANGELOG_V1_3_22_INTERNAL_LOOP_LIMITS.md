# Changelog — v1.3.22-slot1-slot4-six-loops

## Cambio canónico

- Los bucles internos agentic de los slots 1 y 4 pasan de diez a seis
  iteraciones: `candidate.001`–`candidate.006`.
- Los slots 7 y 8 conservan `candidate.001`–`candidate.010`.
- El runtime continúa leyendo `internal_loop.max_iterations` desde el canon; no
  existe un límite seis hardcodeado en el motor ni una alteración de los loops
  externos de slots 3, 6, 10, 11, 12, 13 y 14.

## Sincronización Camino A / Camino B

- El contrato compartido y la entrega de preauditoría describen límites por
  slot y aplican la misma regla a ambos caminos.
- Las Instructions de GPT Cerebro Camino A y GPT Auditor Externo Camino B
  exigen `.001`–`.006` en slots 1/4 y `.001`–`.010` en slots 7/8.
- El protocolo de evaluación Sol/Actions incorpora una comprobación A/B de los
  límites internos.

## Compatibilidad y evidencia

- Se conserva la secuencia auditar → corregir/reescribir → testear → reauditar
  → decidir y la entrega de deuda residual al agotar el límite.
- Se agregan pruebas explícitas del mapa `{1: 6, 4: 6, 7: 10, 8: 10}` y de las
  Instructions de ambos GPT.
