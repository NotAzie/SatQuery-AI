# Platform roadmap

The roadmap covers the Platform only. SatQuery Engine remains the sole execution system for
reasoning, tool calling, investigations, evidence, and scientific results.

## V2 Phase 7 — Investigation Workspace

**Objective:** make an Engine investigation the primary scientific artifact, organized inside a
durable Platform Project. Projects group work but never replace or duplicate Engine investigation,
report, evidence, or scientific state.

| Slice | Capability | Status | Why it comes next | Contract, reuse, complexity, dependencies |
|---|---|---|---|---|
| 1 | Project foundation and Project-owned sessions | Implemented | Establish durable organization and navigation first. | Platform `Project` and `ProjectSessionLink` HTTP models; SQLite Project tables and REST routes. Reuses session persistence, FastAPI container, React session navigation, and generated contracts. Medium. No Engine dependency. |
| 2 | Project investigation catalog | Implemented | Make Engine investigations—not chat sessions—the navigable scientific artifacts. | Platform returns Engine-issued IDs and their linked-session references only; reuses linked-session listing, Engine transcript, and existing session-scoped report/history APIs. Medium. Depends on Slice 1 and existing Engine records; no new scientific state. |
| 3 | Evidence, report, and source review | Implemented | Give users a complete review path from a catalog item to its Engine-authored conclusions and provenance. | Reuses typed Engine reports, source observations, Engine Object evidence/source IDs, and session-ownership checks. The Platform adapts the Engine's existing observations endpoint; no scientific inference or new Engine behavior. Medium/high. Depends on Slice 2 and existing Engine records. |
| 4 | Saved Earth views, notes, image links, and measurements | Implemented | Preserve useful presentation context without presenting local annotations as scientific evidence. | Platform-owned Project views and notes, with optional investigation-scoped associations; links to existing session image IDs; reuse persisted Earth workspace and image APIs. Medium/high. Depends on Slice 1 and explicit labeling of presentation-only data. |
| 5 | Project timeline and reproducibility review | Implemented | Make prior work understandable and replayable after the catalog and review surfaces exist. | Reuse Engine-paged investigation journal, Platform event/session timestamps, and saved Earth views; never infer scientific sequence from chat prose. High. Depends on Slices 2–4 and journal completeness. |
| 6 | Project-linked monitoring | Implemented | Bring ongoing Engine work into the same durable organization after investigation review is established. | Platform association to existing Engine schedule/mission IDs; reuse monitoring UI and Engine schedule/run APIs. Medium. Depends on Slice 1 and Engine IDs being sufficient to associate without transferring schedule ownership. |
| 7 | Historical reopen and integrity behavior | Implemented | Close the phase with reliable long-term navigation, links, and restoration across restarts and record lifecycle changes. | Reuses transactional Project/session storage, saved Earth snapshots, and existing session-scoped ownership; reopening persists a bookmark in the original session before restoring it. Medium/high. Depends on all preceding slices. |
| 8 | Durable investigation workspace | Implemented | Replace separate inline Review and History actions with one reloadable destination centered on an Engine investigation. | Reuses the existing report, observations, Earth Object, and cursor-paged journal contracts. A Platform endpoint verifies Project/session membership and the Engine transcript before returning the existing typed reference. Medium. Depends on Slices 2, 3, and 5; no new Engine contract or scientific state. |
| 9 | Investigation-scoped notes | Implemented | Attach a researcher's question or interpretation to the investigation it concerns, rather than leaving every note as an undifferentiated Project annotation. | Extends the Platform Project note contract with the existing Engine investigation ID and source-session ID. The Platform validates both against the linked Project session and Engine transcript, then persists and paginates notes by that pair. Medium. Depends on Slices 4 and 8; no Engine-owned notes or scientific claims. |
| 10 | Investigation-linked Earth views | Implemented | Reopen a map context from inside the investigation it documents instead of searching a Project-wide list. | Extends saved-view records with an optional Engine investigation ID bound to their existing source session. The Platform validates the association against the Engine transcript and filters views by that pair. Reuses EarthContext bookmarks and restoration. Medium. Depends on Slices 4 and 8; no new Engine contract. |
| 11 | Investigation Earth-context review | Implemented | Make imagery and measurements visible in the investigation that uses a saved map context, without requiring a detour to the Project catalog. | Presents the existing saved EarthContext camera, measurement, and image references in the investigation route. Image thumbnails use the existing source-session asset endpoint only while that session exists. Low. Depends on Slice 10; no new contract or persistence. |
| 12 | Investigation note editing and deletion | Implemented | Let researchers correct or remove their Platform annotations without leaving the investigation workspace. | Reuses the existing revision-checked Project note update and delete endpoints. The investigation/source-session association remains unchanged; no Engine contract is required. Low. Depends on Slice 9. |
| 13 | Durable investigation comparisons | Implemented | Review two related investigations together while preserving each Engine record as the scientific authority. | Adds a Platform comparison record containing only a title and two validated Engine investigation/session references. A side-by-side route presents existing reports, sources, evidence references, and the first bounded journal page. Medium. Depends on Slices 2, 3, 5, and 8; no new Engine contract. |
| 14 | Engine-owned hypothesis lifecycle review | Implemented | Give researchers an explicit, durable place to record and manage hypotheses associated with the scientific investigation, without asking the Platform to judge them. | Reuses the Engine's typed, versioned hypothesis graph and lifecycle APIs. The Platform validates session ownership, displays Engine records/events, and submits only explicit researcher declarations and version-checked transitions. Medium. Depends on Slices 2 and 8 and the existing Engine hypothesis contract. |
| 15 | Engine-authored scientific comparison | Implemented | Turn a saved pair of investigations into a reproducible evidence-alignment result, rather than only a side-by-side display. | Reuses Engine comparison generation and adds digest-addressed retrieval for its persisted result. The Platform validates both session/investigation links, stores only the Engine comparison ID/digest with the Project record, and renders Engine output and limitations. Medium/high. Depends on Slice 13 and the existing Engine comparison algorithm. |
| 16 | Engine reasoning and reproducibility review | Implemented | Complete the investigation workspace's review path by exposing Engine-authored scientific findings and the actual reproducibility export, rather than leaving existing Engine APIs inaccessible to researchers. | Adds typed session-scoped forwarding for Engine reasoning and reproducibility endpoints. The Platform validates response shapes, investigation identity, and the canonical bundle SHA-256, then presents Engine findings, method-input sufficiency, limitations, bundle digest, missing artifacts, and JSON download. Medium. Reuses existing Engine APIs; no new scientific behavior or Engine contract. Depends on Slice 8 and existing Engine reasoning/export records. |

