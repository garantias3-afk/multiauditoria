# Auto-auditoría acotada

Fecha: 2026-07-18. Alcance: sólo `apps/desktop/` y baseline de regresión existente. Máximo usado: 3 vueltas. No se modificó Python.

Resultado estabilizado: `npm run build` pasa, Vitest pasa 77/77 en 10 archivos y el baseline pasa 112/112. Se resolvieron **35 hallazgos agrupados** que se listan abajo. Esto no significa ausencia de bugs; el Core real, el bundle nativo y Camino A siguen siendo filtros posteriores.

## Vuelta 1

Validación previa a la revisión:

- `npm run build`: pasó; 503 módulos. Advertencia no bloqueante por chunk principal >500 kB.
- `npm test -- --reporter=verbose`: 35/35, 6 archivos.
- `python3 -m pytest -p no:libtmux tests` desde `camino-a/runtime`: 112/112.

La revisión adversarial encontró problemas sustantivos en HITL, interrupción, SSE, recuperación, persistencia, cleanup y cobertura. Se corrigieron y se volvió al paso 1.

## Vuelta 2

Validación previa a la revisión:

- `npm run build`: pasó; misma advertencia de tamaño.
- Vitest: 70/70, 8 archivos.
- Baseline correcto desde `camino-a/runtime`: 112/112.

Transparencia sobre comandos inválidos durante esta vuelta: antes de ejecutar el baseline correcto se intentó `tests` desde la raíz (ruta inexistente), luego se incluyeron por error scripts autocontenidos que hacen `SystemExit` al importarse, y después se apuntó al directorio correcto desde el cwd incorrecto, donde fallaron imports `scripts`. Fueron errores de invocación, no regresiones de producto; no se contaron como verdes y quedaron reemplazados por la ejecución 112/112 desde el cwd requerido.

La segunda revisión adversarial encontró carreras combinadas ACK/interrupt, pérdida de evidencia terminal, cobertura de recovery, un test muerto y detalles menores de Markdown/mock. Se corrigieron y se inició la tercera vuelta.

## Vuelta 3

Primera ejecución:

- `npm run build`: pasó.
- Vitest: 76/77; falló la prueba de interrupción incierta porque un abort ya manejado sobrescribía el mensaje fail-closed con el error genérico `This operation was aborted`.

Corrección: se agregó una marca imperativa para distinguir aborts de stream ya presentados por su handler. Se repitió el test UI específico (9/9), luego el ciclo completo:

- `npm run build`: pasó; 503 módulos, CSS 27.47 kB, JS 580.89 kB; sólo la advertencia >500 kB.
- `npm test -- --reporter=verbose`: **77/77**, 10 archivos.
- `python3 -m pytest -p no:libtmux tests` desde `camino-a/runtime`: **112/112** en 5.58 s.
- `git diff --check -- apps/desktop`: sin errores.
- Diff Python: vacío.
- Escaneo de imports/SDKs prohibidos: no encontró SDKs de LLM ni Electron; las únicas referencias a `ROBOT_API_TOKEN`/Authorization pertenecen al contrato y al mock.
- `tauri info`: detectó Node/npm y la configuración, pero confirmó que Rust/Cargo/Xcode no están instalados; por eso no se afirma un build nativo.

Después de la corrección y relectura final no quedaron hallazgos críticos/medios conocidos dentro del alcance estático. Los límites no verificables están en README → Riesgos abiertos.

## 35 hallazgos resueltos

