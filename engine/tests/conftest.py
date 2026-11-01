"""Shared test fixtures.

The backend double here is not a stub that returns canned strings. It computes
its embeddings from real pixel statistics, so the grounding, scene, change, and
counting pipelines are exercised end to end against actual image content: a
blue patch in the top-left really does have to come back as a water region in
the top-left. Only the learned weights are replaced; every algorithm under test
is the production one.
"""

from __future__ import annotations

import io
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pytest
from PIL import Image

from satquery.backends.base import EmbeddingBackend, GenerativeBackend, VisionSuite, l2_normalise
from satquery.config import Settings
from satquery.schemas import BackendKind

# ---------------------------------------------------------------------------
# Synthetic imagery
# ---------------------------------------------------------------------------

WATER = (36, 78, 132)
VEGETATION = (58, 122, 54)
URBAN = (150, 148, 142)
SOIL = (166, 132, 86)


def make_scene(
    width: int = 384,
    height: int = 384,
    *,
    water_box: Optional[Tuple[int, int, int, int]] = None,
    vegetation_box: Optional[Tuple[int, int, int, int]] = None,
    urban_box: Optional[Tuple[int, int, int, int]] = None,
    base: Tuple[int, int, int] = SOIL,
    seed: int = 7,
) -> Image.Image:
    """Build an RGB scene with known content in known places."""
    rng = np.random.default_rng(seed)
    canvas = np.zeros((height, width, 3), dtype=np.float64)
    canvas[:, :] = base

    for box, colour in (
        (water_box, WATER),
        (vegetation_box, VEGETATION),
        (urban_box, URBAN),
    ):
        if box is None:
            continue
        x0, y0, x1, y1 = box
        canvas[y0:y1, x0:x1] = colour

    canvas += rng.normal(0.0, 5.0, canvas.shape)
    return Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), mode="RGB")