## Current phase reassessment (2026-11-04)

These are goal-relative estimates of the Platform roadmap as implemented in
this repository, not test coverage or production-readiness claims. Each phase
is weighted equally. The overall Platform estimate is 89%.

| Phase | Estimate | Genuinely missing capability | Primary classification |
|---|---:|---|---|
| 1 — Platform foundation | 90% | Multi-worker durability and production operations | Deployment or external infrastructure |
| 2 — Agent Runtime integration | 80% | Authentication/authorization and interrupted-turn recovery | Product decision |
| 2 — Agent Runtime integration | 80% | Live validation against a deployed Engine and vision-capable adapter | Deployment or external infrastructure |
| 3 — Earth Workspace foundation | 90% | Additional live Earth command kinds beyond the initial supported commands | New Engine contract |
| 4 — Earth Workspace | 90% | Layer catalogue, source access, and renderable layer semantics | Product decision |
| 5 — Vision | 90% | Provider-backed image interpretation | Deployment or external infrastructure |
| 6 — Earth Intelligence | 85% | Per-user memory isolation and identity ownership | Product decision |
| 6 — Earth Intelligence | 85% | Persistent full-text/vector indexing at demonstrated workload scale | Product decision |
| V1 Phase 7 — Recurring monitoring | 85% | External alert delivery | Product decision |
| V2 Phase 7 — Investigation Workspace | 100% | No remaining gap in the currently defined Phase 7 slices | — |

