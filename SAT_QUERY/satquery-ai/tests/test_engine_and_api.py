"""End-to-end orchestration and the HTTP surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from satquery.api import create_app, set_engine
from satquery.errors import QueryError, ResourceNotConfiguredError
from satquery.orchestrator import SatQueryEngine
from satquery.schemas import BackendKind, Intent, Modality, StepStatus, ToolName

from conftest import make_scene, make_sar_scene, to_png_bytes


@pytest.fixture
def engine(settings, vision) -> SatQueryEngine:
    """An engine whose vision suite is the pixel-derived double."""
    built = SatQueryEngine(settings)
    built.vision_suite = lambda: vision  # type: ignore[assignment]
    return built


@pytest.fixture
def client(engine, settings):
    set_engine(engine)
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    set_engine(None)


def upload(name="scene.png", **kwargs):
    return (name, to_png_bytes(make_scene(**kwargs)))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def test_caption_request_runs_end_to_end(engine):
    response = engine.answer(
        "Describe this scene in detail",
        uploads=[upload(water_box=(0, 0, 150, 150))],
    )

    assert response.intent is Intent.CAPTION
    assert response.tools_used[0] is ToolName.CAPTION
    assert response.answer
    assert response.latency_ms > 0
    assert response.request_id.startswith("sq-")
    assert len(response.images) == 1
    assert response.images[0].modality is Modality.OPTICAL


def test_trace_records_every_stage_in_order(engine):
    response = engine.answer("Where is the water?", uploads=[upload(water_box=(0, 0, 150, 150))])

    steps = [step.step for step in response.trace]
    assert steps[0] == "ingest"
    assert steps[1] == "backend_selection"
    assert steps[2] == "intent_router"
    assert any(step.startswith("tool.grounding") for step in steps)
    assert steps[-1] == "answer_composer"
    assert all(step.status is StepStatus.OK for step in response.trace)
    assert all(step.latency_ms >= 0 for step in response.trace)


def test_nested_tool_calls_appear_in_the_trace(engine):
    response = engine.answer(
        "How many water bodies are visible?", uploads=[upload(water_box=(0, 0, 150, 150))]
    )

    nested = [step.step for step in response.trace if "(nested)" in step.step]
    assert any("grounding" in step for step in nested)
    assert ToolName.COUNTING in response.tools_used
    assert ToolName.GROUNDING in response.tools_used


def test_grounding_response_carries_regions(engine):
    response = engine.answer(
        "Where is the water?", uploads=[upload(water_box=(0, 0, 150, 150))]
    )

    assert response.intent is Intent.GROUNDING
    regions = response.results[0].regions
    assert regions
    assert 0.0 <= regions[0].box.x0 < regions[0].box.x1 <= 1.0
    assert regions[0].box.pixel_box[2] > regions[0].box.pixel_box[0]


def test_change_detection_across_two_uploads(engine):
    before = ("t1.png", to_png_bytes(make_scene(vegetation_box=(0, 0, 384, 384))))
    after = (
        "t2.png",
        to_png_bytes(make_scene(vegetation_box=(0, 0, 384, 384), urban_box=(20, 20, 180, 180))),
    )

    response = engine.answer("What changed between these two images?", uploads=[before, after])

    assert response.intent is Intent.CHANGE_DETECTION
    assert len(response.images) == 2
    assert response.results[0].data["fused"]["changed_ratio"] >= 0.0


def test_change_query_with_one_image_says_so_rather_than_failing(engine):
    with pytest.raises(QueryError) as excinfo:
        engine.answer("What changed here?", uploads=[upload()])
    assert "at least 2" in excinfo.value.message


def test_request_without_an_image_is_refused(engine):
    with pytest.raises(QueryError) as excinfo:
        engine.answer("Describe the scene")
    assert "No image" in excinfo.value.message
    assert excinfo.value.remediation


def test_modality_hint_is_applied_to_every_image(engine):
    response = engine.answer(
        "Is this optical or SAR?", uploads=[upload()], modality_hint=Modality.SAR
    )
    assert response.images[0].modality is Modality.SAR
    assert response.results[0].data["explicit_hint_applied"] is True


def test_sar_imagery_is_detected_without_a_hint(engine):
    response = engine.answer(
        "What sensor produced this?", uploads=[("sar.png", to_png_bytes(make_sar_scene()))]
    )
    assert response.images[0].modality is Modality.SAR
    assert response.intent is Intent.MODALITY_ANALYSIS


def test_force_tool_overrides_the_router(engine):
    response = engine.answer(
        "Describe this scene",
        uploads=[upload(water_box=(0, 0, 150, 150))],
        force_tool=ToolName.SCENE,
    )
    assert response.plan.router == "forced"
    assert response.tools_used == [ToolName.SCENE]


def test_trace_can_be_suppressed(engine):
    response = engine.answer("Describe this", uploads=[upload()], include_trace=False)
    assert response.trace == []


def test_downsampling_is_surfaced_as_a_warning(engine):
    response = engine.answer(
        "Describe this", uploads=[upload(width=900, height=900)]
    )
    assert any("downsampled" in warning for warning in response.warnings)
    assert "Notes:" in response.answer


def test_engine_refuses_when_no_vision_backend_exists(settings, monkeypatch):
    missing = {name: {"installed": False, "version": None} for name in (
        "torch", "transformers", "PIL", "numpy", "httpx", "accelerate", "sentencepiece"
    )}
    monkeypatch.setattr("satquery.registry.probe_dependencies", lambda: missing)
    bare = SatQueryEngine(settings)
    with pytest.raises(ResourceNotConfiguredError) as excinfo:
        bare.answer("Describe this scene", uploads=[upload()])

    assert "will not guess" in excinfo.value.message
    assert any("pip install torch transformers" in line for line in excinfo.value.remediation)


def test_capabilities_reflect_backend_availability(engine, monkeypatch):
    missing = {name: {"installed": False, "version": None} for name in (
        "torch", "transformers", "PIL", "numpy", "httpx", "accelerate", "sentencepiece"
    )}
    monkeypatch.setattr("satquery.registry.probe_dependencies", lambda: missing)
    capabilities = engine.capabilities()
    by_tool = {capability.tool: capability for capability in capabilities}

    assert set(by_tool) == set(ToolName)
    assert by_tool[ToolName.CHANGE].requires_images == 2
    assert by_tool[ToolName.MODALITY].available is False
    assert by_tool[ToolName.GROUNDING].available is False
    assert by_tool[ToolName.GROUNDING].unavailable_reason


def test_tool_rejects_extra_images_before_execution(engine):
    with pytest.raises(QueryError, match="accepts at most 1"):
        engine.answer("Describe this", uploads=[upload(), upload()])


def test_change_tool_rejects_more_than_two_images(engine):
    with pytest.raises(QueryError, match="accepts at most 2"):
        engine.answer("What changed?", uploads=[upload(), upload(), upload()])


def test_health_reports_missing_dependencies_with_actions(engine):
    report = engine.health()
    assert report["status"] in {"ready", "degraded"}
    assert "torch" in report["dependencies"]
    assert isinstance(report["setup_actions"], list)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def test_root_serves_the_console(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "SatQuery" in response.text
    assert "/api/v1/query" in response.text


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "SatQuery AI"
    assert body["owner"] == "Az"
    assert body["problem_statement"] == "SIH26167"
    assert "dependencies" in body


def test_capabilities_endpoint(client):
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(ToolName)
    assert all("description" in item for item in body)


def test_config_endpoint_redacts_secrets(client):
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_api_key"] in (None, "set")
    assert body["app_name"] == "SatQuery AI"


def test_query_endpoint_with_an_upload(client):
    files = {"files": ("scene.png", to_png_bytes(make_scene(water_box=(0, 0, 150, 150))), "image/png")}
    response = client.post(
        "/api/v1/query", data={"query": "Where is the water?"}, files=files
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == Intent.GROUNDING.value
    assert body["tools_used"] == [ToolName.GROUNDING.value]
    assert body["results"][0]["regions"]
    assert body["trace"]
    assert body["latency_ms"] > 0


def test_query_endpoint_accepts_a_modality_hint(client):
    files = {"files": ("scene.png", to_png_bytes(make_scene()), "image/png")}
    response = client.post(
        "/api/v1/query",
        data={"query": "Describe this scene", "modality_hint": "SAR"},
        files=files,
    )
    assert response.status_code == 200
    assert response.json()["images"][0]["modality"] == "SAR"


def test_query_endpoint_rejects_a_bad_modality_hint(client):
    files = {"files": ("scene.png", to_png_bytes(make_scene()), "image/png")}
    response = client.post(
        "/api/v1/query",
        data={"query": "Describe this", "modality_hint": "LIDAR"},
        files=files,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "query_error"
    assert body["remediation"]


def test_query_endpoint_rejects_an_unknown_forced_tool(client):
    files = {"files": ("scene.png", to_png_bytes(make_scene()), "image/png")}
    response = client.post(
        "/api/v1/query",
        data={"query": "Describe this", "force_tool": "telepathy"},
        files=files,
    )
    assert response.status_code == 422
    assert "force_tool" in response.json()["detail"]


def test_query_endpoint_without_an_image_returns_a_helpful_error(client):
    response = client.post("/api/v1/query", data={"query": "Describe this scene"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "query_error"
    assert any("Attach" in line for line in body["remediation"])


def test_location_endpoint_accepts_coordinates_without_empty_place(client, monkeypatch, tmp_path):
    image_path = tmp_path / "location.png"
    image_path.write_bytes(to_png_bytes(make_scene(urban_box=(230, 0, 384, 140))))
    monkeypatch.setattr(
        "plugins.image_fetcher.satellite_fetcher.fetch_satellite_image",
        lambda **kwargs: image_path,
    )

    response = client.post(
        "/api/v1/query/location",
        data={
            "query": "describe this scene",
            "place": "",
            "latitude": "12.842946",
            "longitude": "80.155410",
            "zoom": "18",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"]


def test_query_endpoint_rejects_a_corrupt_upload(client):
    files = {"files": ("broken.png", b"definitely not a png", "image/png")}
    response = client.post("/api/v1/query", data={"query": "Describe this"}, files=files)
    assert response.status_code == 400
    assert response.json()["error"] == "image_error"


def test_two_uploads_drive_change_detection_over_http(client):
    files = [
        ("files", ("t1.png", to_png_bytes(make_scene(vegetation_box=(0, 0, 384, 384))), "image/png")),
        (
            "files",
            (
                "t2.png",
                to_png_bytes(make_scene(vegetation_box=(0, 0, 384, 384), urban_box=(20, 20, 180, 180))),
                "image/png",
            ),
        ),
    ]
    response = client.post(
        "/api/v1/query", data={"query": "What changed between these?"}, files=files
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == Intent.CHANGE_DETECTION.value
    assert len(body["images"]) == 2


def test_json_endpoint_reads_from_a_sandboxed_path(client, settings, tmp_path):
    target = tmp_path / "tile.png"
    target.write_bytes(to_png_bytes(make_scene(water_box=(0, 0, 150, 150))))

    response = client.post(
        "/api/v1/query/json",
        json={"query": "Where is the water?", "image_paths": ["tile.png"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["images"][0]["filename"] == "tile.png"
    assert body["images"][0]["source"].endswith("tile.png")


def test_json_endpoint_requires_paths(client):
    response = client.post("/api/v1/query/json", json={"query": "Describe this"})
    assert response.status_code == 422
    assert response.json()["error"] == "query_error"


def test_json_endpoint_rejects_a_blank_query(client):
    response = client.post(
        "/api/v1/query/json", json={"query": "   ", "image_paths": ["tile.png"]}
    )
    assert response.status_code == 422


def test_json_endpoint_reports_a_missing_file(client):
    response = client.post(
        "/api/v1/query/json",
        json={"query": "Describe this", "image_paths": ["absent.png"]},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "image_not_found"
