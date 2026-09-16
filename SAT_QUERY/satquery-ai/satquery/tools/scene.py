"""Scene and land-use classification.

CLIP zero-shot over the remote-sensing taxonomy, with two accuracy measures
that matter more here than on natural images:

* Prompt ensembling. Each label is embedded under six phrasings and averaged,
  which smooths out the sensitivity of a single template.
* Tiled voting. Overhead scenes are frequently mixed - half farmland, half
  settlement - so the image is scored whole *and* as a 2x2 tiling, and the
  tile agreement tells the caller whether the scene is homogeneous or mixed.

Probabilities come from a softmax over the model's own logit scale, so they
reflect CLIP's actual calibration rather than an invented number.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import numpy as np
from PIL import Image

from ..backends.base import softmax, templates_for
from ..schemas import BackendKind, ScoredLabel, ToolName, ToolResult
from ..taxonomy import GROUP_DESCRIPTIONS, SCENE_LABELS, SCENE_TAXONOMY
from .base import Tool, ToolContext


class SceneClassificationTool(Tool):
    name = ToolName.SCENE
    description = (
        "Classifies the scene into remote-sensing land-use categories and reports the "
        "land-use group mixture across the image."
    )
    min_images = 1
    max_images = 1

    top_k = 5

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        image = context.primary

        cache_key = context.cache_key(self.name, context.modality_name, self.top_k)
        cached = context.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"latency_ms": self.timed(started)})

        embedder = context.vision.embedder
        templates = templates_for(context.modality_name)
        label_embeddings = embedder.embed_prompt_ensemble(SCENE_LABELS, templates)
        logit_scale = embedder.logit_scale()

        # Whole-scene pass.
        whole_embedding = embedder.embed_images([image.pil])
        whole_logits = (whole_embedding @ label_embeddings.T * logit_scale)[0]

        # 2x2 tiling: catches mixed scenes that a single global embedding blurs.
        tiles = self._quadrants(image.pil)
        tile_embeddings = embedder.embed_images(tiles)
        tile_logits = tile_embeddings @ label_embeddings.T * logit_scale

        # Fuse evidence before softmax. Averaging already-normalised tile
        # probabilities lets uncertain tiles flatten the distribution and can
        # promote unstable near-ties. Logit fusion preserves the model's
        # relative evidence while letting the whole-scene view lead.
        combined_logits = 0.65 * whole_logits + 0.35 * tile_logits.mean(axis=0)
        combined = softmax(combined_logits)
        tile_probs = softmax(tile_logits, axis=1)

        order = np.argsort(combined)[::-1]
        top_margin = float(combined[order[0]] - combined[order[1]]) if len(order) > 1 else 1.0
        tile_support = float(np.mean(np.argmax(tile_probs, axis=1) == order[0]))
        ranked: List[ScoredLabel] = [
            ScoredLabel(
                label=SCENE_LABELS[index],
                score=round(float(combined[index]), 4),
                group=SCENE_TAXONOMY[SCENE_LABELS[index]],
            )
            for index in order[: self.top_k]
        ]

        group_mixture = self._group_mixture(combined)
        tile_leaders = self._tile_leaders(tile_probs)
        homogeneity = len({leader for leader, _ in tile_leaders})

        summary = self._summarise(
            ranked, group_mixture, tile_leaders, homogeneity, top_margin, tile_support
        )

        result = self.result(
            summary=summary,
            started=started,
            backend=BackendKind.PRACTICAL,
            model=embedder.name,
            data={
                "top_label": ranked[0].label,
                "top_group": ranked[0].group,
                "ranked": [item.model_dump() for item in ranked],
                "group_mixture": group_mixture,
                "tile_leaders": [
                    {"quadrant": name, "label": label, "score": round(score, 4)}
                    for (label, score), name in zip(
                        tile_leaders, ("top-left", "top-right", "bottom-left", "bottom-right")
                    )
                ],
                "distinct_tile_labels": homogeneity,
                "top_label_margin": round(top_margin, 4),
                "top_label_tile_support": round(tile_support, 4),
                "evidence_quality": (
                    "stable" if top_margin >= 0.05 and tile_support >= 0.5 else "mixed"
                ),
                "taxonomy_size": len(SCENE_LABELS),
                "prompt_templates": len(templates),
            },
            labels=ranked,
            confidence=ranked[0].score,
        )
        context.cache.put(cache_key, result)
        return result

    # ------------------------------------------------------------------

    @staticmethod
    def _quadrants(image: Image.Image) -> List[Image.Image]:
        width, height = image.size
        mid_x, mid_y = max(width // 2, 1), max(height // 2, 1)
        return [
            image.crop((0, 0, mid_x, mid_y)),
            image.crop((mid_x, 0, width, mid_y)),
            image.crop((0, mid_y, mid_x, height)),
            image.crop((mid_x, mid_y, width, height)),
        ]

    @staticmethod
    def _group_mixture(probabilities: np.ndarray) -> Dict[str, float]:
        """Collapse fine labels into land-use groups by summing probability."""
        mixture: Dict[str, float] = {}
        for label, probability in zip(SCENE_LABELS, probabilities):
            group = SCENE_TAXONOMY[label]
            mixture[group] = mixture.get(group, 0.0) + float(probability)
        ordered = sorted(mixture.items(), key=lambda item: item[1], reverse=True)
        return {group: round(value, 4) for group, value in ordered if value >= 0.01}

    @staticmethod
    def _tile_leaders(tile_probs: np.ndarray) -> List[Tuple[str, float]]:
        leaders: List[Tuple[str, float]] = []
        for row in tile_probs:
            index = int(np.argmax(row))
            leaders.append((SCENE_LABELS[index], float(row[index])))
        return leaders

    @staticmethod
    def _summarise(
        ranked: List[ScoredLabel],
        group_mixture: Dict[str, float],
        tile_leaders: List[Tuple[str, float]],
        homogeneity: int,
        top_margin: float,
        tile_support: float,
    ) -> str:
        leader = ranked[0]
        parts = [
            f"The scene classifies as {leader.label} "
            f"({leader.score * 100:.1f}% of the zero-shot probability mass), which falls under "
            f"{GROUP_DESCRIPTIONS.get(leader.group or '', leader.group or 'unclassified')}."
        ]

        runners = ranked[1:4]
        if runners:
            alternatives = "; ".join(
                f"{item.label} ({item.score * 100:.1f}%)" for item in runners
            )
            parts.append(f"Next most likely: {alternatives}.")

        if group_mixture:
            mixture_text = ", ".join(
                f"{GROUP_DESCRIPTIONS.get(group, group)} {value * 100:.0f}%"
                for group, value in list(group_mixture.items())[:4]
            )
            parts.append(f"Land-use mixture across the taxonomy: {mixture_text}.")

        if homogeneity == 1:
            parts.append(
                "All four quadrants classify the same way, so the footprint is homogeneous."
            )
        else:
            distinct = "; ".join(
                f"{name} reads as {label}"
                for (label, _), name in zip(
                    tile_leaders, ("top-left", "top-right", "bottom-left", "bottom-right")
                )
            )
            parts.append(
                f"The quadrants disagree, so this is a mixed scene - {distinct}."
            )

        parts.append(
            f"Evidence stability: the leading label is {top_margin * 100:.1f} percentage points "
            f"ahead of the runner-up and leads {tile_support * 100:.0f}% of quadrants."
        )

        if leader.score < 0.25:
            parts.append(
                "Confidence is low across the whole taxonomy, which usually means the scene "
                "contains something the label set does not cover well. Treat this as a hint "
                "rather than a classification."
            )

        return " ".join(parts)
