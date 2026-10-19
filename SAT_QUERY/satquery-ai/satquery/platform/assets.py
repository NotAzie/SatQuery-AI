"""Local provider-independent discovery of observation and dataset assets."""

from __future__ import annotations

from typing import Iterable

from .contracts import (
    AssetQuery,
    AssetSearchResult,
    DatasetMetadata,
    Observation,
    ObservationAsset,
)


class AssetCatalog:
    """Index assets without downloading, opening, or analyzing their contents."""

    def search(
        self,
        query: AssetQuery,
        *,
        observations: Iterable[Observation] = (),
        datasets: Iterable[DatasetMetadata] = (),
    ) -> AssetSearchResult:
        records: list[tuple[str, str, ObservationAsset]] = []
        for observation in observations:
            dataset_id = (
                observation.dataset.dataset_id if observation.dataset else ""
            )
            records.extend(
                (dataset_id, observation.observation_id, asset)
                for asset in observation.assets.values()
            )
        for dataset in datasets:
            records.extend(
                (dataset.dataset_id, dataset.dataset_id, asset)
                for asset in dataset.assets.values()
            )
        selected = [
            (source_id, asset)
            for dataset_id, source_id, asset in records
            if _matches(query, dataset_id, asset)
        ]
        selected.sort(
            key=lambda item: (
                item[1].uri,
                item[0],
                item[1].media_type or "",
                item[1].roles,
            )
        )
        return AssetSearchResult(
            assets=tuple(asset for _, asset in selected),
            matched=len(selected),
            source_ids=tuple(source_id for source_id, _ in selected),
        )


def _matches(query: AssetQuery, dataset_id: str, asset: ObservationAsset) -> bool:
    if query.dataset_id is not None and query.dataset_id != dataset_id:
        return False
    roles = {value.casefold() for value in asset.roles}
    if query.roles and not {value.casefold() for value in query.roles}.issubset(roles):
        return False
    if query.media_types and (
        asset.media_type is None
        or asset.media_type.casefold()
        not in {value.casefold() for value in query.media_types}
    ):
        return False
    capabilities = {value.casefold() for value in asset.capabilities}
    if query.required_capabilities and not {
        value.casefold() for value in query.required_capabilities
    }.issubset(capabilities):
        return False
    if query.text:
        haystack = " ".join(
            part
            for part in (
                asset.title,
                asset.description,
                asset.uri,
                *asset.roles,
            )
            if part
        ).casefold()
        if query.text.casefold() not in haystack:
            return False
    return True
