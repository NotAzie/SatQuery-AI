"""Exportable visual evidence renderers for future UI integration."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .evidence import Detection, Segmentation


def render_evidence(
    image: Image.Image,
    *,
    detections: Sequence[Detection] = (),
    segmentations: Sequence[Segmentation] = (),
    output_path: Optional[str | Path] = None,
    mask_alpha: int = 90,
) -> Image.Image:
    """Render boxes and masks onto a copy; never mutates the source image."""
    base = image.convert("RGBA").copy()
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = [(255, 72, 72), (48, 180, 255), (72, 210, 120), (255, 190, 50)]
    for index, segmentation in enumerate(segmentations):
        mask = Image.fromarray((segmentation.mask.astype(np.uint8) * 255), mode="L").resize(base.size)
        color = colors[index % len(colors)]
        tint = Image.new("RGBA", base.size, (*color, mask_alpha))
        overlay = Image.composite(tint, overlay, mask)
        draw = ImageDraw.Draw(overlay)
    for index, detection in enumerate(detections):
        color = colors[index % len(colors)]
        box = tuple(int(round(value)) for value in detection.box)
        draw.rectangle(box, outline=(*color, 255), width=3)
        text = f"{detection.label} {detection.confidence:.2f}"
        draw.text((box[0] + 4, max(0, box[1] - 18)), text, fill=(*color, 255))
    rendered = Image.alpha_composite(base, overlay).convert("RGB")
    if output_path is not None:
        rendered.save(output_path)
    return rendered
