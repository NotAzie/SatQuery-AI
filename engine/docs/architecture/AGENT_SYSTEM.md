# SatQuery Agent Interface

SatQuery's agent is a provider-neutral conversational bridge to the existing
Earth Intelligence engine. It reasons about user intent, selects from an
explicit Earth-specific tool allowlist, validates model-requested arguments,
dispatches to `PlatformRuntime`, returns observations to the model, and streams
user-facing progress. It does not plan workflows, schedule work, acquire data,
assess evidence, or perform scientific reasoning itself.

## Architecture

```text
User
  -> Agent API and session service
  -> Registered streaming reasoning adapter
  -> Validated SatQuery tool request
  -> Existing PlatformRuntime services
  -> Existing connectors, workflow compiler, scheduler, and execution journal
  -> Tool observation and evidence-backed response
```

The loop lives in `satquery.agent.AgentTurnService`. The model adapter implements
the `AgentModel` protocol and translates its provider's message, tool-call, and
stream formats to `AgentMessage`, `AgentToolCall`, and `AgentModelEvent`. It
receives the fixed SatQuery system prompt, the current bounded conversation
context, the schemas for the currently allowed tools, and a cooperative
cancellation event. The current user message may also carry verified image
references and transient image bytes. An adapter must declare
`supports_vision = True` before the API accepts an image turn, and translates
those bytes into its provider's image format. Provider-specific formats do not
enter the engine or the HTTP API. The normalized `text_delta` event is user-visible output only;
adapters must not forward private reasoning or hidden model tokens.

Adapters are registered under a stable identifier in
`SatQueryEngine.platform_registries.reasoners`. The registry identity must
match the adapter's `model_id`. An adapter must stream normalized events and
honor cancellation; SatQuery owns validation, dispatch, context persistence,
event sequencing, and configurable round, tool-call, and conversation-context
budgets. No provider SDK is a core dependency. Each model streaming round has a finite deadline controlled by
`agent.model_timeout_seconds` (120 seconds by default); timeout is reported as
an explicit `reasoning_model_timeout` event. Adapters must cooperate with
async task cancellation as well as the supplied cancellation event so an
expired request can release its resources promptly.

The optional `satquery.agent_openai.OpenAIChatAgentModel` adapter implements
OpenAI Chat Completions streaming, function calls, and image data URLs using
the existing `httpx` dependency. It registers at Engine startup only when
`SATQUERY_AGENT_OPENAI_MODEL` and either `SATQUERY_AGENT_OPENAI_API_KEY` or
`OPENAI_API_KEY` are set. Its stable model ID is `openai/<model-name>`; set
the Platform's `EARTH_AGENT__MODEL_ID` to that exact value. Image turns are
rejected unless `SATQUERY_AGENT_OPENAI_SUPPORTS_VISION=true` is explicitly
configured and the selected provider model actually accepts images. The flag
is an operator declaration, not provider capability discovery. The adapter
does not provide an OpenAI Responses API integration or a local model server
integration; other providers still require their own `AgentModel` adapter.

## Tool boundary

The default tool registry is a strict, explicit allowlist:

| Tool | Engine responsibility used |
|---|---|
| `platform.capabilities` | Read the existing perception capability matrix. |
| `investigation.start` | `PlatformRuntime.start_investigation`, the same planner/design/lifecycle path used by the existing investigation API. Planning does not acquire data. |
| `investigation.execute` | Existing investigation execution, workflow compiler, scheduler, and journal. Offered to the model only for a turn with explicit execution authorization. |
| `investigation.inspect` | Existing investigation report, evidence assessment, and scientific reasoning records. |
| `earth-memory.search` | Existing deterministic Earth Memory query service. |
| `investigation.cancel` | Existing cooperative investigation cancellation service. |

Tool arguments use typed Pydantic contracts with extra fields forbidden.
Unknown tools and invalid arguments become explicit tool-failure observations;
they are never treated as successful execution. Tool implementations can be
extended by supplying an `AgentToolRegistry`, without changing the engine or
the reasoning adapter.

The `execution_authorized` turn field is an explicit per-turn user consent
gate, not an identity or access-control system. This deployment has no
multi-user authentication or authorization layer; production deployments must
place the API behind their own identity and access-control boundary.

## Events, cancellation, and persistence

Agent SSE events have a stable event kind, session ID, turn ID, per-turn
sequence, timestamp, and typed payload. They distinguish assistant output,
tool lifecycle, execution-journal progress, completion, cancellation, and
errors. Private model reasoning is not exposed as an event. Investigation
progress is projected from the existing append-only execution journal; the
agent does not create a parallel scheduler or progress journal.

Earth presentation commands are emitted as typed events for the workspace to
apply. Their tool observation records the request as emitted but explicitly
marks workspace application unconfirmed; the Engine does not currently receive
a workspace acknowledgement. The model is instructed not to claim the Earth
state changed based only on the command request.

