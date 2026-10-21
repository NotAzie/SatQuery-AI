"""NOAA CO-OPS in-situ coastal water-level observations."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
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
    ConnectorMetadata,
    DatasetReference,
    EarthObjectCandidate,
    EarthQuery,
    Observation,
    ObservationSearchResult,
    TemporalExtent,
)

_DATA_API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
_METADATA_API = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi"
_DATASET_ID = "noaa-coops-water-level"
_VARIABLE = "coastal_water_level"
_MAX_QUERY_DAYS = 30


class NoaaCoopsConnector(PerceptionConnector):
    """Acquire station-specific coastal water-level records from NOAA CO-OPS.

    A station identifier is required explicitly in ``EarthQuery.filters`` or
    connector configuration. The adapter does not silently choose a nearest
    station or treat that station as representative of a requested area.
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
                timeout_seconds=30,
                max_attempts=2,
                retry_safe=True,
                retry_delay_seconds=0.2,
            ),
        )
        config = dict(configuration or {})
        self.connector_id = str(config.get("connector_id", "noaa-coops-water-level"))
        self.station_id = config.get("station_id")
        self.datum = config.get("datum", "MLLW")
        self.data_api_url = config.get("data_api_url", _DATA_API)
        self.metadata_api_url = config.get("metadata_api_url", _METADATA_API)
        self._transport = transport
        self._client = client
        self._owns_client = client is None
        self._validate_configuration()

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name="NOAA CO-OPS coastal water levels",
            version="1",
            capabilities=("oceanographic_observation", "coastal_water_level"),
            modalities=("oceanic",),
            supported_variables=(_VARIABLE,),
            supports_temporal_query=True,
            supported_query_fields=("filters", "requested_dataset_ids"),
            datasets=(
                DatasetReference(
                    connector_id=self.connector_id,
                    dataset_id=_DATASET_ID,
                    uri=self.data_api_url,
                    metadata={
                        "provider": "NOAA CO-OPS",
                        "variables": [_VARIABLE],
                        "units": {_VARIABLE: "m"},
                        "modalities": ["oceanic"],
                        "capabilities": [
                            "oceanographic_observation",
                            "coastal_water_level",
                        ],
                        "supports_historical": True,
                        "access_policy": {
                            "station_id_required": True,
                            "limitations": [
                                "NOAA CO-OPS station coverage only",
                                "Queries are limited to 30 days per request",
                                "Water levels are referenced to the requested "
                                "tidal datum",
                            ],
                        },
                        "citation": (
                            "NOAA Center for Operational Oceanographic Products "
                            "and Services (CO-OPS)"
                        ),
                        "metadata_api": self.metadata_api_url,
                        "data_api": self.data_api_url,
                    },
                ),
            ),
            provider_version=None,
            provider_metadata={
                "provider": "NOAA CO-OPS",
                "program": "Center for Operational Oceanographic Products and Services",
                "data_api": self.data_api_url,
                "metadata_api": self.metadata_api_url,
                "documentation_url": "https://api.tidesandcurrents.noaa.gov/api/prod/",
                "response_help_url": "https://api.tidesandcurrents.noaa.gov/api/prod/responseHelp.html",
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
        """Expose the adapter's declared water-level product without a request."""
        return self.metadata.datasets

    async def acquire(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return the raw NOAA JSON payload for a validated station request."""
        station_id = self._station_id(request.get("station_id"))
        start = self._date_parameter(request.get("begin_date"), "begin_date")
        end = self._date_parameter(request.get("end_date"), "end_date")
        if end <= start:
            raise ValidationError("NOAA CO-OPS end_date must follow begin_date.")
        if (end - start).total_seconds() > _MAX_QUERY_DAYS * 86400:
            raise ValidationError(
                "NOAA CO-OPS water-level requests are limited to 30 days.",
                context={"maximum_days": _MAX_QUERY_DAYS},
            )
        params = {
            "station": station_id,
            "product": "water_level",
            "begin_date": start.strftime("%Y%m%d %H:%M"),
            "end_date": end.strftime("%Y%m%d %H:%M"),
            "datum": self.datum,
            "time_zone": "gmt",
            "units": "metric",
            "application": "SatQuery",
            "format": "json",
        }
        return await self._get_json(self.data_api_url, params, "water-level data")

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request = self._request_from_query(query)
        station = await self._station_metadata(request["station_id"])
        payload = await self.acquire(request)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ConnectorError(
                "NOAA CO-OPS response is missing its data array.",
                context={"connector": self.connector_id},
            )
        latitude, longitude = self._station_coordinates(station)
        observations = tuple(
            self._observation(row, station, latitude, longitude, request, payload)
            for row in rows
            if isinstance(row, Mapping)
        )
        if len(observations) != len(rows):
            raise ConnectorError(
                "NOAA CO-OPS response contains a non-object data record.",
                context={"connector": self.connector_id},
            )
        return ObservationSearchResult(
            observations=observations,
            matched=len(observations),
            context={
                "provider": "NOAA CO-OPS",
                "station_id": request["station_id"],
                "product": "water_level",
                "datum": self.datum,
                "units": payload.get("units"),
                "record_count": len(observations),
            },
        )

    def _request_from_query(self, query: EarthQuery) -> dict[str, Any]:
        unsupported = tuple(
            field
            for field in (
                "bbox",
                "point",
                "geometry",
                "spatial_resolution",
                "asset_preferences",
            )
            if (
                getattr(query, field) is not None
                and (field != "asset_preferences" or bool(query.asset_preferences))
            )
        )
        if unsupported:
            raise ValidationError(
                "NOAA CO-OPS observations are station based and do not satisfy "
                "spatial geometry queries.",
                context={"unsupported_fields": unsupported},
            )
        if query.temporal_start is None or query.temporal_end is None:
            raise ValidationError(
                "NOAA CO-OPS acquisition requires both temporal_start and "
                "temporal_end.",
                remediation=[
                    "Provide an explicit UTC time interval of at most 30 days."
                ],
            )
        filters = dict(query.filters)
        unknown_filters = set(filters).difference({"station_id"})
        if unknown_filters:
            raise ValidationError(
                "NOAA CO-OPS does not support the requested query filters.",
                context={"unsupported_filters": sorted(unknown_filters)},
            )
        requested = query.requested_variables or (_VARIABLE,)
        if any(
            value.casefold() not in {_VARIABLE, "water_level"} for value in requested
        ):
            raise ValidationError(
                "NOAA CO-OPS water-level adapter does not provide every "
                "requested variable.",
                context={"requested_variables": requested},
            )
        if query.requested_dataset_ids and not any(
            value in {_DATASET_ID, f"{self.connector_id}:{_DATASET_ID}"}
            for value in query.requested_dataset_ids
        ):
            raise ValidationError(
                "NOAA CO-OPS adapter does not provide the requested dataset.",
                context={"requested_dataset_ids": query.requested_dataset_ids},
            )
        start = query.temporal_start.astimezone(timezone.utc)
        end = query.temporal_end.astimezone(timezone.utc)
        if end <= start:
            raise ValidationError("NOAA CO-OPS end time must follow start time.")
        if (end - start).total_seconds() > _MAX_QUERY_DAYS * 86400:
            raise ValidationError(
                "NOAA CO-OPS water-level requests are limited to 30 days.",
                context={"maximum_days": _MAX_QUERY_DAYS},
            )
        station_id = self._station_id(filters.get("station_id"))
        return {
            "station_id": station_id,
            "begin_date": start,
            "end_date": end,
        }

    async def _station_metadata(self, station_id: str) -> Mapping[str, Any]:
        url = f"{self.metadata_api_url.rstrip('/')}/stations/{station_id}.json"
        payload = await self._get_json(url, {}, "station metadata")
        stations = payload.get("stations")
        if (
            not isinstance(stations, list)
            or not stations
            or not isinstance(stations[0], Mapping)
        ):
            raise ConnectorError(
                f"NOAA CO-OPS returned no metadata for station {station_id!r}.",
                context={"connector": self.connector_id, "station_id": station_id},
            )
        station = stations[0]
        if str(station.get("id", "")) != station_id:
            raise ConnectorError(
                "NOAA CO-OPS station metadata identifier did not match the request.",
                context={"connector": self.connector_id, "station_id": station_id},
            )
        return station

    async def _get_json(
        self,
        url: str,
        params: Mapping[str, Any],
        description: str,
    ) -> Mapping[str, Any]:
        if self._client is None:
            raise ConnectorError(
                "NOAA CO-OPS connector has not been started.",
                context={"connector": self.connector_id},
            )
        try:
            response = await self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise NetworkError(
                f"NOAA CO-OPS {description} request timed out.",
                context={"connector": self.connector_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"NOAA CO-OPS {description} request failed: {exc}",
                context={"connector": self.connector_id},
            ) from exc
        if response.status_code == 429:
            raise RateLimitError(
                "NOAA CO-OPS rate limited the request.",
                context={"connector": self.connector_id},
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"NOAA CO-OPS {description} returned HTTP {response.status_code}.",
                context={
                    "connector": self.connector_id,
                    "status_code": response.status_code,
                },
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError(
                f"NOAA CO-OPS {description} response is not valid JSON.",
                context={"connector": self.connector_id},
            ) from exc
        if not isinstance(payload, Mapping):
            raise ConnectorError(
                f"NOAA CO-OPS {description} response must be a JSON object.",
                context={"connector": self.connector_id},
            )
        error = payload.get("error")
        if isinstance(error, Mapping):
            raise ConnectorError(
                f"NOAA CO-OPS {description} request was rejected.",
                context={
                    "connector": self.connector_id,
                    "provider_error": dict(error),
                },
            )
        return payload

    def _observation(
        self,
        row: Mapping[str, Any],
        station: Mapping[str, Any],
        latitude: float,
        longitude: float,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> Observation:
        raw_time = row.get("t")
        if not isinstance(raw_time, str):
            raise ConnectorError("NOAA CO-OPS record is missing its timestamp.")
        observed_at = self._parse_time(raw_time)
        raw_value = row.get("v")
        value: Optional[float]
        if raw_value in (None, "", "-"):
            value = None
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ConnectorError(
                    "NOAA CO-OPS water-level value is not numeric.",
                    context={
                        "station_id": request["station_id"],
                        "timestamp": raw_time,
                    },
                ) from exc
            if not math.isfinite(value):
                raise ConnectorError("NOAA CO-OPS water-level value is not finite.")
        sigma = self._optional_finite_number(row.get("s"))
        flags = row.get("f")
        quality: dict[str, Any] = {}
        if flags is not None:
            quality["provider_data_flags"] = flags
        if row.get("q") is not None:
            quality["provider_qa_qc_level"] = row["q"]
        if value is None:
            quality["missing_values"] = [_VARIABLE]
        source_document = dict(row)
        station_identity = str(request["station_id"])
        observation_digest = hashlib.sha256(
            json.dumps(
                {
                    "row": source_document,
                    "station": dict(station),
                    "datum": self.datum,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        dataset_reference = DatasetReference(
            connector_id=self.connector_id,
            dataset_id=_DATASET_ID,
            uri=self.data_api_url,
            metadata={"station_id": request["station_id"], "datum": self.datum},
        )
        return Observation(
            observation_id=f"noaa-coops:{station_identity}:{observation_digest}",
            source_id=(
                f"{request['station_id']}:{_DATASET_ID}:{raw_time}:{self.datum}"
            ),
            dataset=dataset_reference,
            observed_at=observed_at,
            temporal_extent=TemporalExtent(start=observed_at, end=observed_at),
            geometry={"type": "Point", "coordinates": [longitude, latitude]},
            crs="OGC:CRS84",
            observation_type="in_situ_water_level",
            earth_object_candidate=EarthObjectCandidate(
                identity_namespace="tidesandcurrents.noaa.gov",
                identity_value=station_identity,
                object_type="earth:CoastalWaterLevelStation",
                declared_by=self.connector_id,
                mapping_id="noaa-coops-explicit-station-record@1.0.0",
                provenance={
                    "classification_basis": "explicit NOAA CO-OPS station metadata",
                    "source_attributes": dict(station),
                    "limitations": (
                        "The object represents a provider-identified monitoring station, not a hydrological conclusion.",
                        "Station status and lifecycle are not inferred from water-level samples.",
                    ),
                },
            ),
            measured_variables={
                _VARIABLE: {
                    "value": value,
                    "unit": "m",
                    "source_unit": "m",
                    "source_units_system": response.get("units", "metric"),
                    "source_name": "v",
                    "datum": self.datum,
                    **(
                        {
                            "source_sigma": {
                                "value": sigma,
                                "unit": "m",
                                "definition": (
                                    "Provider-reported standard deviation of "
                                    "one-second samples used to compute this "
                                    "water-level height."
                                ),
                            }
                        }
                        if sigma is not None
                        else {}
                    ),
                }
            },
            modalities=("oceanic",),
            provenance={
                "provider": "NOAA CO-OPS",
                "station_id": request["station_id"],
                "station_name": station.get("name"),
                "product": "water_level",
                "datum": self.datum,
                "time_zone": "gmt",
                "request": {
                    "station": request["station_id"],
                    "begin_date": request["begin_date"].isoformat(),
                    "end_date": request["end_date"].isoformat(),
                    "product": "water_level",
                    "datum": self.datum,
                    "time_zone": "gmt",
                    "units": "metric",
                },
            },
            provider_metadata={
                "provider": "NOAA CO-OPS",
                "station": dict(station),
                "product": "water_level",
                "datum": self.datum,
                "units": response.get("units"),
                "response_metadata": response.get("metadata", {}),
            },
            quality=quality,
            source_document=source_document,
        )

    def _station_id(self, value: Any) -> str:
        station_id = self.station_id if value is None else value
        if not isinstance(station_id, str) or not station_id.strip():
            raise ValidationError(
                "NOAA CO-OPS requires an explicit station_id filter or "
                "configured station_id."
            )
        station_id = station_id.strip()
        if len(station_id) > 16 or not all(
            character.isalnum() or character in "-_" for character in station_id
        ):
            raise ValidationError("NOAA CO-OPS station_id has an invalid format.")
        return station_id

    @staticmethod
    def _date_parameter(value: Any, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValidationError(
                f"NOAA CO-OPS {field} must be a timezone-aware datetime."
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError as exc:
            raise ConnectorError(
                f"NOAA CO-OPS timestamp {value!r} is invalid."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _station_coordinates(station: Mapping[str, Any]) -> tuple[float, float]:
        try:
            latitude = float(station["lat"])
            longitude = float(station["lng"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError(
                "NOAA CO-OPS station metadata has no valid coordinates."
            ) from exc
        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ConnectorError("NOAA CO-OPS station coordinates are out of range.")
        return latitude, longitude

    @staticmethod
    def _optional_finite_number(value: Any) -> Optional[float]:
        if value in (None, "", "-"):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _validate_configuration(self) -> None:
        if not isinstance(self.connector_id, str) or not self.connector_id.strip():
            raise ValidationError("NOAA CO-OPS connector_id must be non-empty.")
        if self.station_id is not None:
            self._station_id(self.station_id)
        if not isinstance(self.datum, str) or self.datum not in {
            "MLLW",
            "MHHW",
            "MHW",
            "MTL",
            "MSL",
            "MLW",
            "NAVD",
            "STND",
        }:
            raise ValidationError("NOAA CO-OPS datum must be a supported tidal datum.")
        for field, url in (
            ("data_api_url", self.data_api_url),
            ("metadata_api_url", self.metadata_api_url),
        ):
            parsed = urlsplit(url) if isinstance(url, str) else None
            if (
                parsed is None
                or parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValidationError(f"NOAA CO-OPS {field} must be a valid HTTPS URL.")
