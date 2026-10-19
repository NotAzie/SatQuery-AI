"""USGS 3DEP point elevation observations through the EPQS JSON service."""

from __future__ import annotations

import math
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
    EarthQuery,
    Observation,
    ObservationSearchResult,
)

_DEFAULT_ENDPOINT = "https://epqs.nationalmap.gov/v1/json"


class UsgsEpqsConnector(PerceptionConnector):
    """Return a source-reported elevation sample for one geographic point.

    The service interpolates from USGS 3DEP elevation data. This adapter does
    not infer a local error estimate or observation date when the response
    does not provide one.
    """

    def __init__(
        self,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        policy: Optional[ConnectorPolicy] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        default_policy = ConnectorPolicy(
            timeout_seconds=30,
            max_attempts=2,
            retry_safe=True,
            retry_delay_seconds=0.2,
        )
        super().__init__(
            configuration=configuration,
            policy=policy or default_policy,
        )
        config = dict(configuration or {})
        endpoint = config.get("endpoint_url", _DEFAULT_ENDPOINT)
        units = config.get("units", "Meters")
        connector_id = config.get("connector_id", "usgs-3dep-epqs")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValidationError("USGS EPQS endpoint_url must be a non-empty URL.")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError(
                "USGS EPQS endpoint_url must be an HTTPS endpoint without credentials, query, or fragment."
            )
        if units not in {"Meters", "Feet"}:
            raise ValidationError("USGS EPQS units must be 'Meters' or 'Feet'.")
        if not isinstance(connector_id, str) or not connector_id.strip():
            raise ValidationError("USGS EPQS connector_id must be non-empty.")
        self.endpoint_url = endpoint
        self.units = units
        self.connector_id = connector_id.strip()
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    @property
    def metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name="USGS 3DEP Elevation Point Query Service",
            version="1",
            capabilities=("terrain", "elevation", "point_observation"),
            modalities=("geological",),
            configuration_schema={
                "type": "object",
                "properties": {
                    "connector_id": {"type": "string", "minLength": 1},
                    "endpoint_url": {"type": "string", "format": "uri"},
                    "units": {"type": "string", "enum": ["Meters", "Feet"]},
                },
                "additionalProperties": False,
            },
            supports_temporal_query=False,
            supported_spatial_types=("point",),
            supported_query_fields=("requested_dataset_ids",),
            supported_variables=("elevation",),
            datasets=(
                DatasetReference(
                    connector_id=self.connector_id,
                    dataset_id="usgs-3dep-epqs",
                    uri=self.endpoint_url,
                    metadata={
                        "variables": ["elevation"],
                        "units": {"elevation": "m" if self.units == "Meters" else "ft"},
                        "modalities": ["geological"],
                    },
                ),
            ),
            provider_metadata={
                "provider": "U.S. Geological Survey",
                "program": "3D Elevation Program (3DEP)",
                "service": "Elevation Point Query Service (EPQS)",
                "endpoint": self.endpoint_url,
                "documentation_url": "https://epqs.nationalmap.gov/v1/docs",
                "accuracy_note_url": "https://www.usgs.gov/faqs/how-accurate-are-elevations-generated-elevation-point-query-service-national-map",
            },
        )

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.policy.timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def discover(self) -> tuple[DatasetReference, ...]:
        return (
            DatasetReference(
                connector_id=self.connector_id,
                dataset_id="usgs-3dep-epqs",
                uri=self.endpoint_url,
                metadata={
                    **self.metadata.provider_metadata,
                    "variables": ["elevation"],
                    "modalities": ["geological"],
                    "capabilities": ["terrain", "elevation", "point_observation"],
                    "spatial_resolution": None,
                    "crs": "OGC:CRS84",
                },
            ),
        )

    async def acquire(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._client is None:
            raise ConnectorError(
                "USGS EPQS connector is not started.",
                context={"connector": self.connector_id},
            )
        try:
            response = await self._client.get(self.endpoint_url, params=dict(request))
        except httpx.TimeoutException as exc:
            raise NetworkError(
                "USGS EPQS request timed out.",
                context={"connector": self.connector_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                f"USGS EPQS request failed: {exc}",
                context={"connector": self.connector_id},
            ) from exc
        if response.status_code == 429:
            raise RateLimitError(
                "USGS EPQS rate limit was reached.",
                context={"connector": self.connector_id},
                recoverable=True,
            )
        if response.status_code >= 500:
            raise NetworkError(
                f"USGS EPQS returned HTTP {response.status_code}.",
                context={
                    "connector": self.connector_id,
                    "status_code": response.status_code,
                },
            )
        if response.is_error:
            raise ConnectorError(
                f"USGS EPQS rejected the request with HTTP {response.status_code}.",
                context={"connector": self.connector_id, "status_code": response.status_code},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError(
                "USGS EPQS returned invalid JSON.",
                context={"connector": self.connector_id},
            ) from exc
        if not isinstance(payload, Mapping):
            raise ConnectorError(
                "USGS EPQS response must be a JSON object.",
                context={"connector": self.connector_id},
            )
        return payload

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request = self._request_from_query(query)
        payload = await self.fetch(request)
        raw_value = payload.get("value")
        try:
            elevation = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ConnectorError(
                "USGS EPQS response did not contain a numeric elevation value.",
                context={"connector": self.connector_id, "value": raw_value},
            ) from exc
        if not math.isfinite(elevation):
            raise ConnectorError(
                "USGS EPQS response contained a non-finite elevation value.",
                context={"connector": self.connector_id},
            )

        longitude, latitude = query.point  # validated by _request_from_query
        source_unit = payload.get("units", self.units)
        unit = self._canonical_unit(source_unit)
        source_data = dict(payload)
        observation = Observation(
            dataset=DatasetReference(
                connector_id=self.connector_id,
                dataset_id="usgs-3dep-epqs",
                uri=self.endpoint_url,
            ),
            geometry={"type": "Point", "coordinates": [longitude, latitude]},
            crs="OGC:CRS84",
            observation_type="elevation_sample",
            measured_variables={
                "elevation": {
                    "value": elevation,
                    "unit": unit,
                    "source_unit": source_unit,
                }
            },
            provider_metadata={
                key: source_data[key]
                for key in ("dataSource", "dataDate", "resolution", "units")
                if key in source_data
            },
            provenance={
                "provider": "U.S. Geological Survey",
                "service": "3DEP EPQS",
                "endpoint": self.endpoint_url,
                "request_parameters": request,
            },
            reproducibility={
                "provider": "U.S. Geological Survey",
                "service": "3DEP EPQS",
                "endpoint": self.endpoint_url,
                "request_parameters": request,
            },
            properties={"requested_point": [longitude, latitude]},
            source_document=source_data,
        )
        return ObservationSearchResult(
            observations=(observation,),
            matched=1,
            context={
                "connector_id": self.connector_id,
                "dataset_id": "usgs-3dep-epqs",
            },
            source_document={
                "provider": "U.S. Geological Survey",
                "endpoint": self.endpoint_url,
                "request": request,
                "response": source_data,
            },
        )

    def _request_from_query(self, query: EarthQuery) -> dict[str, Any]:
        if (
            query.requested_dataset_ids
            and "usgs-3dep-epqs" not in query.requested_dataset_ids
        ):
            raise ValidationError(
                "Requested dataset is not implemented by USGS EPQS."
            )
        if query.point is None:
            raise ValidationError(
                "USGS EPQS requires a single point query.",
                context={"connector": self.connector_id},
            )
        if query.crs.casefold() not in {
            "crs84",
            "ogc:crs84",
            "epsg:4326",
            "urn:ogc:def:crs:ogc:1.3:crs84",
        }:
            raise ValidationError(
                "USGS EPQS requires OGC:CRS84 or EPSG:4326 coordinates.",
                context={"connector": self.connector_id, "crs": query.crs},
            )
        if query.temporal_start is not None or query.temporal_end is not None:
            raise ValidationError(
                "USGS EPQS does not support temporal queries.",
                context={"connector": self.connector_id},
            )
        if (
            query.filters
            or query.asset_preferences
            or query.spatial_resolution is not None
        ):
            raise ValidationError(
                "USGS EPQS does not support filters, asset preferences, or requested spatial resolution.",
                context={"connector": self.connector_id},
            )
        unsupported = [
            variable
            for variable in query.requested_variables
            if variable.casefold() not in {"elevation", "dem", "digital_elevation"}
        ]
        if unsupported:
            raise ValidationError(
                "USGS EPQS only provides elevation samples.",
                context={"connector": self.connector_id, "unsupported_variables": unsupported},
            )
        longitude, latitude = query.point
        return {
            "x": longitude,
            "y": latitude,
            "wkid": 4326,
            "units": self.units,
            "includeDate": "true",
        }

    @staticmethod
    def _canonical_unit(value: Any) -> Optional[str]:
        if isinstance(value, str):
            if value.casefold() in {"meters", "meter", "m"}:
                return "m"
            if value.casefold() in {"feet", "foot", "ft"}:
                return "ft"
        return None
