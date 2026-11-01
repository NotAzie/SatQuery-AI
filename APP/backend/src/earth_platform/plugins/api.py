"""The plugin contract. Third parties import *only* this module (plus the types it re-exports).

A plugin is a Python distribution exposing an entry point in the ``earth_platform.plugins`` group
that resolves to a ``Plugin``. During ``register`` it may contribute LLM providers, tools, Earth
layers and UI panels; the host records ownership so everything is removed on unload.
"""

import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from earth_platform.agent.tools import ToolSource
from earth_platform.earth.layers import LayerSpec
from earth_platform.llm.provider import ProviderFactory
from earth_platform.shared.constants import PLUGIN_API_VERSION

Contribution = Literal["llm_provider", "tool_source", "ui_panel", "earth_layer"]
PanelSlot = Literal["left", "right", "bottom", "overlay", "settings"]


class PluginManifest(BaseModel):
    id: str  # globally unique, e.g. "acme.mining-watch"
    name: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    description: str | None = None
    provides: list[Contribution] = Field(default_factory=list)
    # URL (served by the backend) of an ES module implementing the frontend half, if any.
    frontend_entry: str | None = None


class PanelContribution(BaseModel):
    """Declares a UI panel; its component is exported by the plugin's ``frontend_entry`` module
    under ``component``."""

    id: str
    title: str
    slot: PanelSlot
    component: str
    order: int = 100
    icon: str | None = None


class PluginContext(Protocol):
    plugin_id: str
    config: dict[str, Any]  # settings.plugins.config[plugin_id]
    logger: logging.Logger

    def register_provider_factory(self, factory: ProviderFactory) -> None: ...
    def register_tool_source(self, source: ToolSource) -> None: ...
    def register_earth_layer(self, layer: LayerSpec) -> None: ...
    def register_ui_panel(self, panel: PanelContribution) -> None: ...


class Plugin(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    async def register(self, ctx: PluginContext) -> None: ...

    async def shutdown(self) -> None: ...
