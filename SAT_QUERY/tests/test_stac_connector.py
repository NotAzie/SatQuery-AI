from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from connectors.stac import StacCatalogConnector, StacSearchRequest
from pydantic import ValidationError as PydanticValidationError
from satquery.errors import AuthenticationError, ConnectorError, ValidationError
from satquery.platform.cache import MemoryCache
from satquery.platform.connectors import ConnectorManager, ConnectorPolicy
from satquery.platform.contracts import EarthQuery
from satquery.platform.registry import ComponentRegistry


def stac_item(item_id: str) -> dict:
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": "sentinel-2-l2a",
        "geometry": None,
        "bbox": [10, 20, 11, 21],
        "properties": {"datetime": "2024-01-01T00:00:00Z"},
        "assets": {
            "visual": {
                "href": f"https://assets.example/{item_id}.tif",
                "type": "image/tiff; application=geotiff",
                "roles": ["visual"],
            }
        },
        "links": [],
    }


def json_response(request: httpx.Request, payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/geo+json"},
        json=payload,
        request=request,
    )


def create_manager(
    handler,
    *,
    configuration=None,
    policy=None,
):
    connector = StacCatalogConnector(
        configuration=configuration
        or {
            "catalog_url": "https://catalog.example/stac",
            "collection_ids": ["sentinel-2-l2a"],
        },
        policy=policy,
        transport=httpx.MockTransport(handler),
    )
    manager = ConnectorManager(ComponentRegistry())
    manager.register(connector)
    return manager, connector


