# Implementation status

Last updated: 2026-11-05

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
| V1 Phase 7 — Recurring monitoring | Engine-backed management and review workflow implemented; external delivery blocked | Mission/schedule creation, revision-checked schedule editing, optional Engine-executed rolling temporal windows, run history, comparisons, cursor-paged trigger activity, and operational notification acknowledgement are available; external delivery remains blocked |
| V2 Phase 7 — Investigation Workspace | Implemented within the defined scope | Durable Projects, sessions, Engine-backed investigation review, Project activity, investigation-scoped notes and Earth views, Engine-authored saved comparisons, monitoring references, Engine-owned hypothesis lifecycle review, Engine-authored reasoning review, and verified reproducibility exports exist. |
| Phase 8 — Platform Intelligence | Complete for the current Project-scoped Platform boundary | Researchers can find Project work, connect validated investigations, filter provenance-bearing workflow history, evolve reusable checklists without changing prior runs, and curate explicit investigation subsets as campaigns or review groups. The Platform does not generate Engine plans, scientific methods, or inferred group membership. |

## Current phase reassessment (2026-11-04)

The estimates below are the V1/V2 Phase 7 completion baseline, before Phase 8.
They are goal-relative judgments, not test coverage or production readiness.
The eight then-current Platform roadmap groups were equally weighted, giving an
overall Platform estimate of 89%. Phase 8 is tracked separately below and is
not included in that baseline.

| Phase | Estimate | Missing capability | Primary classification |
|---|---:|---|---|
| 1 — Platform foundation | 90% | Multi-worker durability and production operations | Deployment or external infrastructure |
| 2 — Agent Runtime integration | 80% | Authentication/authorization and interrupted-turn recovery | Product decision |
| 2 — Agent Runtime integration | 80% | Deployed Engine integration and vision-adapter validation | Deployment or external infrastructure |
| 3 — Earth Workspace foundation | 90% | Additional live Earth command kinds beyond the initial supported commands | New Engine contract |
| 4 — Earth Workspace | 90% | Layer catalogue, source access, and renderable layer semantics | Product decision |
| 5 — Vision | 90% | Provider-backed image interpretation | Deployment or external infrastructure |
| 6 — Earth Intelligence | 85% | Per-user memory isolation and identity ownership | Product decision |
| 6 — Earth Intelligence | 85% | Persistent full-text/vector indexing at demonstrated workload scale | Product decision |
| V1 Phase 7 — Recurring monitoring | 85% | External alert delivery | Product decision |
| V2 Phase 7 — Investigation Workspace | 100% | No remaining gap in the currently defined Phase 7 slices | — |

## V2 Phase 7 — Investigation Workspace

