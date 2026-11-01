"""USGS daily stream-discharge statistics through the modern OGC API."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx

from satquery.errors import ConnectorError, NetworkError, RateLimitError, ValidationError
from satquery.platform.connectors import ConnectorPolicy, PerceptionConnector
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    Observation,
    ObservationSearchResult,
    TemporalExtent,
)

_DATASET_ID = "usgs-daily-values-river-discharge"
_VARIABLE = "river_discharge"
_PARAMETER_CODE = "00060"
_DEFAULT_ITEMS_URL = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items"
_CRS84 = {"OGC:CRS84", "CRS84", "urn:ogc:def:crs:OGC:1.3:CRS84"}


class UsgsDailyDischargeConnector(PerceptionConnector):
    """Acquire daily discharge statistics at USGS monitoring locations.

    The adapter requires an explicit daily statistic ID. Users may scope a
    request by an explicit USGS monitoring location or a CRS84 bounding box.
    It never substitutes instantaneous measurements or treats station records
    as spatially continuous discharge fields.
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
        self.connector_id = str(config.get("connector_id", "usgs-water-daily"))
        self.items_url = config.get("items_url", _DEFAULT_ITEMS_URL)
        self.page_size = _positive_int(config.get("page_size", 500), "page_size")
        self.maximum_records = _positive_int(
            config.get("maximum_records", 5000), "maximum_records"
        )
        if self.page_size > self.maximum_records:
            raise ValueError("page_size cannot exceed maximum_records")
        self._transport = transport
        self._client = client
        self._owns_client = client is None
        self._validate_configuration()

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name="USGS daily river discharge statistics",
            version="1.0.0",
            capabilities=("in_situ_hydrology", "daily_discharge"),
            modalities=("hydrological",),
            supported_variables=(_VARIABLE,),
            supports_temporal_query=True,
            supported_query_fields=("bbox", "filters", "requested_dataset_ids"),
            supported_spatial_types=("bbox",),
            datasets=(
                DatasetReference(
                    connector_id=self.connector_id,
                    dataset_id=_DATASET_ID,
                    uri=self.items_url,
                    metadata={
                        "provider": "U.S. Geological Survey",
                        "variables": [_VARIABLE],
                        "modalities": ["hydrological"],
                        "capabilities": ["in_situ_hydrology", "daily_discharge"],
                        "parameter_code": _PARAMETER_CODE,
                        "statistic_selection_required": True,
                        "coverage_boundary_description": "United States monitoring network; exact station coverage varies.",
                        "access_policy": {
                            "temporal_start_and_end_required": True,
                            "daily_statistic_id_required": True,
                            "scope_required": "monitoring_location_id or CRS84 bbox",
                            "maximum_records_per_query": self.maximum_records,
                        },
                        "citation": "U.S. Geological Survey Water Data APIs, Daily Values collection",
                        "documentation_url": "https://api.waterdata.usgs.gov/docs/ogcapi/",
                    },
                ),
            ),
            provider_metadata={
                "provider": "U.S. Geological Survey",
                "service": "Water Data OGC API",
                "collection": "daily",
                "items_url": self.items_url,
                "documentation_url": "https://api.waterdata.usgs.gov/docs/ogcapi/",
            },
        )

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.policy.timeout_seconds or 30,
                transport=self._transport,
                follow_redirects=False,
            )

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def discover(self) -> tuple[DatasetReference, ...]:
        return self.metadata.datasets

    async def acquire(self, request: Mapping[str, Any]) -> Any:
        if self._client is None:
            raise ConnectorError("USGS Water Data connector has not been started.")
        return await self._get_json(str(request["url"]), request.get("params"))

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request = self._request_from_query(query)
        if self._client is None:
            raise ConnectorError("USGS Water Data connector has not been started.")

        features: list[Mapping[str, Any]] = []
        url: Optional[str] = self.items_url
        params: Optional[Mapping[str, Any]] = request["params"]
        matched: Optional[int] = None
        truncated = False
        pages = 0
        while url is not None and len(features) < self.maximum_records:
            if pages >= math.ceil(self.maximum_records / self.page_size) + 1:
                truncated = True
                break
            self._validate_next_url(url)
            payload = await self._get_json(url, params)
            params = None
            pages += 1
            page_features = payload.get("features")
            if not isinstance(page_features, list) or any(
                not isinstance(feature, Mapping) for feature in page_features
            ):
                raise ConnectorError(
                    "USGS Water Data response is missing its GeoJSON features array.",
                    context={"connector": self.connector_id},
                )
            features.extend(page_features)
            total = payload.get("numberMatched")
            if matched is None and isinstance(total, int) and total >= 0:
                matched = total
            next_url = next(
                (
                    link.get("href")
                    for link in payload.get("links", ())
                    if isinstance(link, Mapping) and link.get("rel") == "next"
                ),
                None,
            )
            if next_url is not None and not isinstance(next_url, str):
                raise ConnectorError("USGS Water Data next link is not a URL string.")
            url = next_url
            if len(features) > self.maximum_records:
                features = features[: self.maximum_records]
                truncated = True
                break
        if url is not None:
            truncated = True

        observations = tuple(
            self._observation(feature, request)
            for feature in features[: self.maximum_records]
        )
        if matched is None:
            matched = len(observations)
        return ObservationSearchResult(
            observations=observations,
            matched=matched,
            context={
                "provider": "U.S. Geological Survey",
                "dataset_id": _DATASET_ID,
                "parameter_code": _PARAMETER_CODE,
                "statistic_id": request["statistic_id"],
                "pages_read": pages,
                "records_returned": len(observations),
                "maximum_records": self.maximum_records,
                "truncated": truncated,
                "daily_values_are_provider_summaries": True,
                "spatial_interpretation": "point monitoring locations; not a continuous field",
            },
        )

    def _request_from_query(self, query: EarthQuery) -> dict[str, Any]:
        if query.temporal_start is None or query.temporal_end is None:
            raise ValidationError(
                "USGS daily discharge requires explicit temporal_start and temporal_end."
            )
        start = query.temporal_start.astimezone(timezone.utc)
        end = query.temporal_end.astimezone(timezone.utc)
        if end <= start:
            raise ValidationError("USGS daily discharge end time must follow start time.")
        if (end - start).total_seconds() > 366 * 86400:
            raise ValidationError(
                "USGS daily discharge queries are limited to 366 days.",
                context={"maximum_days": 366},
            )
        if any(
            any((instant.hour, instant.minute, instant.second, instant.microsecond))
            for instant in (start, end)
        ):
            raise ValidationError(
                "USGS daily discharge requires UTC day-boundary timestamps because source records are date-resolved."
            )
        if query.crs not in _CRS84 and query.bbox is not None:
            raise ValidationError("USGS bbox queries require CRS84 longitude/latitude coordinates.")
        if query.point is not None or query.geometry is not None:
            raise ValidationError(
                "USGS daily values support an explicit station filter or bbox, not point-nearest or arbitrary geometry queries."
            )
        filters = dict(query.filters)
        unsupported = set(filters).difference({"statistic_id", "monitoring_location_id"})
        if unsupported:
            raise ValidationError(
                "USGS daily discharge received unsupported filters.",
                context={"unsupported_filters": sorted(unsupported)},
            )
        statistic_id = filters.get("statistic_id")
        if not isinstance(statistic_id, str) or not statistic_id.isdigit():
            raise ValidationError(
                "USGS daily discharge requires an explicit numeric statistic_id.",
                remediation=["Choose the required daily statistic from the USGS daily-values catalog."],
            )
        station_id = filters.get("monitoring_location_id")
        if station_id is not None and (
            not isinstance(station_id, str)
            or not station_id.startswith("USGS-")
            or len(station_id) <= 5
        ):
            raise ValidationError("monitoring_location_id must be an explicit USGS site ID.")
        if station_id is None and query.bbox is None:
            raise ValidationError(
                "USGS daily discharge requires monitoring_location_id or bbox; no nearest station is selected."
            )
        if query.requested_variables and any(
            value.casefold() not in {_VARIABLE, "streamflow"}
            for value in query.requested_variables
        ):
            raise ValidationError(
                "USGS daily discharge does not provide every requested variable.",
                context={"requested_variables": query.requested_variables},
            )
        if query.requested_dataset_ids and not any(
            value in {_DATASET_ID, f"{self.connector_id}:{_DATASET_ID}"}
            for value in query.requested_dataset_ids
        ):
            raise ValidationError(
                "USGS daily discharge does not provide the requested dataset.",
                context={"requested_dataset_ids": query.requested_dataset_ids},
            )
        parameters: dict[str, Any] = {
            "f": "json",
            "limit": min(self.page_size, self.maximum_records),
            "datetime": f"{start.date().isoformat()}/{end.date().isoformat()}",
            "parameter_code": _PARAMETER_CODE,
            "statistic_id": statistic_id,
        }
        if station_id is not None:
            parameters["monitoring_location_id"] = station_id
        if query.bbox is not None:
            if len(query.bbox) != 4:
                raise ValidationError("USGS bbox queries require four CRS84 coordinates.")
            west, south, east, north = query.bbox
            if west < -180 or east > 180 or south < -90 or north > 90 or west > east or south > north:
                raise ValidationError("USGS bbox minimum coordinates must not exceed maxima.")
            parameters["bbox"] = ",".join(str(value) for value in query.bbox)
        return {
            "params": parameters,
            "statistic_id": statistic_id,
            "monitoring_location_id": station_id,
            "bbox": parameters.get("bbox"),
        }

    def _observation(self, feature: Mapping[str, Any], request: Mapping[str, Any]) -> Observation:
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, Mapping) or not isinstance(geometry, Mapping):
            raise ConnectorError("USGS daily feature is missing properties or geometry.")
        if str(properties.get("parameter_code")) != _PARAMETER_CODE:
            raise ConnectorError("USGS daily response returned a different parameter code.")
        if str(properties.get("statistic_id")) != request["statistic_id"]:
            raise ConnectorError("USGS daily response returned a different statistic ID.")
        if geometry.get("type") != "Point":
            raise ConnectorError("USGS daily station geometry is not a GeoJSON Point.")
        coordinates = geometry.get("coordinates")
        if (
            not isinstance(coordinates, (list, tuple))
            or len(coordinates) < 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in coordinates[:2]
            )
            or not -180 <= coordinates[0] <= 180
            or not -90 <= coordinates[1] <= 90
        ):
            raise ConnectorError("USGS daily station coordinates are invalid.")
        raw_date = properties.get("time")
        try:
            day = date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise ConnectorError("USGS daily record has an invalid date.") from exc
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        raw_value = properties.get("value")
        value = None if raw_value in (None, "", "-") else _finite_source_value(raw_value)
        unit = properties.get("unit_of_measure")
        if unit is not None and (not isinstance(unit, str) or not unit.strip()):
            unit = None
        location = properties.get("monitoring_location_id")
        if not isinstance(location, str) or not location:
            raise ConnectorError("USGS daily record lacks monitoring_location_id.")
        timeseries_id = properties.get("timeseries_id")
        source_id = f"{location}:{timeseries_id or _PARAMETER_CODE}:{day.isoformat()}:{request['statistic_id']}"
        quality = {
            "provider_approval_status": properties.get("approvals_status"),
            "provider_qualifier": properties.get("qualifier"),
            "last_modified": properties.get("last_modified"),
        }
        if value is None:
            quality["missing_value"] = True
        return Observation(
            source_id=source_id,
            dataset=DatasetReference(
                connector_id=self.connector_id,
                dataset_id=_DATASET_ID,
                uri=self.items_url,
                metadata={
                    "parameter_code": _PARAMETER_CODE,
                    "statistic_id": request["statistic_id"],
                },
            ),
            observed_at=start,
            temporal_extent=TemporalExtent(start=start, end=end),
            geometry={"type": "Point", "coordinates": list(coordinates)},
            crs="OGC:CRS84",
            observation_type="daily_in_situ_hydrology",
            measured_variables={
                _VARIABLE: {
                    "value": value,
                    "unit": unit,
                    "source_unit": unit,
                    "source_name": _PARAMETER_CODE,
                    "source_aggregation": request["statistic_id"],
                    "temporal_support": "daily",
                }
            },
            modalities=("hydrological",),
            provenance={
                "provider": "U.S. Geological Survey",
                "service": "Water Data OGC API",
                "collection": "daily",
                "record_id": feature.get("id"),
                "monitoring_location_id": location,
                "timeseries_id": timeseries_id,
                "request": {
                    "parameter_code": _PARAMETER_CODE,
                    "statistic_id": request["statistic_id"],
                    "monitoring_location_id": request.get("monitoring_location_id"),
                    "bbox": request.get("bbox"),
                    "temporal_start": request["params"]["datetime"].split("/")[0],
                    "temporal_end": request["params"]["datetime"].split("/")[1],
                },
            },
            provider_metadata={"properties": dict(properties)},
            quality={key: value for key, value in quality.items() if value is not None},
            uncertainty={
                "status": "unknown",
                "reason": "No measurement uncertainty field is declared in the returned record.",
            },
            reproducibility={
                "provider_api": "USGS Water Data OGC API v1",
                "collection": "daily",
                "source_record_id": feature.get("id"),
                "parameter_code": _PARAMETER_CODE,
                "statistic_id": request["statistic_id"],
                "temporal_support": "one provider-reported daily value for the source date",
                "request": dict(request["params"]),
            },
            source_document=dict(feature),
        )

    async def _get_json(self, url: str, params: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
        assert self._client is not None
        try:
            response = await self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise NetworkError("USGS Water Data request timed out.", context={"connector": self.connector_id}) from exc
        except httpx.HTTPError as exc:
            raise NetworkError("USGS Water Data request failed.", context={"connector": self.connector_id}) from exc
        if response.status_code == 429:
            raise RateLimitError("USGS Water Data rate limited the request.", context={"connector": self.connector_id})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(
                f"USGS Water Data returned HTTP {response.status_code}.",
                context={"connector": self.connector_id, "status_code": response.status_code},
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError("USGS Water Data response is not valid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise ConnectorError("USGS Water Data response must be a JSON object.")
        return payload

    def _validate_next_url(self, url: str) -> None:
        configured = urlsplit(self.items_url)
        candidate = urlsplit(url)
        if (
            candidate.scheme != "https"
            or candidate.netloc.casefold() != configured.netloc.casefold()
            or not candidate.path.startswith(configured.path.rsplit("/", 1)[0] + "/")
        ):
            raise ConnectorError("USGS pagination link escaped the configured API origin.")

    def _validate_configuration(self) -> None:
        if not self.connector_id.strip():
            raise ValueError("connector_id must be non-empty")
        parsed = urlsplit(self.items_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("items_url must be an HTTPS URL without embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("items_url must not contain query parameters or a fragment")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _finite_source_value(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConnectorError("USGS daily discharge value is not numeric.") from exc
    if not math.isfinite(result):
        raise ConnectorError("USGS daily discharge value is non-finite.")
    return result
