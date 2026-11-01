# `src/earth/layers`

**Purpose.** Layer catalogue rendering. Interfaces only.

**Belongs here**
- `LayerController`, `LayerRenderer` (one per `LayerSpec.kind`), `RenderedLayer`

**Never here**
- Hard-coded layer URLs (layers come from the backend catalogue or plugins)

**Depends on.** `cesium`, `shared`.

**Public interface.** `LayerRenderer.create`, `LayerController.sync/setVisibility`.
