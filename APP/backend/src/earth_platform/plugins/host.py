from typing import Literal, Protocol

from pydantic import BaseModel

from earth_platform.plugins.api import PluginManifest

PluginStatus = Literal["discovered", "loaded", "failed", "disabled"]


class PluginRecord(BaseModel):
    manifest: PluginManifest
    status: PluginStatus
    error: str | None = None


class PluginHost(Protocol):
    """Discovers plugins (entry points + ``settings.plugins.search_paths``), validates
    ``api_version`` compatibility, provides each a scoped ``PluginContext`` and tracks state. A
    failing plugin is isolated: it is marked ``failed`` and never prevents startup."""

    async def discover(self) -> list[PluginManifest]: ...

    async def load_all(self) -> None: ...

    async def unload(self, plugin_id: str) -> None: ...

    def records(self) -> list[PluginRecord]: ...

    async def aclose(self) -> None: ...
