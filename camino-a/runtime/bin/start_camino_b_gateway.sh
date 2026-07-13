#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${CAMINO_B_QUEUE_ROOT:?CAMINO_B_QUEUE_ROOT is required}"
: "${CAMINO_B_GATEWAY_API_KEY:?CAMINO_B_GATEWAY_API_KEY is required}"

args=(
  --host "${CAMINO_B_GATEWAY_HOST:-127.0.0.1}"
  --port "${CAMINO_B_GATEWAY_PORT:-8787}"
  --queue-root "$CAMINO_B_QUEUE_ROOT"
)
if [[ -n "${CAMINO_B_TLS_CERT:-}" || -n "${CAMINO_B_TLS_KEY:-}" ]]; then
  args+=(--tls-cert "${CAMINO_B_TLS_CERT:-}" --tls-key "${CAMINO_B_TLS_KEY:-}")
fi
exec python3 "$ROOT/scripts/camino_b_gateway.py" "${args[@]}"