No additional Platform-only implementation slice is justified by these
remaining gaps. Resume them when their listed product decisions, Engine
contracts, scientific validation, or deployment dependencies are supplied.

Slice 1 defines the Platform Project as the organizing container and an Engine investigation as the
scientific artifact. A Platform session remains the interaction/Earth-workspace context and can be
linked to at most one Project. Projects and their session links are Platform-owned and persisted
transactionally; session deletion cascades to its link. Project revisions protect concurrent edits.
No new Engine contract is required for this slice.

Slice 8 makes each catalog entry a durable investigation route. Its Platform reference endpoint
checks that the source session belongs to the Project and that the Engine transcript contains the
requested investigation before the UI loads the existing Engine report, observations, Earth Object
references, and execution journal. It replaces separate inline Review and History actions without
adding Engine behavior.

Slice 9 adds explicit investigation association to Platform notes. Both identifiers are required
together and validated against the linked session's Engine transcript. Unscoped notes remain
Project-level; scoped notes appear in the investigation workspace.

Slice 10 applies the same explicit association to saved Earth views, using the existing source
session ID plus the Engine investigation ID. The view remains a Platform snapshot of EarthContext;
it can be restored in the original session, but it does not become Engine evidence or a scientific
result. Existing unscoped Project views remain supported.

Slice 11 brings the saved EarthContext's camera location, presentation measurement, and image
references into the investigation route itself. Image previews continue to use the original
session-scoped asset endpoint and are omitted when that source session no longer exists. No image
bytes or scientific meaning are copied into the investigation record.

Slice 12 completes the investigation note lifecycle by exposing revision-checked edits and deletion
beside each scoped annotation. The existing Project API remains authoritative for note persistence
and concurrency; the investigation route only updates its local presentation after a successful
response.

Slice 13 adds durable Project comparisons of two distinct Engine investigation references. The
Platform validates both references against the Project's linked sessions and Engine transcripts,
persists the selected pair and user-provided title transactionally, and records creation/removal in
Project activity. The comparison view presents Engine-authored records side by side and does not
calculate scientific differences or conclusions.

Slice 14 exposes the Engine's existing hypothesis graph and lifecycle through session-scoped
Platform routes after validating that the investigation belongs to the Engine transcript linked
to that Platform session. The investigation workspace presents Engine-authored propositions,
versions, lifecycle states, and events. Researchers may register explicit propositions and request
version-checked transitions with an actor and rationale; the Engine remains authoritative for
validity and scientific meaning. The Platform does not generate hypotheses, assess truth, or infer
transitions. Unavailable lifecycle history and rejected mutations are shown as errors rather than
replaced with local state.

Slice 15 wires the existing Engine investigation-comparison operation into saved Project
comparisons. Creation validates both Project/session/Engine transcript references before asking the
Engine to align its explicit canonical measurements and eligible exact-support temporal diagnostics.
The Project stores only the Engine comparison ID and full content digest with the two source
references; Engine Memory retains the scientific payload. A digest-addressed Engine endpoint
restores that exact payload, and the Platform displays its output and limitations without
recalculation or scientific interpretation.

For later slices, Platform contracts must carry Engine-issued investigation, report, evidence, and
source identifiers without fabricating or reinterpreting their content. If an Engine-owned listing
or provenance contract proves insufficient, record the exact missing contract and defer that
sub-capability rather than synthesizing scientific state in the Platform.

## Phase 1 — Platform foundation

**Status: implemented foundation.** Modular backend/frontend shells, contracts, DI, configuration,
Cesium isolation, session metadata persistence, and resumable event infrastructure are in place.

## Phase 2 — Agent Runtime integration

