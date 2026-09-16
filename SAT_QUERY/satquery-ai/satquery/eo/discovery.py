"""Provider-neutral STAC discovery primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class DiscoveryQuery:
    bbox: Optional[Tuple[float, float, float, float]] = None
    intersects: Optional[Dict[str, Any]] = None
    start: Optional[str] = None
    end: Optional[str] = None
    collections: Tuple[str, ...] = ()
    sensor: Optional[str] = None
    platform: Optional[str] = None
    modality: Optional[str] = None
    max_cloud_cover: Optional[float] = None
    limit: int = 100


@dataclass(frozen=True)
class ImageryCandidate:
    item_id: str
    provider: str
    collection: Optional[str]
    datetime: Optional[str]
    geometry: Optional[Dict[str, Any]]
    bbox: Optional[Tuple[float, ...]]
    assets: Dict[str, Dict[str, Any]]
    properties: Dict[str, Any] = field(default_factory=dict)
    state: str = "DISCOVERED"

    @property
    def is_downloaded(self) -> bool:
        return self.state in {"DOWNLOADED", "ANALYZED"}


def _candidate(item: Any, provider: str) -> ImageryCandidate:
    assets = {
        key: {"href": asset.href, "title": asset.title, "media_type": asset.media_type, "roles": asset.roles}
        for key, asset in item.assets.items()
    }
    return ImageryCandidate(
        item_id=item.id,
        provider=provider,
        collection=item.collection_id,
        datetime=item.datetime.isoformat() if item.datetime else None,
        geometry=item.geometry,
        bbox=tuple(item.bbox) if item.bbox else None,
        assets=assets,
        properties=dict(item.properties),
    )


class StacDiscoveryProvider:
    """STAC API adapter; search returns metadata and asset links only."""

    def __init__(self, url: str, *, provider_name: Optional[str] = None, modifier: Any = None) -> None:
        self.url = url
        self.provider_name = provider_name or url
        self.modifier = modifier

    def search(self, query: DiscoveryQuery) -> list[ImageryCandidate]:
        try:
            import pystac_client
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("pystac-client is required for STAC discovery. Install satquery-ai[eo].") from exc
        client = pystac_client.Client.open(self.url, modifier=self.modifier)
        search = client.search(
            bbox=query.bbox,
            intersects=query.intersects,
            datetime=f"{query.start or '..'}/{query.end or '..'}" if query.start or query.end else None,
            collections=list(query.collections) or None,
            max_items=query.limit,
        )
        candidates = [_candidate(item, self.provider_name) for item in search.items()]
        return self._filter_and_rank(candidates, query)

    @staticmethod
    def _filter_and_rank(candidates: Sequence[ImageryCandidate], query: DiscoveryQuery) -> list[ImageryCandidate]:
        def score(candidate: ImageryCandidate) -> float:
            props = candidate.properties
            cloud = props.get("eo:cloud_cover")
            value = 0.0
            if query.sensor and str(props.get("instruments", "")).lower().find(query.sensor.lower()) >= 0:
                value += 2.0
            if query.platform and str(props.get("platform", "")).lower() == query.platform.lower():
                value += 2.0
            if query.modality and str(props.get("sar:instrument_mode", "") or props.get("eo:bands", "")).lower().find(query.modality.lower()) >= 0:
                value += 1.0
            if cloud is not None and query.max_cloud_cover is not None and float(cloud) <= query.max_cloud_cover:
                value += 2.0
            if cloud is not None:
                value -= float(cloud) / 100.0
            return value

        filtered = [
            item for item in candidates
            if query.max_cloud_cover is None
            or item.properties.get("eo:cloud_cover") is None
            or float(item.properties["eo:cloud_cover"]) <= query.max_cloud_cover
        ]
        return sorted(filtered, key=score, reverse=True)
