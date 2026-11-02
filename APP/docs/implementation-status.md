# Implementation status

Last updated: 2026-11-02

## Platform scope

The Platform is the UI, workspace, session/conversation UX, image intake, event presentation, and
visualization layer above SatQuery Engine. Engine Agent API is the only execution engine. The
Platform must not implement model orchestration, tool calling, investigation execution, evidence
generation, or scientific reasoning.

## Current phases

| Phase | Status | Notes |
|---|---|---|
| Phase 1 — Platform foundation | Foundation implemented | Backend/frontend modular shells, contracts, transactional session mutations, Cesium shell, bounded live event queues and paged durable replay |
| Phase 2 — Agent Runtime integration | Integration slice implemented; production closure blocked on deployment contracts and decisions | Delegates turns, cancellation, complete bounded typed EarthContext, and image attachments to Engine; reports, paged session-scoped execution history, and WGS 84 overlays; live deployment validation, authentication/authorization, and recovery are deferred |
| Phase 3 — Earth Workspace foundation | Initial Engine integration implemented | Typed `earth.command` SSE events for explicit `fly_to` and session-linked `show_investigation` requests are validated, persisted, and dispatched |
| Phase 4 — Earth Workspace | Workspace and investigation visualization implemented; layer management blocked | Camera history, bookmarks, selection, drawings, measurements, split view, local timeline, Engine execution history, and evidence-linked GeoJSON selection/highlighting are implemented; layers require a typed Engine catalogue/source contract |
| Phase 5 — Vision | End-to-end attachment contract implemented; image interpretation deployment-dependent | Session-scoped images, bounded concurrent intake, browser capture, viewer, manual georeference metadata, and typed image delivery; image interpretation requires a deployed vision-capable Engine adapter |
| Phase 6 — Earth Intelligence | Platform context/planning and Engine dataset/image-capability/Earth modality/Agent tool discovery implemented | Canonical EarthContext snapshots, bounded transcript context, searchable Platform memory, retrieval, prompt assembly, capability reporting, recommendations, pre-turn planning, and a user-facing Engine catalogue with read-only Agent tool descriptors and consent visibility |
| Phase 7 — Recurring monitoring | Engine-backed management and review workflow implemented; external delivery blocked | Mission/schedule creation, revision-checked schedule editing, optional Engine-executed rolling temporal windows, run history, comparisons, cursor-paged trigger activity, and operational notification acknowledgement are available; external delivery remains blocked |

The optional `engine.api_key_env` setting is not currently usable for authentication: the adapter
sends a placeholder authorization value. A supported auth scheme/header, protected endpoint scope,
and error contract must be defined with the Engine or deployment proxy before authenticated Engine
deployments are supported. Platform user authentication additionally needs an identity/tenant and
resource ownership decision.

## Deferred roadmap dependencies

These are blocked rather than dropped. Resume each capability when its dependency is supplied:

| Capability | Classification | Required dependency |
|---|---|
| Layer manager | 4. Blocked by deployment or product decisions | Select supported renderable source kinds and approved providers/licensing, define credential/access rules, and provide source-serving endpoints before the Engine can publish stable layer/source IDs, CRS/geometry semantics, and ownership |
| External alert delivery | 4. Blocked by deployment or product decisions | Select a supported provider and define destinations, credentials, retry/idempotency policy, and delivery ownership before adding the Engine-owned delivery contract |
| Production authentication | 4. Blocked by deployment or product decisions | Engine/proxy credential contract; Platform identity provider, tenancy, and per-user authorization policy |
| Interrupted-turn recovery/multi-worker event delivery | 5. Blocked by external infrastructure | Durable worker and shared event-storage/broker deployment, with recovery ownership and resume semantics defined against that infrastructure |
| Live Engine integration validation | 5. Blocked by external infrastructure | Reachable deployed Engine version and configuration |
| Image interpretation | 5. Blocked by external infrastructure | Deployed reasoning adapter declaring vision support |
| Broader provider administration | 4. Blocked by deployment or product decisions | Administrative roles, provider lifecycle, and credential UX requirements |
| Runtime plugin loading | 4. Blocked by deployment or product decisions | Trust, backend permission, and frontend module-serving/security decisions |
| Distributed Platform deployment | 5. Blocked by external infrastructure | Deployment decision and external shared worker/event/persistence infrastructure |
| Persistent full-text/vector memory index | 4. Blocked by deployment or product decisions | Product workload and scale requirements establishing that query-time index rebuilding needs replacement |

## Phase 3 capability detail

