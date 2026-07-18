# Robot Desktop

Cliente delgado para el Core local de Robot. La UI usa React + TypeScript + Vite y la envoltura de escritorio usa Tauri v2. Sólo habla con la CORE-API por HTTP/SSE: no importa SDKs de LLM, no conoce proveedores, no guarda claves de proveedores y no ejecuta herramientas.

## Puesta en marcha

Requisitos para la UI y el Mock Core: Node.js y npm. Para la aplicación nativa también hacen falta Rust/Cargo y las dependencias de plataforma de Tauri v2.

```bash
cd apps/desktop
npm ci
```

Terminal 1 — Mock Core vivo:

```bash
npm run mock
```

El mock escucha en `http://127.0.0.1:8850`. Si no se define `ROBOT_API_TOKEN`, imprime y usa el token de desarrollo `robot-mock-token`.

Terminal 2 — aplicación Tauri:

```bash
npm run tauri dev
```

En Ajustes, usar la URL y el token del mock. La misma UI puede servirse sin Tauri:

```bash
npm run dev
```

Build web/typecheck y build nativo:

```bash
npm run build
npm run tauri -- build
```

El segundo comando requiere Rust/Cargo; no fue posible ejecutarlo en el entorno de esta entrega porque ese toolchain no está instalado.

Tests:

```bash
npm test
npm run test:integration
```

Baseline Python del repositorio, ejecutado sin modificar Python:

```bash
cd ../../camino-a/runtime
python3 -m pytest -p no:libtmux tests
```

## Pantallas y comportamiento

- D1 Chat: markdown GFM, highlight de código, copia al portapapeles, streaming por tokens, Enter para enviar y Shift+Enter para nueva línea. Adjunta archivos por selector o drag & drop, sube multipart y envía sólo `file_id`; las imágenes elegidas tienen preview `blob:` local. “Detener” llama a `/interrupt` y sólo declara interrumpido después de `{ok:true}`.
- D2 Actividad: timeline por turno para `tool_start`/`tool_end`, argumentos y resultados colapsables, duración observada por el cliente y estado explícito “resultado no verificable” si el stream termina con una tool abierta. `research_progress` muestra iteración, consultas, fuentes y costo.
- D3 HITL: `confirm_request` abre un modal con foco atrapado, rechazo enfocado por defecto, argumentos y botones Aprobar/Rechazar/Detener. No autoaprueba ni recuerda decisiones. Los eventos recibidos durante el ACK se retienen; un ACK perdido corta fail-closed y no permite repetir un efecto incierto.
- D4 Cerebro y costo: escalón, identidad y costo de `/brains`; `brain_switch` agrega un aviso inline con motivo e identidad. VIBE tiene advertencia visual de alto costo. `tier_hint` y `wants_cheap` se mandan por turno.
- D5 Historial: IDs recientes locales por URL del Core, nueva sesión y retomar por ID mediante `GET /session/{id}`. El contrato no ofrece un endpoint para listar sesiones.
- D6 Ajustes: URL loopback, token sólo en memoria y prueba real de `/healthz`. Editar los campos invalida el resultado del test anterior. No existen campos de API keys de LLM.

## Seguridad y errores

- Sólo se aceptan `localhost`, `127.0.0.1` y `::1`, por HTTP o HTTPS. La CSP de Tauri limita `connect-src` a esos destinos.
- El token vive únicamente en estado React; `localStorage` contiene sólo URL e IDs de sesión. El test UI usa un token centinela y comprueba todas las claves y valores persistidos.
- Markdown ignora HTML, bloquea imágenes remotas y abre enlaces con aislamiento y sin referrer.
- El parser acepta exclusivamente los ocho eventos contractuales, valida campos obligatorios y limita cada frame SSE a 1 MiB, incluido overhead y líneas vacías.
- Un corte SSE nunca reenvía `POST /message`: consulta `/healthz` y `GET /session/{id}` para reconciliar sin duplicar efectos. La UI marca el snapshot como no verificable porque el contrato no expone cursor, estado terminal ni reanudación.
- Requests JSON, uploads, confirmaciones e interrupciones tienen deadline de 15 segundos. Readers, timers, abort controllers y URLs `blob:` tienen cleanup.
- Cambiar sesión o credenciales descarta texto, adjuntos, tier y modo barato del borrador anterior. Cambiar un token ya configurado avisa que se quitarán IDs recientes de esa URL; nunca borra sesiones del Core.

