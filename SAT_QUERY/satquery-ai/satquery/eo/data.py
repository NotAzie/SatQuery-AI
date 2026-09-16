"""Metadata-preserving EO raster inputs with an RGB fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class EOWarning:
    code: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EOData:
    """An EO raster or explicitly non-georeferenced image fallback."""

    data: np.ndarray
    source: str
    band_names: Tuple[str, ...] = ()
    band_descriptions: Tuple[str, ...] = ()
    wavelengths: Tuple[Optional[float], ...] = ()
    crs: Optional[str] = None
    transform: Optional[Tuple[float, ...]] = None
    bounds: Optional[Tuple[float, float, float, float]] = None
    resolution: Optional[Tuple[float, float]] = None
    acquisition_time: Optional[str] = None
    sensor: Optional[str] = None
    platform: Optional[str] = None
    nodata: Optional[float] = None
    scales: Tuple[Optional[float], ...] = ()
    offsets: Tuple[Optional[float], ...] = ()
    dtype: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: Tuple[EOWarning, ...] = ()

    @property
    def is_georeferenced(self) -> bool:
        return bool(self.crs and self.transform and self.bounds)

    @property
    def is_eo_native(self) -> bool:
        rgb_names = {"red", "green", "blue"}
        return self.is_georeferenced or self.data.shape[0] != 3 or set(self.band_names) != rgb_names

    @property
    def band_count(self) -> int:
        return int(self.data.shape[0])

    @property
    def height(self) -> int:
        return int(self.data.shape[1])

    @property
    def width(self) -> int:
        return int(self.data.shape[2])

    @property
    def shape(self) -> Tuple[int, int, int]:
        return tuple(int(value) for value in self.data.shape)  # type: ignore[return-value]

    @property
    def valid_mask(self) -> np.ndarray:
        mask = np.isfinite(self.data).all(axis=0)
        if self.nodata is not None:
            mask &= ~np.any(self.data == self.nodata, axis=0)
        return mask

    def resolve_band(self, key: str | int) -> int:
        if isinstance(key, int):
            index = key - 1 if key > 0 else key
            if 0 <= index < self.band_count:
                return index
            raise KeyError(f"Band number {key} is outside 1..{self.band_count}.")
        wanted = key.strip().lower()
        for index, name in enumerate(self.band_names):
            if name.lower() == wanted:
                return index
        for index, description in enumerate(self.band_descriptions):
            if description.lower() == wanted:
                return index
        raise KeyError(
            f"Band {key!r} is unavailable. Available bands: {list(self.band_names) or list(range(1, self.band_count + 1))}."
        )

    def band(self, key: str | int) -> np.ndarray:
        return self.data[self.resolve_band(key)]

    def provenance(self, operation: str, **parameters: Any) -> Dict[str, Any]:
        return {
            "source": self.source,
            "operation": operation,
            "parameters": parameters,
            "georeferenced": self.is_georeferenced,
            "crs": self.crs,
        }


def _warning(code: str, message: str, **context: Any) -> EOWarning:
    return EOWarning(code, message, context)


def _parse_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_datetime(tags: Dict[str, Any]) -> Optional[str]:
    for key in ("datetime", "acquisition_datetime", "acquisition_date", "date_acquired"):
        value = tags.get(key) or tags.get(key.upper())
        if value:
            text = str(value)
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
            except ValueError:
                return text
    return None


def _from_rasterio(path: Path) -> EOData:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError("Rasterio is required for GeoTIFF/COG inputs. Install satquery-ai[eo].") from exc

    with rasterio.open(path) as dataset:
        array = dataset.read()
        tags = dict(dataset.tags())
        descriptions = tuple(item or "" for item in dataset.descriptions)
        names = tuple(item or "" for item in descriptions)
        wavelengths = tuple(
            _parse_float(tags.get(f"wavelength_{index + 1}")) for index in range(dataset.count)
        )
        warnings = []
        if dataset.crs is None:
            warnings.append(_warning("missing_crs", "Raster has no CRS; physical geospatial measurements are unavailable."))
        if dataset.transform is None or dataset.transform.is_identity:
            warnings.append(_warning("missing_transform", "Raster has no meaningful affine transform."))
        return EOData(
            data=array,
            source=str(path.resolve()),
            band_names=names,
            band_descriptions=descriptions,
            wavelengths=wavelengths,
            crs=dataset.crs.to_string() if dataset.crs else None,
            transform=tuple(dataset.transform) if dataset.transform else None,
            bounds=tuple(dataset.bounds) if dataset.bounds else None,
            resolution=tuple(dataset.res) if dataset.res else None,
            acquisition_time=_parse_datetime(tags),
            sensor=tags.get("sensor") or tags.get("SENSOR"),
            platform=tags.get("platform") or tags.get("PLATFORM"),
            nodata=dataset.nodata,
            scales=tuple(dataset.scales),
            offsets=tuple(dataset.offsets),
            dtype=str(dataset.dtypes[0]),
            metadata={"tags": tags, "driver": dataset.driver, "count": dataset.count},
            warnings=tuple(warnings),
        )


def load_eo_raster(source: str | Path, *, allow_rgb_fallback: bool = True) -> EOData:
    """Load a GeoTIFF/COG with metadata or an ordinary image as RGB fallback."""
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"EO raster does not exist: {path}")
    if path.suffix.lower() in {".tif", ".tiff", ".cog"}:
        return _from_rasterio(path)
    if not allow_rgb_fallback:
        raise ValueError(f"{path.name} is not a supported georeferenced raster.")
    from PIL import Image

    array = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32).transpose(2, 0, 1)
    return EOData(
        data=array,
        source=str(path),
        band_names=("red", "green", "blue"),
        band_descriptions=("red", "green", "blue"),
        dtype=str(array.dtype),
        metadata={"format": path.suffix.lower().lstrip(".")},
        warnings=(
            _warning(
                "non_georeferenced_fallback",
                "Ordinary RGB imagery loaded without CRS, transform, GSD, sensor, or wavelength metadata.",
            ),
        ),
    )


def from_array(
    data: np.ndarray,
    *,
    source: str = "memory",
    band_names: Sequence[str] = (),
    crs: Optional[str] = None,
    transform: Optional[Tuple[float, ...]] = None,
    bounds: Optional[Tuple[float, float, float, float]] = None,
    nodata: Optional[float] = None,
) -> EOData:
    array = np.asarray(data)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim != 3:
        raise ValueError("EO data must have shape (bands, height, width).")
    warnings = () if crs and transform and bounds else (
        _warning("incomplete_metadata", "In-memory raster lacks complete geospatial metadata."),
    )
    resolution = None
    if transform is not None and len(transform) >= 5:
        resolution = (abs(float(transform[0])), abs(float(transform[4])))
    return EOData(
        data=array,
        source=source,
        band_names=tuple(band_names),
        crs=crs,
        transform=transform,
        bounds=bounds,
        resolution=resolution,
        nodata=nodata,
        dtype=str(array.dtype),
        warnings=warnings,
    )
