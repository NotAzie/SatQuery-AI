import json

import httpx
import pytest

from satquery import CLIENT_API_VERSION, PlatformAPIError, SatQueryClient
from satquery.__main__ import (
    build_parser,
    command_platform_observe,
    command_platform_plan,
)
from satquery.platform.contracts import EarthQuery


def test_client_exposes_versioned_capability_and_earth_query_calls():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"accepted": True})

    with SatQueryClient(
        "https://satquery.example", transport=httpx.MockTransport(respond)
    ) as client:
        assert client.api_version == CLIENT_API_VERSION == "1"
        assert client.capability_matrix() == {"accepted": True}
        assert client.plan_earth(
            EarthQuery(requested_variables=("air_temperature",)), explain=True
        ) == {"accepted": True}

    assert calls[0].method == "GET"
    assert calls[0].url.path == "/api/v1/platform/earth/capabilities"
    assert calls[1].method == "POST"
    assert calls[1].url.path == "/api/v1/platform/earth/plan/explain"
    payload = json.loads(calls[1].content)
    assert payload["requested_variables"] == ["air_temperature"]
    assert payload["crs"] == "OGC:CRS84"


def test_legacy_earth_commands_share_platform_plan_and_observe_handlers():
    parser = build_parser()
    earth_plan = parser.parse_args(["earth", "plan", "query.json"])
    root_plan = parser.parse_args(["plan", "query.json"])
    earth_observe = parser.parse_args(["earth", "observe", "query.json"])
    root_observe = parser.parse_args(["observe", "query.json"])

    assert earth_plan.func is root_plan.func is command_platform_plan
    assert earth_plan.explain is False
    assert earth_observe.func is root_observe.func is command_platform_observe


def test_client_encodes_user_supplied_resource_identifiers():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    with SatQueryClient(transport=httpx.MockTransport(respond)) as client:
        client.investigation_report("case/with?reserved=value")

    assert requests[0].url.raw_path.endswith(b"/case%2Fwith%3Freserved%3Dvalue/report")


def test_client_preserves_api_error_payload_and_retry_semantics():
    body = {
        "detail": "Revision conflict",
        "remediation": ["Refresh the schedule first."],
    }

    def respond(_request):
        return httpx.Response(409, json=body)

    with (
        SatQueryClient(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(PlatformAPIError) as raised,
    ):
        client.patch("/api/v1/platform/monitoring/schedules/schedule-1", payload={})

    error = raised.value
    assert error.message == "Revision conflict"
    assert error.status_code == 409
    assert error.recoverable is False
    assert error.remediation == ["Refresh the schedule first."]
    assert error.payload == body
    assert error.context["method"] == "PATCH"


def test_client_marks_transport_failures_recoverable_without_retrying():
    calls = 0

    def fail(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    with (
        SatQueryClient(transport=httpx.MockTransport(fail)) as client,
        pytest.raises(PlatformAPIError) as raised,
    ):
        client.health()

    assert calls == 1
    assert raised.value.recoverable is True
    assert raised.value.context["method"] == "GET"


def test_sdk_resource_groups_share_transport_and_cover_platform_workflows():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    with SatQueryClient(transport=httpx.MockTransport(respond)) as client:
        client.platform.modalities()
        client.platform.probe_connector("connector/one")
        client.platform.search_datasets("surface water")
        client.earth.observe(EarthQuery(requested_variables=("precipitation",)))
        client.missions.create({"name": "mission"})
        client.missions.investigations("mission-1")
        client.investigations.start("Review rainfall", mission_id="mission-1")
        client.investigations.design({"question": "Review rainfall"})
        client.investigations.execute("investigation-1")
        client.investigations.method_sufficiency(
            "investigation-1", "method/one", "1.0", {"earth_query": {}}
        )
        client.monitoring.event_page(schedule_id="schedule-1", limit=25)
        client.monitoring.run_due(limit=5)
        client.objects.materialize("investigation-1", {"identity_value": "x"})
        client.objects.graph(investigation_id="investigation-1")
        client.memory.search({"terms": ["rainfall"]})
        client.science.methods(domain="hydrology")

    assert [request.method for request in requests] == [
        "GET",
        "POST",
        "GET",
        "POST",
        "POST",
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "POST",
        "POST",
        "GET",
        "POST",
        "GET",
    ]
    assert requests[1].url.raw_path.endswith(
        b"/connectors/connector%2Fone/health-check"
    )
    assert str(requests[2].url.params) == "q=surface+water"
    assert requests[3].url.path == "/api/v1/platform/earth/observe"
    assert requests[6].url.path == "/api/v1/platform/investigate"
    assert str(requests[10].url.params) == "schedule_id=schedule-1&limit=25"
    assert str(requests[15].url.params) == "domain=hydrology"


def test_existing_client_helpers_delegate_to_canonical_resource_groups():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    with SatQueryClient(transport=httpx.MockTransport(respond)) as client:
        client.capability_matrix()
        client.earth_memory_search({"terms": ["flood"]})
        client.investigation_report("investigation-1")

    assert [request.url.path for request in requests] == [
        "/api/v1/platform/earth/capabilities",
        "/api/v1/platform/earth-memory/search",
        "/api/v1/platform/investigations/investigation-1/report",
    ]


@pytest.mark.parametrize(
    "path", ["https://elsewhere.example/x", "//elsewhere.example/x", "relative"]
)
def test_client_rejects_non_api_paths(path):
    client = SatQueryClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    try:
        with pytest.raises(ValueError, match="absolute API path"):
            client.get(path)
    finally:
        client.close()


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://satquery.example",
        "https://user:password@satquery.example",
        "https://satquery.example?debug=true",
    ],
)
def test_client_rejects_invalid_or_credential_bearing_base_urls(base_url):
    with pytest.raises(ValueError, match="base_url must"):
        SatQueryClient(base_url)
