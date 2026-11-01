# Optional Esri World Imagery fetcher

The image fetcher is an optional acquisition utility. It resolves a place or
coordinates, downloads one Esri World Imagery snapshot, and prints a local
image path that can be passed to `satquery ask`. The same implementation has
a limited point-query adapter in Earth Perception; it does not provide
footprint geometry or acquisition time and rejects unsupported EarthQuery
constraints. The downloaded image should not be represented as a fully
georeferenced scientific observation.

```powershell
cd satquery-ai
.\.venv\Scripts\python.exe -m connectors.image_fetcher --place "VIT Chennai, Vandalur" --zoom 18
.\.venv\Scripts\python.exe -m connectors.image_fetcher --lat 12.842946 --lon 80.155410 --zoom 19
```

Defaults are `zoom=18` and `2048x2048` output. Optional environment variables
use the `SATQUERY_FETCH_*` prefix. Place lookup tries Nominatim fallbacks,
then Photon for campuses, estates, and landmarks. Direct coordinates bypass
geocoding. This integration depends on Esri imagery and external geocoding
services; review their access terms, attribution, and availability before
operational use.
