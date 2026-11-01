"""Configured public Earth-observation catalogs using the shared STAC adapter."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from satquery.platform.connectors import ConnectorPolicy
from satquery.platform.contracts import ConnectorMetadata

from .stac.connector import StacCatalogConnector


class _StacProviderConnector(StacCatalogConnector):
    provider_name = ""
    default_connector_id = ""
    default_catalog_url = ""
    provider_capabilities: tuple[str, ...] = ("earth_observation_catalog",)

    def __init__(
        self,
        *,
        configuration: Optional[Mapping[str, Any]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        policy: Optional[ConnectorPolicy] = None,
    ) -> None:
        resolved = {
            "catalog_url": self.default_catalog_url,
            "connector_id": self.default_connector_id,
            **dict(configuration or {}),
        }
        resolved_policy = policy or ConnectorPolicy(
            timeout_seconds=30,
            max_attempts=2,
            retry_safe=True,
            retry_delay_seconds=0.2,
        )
        super().__init__(
            configuration=resolved,
            transport=transport,
            policy=resolved_policy,
        )

    @property
    def metadata(self) -> ConnectorMetadata:
        metadata = super().metadata
        return metadata.model_copy(
            update={
                "name": f"{self.provider_name} STAC Catalog",
                "capabilities": tuple(
                    sorted(set(metadata.capabilities).union(self.provider_capabilities))
                ),
                "provider_metadata": {
                    **metadata.provider_metadata,
                    "provider": self.provider_name,
                    "catalog_url": str(self.settings.catalog_url),
                },
            }
        )


class PlanetaryComputerConnector(_StacProviderConnector):
    """Microsoft Planetary Computer collection and item metadata discovery."""

    provider_name = "Microsoft Planetary Computer"
    default_connector_id = "microsoft-planetary-computer"
    default_catalog_url = "https://planetarycomputer.microsoft.com/api/stac/v1/"
    provider_capabilities = (
        "earth_observation_catalog",
        "imagery",
        "terrain",
        "land_cover",
        "vegetation",
        "climate",
    )


class CopernicusDataSpaceConnector(_StacProviderConnector):
    """Copernicus Data Space STAC collection and item metadata discovery."""

    provider_name = "Copernicus Data Space Ecosystem"
    default_connector_id = "copernicus-data-space"
    default_catalog_url = "https://stac.dataspace.copernicus.eu/v1/"
    provider_capabilities = ("earth_observation_catalog", "imagery")


class UsGSLandsatConnector(_StacProviderConnector):
    """USGS LandsatLook STAC metadata discovery."""

    provider_name = "USGS LandsatLook"
    default_connector_id = "usgs-landsat"
    default_catalog_url = "https://landsatlook.usgs.gov/stac-server/"
    provider_capabilities = ("earth_observation_catalog", "imagery", "landsat")
