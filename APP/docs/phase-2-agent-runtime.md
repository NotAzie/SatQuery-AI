# Phase 2 — Agent Runtime

## What is implemented

The Platform delegates chat turns to SatQuery Engine's existing Agent Interface. It does not create
a second model loop, tool router, investigation runtime, or scientific evidence store.

- `engine.kind: http` uses the Engine's `POST /api/v1/agent/sessions`,
  `GET /api/v1/agent/sessions/{id}`, `POST .../turns`, and `POST .../cancel` endpoints.
- A Platform session stores its linked Engine Agent session id. Older Platform sessions are linked
  lazily on their first chat or transcript request.
- The Engine Agent session is authoritative for the chat transcript. The Platform stores session
  metadata and its own ordered event log; its general conversation repository is not used by this
  Agent path.
- A linked session cannot be deleted through the Platform because the Engine Agent API has no
  session-delete operation. It can be archived; this avoids orphaning the authoritative transcript.
- Chat SSE events are parsed against the Engine event contract, wrapped as `engine.event`, persisted
  in the Platform event log, and streamed to the browser. The separate session stream can replay
  persisted events with its per-session sequence cursor.
- The frontend can load the Engine-owned transcript, render assistant text deltas, and show basic
  tool/progress status. Investigation execution authorization remains false unless the user enables
  the explicit consent checkbox.
- Adapter and API integration tests use `httpx.MockTransport`; no fake scientific output or live
  provider is used.

## What must be configured for a live turn

1. Run a reachable SatQuery Engine that exposes the documented Agent API.
2. Register a compatible streaming reasoning model inside that Engine.
3. Configure the Platform with `engine.kind: http`, `engine.base_url`, optional
   `engine.api_key_env`, and `agent.model_id` matching that Engine registration.

The Platform's `llm.providers` configuration is not used by this Agent path. Provider SDK
integration, model/tool orchestration, execution, and transcript persistence remain Engine-owned.
The HTTP integration has contract tests but has not been validated against a deployed Engine in this
workspace.

## Remaining before Phase 2 is production-ready

- Validate the adapter against a deployed Engine version, including error responses, cancellation,
  reconnect/disconnect behavior, and session persistence across Engine restarts.
- Validate the supported Engine authentication and reverse-proxy configuration against deployment.
- Decide and implement production authentication and per-user session authorization before exposing
  the chat endpoints to untrusted clients.
- Make the Platform chat UI consume investigation/evidence events into the workspace. The current
  chat displays text and basic tool/progress status only; it does not interpret scientific payloads
  or drive globe layers.
- The current Engine turn contract accepts text and execution authorization, not an `EarthContext`
  or image asset reference. Vision and Earth-context handoff need a supported Engine API contract
  before implementation.
- Current turn lifetime is tied to the POST/SSE request. Durable worker execution, multi-process
  live event delivery, and recovering an interrupted turn are not implemented.

These are Phase 2 completion gaps; the Platform should not begin Phase 3 work until deployment
integration, authorization, and the required end-to-end behavior are resolved.