| Slice | Status | Delivered capability / boundary |
|---|---|---|
| 1. Project foundation and Project-owned sessions | Implemented | Platform Project CRUD/list/read/update/archive, transactional session creation and linking, single-Project session ownership, unlinked session discovery, generated contracts, Project navigation, and historical session association UI. Projects organize work; they do not contain or simulate Engine scientific state. |
| 2. Project investigation catalog | Implemented | Lists only Engine-issued investigation IDs observed in existing Engine transcripts for Project-linked sessions; session ownership is preserved and ID order is stable. |
| 3. Evidence, report, and source review | Implemented | Project catalog opens Engine-authored report text and digest, typed Engine source observations/provenance, and existing evidence/source observation references on Engine Earth Objects. Existing session ownership checks remain in force. |
| 4. Saved Earth views, notes, image links, and measurements | Implemented | Revision-checked Project notes and saved Earth-view snapshots persist in SQLite. Notes and views may be explicitly linked to an Engine investigation and source session; views are copied only from bookmarks in Project-linked sessions. Measurements and annotations are explicitly labeled as presentation state, not Engine evidence or scientific claims. |
| 5. Project timeline and reproducibility review | Implemented | Platform lifecycle actions are recorded transactionally in a bounded, paginated Project activity feed. Each Engine investigation exposes its existing cursor-paged journal in sequence order, including Engine event type, payload, plan ID, and hash-chain references. No chat prose is inferred as scientific state and no Engine behavior is duplicated. |
| 6. Project-linked monitoring | Implemented | Projects can link validated Engine schedule/mission identifiers, list or remove those references, and review Engine-owned run histories. Associations are transactional and included in Project activity; Engine schedule state and execution remain outside Platform persistence. |
| 7. Historical reopen and integrity behavior | Implemented | A saved Project Earth view can be restored into a durable bookmark in its original session and reapplied to the Earth workspace after navigation or restart. The Project snapshot remains readable after session deletion, but restoration is unavailable because its session-scoped assets and Engine-owned history no longer exist. |
| 8. Durable investigation workspace | Implemented | Catalog entries open a durable route that combines the Engine-authored report, source observations, Earth Object evidence references, and paged Engine journal. A typed Platform reference endpoint validates Project/session membership and the Engine transcript before the detail APIs are used. No Engine behavior or scientific state is added. |
| 9. Investigation-scoped notes | Implemented | Notes can be created and paged within an investigation workspace, retaining both Engine investigation ID and source-session ID. The API validates the pair against Project membership and the Engine transcript; notes remain Platform-owned annotations. Existing Project notes remain unscoped. |
| 10. Investigation-linked Earth views | Implemented | A Project view can retain an optional Engine investigation ID alongside its source-session and bookmark IDs. Creation validates the Engine reference and existing bookmark; investigation review can find and restore only views linked to that investigation. Existing Project-level views remain supported. |
| 11. Investigation Earth-context review | Implemented | The investigation workspace shows the saved view's camera position, presentation measurement, and image thumbnails through the source session's existing asset endpoint. Previews are hidden when the source session has been deleted; the snapshot remains readable. No Engine state is inferred. |
| 12. Investigation note editing and deletion | Implemented | Scoped annotations can be edited with the existing optimistic revision token or deleted directly from the investigation route. Requests preserve the Engine investigation/source-session association; errors, including stale revisions, remain visible. |
| 13. Durable investigation comparisons | Implemented | A Project can persist a titled pair of distinct Engine investigation references. Creation validates both linked sessions and Engine transcripts; the comparison route revalidates references, then displays Engine reports, source observations, evidence IDs, and a bounded journal page side by side. Project activity records create/delete operations; no scientific comparison is inferred. |
| 14. Engine-owned hypothesis lifecycle review | Implemented | Typed Engine models/client methods and session-scoped Platform endpoints expose lifecycle reads, explicit hypothesis registration, and expected-version transitions. The investigation route presents Engine records/events and requires researcher actor/rationale; Platform validation preserves source-session ownership and does not assess truth or synthesize lifecycle state. |
| 15. Engine-authored scientific comparison | Implemented | Creating a saved pair invokes the Engine's deterministic comparison API after validating both Project/session/transcript references. The Project transaction stores only the Engine comparison ID and SHA-256 digest; a new digest-addressed Engine read route restores the persisted scientific payload. The comparison workspace renders the Engine-authored Markdown, method versions, digest, and limitations alongside the original reports/evidence. |
| 16. Engine reasoning and reproducibility review | Implemented | Typed session-scoped routes expose Engine-authored reasoning and reproducibility bundles. The HTTP adapter verifies investigation identity and the canonical bundle digest; the investigation route presents findings, method-input sufficiency, limitations, missing artifacts, bundle digest, and JSON export. |
Slice 1 uses the existing Platform SQLite database. `projects` and `project_sessions` are
transactional, session deletion cascades association removal, linking is idempotent within the same
Project, and a session cannot belong to multiple Projects. Project updates use optimistic revisions.
The Project API contracts are generated from Pydantic models into the shared TypeScript contracts.
No Engine behavior or Engine contract was added.

Slice 2 adds a bounded, paginated Project investigation catalog at
`GET /api/v1/projects/{project_id}/investigations`. The Platform reads investigation IDs only from
Engine transcripts of sessions already linked to the Project, skips sessions that have never been
linked to an Engine Agent session, and never creates Engine sessions or infers scientific data.
Catalog entries carry the source Platform session ID; report, Earth Object, and journal requests
continue through their existing session-ownership checks.

Slice 3 adapts the Engine's existing investigation observations endpoint into the typed
`EngineObservation` contract and exposes it only through the session-scoped Platform route.
Project review presents the Engine report ID/digest and text, source observation identifiers and
Engine-supplied provenance metadata, and evidence/source IDs attached to Engine Earth Objects.
These are displayed as references; the Platform does not generate, verify, or reinterpret
scientific claims.

