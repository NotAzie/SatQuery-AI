from fastapi.testclient import TestClient

from earth_platform.main import create_app
from earth_platform.settings import Settings
from earth_platform.settings.models import SessionSettings


def test_session_and_conversation_routes_use_persistent_store(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/v1/sessions", json={"title": "Flood analysis"})
        assert created.status_code == 201
        session_id = created.json()["id"]

        camera = {
            "position": {"lng": 12.5, "lat": 48.1},
            "height_m": 1200000,
            "heading_deg": 20,
            "pitch_deg": -80,
            "roll_deg": 0,
            "view_rect": None,
        }
        workspace = {
            "camera_history": {"past": [], "present": camera, "future": []},
            "bookmarks": [
                {
                    "id": "bookmark-1",
                    "name": "Alps",
                    "context": {
                        "camera": camera,
                        "layers": [],
                        "time": None,
                        "instant": None,
                        "selection": {
                            "entity_id": "feature-1",
                            "position": {"lng": 12.5, "lat": 48.1},
                            "properties": {"label": "Peak"},
                        },
                        "drawings": [
                            {
                                "id": "drawing-1",
                                "name": "Point 1",
                                "kind": "point",
                                "geometry": {"type": "Point", "coordinates": [12.5, 48.1]},
                            }
                        ],
                        "captures": [],
                        "selected_evidence_ids": [],
                        "bookmarks": [],
                        "camera_history": {"past": [], "present": None, "future": []},
                        "split_view": {"enabled": False, "sync_cameras": False},
                        "measurement": None,
                    },
                    "created_at": "2026-11-01T10:00:00Z",
                    "updated_at": "2026-11-01T10:00:00Z",
                }
            ],
            "captures": [],
        }
        saved = client.patch(
            f"/api/v1/sessions/{session_id}",
            json={"earth_workspace": workspace},
        )
        assert saved.status_code == 200
        assert saved.json()["earth_workspace"] == workspace
        assert client.get(f"/api/v1/sessions/{session_id}").json()["earth_workspace"] == workspace

        conversation = client.post(
            f"/api/v1/sessions/{session_id}/conversations",
            json={"title": "First question"},
        )
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]

        assert client.get("/api/v1/sessions").json()[0]["id"] == session_id
        assert (
            client.get(f"/api/v1/sessions/{session_id}/conversations/{conversation_id}").status_code
            == 200
        )
        assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
        assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
