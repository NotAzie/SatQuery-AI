import base64
import random
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from earth_platform.main import create_app
from earth_platform.settings import Settings
from earth_platform.settings.models import SessionSettings, VisionSettings


def _png(size: tuple[int, int] = (16, 16)) -> bytes:
    image = Image.frombytes(
        "RGB",
        size,
        random.Random(42).randbytes(size[0] * size[1] * 3),
    )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _settings(
    tmp_path: Path,
    *,
    max_bytes: int = 1024 * 1024,
    max_message_bytes: int = 40 * 1024 * 1024,
) -> Settings:
    return Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(
            max_image_bytes=max_bytes,
            max_images_per_message=2,
            max_message_bytes=max_message_bytes,
            store_path=tmp_path / "images",
        ),
    )


def test_image_assets_are_session_scoped_prepared_and_persistent(tmp_path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        other_session = client.post("/api/v1/sessions", json={}).json()
        session_id = session["id"]
        other_session_id = other_session["id"]
        image_bytes = _png()

        uploaded = client.post(
            f"/api/v1/vision/sessions/{session_id}/assets",
            files={"upload": ("capture.png", image_bytes, "image/png")},
            data={"origin": "earth_capture"},
        )
        assert uploaded.status_code == 201
        asset = uploaded.json()
        asset_id = asset["id"]
        assert asset["session_id"] == session_id
        assert asset["mime_type"] == "image/png"
        assert asset["width"] == 16
        assert asset["height"] == 16

        listed = client.get(f"/api/v1/vision/sessions/{session_id}/assets")
        assert [item["id"] for item in listed.json()] == [asset_id]
        assert (
            client.get(f"/api/v1/vision/sessions/{other_session_id}/assets/{asset_id}").status_code
            == 404
        )

        content = client.get(f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}/content")
        assert content.content == image_bytes
        thumbnail = client.get(f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}/thumbnail")
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/png"

        prepared = client.post(
            f"/api/v1/vision/sessions/{session_id}/prepare",
            json={
                "asset_ids": [asset_id],
                "context": {
                    "earth_captures": [
                        {
                            "id": "capture-1",
                            "asset_id": asset_id,
                            "captured_at": "2026-11-01T10:00:00Z",
                            "source": "region",
                            "camera": {
                                "position": {"lng": 12.5, "lat": 48.1},
                                "height_m": 1200000,
                                "heading_deg": 20,
                                "pitch_deg": -80,
                                "roll_deg": 0,
                                "view_rect": None,
                            },
                            "region": None,
                            "pixel_region": {
                                "left": 2,
                                "top": 3,
                                "width": 8,
                                "height": 9,
                            },
                            "viewport_width_px": 16,
                            "viewport_height_px": 16,
                        }
                    ],
                    "metadata": {"source": "earth-workspace"},
                },
            },
        )
        assert prepared.status_code == 200
        assert prepared.json()["context"]["assets"][0]["id"] == asset_id
        assert prepared.json()["context"]["earth_captures"][0]["asset_id"] == asset_id
        assert prepared.json()["context"]["earth_captures"][0]["pixel_region"]["left"] == 2
        assert prepared.json()["context"]["metadata"] == {"source": "earth-workspace"}
        assert base64.b64decode(prepared.json()["assets"][0]["data_base64"]) == image_bytes

        invalid_crop = client.post(
            f"/api/v1/vision/sessions/{session_id}/prepare",
            json={
                "asset_ids": [asset_id],
                "context": {
                    "earth_captures": [
                        {
                            "id": "capture-out-of-bounds",
                            "asset_id": asset_id,
                            "captured_at": "2026-11-01T10:00:00Z",
                            "source": "region",
                            "camera": {
                                "position": {"lng": 12.5, "lat": 48.1},
                                "height_m": 1200000,
                                "heading_deg": 20,
                                "pitch_deg": -80,
                                "roll_deg": 0,
                                "view_rect": None,
                            },
                            "region": None,
                            "pixel_region": {
                                "left": 12,
                                "top": 3,
                                "width": 8,
                                "height": 9,
                            },
                            "viewport_width_px": 16,
                            "viewport_height_px": 16,
                        }
                    ]
                },
            },
        )
        assert invalid_crop.status_code == 422

        updated = client.patch(
            f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}",
            json={
                "filename": "renamed.png",
                "georef": {
                    "center": {"lng": 12.5, "lat": 48.1},
                    "pixel_resolution_m": [10, 10],
                },
            },
        )
        assert updated.status_code == 200
        assert updated.json()["filename"] == "renamed.png"
        assert updated.json()["georef"]["pixel_resolution_m"] == [10, 10]

        cleared_georef = client.patch(
            f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}",
            json={"georef": None},
        )
        assert cleared_georef.status_code == 200
        assert cleared_georef.json()["filename"] == "renamed.png"
        assert cleared_georef.json()["georef"] is None

    with TestClient(create_app(settings)) as client:
        restored = client.get(f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}")
        assert restored.status_code == 200
        assert restored.json()["filename"] == "renamed.png"

        deleted = client.delete(f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}")
        assert deleted.status_code == 204
        assert (
            client.get(f"/api/v1/vision/sessions/{session_id}/assets/{asset_id}").status_code == 404
        )


