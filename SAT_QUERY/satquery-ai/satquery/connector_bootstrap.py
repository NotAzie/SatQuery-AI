"""Load explicitly configured trusted connector implementations for the app."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .platform.connectors import Connector, ConnectorPolicy
from .platform.runtime import PlatformRuntime

ConnectorFactory = Callable[[Mapping[str, Any], ConnectorPolicy], Connector]
CONNECTOR_CONFIG_ENV = "SATQUERY_CONNECTORS_CONFIG"


class ConnectorFactoryRegistry:
    """Small, explicit registry of trusted factories for configured adapters."""

    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}
        self._lock = threading.RLock()

    def register(
        self, name: str, factory: ConnectorFactory, *, replace: bool = False
    ) -> None:
        key = name.strip().casefold()
        if not key or not callable(factory):
            raise ValueError("connector factory requires a name and callable")
        with self._lock:
            if key in self._factories and not replace:
                raise ValueError(f"connector factory {key!r} is already registered")
            self._factories[key] = factory

    def get(self, name: str) -> ConnectorFactory:
        key = name.strip().casefold()
        with self._lock:
            try:
                return self._factories[key]
            except KeyError as exc:
                raise ConfigurationError(
                    f"Unknown connector implementation {name!r}.",
                    context={"implementation": name, "available": self.names()},
                ) from exc

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._factories))


def _build_open_meteo(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.open_meteo import OpenMeteoConnector, OpenMeteoEndpoint

    endpoint = value.get("endpoint")
    configuration = value.get("configuration", {})
    if not isinstance(endpoint, str) or not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "Open-Meteo connector definitions require endpoint and "
            "configuration object."
        )
    return OpenMeteoConnector(
        OpenMeteoEndpoint(endpoint), configuration=configuration, policy=policy
    )


def _build_stac(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.stac import StacCatalogConnector

    configuration = value.get("configuration")
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "STAC connector definitions require a configuration object."
        )
    return StacCatalogConnector(configuration=configuration, policy=policy)


def _build_planetary_computer(
    value: Mapping[str, Any], policy: ConnectorPolicy
) -> Connector:
    from connectors.catalogs import PlanetaryComputerConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "Planetary Computer connector configuration must be an object."
        )
    return PlanetaryComputerConnector(configuration=configuration, policy=policy)


def _build_copernicus_data_space(
    value: Mapping[str, Any], policy: ConnectorPolicy
) -> Connector:
    from connectors.catalogs import CopernicusDataSpaceConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "Copernicus Data Space connector configuration must be an object."
        )
    return CopernicusDataSpaceConnector(configuration=configuration, policy=policy)


def _build_usgs_landsat(
    value: Mapping[str, Any], policy: ConnectorPolicy
) -> Connector:
    from connectors.catalogs import UsGSLandsatConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "USGS Landsat connector configuration must be an object."
        )
    return UsGSLandsatConnector(configuration=configuration, policy=policy)


def _build_image_fetcher(
    value: Mapping[str, Any], policy: ConnectorPolicy
) -> Connector:
    from connectors.image_fetcher.connector import ImageFetcherConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "Image fetcher connector configuration must be an object."
        )
    return ImageFetcherConnector(configuration=configuration, policy=policy)


def _build_openstreetmap(
    value: Mapping[str, Any], policy: ConnectorPolicy
) -> Connector:
    from connectors.openstreetmap import OverpassConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "OpenStreetMap connector configuration must be an object."
        )
    return OverpassConnector(configuration=configuration, policy=policy)


def _build_usgs_3dep(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.usgs_3dep import UsgsEpqsConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError("USGS 3DEP connector configuration must be an object.")
    return UsgsEpqsConnector(configuration=configuration, policy=policy)


def _build_usgs_water(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.usgs_water import UsgsDailyDischargeConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError("USGS Water Data connector configuration must be an object.")
    return UsgsDailyDischargeConnector(configuration=configuration, policy=policy)


def _build_nasa_earthdata(
    value: Mapping[str, Any], policy: ConnectorPolicy
) -> Connector:
    from connectors.nasa_earthdata import NasaEarthdataConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "NASA Earthdata connector configuration must be an object."
        )
    return NasaEarthdataConnector(configuration=configuration, policy=policy)


def _build_noaa_coops(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.noaa_coops import NoaaCoopsConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "NOAA CO-OPS connector configuration must be an object."
        )
    return NoaaCoopsConnector(configuration=configuration, policy=policy)


def _build_nasa_firms(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.nasa_firms import NasaFirmsConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError(
            "NASA FIRMS connector configuration must be an object."
        )
    return NasaFirmsConnector(configuration=configuration, policy=policy)


def _build_nasa_power(value: Mapping[str, Any], policy: ConnectorPolicy) -> Connector:
    from connectors.nasa_power import NasaPowerDailyConnector

    configuration = value.get("configuration", {})
    if not isinstance(configuration, Mapping):
        raise ConfigurationError("NASA POWER connector configuration must be an object.")
    return NasaPowerDailyConnector(configuration=configuration, policy=policy)


DEFAULT_CONNECTOR_FACTORIES = ConnectorFactoryRegistry()
for _name, _factory in (
    ("open_meteo", _build_open_meteo),
    ("stac", _build_stac),
    ("planetary_computer", _build_planetary_computer),
    ("copernicus_data_space", _build_copernicus_data_space),
    ("usgs_landsat", _build_usgs_landsat),
    ("image_fetcher", _build_image_fetcher),
    ("openstreetmap", _build_openstreetmap),
    ("usgs_3dep", _build_usgs_3dep),
    ("usgs_water", _build_usgs_water),
    ("nasa_earthdata", _build_nasa_earthdata),
    ("nasa_firms", _build_nasa_firms),
    ("nasa_power", _build_nasa_power),
    ("noaa_coops", _build_noaa_coops),
):
    DEFAULT_CONNECTOR_FACTORIES.register(_name, _factory)


def load_configured_connectors(
    runtime: PlatformRuntime,
    *,
    config_path: str | os.PathLike[str] | None = None,
    factories: ConnectorFactoryRegistry = DEFAULT_CONNECTOR_FACTORIES,
) -> tuple[str, ...]:
    """Build and register connectors from an explicit local JSON manifest.

    Factories execute trusted Python code. The manifest only selects registered
    factories; it cannot import arbitrary modules or classes.
    """
    configured_path = config_path or os.environ.get(CONNECTOR_CONFIG_ENV)
    if configured_path is None:
        return ()
    path = Path(configured_path).expanduser()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Could not read connector manifest {str(path)!r}: {exc}",
            context={"config_path": str(path)},
        ) from exc
    if not isinstance(document, Mapping) or set(document) != {"connectors"}:
        raise ConfigurationError(
            "Connector manifest must contain only a 'connectors' list."
        )
    definitions = document["connectors"]
    if not isinstance(definitions, list):
        raise ConfigurationError("Connector manifest 'connectors' must be a list.")

    connectors: list[Connector] = []
    for index, definition in enumerate(definitions):
        if not isinstance(definition, Mapping):
            raise ConfigurationError(
                "Connector definitions must be JSON objects.",
                context={"index": index},
            )
        if set(definition).difference({"implementation", "configuration", "endpoint"}):
            raise ConfigurationError(
                "Connector definition contains unsupported fields.",
                context={"index": index},
            )
        implementation = definition.get("implementation")
        if not isinstance(implementation, str) or not implementation.strip():
            raise ConfigurationError(
                "Connector definition requires an implementation name.",
                context={"index": index},
            )
        try:
            connector = factories.get(implementation)(
                definition, runtime.config.connector_policy()
            )
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(
                f"Could not build connector implementation {implementation!r}: {exc}",
                context={"index": index, "implementation": implementation},
            ) from exc
        errors = connector.validate()
        if errors:
            raise ConfigurationError(
                f"Connector {connector.metadata.connector_id!r} failed validation.",
                context={"index": index, "errors": errors},
            )
        connectors.append(connector)

    connector_ids = [connector.metadata.connector_id for connector in connectors]
    if len(connector_ids) != len(set(connector_ids)):
        raise ConfigurationError("Connector manifest contains duplicate connector IDs.")
    existing = set(runtime.registries.connectors.names())
    duplicates = existing.intersection(connector_ids)
    if duplicates:
        raise ConfigurationError(
            f"Connector manifest IDs are already registered: {sorted(duplicates)}."
        )

    registered: list[str] = []
    try:
        for connector in connectors:
            runtime.register_connector(connector)
            registered.append(connector.metadata.connector_id)
    except Exception:
        for connector_id in registered:
            runtime.registries.connectors.unregister(connector_id)
        raise
    return tuple(sorted(connector_ids))
