from __future__ import annotations

from satquery.config import Settings
from satquery.schemas import ToolName
from satquery.tools.discovery import DiscoverImageryTool
from satquery.tools.base import ResultCache, ToolContext
from satquery.vision import Detector


def test_discovery_tool_returns_provider_metadata_without_images(monkeypatch):
    from satquery.eo.discovery import ImageryCandidate

    candidate = ImageryCandidate("item-1", "test", "sentinel-2", "2026-09-16T00:00:00Z", None, None, {"B04": {"href": "https://example/B04.tif"}})

    def fake_search(self, query):
        return [candidate]

    monkeypatch.setattr("satquery.tools.discovery.StacDiscoveryProvider.search", fake_search)
    context = ToolContext(query="find satellite imagery", images=[], settings=Settings(router_mode="rules"), vision=None, cache=ResultCache(0), arguments={})  # type: ignore[arg-type]
    result = DiscoverImageryTool().run(context)

    assert result.tool is ToolName.DISCOVER_IMAGERY
    assert result.data["candidates"][0]["state"] == "DISCOVERED"
    assert result.data["state_semantics"]["downloaded"] == "not performed"
