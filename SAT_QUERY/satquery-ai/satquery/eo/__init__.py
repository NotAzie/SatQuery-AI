"""Earth-observation data, discovery, raster, and spectral primitives."""

from .data import EOData, EOWarning, from_array, load_eo_raster
from .discovery import DiscoveryQuery, ImageryCandidate, StacDiscoveryProvider
from .raster import RasterResult, calculate_area, raster_statistics, safe_expression
from .spectral import IndexDefinition, calculate_index, list_indices

__all__ = [
    "DiscoveryQuery",
    "EOData",
    "EOWarning",
    "ImageryCandidate",
    "IndexDefinition",
    "RasterResult",
    "StacDiscoveryProvider",
    "calculate_area",
    "calculate_index",
    "list_indices",
    "load_eo_raster",
    "from_array",
    "raster_statistics",
    "safe_expression",
]
