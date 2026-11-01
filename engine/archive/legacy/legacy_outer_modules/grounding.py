"""Grounding: where in the image is the thing the user asked about.

The approach is sliding-window CLIP scoring, which gives honest semantic
localisation without needing a detection head trained on overhead imagery:

1. Sweep multi-scale windows across the scene.
2. Score every window against the target phrase *relative to a contrast set*,
   so the score is "is this the target rather than one of these alternatives"
   instead of an unanchored similarity that would fire everywhere.
3. Project window scores onto a coarse response grid by area-weighted
   averaging, which turns independent crop scores into a spatial map.
4. Threshold at a high percentile, take connected components, and emit ranked
   boxes.

What this is: semantic region localisation. What it is not: instance-level
detection. Two adjacent ships fall into one region. The tool says so rather
than dressing regions up as object instances.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

from ..backends.base import softmax
from ..errors import QueryError
from ..imaging import (
    accumulate_window_scores,
    generate_windows,
    regions_from_score_map,
)
from ..schemas import BackendKind, Region, ToolName, ToolResult
from ..taxonomy import contrast_set, phrase_for_target
from .base import Tool, ToolContext

RESPONSE_GRID = 32


class GroundingTool(Tool):
    name = ToolName.GROUNDING
    description = (
        "Localises a named target within the scene using multi-scale CLIP windows, "
        "returning ranked regions with normalised boxes and spatial descriptions."
    )
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        target = (context.target or context.arguments.get("target") or "").strip()
        if not target:
            raise QueryError(
                "Grounding needs to know what to look for.",
                remediation=[
                    'Name the target in the query, for example "where are the buildings".',
                    "Or pass force_tool=grounding together with an explicit target argument.",
                ],
            )

        settings = context.settings
        image = context.primary
        cache_key = context.cache_key(self.name, target.lower(), settings.grounding_percentile)
        cached = context.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"latency_ms": self.timed(started)})

        score_map, diagnostics = self.response_map(context, target)

        threshold = float(np.percentile(score_map, settings.grounding_percentile))
        # A percentile always selects something, even from a flat map. Require
        # the selected cells to actually stand out from the background too,
        # otherwise "locate the aircraft" over empty farmland would return
        # confident-looking boxes around nothing.
        spread = float(score_map.std())
        floor = float(score_map.mean()) + 0.5 * spread
        threshold = max(threshold, floor)

        regions = regions_from_score_map(
            score_map,
            label=target,
            width=image.width,
            height=image.height,
            threshold=threshold,
            min_area_fraction=settings.grounding_min_region_frac,
            max_regions=settings.grounding_max_regions,
            prefix="gnd",
        )

        peak = float(score_map.max())
        # A weak peak means the contrast set beat the target everywhere.
        present = peak >= 0.35 and spread > 0.015
        if not present:
            regions = []

        summary = self._summarise(target, regions, peak, spread, diagnostics, present)

        result = self.result(
            summary=summary,
            started=started,
            backend=BackendKind.PRACTICAL,
            model=context.vision.embedder.name,
            data={
                "target": target,
                "target_phrase": diagnostics["target_phrase"],
                "contrast_phrases": diagnostics["contrast_phrases"],
                "windows_scored": diagnostics["window_count"],
                "scales_used": diagnostics["scales"],
                "response_grid": [RESPONSE_GRID, RESPONSE_GRID],
                "peak_response": round(peak, 4),
                "mean_response": round(float(score_map.mean()), 4),
                "response_std": round(spread, 4),
                "threshold": round(threshold, 4),
                "region_count": len(regions),
                "present": present,
                "response_map": np.round(score_map, 4).tolist(),
                "method": "multi-scale CLIP window scoring against a contrast set",
                "granularity": "semantic regions, not object instances",
            },
            regions=regions,
            confidence=round(peak, 4) if present else round(peak, 4),
        )
        context.cache.put(cache_key, result)
        return result

    # ------------------------------------------------------------------

    def response_map(self, context: ToolContext, target: str) -> tuple[np.ndarray, Dict[str, Any]]:
        """Compute the spatial response map for a target phrase.

        Exposed separately so the counting tool can reuse it without paying
        for region extraction twice.
        """
        settings = context.settings
        image = context.primary
        embedder = context.vision.embedder

        target_phrase = phrase_for_target(target)
        contrasts = contrast_set(target_phrase)
        phrases = [target_phrase] + contrasts

        windows = generate_windows(
            image.width,
            image.height,
            settings.grounding_scales,
            stride_ratio=settings.grounding_stride_ratio,
            max_windows=settings.grounding_max_windows,
        )

        crops: List[Image.Image] = [
            image.pil.crop((window.left, window.top, window.right, window.bottom))
            for window in windows
        ]

        window_embeddings = embedder.embed_images(crops)
        phrase_embeddings = embedder.embed_texts(phrases)
        logit_scale = embedder.logit_scale()

        logits = window_embeddings @ phrase_embeddings.T * logit_scale
        probabilities = softmax(logits, axis=1)[:, 0]

        score_map = accumulate_window_scores(
            windows,
            probabilities.tolist(),
            image.width,
            image.height,
            grid=RESPONSE_GRID,
        )

        diagnostics = {
            "target_phrase": target_phrase,
            "contrast_phrases": contrasts,
            "window_count": len(windows),
            "scales": sorted({round(window.scale, 3) for window in windows}, reverse=True),
        }
        return score_map, diagnostics

    # ------------------------------------------------------------------

    @staticmethod
    def _summarise(
        target: str,
        regions: List[Region],
        peak: float,
        spread: float,
        diagnostics: Dict[str, Any],
        present: bool,
    ) -> str:
        if not present or not regions:
            return (
                f"No region of this scene reads as {target}. The strongest window response was "
                f"{peak:.2f} against a contrast set of {len(diagnostics['contrast_phrases'])} "
                f"alternatives, with a spatial spread of {spread:.3f} - too flat to mark a "
                f"location. Either the target is absent, or it is smaller than the "
                f"{diagnostics['window_count']} windows scanned could resolve."
            )

        leader = regions[0]
        parts = [
            f"Found {len(regions)} region{'s' if len(regions) != 1 else ''} matching {target}. "
            f"The strongest sits in the {leader.placement} at normalised box "
            f"[{leader.box.x0:.3f}, {leader.box.y0:.3f}, {leader.box.x1:.3f}, {leader.box.y1:.3f}] "
            f"with a response of {leader.score:.2f}."
        ]

        if len(regions) > 1:
            others = "; ".join(
                f"{region.region_id} in the {region.placement} ({region.score:.2f})"
                for region in regions[1:5]
            )
            parts.append(f"Other regions: {others}.")

        coverage = sum(region.area_fraction for region in regions)
        parts.append(
            f"Together these regions cover {coverage * 100:.1f}% of the frame, scored across "
            f"{diagnostics['window_count']} windows at scales "
            f"{', '.join(str(scale) for scale in diagnostics['scales'])} of the shorter edge."
        )
        parts.append(
            "These are semantic regions rather than object instances - several adjacent objects "
            "merge into one region, so use the boxes for locating, not for counting."
        )
        return " ".join(parts)
