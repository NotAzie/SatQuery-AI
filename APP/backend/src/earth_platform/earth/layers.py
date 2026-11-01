"""Declarative description of globe layers. The backend publishes *what* a layer is; the
frontend decides *how* to render it (a plugin may ship a custom frontend renderer for a
new ``kind``)."""

from typing import Any

from pydantic import BaseModel, Field

from earth_platform.shared.geo import TimeRange
from earth_platform.shared.registry import Registry


class LayerSpec(BaseModel):
    id: str
    title: str
    kind: str  # "imagery" | "terrain" | "geojson" | "3dtiles" | plugin-defined
    source: dict[str, Any]  # kind-specific connection details (url template, asset id, ...)
    default_visible: bool = False
    z_order: int = 0
    time_dynamic: bool = False
    available_time: TimeRange | None = None
    attribution: str | None = None
    style: dict[str, Any] = Field(default_factory=dict)


LayerRegistry = Registry[LayerSpec]
