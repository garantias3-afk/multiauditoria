# Changelog — v1.3.21-slot14-handoff

## Arquitectura

- Camino A puede operar con un Codex orquestador de nivel económico/bajo.
- El fallback del slot 14 no cambia ese modelo: abre un `codex exec` efímero y
  separado, fuerza `gpt-5.6-sol` con razonamiento `ultra`, ignora la
  configuración del usuario y usa únicamente la suscripción ChatGPT.
- Camino B conserva GPT Desktop/Custom GPT High como cerebro y orquestador. Su
  revisor de slot 14 sigue siendo un worker CLI local independiente.

## Entrega 13→14

- Cada candidato genera un pedido JSON nuevo, Markdown compacto y diff textual
  acotado contra `INPUT/target_snapshot`.
- Request, diff, run y candidato quedan ligados por SHA-256 y se validan antes
  de invocar Claude o Codex.
- Claude y Codex reciben el mismo expediente y deben devolver su SHA, intentos
  de falsificación y controles independientes.
- La metodología obliga a buscar evidencia contradictoria y contraejemplos; las
  conclusiones previas se tratan como claims, no como verdad.

## Contingencia

- Fallos de login, CLI, modelo, cuota o transporte de Codex generan
  `STATE/SLOT14_OPERATOR_ACTION_REQUIRED.json` y bloquean el cierre.
- Cambiar el modelo del orquestador o usar una respuesta manual/Desktop no puede
  aprobar el slot 14.

## Camino B

- Se añade el contrato local hash-bound del puente request/status/result para
  slot 14. Su publicación como Action queda condicionada a handlers HTTPS y
  agente pull realmente desplegados; hasta entonces el estado correcto es
  `awaiting_slot14_local_worker`.

## Compatibilidad y seguridad

- OpenAI API, Anthropic API y Claude API siguen prohibidas para estas rutas.
- Los slots con `loop_type=external_slot_loop`, incluido el 14, no ejecutan el
  bucle interno `.001`–`.010`, evitando trabajo y tokens redundantes.
