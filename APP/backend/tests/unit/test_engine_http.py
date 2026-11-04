import hashlib
import json

import httpx
import pytest

from earth_platform.engine.errors import EngineUnavailableError
from earth_platform.engine.http import HttpEngineClient
from earth_platform.engine.models import (
    EngineAgentImage,
    EngineDatasetMetadata,
    EngineHypothesisCreateRequest,
    EngineHypothesisTransitionRequest,
    EngineImageCapability,
    EngineInvestigationComparisonRequest,
    EngineInvestigationReproducibilityBundle,
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
async def test_http_engine_client_forwards_typed_hypothesis_lifecycle_requests():
    requested: list[httpx.Request] = []
    timestamp = "2026-05-01T10:00:00Z"
    hypothesis = {
        "hypothesis_id": "hypothesis-1",
        "version": 1,
        "proposition": "The shoreline moved inland.",
        "source_text": "Researcher's declared proposition",
        "origin": "explicit",
        "lifecycle": "proposed",
        "competing_group_id": None,
        "parent_hypothesis_ids": [],
        "composition": None,
        "metadata": {},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "status": "available",
                    "graph": {"hypotheses": [hypothesis]},
                    "events": [],
                    "restoration_error": None,
                },
            )
        is_transition = request.url.path.endswith("/transitions")
        result_hypothesis = (
            {**hypothesis, "version": 2, "lifecycle": "active"} if is_transition else hypothesis
        )
        event = {
            "event_id": "event-1",
            "hypothesis_id": "hypothesis-1",
            "prior_version": 1 if is_transition else 0,
            "version": 2 if is_transition else 1,
            "from_status": "proposed" if is_transition else None,
            "to_status": "active" if is_transition else "proposed",
            "actor": "Researcher",
            "rationale": "Begin review" if is_transition else "Record the proposed explanation",
            "occurred_at": timestamp,
        }
        return httpx.Response(
            200 if is_transition else 201,
            json={
                "hypothesis": result_hypothesis,
                "events": [event],
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        lifecycle = await client.get_investigation_hypotheses("investigation/1")
        created = await client.add_investigation_hypothesis(
            "investigation/1",
            EngineHypothesisCreateRequest(
                hypothesis_id="hypothesis-1",
                proposition=hypothesis["proposition"],
                source_text=hypothesis["source_text"],
                origin="explicit",
                actor="Researcher",
                rationale="Record the proposed explanation",
            ),
        )
        transitioned = await client.transition_investigation_hypothesis(
            "investigation/1",
            "hypothesis-1",
            EngineHypothesisTransitionRequest(
                expected_version=1,
                status="active",
                actor="Researcher",
                rationale="Begin review",
            ),
        )
    finally:
        await client.aclose()

    assert lifecycle.status == "available"
    assert lifecycle.graph is not None
    assert lifecycle.graph.hypotheses[0].lifecycle == "proposed"
    assert created.hypothesis.hypothesis_id == "hypothesis-1"
    assert transitioned.hypothesis.version == 2
    assert [request.url.raw_path for request in requested] == [
        b"/api/v1/platform/investigations/investigation%2F1/hypotheses",
        b"/api/v1/platform/investigations/investigation%2F1/hypotheses",
        b"/api/v1/platform/investigations/investigation%2F1/hypotheses/hypothesis-1/transitions",
    ]
    assert json.loads(requested[1].content)["actor"] == "Researcher"
    assert json.loads(requested[2].content) == {
        "expected_version": 1,
        "status": "active",
        "actor": "Researcher",
        "rationale": "Begin review",
    }


@pytest.mark.asyncio
async def test_http_engine_client_preserves_unavailable_hypothesis_lifecycle_status():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "status": "unavailable",
                "graph": None,
                "events": [],
                "restoration_error": "Lifecycle journal could not be restored",
            },
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        lifecycle = await client.get_investigation_hypotheses("investigation-1")
    finally:
        await client.aclose()

    assert lifecycle.status == "unavailable"
    assert lifecycle.restoration_error == "Lifecycle journal could not be restored"


@pytest.mark.asyncio
async def test_http_engine_client_creates_and_restores_typed_investigation_comparisons():
    digest = "a" * 64
    comparison = {
        "comparison_id": f"investigation-comparison:{digest[:20]}",
        "comparison_sha256": digest,
        "schema_version": "1.2",
        "stack_builder_version": "1.1.0",
        "temporal_method_id": "satquery.temporal.consecutive-difference",
        "temporal_method_version": "1.0.0",
        "investigation_reports": [],
        "measurement_groups": [
            {
                "canonical_variable": "earth:surface_water_level",
                "unit": "m",
                "records": [],
                "investigation_ids": ["investigation-1", "investigation-2"],
                "coverage": "present_in_all_selected_investigations",
                "interpretation": "Descriptive alignment only.",
            }
        ],
        "observation_stacks": [],
        "temporal_diagnostics": [],
        "alignment_issues": [],
        "temporal_issues": [],
        "observation_identity_conflicts": [],
        "unmatched_observation_ids": [],
        "limitations": ["No scientific conclusions are generated."],
        "markdown": "# Engine comparison",
    }
    requested: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=comparison)
        return httpx.Response(200, json=comparison)

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        created = await client.create_investigation_comparison(
            EngineInvestigationComparisonRequest(
                investigation_ids=["investigation-1", "investigation-2"]
            )
        )
        restored = await client.get_investigation_comparison(digest)
    finally:
        await client.aclose()

    assert created.comparison_id == restored.comparison_id
    assert created.measurement_groups[0].canonical_variable == "earth:surface_water_level"
    assert [request.url.path for request in requested] == [
        "/api/v1/platform/investigation-comparisons",
        f"/api/v1/platform/investigation-comparisons/{digest}",
    ]
    assert json.loads(requested[0].content) == {
        "investigation_ids": ["investigation-1", "investigation-2"]
    }


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
        with pytest.raises(EngineUnavailableError, match="invalid Earth capability snapshot"):
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
        with pytest.raises(EngineUnavailableError, match="invalid Agent tool descriptor list"):
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
        request
        for request in requests
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
    assert requested == ["/proxy/api/v1/platform/investigations/investigation-1/report"]


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
async def test_http_engine_client_reads_engine_reasoning_report():
    requested: list[str] = []
    report = {
        "reasoning_id": "reasoning-1",
        "investigation_id": "investigation-1",
        "engine_id": "scientific-reasoning",
        "engine_version": "1.0",
        "status": "evaluated",
        "findings": [
            {
                "finding_id": "finding-1",
                "rule_id": "shoreline-change",
                "rule_version": "1",
                "statement": "Observed evidence supports the hypothesis.",
                "hypothesis_statement": "The shoreline moved inland.",
                "evidential_relation": "supports",
                "observation_ids": ["observation-1"],
            }
        ],
        "sufficiency": {
            "status": "method_inputs_satisfied",
            "explanation": "The declared method inputs are available.",
        },
        "conclusion": {
            "status": "findings_available",
            "explanation": "The registered method produced a finding.",
        },
        "limitations": ["The report does not quantify confidence."],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, json=report)

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        reasoning = await client.get_investigation_reasoning("investigation-1")
    finally:
        await client.aclose()

    assert reasoning.status == "evaluated"
    assert reasoning.reasoning is not None
    assert reasoning.reasoning.findings[0].observation_ids == ["observation-1"]
    assert reasoning.reasoning.conclusion.explanation == "The registered method produced a finding."
    assert requested == ["/proxy/api/v1/platform/investigations/investigation-1/reasoning"]