## Mock Core

`mocks/server.ts` implementa exactamente las rutas consumidas por la app:

- `POST /session`
- `GET /session/{id}`
- `POST /session/{id}/message`
- `POST /session/{id}/confirm`
- `POST /session/{id}/interrupt`
- `POST /upload`
- `GET /brains`
- `GET /healthz`

El turno scripteado emite tokens, `brain_switch`, dos `research_progress`, `confirm_request` y, sólo tras aprobación confirmada, `tool_start`, `tool_end` y `final`. En rechazo emite un `final` sin ninguna ejecución. El `auditLog` interno de tests demuestra el orden confirmación → ejecución y la ausencia de ejecución en rechazo.

## Estructura completa

```text
apps/desktop/
├── .gitignore
├── AUDIT_LOG.md
├── README.md
├── index.html
├── package-lock.json
├── package.json
├── tsconfig.json
├── vite.config.ts
├── mocks/
│   └── server.ts
├── src-tauri/
│   ├── Cargo.toml
│   ├── build.rs
│   ├── capabilities/default.json
│   ├── src/lib.rs
│   ├── src/main.rs
│   └── tauri.conf.json
├── src/
│   ├── App.tsx
│   ├── main.tsx
│   ├── styles.css
│   ├── vite-env.d.ts
│   ├── components/
│   │   ├── ActivityPanel.tsx
│   │   ├── BrainStatus.tsx
│   │   ├── Composer.tsx
│   │   ├── ConfirmationDialog.tsx
│   │   ├── MarkdownMessage.tsx
│   │   ├── SessionSidebar.tsx
│   │   └── SettingsDialog.tsx
│   ├── core/
│   │   ├── api.ts
│   │   ├── recovery.ts
│   │   ├── sse.ts
│   │   └── types.ts
│   ├── state/chatReducer.ts
│   └── utils/
│       ├── format.ts
│       └── storage.ts
└── tests/
    ├── api.test.ts
    ├── app.hitl.integration.test.ts
    ├── chatReducer.test.ts
    ├── format.test.ts
    ├── markdown.test.ts
    ├── mock.integration.test.ts
    ├── sse.test.ts
    ├── storage.test.ts
    ├── tauri-config.test.ts
    └── types.test.ts
```

Los archivos de este árbol contienen la implementación completa; no hay secciones omitidas ni marcadores de “resto igual”. `node_modules/`, `dist/`, cobertura y `src-tauri/target/` son generados y están ignorados.

## Riesgos abiertos dependientes del Core/entorno

1. El Core real aún no existe; las pruebas de transporte son contra el mock Node local.
2. El contrato no define cursor/Last-Event-ID, endpoint de reanudación ni clave de idempotencia para `/message`. Por seguridad se reconcilia con GET y nunca se reenvía el POST, pero no puede continuarse el mismo SSE.
3. La forma interna de `turns:[...]` no está especificada. El historial se normaliza defensivamente y una recuperación queda marcada “estado final no verificable”.
4. No hay endpoint para listar sesiones. Los IDs se guardan por URL, y como el token no se persiste la app no puede atribuirlos criptográficamente a una credencial después de reiniciar.
5. El contrato no incluye IDs de invocación para tools; pares repetidos se correlacionan por nombre y orden dentro del turno.
6. CORS, Private Network Access, límites/tipos de upload y comportamiento de WebView deben validarse contra el Core real.
7. No se verificó el bundle nativo, firma, notarización ni instaladores: Rust/Cargo no están presentes en este host.
8. El build web conserva una advertencia no bloqueante: el chunk principal minificado supera 500 kB.
9. La inspección visual cubrió layout principal y Ajustes; el navegador de inspección no pudo completar llamadas a un segundo puerto loopback en ese entorno, por lo que el flujo real allí queda cubierto por pruebas HTTP/SSE y no por una prueba visual end-to-end.

## No hecho

- No se integró ningún LLM, SDK de proveedor, API key de proveedor ni lógica de IA.
- No se ejecutan herramientas ni accesos directos al filesystem desde React/Rust; toda acción pertenece al Core.
- No se modificó código Python.
- No se ejecutó `git push` ni `--amend`.
- No se afirma ausencia de bugs; ver [AUDIT_LOG.md](./AUDIT_LOG.md) para evidencia y techo de verificación.
