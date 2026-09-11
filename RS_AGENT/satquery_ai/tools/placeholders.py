"""Capability adapters, including the first real image model integration."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from langchain.tools import Tool

from satquery_ai.knowledge import search_knowledge
from satquery_ai.vision import geochat_caption, geochat_grounding, geochat_scene, geochat_vqa


def _placeholder(message: str):
    def run(*_args: object, **_kwargs: object) -> str:
        return message
    return run


_caption_processor = None
_caption_model = None
_caption_lock = Lock()


def _caption(image_path: str) -> str:
    """Generate a caption from the supplied image using a lazy BLIP pipeline."""
    if os.getenv("GEOCHAT_SOURCE_PATH") and os.getenv("GEOCHAT_MODEL_PATH"):
        return geochat_caption(image_path)
    global _caption_model, _caption_processor
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    if _caption_model is None or _caption_processor is None:
        with _caption_lock:
            if _caption_model is None or _caption_processor is None:
                try:
                    from transformers import BlipForConditionalGeneration, BlipProcessor
                except ImportError as exc:
                    raise RuntimeError(
                        "Captioning requires the optional vision dependencies. "
                        "Install the project with the vision extra."
                    ) from exc
                _caption_processor = BlipProcessor.from_pretrained(
                    "Salesforce/blip-image-captioning-base"
                )
                _caption_model = BlipForConditionalGeneration.from_pretrained(
                    "Salesforce/blip-image-captioning-base"
                )

    from PIL import Image
    import torch

    image = Image.open(path).convert("RGB")
    inputs = _caption_processor(images=image, return_tensors="pt")
    with torch.no_grad():
        output_ids = _caption_model.generate(**inputs, max_new_tokens=40)
    caption = _caption_processor.decode(output_ids[0], skip_special_tokens=True).strip()
    if not caption:
        raise RuntimeError(f"Captioning produced no text for {path}")
    return caption


CAPABILITIES = [
    ("super_resolution_2x", "The image has been super-resolutioned.", "Upscale an image."),
    ("denoising", "The image has been denoised.", "Remove noise from an image."),
    ("caption", "", "Describe an image using the image content."),
    ("optical_detection", "The detection on this optical image has done.", "Detect optical targets."),
    ("optical_plane_type", "The plane type in this optical image is Boeing 747.", "Identify an aircraft type."),
    ("scene", "The scene of this image is airport.", "Classify the scene."),
    ("sar_detection", "The detection on this SAR image has done.", "Detect SAR targets."),
    ("sar_plane_type", "The plane type in this SAR image is Boeing 747.", "Identify a SAR aircraft type."),
    ("knowledge_search", "", "Search the optional knowledge service."),
    ("building_damage_detection", "The building damage detection on this image has done.", "Assess building damage."),
    ("building_extraction", "The buildings in this image have been extracted.", "Extract buildings."),
    ("road_extraction", "The roads in this image have been extracted.", "Extract roads."),
    ("horizontal_object_detection", "The horizontal object detection on this image has done.", "Detect horizontal objects."),
    ("rotated_object_detection", "The rotated object detection on this image has done.", "Detect rotated objects."),
    ("semantic_segmentation", "The semantic segmentation on this image has done.", "Segment image regions."),
    ("land_use_classification", "The land use classification on this image has done.", "Classify land use."),
    ("image_dehazing", "The haze in this image has been removed.", "Remove haze."),
    ("cloud_removal", "The cloud in this image has been removed.", "Remove clouds."),
    ("visual_question_answering", "", "Answer a question about an image using remote-sensing vision."),
    ("grounding", "", "Describe objects and their regions in an image."),
]


def _vision_question_input(payload: str) -> tuple[str, str | None]:
    image_path, separator, question = payload.partition("\nQuestion: ")
    return image_path, question if separator else None


def _vqa(payload: str) -> str:
    image_path, question = _vision_question_input(payload)
    return geochat_vqa(image_path, question)


def _grounding(payload: str) -> str:
    image_path, question = _vision_question_input(payload)
    return geochat_grounding(image_path, question)


def get_placeholder_capabilities() -> list[Tool]:
    tools = []
    for name, message, description in CAPABILITIES:
        if name == "knowledge_search":
            function = search_knowledge
        elif name == "caption":
            function = _caption
        elif name == "scene":
            function = geochat_scene
        elif name == "visual_question_answering":
            function = _vqa
        elif name == "grounding":
            function = _grounding
        else:
            function = _placeholder(message)
        tools.append(Tool(name=name, func=function, description=description))
    return tools