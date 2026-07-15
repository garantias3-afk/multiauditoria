#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# macOS system Python may redirect bytecode into ~/Library/Caches, which is
# unavailable in sandboxes and is not part of the artifact under test.
export PYTHONPYCACHEPREFIX="${CAMINO_PYCACHE_PREFIX:-${TMPDIR:-/tmp}/camino_pycache_${UID}}"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-1}"

if [ ! -d tests ]; then
  echo "RUN_TESTS_FAIL: tests/ is required; a release cannot silently skip pytest" >&2
  exit 2
fi

python3 -m compileall -q scripts
python3 -m compileall -q tests

python3 scripts/render_contracts.py --root . --check >/dev/null
python3 scripts/build_gpt_knowledge_bundle.py --root . \
  --version v1.3.22-slot1-slot4-six-loops --check >/dev/null
python3 scripts/canon_loader.py --root . --profile without_claude --validate >/dev/null
python3 scripts/canon_loader.py --root . --profile with_claude --validate >/dev/null
python3 scripts/probe_live_routes.py --self-test
python3 scripts/test_gateway_protocol.py
python3 scripts/test_gateway_strict.py
python3 scripts/test_cerebro_actions_contract.py
python3 scripts/test_manual_submit_batch.py
python3 scripts/test_drive_locator.py

python3 -m pytest -q tests --import-mode=importlib

echo "RUN_TESTS_OK"