| Capability | Status | Boundary |
|---|---|---|
| Earth Command Dispatcher | Initial Engine slice implemented | Routes validated Engine-issued `fly_to` and `show_investigation` commands to workspace handlers |
| Camera synchronization | Existing basic synchronization | UI camera state is recorded at movement end and may be sent as per-turn EarthContext; Engine-driven camera synchronization is not available |
| Evidence highlighting | Platform handler implemented | Operates only on loaded Engine GeoJSON features with matching evidence IDs; live Engine event source is not available |
| Investigation visualization | Implemented for execution history and materialized Earth Objects | Session-scoped paged Engine execution history and typed Earth Object evidence IDs; unsupported geometry remains omitted by Engine policy |
| Investigation reports | Implemented in chat | Uses Engine session investigation IDs and the existing Engine report endpoint; report text and digest remain Engine-owned |
| Layer manager | Blocked by product/deployment decisions | No configured renderable layer providers or source-serving endpoints exist; dataset acquisition metadata is not a renderable source catalogue |
| Timeline foundation | Local presentation control implemented | Timeline controller and panel drive Cesium clock; time and playback state are forwarded as untrusted context, without Engine-side temporal execution |

## Phase 4 capability detail

| Capability | Status | Boundary |
|---|---|---|
| Timeline range, instant, scrub, playback | Implemented locally | Range, instant, and playback state are forwarded in typed EarthContext; this does not assert Engine data availability or temporal execution; Cesium tick subscription is released on teardown |
| Camera history | Implemented | Move-end states, undo/redo and restore; persisted per Platform session |
| Bookmarks | Implemented | Named EarthContext capture, rename/update/delete/fly-to; persisted per Platform session |
| Earth selection | Implemented | Cesium entity picks produce typed context state and `earth.selection.changed` events |
| Drawings | Implemented | Point/line/polygon/rectangle/circle GeoJSON presentation context; no automatic Engine action |
| Measurements | Implemented | Local geodesic distance/area, coordinates and terrain-provider height when available |
| Split view | Implemented | Two EarthController-backed views share drawings, selection and timeline; cameras independent unless synchronized |
| Investigation visualization | Implemented for Engine-recorded execution history and materialized geometry | Paged session-scoped journal history; feature selection exposes linked evidence IDs and permits highlighting matching loaded evidence; active geometry remains in bounded EarthContext |
| Layer manager | Blocked by product/deployment decisions | Supported source kinds, approved providers/licensing, credential/access rules, and source-serving endpoints must be selected before an Engine-owned catalogue can be implemented |

## Phase 3 Engine command boundary

The Engine Agent emits typed `earth.command` events from an explicit tool call. The initial command
set is deliberately limited to `fly_to` and `show_investigation`; the Engine validates investigation
IDs against its Agent session, and the Platform rechecks ownership before resource reads. The
Platform maps valid events to its shared `EarthCommandIssued` contract, persists them, and dispatches
them to the workspace. It does not infer commands from assistant text or tool results. Time changes,
arbitrary overlays, evidence highlighting, and layer visibility need additional Engine-owned data
contracts and remain unavailable as live commands.

## Phase 4 Engine-owned data boundaries

The session record now stores typed `earth_workspace` state through the existing session API and
SQLite repository. Cesium entity references and rendering objects stay inside `earth/`; selection
properties are restricted to serializable scalar values. Drawings and measurements are client
presentation data, not investigation inputs or scientific findings. The Engine's existing investigation-scoped GeoJSON export supplies only explicitly materialized
WGS 84 Earth Objects; unsupported geometries are omitted by the Engine. The Agent API accepts a
bounded typed snapshot of viewport, camera, timeline, selection, drawings, imagery references,
active overlays, evidence highlights, investigation references, and both viewports when split view
is active, plus the remaining serializable workspace state as per-turn scope. This remains untrusted
context, not evidence. Session-scoped execution history and evidence-linked GeoJSON are available;
there is no general Engine layer/source catalogue or investigation status API. Imagery references
identify Platform captures and attached assets only; the current API does not describe base-map
providers or active imagery sources.

## Phase 7 monitoring contract

The Platform proxies Engine mission and monitoring schedule APIs through `EngineClient`. The
monitoring panel can create a mission, create a schedule with an explicit WGS 84 bounding box,
requested variables and interval, optionally configure descriptive-measurement trigger policies,
change enabled state, edit supported schedule definition fields and policies through the Engine's
optimistic schedule-revision contract, read run history and trigger events, and request the Engine's
recent-run comparison. It also lists Engine notifications for partial/failed runs and sends
acknowledgements to the Engine. Schedule execution, investigation creation, trigger evaluation,
comparison, and notification lifecycle remain Engine-owned. The Platform displays comparison
Markdown, digest and declared limitations without claiming a trend or independently interpreting
measurement data. Schedule query edits preserve unedited query dimensions; the UI edits WGS 84
bounds only for simple rectangular queries.

