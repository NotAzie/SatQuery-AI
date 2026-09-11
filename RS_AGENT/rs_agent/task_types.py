"""Shared task-type parsing used by planning, retrieval, and evaluation."""

from __future__ import annotations

import re


def normalize_task_type(value: str) -> str:
    """Return a canonical task label from an LLM or benchmark value."""
    match = re.search(r"\[\s*['\"]?([^\]'\"]+)['\"]?\s*\]", value)
    label = match.group(1) if match else value
    normalized = re.sub(r"\s+", "_", label.strip().strip("'\""))
    aliases = {
        "Land_Use_Segmentation": "Landuse_Segmentation",
        "Image_Captioning": "Image_Caption",
    }
    return aliases.get(normalized, normalized)


def match_task_type(value: str, allowed: list[str]) -> str | None:
    """Match a model response to an allowed label without accepting near misses."""
    normalized = normalize_task_type(value)
    return {task.casefold(): task for task in allowed}.get(normalized.casefold())
