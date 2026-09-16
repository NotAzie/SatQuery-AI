# Open-Source Stack Inventory

Audit date: 2026-09-16

This inventory records open-source projects considered for Phase 0. No new dependency is added by this inventory.

| Name | Repository | Purpose | License | Status | Relevant SatQuery phase |
|---|---|---|---|---|
| [TorchGeo](https://github.com/torchgeo/torchgeo) | https://github.com/torchgeo/torchgeo | Geospatial datasets, samplers, transforms, benchmarks, and pretrained models | MIT | Evaluated; not integrated | Future geospatial/multispectral phases |
| [torchgeo-bench](https://github.com/torchgeo/torchgeo-bench) | https://github.com/torchgeo/torchgeo-bench | Config-driven frozen-backbone evaluation | MIT | Evaluated; not integrated | Future benchmark expansion |
| [Transformers](https://github.com/huggingface/transformers) | https://github.com/huggingface/transformers | Model loading and inference APIs | Apache-2.0 | Integrated | Current product |
| [PyTorch](https://github.com/pytorch/pytorch) | https://github.com/pytorch/pytorch | Tensor runtime and model execution | BSD-style | Integrated | Current product |
| [Pillow](https://python-pillow.org/) | https://github.com/python-pillow/Pillow | Image decoding and processing | HPND | Integrated | Current product |
| [FastAPI](https://github.com/fastapi/fastapi) | https://github.com/fastapi/fastapi | HTTP API framework | MIT | Integrated | Current product |
| [OpenAI CLIP model card](https://huggingface.co/openai/clip-vit-large-patch14) | https://huggingface.co/openai/clip-vit-large-patch14 | Zero-shot image/text similarity | Model-card terms and deployment cautions apply | Integrated as baseline | Current Phase 0/2 baseline |
| [Salesforce BLIP caption model](https://huggingface.co/Salesforce/blip-image-captioning-large) | https://huggingface.co/Salesforce/blip-image-captioning-large | Image captioning | BSD-3-Clause | Integrated as baseline | Current Phase 0/2 baseline |
| [Salesforce BLIP VQA model](https://huggingface.co/Salesforce/blip-vqa-base) | https://huggingface.co/Salesforce/blip-vqa-base | Visual question answering | BSD-3-Clause | Integrated as baseline | Current Phase 0/2 baseline |

## Selection notes

TorchGeo directly addresses gaps visible in the current system: band-aware data, CRS/resolution handling, geospatial datasets, and benchmark datasets. torchgeo-bench directly addresses reproducible downstream evaluation. Neither is integrated in Phase 0 because the current reference system accepts normalized RGB images and changing that dependency surface would change the baseline.

The current model cards do not establish remote-sensing accuracy for SatQuery. Model names, licenses, and repository URLs are recorded here; model revisions were not pinned by the current project and must be treated as unresolved provenance.

## External imagery provider

The optional fetcher requests imagery from Esri World Imagery and uses Nominatim/Photon for geocoding. These are runtime services rather than Python dependencies. The current fixture files do not contain sidecar license or acquisition metadata, so their provider terms and exact acquisition details are not fully reproducible from the repository alone.
