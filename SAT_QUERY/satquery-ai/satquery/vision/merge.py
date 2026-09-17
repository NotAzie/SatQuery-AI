"""EO tiling and duplicate suppression utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from .evidence import Detection


@dataclass(frozen=True)
class Tile:
    tile_id: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def generate_tiles(width: int, height: int, *, tile_size: int = 1024, overlap: float = 0.2) -> List[Tile]:
    if tile_size < 1 or not 0 <= overlap < 1:
        raise ValueError("tile_size must be positive and overlap must be in [0, 1).")
    step = max(1, int(round(tile_size * (1.0 - overlap))))
    tiles: List[Tile] = []
    y = 0
    row = 0
    while y < height:
        x = 0
        col = 0
        bottom = min(height, y + tile_size)
        while x < width:
            right = min(width, x + tile_size)
            tiles.append(Tile(f"tile-{row:03d}-{col:03d}", x, y, right, bottom))
            if right == width:
                break
            x += step
            col += 1
        if bottom == height:
            break
        y += step
        row += 1
    return tiles


def _iou(left: Tuple[float, float, float, float], right: Tuple[float, float, float, float]) -> float:
    x0 = max(left[0], right[0])
    y0 = max(left[1], right[1])
    x1 = min(left[2], right[2])
    y1 = min(left[3], right[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    return intersection / max(left_area + right_area - intersection, 1e-12)


def non_max_suppression(detections: Sequence[Detection], *, iou_threshold: float = 0.5) -> List[Detection]:
    kept: List[Detection] = []
    for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
        if any(existing.label == detection.label and _iou(existing.box, detection.box) >= iou_threshold for existing in kept):
            continue
        kept.append(detection)
    return kept


def merge_detections(detections: Iterable[Detection], *, iou_threshold: float = 0.5) -> List[Detection]:
    return non_max_suppression(list(detections), iou_threshold=iou_threshold)
