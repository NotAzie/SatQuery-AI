# Stage 1 EO Foundation

SatQuery's EO foundation is additive to the existing `SatQueryEngine` and tool registry.

```text
EO path or RGB image
        |
        v
EOData metadata/data abstraction
        |
        +--> STAC discovery candidates (metadata only)
        |
        +--> safe raster expressions and statistics
        |
        +--> registered spectral indices
        |
        v
existing ToolResult / trace / API / CLI surfaces
```

## EOData

`satquery.eo.data.EOData` represents GeoTIFF/COG rasters and ordinary images. It preserves band descriptions, optional wavelength metadata, CRS, affine transform, bounds, resolution, acquisition time, sensor/platform, nodata, scale/offset, dtype, and warnings. Missing metadata remains `None`; the system does not invent CRS, GSD, sensor, date, or wavelength values.

Ordinary JPEG/PNG inputs are explicit non-georeferenced RGB fallbacks. They can be analyzed in image space, but physical area is unavailable.

## Discovery

`StacDiscoveryProvider` accepts a STAC API URL and returns `ImageryCandidate` metadata and asset links. Candidates remain `DISCOVERED`; discovery does not download or analyze assets. Spatial, temporal, collection, cloud, sensor, platform, and modality fields are provider-neutral query inputs.

## Scientific raster engine

`safe_expression` evaluates only named bands, numeric constants, and arithmetic operators. Raster statistics, masks, normalization, zonal statistics, and area calculations are deterministic NumPy operations. Physical area is returned only when georeferencing and resolution are available; otherwise the result contains image-space counts/fractions and a warning.

## Spectral intelligence

`INDEX_REGISTRY` defines NDVI, NDWI, MNDWI, NDBI, NBR, and EVI with formulas and required band aliases. `calculate_index` resolves named or explicitly mapped bands, returns an output raster plus statistics/provenance, and fails when required bands are missing. RGB channels are not silently treated as arbitrary multispectral bands.

## Product integration

The existing router recognizes EO inspection, raster statistics, and spectral-index queries. The existing orchestrator routes these requests before model backend construction, so deterministic scientific tools do not require BLIP/CLIP warmup. Results use the existing `ToolResult`, trace, error, and capability schemas.

The optional dependency set is in `satquery-ai/requirements-eo.txt` and `pyproject.toml` as `satquery-ai[eo]`: Rasterio, PyProj, Shapely, PySTAC, and PySTAC-Client. Core RGB installation remains unchanged.
