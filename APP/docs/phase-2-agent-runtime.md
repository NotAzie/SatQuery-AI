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
- Chat SSE events are parsed against the Engine event contract. Ordinary Engine events are wrapped
  as `engine.event`, persisted in the Platform event log, and streamed to the browser. A typed
  `earth.command` event is validated against the shared Platform command contract, persisted as a
  first-class command event, and dispatched to the Earth workspace. The separate session stream can
  replay persisted events with its per-session sequence cursor.
- The frontend can load the Engine-owned transcript, render assistant text deltas, and show basic
  tool/progress status. Investigation execution authorization remains false unless the user enables
  the explicit consent checkbox.
- Stop delegates to the existing Engine Agent cancellation endpoint before closing the local event
  stream; cancellation errors remain visible in the chat.
- Investigation report and WGS 84 Earth Object reads are restricted to investigation IDs listed in
  that Engine transcript. The user can view the Engine-authored report and load its explicitly
  exported GeoJSON as a transient map overlay; unsupported geometries remain omitted by the Engine.
- Investigation history is read from the Engine execution journal through a bounded cursor-paged
  API that verifies the investigation is linked to the requested Engine Agent session. Feature
  properties validate evidence IDs as string lists; selecting a feature displays those IDs and lets
  the user highlight matching evidence in the loaded overlay.
- The Engine Agent's explicit `earth.command` tool can emit `fly_to`, `show_investigation`, or
  `set_layer_visibility`. Investigation commands are restricted to IDs linked to that Engine
  session; layer visibility commands are restricted to the current EarthContext's layer IDs and
  validated again by the live God’s Eye layer manager.
- The Platform sends a typed, bounded EarthContext per turn with primary/secondary viewports and
  cameras, timeline and playback, selection, drawings, imagery references, visible overlays,
  selected evidence, investigation references, and persisted workspace state. The Engine validates it
  and includes it as untrusted model context; it does not replace or rewrite Engine transcript history.
  Image bytes remain separate transient attachments.
- Chat image attachments are resolved from the Platform's session-owned store and sent as a typed
  Engine request field. The Engine persists attachment references, not duplicate image bytes, and
  rejects requests unless the registered reasoning adapter explicitly supports vision.
- Adapter and API integration tests use `httpx.MockTransport`; no fake scientific output or live
  provider is used.

## What must be configured for a live turn

1. Run a reachable SatQuery Engine that exposes the documented Agent API.
2. Register a compatible streaming reasoning model inside that Engine.
3. Configure the Platform with `engine.kind: http`, `engine.base_url`, and `agent.model_id`
   matching that Engine registration.

`engine.api_key_env` is forwarded as a Bearer credential, but the Engine API currently does not
validate it. It is not an authorization boundary; authenticated deployments still require a trusted
network or an authenticating deployment proxy.

The Platform's `llm.providers` configuration is not used by this Agent path. Provider SDK
integration, model/tool orchestration, execution, and transcript persistence remain Engine-owned.
The HTTP integration has contract tests but has not been validated against a deployed Engine in this
workspace.

## Remaining before Phase 2 is production-ready

- Validate the adapter against a deployed Engine version, including error responses, cancellation,
  reconnect/disconnect behavior, and session persistence across Engine restarts.
- Define and validate the Engine/reverse-proxy authentication contract; the Engine currently does
  not validate the forwarded `engine.api_key_env` credential.
- Decide and implement production authentication and per-user session authorization before exposing
  the chat endpoints to untrusted clients.
- Investigation progress from the typed `investigation.progress` Engine event is displayed as a
  bounded activity timeline for the active Platform session; historical execution journal events
  are loaded on demand through the session-scoped paged endpoint. Canonical Earth Object geometries
  are rendered only through the Engine's WGS 84 GeoJSON export. Opaque tool results and assistant
  prose are not interpreted as scientific state.
-   The Engine turn contract accepts typed model-relevant EarthContext and image attachments. Actual
  image interpretation still requires a registered reasoning adapter that declares vision support.
- Current turn lifetime is tied to the POST/SSE request. Durable worker execution, multi-process
  live event delivery, and recovering an interrupted turn are not implemented.

These are production-closure gaps, not blockers for additional vertical slices that use already
published Engine APIs. Do not implement speculative Platform substitutes for the missing Engine
contracts listed above.
