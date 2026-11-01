# Platform roadmap

The roadmap covers the Platform only. SatQuery Engine remains the sole execution system for
reasoning, tool calling, investigations, evidence, and scientific results.

## Phase 1 — Platform foundation

**Status: implemented foundation.** Modular backend/frontend shells, contracts, DI, configuration,
Cesium isolation, session metadata persistence, and resumable event infrastructure are in place.

## Phase 2 — Agent Runtime integration

**Status: integration slice implemented; production closure remains.** Platform chat delegates to
the Engine Agent API, links Platform sessions to Engine transcripts, and presents streamed events.
The Platform does not create an Agent Runtime. Deployment verification, authentication, run recovery,
and structured Earth-context/image input remain outstanding; the Platform currently appends
descriptive Earth state to the existing text field only. See
[implementation status](implementation-status.md).

## Phase 3 — Earth Workspace foundation

**Status: dispatcher foundation implemented.** The Earth command dispatcher accepts typed
`earth.command` events, and `fly_to` is wired to the camera controller. The Engine contract gap
below currently prevents live turns from supplying those events.

The Engine Agent event contract currently has no dedicated `earth.command` event kind. The frontend
dispatcher consumes the Platform's typed `EarthCommandIssued` event contract, but its source must be
connected to an explicit Engine event contract before live Engine turns can issue those commands.
The Platform must not infer commands from model text or scientific tool results.

## Phase 4 — Earth Workspace

**Status: in progress.** Add real presentation capabilities while consuming only typed Engine data
for scientific state. No scientific results, investigation geometry, or layer catalogue may be
created by the Platform.

1. **Investigation visualization and evidence highlighting** — blocked pending a typed Engine
   event/API carrying investigation lifecycle and renderable evidence geometry. Opaque tool results
   are not a safe substitute.
2. **Layer manager** — blocked pending an Engine-provided layer catalogue and source definitions.
   The Platform must not invent scientific layers.
3. **Timeline** — implemented as a local Earth workspace presentation control: users can select a
   time range and instant, scrub, and play/pause the Cesium clock. It does not claim data availability
   or send context to the Engine; a supported Engine context/command contract is still needed for
   investigation-time integration.
4. **Camera history and bookmarks** — implemented. Camera move-end states support bounded undo/redo
   and precise restore; named EarthContext bookmarks can be created, renamed, updated, deleted, and
   flown to. State is persisted in the Platform's SQLite-backed session record, with browser-local
   storage as a cache/fallback.
5. **Earth selection and drawings** — implemented as typed local context state. Cesium entity
   selection publishes `earth.selection.changed`; point, line, polygon, rectangle, and circle are
   user-created presentation objects only and never trigger Engine work.
6. **Measurements** — implemented for geodesic distance, spherical polygon area, coordinate
   inspection, and local terrain elevation where the loaded terrain provider returns a height.
7. **Split view** — implemented with a second Cesium view, shared timeline, selection and drawings,
   independent cameras by default, and opt-in camera synchronization. Engine-owned overlays will
   also be shared once the Engine supplies renderable typed overlay events.

Investigation-result overlays are not fabricated or presented as complete. The current Engine event
contract still does not provide typed investigation geometry/lifecycle or a layer catalogue, so
investigation visualization, evidence highlighting, and Engine-backed layer management remain
blocked at that integration boundary.

The sequence may advance around Engine contract blockers, but no feature may synthesize Engine-owned
scientific information. Phase 4 is not complete until implemented capabilities are tested and all
remaining boundaries are documented.

## Phase 5 — Vision

**Status: Platform-owned ingestion and preparation foundation implemented; Engine delivery is
blocked by the current text-only Agent API.** The Platform accepts and validates session-scoped
images, keeps browser and Cesium handling in the Vision/Earth modules, and prepares a neutral
metadata-plus-bytes payload. It performs no image interpretation or scientific work.

1. **Image intake and storage** — file picker, drag/drop, clipboard paste, and display capture
   converge on the Vision attachment module. Uploads report progress, enforce the configured
   MIME/size/count limits, verify actual image encoding, store original bytes and generated
   thumbnails on the configured filesystem adapter, and expose list/content/thumbnail/update/delete
   endpoints scoped to an existing Platform session, with both per-file and aggregate message
   byte limits.
2. **Earth capture** — the Vision module captures the current Cesium viewport through the public
   `EarthController.capture` interface and can crop a user-selected rectangle from that captured
   image. Capture time, camera, and source pixel rectangle are stored in EarthContext and the
   session workspace. Pixel crop metadata is not treated as geographic bounds and is not inferred
   into a georeference.
3. **Viewer and georeference** — uploaded images can be previewed, zoomed, panned, rotated, and
   viewed fullscreen. Users can supply a center coordinate; backend contracts validate optional
   bounds, center, CRS, orientation, and positive pixel resolution. No georeference is inferred.
4. **Provider-neutral preparation** — `MultimodalPreparer` resolves attached asset IDs within the
   owning session and returns `PreparedVisionPayload` containing original bytes (base64 encoded for
   transport) plus typed `VisionContext`. No vendor formatting or vision model is selected here.
