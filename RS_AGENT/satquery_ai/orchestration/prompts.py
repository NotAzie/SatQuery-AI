"""Prompts used by SatQuery AI to understand a question."""

from __future__ import annotations

from satquery_ai.task_catalog import SATQUERY_TASKS

TASK_UNDERSTANDING_PROMPT = """
Given the question: "{question}", identify the most relevant SatQuery capability from the following list.
- Super_Resolution: Improve image resolution.
- Denoising: Remove image noise.
- Captioning: Describe the image.
- Optical_Detection: Detect or count targets in an optical image.
- Optical_Plane_Type: Identify a plane type in an optical image.
- Scene_Classification: Identify the scene shown in the image.
- SAR_Detection: Detect or count targets in a SAR image.
- SAR_Plane_Type: Identify a plane type in a SAR image.
- Knowledge_Search: Search information about an aircraft or remote-sensing topic.
- Building_Damage_Detection: Assess building damage.
- Building_Extraction: Extract buildings.
- Road_Extraction: Extract roads.
- Horizontal_Object_Detection: Detect horizontally aligned objects.
- Rotated_Object_Detection: Detect rotated objects.
- Semantic_Segmentation: Segment image regions.
- Land_Use_Classification: Classify land use or land cover.
- Image_Dehazing: Remove haze.
- Cloud_Removal: Remove clouds.
- Visual_Question_Answering: Answer a question about the image.
- Grounding: Describe objects and provide their image regions or locations.

Return exactly one label from the list, with no brackets, explanation, or other text.
"""

TASK_LABELS = SATQUERY_TASKS