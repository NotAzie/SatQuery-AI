"""Specialist vision tools."""

from typing import Dict

from ..schemas import Intent, ToolName
from .base import ResultCache, Tool, ToolContext
from .caption import CaptionTool
from .change import ChangeDetectionTool
from .counting import CountingTool
from .grounding import GroundingTool
from .modality import ModalityTool
from .scene import SceneClassificationTool
from .vqa import VQATool
from .eo import EOInspectionTool, RasterStatisticsTool, SpectralIndexTool
from .vision import DetectObjectsTool, MeasureVisualEvidenceTool, SegmentRegionTool
from .discovery import DiscoverImageryTool
from .water import WaterAnalysisTool


def build_tools() -> Dict[ToolName, Tool]:
    """Instantiate every tool. Tools are stateless; models live in the registry."""
    tools = (
        CaptionTool(),
        VQATool(),
        SceneClassificationTool(),
        GroundingTool(),
        CountingTool(),
        ChangeDetectionTool(),
        ModalityTool(),
        EOInspectionTool(),
        RasterStatisticsTool(),
        SpectralIndexTool(),
        DetectObjectsTool(),
        SegmentRegionTool(),
        MeasureVisualEvidenceTool(),
        DiscoverImageryTool(),
        WaterAnalysisTool(),
    )
    return {tool.name: tool for tool in tools}


#: Which tool serves which intent.
INTENT_TO_TOOL: Dict[Intent, ToolName] = {
    Intent.CAPTION: ToolName.CAPTION,
    Intent.VQA: ToolName.VQA,
    Intent.SCENE_CLASSIFICATION: ToolName.SCENE,
    Intent.GROUNDING: ToolName.GROUNDING,
    Intent.COUNTING: ToolName.COUNTING,
    Intent.PRESENCE: ToolName.VQA,
    Intent.CHANGE_DETECTION: ToolName.CHANGE,
    Intent.MODALITY_ANALYSIS: ToolName.MODALITY,
    Intent.EO_INSPECTION: ToolName.EO_INSPECTION,
    Intent.RASTER_STATISTICS: ToolName.RASTER_STATISTICS,
    Intent.SPECTRAL_INDEX: ToolName.SPECTRAL_INDEX,
    Intent.OBJECT_DETECTION: ToolName.DETECT_OBJECTS,
    Intent.SEGMENTATION: ToolName.SEGMENT_REGION,
    Intent.VISUAL_MEASUREMENT: ToolName.MEASURE,
    Intent.IMAGERY_DISCOVERY: ToolName.DISCOVER_IMAGERY,
    Intent.WATER_ANALYSIS: ToolName.WATER_ANALYSIS,
}

__all__ = [
    "CaptionTool",
    "ChangeDetectionTool",
    "CountingTool",
    "GroundingTool",
    "ModalityTool",
    "ResultCache",
    "SceneClassificationTool",
    "Tool",
    "ToolContext",
    "VQATool",
    "EOInspectionTool",
    "RasterStatisticsTool",
    "SpectralIndexTool",
    "DetectObjectsTool",
    "SegmentRegionTool",
    "MeasureVisualEvidenceTool",
    "DiscoverImageryTool",
    "WaterAnalysisTool",
    "build_tools",
    "INTENT_TO_TOOL",
]
