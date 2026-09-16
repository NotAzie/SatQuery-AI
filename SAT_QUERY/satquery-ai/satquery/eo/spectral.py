"""Registry-driven spectral indices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from .data import EOData
from .raster import RasterResult, raster_statistics, safe_expression


@dataclass(frozen=True)
class IndexDefinition:
    name: str
    formula: str
    required_bands: Tuple[str, ...]
    valid_range: Optional[Tuple[float, float]] = None
    description: str = ""


INDEX_REGISTRY: Dict[str, IndexDefinition] = {
    "ndvi": IndexDefinition("NDVI", "(nir - red) / (nir + red)", ("nir", "red"), (-1.0, 1.0), "Normalized Difference Vegetation Index"),
    "ndwi": IndexDefinition("NDWI", "(green - nir) / (green + nir)", ("green", "nir"), (-1.0, 1.0), "Normalized Difference Water Index"),
    "mndwi": IndexDefinition("MNDWI", "(green - swir) / (green + swir)", ("green", "swir"), (-1.0, 1.0), "Modified Normalized Difference Water Index"),
    "ndbi": IndexDefinition("NDBI", "(swir - nir) / (swir + nir)", ("swir", "nir"), (-1.0, 1.0), "Normalized Difference Built-up Index"),
    "nbr": IndexDefinition("NBR", "(nir - swir2) / (nir + swir2)", ("nir", "swir2"), (-1.0, 1.0), "Normalized Burn Ratio"),
    "evi": IndexDefinition("EVI", "2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)", ("nir", "red", "blue"), (-1.0, 1.0), "Enhanced Vegetation Index"),
}


def list_indices() -> Tuple[IndexDefinition, ...]:
    return tuple(INDEX_REGISTRY.values())


def _resolve_aliases(raster: EOData, aliases: Mapping[str, str | int]) -> Dict[str, np.ndarray]:
    resolved: Dict[str, np.ndarray] = {}
    for alias, key in aliases.items():
        resolved[alias.lower()] = raster.band(key)
    return resolved


def calculate_index(
    raster: EOData,
    index: str,
    *,
    bands: Optional[Mapping[str, str | int]] = None,
) -> RasterResult:
    definition = INDEX_REGISTRY.get(index.lower())
    if definition is None:
        raise KeyError(f"Unknown spectral index {index!r}. Available: {sorted(INDEX_REGISTRY)}")
    aliases = dict(bands or {name: name for name in definition.required_bands})
    try:
        values = _resolve_aliases(raster, aliases)
    except KeyError as exc:
        raise ValueError(
            f"{definition.name} requires bands {definition.required_bands}; provide metadata names or an explicit bands mapping."
        ) from exc
    result = safe_expression(definition.formula, values)
    warnings = []
    if definition.valid_range:
        low, high = definition.valid_range
        out_of_range = np.isfinite(result) & ((result < low) | (result > high))
        if out_of_range.any():
            warnings.append(f"{int(out_of_range.sum())} pixels fell outside the usual {definition.name} range {definition.valid_range}.")
    return RasterResult(
        values=result,
        operation=definition.name,
        provenance=raster.provenance("spectral_index", index=definition.name, formula=definition.formula, bands=aliases, statistics=raster_statistics(raster, result)),
        warnings=tuple(warnings),
    )
