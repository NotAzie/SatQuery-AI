"""Backend interfaces shared by the practical and strong vision paths.

SatQuery has two vision backends:

* `PracticalVision` - BLIP for captioning and VQA, CLIP for scene
  classification, grounding, and presence checks. Always the fallback, always
  fully implemented.
* `RSVLMVision` - an optional remote-sensing VLM that answers in free text and
  generally beats the practical path on domain vocabulary.

Tools ask a `VisionSuite` for what they need. The suite prefers the strong
backend where it is configured and helpful, and drops to the practical path
otherwise, so no tool has to carry that branching itself.
"""

from __future__ import annotations

import abc
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from ..errors import ResourceNotConfiguredError
from ..schemas import BackendKind


def l2_normalise(matrix: np.ndarray, axis: int = -1) -> np.ndarray:
    """Unit-normalise rows so dot products become cosine similarities."""
    norms = np.linalg.norm(matrix, axis=axis, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def softmax(scores: np.ndarray, axis: int = -1, temperature: float = 1.0) -> np.ndarray:
    scaled = np.asarray(scores, dtype=np.float64) / max(temperature, 1e-6)
    shifted = scaled - scaled.max(axis=axis, keepdims=True)
    exponentiated = np.exp(shifted)
    return exponentiated / np.maximum(exponentiated.sum(axis=axis, keepdims=True), 1e-12)


def chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    size = max(int(size), 1)
    for start in range(0, len(items), size):
        yield items[start : start + size]


#: Prompt templates averaged together for CLIP text embeddings. Ensembling
#: across phrasings is the single cheapest accuracy win available to zero-shot
#: CLIP classification, and it matters more here than on natural images because
#: overhead imagery is far from CLIP's training distribution.
OPTICAL_TEMPLATES: Tuple[str, ...] = (
    "a satellite image of {}",
    "an aerial photograph of {}",
    "a top-down overhead view of {}",
    "a remote sensing image showing {}",
    "a high resolution aerial view of {}",
    "satellite imagery of {} seen from above",
)

SAR_TEMPLATES: Tuple[str, ...] = (
    "a synthetic aperture radar image of {}",
    "a grayscale SAR amplitude image of {}",
    "a radar backscatter image showing {}",
    "an overhead radar image of {}",
)


def templates_for(modality: str) -> Tuple[str, ...]:
    return SAR_TEMPLATES if str(modality).upper() == "SAR" else OPTICAL_TEMPLATES


class VisionBackend(abc.ABC):
    """Common surface for anything that can look at an image."""

    kind: BackendKind = BackendKind.NONE

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable identifier used in the execution trace."""

    @abc.abstractmethod
    def available(self) -> Tuple[bool, Optional[str]]:
        """Whether this backend can run, and why not if it cannot."""


class EmbeddingBackend(VisionBackend):
    """A backend that can embed images and text into a shared space."""

    @abc.abstractmethod
    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Return L2-normalised image embeddings, shape (N, D)."""

    @abc.abstractmethod
    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Return L2-normalised text embeddings, shape (N, D)."""

    @abc.abstractmethod
    def logit_scale(self) -> float:
        """The model's learned temperature, used to calibrate probabilities."""

    def similarity(self, images: Sequence[Image.Image], texts: Sequence[str]) -> np.ndarray:
        """Cosine similarity matrix, shape (len(images), len(texts))."""
        image_embeds = self.embed_images(images)
        text_embeds = self.embed_texts(texts)
        return image_embeds @ text_embeds.T

    def embed_prompt_ensemble(
        self, labels: Sequence[str], templates: Sequence[str]
    ) -> np.ndarray:
        """Average each label's embedding across several phrasings.

        The mean of unit vectors is not itself a unit vector, so the result is
        re-normalised; skipping that step quietly biases classification towards
        labels whose template embeddings happen to disagree least.
        """
        flattened: List[str] = []
        for label in labels:
            flattened.extend(template.format(label) for template in templates)

        embeddings = self.embed_texts(flattened)
        span = len(templates)
        averaged = np.stack(
            [embeddings[index * span : (index + 1) * span].mean(axis=0) for index in range(len(labels))]
        )
        return l2_normalise(averaged)


class GenerativeBackend(VisionBackend):
    """A backend that can produce free text conditioned on imagery."""

    @abc.abstractmethod
    def generate(
        self,
        images: Sequence[Image.Image],
        prompt: str,
        *,
        max_new_tokens: Optional[int] = None,
    ) -> str:
        """Answer a prompt about the supplied images."""


class VisionSuite:
    """The bundle of capabilities the tool layer works against."""

    def __init__(
        self,
        embedder: Optional[EmbeddingBackend],
        captioner: Optional[GenerativeBackend],
        answerer: Optional[GenerativeBackend],
        strong: Optional[GenerativeBackend],
    ) -> None:
        self._embedder = embedder
        self._captioner = captioner
        self._answerer = answerer
        self._strong = strong

    # -- Accessors that raise informative errors ---------------------------

    @property
    def embedder(self) -> EmbeddingBackend:
        if self._embedder is None:
            raise ResourceNotConfiguredError(
                "No embedding backend is available, so scene classification, grounding, "
                "and presence checks cannot run.",
                remediation=[
                    "Install the practical stack: pip install torch transformers",
                    "Then set SATQUERY_CLIP_MODEL (default openai/clip-vit-large-patch14).",
                ],
            )
        return self._embedder

    @property
    def captioner(self) -> GenerativeBackend:
        if self._strong is not None:
            return self._strong
        if self._captioner is None:
            raise ResourceNotConfiguredError(
                "No captioning backend is available.",
                remediation=[
                    "Install the practical stack: pip install torch transformers",
                    "Or configure a remote-sensing VLM via SATQUERY_RSVLM_PATH.",
                ],
            )
        return self._captioner

    @property
    def answerer(self) -> GenerativeBackend:
        if self._strong is not None:
            return self._strong
        if self._answerer is None:
            raise ResourceNotConfiguredError(
                "No visual question answering backend is available.",
                remediation=[
                    "Install the practical stack: pip install torch transformers",
                    "Or configure a remote-sensing VLM via SATQUERY_RSVLM_PATH.",
                ],
            )
        return self._answerer

    @property
    def strong(self) -> Optional[GenerativeBackend]:
        return self._strong

    @property
    def practical_captioner(self) -> Optional[GenerativeBackend]:
        return self._captioner

    @property
    def practical_answerer(self) -> Optional[GenerativeBackend]:
        return self._answerer

    # -- Introspection -----------------------------------------------------

    @property
    def has_embedder(self) -> bool:
        return self._embedder is not None

    @property
    def has_strong(self) -> bool:
        return self._strong is not None

    @property
    def active_kind(self) -> BackendKind:
        if self._strong is not None and self._embedder is not None:
            return BackendKind.MIXED
        if self._strong is not None:
            return BackendKind.RSVLM
        if self._embedder is not None or self._captioner is not None:
            return BackendKind.PRACTICAL
        return BackendKind.NONE

    def describe(self) -> Dict[str, Any]:
        return {
            "embedder": self._embedder.name if self._embedder else None,
            "captioner": self._captioner.name if self._captioner else None,
            "answerer": self._answerer.name if self._answerer else None,
            "strong": self._strong.name if self._strong else None,
            "active": self.active_kind.value,
        }
