"""Asynchronous connector for STAC API catalogs and item search."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import SplitResult, quote, urljoin, urlsplit, urlunsplit

import httpx
from pydantic import ValidationError as PydanticValidationError

from satquery.errors import (
    AuthenticationError,
    ConnectorError,
    NetworkError,
    OperationTimeoutError,
    RateLimitError,
    ValidationError,
)
from satquery.platform.connectors import PerceptionConnector
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    Observation,
    ObservationAsset,
    ObservationSearchResult,
    TemporalExtent,
)
from satquery.platform.modalities import infer_modalities
from satquery.platform.ontology import EARTH_VARIABLE_ONTOLOGY

from .contracts import StacConnectorSettings, StacSearchRequest


class StacCatalogConnector(PerceptionConnector):
    """Connect to one STAC API, preserving Item Search GeoJSON responses.

    Catalog-specific behavior is discovered from STAC landing-page links;
    provider URLs and collection identifiers are configuration, not code.
    """

    def __init__(
        self,
        *,
        configuration: Mapping[str, Any],
        transport: Optional[httpx.AsyncBaseTransport] = None,
        **kwargs: Any,
    ) -> None:
        try:
            settings = StacConnectorSettings.model_validate(configuration)
        except PydanticValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise ValidationError(
                f"Invalid STAC connector configuration: {details}",
                context={"connector": "stac-catalog"},
            ) from exc
        super().__init__(configuration=configuration, **kwargs)
        self.settings = settings
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._search_url: Optional[str] = None
        self._search_method = "GET"
        self._collections_url: Optional[str] = None
        self._catalog_discovered = False
        self._datasets = tuple(
            self._dataset_reference(collection_id)
            for collection_id in settings.collection_ids
        )
        self._datasets_by_id = {
            dataset.dataset_id: dataset for dataset in self._datasets
        }

    @property
    def metadata(self) -> ConnectorMetadata:
        capabilities = ["catalog-discovery", "observation-search", "item-assets"]
        supported_fields = ["requested_dataset_ids"]
        return ConnectorMetadata(
            connector_id=self.settings.connector_id,
            name="STAC API Catalog",
            version="1.3.0",
            capabilities=tuple(capabilities),
            authentication_schemes=("bearer",),
            authentication_required=self.settings.authentication_required,
            supports_async=True,
            supports_streaming=True,
            supports_temporal_query=True,
            supported_query_fields=tuple(supported_fields),
            supported_variables=tuple(
                sorted(
                    {
                        variable
                        for dataset in self._datasets
                        for variable in dataset.metadata.get("variables", ())
                        if isinstance(variable, str)
                    }
                )
            ),
            modalities=tuple(
                sorted(
                    {
                        modality
                        for dataset in self._datasets
                        for modality in (
                            *dataset.metadata.get("modalities", ()),
                            *infer_modalities(dataset.metadata.get("variables", ())),
                        )
                        if isinstance(modality, str)
                    }
                )
            ),
            supported_spatial_types=("bbox", "point", "geometry"),
            datasets=self._datasets,
            provider_metadata={"protocol": "STAC API"},
            configuration_schema={
                "type": "object",
                "required": ["catalog_url"],
                "properties": {
                    "catalog_url": {"type": "string", "format": "uri"},
                    "connector_id": {"type": "string", "minLength": 1},
                    "collection_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "uniqueItems": True,
                    },
                    "authentication_required": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        )

    async def open(self) -> None:
        if self._client is None:
            self._access_token = None
            self._client = httpx.AsyncClient(
                timeout=self.policy.timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
                headers={"Accept": "application/geo+json, application/json"},
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def probe(self) -> None:
        root = await self._request_json(self._catalog_url())
        if not isinstance(root.get("links"), list):
            raise ConnectorError(
                "STAC health probe received an invalid landing page.",
                context={"connector": self.settings.connector_id},
            )

    async def _authenticate(self, credentials: Mapping[str, str]) -> None:
        token = credentials.get("token")
        if (
            not isinstance(token, str)
            or not token.strip()
            or any(character.isspace() for character in token)
        ):
            raise AuthenticationError(
                "STAC bearer authentication requires a non-empty token.",
                context={"connector": self.settings.connector_id},
            )
        catalog = urlsplit(self._catalog_url())
        if catalog.scheme != "https" and catalog.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise AuthenticationError(
                "STAC bearer credentials require HTTPS outside loopback development.",
                context={"connector": self.settings.connector_id},
            )
        self._access_token = token

    async def discover(self) -> tuple[DatasetReference, ...]:
        root = await self._request_json(self._catalog_url())
        search_link = self._search_link(root)
        if search_link is None:
            raise ConnectorError(
                "STAC landing page is missing its 'search' link.",
                context={"connector": self.settings.connector_id},
            )
        search_method = str(search_link.get("method", "GET")).upper()
        if search_method not in {"GET", "POST"}:
            raise ConnectorError(
                f"Unsupported STAC search method {search_method!r}.",
                context={"connector": self.settings.connector_id},
            )
        collections_link = self._link(root, "data")
        search_url = self._resolve_link(search_link["href"])
        collections_url = self._resolve_link(
            collections_link["href"] if collections_link is not None else "collections"
        )

        collections: list[Mapping[str, Any]] = []
        page_url = collections_url
        visited: set[str] = set()
        while page_url is not None:
            if page_url in visited:
                raise ConnectorError(
                    "STAC collection pagination contains a repeated link.",
                    context={"connector": self.settings.connector_id},
                )
            visited.add(page_url)
            page = await self._request_json(page_url)
            values = page.get("collections")
            if not isinstance(values, list):
                raise ConnectorError(
                    "STAC collection response must contain a collections array.",
                    context={"connector": self.settings.connector_id},
                )
            collections.extend(item for item in values if isinstance(item, Mapping))
            next_link = self._link(page, "next")
            page_url = (
                self._resolve_link(next_link["href"]) if next_link is not None else None
            )

        discovered: dict[str, DatasetReference] = {}
        for collection in collections:
            collection_id = collection.get("id")
            if not isinstance(collection_id, str) or not collection_id.strip():
                raise ConnectorError(
                    "STAC collection is missing a non-empty id.",
                    context={"connector": self.settings.connector_id},
                )
            discovered[collection_id] = self._dataset_reference(
                collection_id,
                uri=self._collection_uri(collection_id, collections_url),
                version=(
                    collection.get("version")
                    if isinstance(collection.get("version"), str)
                    else None
                ),
                metadata=self._collection_metadata(collection),
            )

        if self.settings.collection_ids:
            missing = set(self.settings.collection_ids).difference(discovered)
            if missing:
                raise ValidationError(
                    f"Configured STAC collections were not found: {sorted(missing)}.",
                    context={
                        "connector": self.settings.connector_id,
                        "collections": sorted(missing),
                    },
                )
            discovered = {key: discovered[key] for key in self.settings.collection_ids}
        self._datasets = tuple(discovered[key] for key in sorted(discovered))
        self._datasets_by_id = discovered
        self._search_url = search_url
        self._search_method = search_method
        self._collections_url = collections_url
        self._catalog_discovered = True
        return self._datasets

    async def acquire(self, request: Mapping[str, Any]) -> ObservationSearchResult:
        search = self._validate_search_request(request)
        await self._ensure_search_url()
        self._validate_discovered_collections(search)
        payload = search.model_dump(exclude_none=True, mode="json")
        result = await self._send_search(
            self._search_url or "", self._search_method, payload
        )
        return self._observation_page(self._validate_feature_collection(result))

    async def observe(self, query: EarthQuery) -> ObservationSearchResult:
        request = self._request_from_earth_query(query)
        result = await self.fetch(request)
        if not isinstance(result, ObservationSearchResult):
            raise ConnectorError(
                "STAC acquisition did not return normalized observations.",
                context={"connector": self.settings.connector_id},
            )
        return result

    async def stream_observations(
        self, query: EarthQuery
    ) -> AsyncIterator[Observation]:
        request = self._request_from_earth_query(query)
        async for observation in self.stream(request):
            yield observation

    def _request_from_earth_query(self, query: EarthQuery) -> dict[str, Any]:
        if query.crs not in {"OGC:CRS84", "CRS84"}:
            raise ValidationError(
                "STAC Item Search requires coordinates in OGC:CRS84; reprojection is not provided.",
                context={"connector": self.settings.connector_id, "crs": query.crs},
            )
        unsupported = []
        if query.spatial_resolution is not None:
            unsupported.append("spatial_resolution")
        if query.filters:
            unsupported.append("filters")
        if query.asset_preferences:
            unsupported.append("asset_preferences")
        if unsupported:
            raise ValidationError(
                f"STAC connector cannot represent canonical query fields: {unsupported}.",
                context={"connector": self.settings.connector_id},
            )
        request: dict[str, Any] = {}
        if query.bbox is not None:
            request["bbox"] = query.bbox
        elif query.geometry is not None:
            request["intersects"] = query.geometry
        elif query.point is not None:
            request["intersects"] = {
                "type": "Point",
                "coordinates": list(query.point),
            }
        if query.temporal_start is not None or query.temporal_end is not None:
            request["datetime"] = "/".join(
                _format_datetime(value)
                for value in (query.temporal_start, query.temporal_end)
            )
        if query.requested_dataset_ids:
            request["collections"] = query.requested_dataset_ids
        return request

    async def stream(self, request: Mapping[str, Any]) -> AsyncIterator[Observation]:
        search = self._validate_search_request(request)
        await self._ensure_search_url()
        self._validate_discovered_collections(search)
        url = self._search_url or ""
        method = self._search_method
        body: Optional[Mapping[str, Any]] = search.model_dump(
            exclude_none=True, mode="json"
        )
        params: Optional[Mapping[str, Any]] = None
        visited: set[tuple[str, str, str]] = set()

        while True:
            if body is not None and method in {"GET", "POST"}:
                response = await self._send_search(url, method, body)
            else:
                response = await self._request_json(url, method=method, params=params)
            page = self._validate_feature_collection(response)
            for feature in page["features"]:
                yield self._observation_from_item(feature)

            next_link = self._link(page, "next")
            if next_link is None:
                return
            url = self._resolve_link(next_link["href"])
            method = str(next_link.get("method", "GET")).upper()
            if method not in {"GET", "POST"}:
                raise ConnectorError(
                    f"Unsupported STAC pagination method {method!r}.",
                    context={"connector": self.settings.connector_id},
                )
            link_body = next_link.get("body")
            body = link_body if isinstance(link_body, Mapping) else None
            params = body if method == "GET" else None
            marker = (
                url,
                method,
                json.dumps(body, sort_keys=True, default=str)
                if body is not None
                else "",
            )
            if marker in visited:
                raise ConnectorError(
                    "STAC item pagination contains a repeated link.",
                    context={"connector": self.settings.connector_id},
                )
            visited.add(marker)

    async def fetch(
        self,
        request: Mapping[str, Any],
        *,
        cache_key: Optional[str] = None,
        execution_context: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        if cache_key is not None and self.cache is not None:
            if self.policy.cache_ttl_seconds is None:
                raise ValidationError(
                    "STAC caching requires a positive cache_ttl_seconds policy.",
                    context={"connector": self.settings.connector_id},
                )
            cache_key = self._scope_cache_key(cache_key)
        return await super().fetch(
            request,
            cache_key=cache_key,
            execution_context=execution_context,
        )

    async def _ensure_search_url(self) -> None:
        if self._search_url is None:
            await self.discover()

    async def _send_search(
        self, url: str, method: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        if method == "POST":
            return await self._request_json(
                url, method=method, json_body=payload, retry=False
            )
        return await self._request_json(
            url,
            method="GET",
            params=_query_parameters(payload),
            retry=False,
        )

    def _validate_search_request(self, request: Mapping[str, Any]) -> StacSearchRequest:
        try:
            search = StacSearchRequest.model_validate(request)
        except PydanticValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise ValidationError(
                f"Invalid STAC search request: {details}",
                context={"connector": self.settings.connector_id},
            ) from exc
        if (
            self.settings.collection_ids
            and search.collections is not None
            and not set(search.collections).issubset(self.settings.collection_ids)
        ):
            raise ValidationError(
                "Search request includes a collection not enabled for this connector.",
                context={"connector": self.settings.connector_id},
            )
        if self.settings.collection_ids and search.collections is None:
            search = search.model_copy(
                update={"collections": self.settings.collection_ids}
            )
        return search

    def _validate_discovered_collections(self, search: StacSearchRequest) -> None:
        if search.collections is None or not self._catalog_discovered:
            return
        missing = set(search.collections).difference(self._datasets_by_id)
        if missing:
            raise ValidationError(
                f"STAC collections were not discovered: {sorted(missing)}.",
                context={
                    "connector": self.settings.connector_id,
                    "collections": sorted(missing),
                },
            )

    async def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        json_body: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        if self._client is None:
            raise ConnectorError(
                "STAC connector is not open; start it through ConnectorManager.",
                context={"connector": self.settings.connector_id},
            )
        self._assert_same_origin(url)
        headers: dict[str, str] = {}
        token = getattr(self, "_access_token", None)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        attempts = (
            self.policy.max_attempts
            if retry and method == "GET" and self.policy.retry_safe
            else 1
        )
        for attempt in range(1, attempts + 1):
            await self._rate_limiter.acquire()
            try:
                request = self._client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
                response = await request
                self._raise_for_status(response)
            except ConnectorError as exc:
                if not exc.recoverable or attempt == attempts:
                    raise
                await asyncio.sleep(self.policy.retry_delay_seconds)
                continue
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                error = OperationTimeoutError(
                    "STAC request exceeded the configured timeout.",
                    context={"connector": self.settings.connector_id},
                )
                if attempt == attempts:
                    raise error from exc
                await asyncio.sleep(self.policy.retry_delay_seconds)
                continue
            except httpx.NetworkError as exc:
                error = NetworkError(
                    "STAC catalog network request failed.",
                    context={"connector": self.settings.connector_id},
                )
                if attempt == attempts:
                    raise error from exc
                await asyncio.sleep(self.policy.retry_delay_seconds)
                continue
            try:
                payload = response.json()
            except (ValueError, UnicodeError) as exc:
                raise ConnectorError(
                    "STAC catalog returned invalid JSON.",
                    context={"connector": self.settings.connector_id},
                ) from exc
            return self._require_object(payload)
        raise AssertionError("STAC request retry loop exited without a result or error")

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        context = {
            "connector": self.settings.connector_id,
            "status_code": response.status_code,
        }
        if response.status_code in {401, 403}:
            raise AuthenticationError(
                "STAC catalog rejected the supplied credentials.", context=context
            )
        if response.status_code == 429:
            raise RateLimitError(
                "STAC catalog rate limit was reached.", context=context
            )
        if response.status_code >= 500:
            raise NetworkError("STAC catalog returned a server error.", context=context)
        raise ConnectorError(
            f"STAC catalog returned HTTP {response.status_code}.",
            context=context,
        )

    @staticmethod
    def _require_object(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ConnectorError("STAC API response must be a JSON object.")
        return payload

    def _validate_feature_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("type") != "FeatureCollection":
            raise ConnectorError(
                "STAC Item Search response must be a GeoJSON FeatureCollection.",
                context={"connector": self.settings.connector_id},
            )
        features = payload.get("features")
        if not isinstance(features, list) or any(
            not isinstance(feature, dict) or feature.get("type") != "Feature"
            for feature in features
        ):
            raise ConnectorError(
                "STAC FeatureCollection contains invalid features.",
                context={"connector": self.settings.connector_id},
            )
        return payload

    def _observation_page(
        self, feature_collection: Mapping[str, Any]
    ) -> ObservationSearchResult:
        features = feature_collection["features"]
        observations = tuple(self._observation_from_item(item) for item in features)
        context = feature_collection.get("context", {})
        links = feature_collection.get("links", [])
        if not isinstance(context, Mapping) or not isinstance(links, list):
            raise ConnectorError(
                "STAC FeatureCollection has invalid context or links.",
                context={"connector": self.settings.connector_id},
            )
        if any(not isinstance(link, Mapping) for link in links):
            raise ConnectorError(
                "STAC FeatureCollection contains an invalid link.",
                context={"connector": self.settings.connector_id},
            )
        normalized_links = tuple(links)
        matched = context.get("matched")
        try:
            return ObservationSearchResult(
                observations=observations,
                matched=matched,
                context=dict(context),
                links=tuple(dict(link) for link in normalized_links),
                source_document={
                    key: value
                    for key, value in feature_collection.items()
                    if key != "features"
                },
            )
        except PydanticValidationError as exc:
            raise ConnectorError(
                "STAC FeatureCollection context is invalid.",
                context={"connector": self.settings.connector_id},
            ) from exc

    def _observation_from_item(self, item: Mapping[str, Any]) -> Observation:
        source_id = item.get("id")
        properties = item.get("properties")
        geometry = item.get("geometry")
        raw_assets = item.get("assets", {})
        if (
            not isinstance(source_id, str)
            or not source_id
            or not isinstance(properties, Mapping)
            or (geometry is not None and not isinstance(geometry, Mapping))
            or not isinstance(raw_assets, Mapping)
        ):
            raise ConnectorError(
                "STAC Item is missing a valid id, properties, geometry, or assets object.",
                context={"connector": self.settings.connector_id},
            )

        assets: dict[str, ObservationAsset] = {}
        for asset_key, raw_asset in raw_assets.items():
            if not isinstance(asset_key, str) or not isinstance(raw_asset, Mapping):
                raise ConnectorError(
                    "STAC Item contains an invalid asset.",
                    context={"connector": self.settings.connector_id},
                )
            href = raw_asset.get("href")
            if not isinstance(href, str) or not href:
                raise ConnectorError(
                    "STAC Item asset is missing a valid href.",
                    context={
                        "connector": self.settings.connector_id,
                        "item_id": source_id,
                        "asset": asset_key,
                    },
                )
            roles = raw_asset.get("roles", ())
            if not isinstance(roles, (list, tuple)) or any(
                not isinstance(role, str) for role in roles
            ):
                raise ConnectorError(
                    "STAC Item asset roles must be a list of strings.",
                    context={
                        "connector": self.settings.connector_id,
                        "item_id": source_id,
                        "asset": asset_key,
                    },
                )
            known_fields = {
                "href",
                "type",
                "roles",
                "title",
                "description",
                "checksum:multihash",
                "checksum:sha256",
            }
            try:
                assets[asset_key] = ObservationAsset(
                    uri=href,
                    media_type=raw_asset.get("type"),
                    roles=tuple(roles),
                    title=raw_asset.get("title"),
                    description=raw_asset.get("description"),
                    checksum=raw_asset.get(
                        "checksum:multihash", raw_asset.get("checksum:sha256")
                    ),
                    metadata={
                        key: value
                        for key, value in raw_asset.items()
                        if key not in known_fields
                    },
                )
            except PydanticValidationError as exc:
                raise ConnectorError(
                    "STAC Item asset does not match the platform asset contract.",
                    context={
                        "connector": self.settings.connector_id,
                        "item_id": source_id,
                        "asset": asset_key,
                    },
                ) from exc

        collection_id = item.get("collection")
        if collection_id is not None and (
            not isinstance(collection_id, str) or not collection_id
        ):
            raise ConnectorError(
                "STAC Item collection must be a non-empty identifier.",
                context={
                    "connector": self.settings.connector_id,
                    "item_id": source_id,
                },
            )
        dataset = None
        if isinstance(collection_id, str) and collection_id:
            dataset = self._datasets_by_id.get(
                collection_id
            ) or self._dataset_reference(collection_id)
        bbox = item.get("bbox")
        if bbox is not None and not isinstance(bbox, list):
            raise ConnectorError(
                "STAC Item bbox must be an array when provided.",
                context={
                    "connector": self.settings.connector_id,
                    "item_id": source_id,
                },
            )
        try:
            return Observation(
                observation_id=(
                    f"stac:{self.settings.connector_id}:"
                    f"{collection_id or 'unknown'}:{source_id}"
                ),
                source_id=source_id,
                dataset=dataset,
                observed_at=properties.get("datetime"),
                geometry=dict(geometry) if geometry is not None else None,
                bbox=tuple(bbox) if isinstance(bbox, list) else None,
                crs="OGC:CRS84",
                temporal_extent=TemporalExtent(
                    start=properties.get("start_datetime", properties.get("datetime")),
                    end=properties.get("end_datetime", properties.get("datetime")),
                ),
                modalities=tuple(
                    dataset.metadata.get("modalities", ())
                    if dataset is not None
                    else ()
                ),
                provenance={
                    "protocol": "STAC API",
                    "catalog": self._catalog_url(),
                    "item_id": source_id,
                    "collection_id": collection_id,
                },
                properties=dict(properties),
                assets=assets,
                source_document=dict(item),
            )
        except PydanticValidationError as exc:
            raise ConnectorError(
                "STAC Item does not match the platform observation contract.",
                context={
                    "connector": self.settings.connector_id,
                    "item_id": source_id,
                },
            ) from exc

    @staticmethod
    def _link(document: Mapping[str, Any], relation: str, *, required: bool = False):
        links = document.get("links", [])
        if isinstance(links, list):
            for link in links:
                if (
                    isinstance(link, Mapping)
                    and link.get("rel") == relation
                    and isinstance(link.get("href"), str)
                ):
                    return link
        if required:
            raise ConnectorError(f"STAC landing page is missing its {relation!r} link.")
        return None

    @staticmethod
    def _search_link(document: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
        links = document.get("links", [])
        if not isinstance(links, list):
            return None
        candidates = [
            link
            for link in links
            if isinstance(link, Mapping)
            and link.get("rel") == "search"
            and isinstance(link.get("href"), str)
        ]
        return next(
            (
                link
                for link in candidates
                if str(link.get("method", "GET")).upper() == "POST"
            ),
            candidates[0] if candidates else None,
        )

    def _resolve_link(self, href: str) -> str:
        resolved = urljoin(self._catalog_url(), href)
        self._assert_same_origin(resolved)
        return resolved

    def _assert_same_origin(self, url: str) -> None:
        base = urlsplit(self._catalog_url())
        target = urlsplit(url)
        if (
            target.scheme.lower() != base.scheme.lower()
            or target.hostname != base.hostname
            or _effective_port(target) != _effective_port(base)
            or target.username is not None
            or target.password is not None
        ):
            raise ConnectorError(
                "STAC catalog links must remain on the configured origin.",
                context={"connector": self.settings.connector_id},
            )

    def _catalog_url(self) -> str:
        return str(self.settings.catalog_url).rstrip("/") + "/"

    def _collection_uri(
        self, collection_id: str, collections_url: Optional[str] = None
    ) -> str:
        base = (
            collections_url
            or self._collections_url
            or urljoin(self._catalog_url() + "/", "collections")
        )
        parts = urlsplit(base)
        path = f"{parts.path.rstrip('/')}/{quote(collection_id, safe='')}"
        return urlunsplit(parts._replace(path=path))

    def _dataset_reference(
        self,
        collection_id: str,
        *,
        uri: Optional[str] = None,
        version: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> DatasetReference:
        return DatasetReference(
            connector_id=self.settings.connector_id,
            dataset_id=collection_id,
            version=version,
            uri=uri or self._collection_uri(collection_id),
            metadata=metadata or {},
        )

    @staticmethod
    def _collection_metadata(collection: Mapping[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "stac_collection": dict(collection),
        }
        source_variables: set[str] = set()
        measurement_terms: set[str] = set()
        for source, target in (
            ("title", "title"),
            ("description", "description"),
            ("license", "licensing"),
            ("sci:doi", "citation"),
            ("citation", "citation"),
            ("update_frequency", "update_frequency"),
        ):
            if isinstance(collection.get(source), str):
                metadata[target] = collection[source]
        keywords = collection.get("keywords")
        if isinstance(keywords, list) and all(
            isinstance(item, str) for item in keywords
        ):
            metadata["keywords"] = keywords
            metadata["tags"] = keywords
            source_variables.update(keywords)
        declared_variables = collection.get("variables")
        if isinstance(declared_variables, list):
            declared_terms = {
                value for value in declared_variables if isinstance(value, str)
            }
            source_variables.update(declared_terms)
            measurement_terms.update(declared_terms)
        summaries = collection.get("summaries")
        raster_band_declaration = False
        if isinstance(summaries, Mapping):
            for key in ("eo:bands", "raster:bands", "variables"):
                values = summaries.get(key)
                if isinstance(values, list):
                    for value in values:
                        if isinstance(value, str):
                            source_variables.add(value)
                            if key == "variables":
                                measurement_terms.add(value)
                        elif isinstance(value, Mapping):
                            if key in {"eo:bands", "raster:bands"} and any(
                                isinstance(value.get(name), str)
                                and value.get(name).strip()
                                for name in ("name", "common_name", "description")
                            ):
                                raster_band_declaration = True
                            for name in ("name", "common_name", "description"):
                                candidate = value.get(name)
                                if isinstance(candidate, str):
                                    source_variables.add(candidate)
                                    if key in {"eo:bands", "raster:bands"}:
                                        measurement_terms.add(candidate)
            resolution_values = summaries.get("gsd")
            if isinstance(resolution_values, list):
                resolutions = sorted(
                    {
                        float(value)
                        for value in resolution_values
                        if isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(value)
                        and value > 0
                    }
                )
                if len(resolutions) == 1:
                    metadata["spatial_resolution"] = resolutions[0]
                    metadata["resolution_unit"] = "m"
                elif resolutions:
                    metadata["spatial_resolutions"] = resolutions
                    metadata["resolution_unit"] = "m"
        if raster_band_declaration and importlib.util.find_spec("rasterio") is not None:
            metadata["capabilities"] = [
                "raster_point_sampling",
                "raster_zonal_analysis",
            ]
            metadata["asset_processing"] = {
                "raster_point_sampling": "band metadata declared; verified per item at acquisition",
                "raster_zonal_analysis": "band metadata declared; verified per item at acquisition",
            }
        resolved_variables = [
            (source_name, EARTH_VARIABLE_ONTOLOGY.resolve_variable(source_name))
            for source_name in source_variables
        ]
        canonical_variables = {
            variable.canonical_name
            for _, variable in resolved_variables
            if variable is not None
        }
        if canonical_variables or measurement_terms:
            unresolved_measurement_terms = {
                source_name
                for source_name in measurement_terms
                if EARTH_VARIABLE_ONTOLOGY.resolve_variable(source_name) is None
            }
            metadata["variables"] = sorted(
                canonical_variables | unresolved_measurement_terms
            )
        if canonical_variables:
            metadata["modalities"] = list(infer_modalities(canonical_variables))
            metadata["source_variable_terms"] = sorted(
                source_name
                for source_name, variable in resolved_variables
                if variable is not None
            )
            metadata["canonical_concepts"] = sorted(
                {
                    variable.concept_id
                    for variable in EARTH_VARIABLE_ONTOLOGY.variables
                    if variable.canonical_name in canonical_variables
                }
            )
            metadata["categories"] = metadata["canonical_concepts"]
        optical_band_names = {
            "blue",
            "green",
            "red",
            "red_edge",
            "nir",
            "near_infrared",
            "swir",
            "shortwave_infrared",
            "pan",
            "panchromatic",
        }
        if any(
            source_name.strip().casefold().replace("-", "_") in optical_band_names
            for source_name in source_variables
        ):
            metadata["modalities"] = sorted(
                set(metadata.get("modalities", ())) | {"visual"}
            )
        extent = collection.get("extent")
        if isinstance(extent, Mapping):
            spatial = extent.get("spatial")
            bboxes = spatial.get("bbox") if isinstance(spatial, Mapping) else None
            if isinstance(bboxes, list):
                geometries = [
                    _bbox_to_geojson(bounds)
                    for bounds in bboxes
                    if isinstance(bounds, list) and _valid_bbox(bounds)
                ]
                coverage = (
                    geometries[0]
                    if len(geometries) == 1
                    else {
                        "type": "MultiPolygon",
                        "coordinates": [
                            geometry["coordinates"] for geometry in geometries
                        ],
                    }
                    if geometries
                    else None
                )
                if coverage is not None:
                    metadata["spatial_coverage"] = coverage
                    metadata["crs"] = "OGC:CRS84"
            temporal = extent.get("temporal")
            intervals = (
                temporal.get("interval") if isinstance(temporal, Mapping) else None
            )
            if isinstance(intervals, list) and intervals:
                interval = intervals[0]
                if (
                    isinstance(interval, list)
                    and len(interval) == 2
                    and all(
                        value is None or isinstance(value, str) for value in interval
                    )
                ):
                    metadata["temporal_coverage"] = {
                        "start": interval[0],
                        "end": interval[1],
                    }
        return metadata

    def _cache_key(self, request: Mapping[str, Any]) -> Optional[str]:
        if self.policy.cache_ttl_seconds is None:
            return None
        base_key = super()._cache_key(request)
        if base_key is None:
            return base_key
        return self._scope_cache_key(base_key)

    def _scope_cache_key(self, key: str) -> str:
        scope = f"{self._catalog_url()}\0{self._access_token or ''}"
        scope_fingerprint = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        return f"{key}:scope:{scope_fingerprint}"


def _effective_port(url: SplitResult) -> Optional[int]:
    if url.port is not None:
        return url.port
    return {"http": 80, "https": 443}.get(url.scheme.lower())


def _format_datetime(value: Optional[datetime]) -> str:
    if value is None:
        return ".."
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _query_parameters(payload: Mapping[str, Any]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for key, value in payload.items():
        if key == "sortby" and isinstance(value, (tuple, list)):
            parameters[key] = ",".join(
                f"{'-' if item.get('direction', 'asc') == 'desc' else '+'}"
                f"{item['field']}"
                for item in value
            )
        elif isinstance(value, (tuple, list)):
            parameters[key] = ",".join(str(item) for item in value)
        elif isinstance(value, (dict, bool)):
            parameters[key] = json.dumps(value, separators=(",", ":"))
        else:
            parameters[key] = str(value)
    return parameters


def _valid_bbox(bounds: list[Any]) -> bool:
    if len(bounds) not in {4, 6}:
        return False
    try:
        coordinates = [float(value) for value in bounds]
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in coordinates):
        return False
    if len(coordinates) == 4:
        min_x, min_y, max_x, max_y = coordinates
    else:
        min_x, min_y, _, max_x, max_y, _ = coordinates
    return min_x < max_x and min_y < max_y


def _bbox_to_geojson(bounds: list[Any]) -> dict[str, Any]:
    coordinates = [float(value) for value in bounds]
    if len(coordinates) == 6:
        min_x, min_y, _, max_x, max_y, _ = coordinates
    else:
        min_x, min_y, max_x, max_y = coordinates
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y],
            ]
        ],
    }
