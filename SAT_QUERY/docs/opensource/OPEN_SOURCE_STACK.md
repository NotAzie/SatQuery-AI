# Open-Source Stack Inventory

Audit date: 2026-09-16

This inventory records open-source projects considered for Phase 0. No new dependency is added by this inventory.

| Project | Purpose | License observed | Current use | Decision |
|---|---|---|---|---|
| [TorchGeo](https://github.com/torchgeo/torchgeo) | Geospatial datasets, samplers, transforms, benchmark datasets, and pretrained geospatial models | MIT | Not installed or imported by the current system | Evaluate for a future native geospatial/multispectral data layer and labeled datasets |
| [torchgeo-bench](https://github.com/torchgeo/torchgeo-bench) | Config-driven frozen-backbone evaluation on GeoBench and related tracks | MIT | Not installed or imported by the current system | Evaluate for future supervised/foundation-model benchmarking; current custom baseline remains smaller and RGB-specific |
| [Transformers](https://github.com/huggingface/transformers) | Model loading and inference APIs | Apache-2.0 | Installed and used by the model registry | Keep as the current inference dependency |
| [PyTorch](https://github.com/pytorch/pytorch) | Tensor runtime and model execution | BSD-style license | Installed and used by the model registry | Keep as the current runtime dependency |
| [Pillow](https://python-pillow.org/) | Image decoding, conversion, resizing, and crops | HPND | Installed and used by image ingestion | Keep for current RGB image handling |
| [FastAPI](https://github.com/fastapi/fastapi) | HTTP API framework | MIT | Installed and used by the API | Keep |
| [OpenAI CLIP model card](https://huggingface.co/openai/clip-vit-large-patch14) | Zero-shot image/text similarity model | Model card must be followed; deployment is explicitly cautioned and the model is not remote-sensing-specific | Current scene, grounding, and modality corroboration backend | Keep only as a clearly labeled baseline; require in-domain evaluation before stronger claims |
| [Salesforce BLIP caption model](https://huggingface.co/Salesforce/blip-image-captioning-large) | Image captioning | BSD-3-Clause model card | Current caption backend | Keep as baseline; it is general-image rather than EO-specific |
| [Salesforce BLIP VQA model](https://huggingface.co/Salesforce/blip-vqa-base) | Visual question answering | BSD-3-Clause model card | Current VQA backend | Keep as baseline; it is not remote-sensing-specialized |

## Selection notes

TorchGeo directly addresses gaps visible in the current system: band-aware data, CRS/resolution handling, geospatial datasets, and benchmark datasets. torchgeo-bench directly addresses reproducible downstream evaluation. Neither is integrated in Phase 0 because the current reference system accepts normalized RGB images and changing that dependency surface would change the baseline.

The current model cards do not establish remote-sensing accuracy for SatQuery. Model names, licenses, and repository URLs are recorded here; model revisions were not pinned by the current project and must be treated as unresolved provenance.

## External imagery provider

The optional fetcher requests imagery from Esri World Imagery and uses Nominatim/Photon for geocoding. These are runtime services rather than Python dependencies. The current fixture files do not contain sidecar license or acquisition metadata, so their provider terms and exact acquisition details are not fully reproducible from the repository alone.
