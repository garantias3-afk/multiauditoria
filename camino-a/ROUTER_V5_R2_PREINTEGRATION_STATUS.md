# Camino A — estado previo a integrar ROUTER v5 R2

Fecha: 2026-07-26.

## Estado

No hay integración funcional del router.

El análisis de sólo lectura de ZCode/GLM-5.2 verificó que el runtime actual:

- orquesta 14 slots y lanes por proveedor;
- entrega el snapshot completo a los workers;
- no contiene TaskCards ni packets por eje;
- no contiene `router_v5`, `axes_of`, `axis_matrix` ni
  `domain_rules_hash`;
- no materializa seis workers especializados ni `num_ctx=65536`.

Por tanto, copiar el motor no lo integraría y podría fijar prematuramente un
modelo de ejecución distinto del actual.

## Decisión pendiente

Antes de escribir código debe decidirse el rol del router:

1. particionado por eje, que requiere una arquitectura nueva;
2. enriquecimiento de prompts/evidencia sin particionar;
3. trazabilidad/observabilidad únicamente.

El mapeo de ZDesk considera coherentes 2 o 3 con el Camino A actual y deja 1
fuera de alcance hasta que se cierre el ejecutor local de OpenClaw.

## Regla temporal

- No modificar `13_WORKER_BUS`, wrappers, slots ni Camino B por esta deuda.
- No copiar todavía `router_v5.py` a `runtime/scripts/`.
- Cerrar primero la arquitectura local en OpenClaw.
- Retomar después este mapeo y adjudicar el rol semántico del router.

## Evidencia versionada

- `../shared/threads/2026-07-26-ZDESK-MAPEO-PREVIO-ROUTER-V5-R2.md`
- `../shared/audits/router-v5-r2/`
