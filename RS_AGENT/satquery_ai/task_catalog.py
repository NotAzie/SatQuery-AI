"""Task vocabulary and strict task-label matching."""

from __future__ import annotations

import re

SATQUERY_TASKS = [
    "Super_Resolution", "Denoising", "Captioning", "Optical_Detection",
    "Optical_Plane_Type", "Scene_Classification", "SAR_Detection", "SAR_Plane_Type",
    "Knowledge_Search", "Building_Damage_Detection", "Building_Extraction",
    "Road_Extraction", "Horizontal_Object_Detection", "Rotated_Object_Detection",
    "Semantic_Segmentation", "Land_Use_Classification", "Image_Dehazing", "Cloud_Removal",
    "Visual_Question_Answering", "Grounding",
]

COMPARISON_TASKS = [
    "Object_Counting", "Object_Detection", "Landuse_Segmentation", "Instance_Segmentation",
    "Edge_Detection", "Image_Caption", "Scene_Classification",
]


def normalize_task(value: str) -> str:
    """Return a canonical task label from model or evaluation text."""
    match = re.search(r"\[\s*['\"]?([^\]'\"]+)['\"]?\s*\]", value)
    label = match.group(1) if match else value
    normalized = re.sub(r"\s+", "_", label.strip().strip("'\""))
    aliases = {"Land_Use_Segmentation": "Landuse_Segmentation", "Image_Captioning": "Image_Caption"}
    return aliases.get(normalized, normalized)


def match_task(value: str, allowed: list[str]) -> str | None:
    """Accept only an exact task label from the supplied catalog."""
    normalized = normalize_task(value)
    return {task.casefold(): task for task in allowed}.get(normalized.casefold())