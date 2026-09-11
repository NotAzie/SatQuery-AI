"""The SatQuery capability catalog and task-to-capability routes."""

from __future__ import annotations

from langchain.tools import Tool

from .placeholders import get_placeholder_capabilities

TASK_TO_CAPABILITY = {
    "Super_Resolution": "super_resolution_2x", "Denoising": "denoising", "Captioning": "caption",
    "Optical_Detection": "optical_detection", "Optical_Plane_Type": "optical_plane_type",
    "Scene_Classification": "scene", "SAR_Detection": "sar_detection", "SAR_Plane_Type": "sar_plane_type",
    "Knowledge_Search": "knowledge_search", "Building_Damage_Detection": "building_damage_detection",
    "Building_Extraction": "building_extraction", "Road_Extraction": "road_extraction",
    "Horizontal_Object_Detection": "horizontal_object_detection", "Rotated_Object_Detection": "rotated_object_detection",
    "Semantic_Segmentation": "semantic_segmentation", "Land_Use_Classification": "land_use_classification",
    "Image_Dehazing": "image_dehazing", "Cloud_Removal": "cloud_removal",
    "Visual_Question_Answering": "visual_question_answering", "Grounding": "grounding",
}


def get_capabilities() -> list[Tool]:
    return get_placeholder_capabilities()