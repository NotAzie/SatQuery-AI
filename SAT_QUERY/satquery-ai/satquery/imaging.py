"""Image ingestion and pixel-level analysis for SatQuery AI.

This module is deliberately model-free. Everything here operates on real
pixels with NumPy and Pillow, which means it is fully testable on a laptop
with no GPU, and it gives the tool layer a dependable substrate: window
extraction for grounding, response-map thresholding, connected components,
image alignment for change detection, and the optical/SAR heuristics.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageFile, UnidentifiedImageError

from .config import Settings
from .errors import ImageError, ImageNotFoundError
from .schemas import BoundingBox, ImageRef, Modality, Region

# Satellite scenes are frequently large and occasionally truncated in transit.
# Allow Pillow to finish decoding a partial file rather than raising, and lift
# the decompression-bomb guard to something appropriate for aerial imagery
# while still bounded.
ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 512_000_000

SUPPORTED_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif", ".ppm", ".pgm",
}


# ---------------------------------------------------------------------------
# Loaded image container
# ---------------------------------------------------------------------------


@dataclass
class LoadedImage:
    """A validated, normalised RGB image ready for model consumption."""

    image_id: str
    filename: str
    source: str
    pil: Image.Image
    array: np.ndarray  # uint8, (H, W, 3)
    sha256: str
    size_bytes: int
    original_size: Tuple[int, int]
    original_mode: str
    modality: Modality = Modality.UNKNOWN
    modality_confidence: float = 0.0
    modality_evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.array.shape[1])

    @property
    def height(self) -> int:
        return int(self.array.shape[0])

    @property
    def was_resized(self) -> bool:
        return (self.width, self.height) != self.original_size

    def to_ref(self) -> ImageRef:
        return ImageRef(
            image_id=self.image_id,
            filename=self.filename,
            source=self.source,
            width=self.width,
            height=self.height,
            mode=self.original_mode,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
            modality=self.modality,
            modality_confidence=round(self.modality_confidence, 4),
            resized_from=self.original_size if self.was_resized else None,
        )

    def crop_norm(self, box: Tuple[float, float, float, float]) -> Image.Image:
        x0, y0, x1, y1 = box
        left = int(round(x0 * self.width))
        top = int(round(y0 * self.height))
        right = int(round(x1 * self.width))
        bottom = int(round(y1 * self.height))
        left = max(0, min(left, self.width - 1))
        top = max(0, min(top, self.height - 1))
        right = max(left + 1, min(right, self.width))
        bottom = max(top + 1, min(bottom, self.height))
        return self.pil.crop((left, top, right, bottom))


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def _to_rgb(image: Image.Image) -> Image.Image:
    """Normalise any input mode to 8-bit RGB.

    Single-band products (a SAR amplitude GeoTIFF, a panchromatic scene) and
    high bit-depth rasters both arrive here. Rather than let Pillow clip a
    16-bit band to 255, rescale by the observed 2nd-98th percentile range,
    which is the same contrast stretch an analyst would apply before looking
    at the scene.
    """
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA", "P"}:
        background = Image.new("RGB", image.size, (0, 0, 0))
        converted = image.convert("RGBA")
        background.paste(converted, mask=converted.split()[-1])
        return background
    if image.mode in {"I", "I;16", "I;16B", "I;16L", "F"}:
        raw = np.asarray(image).astype(np.float64)
        finite = raw[np.isfinite(raw)]
        if finite.size == 0:
            stretched = np.zeros(raw.shape, dtype=np.uint8)
        else:
            low = float(np.percentile(finite, 2.0))
            high = float(np.percentile(finite, 98.0))
            if high - low < 1e-9:
                high = float(finite.max())
                low = float(finite.min())
            if high - low < 1e-9:
                stretched = np.zeros(raw.shape, dtype=np.uint8)
            else:
                scaled = (raw - low) / (high - low)
                stretched = np.clip(scaled * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(stretched, mode="L").convert("RGB")
    return image.convert("RGB")


def _fit_within(image: Image.Image, max_edge: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_edge:
        return image
    ratio = max_edge / float(longest)
    new_size = (max(1, int(round(width * ratio))), max(1, int(round(height * ratio))))
    return image.resize(new_size, Image.LANCZOS)


def load_image_from_bytes(
    payload: bytes,
    filename: str,
    settings: Settings,
    *,
    source: str = "upload",
) -> LoadedImage:
    """Decode, validate, and normalise an uploaded image."""
    if not payload:
        raise ImageError(
            f"'{filename}' arrived empty.",
            remediation=["Re-upload the file; zero bytes reached the server."],
            context={"filename": filename},
        )

    limit_bytes = int(settings.max_upload_mb * 1024 * 1024)
    if len(payload) > limit_bytes:
        raise ImageError(
            f"'{filename}' is {len(payload) / 1048576:.1f} MB, above the "
            f"{settings.max_upload_mb:g} MB limit.",
            remediation=[
                "Downsample or tile the scene before upload.",
                "Or raise SATQUERY_MAX_UPLOAD_MB if the machine can take it.",
            ],
            context={"filename": filename, "size_bytes": len(payload)},
        )

    try:
        opened = Image.open(io.BytesIO(payload))
        opened.load()
    except UnidentifiedImageError as exc:
        raise ImageError(
            f"'{filename}' is not an image format Pillow can decode.",
            remediation=[
                "Supported inputs: " + ", ".join(sorted(SUPPORTED_SUFFIXES)),
                "Convert GeoTIFF variants with rasterio or gdal_translate first.",
            ],
            context={"filename": filename},
        ) from exc
    except Exception as exc:  # corrupt payloads, decoder faults
        raise ImageError(
            f"'{filename}' could not be decoded: {exc}",
            remediation=["Verify the file opens locally, then re-upload."],
            context={"filename": filename},
        ) from exc

    original_size = opened.size
    original_mode = opened.mode
    rgb = _to_rgb(opened)
    rgb = _fit_within(rgb, settings.max_image_pixels)
    array = np.asarray(rgb, dtype=np.uint8)

    if array.ndim != 3 or array.shape[2] != 3:
        raise ImageError(
            f"'{filename}' did not normalise to a 3-channel RGB array.",
            remediation=["Convert the raster to RGB or single-band grayscale and retry."],
            context={"filename": filename, "shape": list(array.shape)},
        )
    if min(array.shape[0], array.shape[1]) < 32:
        raise ImageError(
            f"'{filename}' is {array.shape[1]}x{array.shape[0]} px, too small to analyse.",
            remediation=["Supply an image at least 32 px on its shorter edge."],
            context={"filename": filename},
        )

    return LoadedImage(
        image_id=f"img-{uuid.uuid4().hex[:12]}",
        filename=filename,
        source=source,
        pil=rgb,
        array=array,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        original_size=original_size,
        original_mode=original_mode,
    )


def load_image_from_path(path: str, settings: Settings) -> LoadedImage:
    """Load an image from disk, honouring the configured sandbox root."""
    if not settings.allow_image_paths:
        raise ImageError(
            "Path-based image access is disabled on this deployment.",
            remediation=[
                "Upload the file through the API instead.",
                "Or set SATQUERY_ALLOW_IMAGE_PATHS=true to re-enable local paths.",
            ],
            context={"path": path},
        )

    candidate = Path(path).expanduser()
    if settings.image_root and not candidate.is_absolute():
        candidate = Path(settings.image_root) / candidate

    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ImageError(
            f"Could not resolve image path {path!r}: {exc}",
            context={"path": path},
        ) from exc

    if settings.image_root:
        root = Path(settings.image_root).resolve()
        if root != resolved and root not in resolved.parents:
            raise ImageError(
                f"{path!r} resolves outside SATQUERY_IMAGE_ROOT.",
                remediation=[
                    f"Place the image under {settings.image_root} and reference it relatively.",
                ],
                context={"path": path, "image_root": settings.image_root},
            )

    if not resolved.exists():
        raise ImageNotFoundError(
            f"No file at {resolved}.",
            remediation=[
                "Check the path spelling and that the file is visible to the server process.",
                "Paths are resolved relative to SATQUERY_IMAGE_ROOT when it is set.",
            ],
            context={"path": str(resolved)},
        )
    if not resolved.is_file():
        raise ImageError(
            f"{resolved} exists but is not a regular file.",
            context={"path": str(resolved)},
        )
    if not os.access(resolved, os.R_OK):
        raise ImageError(
            f"{resolved} is not readable by the server process.",
            remediation=["Fix the file permissions, then retry."],
            context={"path": str(resolved)},
        )

    suffix = resolved.suffix.lower()
    if suffix and suffix not in SUPPORTED_SUFFIXES:
        raise ImageError(
            f"{resolved.name} has an unsupported extension {suffix!r}.",
            remediation=["Supported: " + ", ".join(sorted(SUPPORTED_SUFFIXES))],
            context={"path": str(resolved)},
        )

    payload = resolved.read_bytes()
    return load_image_from_bytes(payload, resolved.name, settings, source=str(resolved))


# ---------------------------------------------------------------------------
# Pixel utilities
# ---------------------------------------------------------------------------


def to_gray(array: np.ndarray) -> np.ndarray:
    """ITU-R BT.601 luma, returned as float64 in [0, 255]."""
    rgb = array.astype(np.float64)
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def box_blur(field_2d: np.ndarray, radius: int) -> np.ndarray:
    """Exact O(n) moving average via prefix sums, applied on both axes."""
    if radius < 1:
        return field_2d.astype(np.float64)
    result = field_2d.astype(np.float64)
    kernel = 2 * radius + 1
    for axis in (0, 1):
        pad_width = [(0, 0), (0, 0)]
        pad_width[axis] = (radius, radius)
        padded = np.pad(result, pad_width, mode="reflect")
        cumulative = np.cumsum(padded, axis=axis)
        lead_shape = list(cumulative.shape)
        lead_shape[axis] = 1
        cumulative = np.concatenate([np.zeros(lead_shape), cumulative], axis=axis)
        length = cumulative.shape[axis]
        upper = np.take(cumulative, np.arange(kernel, length), axis=axis)
        lower = np.take(cumulative, np.arange(0, length - kernel), axis=axis)
        result = (upper - lower) / float(kernel)
    return result


def otsu_threshold(values: np.ndarray, bins: int = 256) -> float:
    """Otsu's method: the cut that maximises between-class variance."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    low = float(finite.min())
    high = float(finite.max())
    if high - low < 1e-12:
        return high

    histogram, edges = np.histogram(finite, bins=bins, range=(low, high))
    histogram = histogram.astype(np.float64)
    total = histogram.sum()
    if total <= 0:
        return high

    centres = (edges[:-1] + edges[1:]) / 2.0
    weight_bg = np.cumsum(histogram) / total
    weight_fg = 1.0 - weight_bg
    cumulative_mean = np.cumsum(histogram * centres) / total
    grand_mean = cumulative_mean[-1]

    with np.errstate(divide="ignore", invalid="ignore"):
        mean_bg = np.where(weight_bg > 0, cumulative_mean / weight_bg, 0.0)
        mean_fg = np.where(weight_fg > 0, (grand_mean - cumulative_mean) / weight_fg, 0.0)

    between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    between = np.nan_to_num(between, nan=0.0, posinf=0.0, neginf=0.0)
    return float(centres[int(np.argmax(between))])


