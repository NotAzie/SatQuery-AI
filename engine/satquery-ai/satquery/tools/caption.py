"""Detailed remote-sensing captioning.

A raw BLIP caption on an overhead image tends to be short and street-level:
"an aerial view of a city". That is true but thin. This tool builds a richer
description by fusing several real measurements of the same image:

* prompt-ensembled BLIP captions (several conditioning prefixes),
* the CLIP scene classification and its land-use mixture,
* the modality call and, for optical scenes, grounded colour statistics,
* a coarse spatial breakdown from per-quadrant captioning.

When a remote-sensing VLM is configured, it writes the description directly
and the practical signals become supporting detail, because a domain model
already has the vocabulary the fusion step is otherwise reconstructing.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..errors import ResourceNotConfiguredError
from ..imaging import dominant_colour_terms, texture_summary
from ..schemas import BackendKind, Modality, ToolName, ToolResult
from ..taxonomy import GROUP_DESCRIPTIONS, caption_prompts
from .base import Tool, ToolContext

RSVLM_CAPTION_PROMPT = (
    "Analyse this overhead remote-sensing image as a satellite image analyst. Describe "
    "only visible evidence: the dominant land cover, built structures and infrastructure, "
    "surface patterns, and spatial layout using compass or quadrant language when useful. "
    "Distinguish observation from inference, avoid street-level assumptions, and say when "
    "the resolution does not support a precise claim."
)


class CaptionTool(Tool):
    name = ToolName.CAPTION
    description = (
        "Produces a detailed remote-sensing description of the scene by fusing captioning, "
        "scene classification, modality analysis, and spatial layout."
    )
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        image = context.primary

        cache_key = context.cache_key(self.name, context.modality_name)
        cached = context.cache.get(cache_key)
        if cached is not None:
            return cached.model_copy(update={"latency_ms": self.timed(started)})

        if context.vision.has_strong:
            try:
                result = self._caption_strong(context, started)
            except Exception as exc:
                if context.vision.practical_captioner is None:
                    raise
                context.warn(
                    f"Strong captioning backend failed ({exc.__class__.__name__}); "
                    "falling back to practical captioning."
                )
                result = self._caption_practical(context, started)
        else:
            result = self._caption_practical(context, started)

        context.cache.put(cache_key, result)
        return result

    # ------------------------------------------------------------------

    def _caption_strong(self, context: ToolContext, started: float) -> ToolResult:
        """Domain VLM writes the description; practical signals corroborate."""
        backend = context.vision.captioner
        image = context.primary

        modality_note = ""
        if image.modality is Modality.SAR:
            modality_note = (
                " This is a synthetic aperture radar image, so describe structure, texture, "
                "and backscatter brightness rather than colour."
            )

        description = backend.generate([image.pil], RSVLM_CAPTION_PROMPT + modality_note)
        if not description.strip():
            context.warn(
                "The remote-sensing VLM returned an empty description; falling back to the "
                "practical captioning path."
            )
            return self._caption_practical(context, started)

        supporting = self._supporting_signals(context)
        summary = description.strip()
        if supporting.get("scene_label"):
            summary += (
                f"\n\nSupporting analysis: CLIP classifies the scene as "
                f"{supporting['scene_label']} ({supporting['scene_score'] * 100:.0f}%). "
                f"{supporting['modality_sentence']}"
            )

        return self.result(
            summary=summary,
            started=started,
            backend=BackendKind.RSVLM,
            model=backend.name,
            data={
                "description": description.strip(),
                "path": "rsvlm",
                **supporting,
            },
            labels=supporting.get("_labels", []),
            confidence=supporting.get("scene_score"),
        )

    # ------------------------------------------------------------------

    def _caption_practical(self, context: ToolContext, started: float) -> ToolResult:
        """BLIP prompt ensembling fused with CLIP scene understanding."""
        captioner = context.vision.captioner
        image = context.primary

        variants: List[str] = []
        if hasattr(captioner, "caption_variants"):
            variants = captioner.caption_variants(
                image.pil, list(caption_prompts(context.modality_name))
            )
        else:  # a strong backend standing in for the captioner
            single = captioner.generate([image.pil], RSVLM_CAPTION_PROMPT)
            variants = [single] if single.strip() else []

        if not variants:
            raise ResourceNotConfiguredError(
                "The captioning model produced no output for this image.",
                remediation=[
                    "Verify SATQUERY_CAPTION_MODEL names a BLIP conditional-generation "
                    "checkpoint.",
                    "Try a smaller image via SATQUERY_MAX_IMAGE_PX if the model ran out of memory.",
                ],
            )

        quadrant_captions = self._quadrant_captions(context, captioner)
        supporting = self._supporting_signals(context)
        texture = texture_summary(image.array)

        summary = self._compose(
            context=context,
            variants=variants,
            quadrants=quadrant_captions,
            supporting=supporting,
            texture=texture,
        )

        return self.result(
            summary=summary,
            started=started,
            backend=BackendKind.PRACTICAL,
            model=captioner.name,
            data={
                "caption_variants": variants,
                "quadrant_captions": quadrant_captions,
                "texture": texture,
                "path": "practical",
                **{key: value for key, value in supporting.items() if not key.startswith("_")},
            },
            labels=supporting.get("_labels", []),
            confidence=supporting.get("scene_score"),
        )

    # ------------------------------------------------------------------

    def _quadrant_captions(self, context: ToolContext, captioner: Any) -> Dict[str, str]:
        """Caption each quadrant so the description can carry spatial structure."""
        if not hasattr(captioner, "caption_variants"):
            return {}

        image = context.primary.pil
        width, height = image.size
        mid_x, mid_y = max(width // 2, 1), max(height // 2, 1)
        boxes = {
            "top-left": (0, 0, mid_x, mid_y),
            "top-right": (mid_x, 0, width, mid_y),
            "bottom-left": (0, mid_y, mid_x, height),
            "bottom-right": (mid_x, mid_y, width, height),
        }

        captions: Dict[str, str] = {}
        for name, box in boxes.items():
            try:
                produced = captioner.caption_variants(image.crop(box), ["an aerial view of"])
            except Exception as exc:
                context.warn(
                    f"Quadrant captioning failed for {name} ({exc.__class__.__name__}); the "
                    "description will omit spatial breakdown."
                )
                return {}
            if produced:
                captions[name] = produced[0]
        return captions

    def _supporting_signals(self, context: ToolContext) -> Dict[str, Any]:
        """Pull scene classification and modality context, tolerating failure."""
        signals: Dict[str, Any] = {
            "scene_label": None,
            "scene_score": None,
            "scene_group": None,
            "group_mixture": {},
            "modality": context.modality_name,
            "modality_sentence": "",
            "_labels": [],
        }

        image = context.primary
        if image.modality is Modality.SAR:
            signals["modality_sentence"] = (
                "The scene is radar amplitude, so brightness reflects surface roughness and "
                "moisture rather than colour."
            )
        elif image.modality is Modality.OPTICAL:
            signals["modality_sentence"] = (
                f"The scene is passive optical (confidence {image.modality_confidence:.2f})."
            )
        else:
            signals["modality_sentence"] = (
                "The acquisition modality could not be determined confidently from pixel "
                "statistics."
            )

        if not context.vision.has_embedder:
            return signals

        try:
            scene = context.run_tool(ToolName.SCENE)
        except Exception as exc:
            context.warn(
                f"Scene classification did not contribute to this caption ({exc.__class__.__name__})."
            )
            return signals

        if scene.labels:
            leader = scene.labels[0]
            signals["scene_label"] = leader.label
            signals["scene_score"] = leader.score
            signals["scene_group"] = leader.group
            signals["_labels"] = list(scene.labels)
            signals["group_mixture"] = scene.data.get("group_mixture", {})
            signals["distinct_tile_labels"] = scene.data.get("distinct_tile_labels")
        return signals

    # ------------------------------------------------------------------

    @staticmethod
    def _compose(
        *,
        context: ToolContext,
        variants: List[str],
        quadrants: Dict[str, str],
        supporting: Dict[str, Any],
        texture: Dict[str, float],
    ) -> str:
        image = context.primary
        parts: List[str] = []

        headline = variants[0]
        if not headline.endswith("."):
            headline += "."

        if supporting.get("scene_label"):
            group = supporting.get("scene_group") or ""
            parts.append(
                f"Overhead land-use evidence reads the footprint as {supporting['scene_label']} "
                f"({supporting['scene_score'] * 100:.0f}% zero-shot mass), which is "
                f"{GROUP_DESCRIPTIONS.get(group, group or 'unclassified')}."
            )
            if supporting.get("distinct_tile_labels") is not None:
                tile_count = supporting["distinct_tile_labels"]
                parts.append(
                    f"Spatial consistency check: {tile_count} distinct land-use readings appear "
                    "across the four quadrants, so the scene should be interpreted as "
                    + ("mixed." if tile_count > 1 else "relatively homogeneous.")
                )
        parts.append("Visual caption: " + headline)

        mixture = supporting.get("group_mixture") or {}
        if len(mixture) > 1:
            listed = ", ".join(
                f"{GROUP_DESCRIPTIONS.get(name, name)} {value * 100:.0f}%"
                for name, value in list(mixture.items())[:3]
            )
            parts.append(f"The land-use mixture is {listed}.")

        extra_variants = [text for text in variants[1:] if text]
        if extra_variants:
            parts.append(
                "Alternative readings under different conditioning prompts: "
                + "; ".join(extra_variants[:3])
                + "."
            )

        if quadrants:
            spatial = "; ".join(f"{name}, {text.lower()}" for name, text in quadrants.items())
            parts.append(f"By quadrant - {spatial}.")

        if image.modality is not Modality.SAR:
            colours = dominant_colour_terms(image.array)
            if colours:
                parts.append("Dominant tones across the frame: " + "; ".join(colours) + ".")

        parts.append(
            f"Remote-sensing evidence: Texture statistics: mean intensity {texture['mean_intensity']:.0f}, standard "
            f"deviation {texture['intensity_std']:.0f}, edge density "
            f"{texture['edge_density']:.3f} - "
            + (
                "a highly structured scene with many boundaries."
                if texture["edge_density"] > 0.18
                else "a relatively smooth scene with few hard boundaries."
            )
        )

        if supporting.get("modality_sentence"):
            parts.append(supporting["modality_sentence"])

        return " ".join(parts)