1. El handler HITL esperaba una promesa de decisión dentro del callback y dejaba de leer el SSE; ahora el reader continúa y la pausa es de estado/UI.
2. Eventos recibidos antes de una decisión podían avanzar el reducer; ahora son violación de protocolo y cancelan fail-closed.
3. Una tool emitida después de rechazo podía quedar neutralizada por el orden del reducer; ahora se detecta imperativamente y el mock prueba cero ejecución.
4. Una confirmación seguía accionable después de perder el SSE; ahora el corte invalida el modal y no permite efectos sin canal de resultado.
5. Un ACK perdido de `/confirm` habilitaba reintentos ambiguos; ahora corta el stream y retira ambos botones.
6. Un `final` podía llegar antes que el ACK y perderse al limpiar refs; ahora los eventos quedan retenidos y se aplican sólo tras `{ok:true}`.
7. “Detener” marcaba stop antes de verificar `{ok:true}` y descartaba eventos; ahora el estado cambia después del ACK.
8. Si fallaba `/interrupt` durante una decisión incierta, HITL reaparecía; ahora cualquier decisión incierta corta fail-closed.
9. Si `/interrupt` tenía éxito después de que tool/final ya llegaron, la cola se descartaba; ahora se conserva la evidencia y el terminal recibido es autoritativo.
10. Un error terminal concurrente podía ocultarse como “Interrumpido”; ahora el mensaje y estado error permanecen visibles junto con el ACK de interrupt.
11. El ACK tardío de interrupt podía rebautizar un error histórico; ahora sólo considera el assistant actual y nunca atraviesa un turno completo.
12. Doble clic podía duplicar sesión, envío, confirmación o interrupción; refs síncronas bloquean duplicados antes del siguiente render.
13. JSON, upload, confirm e interrupt podían quedar colgados; ahora tienen deadline de 15 segundos y AbortSignal padre.
14. Errores de parser/callback/content-type/HTTP no cancelaban siempre el body/reader; ahora el cleanup es best-effort en todos esos caminos.
15. EOF sin terminal se confundía con éxito; ahora es `StreamDisconnectedError` con cantidad de eventos recibidos.
16. Eventos posteriores a `final/error` podían pasar inadvertidos; ahora se rechazan y el reader se cancela al terminal.
17. El límite SSE era inexistente y luego evadible con `data:` vacío; ahora cuenta todo el frame, incluido overhead/comentarios, con techo de 1 MiB.
18. Campos obligatorios, IDs vacíos, costos negativos/no finitos y tiers inconsistentes eran aceptados; ahora fallan como error de protocolo visible.
19. `GET /session/{id}` aceptaba otro `session_id`; ahora exige identidad exacta.
20. Requests viejos de sesión/config podían sobrescribir credenciales nuevas; epochs y abort controllers descartan resultados stale.
21. Recovery podía sugerir terminal verificado o reenviar peligrosamente; ahora usa health→GET, marca snapshot no verificable y una prueba UI demuestra un solo POST `/message`.
22. El historial se borraba en cada reinicio, reaparecía tras cambio de token o trataba espacios como credencial nueva; se normaliza token y se distingue primera carga/cambio real.
23. Persistencia podía afirmar borrado aunque `removeItem` fallara, y la prueba de secretos era tautológica; ahora el borrado devuelve éxito y un token centinela se busca en todas las claves/valores reales.
24. “Probar conexión” seguía mostrando éxito al editar o reabrir; cualquier cambio invalida el resultado probado.
25. Identidad/costo del Core anterior quedaban visibles al cambiar conexión; ahora se limpian antes del nuevo polling.
26. Texto, adjuntos, tier y modo barato podían cruzar a otra sesión/Core; ahora el cambio de contexto descarta el borrador completo.
27. Actividades se mezclaban entre turnos y tools abiertas quedaban falsamente “En curso”; ahora la timeline reinicia por turno y cierra como resultado no verificable.
28. Previews `blob:`, requests, timers y listeners podían sobrevivir a recovery/unmount; ahora se revocan/abortan y se limpian.
29. Markdown podía cargar imágenes remotas y la carrera de dos clics en Copiar dejaba timers/resultados stale; ahora bloquea recursos remotos y sólo aplica la copia más reciente.
30. El chat forzaba autoscroll cada token; ahora sólo sigue el final si el usuario estaba cerca del borde y respeta reduced-motion.
31. Costos positivos minúsculos se mostraban como cero, identidades activas múltiples eran ambiguas y el mock mentía sobre `brain_switch.from`; ahora se muestran/validan honestamente.
32. CSP no cubría IPv6 loopback y Tauri interceptaba drag & drop HTML5 en Windows; se agregó `::1`, prueba exacta de `connect-src` y `dragDropEnabled:false`.
33. Upload/attachments/413 no tenían prueba funcional; ahora hay multipart real, propagación de `file_id`, persistencia en el turno y error 413.
34. El modal HITL podía atrapar foco sin salida y faltaba prueba UI real; tiene Detener, foco seguro y tests DOM de Rechazar/ACK/interrupt.
35. Un abort intencional ya presentado por su handler podía sobrescribir el error fail-closed; `handledStreamAbortRef` evita la segunda presentación y la prueba de carrera pasa.

## Techo de la auto-auditoría

No se afirma “cero bugs”. Se afirma únicamente que el build web/typecheck pasa, las 77 pruebas Vitest y las 112 pruebas baseline pasan, y se resolvieron los 35 hallazgos agrupados anteriores. No se verificó el Core real, un binario Tauri nativo, firma/notarización ni comportamiento de producción fuera del mock.
