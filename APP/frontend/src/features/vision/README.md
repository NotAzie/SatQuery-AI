# `src/features/vision`

**Purpose.** Image intake and presentation: file picker, drag/drop, clipboard, screen capture,
Earth viewport/selected-pixel-region capture, upload progress, attachment selection, preview, and
user-entered georeference metadata.

**Public interface.** `VisionAttachments` is registered by the app composition root as the image
panel. The chat composer opens it and reads selected stored `ImageAsset` references through shared
state. The `services/api/vision` client uploads and manages assets; `PreparedVisionPayload` is
provider-neutral and is not forwarded to the Engine until its Agent API supports multimodal input.

**Boundaries.** Browser and image logic stays inside this feature. Earth screenshots use
`EarthController.capture`; no Cesium types are imported here. This module does not interpret images,
infer georeferences, format requests for a model vendor, or perform scientific analysis.
