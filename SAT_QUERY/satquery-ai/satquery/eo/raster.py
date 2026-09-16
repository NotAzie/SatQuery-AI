"""Safe, reusable raster calculations."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np

from .data import EOData


@dataclass(frozen=True)
class RasterResult:
    values: np.ndarray
    operation: str
    provenance: Dict[str, Any]
    warnings: tuple[str, ...] = ()


def _valid(values: np.ndarray, nodata: Optional[float]) -> np.ndarray:
    mask = np.isfinite(values)
    if nodata is not None:
        mask &= values != nodata
    return mask


def raster_statistics(raster: EOData, values: Optional[np.ndarray] = None) -> Dict[str, Any]:
    array = raster.data if values is None else np.asarray(values)
    valid = _valid(array, raster.nodata)
    finite = array[valid]
    if finite.size == 0:
        return {"count": 0, "valid_fraction": 0.0, "min": None, "max": None, "mean": None, "median": None, "std": None}
    return {
        "count": int(finite.size),
        "valid_fraction": round(float(finite.size / array.size), 6),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "std": float(np.std(finite)),
    }


def normalize(values: np.ndarray, *, low: Optional[float] = None, high: Optional[float] = None) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    low = float(np.nanmin(array) if low is None else low)
    high = float(np.nanmax(array) if high is None else high)
    if high <= low:
        return np.zeros_like(array)
    return np.clip((array - low) / (high - low), 0.0, 1.0)


def mask_values(values: np.ndarray, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> np.ndarray:
    array = np.asarray(values)
    mask = np.isfinite(array)
    if minimum is not None:
        mask &= array >= minimum
    if maximum is not None:
        mask &= array <= maximum
    return mask


_ALLOWED_BINOPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide, ast.Pow: np.power}
_ALLOWED_UNARY = {ast.UAdd: lambda value: value, ast.USub: np.negative}


def safe_expression(expression: str, bands: Mapping[str, np.ndarray]) -> np.ndarray:
    """Evaluate arithmetic over named arrays without Python execution."""
    tree = ast.parse(expression, mode="eval")
    names = {key.lower(): value for key, value in bands.items()}

    def evaluate(node: ast.AST) -> np.ndarray | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Name) and node.id.lower() in names:
            return names[node.id.lower()]
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left, right = evaluate(node.left), evaluate(node.right)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                return _ALLOWED_BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](evaluate(node.operand))
        raise ValueError("Expression permits only named bands, numeric constants, and + - * / ** operators.")

    result = np.asarray(evaluate(tree), dtype=np.float32)
    if result.ndim == 0:
        result = np.full_like(next(iter(names.values())), float(result), dtype=np.float32)
    return result


def calculate_area(mask: np.ndarray, raster: EOData) -> Dict[str, Any]:
    """Calculate pixel count and physical area only when georeferencing is valid."""
    boolean = np.asarray(mask, dtype=bool)
    pixels = int(boolean.sum())
    result: Dict[str, Any] = {"pixel_count": pixels, "image_fraction": float(pixels / boolean.size), "area_m2": None, "area_available": False}
    if not raster.is_georeferenced or not raster.resolution:
        result["warning"] = "Physical area unavailable because CRS, transform, or resolution is missing."
        return result
    try:
        from pyproj import CRS, Geod
        from rasterio.transform import array_bounds

        crs = CRS.from_user_input(raster.crs)
        if crs.is_projected:
            result["area_m2"] = abs(raster.resolution[0] * raster.resolution[1]) * pixels
        else:
            geod = Geod(ellps="WGS84")
            pixel_width, pixel_height = abs(raster.resolution[0]), abs(raster.resolution[1])
            bounds = raster.bounds
            latitude = (bounds[1] + bounds[3]) / 2 if bounds else 0.0
            _, _, width_m = geod.inv(0, latitude, pixel_width, latitude)
            _, _, height_m = geod.inv(0, latitude, 0, latitude + pixel_height)
            result["area_m2"] = abs(width_m * height_m) * pixels
        result["area_available"] = True
        result["area_ha"] = result["area_m2"] / 10000.0
    except Exception as exc:
        result["warning"] = f"Physical area could not be derived safely: {exc}"
    return result


def zonal_statistics(values: np.ndarray, zones: np.ndarray) -> Dict[int, Dict[str, Any]]:
    array = np.asarray(values)
    zone_array = np.asarray(zones)
    if array.shape != zone_array.shape:
        raise ValueError("Values and zones must have identical shapes.")
    output: Dict[int, Dict[str, Any]] = {}
    for zone in np.unique(zone_array):
        if not np.isfinite(zone):
            continue
        output[int(zone)] = raster_statistics(EOData(array[None, ...], source="zonal"), array[zone_array == zone])
    return output