def test_stac_discovery_search_and_pagination_preserve_geojson():
    async def run():
        requests = []

        def handler(request: httpx.Request):
            requests.append(request)
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search", "method": "GET"},
                            {"rel": "search", "href": "search", "method": "POST"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(
                    request,
                    {
                        "collections": [
                            {
                                "id": "sentinel-2-l2a",
                                "title": "Sentinel-2 Level 2A",
                                "version": "v1",
                                "license": "proprietary",
                                "summaries": {
                                    "eo:bands": [
                                        {"name": "red", "common_name": "red"},
                                        {"name": "nir", "common_name": "near_infrared"},
                                    ]
                                },
                            },
                            {"id": "landsat-c2-l2", "title": "Landsat"},
                        ],
                        "links": [],
                    },
                )
            if request.url.path == "/stac/search":
                body = json.loads(request.content)
                if body.get("token") == "page-2":
                    return json_response(
                        request,
                        {
                            "type": "FeatureCollection",
                            "features": [stac_item("item-2")],
                            "links": [],
                        },
                    )
                assert body == {
                    "collections": ["sentinel-2-l2a"],
                    "bbox": [10.0, 20.0, 11.0, 21.0],
                    "datetime": "2024-01-01/2024-01-31",
                }
                return json_response(
                    request,
                    {
                        "type": "FeatureCollection",
                        "features": [stac_item("item-1")],
                        "context": {"matched": 2},
                        "links": [
                            {
                                "rel": "next",
                                "href": "search",
                                "method": "POST",
                                "body": {
                                    "collections": ["sentinel-2-l2a"],
                                    "token": "page-2",
                                },
                            }
                        ],
                    },
                )
            return httpx.Response(404, request=request)

        manager, connector = create_manager(handler)
        await manager.start("stac-catalog")
        datasets = await manager.discover("stac-catalog")
        assert [dataset.dataset_id for dataset in datasets] == ["sentinel-2-l2a"]
        assert datasets[0].metadata["title"] == "Sentinel-2 Level 2A"
        assert not {
            "raster_point_sampling",
            "raster_zonal_analysis",
            "raster_categorical_polygonization",
            "raster_geodesic_area_weighting",
        }.intersection(connector.metadata.capabilities)
        if importlib.util.find_spec("rasterio") is not None:
            assert "raster_point_sampling" in datasets[0].metadata["capabilities"]
            assert "raster_categorical_polygonization" not in datasets[0].metadata["capabilities"]

        result = await manager.acquire(
            "stac-catalog",
            {
                "collections": ["sentinel-2-l2a"],
                "bbox": [10, 20, 11, 21],
                "datetime": "2024-01-01/2024-01-31",
            },
        )
        first_observation = result.observations[0]
        assert first_observation.source_id == "item-1"
        assert first_observation.dataset is not None
        assert first_observation.dataset.dataset_id == "sentinel-2-l2a"
        assert first_observation.dataset.version == "v1"
        assert first_observation.assets["visual"].uri.endswith("item-1.tif")
        assert first_observation.properties["datetime"] == "2024-01-01T00:00:00Z"
        assert first_observation.source_document["id"] == "item-1"
        assert result.matched == 2
        streamed = [
            item async for item in connector.stream(
                {
                    "collections": ["sentinel-2-l2a"],
                    "bbox": [10, 20, 11, 21],
                    "datetime": "2024-01-01/2024-01-31",
                }
            )
        ]
        assert [item.source_id for item in streamed] == ["item-1", "item-2"]
        assert first_observation.observation_id == streamed[0].observation_id
        search_bodies = [
            json.loads(request.content)
            for request in requests
            if request.url.path == "/stac/search"
        ]
        assert any(item.get("token") == "page-2" for item in search_bodies)
        await manager.stop_all()

    asyncio.run(run())


def test_stac_declares_categorical_polygonization_only_for_explicit_class_bands():
    collection_metadata = StacCatalogConnector._collection_metadata({
        "id": "thematic-raster",
        "summaries": {
            "raster:bands": [{
                "name": "land_cover_class",
                "data_type": "uint8",
                "measurement_kind": "categorical",
            }]
        },
    })
    if (
        importlib.util.find_spec("rasterio") is not None
        and importlib.util.find_spec("shapely") is not None
    ):
        assert "raster_categorical_polygonization" in collection_metadata["capabilities"]
    else:
        assert "raster_categorical_polygonization" not in collection_metadata.get(
            "capabilities", ()
        )


def test_earth_query_dataset_selection_maps_to_stac_collection_filter():
    connector = StacCatalogConnector(
        configuration={
            "catalog_url": "https://catalog.example/stac",
            "collection_ids": ["sentinel-2-l2a", "landsat-c2-l2"],
        }
    )
    request = connector._request_from_earth_query(
        EarthQuery(
            bbox=(10, 20, 11, 21),
            requested_dataset_ids=("landsat-c2-l2",),
        )
    )
    assert request["collections"] == ("landsat-c2-l2",)


def test_stac_required_bearer_authentication_is_enforced_by_configuration():
    async def run():
        seen_authorization = []

        def handler(request: httpx.Request):
            seen_authorization.append(request.headers.get("Authorization"))
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            return json_response(
                request,
                {
                    "type": "Catalog",
                    "links": [
                        {"rel": "search", "href": "search"},
                        {"rel": "data", "href": "collections"},
                    ],
                },
            )

        manager, _ = create_manager(
            handler,
            configuration={
                "catalog_url": "https://catalog.example/stac",
                "authentication_required": True,
            },
        )
        with pytest.raises(AuthenticationError):
            await manager.start("stac-catalog")
        await manager.start("stac-catalog", {"token": "secret-token"})
        await manager.discover("stac-catalog")
        assert len(seen_authorization) == 2
        assert all(value.startswith("Bearer ") for value in seen_authorization)
        await manager.stop_all()

        insecure_manager, _ = create_manager(
            handler,
            configuration={
                "catalog_url": "http://catalog.example/stac",
                "authentication_required": True,
            },
        )
        with pytest.raises(AuthenticationError, match="require HTTPS"):
            await insecure_manager.start("stac-catalog", {"token": "another-token"})

    asyncio.run(run())


def test_stac_rejects_invalid_spatial_search_and_foreign_pagination_links():
    with pytest.raises(PydanticValidationError, match="longitude"):
        StacSearchRequest(bbox=[181, -10, 182, 10])
    with pytest.raises(PydanticValidationError, match="mutually exclusive"):
        StacSearchRequest(
            bbox=[10, -10, 20, 10],
            intersects={"type": "Point", "coordinates": [15, 0]},
        )
    dateline = StacSearchRequest(bbox=[170, -10, -170, 10])
    assert dateline.bbox == (170, -10, -170, 10)
    with pytest.raises(PydanticValidationError, match="elevation"):
        StacSearchRequest(bbox=[10, -10, 100, 20, 10, 50])

    async def run():
        def handler(request: httpx.Request):
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            return json_response(
                request,
                {
                    "type": "FeatureCollection",
                    "features": [],
                    "links": [{"rel": "next", "href": "https://other.example/page"}],
                },
            )

        manager, _ = create_manager(
            handler,
            configuration={"catalog_url": "https://catalog.example/stac"},
        )
        await manager.start("stac-catalog")
        with pytest.raises(ConnectorError, match="configured origin"):
            async for item in manager.stream("stac-catalog", {}):
                pytest.fail(f"unexpected item yielded: {item}")
        await manager.stop_all()

    asyncio.run(run())


def test_stac_search_retries_server_errors_only_when_policy_is_safe():
    async def run():
        search_attempts = 0

        def handler(request: httpx.Request):
            nonlocal search_attempts
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            search_attempts += 1
            if search_attempts == 1:
                return httpx.Response(503, request=request)
            return json_response(
                request,
                {"type": "FeatureCollection", "features": [], "links": []},
            )

        manager, _ = create_manager(
            handler,
            configuration={"catalog_url": "https://catalog.example/stac"},
            policy=ConnectorPolicy(
                max_attempts=2, retry_safe=True, retry_delay_seconds=0
            ),
        )
        await manager.start("stac-catalog")
        result = await manager.acquire("stac-catalog", {})
        assert result.observations == ()
        assert search_attempts == 2
        await manager.stop_all()

    asyncio.run(run())


def test_stac_get_search_uses_standard_query_parameter_encoding():
    async def run():
        search_requests = []

        def handler(request: httpx.Request):
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search", "method": "GET"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(
                    request,
                    {
                        "collections": [
                            {"id": "sentinel-2-l2a"},
                            {"id": "landsat-c2-l2"},
                        ],
                        "links": [],
                    },
                )
            search_requests.append(request)
            if len(search_requests) == 1:
                return httpx.Response(503, request=request)
            return json_response(
                request,
                {"type": "FeatureCollection", "features": [], "links": []},
            )

        manager, _ = create_manager(
            handler,
            configuration={"catalog_url": "https://catalog.example/stac"},
            policy=ConnectorPolicy(
                max_attempts=2, retry_safe=True, retry_delay_seconds=0
            ),
        )
        await manager.start("stac-catalog")
        await manager.acquire(
            "stac-catalog",
            {
                "collections": ["sentinel-2-l2a", "landsat-c2-l2"],
                "bbox": [10, 20, 11, 21],
                "sortby": [{"field": "datetime", "direction": "desc"}],
            },
        )
        assert len(search_requests) == 2
        assert search_requests[1].method == "GET"
        assert search_requests[1].url.params["collections"] == (
            "sentinel-2-l2a,landsat-c2-l2"
        )
        assert search_requests[1].url.params["bbox"] == "10.0,20.0,11.0,21.0"
        assert search_requests[1].url.params["sortby"] == "-datetime"
        await manager.stop_all()

    asyncio.run(run())


