"""Object presence and approximate counting.

This is the capability most easily faked, so it is worth being precise about
what it does. CLIP window scoring gives semantic regions, not instances. Two
ships moored side by side produce one region, not two.

The tool therefore reports three things and lets the user judge:

* a region count, which is a firm lower bound on how many distinct areas
  contain the target,
* an area-based estimate that divides the responding area by the typical
  region size, which approximates instance count for repetitive objects,
* the VQA model's own numeric answer where it gives one.

When those signals disagree, the disagreement is the finding.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

import numpy as np

from ..errors import QueryError
from ..schemas import BackendKind, ToolName, ToolResult
from .base import Tool, ToolContext

NUMBER_WORDS = {
    "zero": 0, "no": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "many": -1, "several": -1, "few": -1,
}


class CountingTool(Tool):
    name = ToolName.COUNTING
    description = (
        "Estimates how many instances of a target appear, from grounded regions plus a "
        "VQA numeric answer, and reports the uncertainty between them."
    )
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        target = (context.target or context.arguments.get("target") or "").strip()
        if not target:
            raise QueryError(
                "Counting needs to know what to count.",
                remediation=['Name the object, for example "how many ships are in the harbour".'],
            )

        grounding = context.run_tool(ToolName.GROUNDING, target=target)
        regions = grounding.regions
        region_count = len(regions)
        present = bool(grounding.data.get("present"))

        responding_area = float(sum(region.area_fraction for region in regions))
        area_estimate: Optional[int] = None
        if regions:
            median_area = float(np.median([region.area_fraction for region in regions]))
            if median_area > 1e-6:
                area_estimate = int(round(responding_area / median_area))

        vqa_count: Optional[int] = None
        vqa_answer: Optional[str] = None
        try:
            vqa = context.run_tool(
                ToolName.VQA, question=f"How many {target} are visible in this image?"
            )
            vqa_answer = str(vqa.data.get("raw_answer", "")).strip()
            vqa_count = self._parse_count(vqa_answer)
        except Exception as exc:
            context.warn(
                f"The VQA cross-check for counting did not run ({exc.__class__.__name__}); "
                "the estimate rests on grounded regions alone."
            )

        summary = self._compose(
            target=target,
            present=present,
            region_count=region_count,
            area_estimate=area_estimate,
            responding_area=responding_area,
            vqa_count=vqa_count,
            vqa_answer=vqa_answer,
            peak=float(grounding.data.get("peak_response", 0.0)),
        )

        confidence = grounding.confidence
        if vqa_count is not None and vqa_count >= 0 and region_count:
            # Close agreement between two independent estimators is the only
            # thing that should raise confidence on a count.
            spread = abs(vqa_count - region_count) / max(vqa_count, region_count, 1)
            confidence = float(np.clip((1.0 - spread) * (confidence or 0.5), 0.0, 1.0))

        return self.result(
            summary=summary,
            started=started,
            backend=grounding.backend,
            model=grounding.model,
            data={
                "target": target,
                "present": present,
                "region_count": region_count,
                "area_based_estimate": area_estimate,
                "responding_area_fraction": round(responding_area, 5),
                "vqa_numeric_answer": vqa_count,
                "vqa_raw_answer": vqa_answer,
                "peak_response": grounding.data.get("peak_response"),
                "granularity": "regions, not verified object instances",
            },
            regions=regions,
            confidence=round(confidence, 4) if confidence is not None else None,
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_count(answer: Optional[str]) -> Optional[int]:
        if not answer:
            return None
        text = answer.strip().lower()
        digits = re.search(r"\b(\d{1,4})\b", text)
        if digits:
            return int(digits.group(1))
        for word, value in NUMBER_WORDS.items():
            if re.search(rf"\b{word}\b", text):
                return value
        return None

    @staticmethod
    def _compose(
        *,
        target: str,
        present: bool,
        region_count: int,
        area_estimate: Optional[int],
        responding_area: float,
        vqa_count: Optional[int],
        vqa_answer: Optional[str],
        peak: float,
    ) -> str:
        if not present or region_count == 0:
            base = (
                f"No {target} could be localised in this scene. The strongest window response "
                f"was {peak:.2f}, below the level that marks a confident detection."
            )
            if vqa_count is not None and vqa_count > 0:
                base += (
                    f" The VQA model answered '{vqa_answer}', which the spatial evidence does "
                    f"not support - treat that as a language-prior guess rather than an "
                    f"observation."
                )
            return base

        parts = [
            f"{region_count} distinct region{'s' if region_count != 1 else ''} of this scene "
            f"read as {target}, covering {responding_area * 100:.1f}% of the frame at a peak "
            f"response of {peak:.2f}."
        ]

        if area_estimate is not None and area_estimate != region_count:
            parts.append(
                f"Scaling the responding area by the median region size suggests roughly "
                f"{area_estimate} instance{'s' if area_estimate != 1 else ''}."
            )

        if vqa_count is not None:
            if vqa_count < 0:
                parts.append(
                    f"The VQA model answered '{vqa_answer}' without committing to a number."
                )
            elif vqa_count == region_count:
                parts.append(
                    f"The VQA model independently answered {vqa_count}, matching the region count."
                )
            else:
                parts.append(
                    f"The VQA model answered {vqa_count}, which differs from the "
                    f"{region_count} region{'s' if region_count != 1 else ''} found. The true "
                    f"count most likely sits between the two."
                )

        parts.append(
            f"Treat {region_count} as a lower bound: CLIP window scoring separates areas, not "
            f"individual objects, so adjacent instances merge into one region. For a verified "
            f"count you would want a detector trained on this object class at this resolution."
        )
        return " ".join(parts)
