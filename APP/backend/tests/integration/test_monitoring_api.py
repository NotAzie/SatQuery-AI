import json

import httpx
from fastapi.testclient import TestClient

from earth_platform.engine.factory import _ADAPTERS
from earth_platform.engine.http import HttpEngineClient
from earth_platform.main import create_app
from earth_platform.settings import Settings
from earth_platform.settings.models import EngineSettings, SessionSettings, VisionSettings


def test_monitoring_routes_forward_typed_engine_operations(tmp_path, monkeypatch):
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
        "requested_variables": ["shoreline"],
    }
    schedule = {
        "schedule_id": "schedule-1",
        "mission_id": "mission-1",
        "name": "Daily shoreline check",
        "earth_query": query,
        "interval_seconds": 86400,
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
    patch_requests = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal patch_requests
        requests.append(request)
        path = request.url.path
        if path.endswith("/platform/missions") and request.method == "GET":
            return httpx.Response(200, json=[mission])
        if path.endswith("/platform/missions") and request.method == "POST":
            return httpx.Response(201, json=mission)
        if path.endswith("/monitoring/schedules") and request.method == "GET":
            return httpx.Response(200, json=[schedule])
        if path.endswith("/monitoring/schedules") and request.method == "POST":
            return httpx.Response(201, json=schedule)
        if (
            path.endswith("/monitoring/schedules/schedule-1")
            and request.method == "PATCH"
        ):
            update = json.loads(request.content)
            patch_requests += 1
            if patch_requests == 1:
                assert update["trigger_policies"] == []
                assert update == {"expected_revision": 1, "trigger_policies": []}
                return httpx.Response(
                    200,
                    json={**schedule, "revision": 2, "trigger_policies": []},
                )
            if patch_requests == 2:
                return httpx.Response(
                    409,
                    json={"detail": "schedule revision is 2; expected 1"},
                )
            assert update == {
                "expected_revision": 2,
                "name": "Revised schedule",
                "earth_query": {
                    **query,
                    "requested_variables": ["wind"],
                },
                "interval_seconds": 3600,
                "priority": 10,
                "overlap_policy": "allow",
            }
            return httpx.Response(
                200,
                json={
                    **schedule,
                    "revision": 3,
                    "name": "Revised schedule",
                    "earth_query": {
                        **query,
                        "requested_variables": ["wind"],
                    },
                    "interval_seconds": 3600,
                    "priority": 10,
                    "overlap_policy": "allow",
                    "trigger_policies": [],
                },
            )
        if path.endswith("/schedule-1/disable"):
            return httpx.Response(200, json={**schedule, "enabled": False})
        if path.endswith("/schedule-1/runs"):
            return httpx.Response(200, json=[run])
        if path.endswith("/schedule-1/comparison"):
            return httpx.Response(200, json=comparison)
        if path.endswith("/monitoring/notifications") and request.method == "GET":
            return httpx.Response(200, json=[notification])
        if path.endswith("/notification-1/acknowledge"):
            return httpx.Response(
                200,
                json={**notification, "status": "acknowledged", "acknowledged_at": timestamp},
            )
        if path.endswith("/schedule-1/triggers"):
            return httpx.Response(200, json=trigger_history)
        raise AssertionError(f"Unexpected Engine request: {request.method} {request.url}")

    transport = httpx.MockTransport(handle)
    monkeypatch.setitem(
        _ADAPTERS,
        "http",
        lambda settings: HttpEngineClient(settings, transport=transport),
    )
    settings = Settings(
        _env_file=None,
        engine=EngineSettings(kind="http", base_url="http://satquery.test"),
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(store_path=tmp_path / "images"),
    )

    with TestClient(create_app(settings)) as client:
        missions = client.get("/api/v1/monitoring/missions")
        created_mission = client.post(
            "/api/v1/monitoring/missions",
            json={"name": "Coastal change", "objective": "Monitor shoreline change"},
        )
        schedules = client.get("/api/v1/monitoring/schedules")
        created_schedule = client.post(
            "/api/v1/monitoring/schedules",
            json={
                "mission_id": "mission-1",
                "name": "Daily shoreline check",
                "earth_query": query,
                "interval_seconds": 86400,
            },
        )
        revised_schedule = client.patch(
            "/api/v1/monitoring/schedules/schedule-1",
            json={"expected_revision": 1, "trigger_policies": []},
        )
        invalid_revision = client.patch(
            "/api/v1/monitoring/schedules/schedule-1",
            json={"expected_revision": 1},
        )
        null_revision = client.patch(
            "/api/v1/monitoring/schedules/schedule-1",
            json={"expected_revision": 1, "trigger_policies": None},
        )
        stale_revision = client.patch(
            "/api/v1/monitoring/schedules/schedule-1",
            json={"expected_revision": 1, "trigger_policies": []},
        )
        revised_definition = client.patch(
            "/api/v1/monitoring/schedules/schedule-1",
            json={
                "expected_revision": 2,
                "name": "Revised schedule",
                "earth_query": {
                    **query,
                    "requested_variables": ["wind"],
                },
                "interval_seconds": 3600,
                "priority": 10,
                "overlap_policy": "allow",
            },
        )
        disabled = client.post("/api/v1/monitoring/schedules/schedule-1/disable")
        runs = client.get("/api/v1/monitoring/schedules/schedule-1/runs")
        compared = client.get(
            "/api/v1/monitoring/schedules/schedule-1/comparison?limit=3"
        )
        notifications = client.get(
            "/api/v1/monitoring/notifications?unread_only=true"
        )
        acknowledged = client.post(
            "/api/v1/monitoring/notifications/notification-1/acknowledge"
        )
        trigger_events = client.get(
            "/api/v1/monitoring/schedules/schedule-1/triggers"
        )

    assert missions.status_code == 200
    assert missions.json()[0]["mission_id"] == "mission-1"
    assert created_mission.status_code == 201
    assert created_schedule.status_code == 201
    assert revised_schedule.status_code == 200
    assert revised_schedule.json()["revision"] == 2
    assert revised_schedule.json()["trigger_policies"] == []
    assert invalid_revision.status_code == 422
    assert null_revision.status_code == 422
    assert stale_revision.status_code == 409
    assert stale_revision.json()["error"]["code"] == "conflict"
    assert revised_definition.status_code == 200
    assert revised_definition.json()["name"] == "Revised schedule"
    assert revised_definition.json()["earth_query"]["requested_variables"] == ["wind"]
    assert revised_definition.json()["interval_seconds"] == 3600
    assert revised_definition.json()["priority"] == 10
    assert revised_definition.json()["overlap_policy"] == "allow"
    assert schedules.json()[0]["schedule_id"] == "schedule-1"
    assert disabled.json()["enabled"] is False
    assert runs.json()[0]["investigation_id"] == "investigation-1"
    assert compared.json()["comparison_sha256"] == "b" * 64
    assert "No inference" in compared.json()["markdown"]
    assert notifications.json()[0]["status"] == "unread"
    assert acknowledged.json()["status"] == "acknowledged"
    assert trigger_events.json()["events"][0]["event_type"] == "trigger_matched"

    sent_schedule = next(
        request
        for request in requests
        if request.method == "POST" and request.url.path.endswith("/monitoring/schedules")
    )
    assert json.loads(sent_schedule.content)["earth_query"]["bbox"] == [-123, 36, -121, 38]
