"""Canonical Earth queries, capability selection, and observation acquisition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timezone
from typing import Iterable, Optional, Protocol, Tuple, runtime_checkable

from ..errors import CacheError, ConnectorError, ValidationError
from .cache import CacheBackend, CacheStats, MemoryCache
from .capabilities import (
    EarthCapabilityEntry,
    EarthCapabilityMatrix,
    build_earth_capability_matrix,
)
from .connectors import ConnectorManager, PerceptionConnector
from .contracts import (
    DatasetMetadata,
    EarthQuery,
    Observation,
    ObservationSearchResult,
    PerceptionFailure,
    PerceptionPlan,
    PerceptionProcessingFailure,
    PerceptionResult,
    TemporalExtent,
)
from .fusion import ObservationFusion
from .modalities import (
    EARTH_SENSING_MODALITIES,
    SensingModalityRegistry,
    infer_modalities,
)
from .normalization import SemanticNormalizer
from .observation_graph import ObservationGraphBuilder
from .quality import assess_observation
from .raster import RasterAssetSamplingError, RasterAssetSamplingService
from .raster_analysis import RasterAnalysisService
from .spatial import query_intersects_coverage
from .spatiotemporal import (
    ConsecutiveTemporalDifferenceEngine,
    ExactSupportObservationStackBuilder,
)

_PLATFORM_RASTER_CAPABILITIES = frozenset(
    {
        "raster_point_sampling",
        "raster_zonal_analysis",
        "raster_geodesic_area_weighting",
        "raster_categorical_polygonization",
    }
)
_PLATFORM_RASTER_QUERY_FIELDS = frozenset(
    {
        "asset_sampling",
        "raster_analysis",
        "raster_pixel_selection",
        "raster_weighting",
        "raster_semantics",
        "raster_component_extraction",
    }
)


@runtime_checkable
class ObservationCache(Protocol):
    """Replaceable cache contract keyed by canonical EarthQuery fingerprints."""

    async def get(
        self, fingerprint: str
    ) -> Tuple[bool, Optional[PerceptionResult]]: ...

    async def set(
        self,
        fingerprint: str,
        result: PerceptionResult,
        *,
        ttl_seconds: float,
    ) -> None: ...


@runtime_checkable
class ManagedObservationCache(ObservationCache, Protocol):
    """Optional cache-administration contract implemented by the local cache."""

    async def invalidate_connector(self, connector_id: str) -> int: ...

    async def clear(self) -> None: ...

    async def stats(self) -> CacheStats: ...


@runtime_checkable
class ConnectorSelector(Protocol):
    """Replaceable strategy for selecting perception sources."""

    def select(
        self,
        query: EarthQuery,
        connectors: Iterable[PerceptionConnector],
    ) -> tuple[PerceptionConnector, ...]: ...


class CapabilityConnectorSelector:
    """Plan modality coverage across interchangeable perception implementations."""

    _HEALTH_ORDER = {"healthy": 0, "degraded": 1, "unknown": 2}

    def __init__(
        self,
        modality_registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
    ) -> None:
        self.modality_registry = modality_registry

    def select(
        self,
        query: EarthQuery,
        connectors: Iterable[PerceptionConnector],
        datasets: Iterable[DatasetMetadata] = (),
    ) -> tuple[PerceptionConnector, ...]:
        return self.plan(query, connectors, datasets)[0]

    def plan(
        self,
        query: EarthQuery,
        connectors: Iterable[PerceptionConnector],
        datasets: Iterable[DatasetMetadata] = (),
        *,
        capability_matrix: Optional[EarthCapabilityMatrix] = None,
    ) -> tuple[tuple[PerceptionConnector, ...], PerceptionPlan]:
        connectors = tuple(connectors)
        if capability_matrix is None:
            capability_matrix = build_earth_capability_matrix(
                (connector.metadata for connector in connectors),
                datasets,
                modality_registry=self.modality_registry,
            )
        datasets = capability_matrix.datasets
        datasets = _latest_dataset_versions(datasets, query)
        capabilities_by_connector: dict[str, EarthCapabilityEntry] = {}
        for entry in capability_matrix.entries:
            capabilities_by_connector.setdefault(entry.connector_id, entry)
        required = {capability.casefold() for capability in query.required_capabilities}
        if query.asset_sampling == "point":
            required.add("raster_point_sampling")
        if query.raster_analysis == "zonal_descriptive":
            required.add("raster_zonal_analysis")
        if query.raster_component_extraction:
            required.add("raster_categorical_polygonization")
        # Raster execution is supplied by the platform processing runtime. The
        # selected implementation must expose compatible dataset assets, but
        # the acquisition connector itself need not implement raster analysis.
        required_from_connector = required - _PLATFORM_RASTER_CAPABILITIES
        variables = {
            _canonical_variable(variable, self.modality_registry)
            for variable in query.requested_variables
        }
        requested_modalities = set(
            self.modality_registry.canonicalize(query.requested_modalities)
        )
        requested_modalities.update(
            infer_modalities(query.requested_variables, self.modality_registry)
        )
        datasets_by_implementation: dict[str, list[DatasetMetadata]] = {}
        for dataset in datasets:
            if not dataset.deprecated:
                datasets_by_implementation.setdefault(dataset.connector_id, []).append(
                    dataset
                )
        implementation_variables: dict[str, set[str]] = {}
        implementation_modalities: dict[str, set[str]] = {}
        candidates: list[PerceptionConnector] = []
        for connector in connectors:
            metadata = connector.metadata
            capability = capabilities_by_connector.get(metadata.connector_id)
            if capability is None:
                continue
            if (
                not capability.connector_available
                or capability.connector_health == "unhealthy"
            ):
                continue
            required_capabilities = {
                value.casefold() for value in capability.implementation_capabilities
            }
            if not required_from_connector.issubset(required_capabilities):
                continue
            registered_datasets = datasets_by_implementation.get(
                metadata.connector_id, []
            )
            declared_references = capability.declared_dataset_references
            if declared_references:
                configured_dataset_ids = {
                    reference.dataset_id for reference in declared_references
                }
                registered_datasets = [
                    dataset
                    for dataset in registered_datasets
                    if dataset.dataset_id in configured_dataset_ids
                ]
            if query.requested_dataset_ids and not registered_datasets:
                declared_dataset_ids = {
                    identifier
                    for reference in declared_references
                    for identifier in (
                        reference.dataset_id,
                        f"{reference.connector_id}:{reference.dataset_id}",
                        f"{reference.connector_id}:{reference.dataset_id}@{reference.version}"
                        if reference.version
                        else f"{reference.connector_id}:{reference.dataset_id}",
                    )
                }
                if not declared_dataset_ids.intersection(query.requested_dataset_ids):
                    continue
            if (
                query.asset_sampling == "point"
                or query.raster_analysis is not None
                or bool(_PLATFORM_RASTER_CAPABILITIES.intersection(required))
            ) and not registered_datasets:
                # Asset sampling needs dataset-level band declarations. A
                # connector implementation alone cannot prove those exist.
                continue
            if registered_datasets:
                implementation_datasets = [
                    dataset
                    for dataset in registered_datasets
                    if _dataset_query_compatible(query, dataset)
                    and _dataset_matches_perception_targets(
                        dataset,
                        variables,
                        requested_modalities,
                        self.modality_registry,
                    )
                    and _PLATFORM_RASTER_CAPABILITIES.intersection(required).issubset(
                        {value.casefold() for value in dataset.capabilities}
                    )
                ]
                if not implementation_datasets:
                    continue
                supported_variables = {
                    _canonical_variable(variable, self.modality_registry)
                    for dataset in implementation_datasets
                    for variable in dataset.variables
                }
                declared_modalities = {
                    modality
                    for dataset in implementation_datasets
                    for modality in (
                        *self.modality_registry.canonicalize(dataset.modalities),
                        *infer_modalities(dataset.variables, self.modality_registry),
                    )
                }
            else:
                implementation_datasets = []
                supported_variables = {
                    _canonical_variable(value, self.modality_registry)
                    for value in (
                        variable.canonical_name or variable.source_name
                        for variable in capability.variables
                    )
                }
                declared_modalities = set(capability.modalities)
            implementation_variables[metadata.connector_id] = supported_variables
            implementation_modalities[metadata.connector_id] = declared_modalities
            if requested_modalities and not requested_modalities.intersection(
                declared_modalities
            ):
                continue
            if variables:
                known_variables = {
                    variable
                    for variable in variables
                    if self.modality_registry.ontology.resolve_variable(variable)
                    is not None
                    or variable in supported_variables
                }
                unknown_variables = variables - known_variables
                # Known variables may be acquired by separate implementations.
                # Unknown vocabulary retains the old all-or-nothing behavior.
                if not (known_variables & supported_variables) and not (
                    unknown_variables
                    and unknown_variables.issubset(supported_variables)
                ):
                    continue
            spatial_type = _spatial_query_type(query)
            if (
                spatial_type is not None
                and spatial_type not in capability.supported_spatial_types
            ):
                continue
            if (
                query.temporal_start is not None or query.temporal_end is not None
            ) and not capability.supports_temporal_query:
                continue
            requested_fields = set()
            if query.spatial_resolution is not None:
                requested_fields.add("spatial_resolution")
            if query.requested_dataset_ids or implementation_datasets:
                requested_fields.add("requested_dataset_ids")
            if query.filters:
                requested_fields.add("filters")
            if query.asset_preferences:
                requested_fields.add("asset_preferences")
            if query.asset_sampling is not None:
                requested_fields.add("asset_sampling")
            if query.raster_analysis is not None:
                requested_fields.update(
                    ("raster_analysis", "raster_pixel_selection")
                )
                if query.raster_weighting is not None:
                    requested_fields.add("raster_weighting")
            if query.raster_semantics:
                requested_fields.add("raster_semantics")
            if query.raster_component_extraction:
                requested_fields.add("raster_component_extraction")
            connector_fields = requested_fields - _PLATFORM_RASTER_QUERY_FIELDS
            if not connector_fields.issubset(capability.supported_query_fields):
                continue
            if query.region is not None:
                regions = {value.casefold() for value in capability.supported_regions}
                if query.region.casefold() not in regions and "*" not in regions:
                    continue
            if not _supports_temporal_extent(
                capability.connector_temporal_coverage, query
            ):
                continue
            candidates.append(connector)
        candidates.sort(
            key=lambda connector: (
                -capabilities_by_connector[
                    connector.metadata.connector_id
                ].connector_priority,
                self._HEALTH_ORDER[
                    capabilities_by_connector[
                        connector.metadata.connector_id
                    ].connector_health
                ],
                connector.metadata.connector_id,
            )
        )
        selected = tuple(candidates)
        available_variables = {
            variable
            for connector in selected
            for variable in implementation_variables[connector.metadata.connector_id]
        }
        selected_variables = tuple(sorted(variables & available_variables))
        available_modalities = {
            modality
            for connector in selected
            for modality in implementation_modalities[connector.metadata.connector_id]
        }
        selected_connector_ids = {
            connector.metadata.connector_id for connector in selected
        }
        selected_datasets = tuple(
            dataset
            for implementation_datasets in datasets_by_implementation.values()
            for dataset in implementation_datasets
            if dataset.connector_id in selected_connector_ids
            and _dataset_query_compatible(query, dataset)
            and _dataset_matches_perception_targets(
                dataset,
                variables,
                requested_modalities,
                self.modality_registry,
            )
        )
        selected_modalities = tuple(sorted(requested_modalities & available_modalities))
        plan = PerceptionPlan(
            requested_modalities=tuple(sorted(requested_modalities)),
            selected_modalities=selected_modalities,
            unavailable_modalities=tuple(
                sorted(requested_modalities - available_modalities)
            ),
            requested_variables=tuple(sorted(variables)),
            selected_variables=selected_variables,
            unavailable_variables=tuple(sorted(variables - available_variables)),
            implementation_ids=tuple(
                connector.metadata.connector_id for connector in selected
            ),
            dataset_ids=tuple(
                sorted(
                    f"{dataset.connector_id}:{dataset.dataset_id}"
                    + (f"@{dataset.version}" if dataset.version else "")
                    for dataset in selected_datasets
                )
            ),
            capability_matrix_revision=(
                capability_matrix.revision if capability_matrix is not None else None
            ),
        )
        return selected, plan


def _dataset_matches_perception_targets(
    dataset: DatasetMetadata,
    variables: set[str],
    requested_modalities: set[str],
    modality_registry: SensingModalityRegistry,
) -> bool:
    dataset_variables = {
        _canonical_variable(value, modality_registry) for value in dataset.variables
    }
    dataset_modalities = set(modality_registry.canonicalize(dataset.modalities))
    dataset_modalities.update(infer_modalities(dataset.variables, modality_registry))
    variable_match = not variables or bool(variables & dataset_variables)
    modality_match = not requested_modalities or bool(
        requested_modalities & dataset_modalities
    )
    return variable_match and modality_match


def _dataset_query_compatible(query: EarthQuery, dataset: DatasetMetadata) -> bool:
    """Reject known-disjoint coverage without treating unknown as a guarantee."""
    if query.requested_dataset_ids and not _dataset_id_requested(
        query.requested_dataset_ids,
        dataset.connector_id,
        dataset.dataset_id,
        dataset.version,
    ):
        return False
    has_aoi = any(
        value is not None for value in (query.point, query.bbox, query.geometry)
    )
    if has_aoi and dataset.spatial_coverage is not None:
        if not query_intersects_coverage(
            query,
            dataset.spatial_coverage,
            coverage_crs=dataset.crs or query.crs,
        ):
            return False
    if query.temporal_start is not None or query.temporal_end is not None:
        coverage = dataset.temporal_coverage
        if coverage is not None and (
            query.temporal_start is not None
            and coverage.end is not None
            and query.temporal_start > coverage.end
        ):
            return False
        if coverage is not None and (
            query.temporal_end is not None
            and coverage.start is not None
            and query.temporal_end < coverage.start
        ):
            return False
    return True


def _latest_dataset_versions(
    datasets: Iterable[DatasetMetadata], query: EarthQuery
) -> tuple[DatasetMetadata, ...]:
    """Select one current dataset version unless the query pins a version."""
    requested_versions: dict[tuple[str, str], set[str]] = {}
    for identity in query.requested_dataset_ids:
        if ":" not in identity or "@" not in identity:
            continue
        connector_id, qualified_dataset = identity.split(":", 1)
        dataset_id, version = qualified_dataset.rsplit("@", 1)
        if connector_id and dataset_id and version:
            requested_versions.setdefault((connector_id, dataset_id), set()).add(
                version
            )

    grouped: dict[tuple[str, str], list[DatasetMetadata]] = {}
    for dataset in datasets:
        if query.requested_dataset_ids and not _dataset_id_requested(
            query.requested_dataset_ids,
            dataset.connector_id,
            dataset.dataset_id,
            dataset.version,
        ):
            continue
        grouped.setdefault((dataset.connector_id, dataset.dataset_id), []).append(
            dataset
        )

    selected: list[DatasetMetadata] = []
    for identity in sorted(grouped):
        versions = grouped[identity]
        pinned = requested_versions.get(identity)
        candidates = (
            [item for item in versions if item.version in pinned]
            if pinned
            else versions
        )
        if candidates:
            selected.append(max(candidates, key=lambda item: item.version or ""))
    return tuple(selected)


class ModalityImplementationSelector(CapabilityConnectorSelector):
    """Domain-first selector name; the older class remains a compatible alias."""


class MemoryObservationCache:
    """Observation cache isolated by a namespace over a replaceable backend."""

    def __init__(
        self,
        *,
        max_entries: Optional[int] = None,
        backend: Optional[CacheBackend] = None,
    ) -> None:
        if backend is not None and max_entries is not None:
            raise ValueError("max_entries is only valid when using the default cache")
        self._cache = backend or MemoryCache(max_entries=max_entries)
        self._namespace = "earth-observation:"
        self._index_lock = asyncio.Lock()
        self._index: dict[str, tuple[frozenset[str], Optional[float]]] = {}

    async def get(self, fingerprint: str) -> Tuple[bool, Optional[PerceptionResult]]:
        async with self._index_lock:
            indexed = self._index.get(fingerprint)
            if indexed is not None and indexed[1] is not None:
                if indexed[1] <= time.monotonic():
                    self._index.pop(fingerprint, None)
                    await self._cache.get(self._namespace + fingerprint)
                    return False, None
        found, value = await self._cache.get(self._namespace + fingerprint)
        if not found:
            async with self._index_lock:
                self._index.pop(fingerprint, None)
            return False, None
        if not isinstance(value, PerceptionResult):
            raise CacheError("Observation cache contained an invalid result.")
        return True, value

    async def set(
        self,
        fingerprint: str,
        result: PerceptionResult,
        *,
        ttl_seconds: float,
    ) -> None:
        async with self._index_lock:
            await self._cache.set(
                self._namespace + fingerprint,
                result,
                ttl_seconds=ttl_seconds,
            )
            expires_at = time.monotonic() + ttl_seconds
            self._index[fingerprint] = (
                frozenset(result.connector_ids),
                expires_at,
            )

    async def invalidate_connector(self, connector_id: str) -> int:
        """Remove cached perception results acquired from one connector."""
        async with self._index_lock:
            fingerprints = tuple(
                fingerprint
                for fingerprint, (connector_ids, _) in self._index.items()
                if connector_id in connector_ids
            )
            for fingerprint in fingerprints:
                await self._cache.delete(self._namespace + fingerprint)
                self._index.pop(fingerprint, None)
        return len(fingerprints)

    async def clear(self) -> None:
        async with self._index_lock:
            await self._cache.clear()
            self._index.clear()

    async def stats(self) -> CacheStats:
        """Return local cache statistics, including expired-result count."""
        return await self._cache.stats()


class PerceptionEngine:
    """Plan Earth perception across implementations and expose observations."""

    def __init__(
        self,
        connector_manager: ConnectorManager,
        *,
        cache: Optional[ObservationCache] = None,
        cache_ttl_seconds: float = 300,
        max_concurrency: Optional[int] = 8,
        selector: Optional[ConnectorSelector] = None,
        modality_registry: Optional[SensingModalityRegistry] = None,
        normalizer: Optional[SemanticNormalizer] = None,
        raster_asset_sampler: Optional[RasterAssetSamplingService] = None,
        raster_analysis_service: Optional[RasterAnalysisService] = None,
    ) -> None:
        if cache is not None and cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be greater than zero")
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be greater than zero or None")
        self.connector_manager = connector_manager
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_concurrency = max_concurrency
        self.normalizer = normalizer or SemanticNormalizer()
        self.raster_asset_sampler = raster_asset_sampler or RasterAssetSamplingService()
        self.raster_analysis_service = raster_analysis_service or RasterAnalysisService()
        self.observation_stack_builder = ExactSupportObservationStackBuilder()
        self.temporal_difference_engine = ConsecutiveTemporalDifferenceEngine()
        if selector is None:
            self.modality_registry = modality_registry or EARTH_SENSING_MODALITIES
            self.selector = ModalityImplementationSelector(self.modality_registry)
        else:
            self.selector = selector
            self.modality_registry = modality_registry or getattr(
                selector, "modality_registry", EARTH_SENSING_MODALITIES
            )
        self.fusion = ObservationFusion()
        self.graph_builder = ObservationGraphBuilder()

    def select_implementations(
        self, query: EarthQuery
    ) -> tuple[PerceptionConnector, ...]:
        """Return implementations capable of the requested Earth perception."""
        if not isinstance(query, EarthQuery):
            raise TypeError("query must be an EarthQuery")
        connectors = tuple(
            component
            for _, component in self.connector_manager.registry.items()
            if isinstance(component, PerceptionConnector)
        )
        matrix = self.build_capability_matrix(connectors=connectors)
        if isinstance(self.selector, CapabilityConnectorSelector):
            return self.selector.select(query, connectors, matrix.datasets)
        return self.selector.select(query, connectors)

    def select_connectors(self, query: EarthQuery) -> tuple[PerceptionConnector, ...]:
        """Backward-compatible alias for :meth:`select_implementations`."""
        return self.select_implementations(query)

    def plan(self, query: EarthQuery) -> PerceptionPlan:
        """Expose expected modality and variable coverage before acquisition."""
        if not isinstance(query, EarthQuery):
            raise TypeError("query must be an EarthQuery")
        connectors = tuple(
            component
            for _, component in self.connector_manager.registry.items()
            if isinstance(component, PerceptionConnector)
        )
        matrix = self.build_capability_matrix(connectors=connectors)
        if isinstance(self.selector, CapabilityConnectorSelector):
            return self.selector.plan(
                query,
                connectors,
                matrix.datasets,
                capability_matrix=matrix,
            )[1]
        selected = self.selector.select(query, connectors)
        plan = _plan_from_selected(
            query, selected, self.modality_registry, matrix.datasets
        )
        return plan.model_copy(update={"capability_matrix_revision": matrix.revision})

    def build_capability_matrix(
        self,
        *,
        connectors: Optional[Iterable[PerceptionConnector]] = None,
    ) -> EarthCapabilityMatrix:
        """Return a deterministic snapshot of registered Earth capabilities."""
        connector_values = (
            tuple(connectors)
            if connectors is not None
            else tuple(
                component
                for _, component in self.connector_manager.registry.items()
                if isinstance(component, PerceptionConnector)
            )
        )
        return build_earth_capability_matrix(
            (connector.metadata for connector in connector_values),
            self._registered_datasets(),
            modality_registry=self.modality_registry,
        )

    def _registered_datasets(self) -> tuple[DatasetMetadata, ...]:
        registry = self.connector_manager.dataset_registry
        if registry is None:
            return ()
        return tuple(
            self.normalizer.harmonize_dataset(dataset)
            for dataset in registry.list()
        )

    async def observe(self, query: EarthQuery) -> PerceptionResult:
        fingerprint = query_fingerprint(query)
        registered_connectors = tuple(
            component
            for _, component in self.connector_manager.registry.items()
            if isinstance(component, PerceptionConnector)
        )
        matrix = self.build_capability_matrix(connectors=registered_connectors)
        datasets = matrix.datasets
        if isinstance(self.selector, CapabilityConnectorSelector):
            connectors, plan = self.selector.plan(
                query,
                registered_connectors,
                datasets,
                capability_matrix=matrix,
            )
        else:
            connectors = self.select_implementations(query)
            plan = _plan_from_selected(
                query, connectors, self.modality_registry, datasets
            )
            plan = plan.model_copy(
                update={"capability_matrix_revision": matrix.revision}
            )
        if not connectors:
            raise ConnectorError(
                "No available perception connector satisfies the EarthQuery.",
                context={
                    "required_capabilities": query.required_capabilities,
                    "requested_variables": query.requested_variables,
                    "region": query.region,
                },
            )
        connector_versions = tuple(_connector_identity(item) for item in connectors)
        cache_key = _observation_cache_key(
            fingerprint,
            matrix.revision,
            connector_versions,
            self.normalizer.revision,
            (
                self.raster_asset_sampler.VERSION,
                self.raster_analysis_service.VERSION,
                self.observation_stack_builder.VERSION,
                self.temporal_difference_engine.VERSION,
            ),
        )
        if self.cache is not None:
            try:
                found, cached = await self.cache.get(cache_key)
            except CacheError:
                raise
            except Exception as exc:
                raise CacheError(f"Observation cache lookup failed: {exc}") from exc
            if found:
                if cached is None:
                    raise CacheError(
                        "Observation cache returned an empty cached result."
                    )
                if not isinstance(cached, PerceptionResult):
                    raise CacheError("Observation cache returned an invalid result.")
                if cached.connector_versions == connector_versions:
                    return cached.model_copy(update={"cache_hit": True})
        semaphore = (
            asyncio.Semaphore(self.max_concurrency)
            if self.max_concurrency is not None
            else None
        )
        connector_ids = {item.metadata.connector_id for item in connectors}
        datasets_by_implementation: dict[str, tuple[DatasetMetadata, ...]] = {}
        for connector in connectors:
            datasets_by_implementation[connector.metadata.connector_id] = tuple(
                dataset
                for dataset in datasets
                if dataset.connector_id == connector.metadata.connector_id
                and not dataset.deprecated
            )
        fallback_connectors = tuple(
            item
            for item in connectors
            if item.metadata.fallback_for
            and any(target in connector_ids for target in item.metadata.fallback_for)
        )
        fallback_ids = {item.metadata.connector_id for item in fallback_connectors}
        primary_connectors = tuple(
            item
            for item in connectors
            if item.metadata.connector_id not in fallback_ids
        )
        if not primary_connectors:
            raise ConnectorError(
                "Selected fallback connectors form a cycle without a primary source.",
                context={"connectors": sorted(connector_ids)},
            )
        acquired = list(
            await asyncio.gather(
                *(
                    self._acquire(
                        connector,
                        query,
                        semaphore,
                        datasets_by_implementation.get(
                            connector.metadata.connector_id, ()
                        ),
                    )
                    for connector in primary_connectors
                )
            )
        )
        failed_ids = {
            connector.metadata.connector_id
            for connector, _, failure in acquired
            if failure is not None
        }
        remaining_fallbacks = list(fallback_connectors)
        recovered_ids: set[str] = set()
        while remaining_fallbacks:
            remaining_fallbacks.sort(
                key=lambda connector: (
                    -connector.metadata.priority,
                    connector.metadata.connector_id,
                )
            )
            ready = next(
                (
                    connector
                    for connector in remaining_fallbacks
                    if set(connector.metadata.fallback_for).issubset(failed_ids)
                    and not set(connector.metadata.fallback_for).intersection(
                        recovered_ids
                    )
                ),
                None,
            )
            if ready is None:
                break
            fallback_result = await self._acquire(ready, query, semaphore)
            acquired.append(fallback_result)
            connector, _, failure = fallback_result
            connector_id = connector.metadata.connector_id
            if failure is None:
                recovered_ids.update(connector.metadata.fallback_for)
            else:
                failed_ids.add(connector_id)
            remaining_fallbacks = [
                candidate
                for candidate in remaining_fallbacks
                if candidate.metadata.connector_id != connector_id
            ]
        acquired_by_id = {item[0].metadata.connector_id: item for item in acquired}
        acquired = [
            acquired_by_id[connector.metadata.connector_id]
            for connector in connectors
            if connector.metadata.connector_id in acquired_by_id
        ]
        observations: list[Observation] = []
        failures: list[PerceptionFailure] = []
        processing_failures: list[PerceptionProcessingFailure] = []
        successful_connectors: list[str] = []
        for connector, result, failure in acquired:
            if failure is not None:
                failures.append(failure)
                continue
            if result is None:
                raise ConnectorError(
                    "Perception connector completed without a normalized result.",
                    context={"connector": connector.metadata.connector_id},
                )
            successful_connectors.append(connector.metadata.connector_id)
            retrieved_at = datetime.now(timezone.utc)
            for observation in result.observations:
                enriched = self._with_provenance(
                    observation,
                    connector,
                    fingerprint,
                    retrieved_at,
                    self.modality_registry,
                    capability_matrix_revision=matrix.revision,
                    normalizer_revision=self.normalizer.revision,
                    normalizer_version=self.normalizer.VERSION,
                )
                if query.asset_sampling == "point" or query.raster_analysis is not None:
                    try:
                        enriched, processing_status = await self._process_raster_observation(
                            enriched, query
                        )
                        if processing_status == "no_matching_bands":
                            processing_failures.append(PerceptionProcessingFailure(
                                observation_id=observation.observation_id,
                                stage=(
                                    "raster_asset_sampling"
                                    if query.asset_sampling == "point"
                                    else "raster_analysis"
                                ),
                                error_type="NoCompatibleRasterBands",
                                message=(
                                    "The observation's declared assets do not contain "
                                    "bands matching the requested variables."
                                ),
                            ))
                    except RasterAssetSamplingError as exc:
                        processing_failures.append(PerceptionProcessingFailure(
                            observation_id=observation.observation_id,
                            stage=(
                                "raster_asset_sampling"
                                if query.asset_sampling == "point"
                                else "raster_analysis"
                            ),
                            error_type=type(exc).__name__,
                            message=str(exc),
                        ))
                enriched = self.normalizer.canonicalize_observation(enriched)
                enriched = enriched.model_copy(
                    update={
                        "quality_assessment": assess_observation(
                            enriched,
                            expected_variables=(
                                tuple(
                                    _canonical_variable(value, self.modality_registry)
                                    for value in _implementation_query(
                                        query,
                                        connector,
                                        self.modality_registry,
                                        datasets_by_implementation.get(
                                            connector.metadata.connector_id, ()
                                        ),
                                    ).requested_variables
                                )
                                or None
                            ),
                            now=retrieved_at,
                        )
                    }
                )
                observations.append(enriched)

        merged, duplicate_count = _merge_exact_duplicates(observations)
        stack_build = (
            self.observation_stack_builder.build(tuple(merged))
            if query.asset_sampling == "point" and len(merged) > 1
            else None
        )
        temporal_differences, temporal_difference_issues = (
            self.temporal_difference_engine.build(stack_build.stacks)
            if stack_build is not None
            else ((), ())
        )
        groups = self.fusion.group(merged)
        conflicts = tuple(conflict for group in groups for conflict in group.conflicts)
        graph = self.graph_builder.build(merged)
        status = (
            "failed"
            if failures and not successful_connectors
            else "partial"
            if failures
            or processing_failures
            or plan.unavailable_modalities
            or plan.unavailable_variables
            else "complete"
        )
        result = PerceptionResult(
            query_fingerprint=fingerprint,
            observations=merged,
            connector_ids=tuple(successful_connectors),
            connector_versions=connector_versions,
            failures=tuple(failures),
            processing_failures=tuple(processing_failures),
            duplicate_count=duplicate_count,
            observation_groups=groups,
            observation_stacks=(stack_build.stacks if stack_build else ()),
            temporal_differences=temporal_differences,
            temporal_difference_issues=temporal_difference_issues,
            alignment_issues=(stack_build.issues if stack_build else ()),
            conflicts=conflicts,
            observation_graph=graph,
            plan=plan,
            status=status,
        )
        if self.cache is not None and not failures and not processing_failures:
            try:
                await self.cache.set(
                    cache_key, result, ttl_seconds=self.cache_ttl_seconds
                )
            except CacheError:
                raise
            except Exception as exc:
                raise CacheError(f"Observation cache write failed: {exc}") from exc
        return result

    async def stream(self, query: EarthQuery) -> AsyncIterator[Observation]:
        """Yield normalized observations as each selected connector produces them."""
        fingerprint = query_fingerprint(query)
        matrix = self.build_capability_matrix()
        if isinstance(self.selector, CapabilityConnectorSelector):
            connectors = self.selector.select(
                query,
                tuple(
                    component
                    for _, component in self.connector_manager.registry.items()
                    if isinstance(component, PerceptionConnector)
                ),
                matrix.datasets,
            )
        else:
            connectors = self.selector.select(
                query,
                tuple(
                    component
                    for _, component in self.connector_manager.registry.items()
                    if isinstance(component, PerceptionConnector)
                ),
            )
        if not connectors:
            raise ConnectorError(
                "No available perception connector satisfies the EarthQuery.",
                context={
                    "required_capabilities": query.required_capabilities,
                    "requested_variables": query.requested_variables,
                    "region": query.region,
                },
            )
        for connector in connectors:
            connector_id = connector.metadata.connector_id
            await self.connector_manager.start(connector_id)
            implementation_query = _implementation_query(
                query,
                connector,
                self.modality_registry,
                tuple(
                    dataset
                    for dataset in self._registered_datasets()
                    if dataset.connector_id == connector_id and not dataset.deprecated
                ),
            )
            async for observation in connector.stream_observations(
                implementation_query
            ):
                if not isinstance(observation, Observation):
                    raise ConnectorError(
                        "Perception connector stream yielded a non-Observation value.",
                        context={"connector": connector_id},
                    )
                enriched = self._with_provenance(
                    observation,
                    connector,
                    fingerprint,
                    datetime.now(timezone.utc),
                    self.modality_registry,
                    capability_matrix_revision=matrix.revision,
                    normalizer_revision=self.normalizer.revision,
                    normalizer_version=self.normalizer.VERSION,
                )
                if query.asset_sampling == "point" or query.raster_analysis is not None:
                    enriched, processing_status = await self._process_raster_observation(
                        enriched, query
                    )
                    if processing_status == "no_matching_bands":
                        raise RasterAssetSamplingError(
                            "The observation's declared assets do not contain bands "
                            "matching the requested variables."
                        )
                enriched = self.normalizer.canonicalize_observation(enriched)
                yield enriched.model_copy(
                    update={
                        "quality_assessment": assess_observation(
                            enriched,
                            expected_variables=(
                                implementation_query.requested_variables or None
                            ),
                        )
                    }
                )

    async def _process_raster_observation(
        self, observation: Observation, query: EarthQuery
    ) -> tuple[Observation, str]:
        if query.asset_sampling == "point":
            return await asyncio.to_thread(
                self.raster_asset_sampler.sample, observation, query
            )
        if query.raster_analysis is not None:
            return await asyncio.to_thread(
                self.raster_analysis_service.analyze, observation, query
            )
        return observation, "not_requested"

    async def stream_batches(
        self, query: EarthQuery, *, batch_size: int = 100
    ) -> AsyncIterator[tuple[Observation, ...]]:
        """Yield bounded batches, preserving stream order and consumer backpressure."""
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("batch_size must be a positive integer")
        batch: list[Observation] = []
        async for observation in self.stream(query):
            batch.append(observation)
            if len(batch) == batch_size:
                yield tuple(batch)
                batch.clear()
        if batch:
            yield tuple(batch)

    async def _acquire(
        self,
        connector: PerceptionConnector,
        query: EarthQuery,
        semaphore: Optional[asyncio.Semaphore],
        datasets: tuple[DatasetMetadata, ...] = (),
    ) -> tuple[
        PerceptionConnector,
        Optional[ObservationSearchResult],
        Optional[PerceptionFailure],
    ]:
        connector_id = connector.metadata.connector_id
        try:
            if semaphore is None:
                await self.connector_manager.start(connector_id)
                result = await connector.observe_with_policy(
                    _implementation_query(
                        query, connector, self.modality_registry, datasets
                    )
                )
            else:
                async with semaphore:
                    await self.connector_manager.start(connector_id)
                    result = await connector.observe_with_policy(
                        _implementation_query(
                            query, connector, self.modality_registry, datasets
                        )
                    )
        except ConnectorError as exc:
            return (
                connector,
                None,
                PerceptionFailure(
                    connector_id=connector_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                ),
            )
        if not isinstance(result, ObservationSearchResult):
            raise ConnectorError(
                "Perception connector returned a non-canonical acquisition result.",
                context={"connector": connector_id},
            )
        return connector, result, None

    @staticmethod
    def _with_provenance(
        observation: Observation,
        connector: PerceptionConnector,
        fingerprint: str,
        retrieved_at: datetime,
        modality_registry: SensingModalityRegistry,
        *,
        capability_matrix_revision: Optional[str] = None,
        normalizer_revision: Optional[str] = None,
        normalizer_version: Optional[str] = None,
    ) -> Observation:
        metadata = connector.metadata
        platform_record: dict[str, object] = {
            "connector_id": metadata.connector_id,
            "connector_name": metadata.name,
            "connector_version": metadata.version,
            "provider_version": metadata.provider_version,
            "query_fingerprint": fingerprint,
            "retrieved_at": retrieved_at.isoformat(),
        }
        if capability_matrix_revision is not None:
            platform_record["capability_matrix_revision"] = capability_matrix_revision
        if normalizer_revision is not None:
            platform_record["normalizer_revision"] = normalizer_revision
        if normalizer_version is not None:
            platform_record["normalizer_version"] = normalizer_version
        provider = metadata.provider_metadata.get("provider")
        if isinstance(provider, str) and provider:
            platform_record["provider"] = provider
        provenance = dict(observation.provenance)
        source_satquery = provenance.get("satquery", {})
        satquery = (
            dict(source_satquery)
            if isinstance(source_satquery, Mapping)
            else {"source_satquery_metadata": source_satquery}
        )
        satquery["earth_perception"] = platform_record
        provenance["satquery"] = satquery
        reproducibility = dict(observation.reproducibility)
        source_reproducibility = reproducibility.get("satquery", {})
        satquery_reproducibility = (
            dict(source_reproducibility)
            if isinstance(source_reproducibility, Mapping)
            else {"source_satquery_metadata": source_reproducibility}
        )
        satquery_reproducibility["earth_perception"] = platform_record
        reproducibility["satquery"] = satquery_reproducibility
        provider_metadata = dict(observation.provider_metadata)
        if metadata.provider_metadata:
            declared_metadata = dict(metadata.provider_metadata)
            if "connector_metadata" not in provider_metadata:
                provider_metadata["connector_metadata"] = declared_metadata
            else:
                provider_metadata["connector_metadata"] = {
                    "source": provider_metadata["connector_metadata"],
                    "connector": declared_metadata,
                }
        modalities = set(modality_registry.canonicalize(observation.modalities))
        modalities.update(
            infer_modalities(observation.measured_variables, modality_registry)
        )
        declared_modalities = modality_registry.canonicalize(metadata.modalities)
        # A single declared modality is safe for each result. Multi-domain
        # catalogs must identify each result from its own variables or metadata.
        if len(declared_modalities) == 1:
            modalities.update(declared_modalities)
        dataset_metadata = observation.dataset.metadata if observation.dataset else {}
        dataset_modalities = dataset_metadata.get("modalities", ())
        if isinstance(dataset_modalities, (list, tuple)):
            resolved_dataset_modalities = modality_registry.canonicalize(
                value for value in dataset_modalities if isinstance(value, str)
            )
            if len(resolved_dataset_modalities) == 1:
                modalities.update(resolved_dataset_modalities)
        return observation.model_copy(
            update={
                "provenance": provenance,
                "provider_metadata": provider_metadata,
                "reproducibility": reproducibility,
                "modalities": tuple(sorted(modalities)),
            }
        )


def query_fingerprint(query: EarthQuery) -> str:
    if not isinstance(query, EarthQuery):
        raise TypeError("query must be an EarthQuery")
    payload = query.model_dump(mode="json", exclude_none=True)
    for field in ("temporal_start", "temporal_end"):
        value = getattr(query, field)
        if value is not None:
            payload[field] = value.astimezone(timezone.utc).isoformat()
    payload["requested_variables"] = sorted(query.requested_variables)
    payload["requested_modalities"] = sorted(query.requested_modalities)
    payload["requested_dataset_ids"] = sorted(query.requested_dataset_ids)
    payload["required_capabilities"] = sorted(query.required_capabilities)
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "EarthQuery fields must be finite and JSON-compatible for fingerprinting."
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _observation_cache_key(
    query_hash: str,
    capability_revision: Optional[str],
    connector_versions: tuple[str, ...],
    normalizer_revision: str,
    raster_processing_versions: tuple[str, ...],
) -> str:
    """Scope results to the capability, adapter, and semantic mapping snapshot."""
    payload = {
        "query": query_hash,
        "capability_matrix_revision": capability_revision,
        "connector_versions": connector_versions,
        "normalizer_revision": normalizer_revision,
        "raster_processing_versions": raster_processing_versions,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _connector_identity(connector: PerceptionConnector) -> str:
    metadata = connector.metadata
    return ":".join(
        (
            metadata.connector_id,
            metadata.version,
            metadata.provider_version or "",
        )
    )


def _canonical_variable(
    value: str,
    modality_registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
) -> str:
    """Resolve only unambiguous ontology aliases for connector matching."""
    variable = modality_registry.ontology.resolve_variable(value)
    return (
        variable.canonical_name.casefold() if variable is not None else value.casefold()
    )


def _dataset_id_requested(
    requested_ids: Iterable[str],
    connector_id: str,
    dataset_id: str,
    version: Optional[str] = None,
) -> bool:
    identities = {dataset_id, f"{connector_id}:{dataset_id}"}
    if version:
        identities.add(f"{connector_id}:{dataset_id}@{version}")
    return any(value in identities for value in requested_ids)


def _implementation_query(
    query: EarthQuery,
    connector: PerceptionConnector,
    modality_registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
    datasets: Iterable[DatasetMetadata] = (),
) -> EarthQuery:
    """Restrict an Earth request to the variables a selected implementation serves."""
    datasets = _latest_dataset_versions(datasets, query)
    supported_variables = {
        _canonical_variable(value, modality_registry)
        for value in connector.metadata.supported_variables
    }
    configured_dataset_ids = {
        reference.dataset_id for reference in connector.metadata.datasets
    }
    implementation_datasets = tuple(
        dataset
        for dataset in datasets
        if dataset.connector_id == connector.metadata.connector_id
        and not dataset.deprecated
        and (not configured_dataset_ids or dataset.dataset_id in configured_dataset_ids)
        and _dataset_query_compatible(query, dataset)
        and _dataset_matches_perception_targets(
            dataset,
            {
                _canonical_variable(value, modality_registry)
                for value in query.requested_variables
            },
            set(modality_registry.canonicalize(query.requested_modalities))
            | set(infer_modalities(query.requested_variables, modality_registry)),
            modality_registry,
        )
    )
    if implementation_datasets:
        supported_variables = {
            _canonical_variable(value, modality_registry)
            for dataset in implementation_datasets
            for value in dataset.variables
        }
    if query.requested_variables:
        variables = tuple(
            value
            for value in query.requested_variables
            if _canonical_variable(value, modality_registry) in supported_variables
        )
    else:
        variables = query.requested_variables
    declared_modalities = set(
        modality_registry.canonicalize(connector.metadata.modalities)
    )
    if implementation_datasets:
        declared_modalities = {
            modality
            for dataset in implementation_datasets
            for modality in (
                *modality_registry.canonicalize(dataset.modalities),
                *infer_modalities(dataset.variables, modality_registry),
            )
        }
    else:
        declared_modalities.update(
            infer_modalities(connector.metadata.supported_variables, modality_registry)
        )
    requested_modalities = set(
        modality_registry.canonicalize(query.requested_modalities)
    )
    requested_modalities.update(
        infer_modalities(query.requested_variables, modality_registry)
    )
    modalities = tuple(sorted(requested_modalities & declared_modalities))
    return query.model_copy(
        update={
            "requested_variables": variables,
            "requested_modalities": modalities,
            "requested_dataset_ids": (
                tuple(sorted(dataset.dataset_id for dataset in implementation_datasets))
                if implementation_datasets
                else tuple(
                    reference.dataset_id
                    for reference in connector.metadata.datasets
                    if query.requested_dataset_ids
                    and _dataset_id_requested(
                        query.requested_dataset_ids,
                        reference.connector_id,
                        reference.dataset_id,
                        reference.version,
                    )
                )
            ),
        }
    )


def _plan_from_selected(
    query: EarthQuery,
    selected: Iterable[PerceptionConnector],
    modality_registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
    datasets: Iterable[DatasetMetadata] = (),
) -> PerceptionPlan:
    selected = tuple(selected)
    requested_modalities = set(
        modality_registry.canonicalize(query.requested_modalities)
    )
    requested_modalities.update(
        infer_modalities(query.requested_variables, modality_registry)
    )
    requested_variables = {
        _canonical_variable(value, modality_registry)
        for value in query.requested_variables
    }
    selected = tuple(selected)
    selected_ids = {connector.metadata.connector_id for connector in selected}
    selected_datasets = tuple(
        dataset
        for dataset in datasets
        if dataset.connector_id in selected_ids
        and not dataset.deprecated
        and _dataset_query_compatible(query, dataset)
        and _dataset_matches_perception_targets(
            dataset, requested_variables, requested_modalities, modality_registry
        )
    )
    available_variables = {
        _canonical_variable(value, modality_registry)
        for connector in selected
        for value in connector.metadata.supported_variables
    }
    available_variables.update(
        _canonical_variable(value, modality_registry)
        for dataset in selected_datasets
        for value in dataset.variables
    )
    available_modalities = {
        modality
        for connector in selected
        for modality in (
            *modality_registry.canonicalize(connector.metadata.modalities),
            *infer_modalities(
                connector.metadata.supported_variables, modality_registry
            ),
        )
    }
    available_modalities.update(
        modality
        for dataset in selected_datasets
        for modality in (
            *modality_registry.canonicalize(dataset.modalities),
            *infer_modalities(dataset.variables, modality_registry),
        )
    )
    return PerceptionPlan(
        requested_modalities=tuple(sorted(requested_modalities)),
        selected_modalities=tuple(sorted(requested_modalities & available_modalities)),
        unavailable_modalities=tuple(
            sorted(requested_modalities - available_modalities)
        ),
        requested_variables=tuple(sorted(requested_variables)),
        selected_variables=tuple(sorted(requested_variables & available_variables)),
        unavailable_variables=tuple(sorted(requested_variables - available_variables)),
        implementation_ids=tuple(
            connector.metadata.connector_id for connector in selected
        ),
        dataset_ids=tuple(
            sorted(
                f"{dataset.connector_id}:{dataset.dataset_id}"
                + (f"@{dataset.version}" if dataset.version else "")
                for dataset in selected_datasets
            )
        ),
    )


def _supports_temporal_extent(
    coverage: Optional[TemporalExtent], query: EarthQuery
) -> bool:
    start = coverage.start if coverage is not None else None
    end = coverage.end if coverage is not None else None
    if query.temporal_start is not None and end is not None:
        if query.temporal_start > end:
            return False
    if query.temporal_end is not None and start is not None:
        if query.temporal_end < start:
            return False
    return True


def _spatial_query_type(query: EarthQuery) -> Optional[str]:
    if query.bbox is not None:
        return "bbox"
    if query.point is not None:
        return "point"
    if query.geometry is not None:
        return "point" if query.geometry.get("type") == "Point" else "geometry"
    return None


def _merge_exact_duplicates(
    observations: list[Observation],
) -> tuple[tuple[Observation, ...], int]:
    positions: dict[str, int] = {}
    merged: list[Observation] = []
    duplicate_count = 0
    source_records: dict[str, list[dict[str, object]]] = {}
    for observation in observations:
        try:
            content = observation.model_dump(
                mode="json",
                exclude={
                    "observation_id",
                    "source_id",
                    "dataset",
                    "provenance",
                    "provider_metadata",
                    "reproducibility",
                    "quality_assessment",
                    "source_document",
                },
            )
            # Canonical records repeat the enclosing observation identifier as
            # a trace link. The identifier is intentionally ignored for exact
            # duplicate comparison, while all semantic fields remain part of
            # the signature.
            content["canonical_measurements"] = [
                {**measurement, "observation_id": None}
                for measurement in content.get("canonical_measurements", ())
            ]
            signature = json.dumps(
                content, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Observation fields must be finite and JSON-compatible for deduplication.",
                context={"observation": observation.observation_id},
            ) from exc
        position = positions.get(signature)
        source_record = observation.model_dump(mode="json")
        if position is None:
            positions[signature] = len(merged)
            merged.append(observation)
            source_records[signature] = [source_record]
            continue
        duplicate_count += 1
        source_records[signature].append(source_record)
        original = merged[position]
        provenance = dict(original.provenance)
        satquery = provenance.get("satquery", {})
        satquery = (
            dict(satquery)
            if isinstance(satquery, Mapping)
            else {"source_satquery_metadata": satquery}
        )
        earth_perception = satquery.get("earth_perception", {})
        earth_perception = (
            dict(earth_perception)
            if isinstance(earth_perception, Mapping)
            else {"source_earth_perception": earth_perception}
        )
        earth_perception["merged_sources"] = source_records[signature]
        satquery["earth_perception"] = earth_perception
        provenance["satquery"] = satquery
        merged[position] = original.model_copy(update={"provenance": provenance})
    return tuple(merged), duplicate_count
