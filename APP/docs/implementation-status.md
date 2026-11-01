# Implementation status

Last updated: 2026-11-01

## Platform scope

The Platform is the UI, workspace, session/conversation UX, image intake, event presentation, and
visualization layer above SatQuery Engine. Engine Agent API is the only execution engine. The
Platform must not implement model orchestration, tool calling, investigation execution, evidence
generation, or scientific reasoning.

## Current phases

| Phase | Status | Notes |
|---|---|---|
| Phase 1 — Platform foundation | Foundation implemented | Backend/frontend modular shells, contracts, persistence, Cesium shell |
| Phase 2 — Agent Runtime integration | Integration slice implemented; not production-closed | Delegates turns to Engine; live deployment, auth, recovery, and Earth-context contract still open |
| Phase 3 — Earth Workspace foundation | Implemented foundation | Typed dispatcher; `fly_to` is wired, but Engine currently emits no typed Earth command event |
| Phase 4 — Earth Workspace | In progress | Camera history, bookmarks, selection, drawings, measurements, split view, and local timeline implemented; Engine-backed visualizations remain blocked |
| Phase 5 — Vision | Platform ingestion/preparation implemented; Engine delivery blocked | Session-scoped images, browser intake, viewport capture, viewer, manual georeference metadata, and provider-neutral payload; Engine Agent accepts text only |
| Phase 6 — Earth Intelligence | Platform context/planning slice implemented; Engine discovery boundaries open | Canonical EarthContext snapshots, bounded transcript context, searchable Platform memory, retrieval, prompt assembly, capability reporting, recommendations, and pre-turn planning |

## Phase 3 capability detail

| Capability | Status | Boundary |
|---|---|---|
| Earth Command Dispatcher | Initial slice implemented | Accepts typed `earth.command` events only; routes to registered Earth controllers |
| Camera synchronization | Existing basic synchronization | UI camera state is recorded at movement end; no Engine Earth-context round-trip |
| Evidence highlighting | Not implemented | Must use Engine-provided evidence references/geometry |
| Investigation visualization | Not implemented | Must render Engine events/data without duplicating investigation state |
| Layer manager | Contracts only | No locally invented scientific layers |
| Timeline foundation | Local presentation control implemented | Timeline controller and panel drive Cesium clock; Engine time/context integration is not supported |

## Phase 4 capability detail

| Capability | Status | Boundary |
|---|---|---|
| Timeline range, instant, scrub, playback | Implemented locally | EarthContext presentation state only; no Engine forwarding or scientific availability claims |
| Camera history | Implemented | Move-end states, undo/redo and restore; persisted per Platform session |
| Bookmarks | Implemented | Named EarthContext capture, rename/update/delete/fly-to; persisted per Platform session |
| Earth selection | Implemented | Cesium entity picks produce typed context state and `earth.selection.changed` events |
| Drawings | Implemented | Point/line/polygon/rectangle/circle GeoJSON presentation context; no automatic Engine action |
| Measurements | Implemented | Local geodesic distance/area, coordinates and terrain-provider height when available |
| Split view | Implemented | Two EarthController-backed views share drawings, selection and timeline; cameras independent unless synchronized |
| Investigation visualization | Blocked | Engine must provide typed lifecycle and renderable geometry/evidence data |
| Layer manager | Blocked | Engine must provide a real layer catalogue/source contract |

## Known Phase 3 integration gap

The Platform's generated event contract includes `EarthCommandIssued`, and the frontend dispatcher
is wired to consume it from streamed Agent events. However, the inspected SatQuery Engine Agent SSE
contract currently defines `turn.started`, `assistant.delta`, tool lifecycle/progress, terminal, and
error events; it does **not** define a dedicated Earth command event. The current Platform HTTP
adapter wraps these Engine events as `engine.event` and does not synthesize Earth commands.
Therefore, the dispatcher is testable and ready for the typed server event, but an Engine-to-Platform
event mapping/API addition is needed before live turns can drive the globe. Do not infer Earth
commands from assistant text or tool-result payloads.

## Phase 4 Engine-owned data boundaries

The session record now stores typed `earth_workspace` state through the existing session API and
SQLite repository. Cesium entity references and rendering objects stay inside `earth/`; selection
properties are restricted to serializable scalar values. Drawings and measurements are client
presentation data, not investigation inputs or scientific findings. The current Engine Agent API
still does not accept EarthContext and does not provide the investigation/evidence geometry or layer
catalogue needed for those visualizations.