5. **Chat boundary** — the composer can select and prepare attachments, but it does not send an
   image turn. The inspected Engine Agent request currently accepts only `message`, `model_id`, and
   `execution_authorized`; until Engine publishes a multimodal request contract, the UI explicitly
   reports that nothing was submitted rather than silently dropping images or fabricating an API.

The Phase 5 Engine integration remains open until the Engine Agent Interface defines a supported
multimodal request shape and attachment lifecycle. Provider-specific request formatting, scientific
interpretation, object detection, segmentation, and reasoning remain outside this Platform module.

## Phase 6 — Earth Intelligence

**Status: Platform-owned context and planning foundation implemented; Engine discovery and
multimodal execution remain bounded by the current Engine Agent API.**

1. **Earth Context Builder** — implemented. Chat requests may include the current typed EarthContext.
   The builder merges it with persisted camera history, bookmarks, captures, pinned Engine evidence
   references, prior snapshots, and timeline focus. It includes local selection, drawings,
   measurements, layers, and split-view metadata only when the browser actually supplies them.
   Completed snapshots are retained in the Platform session JSON record, with a configurable cap.
2. **Conversation Context Builder** — implemented. It reads the Engine-owned transcript, applies
   configurable message-count and estimated-token limits, and uses extractive excerpts when older
   messages do not fit. Engine still owns its full transcript: the current Engine API cannot accept a
   replacement/compressed history, so this bounded context is planning metadata and is not sent as
   duplicate conversation history.
3. **Workspace Memory** — implemented as a deterministic, on-demand index over Platform sessions,
   persisted conversations, typed investigation/evidence references, EarthContext snapshots,
   bookmarks, drawings, uploaded image metadata, and typed investigation progress events. Retrieval
   ranks lexical matches plus local geographic proximity and timeline recency. It does not use
   embeddings or reinterpret opaque Engine results.
4. **Context Retrieval** — integrated before each chat turn and also exposed at
   `GET /api/v1/intelligence/sessions/{id}/memory`. The builder ranks only existing workspace
   records; no history is generated when a source record is absent.
5. **Prompt Assembly** — implemented as a vendor-neutral normalized plan. EarthContext, verified
   stored image metadata, relevant memory, capability status, and the current message are accounted
   for against a byte-based token estimate. Low-ranked memory and older context are compressed first.
   The estimate is not a provider tokenizer and cannot budget the Engine's hidden transcript.
6. **Capability Discovery** — implemented at `GET /api/v1/intelligence/capabilities`. Provider
   factories, configured providers, registered Platform tool sources and layers, EarthContext
   fields, and command contracts are discovered from their registries/contracts. Provider vision
   support and active frontend Earth handlers are reported unknown unless an implementation exposes
   a discoverable contract. Engine tool and dataset inventories are unknown because no such Engine
   discovery endpoint exists.
7. **Recommendations** — implemented for references that actually exist in retrieved Platform
   memory (investigation IDs, uploaded assets, bookmarks, timeline-overlapping records, and prior
   conversations). No scientific outcomes are recommended. Tool and dataset recommendations are
   withheld while Engine discovery is unavailable.
8. **Request Planner** — implemented before every text chat turn and available for inspection at
   `POST /api/v1/chat/sessions/{id}/plan`. It validates session-scoped asset references, normalizes
   Earth and vision metadata, retrieves memory, estimates context size, and returns explicit boundary
   warnings. EarthContext is included in the Engine's existing text-only `message` as a clearly
   delimited, serialized descriptive context block; it is never sent as a fabricated structured
   Engine field. The UI hides this machine-added block when rendering the user transcript.

### Phase 6 integration boundaries

- The Engine Agent API persists its own complete conversation. Platform history limits and
  extractive compression are available in the neutral plan but cannot trim the Engine's internal
  transcript until it supports a context/history input.
- Image IDs and typed metadata can be validated and appear in a plan, but image bytes are not sent.
  Chat requests with attachment IDs are rejected before an Engine turn starts. The Engine must
  publish a multimodal request and persistence contract first.
- The current Engine client cannot discover tools, datasets, or Engine-side provider capabilities.
  No tool/dataset recommendation is fabricated.
- Search is deterministic lexical/geographic/temporal ranking, not embedding/vector search. The
  index is rebuilt from persisted Platform records at query time; a durable full-text/vector index
  is a future performance extension if workspace volume requires it.
- Cross-session retrieval currently assumes one trusted workspace because Platform authentication
  and ownership partitioning are not implemented. Do not expose cross-session memory in a shared-user
  deployment until records can be filtered by authenticated owner.
- Engine transcripts are fetched only for the active session. Related conversation retrieval across
  sessions uses Platform-persisted `Conversation` records; the Platform does not fan out Engine
  transcript requests or parse opaque history from other Engine sessions.
- The Engine remains authoritative for investigation/evidence content. Only typed investigation IDs,
  typed investigation progress events, and saved evidence references are indexed; opaque tool results
  and assistant prose are not parsed as scientific records.

## Later platform capabilities

Broader provider administration, plugin contributions, and distributed deployment remain future
work; they do not authorize duplicating Engine execution.