def test_stac_public_catalog_does_not_require_optional_bearer_credentials():
    async def run():
        seen_authorization = []

        def handler(request: httpx.Request):
            seen_authorization.append(request.headers.get("Authorization"))
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            return json_response(
                request,
                {
                    "type": "Catalog",
                    "links": [
                        {"rel": "search", "href": "search"},
                        {"rel": "data", "href": "collections"},
                    ],
                },
            )

        manager, connector = create_manager(
            handler,
            configuration={"catalog_url": "https://catalog.example/stac"},
        )
        assert connector.metadata.authentication_schemes == ("bearer",)
        assert not connector.metadata.authentication_required
        await manager.discover("stac-catalog")
        assert seen_authorization == [None, None]
        await manager.stop_all()

    asyncio.run(run())


def test_configured_collection_allowlist_is_applied_to_unscoped_searches():
    async def run():
        search_bodies = []

        def handler(request: httpx.Request):
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search", "method": "POST"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(
                    request,
                    {
                        "collections": [{"id": "sentinel-2-l2a"}],
                        "links": [],
                    },
                )
            search_bodies.append(json.loads(request.content))
            return json_response(
                request,
                {"type": "FeatureCollection", "features": [], "links": []},
            )

        manager, _ = create_manager(handler)
        await manager.acquire("stac-catalog", {})
        assert search_bodies == [{"collections": ["sentinel-2-l2a"]}]
        await manager.stop_all()

    asyncio.run(run())


