# Cited scientific method records

The list below mirrors the seed records in
`satquery.platform.scientific_library.documented_reference_methods()`.
These citations are research catalog metadata, not claims that SatQuery
implements or validates the methods. The catalog explicitly marks its method
records as non-executable until implementation, benchmark assets, and
governance requirements are satisfied.

| Domain / record | Cited publication | Why it is cataloged | SatQuery status |
|---|---|---|---|
| Hydrology — revised Landsat DSWE partial-surface-water tests | Jones (2019), “Improved Automated Detection of Subpixel-Scale Inundation—Revised DSWE Partial Surface Water Tests,” *Remote Sensing* 11(4), 374. DOI: [10.3390/rs11040374](https://doi.org/10.3390/rs11040374). | Method reference and bounded EDEN evaluation. | Reference only; raster method/benchmark not implemented. |
| Drought — Standardized Precipitation Index | McKee, Doesken & Kleist (1993), “The Relationship of Drought Frequency and Duration to Time Scales,” 8th Conference on Applied Climatology, 179–184. [Catalog URI](https://ccc.atmos.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf). | Foundational method definition. WMO (2012), *Standardized Precipitation Index User Guide*, WMO-No. 1090, [guide](https://library.wmo.int/idurl/4/39629), is separately listed as an identified benchmark reference. | Reference only; fitting/calibration and uncertainty implementation absent. |
| Wildfire — regional CBI burn severity | Picotte et al. (2021), “Determination of burn severity models ranging from regional to continental scales for the conterminous United States,” *Remote Sensing of Environment* 263, 112569. DOI: [10.1016/j.rse.2021.112569](https://doi.org/10.1016/j.rse.2021.112569). | Cites scale- and region-dependent model evaluation. | Reference only; coefficients, field benchmark data, and method implementation absent. |
| Land cover — NLCD 2016 workflow | Yang et al. (2018), “Overall methodology design for the United States National Land Cover Database 2016 products,” *Remote Sensing* 11(3), 297. [USGS publication record](https://pubs.usgs.gov/publication/70245784). | Documents a production workflow and a bounded initial accuracy assessment. | Reference only; not an NLCD production implementation. |
| Cryosphere — geodetic point glacier surface mass balance | Vincent et al. (2021), “Geodetic point surface mass balances: a new approach to determine point surface mass balances on glaciers from remote sensing measurements,” *The Cryosphere* 15, 1259–1276. DOI: [10.5194/tc-15-1259-2021](https://doi.org/10.5194/tc-15-1259-2021). | Cites method and study-specific uncertainty assumptions. | Reference only; no implementation or supplied reference investigations. |
| Vegetation — red/NIR vegetation-index family | Tucker (1979), “Red and photographic infrared linear combinations for monitoring vegetation,” *Remote Sensing of Environment* 8(2), 127–150. DOI: [10.1016/0034-4257(79)90013-0](https://doi.org/10.1016/0034-4257(79)90013-0). | Historical spectral diagnostic reference. | Reference only; index derivation/calibration is not bundled. |
| Urban analysis — Landsat harmonic urban-growth case study | “Urban Growth Derived from Landsat Time Series Using Harmonic Analysis: A Case Study in South England with High Levels of Cloud Cover,” *Remote Sensing* (2021) 13(16), 3339. DOI: [10.3390/rs13163339](https://doi.org/10.3390/rs13163339). | Cites a geographically bounded case study. | Reference only; not a general urban-growth detector. |

Each catalog record carries assumptions, applicability limits, required
measurements/modalities, uncertainty requirements, and benchmark status in
code. Verify those fields there before using a record in research. This page
does not substitute for consulting the original publication or checking its
license and version.