Schedules may declare a rolling window duration, mutually exclusive with fixed EarthQuery temporal
bounds. At claim time the Engine resolves it against the persisted run start, executes the effective
EarthQuery, and returns both bounds in run history. The Platform exposes the duration in schedule
creation/editing and the resolved interval in run history; it does not expose event/notification
delivery configuration. Trigger activity uses cursor-paged Engine history, appends pages in order,
removes duplicate event
IDs, and rejects stale schedule revisions or non-advancing cursors. Trigger policies compare only
descriptive measurements with matching exact canonical variable and unit values. The notification
inbox is limited to the Engine's existing operational partial/failed-run notifications; no trigger
behavior is simulated by the UI.

## Phase 2 external gaps still open

- Validate the HTTP Agent adapter against a deployed Engine version.
- Add production authentication and per-user authorization.
- Decide recovery/retention semantics for interrupted turns and multi-worker delivery.
- Configure and validate a vision-capable reasoning adapter in the deployed Engine.

See the [roadmap](roadmap.md) and [Phase 2 Agent Runtime details](phase-2-agent-runtime.md).

## Plugin extension boundary

Plugin manifests, contribution types, and host protocols exist, as do frontend panel/layer
registries. There is no concrete backend discovery/loader in the application lifecycle and no
frontend manifest feed or module loader. Runtime plugin loading remains deferred until the Platform
defines administrator trust, backend execution permissions, and frontend module serving/security
boundaries; current interfaces must not be described as active plugin capability.

## Phase 5 — Vision detail

| Capability | Status | Boundary |
|---|---|---|
| Upload validation and persistence | Implemented | Filesystem image store; actual format sniffing, per-file and aggregate byte limits, configured MIME allowlist, bounded in-process concurrent ingestion, image dimensions, SHA-256, thumbnails |
| Picker, drag/drop, clipboard, upload progress | Implemented | Browser-only intake in `features/vision`; session-scoped API references, upload cancellation and stale-session write guards |
| Screen capture | Implemented | Browser display permission; image is stored as a regular uploaded asset |
| Earth viewport capture | Implemented | Only through `EarthController.capture`; camera/time/source metadata are held in EarthContext and session workspace |
| Selected-region Earth capture | Implemented as pixel crop | User selects a rectangle on the captured viewport; pixel bounds are persisted; geographic bounds are not inferred |
| Image asset management | Implemented | Session list, content/thumbnail preview, delete, rename, and metadata update endpoints |
| Image viewer | Implemented | Zoom, pan, rotate, fullscreen, and metadata panel |
| Georeference metadata | Implemented | Optional user-supplied values are validated; no automatic location inference |
| Provider-neutral multimodal preparation | Implemented | `MultimodalPreparer` returns typed context and original asset bytes; no provider formatting |
| Attach images to Engine chat turn | Implemented | Chat resolves session-owned assets and sends bytes separately; Engine validates and delivers transient image data to declared vision-capable reasoning adapters |

### Phase 5 Engine contract boundary

`AgentTurnRequest` and the HTTP adapter forward text, model id, execution authorization, supported
typed EarthContext, and verified image attachments. The Platform sends canonical image bytes from
its session-scoped store; the Engine persists only attachment metadata/references in the Agent
transcript and passes bytes transiently to the selected reasoning adapter. The Engine rejects
attachments before streaming unless the adapter declares `supports_vision = True`. The selected
region crop stores pixel coordinates only; geographic region metadata remains unset unless the user
supplies it separately.

The Engine image transport and transcript-reference contract is implemented. A configured
vision-capable Agent adapter remains necessary to interpret images; provider-specific request
formatting and image reasoning remain the adapter's responsibility. Deployment of that adapter is a
deferred dependency, not a Platform implementation task.

## Vision persistence and data handling

Uploaded image bytes and generated PNG thumbnails are stored under the configured Vision filesystem
root. Metadata is persisted alongside each asset and is scoped to the Platform session in API
lookups; asset IDs are validated before path construction. Preparation resolves metadata from the
store rather than trusting client-supplied asset fields. Vision processing stops at validation,
metadata, storage, and transport-neutral preparation; no image content is interpreted.

## Phase 6 — Earth Intelligence detail

