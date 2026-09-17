"""Deterministic imagery discovery tool; returns metadata, not downloads."""

from __future__ import annotations

import re
import time
from typing import Any

from ..eo.discovery import DiscoveryQuery, StacDiscoveryProvider
from ..schemas import BackendKind, ToolName
from .base import Tool, ToolContext


class DiscoverImageryTool(Tool):
    name = ToolName.DISCOVER_IMAGERY
    description = "Searches a configured STAC API and returns ranked imagery candidates without downloading them."
    min_images = 0
    max_images = 0

    def run(self, context: ToolContext):
        started = time.perf_counter()
        url = str(context.arguments.get("stac_url") or context.settings.extras.get("stac_url") or "https://planetarycomputer.microsoft.com/api/stac/v1")
        bbox = context.arguments.get("bbox")
        collections = tuple(context.arguments.get("collections") or ("sentinel-2-l2a",))
        provider = StacDiscoveryProvider(url)
        query = DiscoveryQuery(
            bbox=tuple(bbox) if bbox else None,
            start=context.arguments.get("start"),
            end=context.arguments.get("end"),
            collections=collections,
            max_cloud_cover=context.arguments.get("max_cloud_cover"),
            limit=int(context.arguments.get("limit", 10)),
        )
        candidates = provider.search(query)
        data = {
            "provider": url,
            "state_semantics": {"discovered": "metadata and asset links only", "downloaded": "not performed", "analyzed": "not performed"},
            "query": query.__dict__,
            "candidates": [candidate.__dict__ for candidate in candidates],
        }
        return self.result(summary=f"Discovered {len(candidates)} imagery candidate(s); no assets were downloaded.", started=started, backend=BackendKind.NONE, data=data, confidence=1.0)
