"""Fetch a target-aware, server-rendered high-detail EO image for inspection."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from plugins.image_fetcher.satellite_fetcher import fetch_zoomed_geotiff

if __name__ == "__main__":
    latitude=float(os.getenv("SATQUERY_ZOOM_LAT","12.8500")); longitude=float(os.getenv("SATQUERY_ZOOM_LON","80.1800"))
    target=os.getenv("SATQUERY_ZOOM_TARGET","building"); zoom=os.getenv("SATQUERY_ZOOM_LEVEL")
    image, metadata=fetch_zoomed_geotiff(latitude=latitude,longitude=longitude,target=target,zoom=int(zoom) if zoom else None,width=int(os.getenv("SATQUERY_ZOOM_WIDTH","2048")),height=int(os.getenv("SATQUERY_ZOOM_HEIGHT","2048")),output_dir=str(ROOT/"images"))
    print(json.dumps({"image":str(image),"metadata":str(metadata)},indent=2))