**Status: integration slice implemented; production closure is deferred on external dependencies.**
Platform chat delegates to
the Engine Agent API, links Platform sessions to Engine transcripts, and presents streamed events.
Investigation progress events are presented as a bounded activity timeline. Engine-authored reports
and verified WGS 84 Earth Object GeoJSON can be opened only for IDs in the active Engine transcript.
The Platform displays and manages these Engine-owned records without inferring results or
reprojecting geometry; Stop delegates cancellation to the Engine before closing the local stream.
The Engine also provides bounded, cursor-paged execution history for session-owned investigations;
typed Earth Object properties preserve linked evidence IDs for selection and highlighting.
The Platform does not create an Agent Runtime. Deployment verification, authentication, run
recovery, and provider-backed image interpretation remain outstanding. Image delivery is supported
through the Engine's typed per-turn attachment contract. EarthContext is sent as a typed per-turn
field rather than appended to the user message. It captures the primary and secondary view when
split view is active. See
[implementation status](implementation-status.md).

Production closure is deferred until the Engine/deployment contract and deployment decisions exist:
authentication needs an accepted credential scheme/header and error behavior; per-user authorization
needs an identity and ownership policy; interrupted-turn recovery and multi-worker delivery need
Engine resume semantics plus a shared worker/event deployment design; live adapter validation needs
a reachable deployed Engine version. Image interpretation needs a deployed Engine adapter that
declares vision support.

## Phase 3 — Earth Workspace foundation

**Status: first live Engine commands implemented.** The Engine Agent exposes a typed
`earth.command` tool and emits a sequenced SSE event only for explicit presentation requests.
The Platform validates and persists that event as its shared `EarthCommandIssued` contract.
`fly_to` and session-linked `show_investigation` are wired to the Earth workspace.

Commands are never inferred from assistant prose or scientific tool results. The Engine validates
investigation IDs against the active Agent session before emitting `show_investigation`; the Platform
rechecks session ownership before loading the report or GeoJSON.

The Engine Agent SSE event uses the existing envelope
(`session_id`, `turn_id`, `sequence`, `timestamp`), `kind: "earth.command"`, and a `payload.command`
currently limited to `fly_to` and `show_investigation`. Additional command types remain unavailable
until Engine-owned data and ownership semantics support them. Any future command geometry must be
explicit WGS 84 GeoJSON from Engine-owned records, never generated from prose or silently reprojected
by the Platform.

## Phase 4 — Earth Workspace

**Status: in progress.** Add real presentation capabilities while consuming only typed Engine data
for scientific state. No scientific results, investigation geometry, or layer catalogue may be
created by the Platform.

1. **Investigation visualization and evidence highlighting** — implemented for Engine-recorded
   execution history and materialized Earth Objects. Users can show the Engine's explicitly
   materialized RFC 7946 WGS 84 Earth Objects for a linked investigation, inspect the bounded
   cursor-paged execution journal, and select/highlight evidence IDs retained in typed GeoJSON
   properties. The Engine exporter omits unsupported geometries and reports why; the Platform does
   not repair or reproject them. Live turn progress remains separately streamed by the Engine Agent.
   Opaque tool results are not a safe substitute.
2. **Layer manager** — blocked pending a product/deployment decision on supported renderable layer
   sources, approved providers and licensing, credential/access rules, and source-serving endpoints.
   Current Engine dataset metadata describes acquisition capability, not renderable URLs or layer
   ownership; the Platform must not turn it into fabricated layers or arbitrary URLs.
3. **Timeline** — implemented as a local Earth workspace presentation control: users can select a
   time range and instant, scrub, and play/pause the Cesium clock. Its current time and playback
   state are sent as untrusted EarthContext scope; this does not claim data availability or provide
   Engine-side temporal execution.
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
   independent cameras by default, and opt-in camera synchronization. Overlay visibility is tracked
   per view; only the primary view's active overlays form the chat EarthContext.

Investigation reports, paged execution history, and explicitly exported WGS 84 Earth Object overlays
are available from the Engine. Unsupported objects remain omitted according to the Engine's declared
geometry policy. Engine-backed layer management remains blocked at the integration boundary; the
Platform does not fabricate layers or infer geometry from prose.

The sequence may advance around Engine contract blockers, but no feature may synthesize Engine-owned
scientific information. Phase 4 is not complete until implemented capabilities are tested and all
remaining boundaries are documented.

## Phase 5 — Vision

