"""NASA FIRMS active-fire detections normalized as disaster observations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import quote

import httpx
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
    ObservationSearchResult,
    TemporalExtent,
)
from satquery.platform.ontology import EARTH_VARIABLE_ONTOLOGY

_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
_DATASET_ID = "nasa-firms-active-fire"
_VARIABLES = (
    "active_fire",
    "fire_radiative_power",
    "brightness_temperature_ti4",
    "brightness_temperature_ti5",
)
_SOURCES = frozenset(
    {
        "VIIRS_NOAA21_NRT",
        "VIIRS_NOAA20_NRT",
        "VIIRS_SNPP_NRT",
        "VIIRS_NOAA21_SP",
        "VIIRS_NOAA20_SP",
        "VIIRS_SNPP_SP",
        "MODIS_NRT",
        "MODIS_SP",
    }
)
_MAX_DAYS = 5


class NasaFirmsConnector(PerceptionConnector):
    """Acquire VIIRS/MODIS active-fire records for explicit bbox/date queries.

    FIRMS MAP_KEY values are credentials embedded in the API path. Error
    messages and connector metadata intentionally never include that path.
    """

    def __init__(
        self,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        policy: Optional[ConnectorPolicy] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(
            configuration=configuration,
            policy=policy
            or ConnectorPolicy(
                timeout_seconds=45,
                max_attempts=2,
                retry_safe=True,
                retry_delay_seconds=0.2,
            ),
        )
        config = dict(configuration or {})
        self.connector_id = str(config.get("connector_id", _DATASET_ID))
        self.map_key = config.get("map_key") or os.environ.get(
            "SATQUERY_NASA_FIRMS_MAP_KEY"
        )
        self.source = config.get("source", "VIIRS_NOAA21_NRT")
        self.api_url = str(config.get("api_url", _API)).rstrip("/")
        self._transport = transport
        self._client = client
        self._owns_client = client is None
        self._validate_configuration()

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name="NASA FIRMS active fire observations",
            version="1",
            capabilities=("active_fire_detection", "disaster_observation"),
            modalities=("disaster",),
            supported_variables=_VARIABLES,
            authentication_required=True,
            authentication_schemes=("NASA FIRMS MAP_KEY",),
            configuration_schema={
                "map_key": {
                    "type": "string",
                    "required": True,
                    "secret": True,
                    "environment_variable": "SATQUERY_NASA_FIRMS_MAP_KEY",
                },
                "source": {
                    "type": "string",
                    "enum": sorted(_SOURCES),
                    "default": "VIIRS_NOAA21_NRT",
                },
            },
            supports_temporal_query=True,
            supported_spatial_types=("bbox",),
            supported_query_fields=("filters", "requested_dataset_ids"),
            datasets=(
                DatasetReference(
                    connector_id=self.connector_id,
                    dataset_id=_DATASET_ID,
                    metadata={
                        "provider": "NASA LANCE FIRMS",
                        "variables": list(_VARIABLES),
                        "units": {
                            "fire_radiative_power": "MW",
                            "brightness_temperature_ti4": "K",
                            "brightness_temperature_ti5": "K",
                        },
                        "modalities": ["disaster"],
                        "capabilities": [
                            "active_fire_detection",
                            "disaster_observation",
                        ],
                        "access_policy": {
                            "map_key_required": True,
                            "spatial_query_required": "bbox",
                            "maximum_days_per_request": _MAX_DAYS,
                            "limitations": [
                                "Satellite thermal-anomaly detections are not "
                                "a complete fire census",
                                "A detected hotspot does not by itself "
                                "establish a wildfire or its cause",
                                "Only the selected FIRMS sensor product is queried",
                            ],
                        },
                        "documentation_url": "https://firms.modaps.eosdis.nasa.gov/api/area/",
                    },
                ),
            ),
            provider_metadata={
                "provider": "NASA LANCE FIRMS",
                "product_source": self.source,
                "documentation_url": "https://firms.modaps.eosdis.nasa.gov/api/area/",
                "api_url": self.api_url,
            },
            quota={
                "provider_limit_transactions": 5000,
                "provider_limit_window": "10 minutes",
            },
            documentation_url="https://firms.modaps.eosdis.nasa.gov/api/area/",
        )

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.policy.timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def authenticate(self, credentials: Optional[Mapping[str, str]]) -> None:
        supplied = credentials or {}
        candidate = supplied.get("map_key") or supplied.get("NASA FIRMS MAP_KEY")
        candidate = candidate or self.map_key
        if not _valid_map_key(candidate):
            raise AuthenticationError(
                "NASA FIRMS requires a MAP_KEY from connector configuration, "
                "SATQUERY_NASA_FIRMS_MAP_KEY, or the credential provider."
            )
        self.map_key = candidate

    async def discover(self) -> tuple[DatasetReference, ...]:
        return self.metadata.datasets

    async def acquire(self, request: Mapping[str, Any]) -> str:
        """Return provider CSV text; never put the credential in diagnostics."""
        if self._client is None:
            raise ConnectorError("NASA FIRMS connector has not been started.")
        if not _valid_map_key(self.map_key):
            raise AuthenticationError(
                "NASA FIRMS requires a MAP_KEY before acquisition."
            )
        bbox = request.get("bbox")
        if not isinstance(bbox, tuple) or len(bbox) != 4:
            raise ValidationError("NASA FIRMS acquisition requires a 2D bbox.")
        west, south, east, north = bbox
        area = ",".join(_coordinate(value) for value in (west, south, east, north))
        day_count = request.get("day_count")
        start_date = request.get("start_date")
        if not isinstance(day_count, int) or not 1 <= day_count <= _MAX_DAYS:
            raise ValidationError("NASA FIRMS day range must be between 1 and 5 days.")
        if not isinstance(start_date, str):
            raise ValidationError("NASA FIRMS acquisition requires an explicit date.")
        url = "/".join(
            (
                self.api_url,
                quote(str(self.map_key), safe=""),
                str(self.source),
                area,
                str(day_count),
                start_date,
            )
        )
        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            raise NetworkError("NASA FIRMS observation request timed out.") from exc
        except httpx.HTTPError as exc:
            raise NetworkError("NASA FIRMS observation request failed.") from exc
        if response.status_code == 429:
            raise RateLimitError("NASA FIRMS rate limited the request.")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"NASA FIRMS returned HTTP {response.status_code}.",
                context={"status_code": response.status_code},
            ) from exc
        return response.text

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request = self._request_from_query(query)
        csv_text = await self.acquire(request)
        reader = csv.DictReader(io.StringIO(csv_text))
        required_columns = {"latitude", "longitude", "acq_date", "acq_time"}
        if reader.fieldnames is None or not required_columns.issubset(
            reader.fieldnames
        ):
            raise ConnectorError(
                "NASA FIRMS response is missing required detection columns.",
                context={"connector": self.connector_id},
            )
        rows = tuple(reader)
        observations = tuple(
            self._observation(row)
            for row in rows
            if request["start"] <= self._timestamp(row) <= request["end"]
        )
        return ObservationSearchResult(
            observations=observations,
            matched=len(observations),
            context={
                "provider": "NASA LANCE FIRMS",
                "source": self.source,
                "record_count": len(observations),
                "query_bbox": request["bbox"],
                "query_date_start": request["start_date"],
                "query_day_count": request["day_count"],
            },
        )

    def _request_from_query(self, query: EarthQuery) -> dict[str, Any]:
        if (
            query.bbox is None
            or len(query.bbox) != 4
            or query.crs.casefold()
            not in {
                "ogc:crs84",
                "epsg:4326",
            }
        ):
            raise ValidationError(
                "NASA FIRMS requires a 2D geographic bbox in CRS84 or EPSG:4326."
            )
        west, south, east, north = query.bbox
        if west >= east or south >= north:
            raise ValidationError(
                "NASA FIRMS bbox must not cross the antimeridian and must have area."
            )
        if query.temporal_start is None or query.temporal_end is None:
            raise ValidationError(
                "NASA FIRMS requires explicit temporal_start and temporal_end."
            )
        start = query.temporal_start.astimezone(timezone.utc)
        end = query.temporal_end.astimezone(timezone.utc)
        first_date = start.date()
        last_date = end.date()
        if end < start:
            raise ValidationError("NASA FIRMS query end must follow query start.")
        day_count = (last_date - first_date).days + 1
        if day_count > _MAX_DAYS:
            raise ValidationError(
                "NASA FIRMS requests may cover at most 5 calendar days."
            )
        filters = dict(query.filters)
        if set(filters).difference({"source"}):
            raise ValidationError("NASA FIRMS received unsupported query filters.")
        source = filters.get("source", self.source)
        if source != self.source:
            raise ValidationError(
                "NASA FIRMS source is fixed by connector configuration.",
                context={"configured_source": self.source},
            )
        unsupported_variables = []
        for value in query.requested_variables:
            resolved = EARTH_VARIABLE_ONTOLOGY.resolve_variable(value)
            canonical = resolved.canonical_name if resolved is not None else value
            if canonical not in _VARIABLES:
                unsupported_variables.append(value)
        if unsupported_variables:
            raise ValidationError(
                "NASA FIRMS cannot provide every requested variable.",
                context={"requested_variables": unsupported_variables},
            )
        if query.requested_dataset_ids and not any(
            value in {_DATASET_ID, f"{self.connector_id}:{_DATASET_ID}"}
            for value in query.requested_dataset_ids
        ):
            raise ValidationError("NASA FIRMS does not provide the requested dataset.")
        return {
            "bbox": tuple(query.bbox),
            "start_date": first_date.isoformat(),
            "day_count": day_count,
            "start": start,
            "end": end,
        }

    def _observation(self, row: Mapping[str, Any]) -> Observation:
        latitude = _finite_number(row.get("latitude"), "latitude")
        longitude = _finite_number(row.get("longitude"), "longitude")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ConnectorError("NASA FIRMS returned coordinates out of range.")
        observed_at = self._timestamp(row)
        measurements: dict[str, dict[str, Any]] = {
            "active_fire": {
                "value": "detected",
                "source_name": "FIRMS active-fire detection record",
                "interpretation_limit": (
                    "Provider detection indicates a satellite thermal anomaly; "
                    "it does not verify wildfire cause or impact."
                ),
            }
        }
        for source_name, canonical, unit in (
            ("frp", "fire_radiative_power", "MW"),
            ("bright_ti4", "brightness_temperature_ti4", "K"),
            ("bright_ti5", "brightness_temperature_ti5", "K"),
        ):
            number = _optional_number(row.get(source_name))
            if number is not None:
                measurements[canonical] = {
                    "value": number,
                    "unit": unit,
                    "source_unit": unit,
                    "source_name": source_name,
                }
        provider_metadata = {
            key: row[key]
            for key in (
                "confidence",
                "satellite",
                "instrument",
                "version",
                "daynight",
                "scan",
                "track",
            )
            if row.get(key) not in (None, "")
        }
        source_digest = hashlib.sha256(
            json.dumps(dict(row), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        reference = DatasetReference(
            connector_id=self.connector_id,
            dataset_id=_DATASET_ID,
            metadata={"sensor_source": self.source},
        )
        return Observation(
            source_id=f"{self.source}:{source_digest}",
            dataset=reference,
            observed_at=observed_at,
            temporal_extent=TemporalExtent(start=observed_at, end=observed_at),
            geometry={"type": "Point", "coordinates": [longitude, latitude]},
            crs="OGC:CRS84",
            observation_type="satellite_thermal_anomaly",
            measured_variables=measurements,
            modalities=("disaster",),
            provenance={
                "provider": "NASA LANCE FIRMS",
                "sensor_source": self.source,
                "time_precision": "minute",
            },
            provider_metadata=provider_metadata,
            source_document=dict(row),
        )

    @staticmethod
    def _timestamp(row: Mapping[str, Any]) -> datetime:
        date_value = row.get("acq_date")
        time_value = row.get("acq_time")
        try:
            date = datetime.strptime(str(date_value), "%Y-%m-%d").date()
            time_code = str(time_value).zfill(4)
            if (
                not time_code.isdigit()
                or int(time_code[:2]) > 23
                or int(time_code[2:]) > 59
            ):
                raise ValueError("invalid acquisition time")
            return datetime(
                date.year,
                date.month,
                date.day,
                int(time_code[:2]),
                int(time_code[2:]),
                tzinfo=timezone.utc,
            )
        except (TypeError, ValueError) as exc:
            raise ConnectorError(
                "NASA FIRMS returned an invalid acquisition time."
            ) from exc

    def _validate_configuration(self) -> None:
        if self.map_key is not None and not _valid_map_key(self.map_key):
            raise ValidationError("NASA FIRMS map_key contains invalid characters.")
        if self.source not in _SOURCES:
            raise ValidationError(
                "NASA FIRMS source is not in the supported sensor-product allowlist.",
                context={"source": self.source},
            )
        parts = httpx.URL(self.api_url)
        if parts.scheme != "https" or not parts.host:
            raise ValidationError("NASA FIRMS API URL must use HTTPS.")


def _finite_number(value: Any, field: str) -> float:
    number = _optional_number(value)
    if number is None:
        raise ConnectorError(f"NASA FIRMS returned an invalid {field} value.")
    return number


def _optional_number(value: Any) -> Optional[float]:
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConnectorError("NASA FIRMS returned a non-numeric measurement.")
    if not math.isfinite(number):
        raise ConnectorError("NASA FIRMS returned a non-finite measurement.")
    return number


def _coordinate(value: float) -> str:
    return format(value, ".8g")


def _valid_map_key(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.replace("-", "").replace("_", "").isalnum()
    )