def connected_components(mask: np.ndarray) -> List[np.ndarray]:
    """4-connected components of a boolean mask, as index arrays.

    Written directly against NumPy rather than pulled from scipy.ndimage so the
    dependency surface stays small; masks here are coarse response maps, not
    full-resolution rasters, so an explicit flood fill is cheap.
    """
    if mask.ndim != 2:
        raise ValueError("connected_components expects a 2-D boolean mask")
    if not mask.any():
        return []

    visited = np.zeros(mask.shape, dtype=bool)
    rows, cols = mask.shape
    components: List[np.ndarray] = []
    row_idx, col_idx = np.nonzero(mask)

    for start_r, start_c in zip(row_idx, col_idx):
        if visited[start_r, start_c]:
            continue
        stack = [(int(start_r), int(start_c))]
        visited[start_r, start_c] = True
        members: List[Tuple[int, int]] = []
        while stack:
            r, c = stack.pop()
            members.append((r, c))
            if r > 0 and mask[r - 1, c] and not visited[r - 1, c]:
                visited[r - 1, c] = True
                stack.append((r - 1, c))
            if r + 1 < rows and mask[r + 1, c] and not visited[r + 1, c]:
                visited[r + 1, c] = True
                stack.append((r + 1, c))
            if c > 0 and mask[r, c - 1] and not visited[r, c - 1]:
                visited[r, c - 1] = True
                stack.append((r, c - 1))
            if c + 1 < cols and mask[r, c + 1] and not visited[r, c + 1]:
                visited[r, c + 1] = True
                stack.append((r, c + 1))
        components.append(np.array(members, dtype=np.int32))
    return components


