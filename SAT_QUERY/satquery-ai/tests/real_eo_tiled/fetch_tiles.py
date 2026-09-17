from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

from plugins.image_fetcher.satellite_fetcher import fetch_zoomed_geotiff

ROOT = Path(__file__).resolve().parent
TILES = ROOT / "tiles"


def _span(latitude: float, zoom: int, width: int, height: int) -> tuple[float, float]:
    lat_span = 360.0 * max(width, height) / 256.0 / (2**zoom)
    lon_span = lat_span / max(0.1, abs(math.cos(math.radians(latitude))))
    return lon_span, lat_span


def acquire() -> dict:
    lat = float(os.getenv("SATQUERY_TILE_LAT", "12.8500"))
    lon = float(os.getenv("SATQUERY_TILE_LON", "80.1800"))
    rows = int(os.getenv("SATQUERY_TILE_ROWS", "2"))
    cols = int(os.getenv("SATQUERY_TILE_COLS", "2"))
    overlap = float(os.getenv("SATQUERY_TILE_OVERLAP", "0.20"))
    zoom = int(os.getenv("SATQUERY_TILE_ZOOM", "19"))
    width = int(os.getenv("SATQUERY_TILE_WIDTH", "1024"))
    height = int(os.getenv("SATQUERY_TILE_HEIGHT", "1024"))
    if rows < 1 or cols < 1 or not 0 <= overlap < 1:
        raise ValueError("rows/cols must be positive and overlap must be in [0,1).")
    lon_span, lat_span = _span(lat, zoom, width, height)
    step_lon, step_lat = lon_span * (1 - overlap), lat_span * (1 - overlap)
    center_lon = lon - (cols - 1) * step_lon / 2
    center_lat = lat - (rows - 1) * step_lat / 2
    tiles = []
    for row in range(rows):
        for col in range(cols):
            tile_lat = center_lat + row * step_lat
            tile_lon = center_lon + col * step_lon
            path, metadata = fetch_zoomed_geotiff(
                latitude=tile_lat,
                longitude=tile_lon,
                target="building",
                zoom=zoom,
                width=width,
                height=height,
                output_dir=str(TILES),
            )
            meta = json.loads(metadata.read_text(encoding="utf-8"))
            tiles.append({"tile_id": f"tile-{row:02d}-{col:02d}", "row": row, "col": col, "path": str(path), "metadata": str(metadata), "center": [tile_lat, tile_lon], "bounds": meta["bounds"], "requested_zoom": zoom, "width": width, "height": height})
    union = [min(tile["bounds"][0] for tile in tiles), min(tile["bounds"][1] for tile in tiles), max(tile["bounds"][2] for tile in tiles), max(tile["bounds"][3] for tile in tiles)]
    result = {"center": [lat, lon], "rows": rows, "cols": cols, "overlap": overlap, "zoom": zoom, "tile_size": [width, height], "tile_span": [lon_span, lat_span], "union_bounds": union, "tiles": tiles}
    (TILES / "acquisition.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(acquire(), indent=2))
