"""Open-Meteo source adapter for point weather, climate, and flood data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping, Optional

import httpx
from satquery.errors import (
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
from satquery.platform.modalities import infer_modalities
from satquery.platform.normalization import SemanticNormalizer, VariableSemantic


class OpenMeteoEndpoint(str, Enum):
    WEATHER = "weather"
    HISTORICAL_WEATHER = "historical_weather"
    CLIMATE = "climate"
    HYDROLOGY = "hydrology"


_ENDPOINTS: dict[OpenMeteoEndpoint, dict[str, Any]] = {
    OpenMeteoEndpoint.WEATHER: {
        "url": "https://api.open-meteo.com/v1/forecast",
        "dataset": "weather-forecast",
        "capability": "weather",
        "key": "hourly",
        "variables": {
            "air_temperature_2m": ("temperature_2m", "°C", "air_temperature"),
            "relative_humidity_2m": ("relative_humidity_2m", "%", None),
            "precipitation_amount": ("precipitation", "mm", None),
            "wind_speed_10m": ("wind_speed_10m", "m/s", "wind_speed"),
        },
        "defaults": ("air_temperature_2m", "precipitation_amount"),
    },
    OpenMeteoEndpoint.HISTORICAL_WEATHER: {
        "url": "https://archive-api.open-meteo.com/v1/archive",
        "dataset": "historical-weather",
        "capability": "weather",
        "key": "hourly",
        "variables": {
            "air_temperature_2m": ("temperature_2m", "°C", "air_temperature"),
            "relative_humidity_2m": ("relative_humidity_2m", "%", None),
            "precipitation_amount": ("precipitation", "mm", None),
            "wind_speed_10m": ("wind_speed_10m", "m/s", "wind_speed"),
        },
        "defaults": ("air_temperature_2m", "precipitation_amount"),
    },
    OpenMeteoEndpoint.CLIMATE: {
        "url": "https://climate-api.open-meteo.com/v1/climate",
        "dataset": "climate-projections",
        "capability": "climate",
        "key": "daily",
        "variables": {
            "air_temperature_2m_mean": (
                "temperature_2m_mean",
                "°C",
                "air_temperature",
            ),
            "air_temperature_2m_max": (
                "temperature_2m_max",
                "°C",
                "air_temperature",
            ),
            "air_temperature_2m_min": (
                "temperature_2m_min",
                "°C",
                "air_temperature",
            ),
            "precipitation_amount": ("precipitation_sum", "mm", None),
        },
        "defaults": ("air_temperature_2m_mean", "precipitation_amount"),
    },
    OpenMeteoEndpoint.HYDROLOGY: {
        "url": "https://flood-api.open-meteo.com/v1/flood",
        "dataset": "glofas-river-discharge",
        "capability": "hydrology",
        "key": "daily",
        "variables": {"river_discharge": ("river_discharge", "m³/s", None)},
        "defaults": ("river_discharge",),
    },
}


class OpenMeteoConnector(PerceptionConnector):
    """Configurable endpoint-specific adapter for Open-Meteo model products."""

    def __init__(
        self,
        endpoint: OpenMeteoEndpoint | str,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        policy: Optional[ConnectorPolicy] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(configuration=configuration, policy=policy)
        try:
            self.endpoint = OpenMeteoEndpoint(endpoint)
        except ValueError as exc:
            raise ValueError(f"unsupported Open-Meteo endpoint: {endpoint!r}") from exc
        self._spec = _ENDPOINTS[self.endpoint]
        configured_url = self.configuration.get("endpoint_url")
        self._url = str(configured_url or self._spec["url"]).rstrip("/")
        self._client = client
        self._owns_client = client is None
        aliases = {
            source_name: VariableSemantic(canonical, standard_name)
            for canonical, (source_name, _, standard_name) in self._spec[
                "variables"
            ].items()
        }
        self._normalizer = SemanticNormalizer(aliases)

    @property
    def metadata(self) -> ConnectorMetadata:
        product_types = {
            OpenMeteoEndpoint.WEATHER: "weather_forecast",
            OpenMeteoEndpoint.HISTORICAL_WEATHER: "historical_weather_analysis",
            OpenMeteoEndpoint.CLIMATE: "climate_projection",
            OpenMeteoEndpoint.HYDROLOGY: "river_discharge_model",
        }
        capabilities = (self._spec["capability"],)
        if self.endpoint in {
            OpenMeteoEndpoint.WEATHER,
            OpenMeteoEndpoint.HISTORICAL_WEATHER,
        }:
            capabilities += ("meteorology",)
        if self.endpoint == OpenMeteoEndpoint.CLIMATE:
            capabilities += ("scientific_dataset",)
        if self.endpoint == OpenMeteoEndpoint.HYDROLOGY:
            capabilities += ("river_discharge",)
        return ConnectorMetadata(
            connector_id=f"open-meteo.{self.endpoint.value}",
            name=f"Open-Meteo {self.endpoint.value.replace('_', ' ')}",
            version="1",
            provider_version=None,
            capabilities=capabilities,
            health="unknown",
            available=True,
            supported_regions=(),
            supported_spatial_types=("point",),
            supports_temporal_query=True,
            supported_query_fields=("requested_dataset_ids",),
            supported_variables=tuple(self._spec["variables"]),
            modalities=infer_modalities(self._spec["variables"]),
            datasets=(
                DatasetReference(
                    connector_id=f"open-meteo.{self.endpoint.value}",
                    dataset_id=self._spec["dataset"],
                    uri=self._url,
                    metadata={
                        "variables": list(self._spec["variables"]),
                        "units": {
                            canonical: specification[1]
                            for canonical, specification in self._spec[
                                "variables"
                            ].items()
                        },
                        "modalities": list(infer_modalities(self._spec["variables"])),
                        "capabilities": list(capabilities),
                        **(
                            {
                                "supports_forecast": True,
                                "supports_historical": False,
                            }
                            if self.endpoint == OpenMeteoEndpoint.WEATHER
                            else {
                                "supports_historical": True,
                                "supports_forecast": False,
                            }
                            if self.endpoint == OpenMeteoEndpoint.HISTORICAL_WEATHER
                            else {}
                        ),
                    },
                ),
            ),
            provider_metadata={
                "provider": "Open-Meteo",
                "endpoint": self.endpoint.value,
                "product_type": product_types[self.endpoint],
                "modeled": True,
                "resolution": self._spec["key"],
            },
        )

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=None)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover(self) -> tuple[DatasetReference, ...]:
        return (
            DatasetReference(
                connector_id=self.metadata.connector_id,
                dataset_id=self._spec["dataset"],
                version=self.metadata.provider_version,
                uri=self._url,
                metadata={
                    **self.metadata.provider_metadata,
                    "variables": list(self.metadata.supported_variables),
                    "modalities": list(self.metadata.modalities),
                    "capabilities": list(self.metadata.capabilities),
                },
            ),
        )

    async def acquire(self, request: Mapping[str, Any]) -> Any:
        if self._client is None:
            raise ConnectorError(
                "Open-Meteo connector is not started.",
                context={"connector": self.metadata.connector_id},
            )
        try:
            response = await self._client.get(self._url, params=dict(request))
        except httpx.TimeoutException as exc:
            raise NetworkError(
                "Open-Meteo request timed out.",
                context={"connector": self.metadata.connector_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"Open-Meteo request failed: {exc}",
                context={"connector": self.metadata.connector_id},
            ) from exc
        if response.status_code == 429:
            raise RateLimitError(
                "Open-Meteo rate limit was reached.",
                context={"connector": self.metadata.connector_id},
                recoverable=True,
            )
        if response.status_code >= 500:
            raise NetworkError(
                f"Open-Meteo service returned HTTP {response.status_code}.",
                context={
                    "connector": self.metadata.connector_id,
                    "status_code": response.status_code,
                },
            )
        if response.is_error:
            raise ConnectorError(
                f"Open-Meteo rejected the request with HTTP {response.status_code}.",
                context={
                    "connector": self.metadata.connector_id,
                    "status_code": response.status_code,
                    "response": response.text[:1000],
                },
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ConnectorError(
                "Open-Meteo returned invalid JSON.",
                context={"connector": self.metadata.connector_id},
            ) from exc

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request, requested = self._build_request(query)
        payload = await self.fetch(request)
        if not isinstance(payload, Mapping):
            raise ConnectorError(
                "Open-Meteo response must be a JSON object.",
                context={"connector": self.metadata.connector_id},
            )
        rows = self._normalize_response(payload, query, request, requested)
        return ObservationSearchResult(
            observations=tuple(rows),
            matched=len(rows),
            context={
                "connector_id": self.metadata.connector_id,
                "dataset_id": self._spec["dataset"],
                "endpoint": self.endpoint.value,
            },
            source_document={
                "provider": "Open-Meteo",
                "endpoint": self.endpoint.value,
                "request": request,
                "response_metadata": self._response_metadata(payload),
                "provider_response": dict(payload),
            },
        )

    def _build_request(
        self, query: EarthQuery
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if (
            query.requested_dataset_ids
            and self._spec["dataset"] not in query.requested_dataset_ids
        ):
            raise ValidationError(
                "Requested dataset is not implemented by this Open-Meteo endpoint."
            )
        if query.point is None:
            raise ValidationError(
                "Open-Meteo point endpoints require a geographic point query.",
                context={"connector": self.metadata.connector_id},
            )
        if query.crs.casefold() not in {
            "crs84",
            "ogc:crs84",
            "epsg:4326",
            "urn:ogc:def:crs:ogc:1.3:crs84",
        }:
            raise ValidationError(
                "Open-Meteo point queries require OGC:CRS84 or EPSG:4326.",
                context={"connector": self.metadata.connector_id, "crs": query.crs},
            )
        if query.filters or query.asset_preferences or query.spatial_resolution is not None:
            raise ValidationError(
                "Open-Meteo does not support filters, asset preferences, or requested spatial resolution.",
                context={"connector": self.metadata.connector_id},
            )
        if (query.temporal_start is None) != (query.temporal_end is None):
            raise ValidationError(
                "Open-Meteo date-range queries require both temporal_start and temporal_end.",
                context={"connector": self.metadata.connector_id},
            )
        if self.endpoint in {
            OpenMeteoEndpoint.HISTORICAL_WEATHER,
            OpenMeteoEndpoint.CLIMATE,
            OpenMeteoEndpoint.HYDROLOGY,
        } and (query.temporal_start is None or query.temporal_end is None):
            raise ValidationError(
                f"{self.endpoint.value} requires both temporal_start and temporal_end.",
                context={"connector": self.metadata.connector_id},
            )
        available = self._spec["variables"]
        requested = query.requested_variables or self._spec["defaults"]
        unsupported = tuple(name for name in requested if name not in available)
        if unsupported:
            raise ValidationError(
                "Open-Meteo endpoint does not provide all requested variables.",
                context={
                    "connector": self.metadata.connector_id,
                    "unsupported_variables": unsupported,
                },
            )
        request: dict[str, Any] = {
            "latitude": query.point[1],
            "longitude": query.point[0],
            "timezone": "GMT",
        }
        if self.endpoint in {
            OpenMeteoEndpoint.WEATHER,
            OpenMeteoEndpoint.HISTORICAL_WEATHER,
        }:
            request["hourly"] = ",".join(available[name][0] for name in requested)
        else:
            request["daily"] = ",".join(available[name][0] for name in requested)
        if query.temporal_start is not None and query.temporal_end is not None:
            request["start_date"] = query.temporal_start.astimezone(
                timezone.utc
            ).date().isoformat()
            request["end_date"] = query.temporal_end.astimezone(
                timezone.utc
            ).date().isoformat()
        if self.endpoint == OpenMeteoEndpoint.WEATHER and query.temporal_start is None:
            request["forecast_days"] = 7
        return request, tuple(requested)

    def _normalize_response(
        self,
        payload: Mapping[str, Any],
        query: EarthQuery,
        request: Mapping[str, Any],
        requested: tuple[str, ...],
    ) -> list[Observation]:
        data_key = self._spec["key"]
        time_values = payload.get(data_key, {}).get("time")
        if not isinstance(time_values, list):
            raise ConnectorError(
                f"Open-Meteo response does not contain {data_key}.time.",
                context={"connector": self.metadata.connector_id},
            )
        data = payload[data_key]
        units = payload.get(f"{data_key}_units", {})
        if not isinstance(units, Mapping):
            units = {}
        row_values: dict[str, list[Any]] = {}
        for canonical in requested:
            source_name = self._spec["variables"][canonical][0]
            values = data.get(source_name)
            if not isinstance(values, list) or len(values) != len(time_values):
                raise ConnectorError(
                    f"Open-Meteo response variable {source_name!r} has no aligned time series.",
                    context={"connector": self.metadata.connector_id},
                )
            row_values[canonical] = values
        latitude = payload.get("latitude", query.point[1] if query.point else None)
        longitude = payload.get("longitude", query.point[0] if query.point else None)
        if not isinstance(latitude, (int, float)) or not isinstance(
            longitude, (int, float)
        ):
            raise ConnectorError(
                "Open-Meteo response omitted valid coordinates.",
                context={"connector": self.metadata.connector_id},
            )
        rows: list[Observation] = []
        for index, raw_time in enumerate(time_values):
            instant = self._parse_provider_time(raw_time)
            measured: dict[str, Any] = {}
            source_values: dict[str, Any] = {}
            missing: list[str] = []
            for canonical in requested:
                source_name, configured_unit, standard_name = self._spec["variables"][
                    canonical
                ]
                value = row_values[canonical][index]
                unit = units.get(source_name, configured_unit)
                measurement = self._normalizer.normalize_measurement(
                    source_name,
                    value,
                    unit=str(unit) if unit is not None else None,
                    metadata={"standard_name": standard_name}
                    if standard_name is not None
                    else None,
                )
                measured.update(measurement)
                source_values[source_name] = value
                if value is None:
                    missing.append(canonical)
            if query.temporal_start is not None and query.temporal_end is not None:
                if instant < query.temporal_start.astimezone(timezone.utc):
                    continue
                if instant > query.temporal_end.astimezone(timezone.utc):
                    continue
            is_daily = data_key == "daily"
            end = instant + timedelta(days=1) if is_daily else instant
            observations_source = {
                "provider": "Open-Meteo",
                "endpoint": self.endpoint.value,
                "provider_time": raw_time,
                "provider_values": source_values,
                "response_metadata": self._response_metadata(payload),
                "request": dict(request),
            }
            observation_type = (
                "weather_forecast"
                if self.endpoint == OpenMeteoEndpoint.WEATHER
                else "model_output"
            )
            quality = {"missing_values": missing} if missing else {}
            rows.append(
                Observation(
                    source_id=(
                        f"{self._spec['dataset']}:{latitude}:{longitude}:{raw_time}"
                    ),
                    dataset=DatasetReference(
                        connector_id=self.metadata.connector_id,
                        dataset_id=self._spec["dataset"],
                        version=self.metadata.provider_version,
                        uri=self._url,
                    ),
                    observed_at=instant,
                    geometry={
                        "type": "Point",
                        "coordinates": [float(longitude), float(latitude)],
                    },
                    crs="OGC:CRS84",
                    temporal_extent=TemporalExtent(start=instant, end=end),
                    observation_type=observation_type,
                    measured_variables=measured,
                    provider_metadata=self._response_metadata(payload),
                    quality=quality,
                    reproducibility={
                        "provider": "Open-Meteo",
                        "endpoint": self.endpoint.value,
                        "dataset_id": self._spec["dataset"],
                        "request_parameters": dict(request),
                        "timezone": "GMT",
                    },
                    properties={
                        "requested_point": list(query.point) if query.point else None,
                        "provider_coordinates": [float(longitude), float(latitude)],
                    },
                    source_document=observations_source,
                )
            )
        return rows

    @staticmethod
    def _parse_provider_time(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ConnectorError("Open-Meteo returned a non-string timestamp.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConnectorError(
                f"Open-Meteo returned an invalid timestamp: {value!r}."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if key not in {"hourly", "daily"}
        }