PLACEMENT_ROWS = ("top", "middle", "bottom")
PLACEMENT_COLS = ("left", "centre", "right")


def describe_placement(cx: float, cy: float) -> str:
    """Turn a normalised centroid into plain spatial language."""
    col = PLACEMENT_COLS[min(2, max(0, int(cx * 3)))]
    row = PLACEMENT_ROWS[min(2, max(0, int(cy * 3)))]
    if row == "middle" and col == "centre":
        return "centre of the scene"
    if row == "middle":
        return f"{col} of the scene"
    if col == "centre":
        return f"{row} of the scene"
    return f"{row}-{col} of the scene"


def regions_from_score_map(
    score_map: np.ndarray,
    *,
    label: str,
    width: int,
    height: int,
    threshold: float,
    min_area_fraction: float,
    max_regions: int,
    prefix: str = "reg",
) -> List[Region]:
    """Convert a coarse response map into ranked, boxed regions.

    The score map is in grid space (much coarser than the image). Each
    component becomes a box by taking its grid extent and projecting it back
    to normalised image coordinates, with a half-cell margin so the box covers
    the full footprint of the contributing cells rather than their centres.
    """
    if score_map.ndim != 2:
        raise ValueError("score_map must be 2-D")

    grid_h, grid_w = score_map.shape
    mask = score_map >= threshold
    components = connected_components(mask)
    if not components:
        return []

    candidates: List[Tuple[float, Region]] = []
    for index, members in enumerate(components):
        rows = members[:, 0]
        cols = members[:, 1]
        area_fraction = float(members.shape[0]) / float(grid_h * grid_w)
        if area_fraction < min_area_fraction:
            continue

        scores = score_map[rows, cols]
        peak = float(scores.max())
        mean_score = float(scores.mean())

        y0 = max((rows.min() - 0.5) / grid_h, 0.0)
        y1 = min((rows.max() + 1.5) / grid_h, 1.0)
        x0 = max((cols.min() - 0.5) / grid_w, 0.0)
        x1 = min((cols.max() + 1.5) / grid_w, 1.0)
        if x1 <= x0 or y1 <= y0:
            continue

        cx = float((cols.mean() + 0.5) / grid_w)
        cy = float((rows.mean() + 0.5) / grid_h)

        box = BoundingBox(
            x0=round(x0, 5),
            y0=round(y0, 5),
            x1=round(x1, 5),
            y1=round(y1, 5),
            pixel_box=(
                int(round(x0 * width)),
                int(round(y0 * height)),
                int(round(x1 * width)),
                int(round(y1 * height)),
            ),
        )
        region = Region(
            region_id=f"{prefix}-{index + 1:03d}",
            label=label,
            score=round(float(np.clip(peak, 0.0, 1.0)), 4),
            box=box,
            centroid=(round(cx, 4), round(cy, 4)),
            area_fraction=round(box.area_fraction, 5),
            placement=describe_placement(cx, cy),
            notes=f"mean response {mean_score:.3f} over {members.shape[0]} grid cells",
        )
        candidates.append((peak, region))

    candidates.sort(key=lambda item: item[0], reverse=True)
    ranked = [region for _, region in candidates[:max_regions]]
    return [
        region.model_copy(update={"region_id": f"{prefix}-{position + 1:03d}"})
        for position, region in enumerate(ranked)
    ]