**Status: typed Engine image delivery is implemented; image interpretation requires a
vision-capable Engine adapter.** The Platform accepts and validates session-scoped images, keeps
browser and Cesium handling in the Vision/Earth modules, and sends original bytes through the
provider-neutral Agent attachment contract. The Engine verifies image metadata and content hashes,
persists references in its transcript, and delivers current-turn bytes only to a registered adapter
that declares vision support. Canonical image bytes remain Platform-owned. The Platform performs no
image interpretation or scientific work.

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
5. **Chat boundary** — the composer sends selected asset IDs alongside the user message. The
   Platform resolves the canonical bytes and sends a separate typed attachment list, with bounded
   size/count and verified MIME/size/SHA-256 metadata. The Engine persists attachment references
   rather than duplicating Platform image storage; transcript reload displays those references as
   thumbnails through the owning Platform session. Requests are rejected before streaming unless
   the selected Engine adapter declares vision support.

Provider-specific request formatting, scientific interpretation, object detection, segmentation,
and reasoning remain outside this Platform module. Deployments must register a vision-capable Engine
adapter to use image turns; the core Engine deliberately includes no provider SDK.

## Phase 6 — Earth Intelligence

**Status: Platform-owned context/planning and Engine dataset/image-capability/Earth modality/Agent
tool discovery are implemented and validated; provider-specific image interpretation remains
deployment-dependent.**

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
5. **Prompt Assembly** — implemented as a vendor-neutral normalized plan. Typed Engine-bound
   EarthContext, verified stored image metadata, relevant memory, capability status, and the current
   message are accounted for against a byte-based token estimate. Low-ranked memory and older
   context are compressed first. The estimate is not a provider tokenizer and cannot budget the
   Engine's hidden transcript.
6. **Capability Discovery** — implemented at `GET /api/v1/intelligence/capabilities`. Provider
   factories, configured providers, registered Platform tool sources and layers, EarthContext
   fields, and command contracts are discovered from their registries/contracts. The Earth
   workspace's Engine data panel reads Engine-registered datasets, image-analysis capabilities, and
   the versioned Earth modality snapshot from published Engine APIs through a validated Platform
   endpoint. It also presents Engine-published Agent tool descriptors and their input schemas,
   availability, and execution-consent visibility without invoking tools. These declarations do
   not guarantee data access or scientific suitability. Provider vision support and active
   frontend Earth handlers remain unknown unless an implementation exposes a discoverable contract;
7. **Recommendations** — implemented for references that actually exist in retrieved Platform
   memory (investigation IDs, uploaded assets, bookmarks, timeline-overlapping records, and prior
   conversations). No scientific outcomes are recommended. Dataset recommendations are not
   generated from catalogue metadata alone; tool descriptors are presented for inspection, not
   ranked or recommended from free text.
8. **Request Planner** — implemented before every chat turn and available for inspection at
   `POST /api/v1/chat/sessions/{id}/plan`. It validates session-scoped asset references, normalizes
   Earth and vision metadata, retrieves memory, estimates context size, and returns explicit boundary
   warnings. Model-relevant EarthContext is sent in the Engine Agent request's typed `earth_context`
   field, separate from the user message. The Engine validates and presents that context to its
   reasoning model as untrusted workspace scope. The snapshot includes viewport and camera,
   timeline/playback, selection, imagery references, active overlay geometry, evidence highlights,
   investigation references, primary/secondary viewports, bookmarks, camera history, split-view,
   measurements, and layer state.
   Image bytes remain separate transient attachments; no scientific availability is inferred.

### Phase 6 integration boundaries

- The Engine Agent API persists its own complete conversation. Platform history limits and
  extractive compression are available in the neutral plan but cannot trim the Engine's internal
  transcript; structured EarthContext is per-turn scope, not a replacement history contract.
- The Engine Agent API accepts image attachments. The Platform stores canonical bytes and resends
  selected assets per turn; Engine transcripts retain metadata references only. The configured
  Engine reasoning adapter must declare vision support; the core does not select or install a
  provider-specific vision model.
