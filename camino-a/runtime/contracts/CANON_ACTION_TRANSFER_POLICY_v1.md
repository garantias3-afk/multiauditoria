# CANON_ACTION_TRANSFER_POLICY_v1 — Camino A Cerebro/Gateway

Estado: v1.3.21-slot14-handoff.

## Decisión consolidada

Camino A adopta el patrón **control-plane + context-plane para GPT Cerebro** y reserva el
**data-plane** a Codex/Gateway/filesystem. El esquema de Camino B se toma como base técnica,
pero no se copia completo al GPT Builder. La Action del GPT Cerebro debe ser mínima y no debe
exponer endpoints admin, provider routing, creación general de corridas, upload de zips ni
aprobación de providers reservados.

## Reglas normativas

1. GPT Cerebro no transfiere zips, repositorios ni artefactos binarios grandes por Actions.
2. Codex/Gateway materializa zips, snapshots, manifests, hash trees, builds, tests, paquetes finales y `.DONE`.
3. El primer insumo de una tarea grande es `context_pack`: file map, hashes, summaries, critical files, omitted files, coverage y recommended_reads.
4. GPT puede listar todo el inventario, pero no queda obligado a leer linealmente todos los bytes si el context pack declara cobertura suficiente.
5. GPT sólo lee archivos completos cuando son críticos o pequeños; para el resto usa manifest, search y chunk/range bajo demanda.
6. Si el context pack falta, omite archivos críticos sin razón, no cubre evidencia necesaria, o el SHA no coincide, el resultado permitido es `insufficient_evidence` / `SIN_VEREDICTO_POR_EVIDENCIA_INSUFICIENTE`.
7. Salidas chicas pueden ir inline. Límite recomendado: 32 KiB; límite duro de la spec: 32768 caracteres. Salidas mayores usan upload fragmentado.
8. Output preferido: `patch_plan`, unified diff chico o `artifact_upload_ids`; Gateway/Codex aplica parches, testea y arma zip final server-side.
9. Chunks de salida son idempotentes: mismo índice + mismo hash/contenido acepta duplicado; mismo índice + contenido distinto es `409 Conflict`.
10. `start` de upload para artefactos GPT-origin puede aceptar `size_bytes`/`assert_sha256` nulos; Gateway calcula `computed_sha256` al finalizar. Para artefactos Codex-origin se exige SHA/size upfront.
11. La Action del Cerebro no incluye `createAuditRun`, `uploadTargetFile`, `startExternalAudits`, `probeProvider`, `approveReservedProvider`, `resolveFinding`, ni ids `openai_api`/`anthropic_claude`.
12. Si el Gateway real mantiene endpoints admin por compatibilidad, deben quedar fuera de la spec del GPT Builder y protegidos por scopes/tokens admin.
13. OpenAI API y Claude API siguen prohibidas para workers. Cualquier ruta/provider que intente usarlas debe fallar cerrado y quedar registrado en quality log.
14. El Knowledge servido por Gateway sigue prevaleciendo sobre Knowledge estático del Builder.
15. Seleccionar GPT-5.6 Sol no cambia este contrato de transporte ni habilita
    por sí solo Responses API, Programmatic Tool Calling o multi-agent de API.
16. La spec actual no acepta adjuntos de conversación mediante
    `openaiFileIdRefs`. No se añadirá ese campo hasta que el Gateway implemente y
    pruebe descarga inmediata, límites, MIME/magic, nombres seguros, SHA-256 y
    persistencia atómica; hasta entonces se usa ingesta manual/data plane.

## Flujo de input grande

1. Codex/Gateway ingesta el zip o snapshot fuera de GPT.
2. Gateway calcula manifest, SHA por archivo, hash tree y context pack.
3. GPT llama health, Knowledge metadata/chunks, run status, next task y context pack.
4. GPT valida `input_sha256` + `context_pack_sha256`.
5. GPT usa `searchCaminoABrainTaskFile` y `readCaminoABrainTaskFileChunk` sólo sobre evidencia necesaria.
6. Si la cobertura no alcanza, GPT entrega `insufficient_evidence`, no una aprobación.

## Flujo de output grande

1. GPT produce hallazgos estructurados y patch plan.
2. Si el patch/report excede 32 KiB, usa `startCaminoABrainArtifactUpload`.
3. GPT sube chunks numerados desde 0, reanuda con `getCaminoABrainArtifactUploadState` si hay retry.
4. Gateway valida chunks y genera `computed_sha256` en finalize.
5. GPT llama `submitCaminoABrainTaskResult` con `context_pack_sha256`, `input_sha256`, `evidence_read`, findings y `artifact_upload_ids`.
6. Gateway valida tarea vigente, evidencia, manifest, secretos y `.DONE`.

## Compatibilidad Camino B

Camino B puede adoptar estos endpoints y reglas, pero no debe mezclar su servidor,
watcher ni autoridad mecánica de estado con Camino A. Ambos caminos conservan
la identidad canónica de GPT como cerebro; sólo Camino B le asigna además la
orquestación lógica. La sincronización aceptable es de canon/patrón/protocolo,
no de estado mutable ni de watchers.