Cancelling an agent turn signals the provider adapter. If the turn is executing
an investigation, the service also requests cancellation from the existing
runtime. Closing or disconnecting the SSE stream explicitly closes the
underlying turn iterator; an active investigation task is signalled to cancel
and joined before the iterator releases its session state. Cancellation is
cooperative; already completed upstream requests cannot be rolled back. If a
process stops before all requested tools have persisted observations, the next
turn adds explicit interruption observations for unmatched tool-call IDs.
They state that the outcome may be unknown and require inspection before
retry; SatQuery does not silently replay a tool.

Session state persists normalized user, assistant, and tool messages and
investigation references. The default repository is in-memory. If a platform
storage path is configured, agent sessions use a versioned SQLite table with
optimistic revision checks and a content-integrity digest. SQLite is a
single-host persistence adapter, not distributed session storage. Session
messages are conversational state; Earth Memory remains the separate
long-lived domain/evidence store.

An image turn uses `attachments`, a list of up to eight objects containing
`asset_id`, `mime_type`, `size_bytes`, optional pixel dimensions, `sha256`, and
`data_base64`. Individual images are limited to 20 MiB and the turn total to
40 MiB. The Engine validates strict base64, MIME signature, byte length, and
SHA-256 before opening the stream. Agent transcript messages persist only the
verified metadata references; image bytes are transient on the current user
message and are not copied into Engine session storage. The Platform remains
the durable owner of the source image and must resend it on a later turn when
the user wants the model to inspect it again.

Assistant text deltas are persisted as a partial assistant message if a model
stream fails, times out, or is cancelled after emitting text. Incomplete tool
requests are not persisted as completed assistant messages; interrupted calls
are handled by the explicit recovery observations above. This keeps resumed
conversation context aligned with text already delivered to the client without
implying that a failed model response was complete.

## HTTP interface

- `GET /api/v1/agent/tools` returns the sorted descriptors from the registered Agent tool allowlist.
  Each descriptor includes its JSON input schema and whether it is visible to the model by default
  or only when the turn explicitly authorizes execution. This endpoint is descriptive and never
  invokes a tool.
- `POST /api/v1/agent/sessions` creates a conversation.
- `GET /api/v1/agent/sessions/{session_id}` reads persisted conversation state.
- `GET /api/v1/agent/sessions/{session_id}/investigations/{investigation_id}/events`
  returns an integrity-verified execution-journal page only when the investigation is linked to
  that session. `after_sequence` is the cursor and `limit` is bounded from 1 to 200; an
  investigation without executable tasks returns an empty page rather than a fabricated plan.
- `POST /api/v1/agent/sessions/{session_id}/turns` accepts `message`,
  `model_id`, optional `execution_authorized` (default `false`), optional typed
  `earth_context`, and optional image `attachments`, and streams Server-Sent
  Events. Image requests fail with HTTP 422 before streaming when the selected
  adapter does not declare vision support.
- `POST /api/v1/agent/sessions/{session_id}/cancel` cooperatively cancels the
  active turn.

The optional EarthContext is a bounded per-turn workspace snapshot. It carries
viewport and camera state, temporal state, selection/drawings, imagery
references, currently visible overlay geometry, evidence and investigation
references, and other serializable presentation state. WGS 84 overlay
geometries are validated and the encoded context is capped at 512 KiB. Every
field is untrusted scope rather than evidence or instruction; image bytes are
carried only by the separate attachment field.

The synchronous Python client exposes the same operations through
`client.agents.create_session()`, `get_session(session_id)`,
`stream_turn(session_id, message=..., model_id=...,
execution_authorized=False)`, and `cancel_turn(session_id)`. The CLI exposes
`satquery agent create`, `show`, `turn`, and `cancel`. Its turn command writes
one JSON object per SSE event to stdout; execution consent is opt-in with
`--authorize-execution`. Both interfaces use the REST endpoints as their
single transport contract, preserve the event JSON payload, and propagate
HTTP failures through the shared client error type.

Register at least one compatible reasoner before submitting a turn. An
unregistered or incompatible model is rejected before the event stream starts.
There is deliberately no built-in provider selection, credentials handling,
user identity, autonomous background agent, or multi-agent collaboration.

## Architectural inspiration

The design uses only broadly applicable patterns: normalized model/tool
contracts and tool-call IDs (OpenHands SDK), a model-request/application-owned
tool execution loop (Cursor and Claude Agent SDK documentation), explicit
thread state (LangGraph persistence), and typed observable events (OpenHands
and LangGraph streaming). Provider-specific SDK behavior and product-domain
tools are intentionally not adopted.

## Boundaries and future work

The interface does not add agent collaboration, consensus, independent
scientific authority, scheduling, long-term learned memory, or autonomous
changes to plans based on model claims. Model output is a proposal; evidence,
execution state, and scientific assessments remain owned by SatQuery's
deterministic services. Production authentication, distributed storage,
provider adapters, and deployment infrastructure remain external integration
work.
