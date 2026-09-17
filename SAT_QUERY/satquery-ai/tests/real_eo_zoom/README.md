# Zoom-aware real EO acquisition

This opt-in experiment uses the existing Esri World Imagery export provider to
request a new, smaller geographic extent at target-aware web-map zoom. It does
not enlarge the previous Sentinel-2 or JPEG pixels. The returned PNG is wrapped
as a GeoTIFF using the exact provider-requested EPSG:4326 bounding box.

```powershell
$env:SATQUERY_ZOOM_LAT='12.8500'
$env:SATQUERY_ZOOM_LON='80.1800'
$env:SATQUERY_ZOOM_TARGET='building' # general | water | road | building | vehicle
python tests/real_eo_zoom/fetch_zoomed_eo.py
```

Defaults: general/water zoom 18, road 19, building/vehicle 20, 2048 px square.
The Esri export endpoint is server-rendered rather than a tile endpoint, so it
does not require client-side stitching. Its native mosaic GSD varies by place:
web-map zoom is not proof of native imagery resolution, particularly for vehicles.
