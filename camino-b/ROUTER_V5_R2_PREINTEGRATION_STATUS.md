# Camino B — estado frente a ROUTER v5 R2

Fecha: 2026-07-26.

No se requieren cambios en Camino B durante el cierre de la arquitectura local.

Camino B conserva su responsabilidad de transporte/ejecución. Sus componentes
viven físicamente en `../camino-a/runtime/`, pero la integración propuesta del
router opera sobre el snapshot candidato y la evidencia de Camino A.

Hasta que se adjudique el rol semántico del router:

- no tocar `camino_b_gateway.py`;
- no tocar `camino_b_slot14_bridge.py`;
- no tocar `camino_b_outbound_agent.py`;
- no modificar `path_roles.json` para introducir ejes;
- no duplicar el router dentro de Camino B.

Evidencia:

- `../shared/threads/2026-07-26-ZDESK-MAPEO-PREVIO-ROUTER-V5-R2.md`
- `../shared/audits/router-v5-r2/`
