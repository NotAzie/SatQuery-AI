"""Optical / SAR modality analysis.

Two independent signals are combined: the pixel-statistics heuristic in
`satquery.imaging` (chromaticity, speckle, histogram skew) and, when an
embedding backend is available, a CLIP probe that scores the image against
descriptions of each modality. Agreement raises confidence; disagreement is
reported rather than hidden.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np

from ..backends.base import softmax
from ..imaging import dominant_colour_terms, texture_summary
from ..schemas import BackendKind, Modality, ScoredLabel, ToolName, ToolResult
from .base import Tool, ToolContext

MODALITY_PROBES = {
    Modality.OPTICAL: (
        "a colour optical satellite photograph of the ground",
        "a natural colour aerial photograph",
        "a multispectral satellite image with visible colours",
    ),
    Modality.SAR: (
        "a grayscale synthetic aperture radar image with speckle noise",
        "a SAR radar backscatter image of terrain",
        "a noisy black and white radar image from a satellite",
    ),
}


class ModalityTool(Tool):
    name = ToolName.MODALITY
    description = (
        "Determines whether imagery is passive optical or synthetic aperture radar, and "
        "reports the texture and contrast characteristics that led to that call."
    )
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        image = context.primary

        evidence: Dict[str, Any] = dict(image.modality_evidence)
        heuristic_modality = Modality(evidence.get("heuristic_modality", image.modality.value))
        probe_labels: List[ScoredLabel] = []
        backend = BackendKind.NONE
        model_name = None

        # The CLIP probe is a nice-to-have; the heuristic already answers the
        # question, so a missing embedding backend degrades rather than fails.
        if context.vision.has_embedder:
            try:
                embedder = context.vision.embedder
                phrases: List[str] = []
                owners: List[Modality] = []
                for modality, prompts in MODALITY_PROBES.items():
                    for prompt in prompts:
                        phrases.append(prompt)
                        owners.append(modality)

                similarity = embedder.similarity([image.pil], phrases)[0]
                scaled = similarity * embedder.logit_scale()
                probabilities = softmax(scaled)

                aggregated: Dict[Modality, float] = {}
                for modality, probability in zip(owners, probabilities):
                    aggregated[modality] = aggregated.get(modality, 0.0) + float(probability)

                total = sum(aggregated.values()) or 1.0
                for modality, value in sorted(
                    aggregated.items(), key=lambda item: item[1], reverse=True
                ):
                    probe_labels.append(
                        ScoredLabel(
                            label=modality.value,
                            score=round(float(value / total), 4),
                            group="clip_probe",
                        )
                    )
                evidence["clip_probe"] = {
                    item.label: item.score for item in probe_labels
                }
                backend = BackendKind.PRACTICAL
                model_name = embedder.name
            except Exception as exc:
                context.warn(
                    "The CLIP modality probe could not run, so this call rests on pixel "
                    f"statistics alone ({exc.__class__.__name__})."
                )

        texture = texture_summary(image.array)
        evidence["texture"] = texture

        colour_terms: List[str] = []
        if image.modality is not Modality.SAR:
            colour_terms = dominant_colour_terms(image.array)
            if colour_terms:
                evidence["dominant_tones"] = colour_terms

        agreement = None
        if probe_labels:
            probe_top = Modality(probe_labels[0].label)
            agreement = probe_top is heuristic_modality
            evidence["probe_agrees_with_heuristic"] = agreement

        conflict = agreement is False and not evidence.get("overridden_by_hint")
        if conflict:
            context.warn(
                "Modality evidence conflicts: the pixel heuristic and CLIP probe disagree. "
                "The acquisition type is marked UNKNOWN; do not interpret colour or sensor "
                "semantics as reliable without a known product label."
            )
            image.modality = Modality.UNKNOWN
            image.modality_confidence = 0.0

        summary = self._summarise(
            context=context,
            heuristic=heuristic_modality,
            evidence=evidence,
            texture=texture,
            colour_terms=colour_terms,
            probe_labels=probe_labels,
            agreement=agreement,
            conflict=conflict,
        )

        confidence = image.modality_confidence
        if agreement is True:
            confidence = float(min(1.0, confidence + 0.15))
        elif agreement is False:
            confidence = float(max(0.0, confidence - 0.2))
            context.warn(
                "The pixel heuristic and the CLIP probe disagree about acquisition modality. "
                "Pass an explicit modality hint if you know the sensor."
            )

        return self.result(
            summary=summary,
            started=started,
            backend=backend,
            model=model_name,
            data={
                "modality": image.modality.value,
                "heuristic_modality": heuristic_modality.value,
                "confidence": round(confidence, 4),
                "conflict": conflict,
                "evidence": evidence,
                "explicit_hint_applied": bool(evidence.get("overridden_by_hint")),
            },
            labels=probe_labels,
            confidence=round(confidence, 4),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _summarise(
        *,
        context: ToolContext,
        heuristic: Modality,
        evidence: Dict[str, Any],
        texture: Dict[str, float],
        colour_terms: List[str],
        probe_labels: List[ScoredLabel],
        agreement: Any,
        conflict: bool,
    ) -> str:
        image = context.primary
        parts: List[str] = []

        if evidence.get("overridden_by_hint"):
            parts.append(
                f"Modality is set to {image.modality.value} from the supplied hint. "
                f"Pixel statistics alone would have suggested {heuristic.value}."
            )
        elif image.modality is Modality.UNKNOWN:
            parts.append(
                "The acquisition modality is ambiguous from pixel statistics alone. The image "
                "sits between the optical and radar signatures."
            )
        else:
            parts.append(
                f"This reads as {image.modality.value} imagery "
                f"(confidence {image.modality_confidence:.2f})."
            )

        spread = evidence.get("mean_channel_spread")
        cv = evidence.get("median_local_coefficient_of_variation")
        skew = evidence.get("intensity_skew")
        if spread is not None and cv is not None:
            parts.append(
                f"Mean channel spread is {spread:.1f} of 255 - near zero means the three bands "
                f"carry the same values, which is what a single-band radar amplitude product "
                f"looks like in an RGB container. Median local coefficient of variation is "
                f"{cv:.3f}; radar speckle typically pushes this above 0.25, while optical "
                f"sensors stay smoother over homogeneous ground. Intensity skew is {skew:.2f}."
            )

        parts.append(
            f"Texture: mean intensity {texture['mean_intensity']:.0f}, standard deviation "
            f"{texture['intensity_std']:.0f}, mean gradient {texture['mean_gradient']:.2f}, "
            f"edge density {texture['edge_density']:.3f}."
        )

        if colour_terms:
            parts.append("Dominant tones: " + "; ".join(colour_terms) + ".")

        if probe_labels:
            leader = probe_labels[0]
            parts.append(
                f"An independent CLIP probe scores {leader.label} at {leader.score:.2f}, "
                + ("consistent with" if agreement else "against")
                + " the pixel statistics."
            )

        if conflict:
            parts.append(
                "The independent signals conflict, so this result is UNKNOWN rather than a "
                "sensor identification."
            )

        if image.modality is Modality.SAR or heuristic is Modality.SAR:
            parts.append(
                "Because this is radar, questions about colour have no answer here: SAR measures "
                "backscattered microwave energy, which depends on surface roughness and moisture, "
                "not on visible reflectance. Ask about structure, texture, or extent instead."
            )

        return " ".join(parts)
