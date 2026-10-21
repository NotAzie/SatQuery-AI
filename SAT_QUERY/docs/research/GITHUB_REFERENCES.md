# Software and standards references

SatQuery uses the following upstream projects or interoperability standards.
This inventory records dependencies and formats used by the code; it does not
claim that SatQuery implements every feature in those projects or conforms to
every part of a standard.

| Reference | Current use in SatQuery |
|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | HTTP application and OpenAPI route descriptions. |
| [Pydantic](https://github.com/pydantic/pydantic) | Validated request, configuration, and platform contracts. |
| [Uvicorn](https://github.com/encode/uvicorn) | Local ASGI server. |
| [HTTPX](https://github.com/encode/httpx) | Async-capable HTTP client used by connectors. |
| [pytest](https://github.com/pytest-dev/pytest) | Test runner. |
| [Rasterio](https://github.com/rasterio/rasterio) | Optional raster asset reading and supported raster operations. |
| [Shapely](https://github.com/shapely/shapely) and [PyProj](https://github.com/pyproj/pyproj) | Optional geometry and CRS utility dependencies; presence does not mean all geometries are automatically transformed. |
| [STAC API](https://github.com/radiantearth/stac-api-spec) | STAC search interoperability used by the STAC connector. |
| [OGC CRS84](https://www.ogc.org/standard/crs/) | Explicit coordinate reference labels in supported query and memory contracts. |

Dependency versions and optional extras are defined in
`satquery-ai/pyproject.toml`. Consult each upstream project's license and
SatQuery's dependency metadata before redistributing a packaged deployment.
No GitHub repository is treated as a source of scientific validation.
