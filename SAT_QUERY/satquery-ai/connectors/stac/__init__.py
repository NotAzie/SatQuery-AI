"""STAC API connector for interoperable Earth observation catalogs."""

from .connector import StacCatalogConnector
from .contracts import StacSearchRequest

__all__ = ["StacCatalogConnector", "StacSearchRequest"]
