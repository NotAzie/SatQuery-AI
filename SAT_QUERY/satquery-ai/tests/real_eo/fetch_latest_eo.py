from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import planetary_computer
import pystac_client
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
STAC_URL = os.getenv("SATQUERY_TEST_STAC_URL", "https://planetarycomputer.microsoft.com/api/stac/v1")
DEFAULT_AOI = (80.10, 12.80, 80.20, 12.90)


def _bbox() -> tuple[float, float, float, float]:
    raw = os.getenv("SATQUERY_TEST_AOI")
    if not raw:
        return DEFAULT_AOI
    values = tuple(float(value.strip()) for value in raw.split(","))
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("SATQUERY_TEST_AOI must be min_lon,min_lat,max_lon,max_lat.")
    return values  # type: ignore[return-value]


def _date_range() -> str:
    end = os.getenv("SATQUERY_TEST_END", date.today().isoformat())
    start = os.getenv("SATQUERY_TEST_START", (date.today() - timedelta(days=30)).isoformat())
    return f"{start}/{end}"


def fetch() -> dict:
    bbox = _bbox()
    max_cloud = float(os.getenv("SATQUERY_TEST_MAX_CLOUD", "35"))
    collection = os.getenv("SATQUERY_TEST_COLLECTION", "sentinel-2-l2a")
    client = pystac_client.Client.open(STAC_URL)
    search = client.search(
        collections=[collection],
        bbox=list(bbox),
        datetime=_date_range(),
        query={"eo:cloud_cover": {"lt": max_cloud}},
        max_items=20,
    )
    items = sorted(
        list(search.items()),
        key=lambda item: (item.datetime is None, -(item.datetime.timestamp() if item.datetime else 0)),
    )
    if not items:
        raise RuntimeError("No fresh Sentinel-2 item matched the configured AOI/date/cloud filters.")
    item = planetary_computer.sign(items[0])
    item_id = item.id
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    metadata_path = RAW / f"{item_id}.json"
    metadata = {
        "item_id": item.id,
        "source": STAC_URL,
        "collection": item.collection_id,
        "platform": item.properties.get("platform"),
        "instruments": item.properties.get("instruments"),
        "acquisition_datetime": item.datetime.isoformat() if item.datetime else None,
        "cloud_cover": item.properties.get("eo:cloud_cover"),
        "aoi": bbox,
        "assets": {key: asset.href.split("?", 1)[0] for key, asset in item.assets.items() if key in {"B02", "B03", "B04", "B08"}},
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    bands = [("blue", "B02"), ("green", "B03"), ("red", "B04"), ("nir", "B08")]
    datasets = []
    try:
        for name, asset_key in bands:
            dataset = rasterio.open(item.assets[asset_key].href)
            datasets.append((name, dataset))
        reference = datasets[0][1]
        target_bounds = transform_bounds("EPSG:4326", reference.crs, *bbox, densify_pts=21)
        window = from_bounds(*target_bounds, transform=reference.transform).round_offsets().round_lengths()
        window = window.intersection(rasterio.windows.Window(0, 0, reference.width, reference.height))
        if window.width < 32 or window.height < 32:
            raise RuntimeError("Requested AOI produced an image too small for inference.")
        output = PROCESSED / f"{item_id}_B02-B03-B04-B08.tif"
        # Remote COG reads can fail after the local writer is opened.  Write a
        # sibling partial file and publish it only after every band succeeds.
        partial = output.with_suffix(output.suffix + ".partial")
        profile = reference.profile.copy()
        profile.update(count=4, dtype="uint16", compress="deflate", tiled=True, BIGTIFF="IF_SAFER", width=int(window.width), height=int(window.height), transform=reference.window_transform(window))
        with rasterio.open(partial, "w", **profile) as target:
            for index, (name, dataset) in enumerate(datasets, 1):
                target.write(dataset.read(1, window=window), index)
                target.set_band_description(index, name)
            target.update_tags(
                acquisition_datetime=metadata["acquisition_datetime"] or "",
                platform=metadata["platform"] or "",
                collection=collection,
                source=STAC_URL,
                source_item=item.id,
                cloud_cover=str(metadata["cloud_cover"]),
                aoi=json.dumps(bbox),
            )
        partial.replace(output)
    finally:
        if 'partial' in locals() and partial.exists():
            partial.unlink()
        for _, dataset in datasets:
            dataset.close()
    return {"metadata": str(metadata_path), "raster": str(output), **metadata}


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=2))
