# Protocolo canónico de cambios v1

## Alcance

Este protocolo rige cualquier cambio de roles, slots, rutas, fallbacks,
contratos, esquemas, transporte, políticas de RAM o autoridad de Camino A y
Camino B. Evita que prompts, Knowledge, runtime y paquete publicado diverjan.

## Secuencia obligatoria

1. Modificar primero las fuentes normativas bajo `canon/` y las políticas
   estructuradas bajo `config/`; nunca corregir sólo un archivo generado.
2. Mantener idéntico `canon_version` en rutas, slots y runtime. Un cambio que
   afecte autoridad, identidad o ejecución debe incrementar la versión.
3. Sincronizar `contracts/CAMINO_SHARED_CONTRACT.md` con el contrato canónico y
   regenerar los nueve archivos de `generated/` mediante
   `scripts/render_contracts.py`.
4. Validar ambos perfiles productivos y el perfil de sandbox con
   `scripts/canon_loader.py`; referencias inexistentes o rutas deshabilitadas
   sin fallback independiente fallan cerrado.
5. Reconstruir `CAMINO_A_OVERNIGHT_KNOWLEDGE_CURRENT.md` y su manifest desde la
   lista cerrada de fuentes. Verificar versión, tamaño, SHA-256 y hashes de cada
   fuente antes de publicar.
6. Ejecutar la suite completa, el smoke mecánico y las pruebas operativas que
   el cambio permita. Separar siempre evidencia simulada, sandbox y live.
7. Registrar deudas y dependencias externas como `FALLÓ` o `NO PROBADO`; nunca
   promoverlas a `VERIFICADO` por inferencia.
8. Empaquetar sólo después de los checks de sincronía. El manifest de release y
   el sidecar SHA-256 son la autoridad del ZIP entregado.

## Reglas de seguridad

- OpenAI API y Claude API permanecen prohibidas mientras el canon no cambie de
  forma explícita; las suscripciones CLI no se sustituyen con claves API.
- SQLite, WAL, locks y leases son locales. Drive transporta sólo bundles
  inmutables cerrados; un cambio de esta regla requiere un diseño de consenso
  y pruebas de doble coordinador.
- Las rutas remotas requieren identidad de host estricta, clave dedicada,
  `BatchMode` y guard de recursos ejecutado en el host que posee la RAM.
- Slot 14 conserva orden secuencial: Claude CLI primario; Codex por suscripción
  sólo después de indisponibilidad de Claude registrada.
- Un output sólo cuenta si liga run, slot y SHA del candidato y pasa manifest,
  hashes, secretos, cambios de workspace y autoridad terminal.

## Criterio de cierre del cambio

El cambio queda integrado sólo cuando canon, contratos, generados, Knowledge,
tests y manifest coinciden. La disponibilidad de servicios externos se declara
por separado y exige prueba viva; un paquete coherente no demuestra por sí solo
operación productiva de extremo a extremo.
