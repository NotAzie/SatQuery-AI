"""Platform connector adapter for the existing optional image fetcher."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any, Mapping

from satquery.errors import ConnectorError, ValidationError
from satquery.platform.connectors import PerceptionConnector
from satquery.platform.contracts import (
    ConnectorAcquisition,
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    Observation,
    ObservationAsset,
    ObservationSearchResult,
)

from .satellite_fetcher import FetcherSettings, SatelliteFetchError, fetch_satellite_image


class ImageFetcherConnector(PerceptionConnector):
    """Adapt Esri image acquisition to connector and observation contracts."""

    def __init__(self, **kwargs: Any) -> None:
        supplied_configuration = kwargs.pop("configuration", None)
        configuration = dict(supplied_configuration or {})
        if supplied_configuration is None:
            settings = FetcherSettings.from_env()
        else:
            try:
                settings = FetcherSettings(**configuration)
            except TypeError as exc:
                raise ValidationError(
                    f"Invalid image-fetcher connector configuration: {exc}",
                    context={"connector": "image-fetcher"},
                ) from exc
        super().__init__(configuration=configuration, **kwargs)
        self.settings = settings

    @property
    def metadata(self) -> ConnectorMetadata:
        dataset = DatasetReference(
            connector_id="image-fetcher",
            dataset_id="esri-world-imagery",
            uri=self.settings.provider_url,
            metadata={
                "provider": "Esri World Imagery",
                "modalities": ["visual"],
            },
        )
        return ConnectorMetadata(
            connector_id="image-fetcher",
            name="Satellite Image Fetcher",
            version="1.0.0",
            capabilities=("geocode", "acquire-imagery", "imagery"),
            modalities=("visual",),
            authentication_schemes=(),
            supports_async=True,
            supports_streaming=False,
            supported_spatial_types=("point",),
            supported_query_fields=("requested_dataset_ids",),
            datasets=(dataset,),
            provider_metadata={"provider": "Esri World Imagery"},
            configuration_schema={
                "type": "object",
                "properties": {
                    "output_dir": {"type": "string"},
                    "provider_url": {"type": "string"},
                    "geocoder_url": {"type": "string"},
                    "alternate_geocoder_url": {"type": "string"},
                    "user_agent": {"type": "string"},
                    "timeout_s": {"type": "number", "exclusiveMinimum": 0},
                    "default_zoom": {"type": "integer"},
                    "image_size": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        )

    async def discover(self) -> tuple[DatasetReference, ...]:
        return self.metadata.datasets

    async def acquire(self, request: Mapping[str, Any]) -> ConnectorAcquisition:
        allowed = {"place", "latitude", "longitude", "zoom", "output_dir"}
        unknown = set(request).difference(allowed)
        if unknown:
            raise ValidationError(
                f"Unknown image-fetcher request fields: {sorted(unknown)}",
                context={"connector": self.metadata.connector_id},
            )
        arguments = dict(request)
        arguments["settings"] = self.settings
        try:
            path = await asyncio.to_thread(fetch_satellite_image, **arguments)
        except SatelliteFetchError as exc:
            raise ConnectorError(
                str(exc),
                remediation=exc.remediation,
                context={"connector": self.metadata.connector_id},
                recoverable=False,
            ) from exc
        return ConnectorAcquisition(
            connector_id=self.metadata.connector_id,
            dataset=self.metadata.datasets[0],
            artifact_uri=Path(path).resolve().as_uri(),
            metadata={"path": str(Path(path).resolve())},
        )

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        if (
            query.requested_dataset_ids
            and "esri-world-imagery" not in query.requested_dataset_ids
        ):
            raise ValidationError(
                "Requested dataset is not implemented by the Esri image fetcher."
            )
        if query.crs not in {"OGC:CRS84", "CRS84"}:
            raise ValidationError(
                "Esri image fetcher requires OGC:CRS84 coordinates.",
                context={"connector": self.metadata.connector_id, "crs": query.crs},
            )
        if query.point is not None:
            longitude, latitude = query.point
        elif (
            query.geometry is not None
            and query.geometry.get("type") == "Point"
            and isinstance(query.geometry.get("coordinates"), list)
            and len(query.geometry["coordinates"]) == 2
        ):
            longitude, latitude = query.geometry["coordinates"]
            if (
                not isinstance(longitude, (int, float))
                or isinstance(longitude, bool)
                or not isinstance(latitude, (int, float))
                or isinstance(latitude, bool)
                or not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or not -180 <= longitude <= 180
                or not -90 <= latitude <= 90
            ):
                raise ValidationError(
                    "GeoJSON point coordinates must be finite longitude/latitude values.",
                    context={"connector": self.metadata.connector_id},
                )
        else:
            raise ValidationError(
                "Esri image fetcher currently requires a point query.",
                context={"connector": self.metadata.connector_id},
            )
        unsupported = []
        if query.temporal_start is not None or query.temporal_end is not None:
            unsupported.append("temporal bounds")
        if query.spatial_resolution is not None:
            unsupported.append("spatial resolution")
        if query.filters:
            unsupported.append("filters")
        if query.asset_preferences:
            unsupported.append("asset preferences")
        if unsupported:
            raise ValidationError(
                f"Esri image fetcher cannot represent {', '.join(unsupported)}.",
                context={"connector": self.metadata.connector_id},
            )
        acquisition = await self.fetch(
            {
                "latitude": latitude,
                "longitude": longitude,
                "zoom": self.settings.default_zoom,
            }
        )
        if not isinstance(acquisition, ConnectorAcquisition):
            raise ConnectorError(
                "Image fetcher did not return a normalized acquisition record.",
                context={"connector": self.metadata.connector_id},
            )
        observation = Observation(
            dataset=acquisition.dataset,
            observation_type="imagery",
            crs="OGC:CRS84",
            properties={
                "requested_location": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "requested_zoom": self.settings.default_zoom,
            },
            assets={
                "image": ObservationAsset(
                    uri=acquisition.artifact_uri,
                    roles=("visual",),
                )
            },
            provenance={
                "connector_acquisition": acquisition.model_dump(mode="json"),
                "provider": "Esri World Imagery",
            },
            provider_metadata=dict(acquisition.dataset.metadata),
            source_document=acquisition.model_dump(mode="json"),
        )
        return ObservationSearchResult(
            observations=(observation,),
            matched=1,
            context={"connector_id": self.metadata.connector_id},
        )