def test_empty_catalog_discovery_rejects_unknown_collection_filters():
    async def run():
        requests = []

        def handler(request: httpx.Request):
            requests.append(request.url.path)
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            return json_response(
                request,
                {"type": "FeatureCollection", "features": [], "links": []},
            )

        manager, _ = create_manager(
            handler,
            configuration={"catalog_url": "https://catalog.example/stac"},
        )
        result = await manager.acquire("stac-catalog", {})
        assert result.observations == ()
        with pytest.raises(ConnectorError, match="not discovered"):
            await manager.acquire(
                "stac-catalog", {"collections": ["missing-collection"]}
            )
        assert requests.count("/stac/") == 1
        await manager.stop_all()

    asyncio.run(run())


def test_failed_collection_discovery_does_not_publish_partial_state():
    async def run():
        collection_page_requests = 0

        def handler(request: httpx.Request):
            nonlocal collection_page_requests
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if (
                request.url.path == "/stac/collections"
                and request.url.params.get("page") is None
            ):
                collection_page_requests += 1
                return json_response(
                    request,
                    {
                        "collections": [{"id": "sentinel-2-l2a"}],
                        "links": [
                            {
                                "rel": "next",
                                "href": "collections?page=2",
                            }
                        ],
                    },
                )
            if request.url.params.get("page") == "2":
                if collection_page_requests == 1:
                    return json_response(request, {"collections": "invalid"})
                return json_response(
                    request,
                    {"collections": [{"id": "landsat-c2-l2"}], "links": []},
                )
            return json_response(
                request,
                {"type": "FeatureCollection", "features": [], "links": []},
            )

        _, connector = create_manager(
            handler,
            configuration={"catalog_url": "https://catalog.example/stac"},
        )
        await connector.open()
        with pytest.raises(ConnectorError, match="collections array"):
            await connector.discover()
        assert connector._search_url is None
        assert connector._datasets_by_id == {}
        assert not connector._catalog_discovered

        datasets = await connector.discover()
        assert [item.dataset_id for item in datasets] == [
            "landsat-c2-l2",
            "sentinel-2-l2a",
        ]
        assert connector._catalog_discovered
        await connector.close()

    asyncio.run(run())


def test_earth_search_example_config_matches_connector_contract():
    config_path = (
        Path(__file__).parents[1]
        / "configs"
        / "catalogs"
        / "earth-search.json"
    )
    configuration = json.loads(config_path.read_text(encoding="utf-8"))
    connector = StacCatalogConnector(configuration=configuration)

    assert connector.metadata.connector_id == "earth-search"
    assert {dataset.dataset_id for dataset in connector.metadata.datasets} == {
        "sentinel-2-l2a",
        "sentinel-1-grd",
        "landsat-c2-l2",
        "cop-dem-glo-30",
    }


