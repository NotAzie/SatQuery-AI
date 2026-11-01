"""Provider-neutral Earth dataset metadata registry."""

from __future__ import annotations

import threading
from typing import Iterable, Optional, Protocol, Tuple, runtime_checkable

from ..errors import ExtensionError
from .contracts import DatasetMetadata, DatasetSearchPlan, EarthQuery
from .modalities import (
    EARTH_SENSING_MODALITIES,
    SensingModalityRegistry,
    infer_modalities,
)
from .ontology import EARTH_VARIABLE_ONTOLOGY, EarthVariableOntology
from .spatial import query_intersects_coverage


@runtime_checkable
class DatasetRegistry(Protocol):
    """Stable registry interface for metadata known before data acquisition."""

    def get(self, connector_id: str, dataset_id: str) -> DatasetMetadata: ...

    def list(self) -> Tuple[DatasetMetadata, ...]: ...

    def search(self, query: EarthQuery) -> Tuple[DatasetMetadata, ...]: ...

    def plan(self, query: EarthQuery) -> DatasetSearchPlan: ...

    def search_capabilities(
        self, capabilities: Iterable[str]
    ) -> Tuple[DatasetMetadata, ...]: ...

    def semantic_search(self, text: str) -> Tuple[DatasetMetadata, ...]: ...

    def resolve_alias(self, alias: str) -> Tuple[DatasetMetadata, ...]: ...

    def register(self, dataset: DatasetMetadata, *, replace: bool = False) -> None: ...