| Capability | Status | Boundary |
|---|---|---|
| Earth Context Builder | Implemented | Combines request state with saved camera history, bookmarks, captures, pinned evidence refs, timeline focus, and prior snapshots; no Engine calls |
| Conversation Context Builder | Implemented | Configurable message and estimated-token budgets with extractive compression; Engine-owned full transcript cannot be replaced through its current API |
| Workspace memory | Implemented | On-demand lexical, geographic, and temporal retrieval across saved sessions, conversations, investigation/evidence references, assets, bookmarks, drawings, and snapshots; deterministic tie ordering; no embeddings or opaque-result parsing |
| Context retrieval | Implemented | Runs before chat turns and has a session-scoped memory search API; uses only indexed persisted facts |
| Prompt/context assembly | Implemented | Provider-neutral plan budgets and sends bounded camera/viewport, timeline, selection, imagery references, active overlay geometry, evidence highlights, investigation references, and workspace state in the Engine's typed per-turn field; image bytes use separate attachments |
| Capability discovery | Implemented with explicit unknowns | Reads Platform registries/contracts and exposes Engine-registered datasets, legacy image-analysis capability status, versioned Earth modality snapshot, and typed Agent tool descriptors with consent visibility in the Engine data panel; provider vision support and active frontend Earth handlers remain unknown |
| Recommendations | Implemented for existing references | Can surface related stored investigations, assets, bookmarks, timeline overlaps, and conversations; does not infer dataset suitability or recommend Agent tools from free text |
| Request Planner | Implemented | Validates and normalizes chat context, validates session-owned image IDs, estimates context budget, persists bounded EarthContext snapshots, and executes before every chat turn |

### Phase 6 request and persistence behavior

`POST /api/v1/chat/sessions/{id}/turns` obtains the Engine-owned transcript and builds the
provider-neutral plan. It sends the user/context-plan message and a typed, bounded EarthContext
field separately. The Engine validates the primary and optional secondary viewport, camera,
temporal/playback, selection, drawing, imagery reference, visible overlay geometry, evidence, and
investigation fields and supplies them to the reasoning model as untrusted scope. Platform snapshots
retain the full typed EarthContext,
including bookmarks, layers, history, split view, measurements, and capture metadata, with a
configurable maximum of 20.

`POST /api/v1/chat/sessions/{id}/plan` returns the normalized plan without starting a turn.
`GET /api/v1/intelligence/capabilities` reports dynamically registered/configured implementation
facts and explicitly unknown Engine/provider capabilities.
`GET /api/v1/intelligence/sessions/{id}/memory?query=...` searches records belonging to persisted
Platform sessions. Search uses token overlap, geographic proximity, and timeline recency; it is not
vector search. The current implementation rebuilds its in-process search records per query, so a
persistent full-text index is a future performance extension. Cross-session retrieval assumes a
single trusted workspace and must be owner-scoped before a shared-user deployment; the active
Engine transcript is searchable for its own session, while cross-session conversation search uses
Platform-persisted conversations only.

The planner resolves image metadata into `VisionContext`; the chat boundary then reads canonical
bytes from the Platform store and sends them separately from Engine message text. The user-facing
Engine discovery endpoint validates and presents Engine dataset metadata, the legacy image-analysis
capability response, the versioned Earth modality snapshot, and registered Agent tool descriptors
including input schemas and consent visibility. It does not prove dataset reachability/suitability.
Provider image-adapter support and frontend command-handler availability remain unknown; the
Platform does not guess them. The Engine's conversation history is authoritative
and cannot be compressed by the Platform without a separate replacement-history contract.

## Validation results after Engine discovery integration

All checks below passed except the full backend mypy run, which reports a missing type annotation
in the pre-existing modified streaming event-bus module:

| Check | Result |
|---|---|
| Backend Ruff | Passed |
| Backend mypy | Changed discovery modules passed; full check is blocked by missing annotation for `_EVENT_ADAPTER` in `backend/src/earth_platform/streaming/memory.py:12` |
| Backend pytest | Passed; 58 tests |
| Engine regression suite | Passed; 551 tests, 3 skipped |
| Import-linter | Passed; 84 files and 253 dependencies analyzed |
| Frontend lint | Passed |
| Frontend typecheck | Passed |
| Frontend tests | Passed; 72 tests in 19 files |
| Frontend production build | Passed |
| Contract schema and generated TypeScript | Passed; generated after adding the Agent tool descriptor contract |
| `git diff --check` | Passed; Git reported only existing LF-to-CRLF working-copy warnings |

The Engine regression suite reports 18 upstream Pillow/rasterio deprecation or pending-deprecation
warnings; they do not fail the suite. Engine report, GeoJSON, EarthContext, mission, monitoring, and
discovery boundary models are exported through the shared contract and generated TypeScript types.