def test_stac_cache_is_scoped_to_bearer_credential():
    async def run():
        search_count = 0

        def handler(request: httpx.Request):
            nonlocal search_count
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search", "method": "POST"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            search_count += 1
            return json_response(
                request,
                {
                    "type": "FeatureCollection",
                    "features": [stac_item(request.headers["Authorization"])],
                    "links": [],
                },
            )

        connector = StacCatalogConnector(
            configuration={
                "catalog_url": "https://catalog.example/stac",
                "authentication_required": True,
            },
            policy=ConnectorPolicy(cache_ttl_seconds=60),
            cache=MemoryCache(),
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager(ComponentRegistry())
        manager.register(connector)

        await manager.start("stac-catalog", {"token": "first"})
        first = await manager.acquire(
            "stac-catalog", {"ids": ["same-query"]}, cache_key="shared-key"
        )
        await manager.stop("stac-catalog")
        await manager.start("stac-catalog", {"token": "second"})
        second = await manager.acquire(
            "stac-catalog", {"ids": ["same-query"]}, cache_key="shared-key"
        )

        assert first.observations[0].source_id != second.observations[0].source_id
        assert search_count == 2
        await manager.stop_all()

    asyncio.run(run())


def test_stac_cache_is_scoped_to_catalog_origin():
    async def run():
        responses = {"first": 0, "second": 0}
        cache = MemoryCache()

        def handler_for(name):
            def handler(request: httpx.Request):
                if request.url.path == "/stac/":
                    return json_response(
                        request,
                        {
                            "type": "Catalog",
                            "links": [
                                {"rel": "search", "href": "search", "method": "POST"},
                                {"rel": "data", "href": "collections"},
                            ],
                        },
                    )
                if request.url.path == "/stac/collections":
                    return json_response(request, {"collections": [], "links": []})
                responses[name] += 1
                return json_response(
                    request,
                    {
                        "type": "FeatureCollection",
                        "features": [stac_item(name)],
                        "links": [],
                    },
                )

            return handler

        results = []
        for name in ("first", "second"):
            connector = StacCatalogConnector(
                configuration={
                    "catalog_url": f"https://{name}.example/stac",
                    "connector_id": "same-connector-id",
                },
                policy=ConnectorPolicy(cache_ttl_seconds=60),
                cache=cache,
                transport=httpx.MockTransport(handler_for(name)),
            )
            manager = ConnectorManager(ComponentRegistry())
            manager.register(connector)
            results.append(
                await manager.acquire(
                    "same-connector-id",
                    {"ids": ["same-query"]},
                    cache_key="shared-key",
                )
            )
            await manager.stop_all()

        assert [item.observations[0].source_id for item in results] == [
            "first",
            "second",
        ]
        assert responses == {"first": 1, "second": 1}

    asyncio.run(run())


def test_stac_search_caching_requires_an_explicit_positive_ttl():
    async def run():
        search_count = 0

        def handler(request: httpx.Request):
            nonlocal search_count
            if request.url.path == "/stac/":
                return json_response(
                    request,
                    {
                        "type": "Catalog",
                        "links": [
                            {"rel": "search", "href": "search", "method": "POST"},
                            {"rel": "data", "href": "collections"},
                        ],
                    },
                )
            if request.url.path == "/stac/collections":
                return json_response(request, {"collections": [], "links": []})
            search_count += 1
            return json_response(
                request,
                {"type": "FeatureCollection", "features": [], "links": []},
            )

        connector = StacCatalogConnector(
            configuration={"catalog_url": "https://catalog.example/stac"},
            cache=MemoryCache(),
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager(ComponentRegistry())
        manager.register(connector)
        await manager.acquire("stac-catalog", {"ids": ["same-query"]})
        await manager.acquire("stac-catalog", {"ids": ["same-query"]})
        with pytest.raises(ValidationError, match="positive cache_ttl_seconds"):
            await manager.acquire(
                "stac-catalog",
                {"ids": ["same-query"]},
                cache_key="explicit-cache",
            )

        assert search_count == 2
        await manager.stop_all()

    asyncio.run(run())
