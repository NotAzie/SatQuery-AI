# `earth_platform/vision`

**Purpose.** Session-scoped image intake, persistence, and provider-neutral preparation/delivery,
with no model inside.

**Belongs here**
- `ImageIngestor` (all entry points converge here), `ImageStore`, `MultimodalPreparer`, `ImageAsset`
- Chat orchestration resolves asset IDs here; the API layer forwards original bytes through the
  typed Engine boundary.

**Never here**
- Image *understanding* (that is the LLM or an Engine tool)
- Geolocation/analysis (an investigation, not metadata)
- Browser concerns (drag & drop, screenshots live in the frontend)

**Depends on.** `settings`, `shared`.

**Public interface.** `ImageIngestor.ingest`, `ImageStore`, `MultimodalPreparer.prepare`, `ImageAsset`.
