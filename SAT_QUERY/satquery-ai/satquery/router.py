"""Query understanding and tool selection.

Routing is deterministic first. Most real questions about imagery are phrased
unambiguously - "where are the buildings", "how many ships", "describe this
scene" - and a keyword cascade answers them in microseconds with no API call
and no variance between runs, which matters when the same demo is run twice in
front of judges.

The planning LLM exists for the rest: compound questions, unusual phrasing,
and languages the rules do not cover. It is consulted only when the rules are
not confident, it never sees the image, and it never produces the answer. If
it is unavailable or returns nonsense, routing falls back to the rules.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .backends.llm import PlannerLLM
from .config import Settings
from .errors import QueryError
from .schemas import Intent, PlannedStep, QueryPlan, ToolName
from .taxonomy import TARGET_PHRASES
from .tools import INTENT_TO_TOOL

logger = logging.getLogger("satquery.router")

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

CHANGE_TERMS = (
    "change", "changed", "changes", "changing", "compare", "comparison", "compared",
    "difference between", "differences", "before and after", "before/after", "temporal",
    "bi-temporal", "bitemporal", "over time", "since", "grown", "growth", "expanded",
    "shrunk", "deforestation", "encroachment", "what happened", "evolved", "new since",
)

LOCATE_TERMS = (
    "where", "locate", "localise", "localize", "location of", "position of", "pinpoint",
    "show me where", "point out", "highlight", "mark", "which part", "which area",
    "whereabouts", "bounding box", "bounding boxes", "segment",
)

COUNT_TERMS = (
    "how many", "count", "number of", "quantity of", "tally", "total number",
)

SCENE_TERMS = (
    "land use", "landuse", "land cover", "landcover", "what type of scene",
    "what kind of scene", "what kind of area", "what type of area", "classify",
    "classification", "scene type", "categorise", "categorize", "what terrain",
    "what sort of place", "what is this area",
)

CAPTION_TERMS = (
    "describe", "description", "caption", "summarise", "summarize", "summary",
    "tell me about", "what do you see", "what is in this image", "what's in this image",
    "overview", "walk me through", "explain this image", "what does this show",
)

MODALITY_TERMS = (
    "optical or sar", "sar or optical", "what sensor", "which sensor", "sensor type",
    "is this radar", "is this sar", "is this optical", "what kind of image is this",
    "modality", "radar or optical", "image quality", "what instrument",
)

PRESENCE_STARTERS = (
    "is there", "are there", "is it", "are any", "any ", "does this", "do you see",
    "can you see", "does the image", "does it contain", "is the", "are the",
)


def _contains(text: str, terms: Tuple[str, ...]) -> List[str]:
    """Phrase containment with word boundaries on both sides."""
    hits: List[str] = []
    for term in terms:
        pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            hits.append(term)
    return hits


def normalise_query(query: str) -> str:
    lowered = query.lower()
    stripped = re.sub(r"[^a-z0-9\s/'-]", " ", lowered)
    return " ".join(stripped.split())


# ---------------------------------------------------------------------------
# Target extraction
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "any", "some", "this", "that", "these", "those", "in", "on", "at",
    "of", "is", "are", "there", "image", "images", "scene", "photo", "picture", "visible",
    "shown", "present", "located", "here", "it", "and", "or", "you", "see", "can", "do",
    "does", "did", "within", "inside", "area", "region", "satellite", "aerial",
}

_TARGET_PATTERNS = (
    r"(?:where\s+(?:is|are|can\s+i\s+find)\s+)(?:the\s+|any\s+|all\s+)?(.+?)(?:\s+in\s+|\s+on\s+|\s+located|\s+situated|$)",
    r"(?:locate|find|highlight|mark|point\s+out|show\s+me)\s+(?:the\s+|any\s+|all\s+)?(.+?)(?:\s+in\s+|\s+on\s+|$)",
    r"(?:how\s+many)\s+(.+?)(?:\s+are\s+|\s+is\s+|\s+can\s+|\s+in\s+|\s+on\s+|$)",
    r"(?:count|number\s+of|quantity\s+of)\s+(?:the\s+|all\s+)?(.+?)(?:\s+in\s+|\s+on\s+|$)",
    r"(?:are|is)\s+there\s+(?:any\s+|a\s+|an\s+|some\s+)?(.+?)(?:\s+in\s+|\s+on\s+|\s+visible|$)",
    r"(?:do(?:es)?\s+(?:this|the|it)\s+\w+\s+(?:contain|have|show))\s+(?:any\s+|a\s+|an\s+)?(.+?)$",
    r"(?:which\s+(?:part|area|region)\s+(?:of\s+\w+\s+)?(?:has|contains|shows))\s+(?:the\s+|any\s+)?(.+?)$",
)


def extract_target(query: str) -> Optional[str]:
    """Pull the object-of-interest noun phrase out of a query.

    Known vocabulary wins over pattern matching: if the query names something
    the taxonomy already has a good overhead phrasing for, use that, because
    the phrasing is what drives grounding quality. Patterns are the fallback
    for targets outside the vocabulary.
    """
    text = normalise_query(query)

    # Among known vocabulary, prefer whichever target the user named first.
    # "Locate the ships in the harbour" is a question about ships that happens
    # to mention a harbour; taking the longest match would answer the wrong
    # question. Ties at the same position go to the longer phrase, so "storage
    # tank" beats a bare "tank".
    matches: List[Tuple[int, int, str]] = []
    for name in TARGET_PHRASES:
        found = re.search(r"(?<![a-z])" + re.escape(name) + r"(e?s)?(?![a-z])", text)
        if found:
            matches.append((found.start(), -len(name), name))
    if matches:
        matches.sort()
        return matches[0][2]

    for pattern in _TARGET_PATTERNS:
        match = re.search(pattern, text)
        if not match:
            continue
        candidate = match.group(1).strip()
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,'-")
        words = [word for word in candidate.split() if word not in _STOPWORDS]
        if not words:
            continue
        # Keep it to a short noun phrase; long tails are usually trailing clauses.
        return " ".join(words[:3])

    return None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class QueryRouter:
    """Chooses the capability for a query."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._planner = PlannerLLM(settings) if settings.llm_available else None
        self._planner_cache: OrderedDict[
            Tuple[str, int, str, str], Tuple[Intent, float, str]
        ] = OrderedDict()
        self._planner_cache_limit = min(max(settings.cache_size, 1), 256)

    # -- Public -----------------------------------------------------------

    def route(
        self,
        query: str,
        *,
        image_count: int,
        force_tool: Optional[ToolName] = None,
    ) -> QueryPlan:
        if not query.strip():
            raise QueryError(
                "The query is empty.",
                remediation=["Ask something about the image, for example 'describe this scene'."],
            )

        if force_tool is not None:
            intent = next(
                (candidate for candidate, tool in INTENT_TO_TOOL.items() if tool is force_tool),
                Intent.VQA,
            )
            return QueryPlan(
                intent=intent,
                steps=[
                    PlannedStep(
                        tool=force_tool,
                        reason="The caller pinned this tool explicitly.",
                        arguments=self._arguments_for(force_tool, query),
                    )
                ],
                router="forced",
                rationale=f"force_tool={force_tool.value} was supplied, bypassing routing.",
                target=extract_target(query),
                confidence=1.0,
            )

        intent, confidence, rationale = self._rule_route(query, image_count)

        mode = self.settings.router_mode
        should_consult = mode == "llm" or (mode == "hybrid" and confidence < 0.6)
        if should_consult and self._planner is not None:
            planned = self._llm_route(query, image_count)
            if planned is not None:
                intent, confidence, rationale = planned
                return self._build_plan(
                    intent, query, image_count, confidence, rationale, router="llm"
                )

        return self._build_plan(
            intent, query, image_count, confidence, rationale, router="rules"
        )

    # -- Rule cascade ------------------------------------------------------

    def _rule_route(self, query: str, image_count: int) -> Tuple[Intent, float, str]:
        text = normalise_query(query)

        change_hits = _contains(text, CHANGE_TERMS)
        modality_hits = _contains(text, MODALITY_TERMS)
        count_hits = _contains(text, COUNT_TERMS)
        locate_hits = _contains(text, LOCATE_TERMS)
        scene_hits = _contains(text, SCENE_TERMS)
        caption_hits = _contains(text, CAPTION_TERMS)

        # Two images plus comparison language is unambiguous.
        if change_hits and image_count >= 2:
            return (
                Intent.CHANGE_DETECTION,
                0.95,
                f"Comparison wording ({change_hits[0]}) with {image_count} images supplied.",
            )
        if change_hits:
            return (
                Intent.CHANGE_DETECTION,
                0.8,
                f"Comparison wording ({change_hits[0]}); change detection needs a second epoch.",
            )

        if modality_hits:
            return (
                Intent.MODALITY_ANALYSIS,
                0.9,
                f"The query asks about the sensor or acquisition type ({modality_hits[0]}).",
            )

        # Counting outranks locating: "how many buildings and where" is
        # answered by the counting tool, which grounds internally anyway.
        if count_hits:
            return (
                Intent.COUNTING,
                0.92,
                f"Quantity wording ({count_hits[0]}).",
            )

        if locate_hits:
            target = extract_target(query)
            if target:
                return (
                    Intent.GROUNDING,
                    0.92,
                    f"Spatial wording ({locate_hits[0]}) with target '{target}'.",
                )
            return (
                Intent.GROUNDING,
                0.55,
                f"Spatial wording ({locate_hits[0]}) but no target noun was extracted.",
            )

        if scene_hits:
            return (
                Intent.SCENE_CLASSIFICATION,
                0.9,
                f"Land-use or classification wording ({scene_hits[0]}).",
            )

        if caption_hits:
            return (
                Intent.CAPTION,
                0.9,
                f"Description wording ({caption_hits[0]}).",
            )

        if text.startswith(PRESENCE_STARTERS):
            target = extract_target(query)
            if target:
                return (
                    Intent.PRESENCE,
                    0.85,
                    f"Yes/no phrasing about '{target}'.",
                )
            return (
                Intent.PRESENCE,
                0.55,
                "Yes/no phrasing, but the subject could not be isolated.",
            )

        if len(text.split()) <= 2:
            return (
                Intent.CAPTION,
                0.5,
                "The query is too short to carry an intent; defaulting to a scene description.",
            )

        return (
            Intent.VQA,
            0.45,
            "No capability keyword matched, so this is treated as an open visual question.",
        )

    # -- LLM planning ------------------------------------------------------

    def _llm_route(
        self, query: str, image_count: int
    ) -> Optional[Tuple[Intent, float, str]]:
        assert self._planner is not None
        cache_key = (
            normalise_query(query),
            image_count,
            self.settings.router_mode,
            self.settings.llm_model,
        )
        cached = self._planner_cache.get(cache_key)
        if cached is not None:
            self._planner_cache.move_to_end(cache_key)
            return cached
        try:
            plan = self._planner.plan(query, image_count=image_count)
        except Exception as exc:
            logger.warning("Planner raised %s; using rule routing.", exc)
            return None
        if not plan:
            return None

        raw_intent = str(plan.get("intent", "")).strip().upper()
        try:
            intent = Intent(raw_intent)
        except ValueError:
            logger.warning("Planner returned unknown intent %r; using rule routing.", raw_intent)
            return None

        # The planner cannot conjure a second epoch that was not uploaded.
        if intent is Intent.CHANGE_DETECTION and image_count < 2:
            return (
                intent,
                0.7,
                "The planner read this as a comparison, but only one image was supplied.",
            )

        try:
            confidence = float(plan.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = max(0.0, min(confidence, 1.0))

        rationale = str(plan.get("rationale") or "Routed by the planning LLM.").strip()
        result = intent, confidence, rationale
        self._planner_cache[cache_key] = result
        self._planner_cache.move_to_end(cache_key)
        while len(self._planner_cache) > self._planner_cache_limit:
            self._planner_cache.popitem(last=False)
        return result

    # -- Plan assembly -----------------------------------------------------

    def _build_plan(
        self,
        intent: Intent,
        query: str,
        image_count: int,
        confidence: float,
        rationale: str,
        *,
        router: str,
    ) -> QueryPlan:
        target = extract_target(query)
        tool = INTENT_TO_TOOL[intent]

        steps = [
            PlannedStep(
                tool=tool,
                reason=rationale,
                arguments=self._arguments_for(tool, query, target=target),
            )
        ]

        return QueryPlan(
            intent=intent,
            steps=steps,
            router=router,
            rationale=rationale,
            target=target,
            confidence=confidence,
        )

    @staticmethod
    def _arguments_for(
        tool: ToolName, query: str, *, target: Optional[str] = None
    ) -> Dict[str, object]:
        resolved = target if target is not None else extract_target(query)
        if tool in {ToolName.GROUNDING, ToolName.COUNTING}:
            return {"target": resolved} if resolved else {}
        if tool is ToolName.VQA:
            arguments: Dict[str, object] = {"question": query}
            if resolved:
                arguments["target"] = resolved
            return arguments
        return {}
