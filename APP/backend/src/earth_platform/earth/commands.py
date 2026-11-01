"""Typed instructions that make the globe react. Emitted by the agent / tools as
``earth.command`` events and applied by the frontend's Earth controller.

Commands are *presentation directives*; they never carry computed science. Evidence is
referenced by id and fetched from the Engine."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from earth_platform.shared.geo import BoundingBox, GeoJSONGeometry, LngLat, TimeRange


class FlyTo(BaseModel):
    type: Literal["fly_to"] = "fly_to"
    target: BoundingBox | LngLat
    height_m: float | None = None
    duration_s: float = 2.0


class SetTime(BaseModel):
    type: Literal["set_time"] = "set_time"
    instant: datetime | None = None
    range: TimeRange | None = None
    playback_speed: float | None = None  # None = paused


class SetLayerVisibility(BaseModel):
    type: Literal["set_layer_visibility"] = "set_layer_visibility"
    layer_id: str
    visible: bool
    opacity: float | None = Field(default=None, ge=0, le=1)


class AddOverlay(BaseModel):
    type: Literal["add_overlay"] = "add_overlay"
    overlay_id: str
    geometry: GeoJSONGeometry
    style: dict[str, str | float | bool] = Field(default_factory=dict)
    label: str | None = None
    evidence_id: str | None = None


class ClearOverlays(BaseModel):
    type: Literal["clear_overlays"] = "clear_overlays"
    overlay_ids: list[str] | None = None  # None = all


class HighlightEvidence(BaseModel):
    type: Literal["highlight_evidence"] = "highlight_evidence"
    evidence_ids: list[str]


class ShowInvestigation(BaseModel):
    type: Literal["show_investigation"] = "show_investigation"
    investigation_id: str
    area: GeoJSONGeometry | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    time_range: TimeRange | None = None


EarthCommand = Annotated[
    FlyTo
    | SetTime
    | SetLayerVisibility
    | AddOverlay
    | ClearOverlays
    | HighlightEvidence
    | ShowInvestigation,
    Field(discriminator="type"),
]
