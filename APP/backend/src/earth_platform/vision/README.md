# `earth_platform/vision`

**Purpose.** Image intake and multimodal preparation, with no model inside.

**Belongs here**
- `ImageIngestor` (all entry points converge here), `ImageStore`, `MultimodalPreparer`, `ImageAsset`

**Never here**
- Image *understanding* (that is the LLM or an Engine tool)
- Geolocation/analysis (an investigation, not metadata)
- Browser concerns (drag & drop, screenshots live in the frontend)

**Depends on.** `llm` (capabilities only), `settings`, `shared`.

**Public interface.** `ImageIngestor.ingest`, `ImageStore`, `MultimodalPreparer.prepare`, `ImageAsset`.