def test_image_upload_rejects_mime_mismatch_size_and_invalid_georeference(tmp_path):
    settings = _settings(tmp_path, max_bytes=1024)
    with TestClient(create_app(settings)) as client:
        session_id = client.post("/api/v1/sessions", json={}).json()["id"]
        valid_png = _png()

        mismatch = client.post(
            f"/api/v1/vision/sessions/{session_id}/assets",
            files={"upload": ("capture.png", valid_png, "image/jpeg")},
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["error"]["message"] == (
            "Declared content type does not match the image data"
        )

        too_large = client.post(
            f"/api/v1/vision/sessions/{session_id}/assets",
            files={"upload": ("large.png", _png((64, 64)), "image/png")},
        )
        assert too_large.status_code == 422
        assert "size limit" in too_large.json()["error"]["message"]

        invalid_georef = client.post(
            f"/api/v1/vision/sessions/{session_id}/assets",
            files={"upload": ("capture.png", _png(), "image/png")},
            data={"georef": '{"pixel_resolution_m":[0,10]}'},
        )
        assert invalid_georef.status_code == 422
        assert invalid_georef.json()["error"]["message"] == "Georeference metadata is invalid"

        invalid_file = client.post(
            f"/api/v1/vision/sessions/{session_id}/assets",
            files={"upload": ("not-image.png", b"not an image", "image/png")},
        )
        assert invalid_file.status_code == 422
        assert invalid_file.json()["error"]["message"] == (
            "Uploaded data is not a valid supported image"
        )


def test_prepare_rejects_cross_session_assets_and_duplicate_ids(tmp_path):
    with TestClient(create_app(_settings(tmp_path))) as client:
        session_id = client.post("/api/v1/sessions", json={}).json()["id"]
        other_session_id = client.post("/api/v1/sessions", json={}).json()["id"]
        uploaded = client.post(
            f"/api/v1/vision/sessions/{other_session_id}/assets",
            files={"upload": ("capture.png", _png(), "image/png")},
        )
        asset_id = uploaded.json()["id"]

        cross_session = client.post(
            f"/api/v1/vision/sessions/{session_id}/prepare",
            json={"asset_ids": [asset_id]},
        )
        assert cross_session.status_code == 404

        duplicate = client.post(
            f"/api/v1/vision/sessions/{other_session_id}/prepare",
            json={"asset_ids": [asset_id, asset_id]},
        )
        assert duplicate.status_code == 422
        assert duplicate.json()["error"]["message"] == ("An image asset may only be attached once")


def test_prepare_enforces_aggregate_attachment_size_limit(tmp_path):
    with TestClient(create_app(_settings(tmp_path, max_message_bytes=1000))) as client:
        session_id = client.post("/api/v1/sessions", json={}).json()["id"]
        asset_ids = []
        for index in range(2):
            uploaded = client.post(
                f"/api/v1/vision/sessions/{session_id}/assets",
                files={"upload": (f"capture-{index}.png", _png(), "image/png")},
            )
            assert uploaded.status_code == 201
            asset_ids.append(uploaded.json()["id"])

        prepared = client.post(
            f"/api/v1/vision/sessions/{session_id}/prepare",
            json={"asset_ids": asset_ids},
        )
        assert prepared.status_code == 422
        assert "message size limit" in prepared.json()["error"]["message"]
