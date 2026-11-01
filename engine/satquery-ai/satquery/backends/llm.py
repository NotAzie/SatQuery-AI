"""Optional planning LLM.

The deterministic router handles clear queries. When a query is ambiguous -
compound, unusually phrased, or in a language the keyword rules do not cover -
an LLM is asked to pick the capability and extract the target noun.

The LLM never answers the user's question. It only produces a plan. Keeping it
out of the answer path is what stops the system from quietly turning into a
text model that talks about satellites without looking at one.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..errors import DependencyMissingError, ResourceNotConfiguredError

logger = logging.getLogger("satquery.backends.llm")

PLANNER_SYSTEM_PROMPT = """You route natural-language questions about satellite and aerial imagery to exactly one analysis capability.

Capabilities:
- CAPTION: the user wants a description or summary of the whole scene.
- VQA: an open question about the image that is not one of the other cases.
- SCENE_CLASSIFICATION: the user wants the land-use or scene category.
- GROUNDING: the user wants to know WHERE something is, or wants it localised.
- COUNTING: the user wants a quantity or count of some object.
- PRESENCE: a yes/no question about whether something appears in the image.
- CHANGE_DETECTION: the user is comparing two images or asking what changed.
- MODALITY_ANALYSIS: the user asks about the sensor type, whether it is optical or radar, or about image quality.

Reply with a single JSON object and nothing else:
{"intent": "<one capability>", "target": "<the object or category in question, lowercase, or null>", "rationale": "<one short sentence>", "confidence": <0.0 to 1.0>}

The "target" matters for GROUNDING, COUNTING, and PRESENCE. Use null elsewhere."""


class PlannerLLM:
    """Thin OpenAI-compatible chat client used only for routing."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def available(self) -> bool:
        return self.settings.llm_available

    def plan(self, query: str, *, image_count: int) -> Optional[Dict[str, Any]]:
        """Ask the LLM for a routing decision.

        Returns `None` on any failure. Routing must never be the thing that
        breaks a request, so a planner outage degrades to the deterministic
        rules rather than surfacing an error.
        """
        if not self.settings.llm_available:
            raise ResourceNotConfiguredError(
                "The planning LLM was requested but no API key is configured.",
                remediation=[
                    "Set OPENAI_API_KEY or SATQUERY_LLM_API_KEY.",
                    "Or set SATQUERY_ROUTER=rules to route deterministically.",
                ],
            )

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx ships with fastapi
            raise DependencyMissingError.for_package(
                "httpx", "calling the planning LLM", "pip install httpx"
            ) from exc

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Images supplied: {image_count}\n"
                        f"Question: {query}"
                    ),
                },
            ],
            "temperature": 0.0,
            "max_tokens": 200,
        }

        try:
            response = httpx.post(
                f"{self.settings.llm_base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.settings.llm_timeout_s,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("Planning LLM call failed (%s); falling back to rule routing.", exc)
            return None

        parsed = _extract_json(content)
        if parsed is None:
            logger.warning("Planning LLM returned unparseable content; using rule routing.")
            return None
        return parsed


def _extract_json(content: str) -> Optional[Dict[str, Any]]:
    """Pull a JSON object out of a model reply that may be fenced or chatty."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        braced = re.search(r"\{.*\}", text, re.DOTALL)
        if braced:
            text = braced.group(0)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
