"""Earth sensing modalities and variable-to-modality resolution.

Modalities describe what SatQuery observes about Earth. Dataset adapters are
implementations of these capabilities, not the capabilities themselves.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Optional

from .ontology import (
    EARTH_VARIABLE_ONTOLOGY,
    EarthVariableOntology,
)


@dataclass(frozen=True)
class SensingModality:
    modality_id: str
    label: str
    description: str
    ontology_concepts: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


class SensingModalityRegistry:
    """Extensible, deterministic registry of Earth perception domains."""

    def __init__(
        self,
        modalities: Iterable[SensingModality] = (),
        *,
        ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
    ) -> None:
        self._modalities: dict[str, SensingModality] = {}
        self._aliases: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self.ontology = ontology
        for modality in modalities:
            self.register(modality)

    def register(self, modality: SensingModality, *, replace: bool = False) -> None:
        modality_id = modality.modality_id.strip().casefold()
        if not modality_id:
            raise ValueError("modality_id must be non-empty")
        aliases = tuple(dict.fromkeys(alias.strip() for alias in modality.aliases))
        if any(not alias for alias in aliases):
            raise ValueError("modality aliases must not contain empty values")
        if not modality.label.strip() or not modality.description.strip():
            raise ValueError("modality label and description must be non-empty")
        if any(
            self.ontology.concept(concept_id) is None
            for concept_id in modality.ontology_concepts
        ):
            raise ValueError("modality references an unknown Earth ontology concept")
        normalized = SensingModality(
            modality_id=modality_id,
            label=modality.label,
            description=modality.description,
            ontology_concepts=tuple(dict.fromkeys(modality.ontology_concepts)),
            aliases=aliases,
        )
        with self._lock:
            if modality_id in self._modalities and not replace:
                raise ValueError(f"modality {modality_id!r} is already registered")
            if replace and modality_id in self._modalities:
                old = self._modalities.pop(modality_id)
                for alias in (old.modality_id, *old.aliases):
                    self._aliases.get(alias.casefold(), set()).discard(modality_id)
            self._modalities[modality_id] = normalized
            for alias in (normalized.modality_id, *normalized.aliases):
                self._aliases.setdefault(alias.casefold(), set()).add(modality_id)

    def get(self, modality_id: str) -> Optional[SensingModality]:
        canonical = self.resolve_id(modality_id)
        if canonical is None:
            return None
        with self._lock:
            return self._modalities.get(canonical)

    def resolve_id(self, name: str) -> Optional[str]:
        with self._lock:
            matches = self._aliases.get(name.strip().casefold(), set())
            return next(iter(matches)) if len(matches) == 1 else None

    def canonicalize(self, names: Iterable[str]) -> tuple[str, ...]:
        """Canonicalize known aliases; preserve unknown names for honest reporting."""
        result = {
            self.resolve_id(name) or name.strip().casefold()
            for name in names
            if name.strip()
        }
        return tuple(sorted(result))

    def for_variable(self, name: str) -> tuple[str, ...]:
        variable = self.ontology.resolve_variable(name)
        if variable is None:
            return ()
        return tuple(
            modality_id
            for modality_id, modality in (
                (item.modality_id, item) for item in self.modalities()
            )
            if variable.concept_id in modality.ontology_concepts
        )

    def for_variables(self, names: Iterable[str]) -> tuple[str, ...]:
        return tuple(
            sorted({item for name in names for item in self.for_variable(name)})
        )

    def modalities(self) -> tuple[SensingModality, ...]:
        with self._lock:
            return tuple(self._modalities[key] for key in sorted(self._modalities))


EARTH_SENSING_MODALITIES = SensingModalityRegistry(
    (
        SensingModality(
            "visual",
            "Visual",
            "Optical and other directly imageable Earth observations.",
            (),
            ("imagery", "optical"),
        ),
        SensingModality(
            "atmospheric",
            "Atmospheric",
            "Atmospheric state, weather, and climate.",
            ("atmosphere", "weather", "climate", "storm", "cyclone", "heatwave"),
            ("atmosphere", "weather", "climate"),
        ),
        SensingModality(
            "hydrological",
            "Hydrological",
            "Surface water, groundwater, and hydrologic systems.",
            ("hydrology", "flood"),
            ("hydrology", "water"),
        ),
        SensingModality(
            "ecological",
            "Ecological",
            "Living systems, vegetation, biodiversity, and land cover.",
            ("vegetation", "land_cover", "biodiversity", "agriculture"),
            ("ecology", "ecosystems", "biodiversity"),
        ),
        SensingModality(
            "geological",
            "Geological",
            "Terrain, geology, and solid-Earth observations.",
            ("terrain", "geology", "earthquake", "landslide", "volcanic_activity"),
            ("geology", "geoscience", "terrain"),
        ),
        SensingModality(
            "human",
            "Human",
            "Population, settlements, infrastructure, mobility, and energy.",
            ("human_geography", "infrastructure", "transportation", "energy"),
            ("human_geography", "population", "infrastructure"),
        ),
        SensingModality(
            "oceanic",
            "Oceanic",
            "Ocean state and marine observations.",
            ("oceans", "marine_heatwave"),
            ("ocean", "marine", "ocean"),
        ),
        SensingModality(
            "disaster",
            "Disaster",
            "Hazards, events, impacts, and response observations.",
            ("disasters", "fire", "flood", "drought", "storm", "cyclone", "earthquake", "landslide", "volcanic_activity"),
            ("disasters", "hazards", "hazard", "wildfire"),
        ),
        SensingModality(
            "cryospheric",
            "Cryospheric",
            "Snow, ice, glaciers, and frozen-ground observations.",
            ("cryosphere",),
            ("cryosphere", "ice", "snow"),
        ),
    )
)


def infer_modalities(
    names: Iterable[str],
    registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
) -> tuple[str, ...]:
    """Infer declared Earth domains only from unambiguous ontology variables."""
    return registry.for_variables(names)
