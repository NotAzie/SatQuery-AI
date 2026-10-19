"""Conservative canonical concepts for commonly used Earth observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class EarthConcept:
    concept_id: str
    label: str
    parent_id: Optional[str] = None
    aliases: tuple[str, ...] = ()
    related_concepts: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EarthVariable:
    canonical_name: str
    concept_id: str
    label: str
    aliases: tuple[str, ...] = ()
    standard_name: Optional[str] = None
    ontology_uri: Optional[str] = None
    unit_dimension: Optional[str] = None
    canonical_units: tuple[str, ...] = ()
    related_variables: tuple[str, ...] = ()


class EarthVariableOntology:
    """Immutable lookup over declared Earth concepts and variable aliases.

    Alias resolution deliberately returns no canonical variable when a term is
    ambiguous. Source-specific metadata should resolve those cases explicitly.
    """

    def __init__(
        self,
        concepts: Iterable[EarthConcept],
        variables: Iterable[EarthVariable],
    ) -> None:
        concept_values = tuple(concepts)
        variable_values = tuple(variables)
        self._concepts = {item.concept_id: item for item in concept_values}
        self._variables = {item.canonical_name: item for item in variable_values}
        if len(self._concepts) != len(concept_values):
            raise ValueError("Earth concept identifiers must be unique")
        if len(self._variables) != len(variable_values):
            raise ValueError("canonical Earth variable names must be unique")
        for concept in concept_values:
            if (
                concept.parent_id is not None
                and concept.parent_id not in self._concepts
            ):
                raise ValueError(
                    f"concept {concept.concept_id!r} references an unknown parent"
                )
            if any(name not in self._concepts for name in concept.related_concepts):
                raise ValueError(
                    f"concept {concept.concept_id!r} has an unknown relation"
                )
        for variable in variable_values:
            if variable.concept_id not in self._concepts:
                raise ValueError(
                    f"variable {variable.canonical_name!r} references an "
                    f"unknown concept {variable.concept_id!r}"
                )
            if any(name not in self._variables for name in variable.related_variables):
                raise ValueError(
                    f"variable {variable.canonical_name!r} has an unknown relation"
                )
        aliases: dict[str, set[str]] = {}
        for variable in variable_values:
            names = (variable.canonical_name, *variable.aliases)
            for name in names:
                aliases.setdefault(name.casefold(), set()).add(variable.canonical_name)
        self._aliases = {key: tuple(sorted(names)) for key, names in aliases.items()}
        concept_aliases: dict[str, set[str]] = {}
        for concept in concept_values:
            for name in (concept.concept_id, concept.label, *concept.aliases):
                concept_aliases.setdefault(name.casefold(), set()).add(
                    concept.concept_id
                )
        self._concept_aliases = {
            key: tuple(sorted(names)) for key, names in concept_aliases.items()
        }

    @property
    def concepts(self) -> tuple[EarthConcept, ...]:
        return tuple(self._concepts[key] for key in sorted(self._concepts))

    @property
    def variables(self) -> tuple[EarthVariable, ...]:
        return tuple(self._variables[key] for key in sorted(self._variables))

    def concept(self, concept_id: str) -> Optional[EarthConcept]:
        return self._concepts.get(concept_id)

    def resolve_concept(self, name: str) -> Optional[EarthConcept]:
        candidates = self._concept_aliases.get(name.casefold(), ())
        if len(candidates) != 1:
            return None
        return self._concepts[candidates[0]]

    def variables_for_concept(self, concept_id: str) -> tuple[EarthVariable, ...]:
        return tuple(
            variable for variable in self.variables if variable.concept_id == concept_id
        )

    def concept_metadata(self, concept_id: str) -> Optional[dict[str, object]]:
        concept = self.concept(concept_id)
        if concept is None:
            return None
        return {
            "concept_id": concept.concept_id,
            "label": concept.label,
            "parent_id": concept.parent_id,
            "aliases": concept.aliases,
            "canonical_variables": tuple(
                variable.canonical_name
                for variable in self.variables_for_concept(concept_id)
            ),
            "related_concepts": concept.related_concepts,
            **dict(concept.metadata),
        }

    def variable(self, canonical_name: str) -> Optional[EarthVariable]:
        return self._variables.get(canonical_name)

    def resolve_variable(self, name: str) -> Optional[EarthVariable]:
        candidates = self._aliases.get(name.casefold(), ())
        if len(candidates) != 1:
            return None
        return self._variables[candidates[0]]

    def variable_aliases(self, name: str) -> tuple[EarthVariable, ...]:
        return tuple(
            self._variables[canonical]
            for canonical in self._aliases.get(name.casefold(), ())
        )


_CONCEPTS = (
    EarthConcept(
        "atmosphere",
        "Atmosphere",
        aliases=("atmospheric",),
        related_concepts=("weather", "climate"),
    ),
    EarthConcept(
        "weather", "Weather", parent_id="atmosphere", aliases=("meteorology",)
    ),
    EarthConcept("storm", "Storm", parent_id="weather", aliases=("storm system",)),
    EarthConcept("cyclone", "Cyclone", parent_id="storm", aliases=("hurricane", "typhoon")),
    EarthConcept("heatwave", "Heatwave", parent_id="weather", aliases=("heat wave",)),
    EarthConcept(
        "climate", "Climate", parent_id="atmosphere", aliases=("climatology",)
    ),
    EarthConcept(
        "vegetation",
        "Vegetation",
        aliases=("plant cover",),
        related_concepts=("land_cover", "agriculture", "biodiversity"),
    ),
    EarthConcept(
        "hydrology",
        "Hydrology",
        aliases=("water",),
        related_concepts=("climate",),
    ),
    EarthConcept("flood", "Flood", parent_id="hydrology", aliases=("flooding", "inundation")),
    EarthConcept("drought", "Drought", parent_id="climate", aliases=("dry spell",)),
    EarthConcept(
        "terrain",
        "Terrain",
        aliases=("topography",),
        related_concepts=("geology",),
    ),
    EarthConcept(
        "land_cover",
        "Land Cover",
        aliases=("land cover", "landcover"),
        related_concepts=("agriculture", "biodiversity"),
    ),
    EarthConcept(
        "human_geography",
        "Human Geography",
        aliases=("population", "settlement"),
        related_concepts=("infrastructure", "transportation", "energy"),
    ),
    EarthConcept(
        "infrastructure",
        "Infrastructure",
        aliases=("built environment",),
        related_concepts=("human_geography",),
    ),
    EarthConcept("disasters", "Disasters", aliases=("hazards",)),
    EarthConcept(
        "fire", "Fire", parent_id="disasters", aliases=("wildfire", "active fire")
    ),
    EarthConcept("oceans", "Oceans", aliases=("ocean", "marine")),
    EarthConcept("marine_heatwave", "Marine Heatwave", parent_id="oceans", aliases=("marine heat wave",)),
    EarthConcept("cryosphere", "Cryosphere", aliases=("ice", "snow")),
    EarthConcept(
        "agriculture",
        "Agriculture",
        aliases=("farming", "crops"),
        related_concepts=("vegetation", "land_cover"),
    ),
    EarthConcept(
        "geology",
        "Geology",
        aliases=("geoscience",),
        related_concepts=("terrain",),
    ),
    EarthConcept("earthquake", "Earthquake", parent_id="geology", aliases=("seismic event",)),
    EarthConcept("landslide", "Landslide", parent_id="geology", aliases=("mudslide", "slope failure")),
    EarthConcept("volcanic_activity", "Volcanic Activity", parent_id="geology", aliases=("volcanic eruption", "eruption")),
    EarthConcept(
        "biodiversity",
        "Biodiversity",
        aliases=("species", "ecosystems", "ecology"),
        related_concepts=("vegetation", "land_cover"),
    ),
    EarthConcept(
        "transportation",
        "Transportation",
        aliases=("transport", "mobility"),
        related_concepts=("infrastructure", "human_geography"),
    ),
    EarthConcept(
        "energy",
        "Energy",
        aliases=("power", "electricity"),
        related_concepts=("infrastructure", "human_geography"),
    ),
)

_VARIABLES = (
    EarthVariable(
        "air_temperature",
        "weather",
        "Air temperature",
        aliases=(
            "air_temperature",
            "air_temperature_2m",
            "temperature_2m",
            "t2m",
            "tmp",
            "temperature",
        ),
        standard_name="air_temperature",
        ontology_uri="https://vocab.nerc.ac.uk/standard_name/air_temperature/",
        unit_dimension="temperature",
        canonical_units=("K",),
    ),
    EarthVariable(
        "land_surface_temperature",
        "climate",
        "Land surface temperature",
        aliases=(
            "land_surface_temperature",
            "surface_temperature",
            "lst",
            "temperature",
        ),
        standard_name="surface_temperature",
        ontology_uri="https://vocab.nerc.ac.uk/standard_name/surface_temperature/",
        unit_dimension="temperature",
        canonical_units=("K",),
    ),
    EarthVariable(
        "precipitation_amount",
        "weather",
        "Precipitation amount",
        aliases=("precipitation_amount", "precipitation", "precip", "pr"),
        standard_name="precipitation_amount",
        ontology_uri="https://vocab.nerc.ac.uk/standard_name/precipitation_amount/",
        unit_dimension="length",
        canonical_units=("kg m-2", "mm"),
    ),
    EarthVariable(
        "relative_humidity",
        "weather",
        "Relative humidity",
        aliases=("relative_humidity", "relative_humidity_2m", "rh"),
        standard_name="relative_humidity",
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
    ),
    EarthVariable(
        "surface_air_pressure",
        "atmosphere",
        "Surface air pressure",
        aliases=("surface_air_pressure", "mean_sea_level_pressure", "mslp", "sp"),
        standard_name="surface_air_pressure",
        unit_dimension="pressure",
        canonical_units=("Pa", "hPa"),
    ),
    EarthVariable(
        "wind_speed",
        "weather",
        "Wind speed",
        aliases=("wind_speed", "windspeed", "wind_speed_10m", "ws"),
        unit_dimension="speed",
        canonical_units=("m s-1", "km h-1"),
        related_variables=("wind_direction",),
    ),
    EarthVariable(
        "wind_direction",
        "weather",
        "Wind direction",
        aliases=("wind_direction", "wind_direction_10m", "wd"),
        unit_dimension="angle",
        canonical_units=("degree", "radian"),
        related_variables=("wind_speed",),
    ),
    EarthVariable(
        "cloud_fraction",
        "atmosphere",
        "Cloud fraction",
        aliases=("cloud_fraction", "cloud_cover", "cloudcover"),
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
    ),
    EarthVariable(
        "aerosol_optical_depth",
        "atmosphere",
        "Aerosol optical depth",
        aliases=("aerosol_optical_depth", "aod"),
        unit_dimension="dimensionless",
        canonical_units=("1",),
    ),
    EarthVariable(
        "ozone_column_amount",
        "atmosphere",
        "Atmospheric ozone column amount",
        aliases=("ozone_column_amount", "total_column_ozone", "tco"),
        unit_dimension="amount_per_area",
        canonical_units=("mol m-2", "DU"),
    ),
    EarthVariable(
        "ndvi",
        "vegetation",
        "Normalized Difference Vegetation Index",
        aliases=("ndvi", "normalized_difference_vegetation_index"),
        unit_dimension="dimensionless",
        canonical_units=("1",),
        related_variables=("evi",),
    ),
    EarthVariable(
        "evi",
        "vegetation",
        "Enhanced Vegetation Index",
        aliases=("evi", "enhanced_vegetation_index"),
        unit_dimension="dimensionless",
        canonical_units=("1",),
        related_variables=("ndvi",),
    ),
    EarthVariable(
        "leaf_area_index",
        "vegetation",
        "Leaf area index",
        aliases=("leaf_area_index", "lai"),
        unit_dimension="area_per_area",
        canonical_units=("m2 m-2",),
    ),
    EarthVariable(
        "elevation",
        "terrain",
        "Elevation",
        aliases=("elevation", "dem", "digital_elevation"),
        standard_name="surface_altitude",
        ontology_uri="https://vocab.nerc.ac.uk/standard_name/altitude/",
        unit_dimension="length",
        canonical_units=("m",),
        related_variables=("slope", "aspect"),
    ),
    EarthVariable(
        "slope",
        "terrain",
        "Terrain slope",
        aliases=("slope", "slope_angle"),
        unit_dimension="angle",
        canonical_units=("degree", "radian"),
        related_variables=("elevation",),
    ),
    EarthVariable(
        "aspect",
        "terrain",
        "Terrain aspect",
        aliases=("aspect", "slope_aspect"),
        unit_dimension="angle",
        canonical_units=("degree", "radian"),
        related_variables=("elevation",),
    ),
    EarthVariable(
        "soil_moisture",
        "hydrology",
        "Soil moisture",
        aliases=("soil_moisture", "sm", "sm_surface"),
        standard_name="volume_fraction_of_water_in_soil",
        unit_dimension="dimensionless",
        canonical_units=("m3 m-3",),
    ),
    EarthVariable(
        "river_discharge",
        "hydrology",
        "River discharge",
        aliases=("river_discharge", "streamflow", "runoff"),
        unit_dimension="volume_per_time",
        canonical_units=("m3 s-1",),
    ),
    EarthVariable(
        "fapar",
        "vegetation",
        "Fraction of absorbed photosynthetically active radiation",
        aliases=("fapar", "fraction_absorbed_par"),
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
        related_variables=("leaf_area_index", "ndvi"),
    ),
    EarthVariable(
        "vegetation_fraction",
        "vegetation",
        "Vegetation fraction",
        aliases=("vegetation_fraction", "fractional_vegetation_cover", "fvc"),
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
    ),
    EarthVariable(
        "aboveground_biomass",
        "vegetation",
        "Above-ground biomass",
        aliases=("aboveground_biomass", "biomass", "agb"),
        unit_dimension="mass_per_area",
        canonical_units=("kg m-2", "Mg ha-1"),
    ),
    EarthVariable(
        "land_cover_class",
        "land_cover",
        "Land-cover class",
        aliases=("land_cover", "landcover", "land_cover_class", "lc_class"),
        unit_dimension="categorical",
    ),
    EarthVariable(
        "impervious_surface_fraction",
        "land_cover",
        "Impervious-surface fraction",
        aliases=("impervious_surface", "imperviousness", "impervious_fraction"),
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
    ),
    EarthVariable(
        "water_occurrence",
        "hydrology",
        "Surface-water occurrence",
        aliases=("water_occurrence", "occurrence", "surface_water_occurrence"),
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
    ),
    EarthVariable(
        "water_extent",
        "hydrology",
        "Surface-water extent",
        aliases=("water_extent", "surface_water_extent", "water_body_extent"),
        unit_dimension="categorical",
        related_variables=("water_occurrence", "flood_extent"),
    ),
    EarthVariable(
        "river_network",
        "hydrology",
        "River network",
        aliases=("river_network", "rivers", "stream_network"),
        unit_dimension="geometry",
    ),
    EarthVariable(
        "watershed_boundary",
        "hydrology",
        "Watershed boundary",
        aliases=("watershed_boundary", "watershed", "basin_boundary"),
        unit_dimension="geometry",
    ),
    EarthVariable(
        "lake_area",
        "hydrology",
        "Lake area",
        aliases=("lake_area", "reservoir_area", "water_body_area"),
        unit_dimension="area",
        canonical_units=("m2", "km2"),
    ),
    EarthVariable(
        "reservoir_storage",
        "hydrology",
        "Reservoir storage",
        aliases=("reservoir_storage", "reservoir_volume", "water_storage"),
        unit_dimension="volume",
        canonical_units=("m3", "km3"),
    ),
    EarthVariable(
        "flood_extent",
        "disasters",
        "Flood extent",
        aliases=("flood_extent", "inundation_extent", "flooded_area"),
        unit_dimension="categorical",
        related_variables=("water_extent",),
    ),
    EarthVariable(
        "population_density",
        "human_geography",
        "Population density",
        aliases=("population_density", "pop_density", "people_per_km2"),
        unit_dimension="population_per_area",
        canonical_units=("person km-2",),
    ),
    EarthVariable(
        "population_count",
        "human_geography",
        "Population count",
        aliases=("population", "population_count", "pop_count"),
        unit_dimension="population",
        canonical_units=("person",),
    ),
    EarthVariable(
        "built_up_area",
        "human_geography",
        "Built-up area",
        aliases=("built_up_area", "builtup_area", "urban_extent"),
        unit_dimension="area",
        canonical_units=("m2", "km2"),
    ),
    EarthVariable(
        "settlement_class",
        "human_geography",
        "Settlement class",
        aliases=("settlement_type", "urban_rural_class"),
        unit_dimension="categorical",
    ),
    EarthVariable(
        "building_footprint",
        "infrastructure",
        "Building footprint",
        aliases=("building_footprint", "building_footprints", "buildings"),
        unit_dimension="geometry",
    ),
    EarthVariable(
        "road_network",
        "transportation",
        "Road network",
        aliases=("road_network", "roads", "highway"),
        unit_dimension="geometry",
    ),
    EarthVariable(
        "rail_network",
        "transportation",
        "Rail network",
        aliases=("rail_network", "railways", "railway"),
        unit_dimension="geometry",
    ),
    EarthVariable(
        "active_fire",
        "disasters",
        "Active fire detection",
        aliases=("active_fire", "fire_detection", "wildfire"),
        unit_dimension="categorical",
        related_variables=("fire_radiative_power",),
    ),
    EarthVariable(
        "fire_radiative_power",
        "fire",
        "Fire radiative power",
        aliases=("fire_radiative_power", "frp"),
        unit_dimension="power",
        canonical_units=("MW",),
        related_variables=("active_fire",),
    ),
    EarthVariable(
        "drought_index",
        "disasters",
        "Drought index",
        aliases=("drought_index", "spei", "spi", "drought_severity"),
        unit_dimension="index",
    ),
    EarthVariable(
        "cyclone_track",
        "disasters",
        "Cyclone track",
        aliases=("cyclone_track", "tropical_cyclone_track", "hurricane_track"),
        unit_dimension="geometry",
    ),
    EarthVariable(
        "volcanic_activity",
        "disasters",
        "Volcanic activity observation",
        aliases=("volcanic_activity", "volcano_event", "volcanic_event"),
        unit_dimension="categorical",
    ),
    EarthVariable(
        "severe_weather_event",
        "disasters",
        "Severe weather event observation",
        aliases=("severe_weather_event", "storm_event", "weather_hazard"),
        unit_dimension="categorical",
    ),
    EarthVariable(
        "earthquake_magnitude",
        "disasters",
        "Earthquake magnitude",
        aliases=("earthquake_magnitude", "magnitude", "mag"),
        unit_dimension="magnitude",
    ),
    EarthVariable(
        "snow_water_equivalent",
        "cryosphere",
        "Snow water equivalent",
        aliases=("snow_water_equivalent", "swe"),
        unit_dimension="length",
        canonical_units=("m", "mm"),
    ),
    EarthVariable(
        "glacier_extent",
        "cryosphere",
        "Glacier extent",
        aliases=("glacier_extent", "glacier_area"),
        unit_dimension="area",
        canonical_units=("m2", "km2"),
    ),
    EarthVariable(
        "population_change",
        "human_geography",
        "Population change",
        aliases=("population_change", "population_growth"),
        unit_dimension="population",
        canonical_units=("person", "person year-1"),
    ),
    EarthVariable(
        "sea_ice_concentration",
        "cryosphere",
        "Sea-ice concentration",
        aliases=("sea_ice_concentration", "ice_concentration"),
        unit_dimension="dimensionless",
        canonical_units=("1", "%"),
    ),
    EarthVariable(
        "coastal_water_level",
        "oceans",
        "Coastal water level relative to a declared datum",
        aliases=("coastal_water_level", "water_level", "tide_gauge_height"),
        unit_dimension="length",
        canonical_units=("m", "ft"),
    ),
    EarthVariable(
        "sea_surface_temperature",
        "oceans",
        "Sea-surface temperature",
        aliases=("sea_surface_temperature", "sst"),
        unit_dimension="temperature",
        canonical_units=("K",),
    ),
    EarthVariable(
        "chlorophyll_concentration",
        "oceans",
        "Chlorophyll concentration",
        aliases=("chlorophyll", "chlorophyll_concentration", "chl_a"),
        unit_dimension="mass_per_volume",
        canonical_units=("mg m-3",),
    ),
    EarthVariable(
        "soil_organic_carbon",
        "agriculture",
        "Soil organic carbon",
        aliases=("soil_organic_carbon", "soc"),
        unit_dimension="mass_per_area",
        canonical_units=("kg m-2",),
    ),
    EarthVariable(
        "crop_type",
        "agriculture",
        "Crop type",
        aliases=("crop_type", "crop_class", "crop"),
        unit_dimension="categorical",
    ),
    EarthVariable(
        "seismic_event_magnitude",
        "geology",
        "Seismic event magnitude",
        aliases=("seismic_event_magnitude", "earthquake_magnitude", "magnitude"),
        unit_dimension="magnitude",
    ),
    EarthVariable(
        "species_observation",
        "biodiversity",
        "Species observation",
        aliases=("species_observation", "species_occurrence", "taxon_observation"),
        unit_dimension="count",
    ),
    EarthVariable(
        "power_generation",
        "energy",
        "Power generation",
        aliases=("power_generation", "electricity_generation"),
        unit_dimension="power",
        canonical_units=("W", "MW", "GW"),
    ),
    EarthVariable(
        "brightness_temperature_ti4",
        "fire",
        "Brightness temperature for provider channel ti4",
        aliases=("bright_ti4",),
        unit_dimension="temperature",
        canonical_units=("K",),
    ),
    EarthVariable(
        "brightness_temperature_ti5",
        "fire",
        "Brightness temperature for provider channel ti5",
        aliases=("bright_ti5",),
        unit_dimension="temperature",
        canonical_units=("K",),
    ),
)

EARTH_VARIABLE_ONTOLOGY = EarthVariableOntology(_CONCEPTS, _VARIABLES)


def canonical_variable_name(
    name: str,
    ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
) -> str:
    """Return a canonical name only when an ontology alias is unambiguous."""
    variable = ontology.resolve_variable(name)
    return variable.canonical_name if variable is not None else name
