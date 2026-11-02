import json

import httpx
import pytest

from earth_platform.engine.errors import EngineUnavailableError
from earth_platform.engine.http import HttpEngineClient
from earth_platform.engine.models import (
    EngineAgentImage,
    EngineDatasetMetadata,
    EngineImageCapability,
    EngineMissionCreate,
    EngineMonitoringScheduleCreate,
)
from earth_platform.settings.models import EngineSettings
from earth_platform.shared.errors import ConflictError, ValidationFailedError


@pytest.mark.asyncio
async def test_http_engine_client_reads_agent_sse_and_forwards_authorization(monkeypatch):
    requested: list[httpx.Request] = []
    monkeypatch.setenv("TEST_ENGINE_KEY", "test-token")

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.url.path.endswith("/turns"):
            event = {
                "kind": "assistant.delta",
                "session_id": "agent-1",
                "turn_id": "turn-1",
                "sequence": 1,
                "timestamp": "2026-05-01T10:00:00Z",
                "payload": {"text": "hello"},
            }
            return httpx.Response(
                200,
                content=f"event: assistant.delta\nid: turn-1:1\ndata: {json.dumps(event)}\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json={"session_id": "agent-1"})

    client = HttpEngineClient(
        EngineSettings(
            kind="http",
            base_url="https://engine.test",
            api_key_env="TEST_ENGINE_KEY",
        ),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        streamed = [
            event
            async for event in client.stream_agent_turn(
                "agent-1",
                message="question",
                model_id="registered-model",
                execution_authorized=True,
            )
        ]
    finally:
        await client.aclose()

    assert len(streamed) == 1
    assert streamed[0].kind == "assistant.delta"
    assert streamed[0].payload == {"text": "hello"}
    assert requested[0].headers["authorization"] == "Bearer test-token"
    assert json.loads(requested[0].content) == {
        "message": "question",
        "model_id": "registered-model",
        "execution_authorized": True,
    }


@pytest.mark.asyncio
async def test_http_engine_client_forwards_image_attachment_separately():
    requested: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        event = {
            "kind": "turn.completed",
            "session_id": "agent-1",
            "turn_id": "turn-1",
            "sequence": 1,
            "timestamp": "2026-05-01T10:00:00Z",
            "payload": {},
        }
        return httpx.Response(
            200,
            content=f"data: {json.dumps(event)}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    image = EngineAgentImage(
        asset_id="platform-image",
        mime_type="image/png",
        size_bytes=3,
        sha256="a" * 64,
        data_base64="aW1n",
    )
    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        events = [
            item
            async for item in client.stream_agent_turn(
                "agent-1",
                message="Describe image",
                model_id="vision-model",
                attachments=[image],
            )
        ]
    finally:
        await client.aclose()

    body = json.loads(requested[0].content)
    assert body["message"] == "Describe image"
    assert body["attachments"] == [image.model_dump(mode="json")]
    assert events[0].kind == "turn.completed"


@pytest.mark.asyncio
async def test_http_engine_client_surfaces_engine_image_validation_errors():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": "validation_error",
                "detail": "Reasoning model does not support image attachments.",
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(ValidationFailedError, match="does not support image"):
            _ = [
                event
                async for event in client.stream_agent_turn(
                    "agent-1",
                    message="Describe image",
                    model_id="text-model",
                    attachments=[
                        EngineAgentImage(
                            asset_id="platform-image",
                            mime_type="image/png",
                            size_bytes=3,
                            sha256="a" * 64,
                            data_base64="aW1n",
                        )
                    ],
                )
            ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_preserves_monitoring_comparison_conflict():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": "At least two completed investigations are required."},
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(ConflictError, match="At least two completed"):
            await client.compare_monitoring_schedule("schedule-1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_reads_registered_datasets_and_image_capabilities():
    requested: list[httpx.Request] = []
    dataset = {
        "connector_id": "stac",
        "dataset_id": "landsat",
        "provider": "USGS",
        "variables": ["red", "green"],
        "units": {},
        "modalities": ["optical"],
        "capabilities": ["earth_observation_catalog"],
        "temporal_coverage": {
            "start": "2020-01-01T00:00:00Z",
            "end": "2025-01-01T00:00:00Z",
        },
    }
    image_capability = {
        "tool": "caption",
        "intent": "CAPTION",
        "description": "Describe an image.",
        "requires_images": 1,
        "backend_preference": ["practical"],
        "available": True,
        "unavailable_reason": None,
    }
    agent_tool = {
        "tool_id": "investigation.execute",
        "description": "Execute a SatQuery investigation.",
        "input_schema": {
            "type": "object",
            "properties": {"investigation_id": {"type": "string"}},
            "required": ["investigation_id"],
        },
        "availability": "available",
        "requires_execution_authorization": True,
        "model_visible_without_consent": False,
        "model_visible_with_execution_consent": True,
    }
    earth_capabilities = {
        "revision": "a" * 64,
        "modalities": [
            {
                "modality_id": "optical",
                "label": "Optical",
                "description": "Passive optical imagery.",
                "status": "registered",
                "implementation_ids": ["landsat"],
                "dataset_ids": ["landsat-9"],
                "variables": ["red", "green", "blue"],
            }
        ],
        "snapshot_sha256": "b" * 64,
        "snapshot_schema_version": "1.0.0",
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.url.path.endswith("/platform/datasets"):
            return httpx.Response(200, json=[dataset])
        if request.url.path.endswith("/platform/earth/capabilities"):
            return httpx.Response(200, json=earth_capabilities)
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json=[image_capability])
        if request.url.path.endswith("/agent/tools"):
            return httpx.Response(200, json=[agent_tool])
        raise AssertionError(f"Unexpected Engine request: {request.url}")

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        datasets = await client.list_engine_datasets()
        capabilities = await client.list_engine_image_capabilities()
        earth_matrix = await client.get_engine_earth_capabilities()
        agent_tools = await client.list_engine_agent_tools()
    finally:
        await client.aclose()

    assert [request.url.path for request in requested] == [
        "/api/v1/platform/datasets",
        "/api/v1/capabilities",
        "/api/v1/platform/earth/capabilities",
        "/api/v1/agent/tools",
    ]
    assert datasets == [EngineDatasetMetadata.model_validate(dataset)]
    assert capabilities == [EngineImageCapability.model_validate(image_capability)]
    assert earth_matrix.modalities[0].modality_id == "optical"
    assert agent_tools[0].tool_id == "investigation.execute"
    assert agent_tools[0].model_visible_without_consent is False


@pytest.mark.asyncio
async def test_http_engine_client_rejects_malformed_earth_capability_snapshot():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "revision": "invalid",
                "modalities": [],
                "snapshot_sha256": "invalid",
                "snapshot_schema_version": "1.0.0",
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(
            EngineUnavailableError, match="invalid Earth capability snapshot"
        ):
            await client.get_engine_earth_capabilities()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_rejects_malformed_engine_dataset_metadata():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"dataset_id": "missing-required-fields"}])

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(EngineUnavailableError, match="invalid dataset metadata list"):
            await client.list_engine_datasets()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_rejects_malformed_agent_tool_descriptor():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"tool_id": "missing-fields"}])

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(
            EngineUnavailableError, match="invalid Agent tool descriptor list"
        ):
            await client.list_engine_agent_tools()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_manages_missions_and_monitoring_schedules():
    timestamp = "2026-11-02T10:00:00Z"
    requests: list[httpx.Request] = []
    mission = {
        "mission_id": "mission-1",
        "name": "Coastal change",
        "objective": "Monitor shoreline change",
        "status": "active",
        "created_at": timestamp,
        "finished_at": None,
        "metadata": {},
    }
    query = {
        "bbox": [-123, 36, -121, 38],
        "point": None,
        "geometry": None,
        "temporal_start": None,
        "temporal_end": None,
        "crs": "OGC:CRS84",
        "spatial_resolution": None,
        "resolution_unit": None,
        "requested_dataset_ids": [],
        "requested_variables": ["shoreline"],
        "requested_modalities": [],
        "required_capabilities": [],
        "region": None,
        "filters": {},
        "asset_preferences": [],
        "asset_sampling": None,
        "raster_analysis": None,
        "raster_pixel_selection": None,
        "raster_weighting": None,
        "raster_semantics": {},
        "raster_component_extraction": [],
    }
    schedule = {
        "schedule_id": "schedule-1",
        "mission_id": "mission-1",
        "name": "Daily shoreline check",
        "earth_query": query,
        "interval_seconds": 86400,
        "rolling_window_seconds": 3600,
        "priority": 0,
        "overlap_policy": "skip_while_running",
        "trigger_policies": [],
        "enabled": True,
        "next_run_at": timestamp,
        "created_at": timestamp,
        "updated_at": timestamp,
        "revision": 1,
    }
    run = {
        "run_id": "run-1",
        "schedule_id": "schedule-1",
        "schedule_revision": 1,
        "mission_id": "mission-1",
        "scheduled_at": timestamp,
        "started_at": timestamp,
        "effective_temporal_start": "2026-04-30T10:00:00Z",
        "effective_temporal_end": timestamp,
        "finished_at": timestamp,
        "status": "completed",
        "investigation_id": "investigation-1",
        "execution_id": "execution-1",
        "missed_intervals": 0,
        "failure_type": None,
        "worker_id": "worker-1",
        "lease_expires_at": None,
    }
    comparison = {
        "comparison_id": "comparison-1",
        "comparison_sha256": "b" * 64,
        "limitations": ["descriptive alignment only"],
        "markdown": "## Comparison\nNo inference.",
    }
    notification = {
        "notification_id": "notification-1",
        "event_id": "event-1",
        "schedule_id": "schedule-1",
        "run_id": "run-1",
        "severity": "warning",
        "title": "Partial monitoring run",
        "detail": "One observation was unavailable.",
        "status": "unread",
        "created_at": timestamp,
        "acknowledged_at": None,
    }
    trigger_history = {
        "schedule_id": "schedule-1",
        "schedule_revision": 1,
        "policies": [],
        "events": [
            {
                "event_id": "trigger-event-1",
                "event_type": "trigger_matched",
                "schedule_id": "schedule-1",
                "run_id": "run-1",
                "occurred_at": timestamp,
                "payload": {"policy_name": "High shoreline change"},
            }
        ],
        "next_cursor": None,
        "has_more": False,
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/missions") and request.method == "GET":
            return httpx.Response(200, json=[mission])
        if request.url.path.endswith("/missions") and request.method == "POST":
            return httpx.Response(201, json=mission)
        if request.url.path.endswith("/monitoring/schedules") and request.method == "GET":
            return httpx.Response(200, json=[schedule])
        if request.url.path.endswith("/monitoring/schedules") and request.method == "POST":
            return httpx.Response(201, json=schedule)
        if request.url.path.endswith("/schedule-1/enable"):
            return httpx.Response(200, json=schedule)
        if request.url.path.endswith("/schedule-1/runs"):
            return httpx.Response(200, json=[run])
        if request.url.path.endswith("/schedule-1/comparison"):
            return httpx.Response(200, json=comparison)
        if request.url.path.endswith("/monitoring/notifications") and request.method == "GET":
            return httpx.Response(200, json=[notification])
        if request.url.path.endswith("/notification-1/acknowledge"):
            return httpx.Response(
                200,
                json={**notification, "status": "acknowledged", "acknowledged_at": timestamp},
            )
        if request.url.path.endswith("/schedule-1/triggers"):
            return httpx.Response(200, json=trigger_history)
        raise AssertionError(f"Unexpected Engine request: {request.method} {request.url}")

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        missions = await client.list_missions()
        created_mission = await client.create_mission(
            EngineMissionCreate(name="Coastal change", objective="Monitor shoreline change")
        )
        schedules = await client.list_monitoring_schedules()
        created_schedule = await client.create_monitoring_schedule(
            EngineMonitoringScheduleCreate(
                mission_id="mission-1",
                name="Daily shoreline check",
                earth_query={"bbox": [-123, 36, -121, 38], "requested_variables": ["shoreline"]},
                interval_seconds=86400,
                rolling_window_seconds=900,
            )
        )
        enabled_schedule = await client.set_monitoring_schedule_enabled("schedule-1", True)
        runs = await client.list_monitoring_runs("schedule-1")
        compared = await client.compare_monitoring_schedule("schedule-1", limit=3)
        notifications = await client.list_monitoring_notifications(unread_only=True)
        acknowledged = await client.acknowledge_monitoring_notification("notification-1")
        trigger_events = await client.get_monitoring_triggers("schedule-1")
    finally:
        await client.aclose()

    assert missions[0].mission_id == created_mission.mission_id == "mission-1"
    assert schedules[0].schedule_id == created_schedule.schedule_id == "schedule-1"
    assert enabled_schedule.enabled is True
    assert runs[0].investigation_id == "investigation-1"
    assert compared.comparison_sha256 == "b" * 64
    assert compared.markdown == "## Comparison\nNo inference."
    assert notifications[0].status == "unread"
    assert acknowledged.status == "acknowledged"
    assert trigger_events.events[0].event_type == "trigger_matched"
    schedule_post = next(
        request for request in requests
        if request.method == "POST" and request.url.path.endswith("/monitoring/schedules")
    )
    assert json.loads(schedule_post.content)["earth_query"]["bbox"] == [-123, 36, -121, 38]
    assert json.loads(schedule_post.content)["rolling_window_seconds"] == 900


@pytest.mark.asyncio
async def test_http_engine_client_reports_rejected_agent_session():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"message": "agent service unavailable"}},
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(EngineUnavailableError, match="agent service unavailable"):
            await client.create_agent_session()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_health_uses_engine_readiness_and_preserves_base_path():
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(
            200,
            json={"ready": False, "version": "1.2.3", "status": "degraded"},
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        health = await client.health()
    finally:
        await client.aclose()

    assert health.status == "degraded"
    assert health.version == "1.2.3"
    assert requested == ["/proxy/api/v1/health"]


@pytest.mark.asyncio
async def test_http_engine_client_reads_investigation_report_and_checks_identity():
    requested: list[str] = []
    report_sha256 = "a" * 64

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "report_id": "report-1",
                "report_sha256": report_sha256,
                "investigation": {"investigation_id": "investigation-1"},
                "markdown": "# Investigation report",
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        report = await client.get_investigation_report("investigation-1")
    finally:
        await client.aclose()

    assert report.report_id == "report-1"
    assert report.report_sha256 == report_sha256
    assert report.investigation_id == "investigation-1"
    assert report.markdown == "# Investigation report"
    assert requested == [
        "/proxy/api/v1/platform/investigations/investigation-1/report"
    ]


@pytest.mark.asyncio
async def test_http_engine_client_rejects_mismatched_investigation_report():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "report_id": "report-1",
                "report_sha256": "a" * 64,
                "investigation": {"investigation_id": "other-investigation"},
                "markdown": "# Investigation report",
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(EngineUnavailableError, match="invalid investigation report"):
            await client.get_investigation_report("investigation-1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_reads_only_exported_wgs84_earth_objects():
    requested: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "object-1",
                        "geometry": {"type": "Point", "coordinates": [10, 20]},
                        "properties": {"evidence_ids": ["evidence-1"]},
                    }
                ],
                "satquery:omitted_objects": [
                    {"object_id": "object-2", "reason": "crs_not_supported_for_geojson"}
                ],
                "satquery:geometry_policy": "WGS 84 longitude/latitude only",
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        collection = await client.get_investigation_earth_objects("investigation-1")
    finally:
        await client.aclose()

    assert collection.type == "FeatureCollection"
    assert collection.features[0].id == "object-1"
    assert collection.omitted_objects[0].reason == "crs_not_supported_for_geojson"
    assert collection.geometry_policy == "WGS 84 longitude/latitude only"
    assert requested[0].url.path == "/proxy/api/v1/platform/earth-objects/geojson"
    assert requested[0].url.params["investigation_id"] == "investigation-1"


@pytest.mark.asyncio
async def test_http_engine_client_reads_session_scoped_investigation_events():
    requested: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={
                "investigation_id": "investigation-1",
                "plan_id": "plan-1",
                "events": [
                    {
                        "sequence": 3,
                        "plan_id": "plan-1",
                        "event_type": "task.completed",
                        "timestamp": "2026-05-01T10:00:00Z",
                        "payload": {"task_id": "acquire"},
                        "previous_event_sha256": "a" * 64,
                        "event_sha256": "b" * 64,
                    }
                ],
                "next_sequence": 3,
                "has_more": False,
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        page = await client.get_investigation_events(
            "agent/session",
            "investigation-1",
            after_sequence=2,
            limit=10,
        )
    finally:
        await client.aclose()

    assert page.events[0].event_type == "task.completed"
    assert page.next_sequence == 3
    assert requested[0].url.raw_path.split(b"?")[0] == (
        b"/api/v1/agent/sessions/agent%2Fsession/investigations/"
        b"investigation-1/events"
    )
    assert dict(requested[0].url.params) == {"after_sequence": "2", "limit": "10"}
