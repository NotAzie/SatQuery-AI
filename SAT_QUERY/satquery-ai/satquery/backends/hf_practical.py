"""The practical vision backend: BLIP for language, CLIP for similarity.

Every method here performs a real forward pass. Nothing is stubbed, nothing
returns a canned string. If the model cannot be loaded, the caller gets a
`ResourceNotConfiguredError` explaining what to install or configure.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from ..config import Settings
from ..errors import ToolExecutionError
from ..registry import ModelRegistry, require_torch
from ..schemas import BackendKind
from .base import EmbeddingBackend, GenerativeBackend, chunked, l2_normalise

logger = logging.getLogger("satquery.backends.practical")


def _feature_tensor(output: Any, kind: str) -> Any:
    """Extract projected CLIP features from tensor or structured outputs.

    Transformers 5.x returns ``BaseModelOutputWithPooling`` from
    ``get_image_features`` and ``get_text_features``. Its ``pooler_output``
    is already projected into the shared CLIP space; detaching the wrapper
    itself raises ``AttributeError``.
    """
    if hasattr(output, "detach"):
        return output

    for attribute in (f"{kind}_embeds", "pooler_output"):
        value = getattr(output, attribute, None)
        if value is not None and hasattr(value, "detach"):
            return value

    if isinstance(output, (tuple, list)):
        tensors = [item for item in output if hasattr(item, "detach")]
        for tensor in tensors:
            if getattr(tensor, "ndim", 0) == 2:
                return tensor
        if tensors:
            return tensors[0]

    raise TypeError(
        f"CLIP {kind} features returned unsupported output type {type(output).__name__}."
    )


class ClipEmbedder(EmbeddingBackend):
    """CLIP image/text embeddings, batched and cached per process."""

    kind = BackendKind.PRACTICAL

    def __init__(self, registry: ModelRegistry, settings: Settings) -> None:
        self.registry = registry
        self.settings = settings
        self._text_cache: Dict[str, np.ndarray] = {}

    @property
    def name(self) -> str:
        return f"clip:{self.settings.clip_model}"

    def available(self) -> Tuple[bool, Optional[str]]:
        status = self.registry.status()["practical"]
        return bool(status["available"]), status["reason"]

    # -- Embeddings --------------------------------------------------------

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        if not images:
            return np.zeros((0, 1), dtype=np.float64)

        torch = require_torch()
        loaded = self.registry.clip()
        model, processor = loaded.model, loaded.processor
        device = loaded.device

        outputs: List[np.ndarray] = []
        with torch.no_grad():
            for batch in chunked(list(images), self.settings.inference_batch_size):
                inputs = processor(images=list(batch), return_tensors="pt")
                inputs = {key: value.to(device) for key, value in inputs.items()}
                if "pixel_values" in inputs:
                    inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)
                features = _feature_tensor(model.get_image_features(**inputs), "image")
                outputs.append(features.detach().float().cpu().numpy())

        return l2_normalise(np.concatenate(outputs, axis=0))

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float64)

        # Text embeddings are reused constantly - the same taxonomy on every
        # request - so they are worth memoising for the life of the process.
        missing = [text for text in texts if text not in self._text_cache]
        if missing:
            torch = require_torch()
            loaded = self.registry.clip()
            model, processor = loaded.model, loaded.processor
            device = loaded.device

            computed: List[np.ndarray] = []
            with torch.no_grad():
                for batch in chunked(missing, self.settings.inference_batch_size):
                    inputs = processor(
                        text=list(batch), return_tensors="pt", padding=True, truncation=True
                    )
                    inputs = {key: value.to(device) for key, value in inputs.items()}
                    features = _feature_tensor(model.get_text_features(**inputs), "text")
                    computed.append(features.detach().float().cpu().numpy())

            stacked = l2_normalise(np.concatenate(computed, axis=0))
            for text, vector in zip(missing, stacked):
                self._text_cache[text] = vector

        return np.stack([self._text_cache[text] for text in texts])

    def logit_scale(self) -> float:
        torch = require_torch()
        loaded = self.registry.clip()
        with torch.no_grad():
            return float(loaded.model.logit_scale.detach().float().exp().cpu().item())


class BlipCaptioner(GenerativeBackend):
    """BLIP conditional captioning with prompt ensembling."""

    kind = BackendKind.PRACTICAL

    def __init__(self, registry: ModelRegistry, settings: Settings) -> None:
        self.registry = registry
        self.settings = settings

    @property
    def name(self) -> str:
        return f"blip-caption:{self.settings.caption_model}"

    def available(self) -> Tuple[bool, Optional[str]]:
        status = self.registry.status()["practical"]
        return bool(status["available"]), status["reason"]

    def generate(
        self,
        images: Sequence[Image.Image],
        prompt: str,
        *,
        max_new_tokens: Optional[int] = None,
    ) -> str:
        captions = self.caption_variants(images[0], [prompt] if prompt else [""])
        return captions[0] if captions else ""

    def caption_variants(
        self, image: Image.Image, prompts: Sequence[str]
    ) -> List[str]:
        """Caption the same image under several conditioning prefixes.

        BLIP is highly sensitive to its prefix. Sampling a handful of
        remote-sensing oriented prefixes and keeping the distinct results gives
        a much richer description than any single prompt, and it surfaces
        details that one phrasing alone would miss.
        """
        torch = require_torch()
        loaded = self.registry.captioner()
        model, processor = loaded.model, loaded.processor
        device = loaded.device
        max_tokens = self.settings.caption_max_new_tokens

        results: List[str] = []
        with torch.no_grad():
            for prompt in prompts:
                text = prompt.strip()
                if text:
                    inputs = processor(images=image, text=text, return_tensors="pt")
                else:
                    inputs = processor(images=image, return_tensors="pt")
                inputs = {key: value.to(device) for key, value in inputs.items()}
                if "pixel_values" in inputs:
                    inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)

                try:
                    generated = model.generate(
                        **inputs,
                        max_new_tokens=max_tokens,
                        num_beams=3,
                        length_penalty=1.0,
                        repetition_penalty=1.15,
                    )
                except Exception as exc:
                    raise ToolExecutionError(
                        "caption",
                        f"BLIP caption generation failed: {exc}",
                        remediation=[
                            "On CUDA, out-of-memory is the usual cause; lower "
                            "SATQUERY_BATCH_SIZE or SATQUERY_MAX_IMAGE_PX.",
                            "Set SATQUERY_DEVICE=cpu to rule out a GPU problem.",
                        ],
                    ) from exc

                decoded = processor.batch_decode(generated, skip_special_tokens=True)[0]
                cleaned = _clean_caption(decoded, text)
                if cleaned:
                    results.append(cleaned)

        return _dedupe_preserving_order(results)


class BlipAnswerer(GenerativeBackend):
    """BLIP visual question answering."""

    kind = BackendKind.PRACTICAL

    def __init__(self, registry: ModelRegistry, settings: Settings) -> None:
        self.registry = registry
        self.settings = settings

    @property
    def name(self) -> str:
        return f"blip-vqa:{self.settings.vqa_model}"

    def available(self) -> Tuple[bool, Optional[str]]:
        status = self.registry.status()["practical"]
        return bool(status["available"]), status["reason"]

    def generate(
        self,
        images: Sequence[Image.Image],
        prompt: str,
        *,
        max_new_tokens: Optional[int] = None,
    ) -> str:
        answer, _ = self.answer(images[0], prompt, max_new_tokens=max_new_tokens)
        return answer

    def answer(
        self,
        image: Image.Image,
        question: str,
        *,
        max_new_tokens: Optional[int] = None,
    ) -> Tuple[str, Optional[float]]:
        """Answer one question, returning the text and a sequence score.

        The score is the length-normalised sequence log-probability mapped
        through an exponential, which makes it comparable across answers of
        different lengths. It is a decoding confidence, not a calibrated
        probability, and the tool layer labels it as such.
        """
        torch = require_torch()
        loaded = self.registry.vqa()
        model, processor = loaded.model, loaded.processor
        device = loaded.device
        tokens = max_new_tokens or self.settings.vqa_max_new_tokens

        inputs = processor(images=image, text=question, return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        if "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)

        with torch.no_grad():
            try:
                generated = model.generate(
                    **inputs,
                    max_new_tokens=tokens,
                    num_beams=3,
                    output_scores=True,
                    return_dict_in_generate=True,
                )
            except Exception as exc:
                raise ToolExecutionError(
                    "vqa",
                    f"BLIP VQA generation failed: {exc}",
                    remediation=[
                        "On CUDA, out-of-memory is the usual cause; lower "
                        "SATQUERY_MAX_IMAGE_PX or set SATQUERY_DEVICE=cpu.",
                    ],
                ) from exc

        sequences = getattr(generated, "sequences", generated)
        text = processor.batch_decode(sequences, skip_special_tokens=True)[0].strip()

        score: Optional[float] = None
        sequence_scores = getattr(generated, "sequences_scores", None)
        if sequence_scores is not None and len(sequence_scores) > 0:
            score = float(np.exp(float(sequence_scores[0].detach().float().cpu())))
            score = float(np.clip(score, 0.0, 1.0))

        return text, score


class PracticalVisionFactory:
    """Builds the practical backends against a shared registry."""

    def __init__(self, registry: ModelRegistry, settings: Settings) -> None:
        self.registry = registry
        self.settings = settings
        self._embedder: Optional[ClipEmbedder] = None
        self._captioner: Optional[BlipCaptioner] = None
        self._answerer: Optional[BlipAnswerer] = None

    def embedder(self) -> ClipEmbedder:
        if self._embedder is None:
            self._embedder = ClipEmbedder(self.registry, self.settings)
        return self._embedder

    def captioner(self) -> BlipCaptioner:
        if self._captioner is None:
            self._captioner = BlipCaptioner(self.registry, self.settings)
        return self._captioner

    def answerer(self) -> BlipAnswerer:
        if self._answerer is None:
            self._answerer = BlipAnswerer(self.registry, self.settings)
        return self._answerer


# ---------------------------------------------------------------------------
# Text post-processing
# ---------------------------------------------------------------------------

_PREFIX_NOISE = re.compile(
    r"^(arafed|araffe|araffes|there is|there are|this is|a picture of|an image of)\s+",
    re.IGNORECASE,
)


def _clean_caption(decoded: str, prompt: str) -> str:
    """Strip the conditioning prefix and BLIP's habitual filler openers."""
    text = decoded.strip()
    if prompt:
        lowered = text.lower()
        prompt_lower = prompt.strip().lower()
        if lowered.startswith(prompt_lower):
            text = text[len(prompt) :].strip()

    previous = None
    while previous != text:
        previous = text
        text = _PREFIX_NOISE.sub("", text).strip()

    text = re.sub(r"\s+", " ", text).strip(" .,")
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _dedupe_preserving_order(items: Sequence[str]) -> List[str]:
    """Drop duplicates and near-duplicates, keeping first appearance."""
    seen: List[str] = []
    seen_keys: set[str] = set()
    for item in items:
        key = re.sub(r"[^a-z0-9 ]", "", item.lower()).strip()
        if not key or key in seen_keys:
            continue
        # Treat one caption as redundant when it is wholly contained in another
        # already kept; BLIP prefix variants often differ only by a suffix.
        if any(key in existing or existing in key for existing in seen_keys):
            continue
        seen_keys.add(key)
        seen.append(item)
    return seen