def make_sar_scene(width: int = 320, height: int = 320, seed: int = 11) -> Image.Image:
    """A grayscale field with multiplicative speckle, as radar amplitude looks."""
    rng = np.random.default_rng(seed)
    base = np.full((height, width), 70.0)
    base[height // 3 : 2 * height // 3, :] = 130.0
    speckle = rng.gamma(shape=1.4, scale=1.0 / 1.4, size=(height, width))
    amplitude = np.clip(base * speckle, 0, 255).astype(np.uint8)
    return Image.fromarray(amplitude, mode="L").convert("RGB")


def to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Pixel-derived backend double
# ---------------------------------------------------------------------------

FEATURE_DIM = 6

#: Keyword -> prototype feature vector in the same space the image encoder
#: produces: [red, green, blue, brightness, edge density, saturation].
TEXT_PROTOTYPES: Dict[str, Sequence[float]] = {
    "water": (0.10, 0.25, 0.95, 0.35, 0.10, 0.70),
    "river": (0.10, 0.25, 0.95, 0.35, 0.15, 0.70),
    "lake": (0.10, 0.25, 0.95, 0.30, 0.10, 0.70),
    "sea": (0.10, 0.25, 0.95, 0.35, 0.10, 0.70),
    "ocean": (0.10, 0.25, 0.95, 0.35, 0.10, 0.70),
    "flood": (0.15, 0.30, 0.90, 0.35, 0.20, 0.60),
    "vegetation": (0.22, 0.95, 0.20, 0.45, 0.20, 0.70),
    "tree": (0.22, 0.95, 0.20, 0.40, 0.30, 0.70),
    "forest": (0.20, 0.95, 0.18, 0.38, 0.25, 0.72),
    "grass": (0.30, 0.90, 0.25, 0.50, 0.15, 0.60),
    "crop": (0.35, 0.88, 0.25, 0.52, 0.25, 0.55),
    "farmland": (0.40, 0.85, 0.28, 0.55, 0.30, 0.50),
    "field": (0.40, 0.85, 0.28, 0.55, 0.28, 0.50),
    "agricultural": (0.40, 0.85, 0.28, 0.55, 0.30, 0.50),
    "building": (0.72, 0.72, 0.70, 0.75, 0.75, 0.10),
    "rooftop": (0.74, 0.73, 0.71, 0.78, 0.78, 0.10),
    "urban": (0.70, 0.70, 0.68, 0.72, 0.70, 0.12),
    "residential": (0.70, 0.70, 0.68, 0.72, 0.68, 0.12),
    "industrial": (0.68, 0.68, 0.66, 0.70, 0.72, 0.12),
    "road": (0.55, 0.55, 0.55, 0.55, 0.65, 0.08),
    "parking": (0.60, 0.60, 0.60, 0.62, 0.70, 0.10),
    "soil": (0.85, 0.66, 0.42, 0.68, 0.20, 0.45),
    "bare": (0.85, 0.66, 0.42, 0.68, 0.18, 0.45),
    "barren": (0.85, 0.66, 0.42, 0.68, 0.18, 0.45),
    "desert": (0.90, 0.72, 0.45, 0.75, 0.12, 0.45),
    "sand": (0.90, 0.75, 0.50, 0.78, 0.12, 0.42),
    "beach": (0.88, 0.76, 0.55, 0.78, 0.15, 0.38),
    "ship": (0.66, 0.66, 0.78, 0.60, 0.80, 0.25),
    "vessel": (0.66, 0.66, 0.78, 0.60, 0.80, 0.25),
    "boat": (0.66, 0.66, 0.78, 0.60, 0.78, 0.25),
    "aircraft": (0.78, 0.78, 0.78, 0.82, 0.85, 0.08),
    "empty": (0.50, 0.50, 0.50, 0.50, 0.05, 0.05),
    "textureless": (0.50, 0.50, 0.50, 0.50, 0.02, 0.03),
    "uniform": (0.50, 0.50, 0.50, 0.50, 0.02, 0.03),
    "cloud": (0.95, 0.95, 0.95, 0.96, 0.10, 0.03),
    "radar": (0.50, 0.50, 0.50, 0.45, 0.85, 0.02),
    "sar": (0.50, 0.50, 0.50, 0.45, 0.85, 0.02),
    "speckle": (0.50, 0.50, 0.50, 0.45, 0.90, 0.02),
    "grayscale": (0.50, 0.50, 0.50, 0.50, 0.50, 0.02),
    "colour": (0.60, 0.55, 0.45, 0.60, 0.35, 0.55),
    "color": (0.60, 0.55, 0.45, 0.60, 0.35, 0.55),
    "optical": (0.60, 0.55, 0.45, 0.60, 0.35, 0.55),
}

NEUTRAL = np.array([0.5, 0.5, 0.5, 0.5, 0.3, 0.2], dtype=np.float64)


def _image_features(image: Image.Image) -> np.ndarray:
    """Pixel statistics in the shared feature space."""
    array = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    if array.size == 0:
        return NEUTRAL.copy()

    means = array.reshape(-1, 3).mean(axis=0)
    brightness = float(array.mean())
    maximum = array.max(axis=2)
    minimum = array.min(axis=2)
    saturation = float(np.mean((maximum - minimum) / np.maximum(maximum, 1e-6)))

    gray = array.mean(axis=2)
    if gray.shape[1] > 1:
        edges = float((np.abs(np.diff(gray, axis=1)) > 0.06).mean())
    else:
        edges = 0.0

    # Rescale the channel means so that a channel which merely dominates
    # slightly separates strongly, matching how the text prototypes are written.
    total = float(means.sum()) or 1.0
    ratios = means / total
    emphasised = np.clip((ratios - 1.0 / 3.0) * 3.0 + 0.5, 0.0, 1.0)

    return np.array(
        [emphasised[0], emphasised[1], emphasised[2], brightness, edges, saturation],
        dtype=np.float64,
    )


def _text_features(text: str) -> np.ndarray:
    words = [word.strip(".,") for word in text.lower().split()]
    matched = [np.array(TEXT_PROTOTYPES[word], dtype=np.float64)
               for word in words if word in TEXT_PROTOTYPES]
    if not matched:
        for key, vector in TEXT_PROTOTYPES.items():
            if key in text.lower():
                matched.append(np.array(vector, dtype=np.float64))
    if not matched:
        return NEUTRAL.copy()
    return np.mean(matched, axis=0)


class FakeEmbedder(EmbeddingBackend):
    """CLIP stand-in whose similarity is a real function of the pixels."""

    kind = BackendKind.PRACTICAL

    def __init__(self) -> None:
        self.image_calls = 0
        self.text_calls = 0

    @property
    def name(self) -> str:
        return "test-embedder:pixel-features"

    def available(self):
        return True, None

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        self.image_calls += len(images)
        if not images:
            return np.zeros((0, FEATURE_DIM))
        return l2_normalise(np.stack([_image_features(image) for image in images]))

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        self.text_calls += len(texts)
        if not texts:
            return np.zeros((0, FEATURE_DIM))
        return l2_normalise(np.stack([_text_features(text) for text in texts]))

    def logit_scale(self) -> float:
        return 28.0


class FakeCaptioner(GenerativeBackend):
    """Caption generator whose words follow the dominant pixel content."""

    kind = BackendKind.PRACTICAL

    def __init__(self) -> None:
        self.calls: List[str] = []

    @property
    def name(self) -> str:
        return "test-captioner:pixel-features"

    def available(self):
        return True, None

    def generate(self, images, prompt, *, max_new_tokens=None) -> str:
        return self.caption_variants(images[0], [prompt])[0]

    def caption_variants(self, image: Image.Image, prompts: Sequence[str]) -> List[str]:
        features = _image_features(image)
        descriptors: List[str] = []
        if features[2] > 0.6:
            descriptors.append("a body of water")
        if features[1] > 0.6:
            descriptors.append("vegetated ground")
        if features[4] > 0.4:
            descriptors.append("built structures")
        if not descriptors:
            descriptors.append("open bare terrain")

        results: List[str] = []
        for index, prompt in enumerate(prompts):
            self.calls.append(prompt)
            subject = descriptors[index % len(descriptors)]
            results.append(f"An overhead view of {subject}")
        # Deduplicate the way the production captioner does.
        seen: List[str] = []
        for item in results:
            if item not in seen:
                seen.append(item)
        return seen


class FakeAnswerer(GenerativeBackend):
    """VQA stand-in that answers presence questions from the pixels."""

    kind = BackendKind.PRACTICAL

    def __init__(self, forced: Optional[str] = None) -> None:
        self.forced = forced
        self.questions: List[str] = []

    @property
    def name(self) -> str:
        return "test-answerer:pixel-features"

    def available(self):
        return True, None

    def generate(self, images, prompt, *, max_new_tokens=None) -> str:
        return self.answer(images[0], prompt)[0]

    def answer(self, image: Image.Image, question: str, *, max_new_tokens=None):
        self.questions.append(question)
        if self.forced is not None:
            return self.forced, 0.8

        features = _image_features(image)
        lowered = question.lower()
        if "how many" in lowered:
            return "three", 0.6
        if lowered.startswith(("is", "are", "does", "do", "can", "any")):
            subject = _text_features(question)
            similarity = float(
                np.dot(features / np.linalg.norm(features), subject / np.linalg.norm(subject))
            )
            return ("yes" if similarity > 0.93 else "no"), round(similarity, 3)
        if features[2] > 0.6:
            return "water", 0.7
        if features[1] > 0.6:
            return "vegetation", 0.7
        return "bare ground", 0.5


class FakeStrong(GenerativeBackend):
    """Stand-in for a configured remote-sensing VLM."""

    kind = BackendKind.RSVLM

    def __init__(self, text: str = "A riverine floodplain with cultivated parcels along the bank.") -> None:
        self.text = text
        self.prompts: List[str] = []

    @property
    def name(self) -> str:
        return "test-rsvlm:stub"

    def available(self):
        return True, None

    def generate(self, images, prompt, *, max_new_tokens=None) -> str:
        self.prompts.append(prompt)
        return self.text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        max_image_pixels=384,
        grounding_scales=(0.5, 0.33, 0.25),
        grounding_max_windows=120,
        grounding_max_regions=12,
        cache_size=32,
        change_patch_grid=8,
        router_mode="rules",
        image_root=str(tmp_path),
    )


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def vision(embedder) -> VisionSuite:
    return VisionSuite(
        embedder=embedder,
        captioner=FakeCaptioner(),
        answerer=FakeAnswerer(),
        strong=None,
    )


@pytest.fixture
def strong_vision(embedder) -> VisionSuite:
    return VisionSuite(
        embedder=embedder,
        captioner=FakeCaptioner(),
        answerer=FakeAnswerer(),
        strong=FakeStrong(),
    )


@pytest.fixture
def water_corner_scene() -> Image.Image:
    """Bare terrain with a water body in the top-left quadrant."""
    return make_scene(water_box=(0, 0, 150, 150))


@pytest.fixture
def mixed_scene() -> Image.Image:
    """Water top-left, vegetation bottom-right, built area top-right."""
    return make_scene(
        water_box=(0, 0, 150, 150),
        vegetation_box=(200, 220, 384, 384),
        urban_box=(230, 0, 384, 140),
    )
