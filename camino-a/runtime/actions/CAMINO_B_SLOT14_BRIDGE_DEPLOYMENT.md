# Camino B slot 14 bridge - deployment runbook

## Current state

The local Gateway and outbound subscription agent are implemented and tested in
this repository. `CAMINO_B_SLOT14_BRIDGE_ACTIONS.v1.yaml` remains a merge
fragment: it must be merged into the existing 25-operation Camino B Action and
its `servers` URL must point at the HTTPS deployment. Do not replace the full
specification with this three-operation fragment.

The implementation consists of:

- `scripts/camino_b_gateway.py`: authenticated request/status/result HTTP handlers;
- `scripts/camino_b_outbound_agent.py`: Claude-first subscription worker and sequential Codex fallback;
- `scripts/camino_b_slot14_bridge.py`: atomic queue, claims and bundle validation;
- `bin/start_camino_b_gateway.sh` and `bin/run_camino_b_agent.sh`: operator entrypoints.

Together they validate:

- a new slot 13 to slot 14 audit request and diff, each bound by SHA-256;
- `run_id`, `candidate_sha256`, source slot 13, target slot 14 and completion of
  prior slots;
- idempotent request replay and conflict rejection;
- exclusive Claude/Codex claims with a private token and public claim receipt;
- Codex fallback only after a real, hash-bound Claude availability failure;
- imported worker `result.json`, manifest and `.DONE` against the exact
  candidate SHA;
- a final bridge receipt and `CAMINO_B_SLOT14_BRIDGE.DONE`.

The bridge always returns `terminal_approval=false`. A `completed` bridge job
means that transport and validation completed; the canonical terminal gate
must still decide whether the worker result is eligible to approve.

## Local start

Copy the variable names from `config/camino_b.env.example`, set an API key of
at least 24 characters, then run in separate terminals:

```bash
bin/start_camino_b_gateway.sh
bin/run_camino_b_agent.sh
```

The agent is intentionally one-shot. Run it from launchd/cron or invoke it when
the Action returns `awaiting_slot14_local_worker`.

## Required publication work

1. Expose `camino_b_gateway.py` through a stable HTTPS reverse proxy or tunnel.
2. Merge these paths and components into the full, version-controlled Camino B
   OpenAPI document. Remove or disable legacy reserved OpenAI/Anthropic API
   approval operations.
3. Configure the Builder `X-API-Key` secret and import the merged specification.
4. Run request/status/result smokes through ChatGPT Actions and retain the
   handoff ID, candidate SHA, Action response and worker receipt.

Until publication passes, ChatGPT Actions must stop at
`awaiting_slot14_local_worker` and show the returned `operator_action`. It must
not ask the user to change the GPT model and must not synthesize a `.DONE`.

## Verified evidence

- authoritative suite: `bin/run_tests.sh`;
- HTTP/queue/agent tests: `tests/test_camino_b_gateway.py`,
  `tests/test_camino_b_outbound_agent.py` and
  `tests/test_camino_b_slot14_bridge.py`;
- operational bridge smoke: `scripts/run_camino_b_bridge_smoke.py`;
- versioned result: `../../../shared/evidence/2026-07-12-camino-b-bridge-smoke.json`.

## Local queue CLI

Create or replay a request:

```bash
python3 scripts/camino_b_slot14_bridge.py \
  --queue-root /local/path/camino-b-slot14 \
  request --request-json /local/path/request.json
```

Claiming prints the private token once. Store it in a local mode-0600 file; do
not send it to GPT or include it in a status response:

```bash
python3 scripts/camino_b_slot14_bridge.py \
  --queue-root /local/path/camino-b-slot14 claim \
  --handoff-id B14_0123456789abcdef0123456789abcdef \
  --candidate-sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --worker-id claude_code --route-id claude_code_subscription_cli \
  --claim-id CLAIM_local_001 --host-id macbook
```

Completion accepts only a real flat worker bundle with manifest and `.DONE`:

```bash
python3 scripts/camino_b_slot14_bridge.py \
  --queue-root /local/path/camino-b-slot14 complete \
  --handoff-id B14_0123456789abcdef0123456789abcdef \
  --candidate-sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --bundle /local/path/worker-output \
  --claim-token-file /local/path/claim-token
```

The queue CLI does not launch Claude or Codex. The versioned outbound agent is
the only component that does so, using the existing subscription workers.
