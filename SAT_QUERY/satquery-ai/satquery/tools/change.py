"""Bi-temporal change detection.

Two independent views of change are computed and fused:

* Radiometric. Both epochs are standardised in luma before differencing, so a
  global brightness or gain shift between acquisitions does not read as change
  across the whole scene. Otsu picks the threshold from the difference
  histogram rather than a fixed constant.
* Semantic. Each epoch is split into a patch grid and embedded with CLIP; the
  cosine distance per patch measures whether the *content* of that patch
  changed, which catches a field becoming a car park even when mean brightness
  barely moves.

Fusing the two is what separates real change from illumination and seasonal
drift. Both epochs are also classified so the summary can name the transition.

This is genuine differencing, not registration. Uncorrected misalignment
dominates any real signal, so the tool says so when the inputs look
mismatched.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from ..imaging import (
    align_pair,
    normalised_difference,
    otsu_threshold,
    pair_correspondence,
    regions_from_score_map,
)
from ..errors import QueryError
from ..schemas import BackendKind, Region, ToolName, ToolResult
from .base import Tool, ToolContext

#: Full-scale references for fusing the two channels.
#:
#: These must be absolute, not min-max derived. Rescaling each channel to its
#: own observed range would stretch pure sensor noise across the full [0, 1]
#: span, so two identical scenes differing only in gain would come back as
#: heavily changed. Anchoring to fixed references keeps "almost nothing moved"
#: distinguishable from "half the scene was rebuilt".
#:
#: The radiometric map is in units of standard deviations of standardised luma,
#: so one sigma of local difference counts as a full response. The semantic map
#: is a cosine distance between co-located patch embeddings, where 0.25 is
#: already a substantial change of content.
RADIOMETRIC_FULL_SCALE = 1.0
SEMANTIC_FULL_SCALE = 0.25

#: Below this fused response, the scene is reported as unchanged rather than
#: having boxes drawn around whatever happened to be marginally brightest.
SIGNIFICANCE_FLOOR = 0.20


class ChangeDetectionTool(Tool):
    name = ToolName.CHANGE
    description = (
        "Compares two co-registered epochs, fusing radiometric differencing with CLIP "
        "semantic patch drift, and reports where and how the scene changed."
    )
    min_images = 2
    max_images = 2

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        first, second = context.images[0], context.images[1]

        array_a, array_b, (width, height), align_warnings = align_pair(first, second)
        for warning in align_warnings:
            context.warn(warning)

        aspect_a = first.width / max(first.height, 1)
        aspect_b = second.width / max(second.height, 1)
        aspect_delta = abs(aspect_a - aspect_b)
        correspondence = pair_correspondence(array_a, array_b)
        correspondence["aspect_ratio_delta"] = round(aspect_delta, 4)
        correspondence["safe"] = bool(correspondence["safe"]) and aspect_delta <= 0.08
        if aspect_delta > 0.08:
            raise QueryError(
                "The two images do not have a sufficiently corresponding footprint for safe "
                "change detection.",
                remediation=[
                    "Provide the same geographic footprint with matching orientation and crop.",
                    "Use co-registered epochs rather than unrelated screenshots or views.",
                ],
                context={"correspondence": correspondence},
            )
        if not correspondence["safe"]:
            raise QueryError(
                "The two epochs have insufficient pixel correspondence for a trustworthy "
                "change result.",
                remediation=[
                    "Use co-registered images of the same footprint and acquisition geometry.",
                    "Check for crop, rotation, cloud cover, or unrelated scenes before retrying.",
                ],
                context={"correspondence": correspondence},
            )
        if correspondence["pixel_correlation"] < 0.30:
            context.warn(
                "The epochs correspond only moderately after alignment; change regions are "
                "indicative and should be reviewed against the source imagery."
            )

        # -- Radiometric channel ------------------------------------------
        difference = normalised_difference(array_a, array_b)
        threshold = otsu_threshold(difference)
        changed_mask = difference > threshold
        radiometric_ratio = float(changed_mask.mean())

        signed = np.sign(
            np.asarray(Image.fromarray(array_b).convert("L"), dtype=np.float64)
            - np.asarray(Image.fromarray(array_a).convert("L"), dtype=np.float64)
        )
        brightened = int(np.count_nonzero(changed_mask & (signed > 0)))
        darkened = int(np.count_nonzero(changed_mask & (signed < 0)))

        # -- Semantic channel ---------------------------------------------
        grid = context.settings.change_patch_grid
        semantic_map: Optional[np.ndarray] = None
        semantic_model: Optional[str] = None
        if context.vision.has_embedder:
            try:
                semantic_map, semantic_model = self._semantic_drift(
                    context, Image.fromarray(array_a), Image.fromarray(array_b), grid
                )
            except Exception as exc:
                context.warn(
                    "Semantic change analysis could not run, so this result rests on pixel "
                    f"differencing alone ({exc.__class__.__name__})."
                )

        # -- Fusion --------------------------------------------------------
        radiometric_grid = self._saturating_scale(
            self._downsample_mean(difference, grid), RADIOMETRIC_FULL_SCALE
        )

        if semantic_map is not None:
            fused = 0.45 * radiometric_grid + 0.55 * self._saturating_scale(
                semantic_map, SEMANTIC_FULL_SCALE
            )
            method = "fused radiometric difference and CLIP semantic patch drift"
        else:
            fused = radiometric_grid
            method = "radiometric difference only (no embedding backend available)"

        peak = float(fused.max())
        significant = peak >= SIGNIFICANCE_FLOOR

        # Otsu only helps where there are two populations to separate. On a
        # uniformly changed scene it collapses onto the single mode and would
        # exclude everything, so it is applied only when the map has spread.
        spread = float(fused.std())
        fused_threshold = float(fused.mean() + 0.6 * spread)
        if spread > 0.05:
            fused_threshold = max(fused_threshold, float(otsu_threshold(fused)))
        fused_threshold = max(fused_threshold, SIGNIFICANCE_FLOOR)

        if significant:
            regions = regions_from_score_map(
                fused,
                label="changed area",
                width=width,
                height=height,
                threshold=fused_threshold,
                min_area_fraction=context.settings.change_min_region_frac,
                max_regions=context.settings.grounding_max_regions,
                prefix="chg",
            )
            fused_ratio = float((fused >= fused_threshold).mean())
        else:
            regions = []
            fused_ratio = 0.0

        # -- Scene transition ---------------------------------------------
        transition = self._scene_transition(context)

        summary = self._compose(
            context=context,
            radiometric_ratio=radiometric_ratio,
            fused_ratio=fused_ratio,
            brightened=brightened,
            darkened=darkened,
            regions=regions,
            transition=transition,
            semantic_available=semantic_map is not None,
            method=method,
            threshold=threshold,
            significant=significant,
            peak=peak,
        )

        return self.result(
            summary=summary,
            started=started,
            backend=BackendKind.PRACTICAL if semantic_map is not None else BackendKind.NONE,
            model=semantic_model,
            data={
                "epoch_a": first.filename,
                "epoch_b": second.filename,
                "aligned_size": [width, height],
                "correspondence": correspondence,
                "method": method,
                "radiometric": {
                    "otsu_threshold": round(float(threshold), 5),
                    "changed_ratio": round(radiometric_ratio, 5),
                    "brightened_pixels": brightened,
                    "darkened_pixels": darkened,
                    "mean_difference": round(float(difference.mean()), 5),
                    "max_difference": round(float(difference.max()), 5),
                },
                "semantic": {
                    "available": semantic_map is not None,
                    "patch_grid": grid,
                    "mean_drift": round(float(semantic_map.mean()), 5)
                    if semantic_map is not None
                    else None,
                    "max_drift": round(float(semantic_map.max()), 5)
                    if semantic_map is not None
                    else None,
                },
                "fused": {
                    "significant": significant,
                    "peak_response": round(peak, 5),
                    "significance_floor": SIGNIFICANCE_FLOOR,
                    "threshold": round(fused_threshold, 5),
                    "changed_ratio": round(fused_ratio, 5),
                    "region_count": len(regions),
                    "map": np.round(fused, 4).tolist(),
                },
                "scene_transition": transition,
            },
            regions=regions,
            confidence=round(
                float(np.clip(peak * min(correspondence["pixel_correlation"] / 0.30, 1.0), 0.0, 1.0)),
                4,
            ),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _semantic_drift(
        context: ToolContext, image_a: Image.Image, image_b: Image.Image, grid: int
    ) -> Tuple[np.ndarray, str]:
        """Cosine distance between co-located patch embeddings."""
        from ..imaging import patch_grid

        embedder = context.vision.embedder
        crops_a, coords = patch_grid(image_a, grid)
        crops_b, _ = patch_grid(image_b, grid)

        embeds_a = embedder.embed_images(crops_a)
        embeds_b = embedder.embed_images(crops_b)

        # Both sets are already L2-normalised, so the row-wise dot product is
        # the cosine similarity and 1 - it is the drift.
        similarity = np.sum(embeds_a * embeds_b, axis=1)
        drift = 1.0 - similarity

        drift_map = np.zeros((grid, grid), dtype=np.float64)
        for value, (row, col) in zip(drift, coords):
            drift_map[row, col] = float(value)
        return drift_map, embedder.name

    @staticmethod
    def _downsample_mean(matrix: np.ndarray, grid: int) -> np.ndarray:
        """Block-mean a full-resolution map onto the patch grid."""
        height, width = matrix.shape
        rows = np.linspace(0, height, grid + 1).astype(int)
        cols = np.linspace(0, width, grid + 1).astype(int)
        output = np.zeros((grid, grid), dtype=np.float64)
        for r in range(grid):
            for c in range(grid):
                block = matrix[rows[r] : max(rows[r + 1], rows[r] + 1),
                               cols[c] : max(cols[c + 1], cols[c] + 1)]
                output[r, c] = float(block.mean()) if block.size else 0.0
        return output

    @staticmethod
    def _saturating_scale(matrix: np.ndarray, full_scale: float) -> np.ndarray:
        """Map a channel onto [0, 1] against a fixed reference, not its own range."""
        return np.clip(matrix / max(full_scale, 1e-9), 0.0, 1.0)

    @staticmethod
    def _scene_transition(context: ToolContext) -> Optional[Dict[str, Any]]:
        """Classify both epochs so the change can be named, not just located."""
        if not context.vision.has_embedder:
            return None

        from ..tools.scene import SceneClassificationTool

        tool = SceneClassificationTool()
        try:
            first_context = _single_image_context(context, 0)
            second_context = _single_image_context(context, 1)
            before = tool.run(first_context)
            after = tool.run(second_context)
        except Exception as exc:
            context.warn(
                f"Per-epoch scene classification did not run ({exc.__class__.__name__}); the "
                "change summary will not name a land-use transition."
            )
            return None

        before_label = before.labels[0] if before.labels else None
        after_label = after.labels[0] if after.labels else None
        if before_label is None or after_label is None:
            return None

        return {
            "before": {
                "label": before_label.label,
                "group": before_label.group,
                "score": before_label.score,
            },
            "after": {
                "label": after_label.label,
                "group": after_label.group,
                "score": after_label.score,
            },
            "group_changed": before_label.group != after_label.group,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _compose(
        *,
        context: ToolContext,
        radiometric_ratio: float,
        fused_ratio: float,
        brightened: int,
        darkened: int,
        regions: List[Region],
        transition: Optional[Dict[str, Any]],
        semantic_available: bool,
        method: str,
        threshold: float,
        significant: bool,
        peak: float,
    ) -> str:
        first, second = context.images[0], context.images[1]

        if not significant:
            return (
                f"Comparing '{first.filename}' against '{second.filename}', nothing in the "
                f"common footprint rises to the level of real change. The strongest fused "
                f"response anywhere in the scene is {peak:.3f}, against a floor of "
                f"{SIGNIFICANCE_FLOOR:.2f}. Radiometric differencing flags "
                f"{radiometric_ratio * 100:.2f}% of pixels at an Otsu threshold of "
                f"{threshold:.3f}, but that split is being drawn through noise rather than "
                f"through two distinct populations - the standardised difference removes any "
                f"uniform gain or brightness offset between the acquisitions, and what remains "
                f"is flat. No change regions are reported."
            )

        parts = [
            f"Comparing '{first.filename}' against '{second.filename}', "
            f"{fused_ratio * 100:.2f}% of the common footprint is flagged as changed "
            f"(peak fused response {peak:.2f})."
        ]

        parts.append(
            f"Radiometric differencing alone flags {radiometric_ratio * 100:.2f}% at an Otsu "
            f"threshold of {threshold:.3f}, split {brightened:,} pixels brighter and "
            f"{darkened:,} darker between the two epochs."
        )

        if semantic_available:
            parts.append(
                "CLIP patch embeddings were compared position by position, so areas whose "
                "content changed are separated from areas that merely got brighter or darker. "
                f"The reported figure is the {method}."
            )
        else:
            parts.append(
                "No embedding backend was available, so this rests on pixel differencing alone "
                "and cannot distinguish real land-cover change from illumination differences."
            )

        if regions:
            leader = regions[0]
            parts.append(
                f"{len(regions)} change region{'s' if len(regions) != 1 else ''} were isolated. "
                f"The largest response sits in the {leader.placement} at normalised box "
                f"[{leader.box.x0:.3f}, {leader.box.y0:.3f}, {leader.box.x1:.3f}, "
                f"{leader.box.y1:.3f}]."
            )
            if len(regions) > 1:
                others = "; ".join(
                    f"{region.region_id} in the {region.placement}" for region in regions[1:5]
                )
                parts.append(f"Further regions: {others}.")
        else:
            parts.append(
                "No coherent change region cleared the threshold, so whatever differences exist "
                "are scattered rather than concentrated - typically seasonal or atmospheric "
                "rather than structural."
            )

        if transition:
            before = transition["before"]
            after = transition["after"]
            if transition["group_changed"]:
                parts.append(
                    f"The scene classification shifts from {before['label']} "
                    f"({before['score'] * 100:.0f}%) to {after['label']} "
                    f"({after['score'] * 100:.0f}%), a land-use transition rather than a "
                    f"cosmetic one."
                )
            else:
                parts.append(
                    f"Both epochs still classify as {after['label']}, so the land-use category "
                    f"is unchanged even where pixels differ."
                )

        if brightened > darkened * 1.6:
            parts.append("The net direction is brightening, which over land often means clearing, new construction, or bare soil replacing vegetation.")
        elif darkened > brightened * 1.6:
            parts.append("The net direction is darkening, which often means vegetation growth, flooding, or new shadow from taller structures.")

        return " ".join(parts)


def _single_image_context(context: ToolContext, index: int) -> ToolContext:
    """A one-image view of a two-image context, for per-epoch analysis."""
    from .base import ToolContext as _ToolContext

    return _ToolContext(
        query=context.query,
        images=[context.images[index]],
        settings=context.settings,
        vision=context.vision,
        cache=context.cache,
        target=context.target,
        arguments=dict(context.arguments),
        warnings=context.warnings,
        invoke=context.invoke,
    )
