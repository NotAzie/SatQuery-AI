from __future__ import annotations

import torch
from PIL import Image
from transformers.modeling_outputs import BaseModelOutputWithPooling

from satquery.backends.hf_practical import ClipEmbedder
from satquery.registry import LoadedModel


class StructuredClipModel:
    dtype = torch.float32
    logit_scale = torch.tensor(1.0)

    def get_image_features(self, **inputs):
        batch = inputs["pixel_values"].shape[0]
        return BaseModelOutputWithPooling(
            last_hidden_state=torch.zeros(batch, 2, 4),
            pooler_output=torch.ones(batch, 4),
        )

    def get_text_features(self, **inputs):
        batch = inputs["input_ids"].shape[0]
        return BaseModelOutputWithPooling(
            last_hidden_state=torch.zeros(batch, 2, 4),
            pooler_output=torch.ones(batch, 4),
        )


class StructuredProcessor:
    def __call__(self, *, images=None, text=None, **kwargs):
        batch = len(images) if images is not None else len(text)
        key = "pixel_values" if images is not None else "input_ids"
        return {key: torch.ones(batch, 4)}


class StubRegistry:
    def __init__(self):
        self.loaded = LoadedModel(
            key="clip",
            model=StructuredClipModel(),
            processor=StructuredProcessor(),
            model_id="test-clip",
            device="cpu",
            dtype="float32",
            load_seconds=0.0,
        )

    def clip(self):
        return self.loaded


def test_clip_embedder_extracts_structured_pooler_outputs(settings):
    embedder = ClipEmbedder(StubRegistry(), settings)
    image_embeddings = embedder.embed_images([Image.new("RGB", (8, 8))])
    text_embeddings = embedder.embed_texts(["a building"])

    assert image_embeddings.shape == (1, 4)
    assert text_embeddings.shape == (1, 4)
    assert torch.isfinite(torch.tensor(image_embeddings)).all()
    assert torch.isfinite(torch.tensor(text_embeddings)).all()