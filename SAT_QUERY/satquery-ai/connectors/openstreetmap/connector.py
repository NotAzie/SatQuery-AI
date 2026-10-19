"""OpenStreetMap/Overpass vector acquisition through canonical observations."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from satquery.errors import ConnectorError, NetworkError, RateLimitError, ValidationError
from satquery.platform.connectors import ConnectorPolicy, PerceptionConnector
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetReference,
    EarthObjectCandidate,
    EarthQuery,
    Observation,
    ObservationAsset,
    ObservationSearchResult,
    TemporalExtent,
)

_DEFAULT_TAGS = ("highway", "building", "landuse", "boundary", "waterway", "man_made")
_TAG_KEY = re.compile(r"^[A-Za-z0-9:_-]+$")


class OverpassSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: str = Field(default="openstreetmap-overpass", min_length=1)
    endpoint_url: AnyHttpUrl = AnyHttpUrl("https://overpass-api.de/api/interpreter")
    timeout_seconds: float = Field(default=60, gt=0, le=300)
    point_radius_m: float = Field(default=250, gt=0, le=5000)
    default_tag_keys: tuple[str, ...] = _DEFAULT_TAGS


class OverpassConnector(PerceptionConnector):
    """Read-only OSM geometry discovery; no OSM data is downloaded elsewhere."""

    def __init__(
        self,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        policy: Optional[ConnectorPolicy] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        resolved_policy = policy or ConnectorPolicy(
            timeout_seconds=65,
            max_attempts=2,
            retry_safe=True,
            retry_delay_seconds=0.2,
        )
        super().__init__(configuration=configuration, policy=resolved_policy)
        try:
            self.settings = OverpassSettings.model_validate(
                dict(configuration or {})
            )
        except PydanticValidationError as exc:
            raise ValidationError(
                "Invalid Overpass connector configuration.",
                context={"errors": exc.errors(include_input=False, include_url=False)},
            ) from exc
        endpoint = urlsplit(str(self.settings.endpoint_url))
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValidationError(
                "Overpass endpoint URL must not contain credentials, query, or fragment."
            )
        if not self.settings.default_tag_keys or any(
            not _TAG_KEY.fullmatch(key) for key in self.settings.default_tag_keys
        ):
            raise ValidationError("Overpass tag keys must be valid and non-empty.")
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.settings.connector_id,
            name="OpenStreetMap Overpass",
            version="1",
            capabilities=("vector", "infrastructure", "human_geography"),
            modalities=("human",),
            supports_temporal_query=False,
            supported_spatial_types=("bbox", "point", "geometry"),
            supported_query_fields=("filters", "requested_dataset_ids"),
            datasets=(
                DatasetReference(
                    connector_id=self.settings.connector_id,
                    dataset_id="osm-map-features",
                    uri="https://www.openstreetmap.org/",
                    metadata={"modalities": ["human"]},
                ),
            ),
            provider_metadata={
                "provider": "OpenStreetMap",
                "protocol": "Overpass API",
                "endpoint": str(self.settings.endpoint_url),
                "license": "ODbL-1.0",
            },
            configuration_schema={
                "type": "object",
                "properties": {
                    "connector_id": {"type": "string"},
                    "endpoint_url": {"type": "string", "format": "uri"},
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                    "point_radius_m": {"type": "number", "exclusiveMinimum": 0},
                    "default_tag_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        )

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=min(
                    self.settings.timeout_seconds + 5,
                    self.policy.timeout_seconds or self.settings.timeout_seconds + 5,
                ),
                follow_redirects=False,
                transport=self._transport,
                headers={"Accept": "application/json"},
            )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover(self) -> tuple[DatasetReference, ...]:
        return (
            DatasetReference(
                connector_id=self.metadata.connector_id,
                dataset_id="osm-map-features",
                uri="https://www.openstreetmap.org/",
                metadata={
                    "title": "OpenStreetMap map features",
                    "description": "Read-only vector features selected with Overpass.",
                    "capabilities": list(self.metadata.capabilities),
                    "modalities": list(self.metadata.modalities),
                    "licensing": "ODbL-1.0",
                    "citation": "© OpenStreetMap contributors",
                    "keywords": list(self.settings.default_tag_keys),
                    "tags": list(self.settings.default_tag_keys),
                },
            ),
        )

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        overpass_query, requested_tags = self._build_query(query)
        document = await self._request(overpass_query)
        elements = document.get("elements")
        if not isinstance(elements, list) or any(
            not isinstance(item, Mapping) for item in elements
        ):
            raise ConnectorError(
                "Overpass response must contain an elements array.",
                context={"connector": self.metadata.connector_id},
            )
        snapshot_time = _parse_datetime(
            document.get("osm3s", {}).get("timestamp_osm_base")
            if isinstance(document.get("osm3s"), Mapping)
            else None
        )
        observations = tuple(
            self._observation(element, snapshot_time, requested_tags)
            for element in elements
        )
        return ObservationSearchResult(
            observations=observations,
            matched=len(observations),
            context={
                "provider": "OpenStreetMap",
                "snapshot_time": snapshot_time.isoformat() if snapshot_time else None,
                "tags": requested_tags,
            },
            source_document={
                key: value for key, value in document.items() if key != "elements"
            },
        )

    async def acquire(self, request: Mapping[str, Any]) -> Any:
        raise ValidationError(
            "OpenStreetMap acquisition requires a canonical EarthQuery.",
            context={"connector": self.metadata.connector_id},
        )

    def _build_query(self, query: EarthQuery) -> tuple[str, tuple[str, ...]]:
        if (
            query.requested_dataset_ids
            and "osm-map-features" not in query.requested_dataset_ids
        ):
            raise ValidationError("Requested dataset is not implemented by Overpass.")
        if query.crs.casefold() not in {
            "ogc:crs84",
            "crs84",
            "epsg:4326",
        }:
            raise ValidationError(
                "Overpass spatial queries require geographic coordinates.",
                context={"crs": query.crs},
            )
        if query.temporal_start is not None or query.temporal_end is not None:
            raise ValidationError(
                "Overpass connector does not provide historical or temporal queries."
            )
        if query.spatial_resolution is not None or query.asset_preferences:
            raise ValidationError(
                "Overpass connector cannot represent resolution or asset preferences."
            )
        if not any((query.bbox, query.point, query.geometry)):
            raise ValidationError("Overpass queries require a bounded area of interest.")
        allowed_filters = {"osm_tags", "element_types"}
        unknown = set(query.filters).difference(allowed_filters)
        if unknown:
            raise ValidationError(
                "Overpass connector cannot represent the requested filters.",
                context={"filters": sorted(unknown)},
            )
        tags = query.filters.get("osm_tags")
        selectors: list[tuple[str, Optional[str]]] = []
        if tags is None:
            selectors = [(key, None) for key in self.settings.default_tag_keys]
        elif isinstance(tags, Mapping) and tags:
            for key, values in sorted(tags.items()):
                if not isinstance(key, str) or not _TAG_KEY.fullmatch(key):
                    raise ValidationError("Overpass tag keys contain invalid characters.")
                if values is None:
                    selectors.append((key, None))
                elif isinstance(values, str):
                    selectors.append((key, values))
                elif isinstance(values, (list, tuple)) and values and all(
                    isinstance(value, str) for value in values
                ):
                    selectors.extend((key, value) for value in values)
                else:
                    raise ValidationError(
                        f"Overpass tag values for {key!r} must be a string or non-empty string list."
                    )
        else:
            raise ValidationError("Overpass osm_tags filter must be a non-empty object.")
        if query.point is not None:
            selector = (
                f"(around:{self.settings.point_radius_m:g},"
                f"{query.point[1]:.8f},{query.point[0]:.8f})"
            )
        elif query.bbox is not None:
            if len(query.bbox) != 4:
                raise ValidationError("Overpass bounding boxes require four coordinates.")
            west, south, east, north = query.bbox
            if west >= east:
                raise ValidationError(
                    "Overpass does not support antimeridian-crossing bounding boxes."
                )
            selector = f"({south:.8f},{west:.8f},{north:.8f},{east:.8f})"
        else:
            selector = self._polygon_selector(query.geometry)
        element_types = query.filters.get("element_types", ("node", "way", "relation"))
        if isinstance(element_types, str):
            element_types = (element_types,)
        if (
            not isinstance(element_types, (tuple, list))
            or not element_types
            or any(not isinstance(item, str) for item in element_types)
            or any(item not in {"node", "way", "relation"} for item in element_types)
        ):
            raise ValidationError(
                "Overpass element_types must contain node, way, or relation."
            )
        statements = []
        for element_type in sorted(set(element_types)):
            for key, value in selectors:
                tag_filter = f'["{key}"]' if value is None else (
                    f'["{key}"="{_escape_ql(value)}"]'
                )
                statements.append(f"{element_type}{selector}{tag_filter};")
        ql = (
            f"[out:json][timeout:{int(self.settings.timeout_seconds)}];"
            f"({' '.join(statements)});out body geom;"
        )
        return ql, tuple(sorted({key for key, _ in selectors}))

    @staticmethod
    def _polygon_selector(geometry: Optional[Mapping[str, Any]]) -> str:
        if not isinstance(geometry, Mapping) or geometry.get("type") != "Polygon":
            raise ValidationError(
                "Overpass supports point, bbox, and single-ring GeoJSON Polygon queries."
            )
        coordinates = geometry.get("coordinates")
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 1
            or not isinstance(coordinates[0], list)
            or len(coordinates[0]) < 4
        ):
            raise ValidationError(
                "Overpass polygon queries require one closed exterior ring without holes."
            )
        try:
            pairs = [(float(item[1]), float(item[0])) for item in coordinates[0]]
        except (IndexError, TypeError, ValueError) as exc:
            raise ValidationError("Overpass polygon coordinates are invalid.") from exc
        if any(
            not math.isfinite(lat)
            or not math.isfinite(lon)
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
            for lat, lon in pairs
        ):
            raise ValidationError("Overpass polygon coordinates are out of range.")
        if pairs[0] != pairs[-1]:
            raise ValidationError("Overpass polygon exterior ring must be closed.")
        return "(poly:" + " ".join(f"{lat:.8f} {lon:.8f}" for lat, lon in pairs) + ")"

    async def _request(self, query: str) -> Mapping[str, Any]:
        if self._client is None:
            raise ConnectorError(
                "Overpass connector is not started.",
                context={"connector": self.metadata.connector_id},
            )
        try:
            response = await self._client.post(
                str(self.settings.endpoint_url),
                data={"data": query},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.TimeoutException as exc:
            raise NetworkError(
                "Overpass request timed out.",
                context={"connector": self.metadata.connector_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"Overpass request failed: {exc}",
                context={"connector": self.metadata.connector_id},
            ) from exc
        if response.status_code == 429:
            raise RateLimitError(
                "Overpass rate limit was reached.",
                context={"connector": self.metadata.connector_id},
                recoverable=True,
            )
        if response.status_code >= 500:
            raise NetworkError(
                f"Overpass service returned HTTP {response.status_code}.",
                context={"connector": self.metadata.connector_id},
            )
        if response.status_code >= 400:
            raise ConnectorError(
                f"Overpass returned HTTP {response.status_code}.",
                context={"connector": self.metadata.connector_id},
            )
        try:
            document = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConnectorError("Overpass returned invalid JSON.") from exc
        if not isinstance(document, Mapping):
            raise ConnectorError("Overpass response must be a JSON object.")
        return document

    def _observation(
        self,
        element: Mapping[str, Any],
        snapshot_time: Optional[datetime],
        requested_tags: tuple[str, ...],
    ) -> Observation:
        element_type, osm_id = element.get("type"), element.get("id")
        if element_type not in {"node", "way", "relation"} or not isinstance(osm_id, int):
            raise ConnectorError("Overpass element has an invalid type or id.")
        geometry = _osm_geometry(element)
        tags = element.get("tags", {})
        if not isinstance(tags, Mapping):
            raise ConnectorError("Overpass element tags must be an object.")
        observation_id = f"{element_type}/{osm_id}"
        asset = ObservationAsset(
            uri=f"https://www.openstreetmap.org/{element_type}/{osm_id}",
            media_type="text/html",
            roles=("metadata",),
            title=f"OpenStreetMap {element_type} {osm_id}",
            metadata={"osm_type": element_type, "osm_id": osm_id},
        )
        extent = (
            TemporalExtent(start=snapshot_time, end=snapshot_time)
            if snapshot_time is not None
            else None
        )
        return Observation(
            source_id=observation_id,
            dataset=DatasetReference(
                connector_id=self.metadata.connector_id,
                dataset_id="osm-map-features",
                uri="https://www.openstreetmap.org/",
            ),
            observed_at=snapshot_time,
            geometry=geometry,
            crs="OGC:CRS84" if geometry is not None else None,
            temporal_extent=extent,
            observation_type="vector_feature",
            earth_object_candidate=_earth_object_candidate(
                connector_id=self.metadata.connector_id,
                element_type=element_type,
                osm_id=osm_id,
                tags=tags,
            ),
            provenance={
                "provider": "OpenStreetMap",
                "protocol": "Overpass API",
                "element_type": element_type,
                "element_id": osm_id,
            },
            provider_metadata={
                "version": element.get("version"),
                "timestamp": element.get("timestamp"),
                "requested_tag_keys": requested_tags,
            },
            reproducibility={
                "endpoint": str(self.settings.endpoint_url),
                "osm_type": element_type,
                "osm_id": osm_id,
                "version": element.get("version"),
            },
            properties={
                "osm_type": element_type,
                "osm_id": osm_id,
                "tags": dict(tags),
            },
            assets={"metadata": asset},
            source_document=dict(element),
        )


def _earth_object_candidate(
    *, connector_id: str, element_type: str, osm_id: int, tags: Mapping[str, Any]
) -> Optional[EarthObjectCandidate]:
    """Map explicit OSM feature tags to declared Earth entity categories.

    These are source classifications, not inferred ground truth. Unknown tag
    combinations intentionally remain observations without an object candidate.
    """
    natural = tags.get("natural")
    landuse = tags.get("landuse")
    natural_type = (
        "earth:WaterBody" if natural == "water"
        else "earth:ForestArea" if natural == "wood"
        else None
    )
    landuse_type = (
        "earth:ForestArea" if landuse == "forest"
        else "earth:LandUseArea" if isinstance(landuse, str) and landuse.casefold() not in {"", "no"}
        else None
    )
    building = tags.get("building")
    mappings = (
        ("building", "earth:BuildingAccessFeature" if building == "entrance" else "earth:Building"),
        ("highway", "earth:TransportFeature"),
        ("waterway", "earth:HydrographicFeature"),
        ("natural", natural_type),
        ("landuse", landuse_type),
    )
    for key, object_type in mappings:
        value = tags.get(key)
        if object_type and isinstance(value, str) and value.casefold() not in {"", "no", "none"}:
            return EarthObjectCandidate(
                identity_namespace="openstreetmap.org",
                identity_value=f"{element_type}/{osm_id}",
                object_type=object_type,
                declared_by=connector_id,
                mapping_id="osm-explicit-tag-classification@1.0.0",
                provenance={"source_tag": {key: value}, "classification_basis": "explicit OpenStreetMap tag"},
            )
    return None


def _osm_geometry(element: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    if element.get("type") == "node":
        latitude, longitude = element.get("lat"), element.get("lon")
        if (
            isinstance(longitude, (int, float))
            and isinstance(latitude, (int, float))
            and _valid_lon_lat(longitude, latitude)
        ):
            return {"type": "Point", "coordinates": [float(longitude), float(latitude)]}
        raise ConnectorError("Overpass node has invalid coordinates.")
    points = element.get("geometry")
    if isinstance(points, list):
        coordinates: list[list[float]] = []
        for item in points:
            if not isinstance(item, Mapping):
                raise ConnectorError(
                    "Overpass way geometry contains invalid coordinates."
                )
            longitude, latitude = item.get("lon"), item.get("lat")
            if (
                not isinstance(longitude, (int, float))
                or not isinstance(latitude, (int, float))
                or not _valid_lon_lat(longitude, latitude)
            ):
                raise ConnectorError(
                    "Overpass way geometry contains invalid coordinates."
                )
            coordinates.append([float(longitude), float(latitude)])
        if len(coordinates) == 1:
            return {"type": "Point", "coordinates": coordinates[0]}
        if len(coordinates) >= 2:
            return {"type": "LineString", "coordinates": coordinates}
    members = element.get("members")
    if isinstance(members, list):
        geometries = []
        for member in members:
            if not isinstance(member, Mapping) or not isinstance(
                member.get("geometry"), list
            ):
                continue
            coordinates: list[list[float]] = []
            for item in member["geometry"]:
                if not isinstance(item, Mapping):
                    raise ConnectorError(
                        "Overpass relation geometry contains invalid coordinates."
                    )
                longitude, latitude = item.get("lon"), item.get("lat")
                if (
                    not isinstance(longitude, (int, float))
                    or not isinstance(latitude, (int, float))
                    or not _valid_lon_lat(longitude, latitude)
                ):
                    raise ConnectorError(
                        "Overpass relation geometry contains invalid coordinates."
                    )
                coordinates.append([float(longitude), float(latitude)])
            if len(coordinates) >= 2:
                geometries.append({"type": "LineString", "coordinates": coordinates})
        if geometries:
            return {"type": "GeometryCollection", "geometries": geometries}
    return None


def _valid_lon_lat(longitude: Any, latitude: Any) -> bool:
    return (
        isinstance(longitude, (int, float))
        and not isinstance(longitude, bool)
        and isinstance(latitude, (int, float))
        and not isinstance(latitude, bool)
        and math.isfinite(longitude)
        and math.isfinite(latitude)
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    )


def _escape_ql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConnectorError("Overpass timestamp must be a string.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorError("Overpass returned an invalid snapshot timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
