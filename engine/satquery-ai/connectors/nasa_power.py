"""NASA POWER daily point data through canonical Earth observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from satquery.errors import (
    ConnectorError,
    NetworkError,
    RateLimitError,
    ValidationError,
)
from satquery.platform.connectors import ConnectorPolicy, PerceptionConnector
from satquery.platform.contracts import (
    CanonicalMeasurement,
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    Observation,
    ObservationSearchResult,
    TemporalExtent,
)
from satquery.platform.ontology import EARTH_VARIABLE_ONTOLOGY

_DEFAULT_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
_DATASET_ID = "nasa-power-daily-point"
_PARAMETERS: dict[str, tuple[str, str]] = {
    "air_temperature": ("T2M", "Air temperature at 2 m"),
    "precipitation_amount": ("PRECTOTCORR", "Corrected precipitation"),
    "relative_humidity": ("RH2M", "Relative humidity at 2 m"),
    "wind_speed": ("WS10M", "Wind speed at 10 m"),
    "surface_air_pressure": ("PS", "Surface air pressure"),
}
_COMMUNITIES = {"AG", "RE", "SB"}


class NasaPowerDailyConnector(PerceptionConnector):
    """Acquire source-reported NASA POWER daily values at an explicit point.

    This adapter requests UTC daily records only. It never treats the gridded
    POWER product as an in-situ station measurement and does not derive values,
    uncertainty, or confidence.
    """

    def __init__(
        self,
        *,
        configuration: Mapping[str, Any] | None = None,
        policy: ConnectorPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            configuration=configuration,
            policy=policy
            or ConnectorPolicy(timeout_seconds=45, max_attempts=2, retry_safe=True),
        )
        config = dict(configuration or {})
        self.connector_id = str(config.get("connector_id", "nasa-power-daily"))
        self.endpoint_url = str(config.get("endpoint_url", _DEFAULT_URL)).rstrip("?")
        self.community = str(config.get("community", "AG")).upper()
        self.maximum_days = config.get("maximum_days", 18263)
        self._transport = transport
        self._client = client
        self._owns_client = client is None
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        parsed = urlsplit(self.endpoint_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("NASA POWER endpoint_url contains an invalid port.") from exc
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.hostname != "power.larc.nasa.gov"
            or parsed.path != "/api/temporal/daily/point"
            or port not in {None, 443}
        ):
            raise ValidationError(
                "NASA POWER endpoint_url must use the official HTTPS daily point endpoint without credentials, query, or fragment."
            )
        if not self.connector_id.strip():
            raise ValidationError("NASA POWER connector_id must not be empty.")
        if self.community not in _COMMUNITIES:
            raise ValidationError(
                "NASA POWER community must be one of AG, RE, or SB."
            )
        if (
            isinstance(self.maximum_days, bool)
            or not isinstance(self.maximum_days, int)
            or self.maximum_days < 1
        ):
            raise ValidationError("NASA POWER maximum_days must be a positive integer.")

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name="NASA POWER daily point products",
            version="1.0.0",
            capabilities=("daily_climate", "meteorology", "agroclimatology"),
            modalities=("atmospheric",),
            supports_temporal_query=True,
            supported_spatial_types=("point",),
            supported_query_fields=("requested_dataset_ids", "filters"),
            supported_variables=tuple(_PARAMETERS),
            datasets=(
                DatasetReference(
                    connector_id=self.connector_id,
                    dataset_id=_DATASET_ID,
                    uri=self.endpoint_url,
                    metadata={
                        "provider": "NASA Langley Research Center POWER Project",
                        "variables": tuple(_PARAMETERS),
                        "modalities": ["atmospheric"],
                        "capabilities": ["daily_climate", "meteorology", "agroclimatology"],
                        "supports_historical": True,
                        "supports_forecast": False,
                        "historical_coverage": {
                            "start": datetime(1981, 1, 1, tzinfo=timezone.utc).isoformat(),
                            "end": None,
                        },
                        "access_policy": {
                            "credentials_required": False,
                            "point_query_required": True,
                            "utc_daily_records": True,
                            "community": self.community,
                            "maximum_days_per_query": self.maximum_days,
                            "limitations": [
                                "Supported parameter availability depends on the selected POWER community.",
                                "Spatial resolution varies by parameter and source; no single resolution is declared.",
                                "Near-real-time records may later be replaced by climate-quality products.",
                                "Repeated requests for the same relative location may be rate limited by NASA POWER.",
                            ],
                        },
                        "citation": "NASA Prediction Of Worldwide Energy Resources (POWER) Project",
                        "documentation_url": "https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
                        "parameter_dictionary_url": "https://power.larc.nasa.gov/parameters/",
                        "configured_community": self.community,
                    },
                ),
            ),
            configuration_schema={
                "type": "object",
                "properties": {
                    "connector_id": {"type": "string", "minLength": 1},
                    "endpoint_url": {"type": "string", "format": "uri"},
                    "community": {"type": "string", "enum": sorted(_COMMUNITIES)},
                    "maximum_days": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
            provider_metadata={
                "provider": "NASA Langley Research Center POWER Project",
                "endpoint": self.endpoint_url,
                "temporal_resolution": "daily",
                "time_standard": "UTC",
                "community": self.community,
                "parameter_codes": {
                    canonical: source for canonical, (source, _) in _PARAMETERS.items()
                },
                "documentation_url": "https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
            },
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

    async def discover(self) -> tuple[DatasetReference, ...]:
        return self.metadata.datasets

    async def acquire(self, request: Mapping[str, Any]) -> Any:
        if self._client is None:
            raise ConnectorError("NASA POWER connector has not been started.")
        try:
            response = await self._client.get(self.endpoint_url, params=dict(request))
        except httpx.TimeoutException as exc:
            raise NetworkError(
                "NASA POWER request timed out.",
                context={"connector": self.connector_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"NASA POWER request failed: {exc}",
                context={"connector": self.connector_id},
            ) from exc
        if response.status_code == 429:
            raise RateLimitError(
                "NASA POWER rate limit was reached.",
                context={"connector": self.connector_id},
                recoverable=True,
            )
        if response.status_code >= 500:
            raise NetworkError(
                f"NASA POWER returned HTTP {response.status_code}.",
                context={"connector": self.connector_id, "status_code": response.status_code},
            )
        if response.is_error:
            raise ConnectorError(
                f"NASA POWER rejected the query with HTTP {response.status_code}.",
                context={
                    "connector": self.connector_id,
                    "status_code": response.status_code,
                    "response": response.text[:1000],
                },
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError("NASA POWER returned invalid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise ConnectorError("NASA POWER response must be a JSON object.")
        messages = payload.get("messages")
        if isinstance(messages, list) and messages:
            raise ConnectorError(
                "NASA POWER returned provider messages for the request.",
                context={"messages": messages[:10]},
            )
        return payload

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request, variables = self._build_request(query)
        payload = await self.fetch(request)
        observations = self._observations(payload, query, request, variables)
        return ObservationSearchResult(
            observations=observations,
            matched=len(observations),
            context={
                "connector_id": self.connector_id,
                "dataset_id": _DATASET_ID,
                "community": request["community"],
                "time_standard": "UTC",
                "requested_parameter_codes": tuple(
                    _PARAMETERS[variable][0] for variable in variables
                ),
            },
            source_document={
                "provider": "NASA POWER",
                "request_parameters": request,
                "response_metadata": _response_metadata(payload),
            },
        )

    def _build_request(self, query: EarthQuery) -> tuple[dict[str, Any], tuple[str, ...]]:
        if query.requested_dataset_ids and _DATASET_ID not in query.requested_dataset_ids:
            raise ValidationError("Requested dataset is not implemented by NASA POWER.")
        if query.point is None:
            raise ValidationError("NASA POWER daily acquisition requires an explicit point.")
        if query.crs.casefold() not in {"ogc:crs84", "crs84", "epsg:4326"}:
            raise ValidationError("NASA POWER point queries require OGC:CRS84 or EPSG:4326.")
        if query.bbox is not None or query.geometry is not None:
            raise ValidationError("NASA POWER daily point service does not represent area queries.")
        if query.spatial_resolution is not None or query.asset_preferences:
            raise ValidationError("NASA POWER does not accept requested spatial resolution or asset preferences.")
        if query.temporal_start is None or query.temporal_end is None:
            raise ValidationError("NASA POWER daily acquisition requires explicit start and end times.")
        start = query.temporal_start.astimezone(timezone.utc)
        end = query.temporal_end.astimezone(timezone.utc)
        if end < start:
            raise ValidationError("NASA POWER temporal_end must not precede temporal_start.")
        if any(
            (instant.hour, instant.minute, instant.second, instant.microsecond)
            for instant in (start, end)
        ):
            raise ValidationError(
                "NASA POWER daily queries require UTC day-boundary timestamps."
            )
        day_count = (end.date() - start.date()).days + 1
        if day_count > self.maximum_days:
            raise ValidationError(
                "NASA POWER query exceeds its configured maximum duration.",
                context={"maximum_days": self.maximum_days, "requested_days": day_count},
            )
        unsupported_filters = set(query.filters).difference({"power_community"})
        if unsupported_filters:
            raise ValidationError(
                "NASA POWER received unsupported filters.",
                context={"unsupported_filters": sorted(unsupported_filters)},
            )
        community = str(query.filters.get("power_community", self.community)).upper()
        if community not in _COMMUNITIES:
            raise ValidationError("power_community must be AG, RE, or SB.")
        requested = query.requested_variables or tuple(_PARAMETERS)
        canonical_by_alias = {name.casefold(): name for name in _PARAMETERS}
        for canonical, (source, _) in _PARAMETERS.items():
            canonical_by_alias[source.casefold()] = canonical
        normalized = tuple(canonical_by_alias.get(value.casefold(), "") for value in requested)
        unsupported = tuple(value for value, canonical in zip(requested, normalized, strict=True) if not canonical)
        if unsupported:
            raise ValidationError(
                "NASA POWER connector does not declare all requested variables.",
                context={"unsupported_variables": unsupported},
            )
        variables = tuple(dict.fromkeys(normalized))
        if len(variables) != len(normalized):
            raise ValidationError("NASA POWER query contains duplicate variable aliases.")
        request = {
            "parameters": ",".join(_PARAMETERS[name][0] for name in variables),
            "community": community,
            "longitude": query.point[0],
            "latitude": query.point[1],
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }
        return request, variables

    def _observations(
        self,
        payload: Mapping[str, Any],
        query: EarthQuery,
        request: Mapping[str, Any],
        variables: tuple[str, ...],
    ) -> tuple[Observation, ...]:
        header = payload.get("header")
        parameter_metadata = payload.get("parameters")
        if not isinstance(header, Mapping) or not isinstance(parameter_metadata, Mapping):
            raise ConnectorError("NASA POWER response omitted its header or parameter metadata.")
        fill_value = header.get("fill_value")
        if isinstance(fill_value, bool) or not isinstance(fill_value, (int, float)) or not math.isfinite(fill_value):
            raise ConnectorError("NASA POWER response does not declare a finite fill_value.")
        parameter_values = _parameter_values(payload)
        expected_codes = tuple(_PARAMETERS[name][0] for name in variables)
        request_start = datetime.strptime(str(request["start"]), "%Y%m%d").replace(
            tzinfo=timezone.utc
        )
        request_end = datetime.strptime(str(request["end"]), "%Y%m%d").replace(
            tzinfo=timezone.utc
        )
        missing_parameters = tuple(code for code in expected_codes if code not in parameter_values)
        if missing_parameters:
            raise ConnectorError(
                "NASA POWER response omitted requested parameter time series.",
                context={"missing_parameters": missing_parameters},
            )
        dates: set[str] = set()
        for code in expected_codes:
            values = parameter_values[code]
            if not isinstance(values, Mapping):
                raise ConnectorError(f"NASA POWER parameter {code!r} has no dated values.")
            dates.update(str(day) for day in values)

        observations: list[Observation] = []
        for raw_day in sorted(dates):
            try:
                day = datetime.strptime(raw_day, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise ConnectorError(f"NASA POWER returned invalid date key {raw_day!r}.") from exc
            if not request_start <= day <= request_end:
                continue
            measured: dict[str, Any] = {}
            canonical_measurements: list[CanonicalMeasurement] = []
            missing: list[str] = []
            raw_values: dict[str, Any] = {}
            day_identity = hashlib.sha256(
                json.dumps(
                    [
                        self.connector_id,
                        request["longitude"],
                        request["latitude"],
                        raw_day,
                        expected_codes,
                    ],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:24]
            for canonical, code in zip(variables, expected_codes, strict=True):
                raw = parameter_values[code].get(raw_day)
                metadata = parameter_metadata.get(code)
                if not isinstance(metadata, Mapping):
                    raise ConnectorError(f"NASA POWER omitted metadata for parameter {code!r}.")
                unit = metadata.get("units")
                unit = unit.strip() if isinstance(unit, str) and unit.strip() else None
                if raw is None:
                    value = None
                    missing.append(canonical)
                elif isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
                    raise ConnectorError(f"NASA POWER returned a non-finite value for {code!r}.")
                elif float(raw) == float(fill_value):
                    value = None
                    missing.append(canonical)
                else:
                    value = raw
                source_metadata = {
                    "parameter_code": code,
                    "longname": metadata.get("longname"),
                    "provider_units": unit,
                    "community": request["community"],
                    "fill_value": fill_value,
                    "time_standard": "UTC",
                }
                measured[code] = {
                    "value": value,
                    "unit": unit,
                    "source_name": code,
                    "source_unit": unit,
                    "source_metadata": source_metadata,
                }
                earth_variable = EARTH_VARIABLE_ONTOLOGY.resolve_variable(canonical)
                canonical_measurements.append(
                    CanonicalMeasurement(
                        canonical_variable=canonical,
                        value=value,
                        unit=unit,
                        source_variable=code,
                        source_unit=unit,
                        ontology_uri=(
                            earth_variable.ontology_uri
                            if earth_variable is not None
                            else None
                        ),
                        semantic_status=("resolved" if earth_variable is not None else "unresolved"),
                        source_metadata=source_metadata,
                        observation_id=f"nasa-power:{day_identity}",
                    )
                )
                raw_values[code] = raw
            day_end = day + timedelta(days=1)
            observations.append(
                Observation(
                    observation_id=f"nasa-power:{day_identity}",
                    source_id=f"{_DATASET_ID}:{request['longitude']}:{request['latitude']}:{raw_day}",
                    dataset=DatasetReference(
                        connector_id=self.connector_id,
                        dataset_id=_DATASET_ID,
                        uri=self.endpoint_url,
                    ),
                    observed_at=day,
                    geometry={"type": "Point", "coordinates": [request["longitude"], request["latitude"]]},
                    crs="OGC:CRS84",
                    temporal_extent=TemporalExtent(start=day, end=day_end),
                    observation_type="daily_environmental_product",
                    measured_variables=measured,
                    canonical_measurements=tuple(canonical_measurements),
                    provider_metadata={
                        "provider": "NASA POWER",
                        "header": dict(header),
                        "parameters": {
                            code: dict(parameter_metadata[code]) for code in expected_codes
                        },
                    },
                    quality={"missing_values": tuple(missing)} if missing else {},
                    uncertainty={"status": "not_reported_in_response"},
                    reproducibility={
                        "connector_id": self.connector_id,
                        "connector_version": self.metadata.version,
                        "request_parameters": dict(request),
                        "source_date": raw_day,
                    },
                    properties={
                        "requested_point": query.point,
                        "daily_product": True,
                        "source_time_standard": "UTC",
                    },
                    source_document={
                        "header": dict(header),
                        "parameter_values": raw_values,
                        "parameter_metadata": {
                            code: dict(parameter_metadata[code]) for code in expected_codes
                        },
                    },
                )
            )
        return tuple(observations)


def _parameter_values(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    properties = payload.get("properties")
    if isinstance(properties, Mapping) and isinstance(properties.get("parameter"), Mapping):
        return properties["parameter"]
    feature = payload.get("feature")
    if isinstance(feature, Mapping):
        feature_properties = feature.get("properties")
        if isinstance(feature_properties, Mapping) and isinstance(feature_properties.get("parameter"), Mapping):
            return feature_properties["parameter"]
    features = payload.get("features")
    if isinstance(features, list) and len(features) == 1 and isinstance(features[0], Mapping):
        feature_properties = features[0].get("properties")
        if isinstance(feature_properties, Mapping) and isinstance(feature_properties.get("parameter"), Mapping):
            return feature_properties["parameter"]
    raise ConnectorError("NASA POWER response omitted its parameter time-series object.")


def _response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"properties", "feature", "features"}
    }
