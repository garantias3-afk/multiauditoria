# Camino B slot 14 bridge — contract-only deployment note

## Current state

`CAMINO_B_SLOT14_BRIDGE_ACTIONS.v1.yaml` is a versioned merge fragment, not a
deployed Action specification. The source code for
`camino-b-ultimo.marianogrammatico.com.ar` is not present in this repository,
so this release cannot truthfully assert that its three HTTPS handlers exist.
Do not replace the existing 25-operation Camino B specification with this
three-operation fragment.

The implemented local component is `scripts/camino_b_slot14_bridge.py`. It
provides an atomic filesystem queue for an outbound Mac agent and validates:

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

## Required remote work before Builder publication

1. Implement the three fragment paths in the existing HTTPS Gateway with the
   same X-API-Key policy used by the current Camino B Action.
2. Persist the Gateway-side job and idempotency index transactionally. The
   remote store must enforce the same candidate/request/diff SHA bindings.
3. Deploy an outbound-only agent on the selected iMac or MacBook. It must poll
   the Gateway, materialize a local queue request, claim the job, execute the
   existing Claude subscription worker, and upload its validated receipt.
4. Arm the Codex subscription fallback only after the Claude failure receipt
   passes the allowlist and hash checks. GPT Desktop High is not this reviewer.
5. Make status/result responses omit claim tokens and all credentials.
6. Merge these paths and components into the full, version-controlled Camino B
   OpenAPI document. Remove or disable legacy reserved OpenAI/Anthropic API
   approval operations.
7. Run real request/status/result smokes through ChatGPT Actions and retain the
   handoff ID, candidate SHA, Action response and worker receipt.

Until all seven steps pass, Camino B must stop at
`awaiting_slot14_local_worker` and show the returned `operator_action`. It must
not ask the user to change the GPT model and must not synthesize a `.DONE`.

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

This CLI does not launch Claude or Codex. That remains the responsibility of
the outbound agent using the existing subscription workers.
