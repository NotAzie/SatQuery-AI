"""NASA CMR collection and granule discovery as canonical observations."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import quote, urljoin, urlsplit

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from satquery.errors import (
    AuthenticationError,
    ConnectorError,
    NetworkError,
    RateLimitError,
    ValidationError,
)
from satquery.platform.connectors import ConnectorPolicy, PerceptionConnector
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    Observation,
    ObservationAsset,
    ObservationSearchResult,
    TemporalExtent,
)

_CMR_ROOT = "https://cmr.earthdata.nasa.gov/search/"


class NasaEarthdataSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: str = Field(default="nasa-earthdata", min_length=1)
    search_url: AnyHttpUrl = AnyHttpUrl(_CMR_ROOT)
    provider_id: Optional[str] = None
    short_names: tuple[str, ...] = ()
    collection_concept_ids: tuple[str, ...] = ()
    page_size: int = Field(default=100, ge=1, le=2000)
    authentication_required: bool = False

    def validate_settings(self) -> "NasaEarthdataSettings":
        if len(set(self.short_names)) != len(self.short_names):
            raise ValueError("short_names must be unique")
        if len(set(self.collection_concept_ids)) != len(self.collection_concept_ids):
            raise ValueError("collection_concept_ids must be unique")
        if any(not value.strip() for value in (*self.short_names, *self.collection_concept_ids)):
            raise ValueError("collection selectors must not be empty")
        url = urlsplit(str(self.search_url))
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("search_url must not contain credentials, query, or fragment")
        return self


class NasaEarthdataConnector(PerceptionConnector):
    """Access public CMR metadata and granule links; assets are never downloaded."""

    def __init__(
        self,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        policy: Optional[ConnectorPolicy] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        resolved_policy = policy or ConnectorPolicy(
            timeout_seconds=30,
            max_attempts=2,
            retry_safe=True,
            retry_delay_seconds=0.2,
        )
        super().__init__(configuration=configuration, policy=resolved_policy)
        try:
            self.settings = NasaEarthdataSettings.model_validate(
                dict(configuration or {})
            )
        except PydanticValidationError as exc:
            raise ValidationError(
                "Invalid NASA Earthdata connector configuration.",
                context={"errors": exc.errors(include_input=False, include_url=False)},
            ) from exc
        self.settings.validate_settings()
        self._transport = transport
        self._client = client
        self._owns_client = client is None
        self._token: Optional[str] = None

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.settings.connector_id,
            name="NASA Earthdata CMR",
            version="1",
            capabilities=("earth_observation_catalog", "observation_search", "item_assets"),
            authentication_schemes=("bearer",),
            authentication_required=self.settings.authentication_required,
            supports_temporal_query=True,
            supported_spatial_types=("bbox", "point"),
            supported_query_fields=("filters", "requested_dataset_ids"),
            datasets=tuple(
                DatasetReference(
                    connector_id=self.settings.connector_id,
                    dataset_id=concept_id,
                    uri=str(self.settings.search_url),
                )
                for concept_id in self.settings.collection_concept_ids
            ),
            provider_metadata={
                "provider": "NASA Earthdata",
                "protocol": "NASA Common Metadata Repository",
                "catalog_url": str(self.settings.search_url),
            },
            configuration_schema={
                "type": "object",
                "properties": {
                    "connector_id": {"type": "string"},
                    "search_url": {"type": "string", "format": "uri"},
                    "provider_id": {"type": "string"},
                    "short_names": {"type": "array", "items": {"type": "string"}},
                    "collection_concept_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 2000},
                    "authentication_required": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        )

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.policy.timeout_seconds,
                follow_redirects=True,
                transport=self._transport,
            )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
        self._token = None

    async def _authenticate(self, credentials: Mapping[str, str]) -> None:
        token = credentials.get("token")
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationError(
                "NASA Earthdata bearer authentication requires a non-empty token."
            )
        if urlsplit(str(self.settings.search_url)).scheme != "https":
            raise AuthenticationError(
                "NASA Earthdata credentials require an HTTPS CMR endpoint."
            )
        self._token = token

    async def discover(self) -> tuple[DatasetReference, ...]:
        params: dict[str, Any] = {"page_size": self.settings.page_size}
        if self.settings.provider_id:
            params["provider"] = self.settings.provider_id
        if self.settings.short_names:
            params["short_name"] = ",".join(self.settings.short_names)
        if self.settings.collection_concept_ids:
            params["concept_id"] = ",".join(self.settings.collection_concept_ids)
        entries, _, _ = await self._scroll_entries("collections.json", params)
        references: dict[str, DatasetReference] = {}
        for entry in entries:
            concept_id = entry.get("id")
            if not isinstance(concept_id, str) or not concept_id.strip():
                raise ConnectorError("NASA CMR collection is missing a concept id.")
            references[concept_id] = DatasetReference(
                connector_id=self.metadata.connector_id,
                dataset_id=concept_id,
                version=_text(entry.get("version_id")),
                uri=urljoin(
                    str(self.settings.search_url).rstrip("/") + "/",
                    f"concepts/{quote(concept_id, safe='')}.html",
                ),
                metadata=_collection_metadata(entry),
            )
        return tuple(references[key] for key in sorted(references))

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        params = self._granule_parameters(query)
        entries, matched, pages = await self._scroll_entries("granules.json", params)
        observations = tuple(
            self._observation_from_granule(entry) for entry in entries
        )
        return ObservationSearchResult(
            observations=observations,
            matched=matched,
            context={
                "provider": "NASA Earthdata",
                "page_size": self.settings.page_size,
            },
            source_document={"pages": pages},
        )

    async def acquire(self, request: Mapping[str, Any]) -> Any:
        raise ValidationError(
            "NASA Earthdata acquisition requires a canonical EarthQuery.",
            context={"connector": self.metadata.connector_id},
        )

    def _granule_parameters(self, query: EarthQuery) -> dict[str, Any]:
        if query.crs.casefold() not in {
            "ogc:crs84",
            "crs84",
            "epsg:4326",
        }:
            raise ValidationError(
                "NASA CMR spatial search requires geographic coordinates.",
                context={"crs": query.crs},
            )
        if query.geometry is not None or query.spatial_resolution is not None:
            raise ValidationError(
                "NASA CMR connector supports bbox and point queries only."
            )
        if query.requested_variables:
            raise ValidationError(
                "NASA CMR granule metadata does not guarantee variable-level filtering."
            )
        allowed_filters = {"collection_concept_id", "provider", "short_name"}
        unknown_filters = set(query.filters).difference(allowed_filters)
        if unknown_filters:
            raise ValidationError(
                "NASA CMR connector cannot represent the requested filters.",
                context={"filters": sorted(unknown_filters)},
            )
        configured_collection_filter = query.filters.get("collection_concept_id")
        if isinstance(configured_collection_filter, str):
            configured_collection_filter = (configured_collection_filter,)
        selected_collections = query.requested_dataset_ids
        if selected_collections and configured_collection_filter is not None:
            selected_collections = tuple(
                value
                for value in selected_collections
                if value in configured_collection_filter
            )
            if not selected_collections:
                raise ValidationError(
                    "Requested NASA datasets conflict with collection_concept_id filter."
                )
        if not selected_collections:
            selected_collections = (
                configured_collection_filter or self.settings.collection_concept_ids
            )
        if isinstance(selected_collections, str):
            selected_collections = (selected_collections,)
        if not isinstance(selected_collections, (list, tuple)) or any(
            not isinstance(value, str) or not value.strip()
            for value in selected_collections
        ):
            raise ValidationError("collection_concept_id filters must be non-empty strings.")
        if (
            self.settings.collection_concept_ids
            and selected_collections
            and not set(selected_collections).issubset(
                self.settings.collection_concept_ids
            )
        ):
            raise ValidationError(
                "Requested NASA collection is not enabled for this connector."
            )
        if selected_collections:
            params: dict[str, Any] = {
                "collection_concept_id": ",".join(selected_collections)
            }
        elif self.settings.short_names:
            params = {"short_name": ",".join(self.settings.short_names)}
        else:
            raise ValidationError(
                "NASA CMR granule search requires configured collections or "
                "a collection_concept_id filter."
            )
        if query.point is not None:
            params["point"] = f"{query.point[0]},{query.point[1]}"
        elif query.bbox is not None:
            if len(query.bbox) != 4:
                raise ValidationError("NASA CMR bounding boxes require four coordinates.")
            params["bounding_box"] = ",".join(str(value) for value in query.bbox)
        if query.temporal_start is not None or query.temporal_end is not None:
            params["temporal"] = ",".join(
                _format_datetime(value)
                for value in (query.temporal_start, query.temporal_end)
            )
        params["page_size"] = self.settings.page_size
        for key in ("provider", "short_name"):
            if key in query.filters:
                params[key] = query.filters[key]
        return params

    async def _scroll_entries(
        self, endpoint: str, params: Mapping[str, Any]
    ) -> tuple[list[Mapping[str, Any]], Optional[int], tuple[Mapping[str, Any], ...]]:
        entries: list[Mapping[str, Any]] = []
        pages: list[Mapping[str, Any]] = []
        matched: Optional[int] = None
        cursor: Optional[str] = None
        seen: set[str] = set()
        while True:
            headers = {"CMR-Search-After": cursor} if cursor is not None else {}
            document, response_headers = await self._request_json(
                endpoint,
                params={**params, "scroll": "true"},
                headers=headers,
                return_headers=True,
            )
            feed = document.get("feed")
            page = feed.get("entry") if isinstance(feed, Mapping) else None
            if not isinstance(page, list) or any(
                not isinstance(entry, Mapping) for entry in page
            ):
                raise ConnectorError(
                    "NASA CMR collection response must contain a feed entry array."
                )
            entries.extend(page)
            pages.append(document)
            if matched is None:
                hits = feed.get("hits")
                if isinstance(hits, int) and not isinstance(hits, bool):
                    matched = hits
            next_cursor = response_headers.get("CMR-Search-After")
            if not next_cursor or not page:
                return entries, matched, tuple(pages)
            if next_cursor in seen:
                raise ConnectorError("NASA CMR collection pagination repeated a cursor.")
            seen.add(next_cursor)
            cursor = next_cursor

    async def _request_json(
        self,
        endpoint: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        return_headers: bool = False,
    ) -> Any:
        if self._client is None:
            raise ConnectorError(
                "NASA Earthdata connector is not started.",
                context={"connector": self.metadata.connector_id},
            )
        request_headers = dict(headers or {})
        if self._token is not None:
            request_headers["Authorization"] = f"Bearer {self._token}"
        url = urljoin(str(self.settings.search_url).rstrip("/") + "/", endpoint)
        try:
            response = await self._client.get(
                url,
                params=dict(params or {}),
                headers=request_headers,
            )
        except httpx.TimeoutException as exc:
            raise NetworkError(
                "NASA CMR request timed out.",
                context={"connector": self.metadata.connector_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"NASA CMR request failed: {exc}",
                context={"connector": self.metadata.connector_id},
            ) from exc
        if response.status_code == 429:
            raise RateLimitError(
                "NASA CMR rate limit was reached.",
                context={"connector": self.metadata.connector_id},
                recoverable=True,
            )
        if response.status_code >= 500:
            raise NetworkError(
                f"NASA CMR service returned HTTP {response.status_code}.",
                context={"connector": self.metadata.connector_id},
            )
        if response.status_code >= 400:
            raise ConnectorError(
                f"NASA CMR returned HTTP {response.status_code}.",
                context={"connector": self.metadata.connector_id},
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConnectorError("NASA CMR returned invalid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise ConnectorError("NASA CMR response must be a JSON object.")
        if return_headers:
            return dict(payload), response.headers
        return dict(payload)

    def _observation_from_granule(
        self, entry: Mapping[str, Any]
    ) -> Observation:
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not source_id:
            raise ConnectorError("NASA CMR granule is missing an id.")
        temporal_start = _parse_datetime(entry.get("time_start"))
        temporal_end = _parse_datetime(entry.get("time_end"))
        temporal = (
            TemporalExtent(start=temporal_start, end=temporal_end)
            if temporal_start is not None or temporal_end is not None
            else None
        )
        geometry, bbox = _granule_geometry(entry)
        assets: dict[str, ObservationAsset] = {}
        raw_links = entry.get("links", ())
        if isinstance(raw_links, list):
            for index, link in enumerate(raw_links):
                if not isinstance(link, Mapping):
                    continue
                href = link.get("href")
                if not isinstance(href, str) or not href.startswith(("https://", "http://")):
                    continue
                relation = str(link.get("rel", ""))
                if "data" not in relation.casefold() and "browse" not in relation.casefold():
                    continue
                role = "preview" if "browse" in relation.casefold() else "data"
                key = str(link.get("title") or f"{role}-{index}")
                assets[key] = ObservationAsset(
                    uri=href,
                    media_type=_text(link.get("type")),
                    roles=(role,),
                    title=_text(link.get("title")),
                    description=_text(link.get("hreflang")),
                    metadata=dict(link),
                )
        concept_id = _text(entry.get("collection_concept_id"))
        dataset = (
            DatasetReference(
                connector_id=self.metadata.connector_id,
                dataset_id=concept_id,
                metadata={"concept_id": concept_id},
            )
            if concept_id
            else None
        )
        return Observation(
            source_id=source_id,
            dataset=dataset,
            observed_at=temporal_start,
            geometry=geometry,
            bbox=bbox,
            crs="OGC:CRS84" if geometry is not None or bbox is not None else None,
            temporal_extent=temporal,
            observation_type="earth_observation_granule",
            provenance={
                "provider": "NASA Earthdata",
                "protocol": "NASA CMR",
                "granule_id": source_id,
                "collection_concept_id": concept_id,
            },
            provider_metadata={
                key: value
                for key, value in entry.items()
                if key not in {"links", "polygons", "boxes"}
            },
            reproducibility={
                "provider": "NASA Earthdata",
                "catalog_url": str(self.settings.search_url),
                "granule_id": source_id,
            },
            properties=dict(entry),
            assets=assets,
            source_document=dict(entry),
        )


def _collection_metadata(entry: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"cmr_collection": dict(entry)}
    for source, target in (
        ("short_name", "short_name"),
        ("title", "title"),
        ("summary", "description"),
        ("provider_id", "provider_id"),
        ("version_id", "version"),
        ("science_keywords", "keywords"),
    ):
        if source in entry:
            metadata[target] = entry[source]
    if isinstance(entry.get("science_keywords"), list):
        metadata["keywords"] = [
            item.get("topic") or item.get("term")
            for item in entry["science_keywords"]
            if isinstance(item, Mapping)
            and isinstance(item.get("topic") or item.get("term"), str)
        ]
    start, end = _parse_datetime(entry.get("time_start")), _parse_datetime(
        entry.get("time_end")
    )
    if start is not None or end is not None:
        metadata["temporal_coverage"] = {"start": start, "end": end}
    _, bbox = _granule_geometry(entry)
    if bbox is not None:
        metadata["spatial_coverage"] = _bbox_geometry(bbox)
        metadata["crs"] = "OGC:CRS84"
    return metadata


def _granule_geometry(
    entry: Mapping[str, Any],
) -> tuple[Optional[dict[str, Any]], Optional[tuple[float, float, float, float]]]:
    polygons = entry.get("polygons")
    if isinstance(polygons, list) and polygons:
        raw_polygon = polygons[0]
        if isinstance(raw_polygon, str):
            try:
                values = [float(value) for value in raw_polygon.split()]
            except ValueError:
                values = []
            if len(values) >= 6 and len(values) % 2 == 0:
                ring = [
                    [values[index + 1], values[index]]
                    for index in range(0, len(values), 2)
                ]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                if len(ring) >= 4:
                    return {"type": "Polygon", "coordinates": [ring]}, None
    boxes = entry.get("boxes")
    if isinstance(boxes, list) and boxes and isinstance(boxes[0], str):
        try:
            south, west, north, east = (
                float(value) for value in boxes[0].split()
            )
        except (ValueError, TypeError):
            return None, None
        if (
            all(math.isfinite(value) for value in (south, west, north, east))
            and south < north
            and west < east
        ):
            bbox = (west, south, east, north)
            return _bbox_geometry(bbox), bbox
    return None, None


def _bbox_geometry(
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    west, south, east, north = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConnectorError("NASA CMR temporal value must be a string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorError("NASA CMR returned an invalid timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: Optional[datetime]) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else ""


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None
