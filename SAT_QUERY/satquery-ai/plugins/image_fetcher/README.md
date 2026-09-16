# Optional Image Fetcher

This plugin is separate from the SatQuery core query flow. It resolves a place or coordinates, downloads one Esri World Imagery snapshot, and prints a path that can be passed to `satquery ask`.

```powershell
python -m plugins.image_fetcher --place "VIT Chennai, Vandalur" --zoom 18
python -m plugins.image_fetcher --lat 12.842946 --lon 80.155410 --zoom 19
```

Defaults are `zoom=18` and `2048x2048` output. Override them with `--zoom` or these optional environment variables:

- `SATQUERY_FETCH_OUTPUT_DIR`
- `SATQUERY_FETCH_ZOOM`
- `SATQUERY_FETCH_IMAGE_SIZE` (`512` to `2048`)
- `SATQUERY_FETCH_TIMEOUT`
- `SATQUERY_FETCH_USER_AGENT`
- `SATQUERY_FETCH_GEOCODER_URL`
- `SATQUERY_FETCH_ALTERNATE_GEOCODER_URL`
- `SATQUERY_FETCH_PROVIDER_URL`

Place lookup tries Nominatim with several address fallbacks, then Photon for campuses, estates, and landmarks that are missing from Nominatim. Direct coordinates bypass geocoding and are the most reliable option.