- The Platform can read registered Engine datasets, the versioned Earth modality snapshot,
  legacy image-analysis capability status, and typed Agent tool descriptors through published
  Engine APIs. Descriptors are presented read-only and do not invoke tools; visibility distinguishes
  default turns from turns with explicit execution consent. Dataset metadata is declared registration,
  not proof of live access or suitability. A configured Agent adapter must declare vision support
  before an image turn is accepted.
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

- Current Platform validation and remaining Engine/deployment boundaries are recorded in the
  [implementation status](implementation-status.md).

## V1 Phase 7 — Recurring monitoring workflows

**Status: Engine-backed management and review workflow implemented.** The workspace can create and
select Engine-owned missions, create recurring schedules from a user-declared WGS 84 bounding box
and optional requested variables, revise schedule name, supported query scope, interval, priority,
overlap policy, and trigger policies through optimistic revisions, enable or pause schedules,
inspect durable run history, and open the Engine-authored comparison for recent completed runs. The
Platform only validates and presents the typed Engine contract, lists operational alerts for
partial/failed runs, and acknowledges notifications. Users may declare descriptive-measurement
trigger policies when creating or revising a schedule, then inspect Engine-authored trigger
lifecycle events. The Platform does not execute investigations or interpret measurements.

Schedules may optionally declare a rolling lookback duration. For each run, the Engine anchors the
window end to the persisted run start time, subtracts the declared duration for the start, and
executes the resulting EarthQuery; the resolved bounds are retained in run history. Rolling windows
cannot be combined with fixed EarthQuery temporal bounds. Engine comparisons align explicitly
resolved canonical variables and exact unit strings; they do not establish trend, causality, or
scientific comparability. Trigger activity uses the Engine's cursor-paged history contract. External
alert delivery is blocked until the Engine exposes a typed delivery configuration/lifecycle and the
deployment selects and configures a delivery provider.

## Later platform capabilities

Broader provider administration and runtime plugin contributions require product/security decisions;
distributed deployment requires externally provisioned shared infrastructure. These are deferred
capabilities and do not authorize duplicating Engine execution.

## Deferred roadmap blockers

Blocked capabilities stay on the roadmap and can resume when their dependencies are available:

| Capability | Classification | Explicit dependency |
|---|---|---|
| Earth layer manager | 4. Blocked by deployment or product decisions | Select supported renderable source kinds and approved providers/licensing, define credential/access rules, and provide source-serving endpoints from which the Engine can publish stable layer/source IDs and CRS/geometry semantics |
| External monitoring alert delivery | 4. Blocked by deployment or product decisions | Select an operator-supported delivery provider and define destinations, credentials, retry/idempotency policy, and delivery ownership before adding the Engine-owned delivery contract |
| Production Engine authentication | 4. Blocked by deployment or product decisions | Engine or proxy decision for accepted credential scheme/header, protected endpoints, and authentication error contract |
| Platform user authentication and authorization | 4. Blocked by deployment or product decisions | Identity provider, tenant boundaries, and per-user session/resource ownership |
| Interrupted-turn recovery and multi-worker delivery | 5. Blocked by external infrastructure | Select and deploy durable workers and shared event storage/broker; define recovery ownership and resume semantics against that infrastructure before implementing the Engine contract |
| Live Engine adapter validation | 5. Blocked by external infrastructure | Reachable deployed Engine version and deployment configuration |
| Image interpretation | 5. Blocked by external infrastructure | Deployed Engine reasoning adapter that declares vision support and its provider configuration |
| Broader provider administration | 4. Blocked by deployment or product decisions | Product requirements for administrative roles, provider lifecycle, and credential-management UX |
| Runtime plugin loading | 4. Blocked by deployment or product decisions | Administrator trust, backend execution permissions, and frontend module serving/security decisions |
| Distributed Platform deployment | 5. Blocked by external infrastructure | Deployment decision and shared durable work, event fan-out, and persistence infrastructure |
| Persistent full-text/vector memory index | 4. Blocked by deployment or product decisions | Product workload and scale requirements establishing that query-time index rebuilding needs replacement |