Slice 4 adds Project-owned notes and Earth-view snapshots. Notes have bounded fields, deterministic
pagination, revision-checked edits, and persistent create/read/update/delete operations. A saved view
copies an existing bookmark's typed EarthContext only after verifying that its source session belongs
to the Project and that the bookmark exists in that session. The source session and bookmark IDs are
retained for traceability, but the context snapshot has no session-delete cascade. The UI can save a
bookmark from a linked session, review camera/measurement/image references, open the source session,
and manage notes and saved views. The API reports when the original session has been deleted, while
retaining the Earth-context snapshot. Image previews use the original session-scoped image API; the
Platform does not copy image bytes or reinterpret local measurements as Engine evidence. All new
request/response models are generated into the shared TypeScript contracts.

Slice 5 adds an immutable Project activity record in the same SQLite transaction as each
Project/session association and Project, note, or saved-view mutation. The bounded, paginated feed
records resource identifiers, action, timestamp, and a short label; it does not copy conversation
text or pretend to preserve revisions of Engine state. Project investigations also expose the
Engine's existing sequence-paged event journal through the session-scoped route, preserving
Engine-issued sequence numbers, timestamps, payloads, and event hashes. The UI presents these
journals separately from Platform activity, with independent pagination and explicit ownership
labels; it does not recompute or claim to verify the Engine's hash chain.

Slice 6 adds a transactional Project-to-Engine monitoring association keyed by the Engine schedule
ID and carrying its Engine mission ID. The Platform validates a requested schedule against the
Engine's existing schedule catalogue before linking it; the repository stores only those IDs and
the link timestamp. A schedule may be referenced by multiple Projects, repeated linking to the
same Project is idempotent, and unlinking never deletes or changes the Engine schedule. Project
users can inspect current Engine schedule status and request its existing Engine run history, while
schedule editing and execution remain in the existing Monitoring panel/Engine boundary. Monitoring
links and removals are recorded in the Project activity journal.

Slice 8 replaces separate inline Review and History controls with a reloadable investigation
workspace URL containing the Project, source session, and Engine investigation identifiers. The
Platform checks the Project/session association before confirming the investigation against the
Engine transcript, then the frontend presents Engine reports, source observations, evidence
references, and cursor-paged execution history together.

Slice 9 adds optional investigation and source-session references to Project note contracts and
SQLite records. Existing databases receive additive nullable-column migration. Scoped note creation
and filtering validate both identifiers against the linked Project session and current Engine
transcript; unscoped Project notes continue to work. The investigation route can create, review, and
page these annotations. They are never presented as Engine findings or evidence.

Slice 10 adds an optional Engine investigation ID to saved Project Earth views. The source session
already retained by each view supplies the second half of the reference. The API validates the
investigation in that Project-linked session before creating the snapshot; existing databases
receive an additive nullable column. The investigation workspace can save existing bookmarks,
review its views, and restore them through the source session without converting them into Engine
evidence.

Slice 11 exposes details already present in an associated EarthContext snapshot directly in the
investigation workspace: camera position, presentation measurement, and image thumbnails. Image
content is still loaded from the source session's existing asset endpoint and is not copied into
Project storage. A missing source session suppresses previews without hiding the retained snapshot.
The component regression tests verify both the visible details and the missing-session behavior.

Slice 12 makes investigation-scoped Platform notes editable and deletable from the same route.
Updates pass the note's current revision to the existing API, so stale edits receive the established
conflict response instead of silently overwriting newer work. The UI reports update/delete errors
and only changes its local list after a successful persistence response.

Slice 13 stores only a title and two distinct Engine investigation/session references in a
Project-owned comparison record. Both references are checked against Project membership and the
Engine transcript on creation, and checked again before the review route loads Engine data. The
route displays Engine-owned reports, source observations, evidence identifiers, and a bounded
ordered journal page side by side. It does not compute or label a scientific delta. SQLite
mutations and Project activity events are transactional; comparisons remain as records if their
source sessions are later removed, while the review route reports that the Engine records can no
longer be loaded.

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

## Phase 8 — Platform Intelligence

