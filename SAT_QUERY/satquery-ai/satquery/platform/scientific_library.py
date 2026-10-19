"""Cited Earth-science method knowledge, kept separate from certification.

Catalog records preserve published scope and validation evidence. They do not
make an implementation executable or certified; execution still requires the
existing content-addressed benchmark and certification gates.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Contract
from .scientific_knowledge import EARTH_SCIENCE_DOMAINS
from .scientific_methods import ScientificReference


class MethodValidationEvidence(Contract):
    evidence_type: Literal["published_validation", "method_definition_only"]
    description: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)


class MethodMeasurementRequirement(Contract):
    variable: str = Field(min_length=1)
    compatible_units: tuple[str, ...] = Field(min_length=1)


class ScientificMethodKnowledge(Contract):
    method_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    publication: ScientificReference
    validation_evidence: MethodValidationEvidence
    assumptions: tuple[str, ...] = Field(min_length=1)
    applicability: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    required_variables: tuple[str, ...] = Field(min_length=1)
    required_measurements: tuple[MethodMeasurementRequirement, ...] = Field(min_length=1)
    minimum_observation_count: int | None = Field(default=None, ge=1)
    required_uncertainty_categories: tuple[str, ...] = ()
    required_datasets: tuple[str, ...] = Field(min_length=1)
    required_modalities: tuple[str, ...] = Field(min_length=1)
    uncertainty_model: str = Field(min_length=1)
    benchmark_suite_id: str | None = None
    benchmark_reference: ScientificReference | None = None
    benchmark_status: Literal["identified_not_materialized", "not_identified", "registered_executable"] = "identified_not_materialized"
    reproducibility_requirements: tuple[str, ...] = Field(min_length=1)
    implementation_status: Literal[
        "reference_catalog_only", "implementation_pending",
        "benchmark_pending", "executable_certified",
    ] = "reference_catalog_only"
    executable_method_id: str | None = None
    executable_method_version: str | None = None

    @model_validator(mode="after")
    def execution_requires_registered_identity(self) -> ScientificMethodKnowledge:
        if self.implementation_status == "executable_certified":
            if not self.executable_method_id or not self.executable_method_version:
                raise ValueError("certified catalog methods require an executable method identity")
            if self.benchmark_status != "registered_executable" or not self.benchmark_suite_id:
                raise ValueError("certified catalog methods require an executable benchmark suite identity")
        elif self.executable_method_id or self.executable_method_version:
            raise ValueError("non-executable catalog records cannot point to an executable method")
        if self.benchmark_status == "registered_executable" and not self.benchmark_suite_id:
            raise ValueError("registered executable benchmark status requires a suite identity")
        return self


class ScientificKnowledgeLibrary:
    def __init__(self, methods: Iterable[ScientificMethodKnowledge] = ()) -> None:
        self._methods: dict[tuple[str, str], ScientificMethodKnowledge] = {}
        for method in methods:
            self.register(method)

    def register(self, method: ScientificMethodKnowledge) -> None:
        key = (method.method_id, method.version)
        if key in self._methods:
            raise ValueError(f"scientific knowledge already registered: {key[0]}@{key[1]}")
        reference_ids = {
            method.publication.reference_id, method.benchmark_reference.reference_id,
        }
        if not set(method.validation_evidence.evidence_references).issubset(reference_ids):
            raise ValueError("method validation evidence must cite its declared references")
        self._methods[key] = method

    def all(self) -> tuple[ScientificMethodKnowledge, ...]:
        return tuple(self._methods[key] for key in sorted(self._methods))

    def get(self, method_id: str, version: str) -> ScientificMethodKnowledge | None:
        return self._methods.get((method_id, version))

    def for_domain(self, domain: str) -> tuple[ScientificMethodKnowledge, ...]:
        return tuple(item for item in self.all() if item.domain == domain)

    def domain_catalog(self) -> tuple[dict[str, object], ...]:
        return tuple({
            "domain": domain,
            "method_ids": tuple(item.method_id for item in self.for_domain(domain)),
            "executable_method_ids": tuple(
                item.method_id for item in self.for_domain(domain)
                if item.implementation_status == "executable_certified"
            ),
            "status": (
                "cited_catalog_records_only"
                if self.for_domain(domain)
                else "no_documented_method_record"
            ),
        } for domain in EARTH_SCIENCE_DOMAINS)


def documented_reference_methods() -> tuple[ScientificMethodKnowledge, ...]:
    """Small audited seed catalog; records remain non-executable by design."""
    dswe_paper = ScientificReference(
        reference_id="jones-2019-dswe-psw",
        title="Improved Automated Detection of Subpixel-Scale Inundation—Revised DSWE Partial Surface Water Tests",
        citation="Jones, J. (2019), Remote Sensing, 11(4), 374.",
        doi="10.3390/rs11040374", publication_year=2019,
    )
    dswe_benchmark = ScientificReference(
        reference_id="jones-2019-dswe-validation",
        title="Revised DSWE partial surface water tests evaluated against Everglades EDEN observations",
        citation="Evaluation described in Jones (2019), Remote Sensing 11(4), 374.",
        doi="10.3390/rs11040374", publication_year=2019,
    )
    spi_reference = ScientificReference(
        reference_id="mckee-1993-spi",
        title="The Relationship of Drought Frequency and Duration to Time Scales",
        citation="McKee, T.B., Doesken, N.J., and Kleist, J. (1993), 8th Conference on Applied Climatology, pp. 179–184.",
        uri="https://ccc.atmos.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf",
        publication_year=1993,
    )
    spi_benchmark = ScientificReference(
        reference_id="wmo-2012-spi-guide",
        title="Standardized Precipitation Index User Guide",
        citation="World Meteorological Organization (2012), WMO-No. 1090.",
        uri="https://library.wmo.int/idurl/4/39629", publication_year=2012,
    )
    burn_reference = ScientificReference(
        reference_id="picotte-2021-burn-severity",
        title="Determination of burn severity models ranging from regional to continental scales for the conterminous United States",
        citation="Picotte et al. (2021), Remote Sensing of Environment, 263, 112569.",
        doi="10.1016/j.rse.2021.112569", publication_year=2021,
    )
    landcover_reference = ScientificReference(
        reference_id="yang-2018-nlcd-methodology",
        title="Overall methodology design for the United States National Land Cover Database 2016 products",
        citation="Yang et al. (2018), Remote Sensing, 11(3), 297.",
        uri="https://pubs.usgs.gov/publication/70245784", publication_year=2018,
    )
    glacier_reference = ScientificReference(
        reference_id="vincent-2021-geodetic-point-smb",
        title="Geodetic point surface mass balances: a new approach to determine point surface mass balances on glaciers from remote sensing measurements",
        citation="Vincent et al. (2021), The Cryosphere, 15, 1259–1276.",
        doi="10.5194/tc-15-1259-2021", publication_year=2021,
    )
    vegetation_reference = ScientificReference(
        reference_id="tucker-1979-vegetation-index",
        title="Red and photographic infrared linear combinations for monitoring vegetation",
        citation="Tucker (1979), Remote Sensing of Environment, 8(2), 127–150.",
        doi="10.1016/0034-4257(79)90013-0", publication_year=1979,
    )
    urban_reference = ScientificReference(
        reference_id="urban-growth-harmonic-2021",
        title="Urban Growth Derived from Landsat Time Series Using Harmonic Analysis: A Case Study in South England with High Levels of Cloud Cover",
        citation="Remote Sensing (2021), 13(16), 3339.",
        doi="10.3390/rs13163339", publication_year=2021,
    )

    return (
        ScientificMethodKnowledge(
            method_id="landsat-dswe-psw-v2", version="reference-1", title="Revised Landsat DSWE Partial Surface Water Tests",
            domain="hydrology", publication=dswe_paper,
            validation_evidence=MethodValidationEvidence(
                evidence_type="published_validation",
                description="The paper reports rerunning the EDEN-based experiments; mean overall agreement improved 4% and omission error declined 11% for the revised PSW tests. SatQuery has not independently rerun these comparisons.",
                evidence_references=(dswe_paper.reference_id,),
                limitations=("The published validation context does not establish universal performance across regions or conditions.",),
            ),
            assumptions=("Inputs conform to the Landsat surface-reflectance product specification used by the method.", "Cloud, shadow, and snow screening is applied as specified by the referenced method."),
            applicability=("Landsat surface-water extent mapping within the method's documented sensor and environmental scope.",),
            limitations=("This method record is specifically for the revised partial-surface-water component, not a complete independent implementation of every DSWE test.", "Published EDEN validation is site- and condition-bounded; performance varies with vegetation, substrate, clouds, and mixed pixels.", "The SatQuery raster-processing and benchmark adapter has not been implemented."),
            required_variables=("surface_reflectance", "elevation"),
            required_measurements=(
                MethodMeasurementRequirement(variable="surface_reflectance", compatible_units=("1",)),
                MethodMeasurementRequirement(variable="elevation", compatible_units=("m",)),
            ),
            minimum_observation_count=1,
            required_uncertainty_categories=("measurement", "dataset"),
            required_datasets=("Landsat surface reflectance; DEM meeting the cited method specification",),
            required_modalities=("visual", "geological"),
            uncertainty_model="Method-specific classification uncertainty must be supplied by an independently validated implementation; this catalog does not infer pixel-level uncertainty.",
            benchmark_suite_id=None,
            benchmark_reference=dswe_benchmark,
            benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record Landsat collection and processing level.", "Record DEM identity/version and preprocessing.", "Record algorithm implementation digest and all quality masks.", "Retain reference observations and spatial/temporal match policy."),
        ),
        ScientificMethodKnowledge(
            method_id="standardized-precipitation-index", version="reference-1", title="Standardized Precipitation Index",
            domain="drought", publication=spi_reference,
            validation_evidence=MethodValidationEvidence(
                evidence_type="method_definition_only",
                description="Foundational publication defines the index and time-scale framing; it is method documentation, not independent performance validation for a SatQuery implementation.",
                evidence_references=(spi_reference.reference_id,),
                limitations=("Reference period, probability distribution fitting, zero-precipitation treatment, accumulation window, and calibration choices affect results and must be specified.",),
            ),
            assumptions=("Precipitation time series are temporally complete and homogeneous enough for the selected calibration procedure.", "Accumulation window and calibration reference period are explicitly declared."),
            applicability=("Meteorological drought characterization from precipitation at an explicitly selected accumulation scale.",),
            limitations=("SPI uses precipitation alone and does not represent evapotranspiration or other drought dimensions.", "No distribution-fitting implementation or uncertainty propagation is included in SatQuery yet."),
            required_variables=("precipitation",),
            required_measurements=(
                MethodMeasurementRequirement(variable="precipitation", compatible_units=("mm",)),
            ),
            required_uncertainty_categories=("measurement", "model"),
            required_datasets=("Versioned precipitation time series with declared temporal sampling and calibration coverage",),
            required_modalities=("atmospheric",),
            uncertainty_model="Requires explicit treatment of sampling and distribution-fit uncertainty; no uncertainty estimator is specified or computed by this catalog.",
            benchmark_suite_id=None,
            benchmark_reference=spi_benchmark,
            benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record accumulation scale and calendar handling.", "Record calibration period, fitting method, zero handling, and software digest.", "Preserve source series, missing-data policy, and fit diagnostics."),
        ),
        ScientificMethodKnowledge(
            method_id="regional-cbi-burn-severity", version="reference-1",
            title="Scale-selected Landsat dNBR/NBR regression to Composite Burn Index",
            domain="wildfire", publication=burn_reference,
            validation_evidence=MethodValidationEvidence(
                evidence_type="published_validation",
                description="Published study fit and compared scale-specific regression models using 6,280 Composite Burn Index plots across 234 CONUS fires; model fit varied substantially by vegetation/ecoregion and scale.",
                evidence_references=(burn_reference.reference_id,),
                limitations=("Applicability is conterminous United States and represented vegetation/ecoregion strata.", "Reported model fit ranges from weak to strong across regions; some areas require more field plots or alternative transformations."),
            ),
            assumptions=("Field CBI plots and Landsat NBR/dNBR are spatially and temporally matched using the referenced procedures.", "A regression scale is selected using the paper's decision framework.", "Training-domain ecological classes represent the target fire."),
            applicability=("Estimating CBI-scale burn severity for CONUS fires where the applicable published regression and ecological classification are available.",),
            limitations=("Requires the published regression coefficients and decision schema, which are not bundled here.", "Outside CONUS or unsupported vegetation strata require separate validation.", "Satellite index-to-field-severity relationships are not universal."),
            required_variables=("prefire_nbr", "postfire_nbr", "landcover_class"),
            required_measurements=(
                MethodMeasurementRequirement(variable="prefire_nbr", compatible_units=("1",)),
                MethodMeasurementRequirement(variable="postfire_nbr", compatible_units=("1",)),
                MethodMeasurementRequirement(variable="landcover_class", compatible_units=("1",)),
            ),
            required_uncertainty_categories=("measurement", "model"),
            required_datasets=("Landsat surface reflectance for prefire and postfire windows", "Applicable vegetation/ecoregion classification and versioned CBI regression coefficients"),
            required_modalities=("visual", "ecological"),
            uncertainty_model="The publication reports scale-specific regression fit statistics and ranges; implementation must retain the selected regression residual/calibration uncertainty and must not convert R-squared into per-fire confidence.",
            benchmark_reference=burn_reference, benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record Landsat scenes, QA masks, acquisition windows, and NBR/dNBR derivation.", "Record ecological classification and regression-scale decision.", "Record coefficient version, training plot provenance, and model residual diagnostics."),
        ),
        ScientificMethodKnowledge(
            method_id="nlcd-2016-land-cover-workflow", version="reference-1",
            title="US National Land Cover Database 2016 land-cover and change production workflow",
            domain="land_cover", publication=landcover_reference,
            validation_evidence=MethodValidationEvidence(
                evidence_type="published_validation",
                description="The published workflow reports an initial accuracy assessment on four selected Landsat path/rows: 82.0% at Anderson Level II and 86.6% at Level I after combining primary and alternate reference labels.",
                evidence_references=(landcover_reference.reference_id,),
                limitations=("The reported initial assessment covers four selected path/rows and is not a national accuracy guarantee.", "NLCD workflow includes curated training, ancillary data, postprocessing, integration, and region-specific production decisions."),
            ),
            assumptions=("Target area lies within the conterminous United States and uses the stated NLCD 2016 class definitions.", "Input imagery and ancillary layers are aligned and processed according to the documented workflow.",),
            applicability=("Reproduction or evaluation of NLCD 2016 workflow components for its documented CONUS classes and epochs.",),
            limitations=("This production workflow is not a provider-neutral generic classifier.", "Reference labels, training data, ancillary layers, code, and full benchmark inputs are not packaged in SatQuery."),
            required_variables=("multispectral_surface_reflectance",),
            required_measurements=(MethodMeasurementRequirement(variable="multispectral_surface_reflectance", compatible_units=("1",)),),
            required_uncertainty_categories=("measurement", "dataset", "model"),
            required_datasets=("Multi-temporal Landsat imagery, reference/training labels, and workflow-specific ancillary datasets",),
            required_modalities=("visual",),
            uncertainty_model="The cited workflow reports thematic accuracy on an initial selected sample. A SatQuery implementation must carry class-specific confusion/accuracy statistics and sampling-design uncertainty from an applicable reference assessment; no class confidence is inferred here.",
            benchmark_reference=landcover_reference, benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record Landsat collection, epochs, QA masks, and preprocessing.", "Record training/reference labels and ancillary data versions.", "Record class schema, change-detection steps, postprocessing, and assessment sampling design."),
        ),
        ScientificMethodKnowledge(
            method_id="geodetic-point-glacier-surface-mass-balance", version="reference-1",
            title="Geodetic point surface mass balance from surface elevation and ice velocity",
            domain="cryosphere", publication=glacier_reference,
            validation_evidence=MethodValidationEvidence(
                evidence_type="published_validation",
                description="The study compared reconstructed point balances with in-situ stake observations at Argentière and Mer de Glace; reported remote-sensing uncertainty ranged about 0.20–0.60 m water equivalent per year in the studied settings.",
                evidence_references=(glacier_reference.reference_id,),
                limitations=("Validation sites and glacier zones are limited; method depends on accurately measured vertical velocity and spatially co-located surface velocity/elevation.", "The paper reports sensitivity to roughness and spatial velocity gradients."),
            ),
            assumptions=("Annual vertical velocities are sufficiently stable over the reconstruction interval.", "Surface elevation and horizontal displacement endpoints are measured at the same locations, within the documented spatial tolerance.", "The method is applied in the documented ablation-zone context."),
            applicability=("Point surface mass balance reconstruction for glacier ablation zones with past vertical-velocity observations and co-located elevation/flow measurements.",),
            limitations=("Not a glacier-wide balance method.", "Requires in-situ vertical velocity history; remote sensing inputs alone are insufficient.", "The reported error range is site and data quality dependent."),
            required_variables=("surface_elevation", "horizontal_ice_velocity", "vertical_ice_velocity"),
            required_measurements=(
                MethodMeasurementRequirement(variable="surface_elevation", compatible_units=("m",)),
                MethodMeasurementRequirement(variable="horizontal_ice_velocity", compatible_units=("m/year",)),
                MethodMeasurementRequirement(variable="vertical_ice_velocity", compatible_units=("m/year",)),
            ),
            required_uncertainty_categories=("measurement", "model"),
            required_datasets=("Co-located repeated DEM or surface elevations, ice-flow displacement/velocity, and field vertical-velocity observations",),
            required_modalities=("visual", "cryospheric"),
            uncertainty_model="The paper propagates two elevation uncertainty terms and vertical-velocity uncertainty assuming uncorrelated errors; implementation must expose those inputs, assumptions, and covariance limitation.",
            benchmark_reference=glacier_reference, benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record glacier boundary and point locations.", "Record DEM/elevation and velocity source versions, temporal intervals, co-location tolerance, and field vertical-velocity history.", "Record uncertainty inputs and uncorrelated-error assumption."),
        ),
        ScientificMethodKnowledge(
            method_id="tucker-vegetation-index", version="reference-1",
            title="Tucker red and photographic-infrared vegetation index family",
            domain="vegetation", publication=vegetation_reference,
            validation_evidence=MethodValidationEvidence(
                evidence_type="published_validation",
                description="The paper empirically evaluated red/photographic-infrared radiance combinations against vegetation parameters and reported sensitivity of its normalized difference index to photosynthetically active vegetation.",
                evidence_references=(vegetation_reference.reference_id,),
                limitations=("The study's sensors, targets, and empirical domain do not establish universal calibration to biomass, health, or productivity.", "The index is a spectral diagnostic and does not itself establish vegetation condition or cause."),
            ),
            assumptions=("Red and photographic-infrared radiances are calibrated and spatially/temporally comparable.", "The measurement is used as a spectral vegetation index only, without asserting direct biomass equivalence."),
            applicability=("Computing the cited radiance index variants for compatible multispectral observations.",),
            limitations=("Atmospheric, soil-background, canopy, sensor-response, and illumination effects remain relevant.", "No validated uncertainty propagation or universal thresholds are supplied by this catalog."),
            required_variables=("red_radiance", "photographic_infrared_radiance"),
            required_measurements=(
                MethodMeasurementRequirement(variable="red_radiance", compatible_units=("W m-2 sr-1 um-1",)),
                MethodMeasurementRequirement(variable="photographic_infrared_radiance", compatible_units=("W m-2 sr-1 um-1",)),
            ),
            required_uncertainty_categories=("measurement", "dataset"),
            required_datasets=("Calibrated multispectral radiance with compatible red and photographic-infrared bands",),
            required_modalities=("visual",),
            uncertainty_model="No uncertainty estimator is asserted by this reference record; radiometric and processing uncertainty must be declared and propagated by a separately validated implementation.",
            benchmark_reference=vegetation_reference, benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record sensor band definitions/responses and calibration version.", "Record radiometric/atmospheric processing, masks, and exact index variant.", "Preserve source radiances and metadata."),
        ),
        ScientificMethodKnowledge(
            method_id="landsat-harmonic-urban-growth", version="reference-1",
            title="Urban growth detection from Landsat time series using harmonic analysis",
            domain="urban_analysis", publication=urban_reference,
            validation_evidence=MethodValidationEvidence(
                evidence_type="published_validation",
                description="The case study assessed change detection against 500 manually examined reference points across four South England urban-development sites.",
                evidence_references=(urban_reference.reference_id,),
                limitations=("Evaluation is tied to the selected South England sites and development types.", "The method performs less well where urban change produces small NDVI-dynamics differences, including dense built-up contexts."),
            ),
            assumptions=("Multi-year Landsat observations provide sufficient temporal sampling after cloud screening.", "Urban growth produces a temporally detectable vegetation/land-cover trajectory in the target setting."),
            applicability=("Site-specific urban-growth detection for landscapes and transitions similar to the published South England case study.",),
            limitations=("Not a universal urban-expansion classifier.", "Cloud, temporal sampling, urban density, and transition type influence detectability.", "The published reference points and full workflow are not bundled here."),
            required_variables=("multispectral_surface_reflectance", "vegetation_index"),
            required_measurements=(
                MethodMeasurementRequirement(variable="multispectral_surface_reflectance", compatible_units=("1",)),
                MethodMeasurementRequirement(variable="vegetation_index", compatible_units=("1",)),
            ),
            required_uncertainty_categories=("measurement", "model"),
            required_datasets=("Multi-year Landsat surface-reflectance time series and reference change labels",),
            required_modalities=("visual", "human"),
            uncertainty_model="The source reports reference-point accuracy assessment; a reproducible implementation must retain its sampling design, class confusion counts, and date/phenology uncertainty. No confidence is derived by this catalog.",
            benchmark_reference=urban_reference, benchmark_status="identified_not_materialized",
            reproducibility_requirements=("Record Landsat scene set, QA/cloud masks, harmonic model configuration, and temporal gaps.", "Record reference-point interpretation and sampling design.", "Record urban-change class definitions and validation contingency table."),
        ),
    )
