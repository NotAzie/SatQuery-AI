"""Request, response, and trace schemas for SatQuery AI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Modality(str, Enum):
    """Acquisition modality of the supplied imagery."""

    OPTICAL = "OPTICAL"
    SAR = "SAR"
    UNKNOWN = "UNKNOWN"


class Intent(str, Enum):
    """Capabilities the router can dispatch to."""

    CAPTION = "CAPTION"
    VQA = "VQA"
    SCENE_CLASSIFICATION = "SCENE_CLASSIFICATION"
    GROUNDING = "GROUNDING"
    COUNTING = "COUNTING"
    PRESENCE = "PRESENCE"
    CHANGE_DETECTION = "CHANGE_DETECTION"
    MODALITY_ANALYSIS = "MODALITY_ANALYSIS"
    EO_INSPECTION = "EO_INSPECTION"
    RASTER_STATISTICS = "RASTER_STATISTICS"
    SPECTRAL_INDEX = "SPECTRAL_INDEX"
    OBJECT_DETECTION = "OBJECT_DETECTION"
    SEGMENTATION = "SEGMENTATION"
    VISUAL_MEASUREMENT = "VISUAL_MEASUREMENT"


class ToolName(str, Enum):
    CAPTION = "caption"
    VQA = "vqa"
    SCENE = "scene_classification"
    GROUNDING = "grounding"
    COUNTING = "counting"
    CHANGE = "change_detection"
    MODALITY = "modality_analysis"
    EO_INSPECTION = "inspect_eo_data"
    RASTER_STATISTICS = "raster_statistics"
    SPECTRAL_INDEX = "calculate_spectral_index"
    DETECT_OBJECTS = "detect_objects"
    SEGMENT_REGION = "segment_region"
    MEASURE = "measure_visual_evidence"


class BackendKind(str, Enum):
    PRACTICAL = "practical"
    RSVLM = "rsvlm"
    MIXED = "mixed"
    NONE = "none"


class StepStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    CACHED = "cached"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """Axis-aligned box in both normalised and pixel coordinates."""

    model_config = ConfigDict(frozen=True)

    x0: float = Field(..., ge=0.0, le=1.0)
    y0: float = Field(..., ge=0.0, le=1.0)
    x1: float = Field(..., ge=0.0, le=1.0)
    y1: float = Field(..., ge=0.0, le=1.0)
    pixel_box: Tuple[int, int, int, int]

    @property
    def area_fraction(self) -> float:
        return max(self.x1 - self.x0, 0.0) * max(self.y1 - self.y0, 0.0)

    def as_list(self) -> List[float]:
        return [self.x0, self.y0, self.x1, self.y1]


class Region(BaseModel):
    """A localised area of interest returned by grounding or change detection."""

    model_config = ConfigDict(frozen=True)

    region_id: str
    label: str
    score: float = Field(..., ge=0.0, le=1.0)
    box: BoundingBox
    centroid: Tuple[float, float]
    area_fraction: float = Field(..., ge=0.0, le=1.0)
    placement: str = ""
    notes: str = ""


class ScoredLabel(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    score: float = Field(..., ge=0.0, le=1.0)
    group: Optional[str] = None


class ImageRef(BaseModel):
    """Everything the response needs to say about one input image."""

    model_config = ConfigDict(frozen=True)

    image_id: str
    filename: str
    source: str
    width: int
    height: int
    mode: str
    sha256: str
    size_bytes: int
    modality: Modality = Modality.UNKNOWN
    modality_confidence: float = 0.0
    resized_from: Optional[Tuple[int, int]] = None


class TraceStep(BaseModel):
    """One executed step in the orchestration path."""

    model_config = ConfigDict(frozen=True)

    step: str
    kind: str
    status: StepStatus
    latency_ms: float
    backend: Optional[str] = None
    model: Optional[str] = None
    detail: str = ""
    error: Optional[str] = None


class ToolResult(BaseModel):
    """Structured output of a specialist tool."""

    model_config = ConfigDict(frozen=True)

    tool: ToolName
    ok: bool
    summary: str
    latency_ms: float
    backend: BackendKind = BackendKind.NONE
    model: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    regions: List[Region] = Field(default_factory=list)
    labels: List[ScoredLabel] = Field(default_factory=list)
    confidence: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)


class PlannedStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: ToolName
    reason: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class QueryPlan(BaseModel):
    """What the router decided to do, and why."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    steps: List[PlannedStep]
    router: str
    rationale: str
    target: Optional[str] = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """JSON body for path-based queries (uploads use multipart instead)."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000)
    image_paths: List[str] = Field(default_factory=list, max_length=8)
    modality_hint: Optional[Modality] = None
    force_tool: Optional[ToolName] = None
    include_trace: bool = True

    @field_validator("query")
    @classmethod
    def _clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("query cannot be blank")
        return cleaned


class QueryResponse(BaseModel):
    """The answer, plus everything needed to audit how it was produced."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    timestamp_utc: str = Field(default_factory=utc_now_iso)
    query: str
    answer: str
    intent: Intent
    tools_used: List[ToolName]
    backend: BackendKind
    confidence: Optional[float] = None
    images: List[ImageRef]
    results: List[ToolResult]
    plan: QueryPlan
    trace: List[TraceStep] = Field(default_factory=list)
    latency_ms: float
    warnings: List[str] = Field(default_factory=list)


class CapabilityInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: ToolName
    intent: Intent
    description: str
    requires_images: int
    backend_preference: List[BackendKind]
    available: bool
    unavailable_reason: Optional[str] = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    app: str
    version: str
    owner: str
    problem_statement: str
    timestamp_utc: str = Field(default_factory=utc_now_iso)
    device: str
    backends: Dict[str, Any]
    dependencies: Dict[str, Any]
    ready: bool
    setup_actions: List[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: str
    detail: str
    remediation: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