# ---------------------------------------------------------------------------
# Windowing for grounding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """One candidate crop, in pixel and normalised coordinates."""

    left: int
    top: int
    right: int
    bottom: int
    scale: float

    @property
    def norm_box(self) -> Tuple[float, float, float, float]:
        return (self.left, self.top, self.right, self.bottom)  # filled by caller


def generate_windows(
    width: int,
    height: int,
    scales: Sequence[float],
    *,
    stride_ratio: float = 0.5,
    max_windows: int = 320,
    min_edge_px: int = 48,
) -> List[Window]:
    """Multi-scale sliding windows over the image.

    Scales are expressed as a fraction of the shorter edge, so a 0.25 scale on
    a 1024x768 scene produces 192 px windows regardless of aspect ratio. If the
    full sweep would exceed `max_windows`, coarse scales are kept and the
    finest ones are dropped, because the fine scales are the expensive ones and
    the coarse ones carry most of the recall.
    """
    shorter = min(width, height)
    windows: List[Window] = []

    for scale in sorted(scales, reverse=True):
        edge = int(round(shorter * scale))
        if edge < min_edge_px or edge <= 0:
            continue
        edge = min(edge, shorter)
        stride = max(int(round(edge * stride_ratio)), 1)

        tops = list(range(0, max(height - edge, 0) + 1, stride))
        lefts = list(range(0, max(width - edge, 0) + 1, stride))
        if tops[-1] != height - edge and height - edge > 0:
            tops.append(height - edge)
        if lefts[-1] != width - edge and width - edge > 0:
            lefts.append(width - edge)

        scale_windows = [
            Window(left=left, top=top, right=left + edge, bottom=top + edge, scale=scale)
            for top in tops
            for left in lefts
        ]
        if len(windows) + len(scale_windows) > max_windows:
            remaining = max_windows - len(windows)
            if remaining <= 0:
                break
            step = max(1, len(scale_windows) // remaining)
            scale_windows = scale_windows[::step][:remaining]
        windows.extend(scale_windows)
        if len(windows) >= max_windows:
            break

    if not windows:
        windows = [Window(left=0, top=0, right=width, bottom=height, scale=1.0)]
    return windows


def accumulate_window_scores(
    windows: Sequence[Window],
    scores: Sequence[float],
    width: int,
    height: int,
    grid: int = 32,
) -> np.ndarray:
    """Project per-window scores onto a coarse grid by area-weighted averaging.

    A pixel covered by several windows gets the mean of their scores, weighted
    by nothing more exotic than coverage count. This is what turns a bag of
    independent crop scores into a spatial response map.
    """
    if len(windows) != len(scores):
        raise ValueError("windows and scores must be the same length")

    total = np.zeros((grid, grid), dtype=np.float64)
    count = np.zeros((grid, grid), dtype=np.float64)

    for window, score in zip(windows, scores):
        r0 = int(math.floor(window.top / height * grid))
        r1 = int(math.ceil(window.bottom / height * grid))
        c0 = int(math.floor(window.left / width * grid))
        c1 = int(math.ceil(window.right / width * grid))
        r0 = max(0, min(r0, grid - 1))
        c0 = max(0, min(c0, grid - 1))
        r1 = max(r0 + 1, min(r1, grid))
        c1 = max(c0 + 1, min(c1, grid))
        total[r0:r1, c0:c1] += float(score)
        count[r0:r1, c0:c1] += 1.0

    with np.errstate(invalid="ignore", divide="ignore"):
        averaged = np.where(count > 0, total / np.maximum(count, 1e-9), 0.0)
    return averaged


def patch_grid(image: Image.Image, grid: int) -> Tuple[List[Image.Image], List[Tuple[int, int]]]:
    """Split an image into a `grid` x `grid` set of crops, row-major."""
    width, height = image.size
    xs = [int(round(i * width / grid)) for i in range(grid + 1)]
    ys = [int(round(i * height / grid)) for i in range(grid + 1)]
    crops: List[Image.Image] = []
    coords: List[Tuple[int, int]] = []
    for r in range(grid):
        for c in range(grid):
            left, right = xs[c], max(xs[c + 1], xs[c] + 1)
            top, bottom = ys[r], max(ys[r + 1], ys[r] + 1)
            crops.append(image.crop((left, top, right, bottom)))
            coords.append((r, c))
    return crops, coords


# ---------------------------------------------------------------------------
# Change detection support
# ---------------------------------------------------------------------------


def align_pair(first: LoadedImage, second: LoadedImage) -> Tuple[np.ndarray, np.ndarray, Tuple[int, int], List[str]]:
    """Bring two scenes onto a common raster.

    This is a resampling step, not a registration step. If the two epochs are
    not already co-registered, the differences this produces are dominated by
    misalignment rather than by real change, so the caller is handed a warning
    to pass through to the operator.
    """
    warnings: List[str] = []
    target_w = min(first.width, second.width)
    target_h = min(first.height, second.height)
    target_w = max(target_w, 64)
    target_h = max(target_h, 64)

    if (first.width, first.height) != (second.width, second.height):
        warnings.append(
            f"Epochs differ in size ({first.width}x{first.height} vs "
            f"{second.width}x{second.height}); both were resampled to "
            f"{target_w}x{target_h}. Differences near edges may be resampling artefacts."
        )

    a = np.asarray(first.pil.resize((target_w, target_h), Image.LANCZOS), dtype=np.uint8)
    b = np.asarray(second.pil.resize((target_w, target_h), Image.LANCZOS), dtype=np.uint8)

    shift, before_score, after_score = _estimate_translation(a, b)
    if shift != (0, 0) and after_score - before_score >= 0.03:
        b = _translate_array(b, shift[0], shift[1])
        warnings.append(
            f"Applied a small translation alignment of {shift[0]} px horizontally and "
            f"{shift[1]} px vertically; residual registration quality is {after_score:.2f}."
        )

    ratio_a = first.width / max(first.height, 1)
    ratio_b = second.width / max(second.height, 1)
    if abs(ratio_a - ratio_b) > 0.08:
        warnings.append(
            "The two epochs have noticeably different aspect ratios, so they probably do not "
            "cover the same footprint. Treat the change map as indicative only."
        )

    return a, b, (target_w, target_h), warnings


def pair_correspondence(a: np.ndarray, b: np.ndarray) -> Dict[str, float]:
    """Measure residual pixel correspondence after the alignment step.

    This is deliberately a conservative image-space check, not a claim of
    geospatial registration. It catches unrelated scenes and severe crop or
    alignment failures before change scores are presented as observations.
    """
    score = _correlation(to_gray(a), to_gray(b))
    return {
        "pixel_correlation": round(score, 4),
        # A real localized change can lower whole-frame correlation sharply;
        # footprint/aspect checks provide the stronger guard against crops.
        "minimum_safe_correlation": 0.10,
        "safe": bool(score >= 0.10),
    }


def _correlation(first: np.ndarray, second: np.ndarray) -> float:
    left = first.astype(np.float64).ravel()
    right = second.astype(np.float64).ravel()
    left -= left.mean()
    right -= right.mean()
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator < 1e-9:
        return 1.0 if np.allclose(first, second) else 0.0
    return float(np.clip(np.dot(left, right) / denominator, -1.0, 1.0))


def _translate_array(array: np.ndarray, dx: int, dy: int) -> np.ndarray:
    shifted = np.roll(array, (dy, dx), axis=(0, 1))
    if dy > 0:
        shifted[:dy, :] = shifted[dy : dy + 1, :]
    elif dy < 0:
        shifted[dy:, :] = shifted[dy - 1 : dy, :]
    if dx > 0:
        shifted[:, :dx] = shifted[:, dx : dx + 1]
    elif dx < 0:
        shifted[:, dx:] = shifted[:, dx - 1 : dx]
    return shifted


def _estimate_translation(
    first: np.ndarray, second: np.ndarray
) -> Tuple[Tuple[int, int], float, float]:
    """Find a small translational correction using a bounded correlation search."""
    height, width = first.shape[:2]
    scale = min(1.0, 128.0 / max(height, width))
    size = (max(32, int(round(width * scale))), max(32, int(round(height * scale))))
    first_small = np.asarray(Image.fromarray(first).resize(size, Image.BILINEAR))
    second_small = np.asarray(Image.fromarray(second).resize(size, Image.BILINEAR))
    first_gray = to_gray(first_small)
    second_gray = to_gray(second_small)
    limit_x = min(16, max(1, size[0] // 8))
    limit_y = min(16, max(1, size[1] // 8))

    best_shift = (0, 0)
    before = _correlation(first_gray, second_gray)
    best = before
    for dy in range(-limit_y, limit_y + 1):
        for dx in range(-limit_x, limit_x + 1):
            candidate = _translate_array(second_gray, dx, dy)
            score = _correlation(first_gray, candidate)
            if score > best:
                best = score
                best_shift = (dx, dy)

    full_dx = int(round(best_shift[0] / max(scale, 1e-9)))
    full_dy = int(round(best_shift[1] / max(scale, 1e-9)))
    return (full_dx, full_dy), before, best


def normalised_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Illumination-robust absolute difference of two RGB rasters.

    Each epoch is standardised to zero mean and unit variance in luma before
    differencing, so a global brightness or gain shift between acquisitions
    does not masquerade as change across the entire scene.
    """
    gray_a = to_gray(a)
    gray_b = to_gray(b)

    def standardise(plane: np.ndarray) -> np.ndarray:
        mean = float(plane.mean())
        std = float(plane.std())
        if std < 1e-9:
            return np.zeros_like(plane)
        return (plane - mean) / std

    diff = np.abs(standardise(gray_a) - standardise(gray_b))
    return box_blur(diff, radius=2)


# ---------------------------------------------------------------------------
# Optical / SAR heuristics
# ---------------------------------------------------------------------------


def analyse_modality(array: np.ndarray) -> Tuple[Modality, float, Dict[str, Any]]:
    """Infer acquisition modality from pixel statistics alone.

    Three signals separate a radar amplitude product from a passive optical
    scene, and none of them requires a model:

    * Chromaticity. SAR amplitude is a single band; when it is written to an
      RGB container the three channels are near-identical, so mean per-pixel
      channel spread collapses towards zero.
    * Speckle. Radar is a coherent imaging system, so its multiplicative
      speckle gives a high local coefficient of variation - the ratio of local
      standard deviation to local mean - even over homogeneous surfaces.
      Optical sensors are incoherent and produce much smoother homogeneous
      areas.
    * Intensity skew. SAR amplitude histograms are strongly right-skewed: a
      dark background of specular surfaces with a long tail of bright
      double-bounce returns.

    The result is a heuristic and is reported as one. It is a default that the
    caller can override with an explicit modality hint.
    """
    rgb = array.astype(np.float64)
    channel_spread = float(np.mean(rgb.max(axis=2) - rgb.min(axis=2)))

    gray = to_gray(array)
    local_mean = box_blur(gray, radius=3)
    local_sq = box_blur(gray ** 2, radius=3)
    local_var = np.maximum(local_sq - local_mean ** 2, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        coeff_var = np.sqrt(local_var) / np.maximum(local_mean, 1.0)
    median_cv = float(np.median(coeff_var))

    mean_intensity = float(gray.mean())
    std_intensity = float(gray.std())
    if std_intensity > 1e-9:
        skew = float(np.mean(((gray - mean_intensity) / std_intensity) ** 3))
    else:
        skew = 0.0

    # Each cue is mapped to a [0, 1] vote for SAR, then averaged with weights
    # reflecting how discriminative the cue is in practice.
    grayness_vote = float(np.clip((12.0 - channel_spread) / 12.0, 0.0, 1.0))
    speckle_vote = float(np.clip((median_cv - 0.12) / 0.28, 0.0, 1.0))
    skew_vote = float(np.clip(skew / 2.0, 0.0, 1.0))

    sar_score = 0.55 * grayness_vote + 0.30 * speckle_vote + 0.15 * skew_vote

    evidence: Dict[str, Any] = {
        "mean_channel_spread": round(channel_spread, 3),
        "median_local_coefficient_of_variation": round(median_cv, 4),
        "intensity_skew": round(skew, 4),
        "grayness_vote": round(grayness_vote, 3),
        "speckle_vote": round(speckle_vote, 3),
        "skew_vote": round(skew_vote, 3),
        "sar_score": round(sar_score, 4),
        "method": "pixel-statistics heuristic (chromaticity, speckle, histogram skew)",
    }

    if sar_score >= 0.62:
        return Modality.SAR, float(np.clip(sar_score, 0.0, 1.0)), evidence
    if sar_score <= 0.34:
        return Modality.OPTICAL, float(np.clip(1.0 - sar_score, 0.0, 1.0)), evidence
    # A score near 0.5 is ambiguity, not confidence. Keep UNKNOWN explicit
    # instead of turning the midpoint into a deceptively high certainty.
    return Modality.UNKNOWN, float(np.clip(abs(sar_score - 0.5) * 2.0, 0.0, 1.0)), evidence


def apply_modality(image: LoadedImage, hint: Optional[Modality]) -> LoadedImage:
    """Attach modality to a loaded image, letting an explicit hint win."""
    modality, confidence, evidence = analyse_modality(image.array)
    if hint is not None and hint is not Modality.UNKNOWN:
        evidence["heuristic_modality"] = modality.value
        evidence["overridden_by_hint"] = True
        image.modality = hint
        image.modality_confidence = 1.0
    else:
        image.modality = modality
        image.modality_confidence = confidence
    image.modality_evidence = evidence
    return image


def dominant_colour_terms(array: np.ndarray) -> List[str]:
    """Coarse colour vocabulary describing an optical scene.

    Used to enrich captions with grounded colour language instead of letting
    the captioner invent it. Reported only for optical imagery, since colour
    has no meaning in a radar amplitude product.
    """
    rgb = array.astype(np.float64) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    value = maximum
    saturation = np.where(maximum > 1e-6, (maximum - minimum) / np.maximum(maximum, 1e-6), 0.0)

    terms: List[Tuple[str, float]] = []
    vegetation = (g > r * 1.03) & (g > b * 1.03) & (saturation > 0.10)
    water = (b > r * 1.05) & (b >= g * 0.95) & (value < 0.62)
    bright = (value > 0.72) & (saturation < 0.18)
    dark = value < 0.22
    earth = (r > g * 1.02) & (g > b * 1.02) & (saturation > 0.12)

    for name, mask in (
        ("green vegetated cover", vegetation),
        ("dark blue-toned water or shadow", water),
        ("bright light-toned surfaces", bright),
        ("very dark surfaces", dark),
        ("warm earth or bare-soil tones", earth),
    ):
        fraction = float(mask.mean())
        if fraction >= 0.08:
            terms.append((name, fraction))

    terms.sort(key=lambda item: item[1], reverse=True)
    return [f"{name} ({fraction * 100:.0f}% of pixels)" for name, fraction in terms[:3]]


def texture_summary(array: np.ndarray) -> Dict[str, float]:
    """Simple texture descriptors that hold for both optical and SAR."""
    gray = to_gray(array)
    gy = np.abs(np.diff(gray, axis=0)).mean() if gray.shape[0] > 1 else 0.0
    gx = np.abs(np.diff(gray, axis=1)).mean() if gray.shape[1] > 1 else 0.0
    return {
        "mean_intensity": round(float(gray.mean()), 3),
        "intensity_std": round(float(gray.std()), 3),
        "mean_gradient": round(float((gx + gy) / 2.0), 4),
        "edge_density": round(float((np.abs(np.diff(gray, axis=1)) > 18).mean()), 4)
        if gray.shape[1] > 1
        else 0.0,
    }


def image_digest(images: Iterable[LoadedImage]) -> str:
    """Stable cache key across a set of images."""
    digest = hashlib.sha256()
    for image in images:
        digest.update(image.sha256.encode("ascii"))
        digest.update(b"|")
    return digest.hexdigest()[:24]