| Capability | Status | Boundary |
|---|---|---|
| Project research search | Implemented | `GET /api/v1/projects/{project_id}/search` scans paginated records owned by that Project: Project metadata, linked session titles and typed workspace references, notes, saved Earth views, saved comparisons, researcher-authored relationship rationale, template text, and collection descriptions/member IDs. Results include deterministic lexical scores, matched terms/fields, concise excerpts, stable tie ordering, and offset pagination. The Project workspace links results to existing destinations. It does not search Engine scientific reports or opaque transcripts, recommend scientific outcomes, or create a duplicate scientific index. |
| Investigation relationships | Implemented | Researchers can create, list, and delete directional relationships between investigations already associated with Project-linked Engine sessions. The Platform verifies session membership and Engine transcript identity, requires a rationale, enforces ordered endpoint/type uniqueness, records activity transactionally, and indexes relationship rationale for Project search. Links and labels are researcher-authored organization, not scientific claims or Engine reasoning. |
| Investigation timeline | Implemented | Project activity events for scoped notes, saved Earth views, comparisons, and relationships carry the exact session-qualified Engine investigation references from their source artifacts. `GET /api/v1/projects/{project_id}/activity` filters by a complete investigation reference and returns stable paginated events; the UI presents provenance links. Indexed references and the event payload are committed transactionally. A one-time migration backfills references for retained scoped artifacts; already-deleted legacy records cannot safely supply missing provenance. |
| Investigation templates and revisioning | Implemented | Project-scoped templates store researcher-authored titles, descriptions, and bounded checklist steps. Expected-revision updates can change metadata and replace steps; new steps receive new IDs. Applying a template atomically creates a Project session and a frozen title/step/revision snapshot; progress is revision-checked. Template text is discoverable through Project search. Deleting a template or its source session leaves run history intact. No Engine reasoning, scientific method, or planning behavior is reproduced. |
| Investigation collections | Implemented | Project-scoped, researcher-authored collections group up to 500 exact Engine investigation references. Adding a member validates its linked Project session and Engine transcript; metadata and membership use expected revisions, changes are transactionally journaled with investigation provenance, and collection text/member IDs participate in deterministic Project search. Collections can be edited and deleted without changing Engine state. |

### Remaining Phase 8 gaps

- Cross-Project sharing and organization-level collections/templates are blocked on authentication,
  tenancy, and ownership decisions not present in the current local Platform.
- Scientific planning, scientific memory, and scientific dataset/analysis recommendations remain
  Engine-owned and require Engine contracts plus scientific validation. Phase 6 Platform memory,
  context planning, capability discovery, and existing-record recommendations are already
  implemented; this phase does not duplicate them.
- Semantic/vector retrieval is not justified without measured workload and requires deployment and
  identity-isolation decisions. Deterministic Project search and on-demand Phase 6 workspace memory
  remain the current retrieval surfaces.
- An interactive graph visualization is deferred unless observed navigation needs show value beyond
  the existing explicit relationships, collections, and durable investigation routes.

The endpoint accepts a nonblank query of at most 200 characters, `limit` 1–100, and a nonnegative
offset. Ranking is transparent token overlap (title matches are weighted above content matches),
then record update time, type, and stable ID. Search rebuilds its Project record set for each request;
large-scale full-text or vector indexing remains a separate workload-driven decision. As elsewhere
in the local Platform, Project scope is organizational rather than authenticated-user isolation.

## Validation results (2026-11-05)

| Check | Result |
|---|---|
| Backend Ruff | Passed; all backend source and tests |
| Backend mypy | Passed; all 90 backend source files |
| Backend pytest | Passed; 100 tests |
| Import-linter | Passed; 90 files and 278 dependencies analyzed |
| Frontend lint | Passed |
| Frontend typecheck | Passed |
| Frontend tests | Passed; 113 tests in 27 files, including all `.test.tsx` UI suites |
| Frontend production build | Passed; route and Cesium-backed Earth chunks are split; initial JavaScript chunk is 421.44 kB (123.48 kB gzip), below Vite's 500 kB advisory threshold |
| Contract schema and generated TypeScript | Passed; schema exported and generated types pass typecheck |
| `git diff --check` | Passed; Git reported only existing LF-to-CRLF working-copy warnings |
| Engine regression suite | Passed in prior full verification of unchanged Engine code; 559 tests, 2 skipped, 5 warnings |

The Engine regression suite now passes after addressing the multipart trace default, Pillow's
16-bit fixture compatibility, and schedule interval revisions retaining a stale due time. The
remaining warnings include unregistered markers in the separate `SAT_QUERY` test tree and
third-party deprecations.

Engine report, GeoJSON, EarthContext, mission, monitoring, and discovery boundary models are
exported through the shared contract and generated TypeScript types. Phase 8 relationship, search,
investigation-timeline provenance, revisioned investigation-template/run, and investigation-
collection models are included in the same generated contract.