## Phase 2 external gaps still open

- Validate the HTTP Agent adapter against a deployed Engine version.
- Add production authentication and per-user authorization.
- Decide recovery/retention semantics for interrupted turns and multi-worker delivery.
- Coordinate a supported Engine contract for vision and Earth-context forwarding.

See the [roadmap](roadmap.md) and [Phase 2 Agent Runtime details](phase-2-agent-runtime.md).

## Phase 5 — Vision detail

| Capability | Status | Boundary |
|---|---|---|
| Upload validation and persistence | Implemented | Filesystem image store; actual format sniffing, per-file and aggregate byte limits, configured MIME allowlist, image dimensions, SHA-256, thumbnails |
| Picker, drag/drop, clipboard, upload progress | Implemented | Browser-only intake in `features/vision`; session-scoped API references |
| Screen capture | Implemented | Browser display permission; image is stored as a regular uploaded asset |
| Earth viewport capture | Implemented | Only through `EarthController.capture`; camera/time/source metadata are held in EarthContext and session workspace |
| Selected-region Earth capture | Implemented as pixel crop | User selects a rectangle on the captured viewport; pixel bounds are persisted; geographic bounds are not inferred |
| Image asset management | Implemented | Session list, content/thumbnail preview, delete, rename, and metadata update endpoints |
| Image viewer | Implemented | Zoom, pan, rotate, fullscreen, and metadata panel |
| Georeference metadata | Implemented | Optional user-supplied values are validated; no automatic location inference |
| Provider-neutral multimodal preparation | Implemented | `MultimodalPreparer` returns typed context and original asset bytes; no provider formatting |
| Attach images to Engine chat turn | Blocked | Engine Agent request currently accepts text only; the composer warns, prepares, and does not submit |

### Phase 5 Engine contract boundary

`AgentTurnRequest` and the HTTP adapter currently forward only text, model id, and execution
authorization. The Platform does not change that request shape, serialize provider-specific image
formats, or send an image-only turn that would be ignored. Once Engine exposes a typed multimodal
request and persistence contract, the chat adapter can be extended at that boundary. The selected
region crop stores pixel coordinates only; geographic region metadata remains unset unless the user
supplies it separately.

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
| Workspace memory | Implemented | On-demand lexical, geographic, and temporal retrieval across saved sessions, conversations, investigation/evidence references, assets, bookmarks, drawings, and snapshots; no embeddings or opaque-result parsing |
| Context retrieval | Implemented | Runs before chat turns and has a session-scoped memory search API; uses only indexed persisted facts |
| Prompt/context assembly | Implemented | Provider-neutral normalized plan; EarthContext is added as a clearly delimited text block because no structured Engine context field exists |
| Capability discovery | Implemented with explicit unknowns | Reads provider/tool/layer registries and wire contracts; Engine tools/datasets, provider vision support, and active frontend Earth handlers are not discoverable from current interfaces |
| Recommendations | Implemented for existing references | Can surface related stored investigations, assets, bookmarks, timeline overlaps, and conversations; does not recommend scientific conclusions, Engine tools, or datasets without discovery |
| Request Planner | Implemented | Validates and normalizes chat context, validates session-owned image IDs, estimates context budget, persists bounded EarthContext snapshots, and executes before every text turn |

### Phase 6 request and persistence behavior

`POST /api/v1/chat/sessions/{id}/turns` now obtains the Engine-owned transcript, builds the
provider-neutral plan, and forwards the plan's text message through the unchanged Engine Agent
request schema. If EarthContext exists, its descriptive JSON is included in that text message; the
frontend strips the Platform block when rendering the user's transcript. Full typed EarthContext
snapshots are retained in the Platform session JSON record with a configurable maximum of 20.

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

The planner does not pass image bytes or create Engine API fields that do not exist. It can resolve
stored asset metadata into `VisionContext` for the neutral plan, but chat submission with asset IDs
returns a validation error before the Engine Agent turn is called. Engine tool/dataset inventories,
provider image capability declarations, and frontend command-handler availability remain unknown;
the Platform does not guess them. The Engine's conversation history is authoritative and cannot be
compressed by the Platform until the Engine provides an explicit context/history contract.