@pytest.mark.asyncio
async def test_http_engine_client_preserves_not_evaluated_reasoning_state():
    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"status": "not_evaluated", "reasoning": None}
            )
        ),
    )
    await client.connect()
    try:
        reasoning = await client.get_investigation_reasoning("investigation-1")
    finally:
        await client.aclose()

    assert reasoning.status == "not_evaluated"
    assert reasoning.reasoning is None


@pytest.mark.asyncio
async def test_http_engine_client_rejects_mismatched_investigation_reasoning():
    report = {
        "reasoning_id": "reasoning-1",
        "investigation_id": "other-investigation",
        "engine_id": "scientific-reasoning",
        "engine_version": "1.0",
        "status": "not_evaluable",
        "findings": [],
        "sufficiency": {"status": "not_assessable", "explanation": "No method registered."},
        "conclusion": {"status": "unresolved", "explanation": "No evaluated findings."},
    }
    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=report)),
    )
    await client.connect()
    try:
        with pytest.raises(EngineUnavailableError, match="invalid investigation reasoning"):
            await client.get_investigation_reasoning("investigation-1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_reads_and_validates_reproducibility_bundle():
    requested: list[str] = []
    bundle = {
        "schema_version": "1.4.0",
        "bundle_id": "repro-1",
        "investigation_id": "investigation-1",
        "artifact_hashes": {"observations": "a" * 64},
        "bundle_sha256": "b" * 64,
        "exported_at": "2026-11-04T10:00:00Z",
    }
    export_model = EngineInvestigationReproducibilityBundle.model_validate(bundle)
    canonical_payload = json.dumps(
        export_model.model_dump(
            mode="json", exclude={"bundle_sha256", "exported_at"}
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
        allow_nan=False,
    )
    bundle["bundle_sha256"] = hashlib.sha256(
        canonical_payload.encode("utf-8")
    ).hexdigest()

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, json=bundle)

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        result = await client.get_investigation_reproducibility("investigation-1")
    finally:
        await client.aclose()

    assert result.bundle_id == "repro-1"
    assert result.artifact_hashes == {"observations": "a" * 64}
    assert result.observations == []
    assert requested == ["/proxy/api/v1/platform/investigations/investigation-1/reproducibility"]


@pytest.mark.asyncio
async def test_http_engine_client_rejects_modified_reproducibility_bundle():
    bundle = {
        "schema_version": "1.4.0",
        "bundle_id": "repro-1",
        "investigation_id": "investigation-1",
        "observations": [{"observation_id": "changed-after-hashing"}],
        "artifact_hashes": {},
        "bundle_sha256": "b" * 64,
        "exported_at": "2026-11-04T10:00:00Z",
    }
    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=bundle)
        ),
    )
    await client.connect()
    try:
        with pytest.raises(
            EngineUnavailableError,
            match="invalid investigation reproducibility bundle",
        ):
            await client.get_investigation_reproducibility("investigation-1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_rejects_mismatched_reproducibility_bundle():
    bundle = {
        "schema_version": "1.4.0",
        "bundle_id": "repro-1",
        "investigation_id": "other-investigation",
        "artifact_hashes": {},
        "bundle_sha256": "b" * 64,
        "exported_at": "2026-11-04T10:00:00Z",
    }
    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=bundle)),
    )
    await client.connect()
    try:
        with pytest.raises(
            EngineUnavailableError,
            match="invalid investigation reproducibility bundle",
        ):
            await client.get_investigation_reproducibility("investigation-1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_client_reads_typed_investigation_observations():
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(
            200,
            json=[
                {
                    "observation_id": "observation-1",
                    "source_id": "source-1",
                    "dataset": {
                        "connector_id": "connector-1",
                        "dataset_id": "dataset-1",
                    },
                    "observed_at": "2026-05-01T10:00:00Z",
                    "provenance": {"citation": "Engine source record"},
                }
            ],
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        observations = await client.get_investigation_observations("investigation-1")
    finally:
        await client.aclose()

    assert len(observations) == 1
    assert observations[0].observation_id == "observation-1"
    assert observations[0].dataset is not None
    assert observations[0].dataset.dataset_id == "dataset-1"
    assert observations[0].provenance == {"citation": "Engine source record"}
    assert requested == ["/proxy/api/v1/platform/investigations/investigation-1/observations"]


@pytest.mark.asyncio
async def test_http_engine_client_rejects_invalid_investigation_observations():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"observation_id": "", "confidence": 2}],
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(EngineUnavailableError, match="invalid investigation observation list"):
            await client.get_investigation_observations("investigation-1")
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
        b"/api/v1/agent/sessions/agent%2Fsession/investigations/investigation-1/events"
    )
    assert dict(requested[0].url.params) == {"after_sequence": "2", "limit": "10"}
