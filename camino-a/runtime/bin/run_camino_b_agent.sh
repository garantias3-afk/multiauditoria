#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${CAMINO_B_QUEUE_ROOT:?CAMINO_B_QUEUE_ROOT is required}"
: "${CAMINO_B_RUNS_ROOT:?CAMINO_B_RUNS_ROOT is required}"

exec python3 "$ROOT/scripts/camino_b_outbound_agent.py" \
  --queue-root "$CAMINO_B_QUEUE_ROOT" \
  --runs-root "$CAMINO_B_RUNS_ROOT" \
  "$@"
