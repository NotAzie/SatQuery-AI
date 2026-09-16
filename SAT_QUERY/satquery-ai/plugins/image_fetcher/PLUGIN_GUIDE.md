# Optional Image Fetcher Guide

This plugin is separate from the SatQuery core query flow. It resolves a place or coordinates, downloads one Esri World Imagery snapshot, and prints a path that can be passed to `satquery ask`.

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m plugins.image_fetcher --place "VIT Chennai, Vandalur" --zoom 18
..\.venv\Scripts\python.exe -m plugins.image_fetcher --lat 12.842946 --lon 80.155410 --zoom 19
```

Defaults are `zoom=18` and `2048x2048` output. Optional environment variables use the `SATQUERY_FETCH_*` prefix. Place lookup tries Nominatim fallbacks, then Photon for campuses, estates, and landmarks. Direct coordinates bypass geocoding and are the most reliable option.