class InMemoryDatasetRegistry:
    """Thread-safe local dataset registry with deterministic query results."""

    def __init__(
        self,
        datasets: Iterable[DatasetMetadata] = (),
        *,
        ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
        modality_registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
    ) -> None:
        self._lock = threading.RLock()
        self._datasets: dict[tuple[str, str, Optional[str]], DatasetMetadata] = {}
        self.ontology = ontology
        self.modality_registry = modality_registry
        for dataset in datasets:
            self.register(dataset)

    def register(self, dataset: DatasetMetadata, *, replace: bool = False) -> None:
        key = (dataset.connector_id, dataset.dataset_id, dataset.version)
        with self._lock:
            if key in self._datasets and not replace:
                raise ExtensionError(
                    f"Dataset {dataset.dataset_id!r} is already registered for "
                    f"connector {dataset.connector_id!r}.",
                    context={
                        "connector_id": key[0],
                        "dataset_id": key[1],
                        "version": key[2],
                    },
                )
            self._datasets[key] = dataset

    def unregister(
        self, connector_id: str, dataset_id: str, version: Optional[str] = None
    ) -> DatasetMetadata:
        key = (connector_id, dataset_id, version)
        with self._lock:
            try:
                return self._datasets.pop(key)
            except KeyError as exc:
                raise ExtensionError(
                    f"Dataset {dataset_id!r} is not registered for connector "
                    f"{connector_id!r}.",
                    context={"connector_id": connector_id, "dataset_id": dataset_id},
                ) from exc

    def get(
        self, connector_id: str, dataset_id: str, version: Optional[str] = None
    ) -> DatasetMetadata:
        with self._lock:
            candidates = [
                dataset
                for (registered_connector, registered_dataset, _), dataset
                in self._datasets.items()
                if registered_connector == connector_id
                and registered_dataset == dataset_id
                and (version is None or dataset.version == version)
            ]
            if candidates:
                return sorted(
                    candidates,
                    key=lambda item: item.version or "",
                    reverse=True,
                )[0]
            else:
                raise ExtensionError(
                    f"Dataset {dataset_id!r} is not registered for connector "
                    f"{connector_id!r}.",
                    context={
                        "connector_id": connector_id,
                        "dataset_id": dataset_id,
                        "version": version,
                    },
                )

    def list(self) -> Tuple[DatasetMetadata, ...]:
        with self._lock:
            return tuple(
                self._datasets[key]
                for key in sorted(
                    self._datasets,
                    key=lambda item: (item[0], item[1], item[2] or ""),
                )
            )

    def search(self, query: EarthQuery) -> Tuple[DatasetMetadata, ...]:
        return self.plan(query).datasets

    def plan(self, query: EarthQuery) -> DatasetSearchPlan:
        """Report dataset implementations and uncovered perception domains."""
        requested_variables = {
            self._canonical_variable(value) for value in query.requested_variables
        }
        requested_modalities = set(
            self.modality_registry.canonicalize(query.requested_modalities)
        )
        requested_modalities.update(
            infer_modalities(query.requested_variables, self.modality_registry)
        )
        required_capabilities = {
            value.casefold() for value in query.required_capabilities
        }
        matches: list[DatasetMetadata] = []
        for dataset in self._latest_datasets():
            if dataset.deprecated:
                continue
            identities = {
                dataset.dataset_id,
                f"{dataset.connector_id}:{dataset.dataset_id}",
            }
            if dataset.version:
                identities.add(
                    f"{dataset.connector_id}:{dataset.dataset_id}@{dataset.version}"
                )
            if (
                query.requested_dataset_ids
                and not any(
                    requested_id
                    in identities
                    for requested_id in query.requested_dataset_ids
                )
            ):
                continue
            variables = {
                self._canonical_variable(value) for value in dataset.variables
            }
            capabilities = {value.casefold() for value in dataset.capabilities}
            modalities = set(
                self.modality_registry.canonicalize(dataset.modalities)
            )
            modalities.update(
                infer_modalities(dataset.variables, self.modality_registry)
            )
            if requested_modalities and not requested_modalities.intersection(
                modalities
            ):
                continue
            if requested_variables:
                known_variables = {
                    variable
                    for variable in requested_variables
                    if self._canonical_variable(variable) != variable
                    or variable in variables
                }
                unknown_variables = requested_variables - known_variables
                if not (known_variables & variables) and not (
                    unknown_variables and unknown_variables.issubset(variables)
                ):
                    continue
            if required_capabilities and not required_capabilities.issubset(
                capabilities
            ):
                continue
            if not _temporal_match(dataset, query):
                continue
            if query_has_aoi(query):
                if dataset.spatial_coverage is None:
                    continue
                if not query_intersects_coverage(
                    query, dataset.spatial_coverage, coverage_crs=dataset.crs or query.crs
                ):
                    continue
            matches.append(dataset)
        available_variables = {
            self._canonical_variable(variable)
            for dataset in matches
            for variable in dataset.variables
        }
        available_modalities = {
            modality
            for dataset in matches
            for modality in (
                *self.modality_registry.canonicalize(dataset.modalities),
                *infer_modalities(dataset.variables, self.modality_registry),
            )
        }
        return DatasetSearchPlan(
            datasets=tuple(matches),
            requested_modalities=tuple(sorted(requested_modalities)),
            available_modalities=tuple(
                sorted(requested_modalities & available_modalities)
            ),
            unavailable_modalities=tuple(
                sorted(requested_modalities - available_modalities)
            ),
            requested_variables=tuple(sorted(requested_variables)),
            available_variables=tuple(
                sorted(requested_variables & available_variables)
            ),
            unavailable_variables=tuple(
                sorted(requested_variables - available_variables)
            ),
        )

    def _canonical_variable(self, value: str) -> str:
        concept = self.ontology.resolve_variable(value)
        return concept.canonical_name.casefold() if concept is not None else value.casefold()

    def search_capabilities(
        self, capabilities: Iterable[str]
    ) -> Tuple[DatasetMetadata, ...]:
        requested = {item.casefold() for item in capabilities}
        return tuple(
            dataset
            for dataset in self._latest_datasets()
            if not dataset.deprecated
            and requested.issubset(
                {item.casefold() for item in dataset.capabilities}
            )
        )

    def semantic_search(self, text: str) -> Tuple[DatasetMetadata, ...]:
        terms = {term.casefold() for term in text.split() if term.strip()}
        if not terms:
            return ()
        ranked: list[tuple[int, DatasetMetadata]] = []
        for dataset in self._latest_datasets():
            if dataset.deprecated:
                continue
            searchable = {
                *dataset.aliases,
                *dataset.keywords,
                *dataset.tags,
                *dataset.categories,
                *dataset.variables,
                *dataset.capabilities,
                dataset.dataset_id,
                dataset.provider,
                str(dataset.metadata.get("title", "")),
                str(dataset.metadata.get("description", "")),
            }
            normalized = " ".join(searchable).casefold()
            score = sum(term in normalized for term in terms)
            if score:
                ranked.append((score, dataset))
        ranked.sort(
            key=lambda item: (-item[0], item[1].connector_id, item[1].dataset_id)
        )
        return tuple(dataset for _, dataset in ranked)

    def resolve_alias(self, alias: str) -> Tuple[DatasetMetadata, ...]:
        normalized = alias.casefold()
        return tuple(
            dataset
            for dataset in self._latest_datasets()
            if normalized == dataset.dataset_id.casefold()
            or normalized in {item.casefold() for item in dataset.aliases}
        )

    def _latest_datasets(self) -> Tuple[DatasetMetadata, ...]:
        latest: dict[tuple[str, str], DatasetMetadata] = {}
        for dataset in self.list():
            key = (dataset.connector_id, dataset.dataset_id)
            current = latest.get(key)
            if current is None or (dataset.version or "") > (current.version or ""):
                latest[key] = dataset
        return tuple(latest[key] for key in sorted(latest))


def query_has_aoi(query: EarthQuery) -> bool:
    return any(value is not None for value in (query.point, query.bbox, query.geometry))


def _temporal_match(dataset: DatasetMetadata, query: EarthQuery) -> bool:
    coverage = dataset.temporal_coverage
    if coverage is None:
        return query.temporal_start is None and query.temporal_end is None
    if query.temporal_start is not None and coverage.end is not None:
        if query.temporal_start > coverage.end:
            return False
    if query.temporal_end is not None and coverage.start is not None:
        if query.temporal_end < coverage.start:
            return False
    return True
