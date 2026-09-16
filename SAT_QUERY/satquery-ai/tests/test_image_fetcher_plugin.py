from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from plugins.image_fetcher.satellite_fetcher import (
    FetcherSettings,
    SatelliteFetchError,
    fetch_satellite_image,
    geocode_place,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (40, 80, 120)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_fetch_coordinates_saves_a_real_image(monkeypatch, tmp_path):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        return FakeResponse(image_bytes())

    monkeypatch.setattr("plugins.image_fetcher.satellite_fetcher.urlopen", fake_urlopen)
    settings = FetcherSettings()
    path = fetch_satellite_image(
        settings=settings,
        latitude=19.0896,
        longitude=72.8656,
        zoom=15,
        output_dir=str(tmp_path),
    )

    assert path.parent == tmp_path.resolve()
    assert path.suffix == ".jpg"
    with Image.open(path) as image:
        assert image.size == (4, 4)
    assert "World_Imagery" in requests[0][0]
    assert requests[0][1] == settings.timeout_s


def test_place_name_is_geocoded(monkeypatch):
    payload = json.dumps([
        {"lat": "19.0896", "lon": "72.8656", "display_name": "Mumbai Airport"}
    ]).encode()
    monkeypatch.setattr(
        "plugins.image_fetcher.satellite_fetcher.urlopen",
        lambda request, timeout: FakeResponse(payload),
    )

    location = geocode_place("Mumbai Airport", FetcherSettings())

    assert location.latitude == pytest.approx(19.0896)
    assert location.longitude == pytest.approx(72.8656)
    assert location.label == "Mumbai Airport"


def test_geocoder_retries_without_house_number_and_ranks_candidates(monkeypatch):
    queries = []

    def fake_urlopen(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)["q"][0]
        queries.append(query)
        if query.startswith("120 "):
            return FakeResponse(b"[]")
        return FakeResponse(json.dumps([
            {
                "lat": "12.8406",
                "lon": "80.1534",
                "display_name": "Vandalur College Campus, Chennai, Tamil Nadu",
                "importance": 0.8,
                "type": "college",
                "class": "amenity",
                "addresstype": "amenity",
            },
            {
                "lat": "12.9",
                "lon": "80.2",
                "display_name": "Chennai, Tamil Nadu",
                "importance": 0.9,
                "type": "city",
                "class": "place",
            },
        ]).encode())

    monkeypatch.setattr("plugins.image_fetcher.satellite_fetcher.urlopen", fake_urlopen)
    location = geocode_place(
        "120 Vandalur College Campus, Chennai, Tamil Nadu",
        FetcherSettings(),
    )

    assert any(not query.startswith("120 ") for query in queries)
    assert "College Campus" in location.label
    assert location.query_used != "120 Vandalur College Campus, Chennai, Tamil Nadu"
    assert len(location.candidates) == 2


def test_alternate_geocoder_handles_missing_nominatim_result(monkeypatch):
    def fake_urlopen(request, timeout):
        url = request.full_url
        if "nominatim" in url:
            return FakeResponse(b"[]")
        return FakeResponse(json.dumps({
            "features": [{
                "geometry": {"type": "Point", "coordinates": [80.1554, 12.8429]},
                "properties": {
                    "name": "VIT Chennai",
                    "city": "Chennai",
                    "state": "Tamil Nadu",
                    "osm_value": "college",
                    "osm_key": "amenity",
                },
            }],
        }).encode())

    settings = FetcherSettings(geocoder_url="https://nominatim.example/search")
    monkeypatch.setattr("plugins.image_fetcher.satellite_fetcher.urlopen", fake_urlopen)
    location = geocode_place("VIT Chennai, Vandalur", settings)

    assert location.label == "VIT Chennai, Chennai, Tamil Nadu"
    assert location.latitude == pytest.approx(12.8429)
    assert location.longitude == pytest.approx(80.1554)


def test_default_fetch_requests_high_detail_image(monkeypatch, tmp_path):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        return FakeResponse(image_bytes())

    monkeypatch.setattr("plugins.image_fetcher.satellite_fetcher.urlopen", fake_urlopen)
    settings = FetcherSettings()
    fetch_satellite_image(
        latitude=12.84,
        longitude=80.15,
        output_dir=str(tmp_path),
        settings=settings,
    )

    params = parse_qs(urlparse(requests[0]).query)
    assert settings.default_zoom == 18
    assert settings.image_size == 2048
    assert params["size"] == ["2048,2048"]


def test_fetch_requires_a_complete_location(tmp_path):
    with pytest.raises(SatelliteFetchError, match="place or both latitude"):
        fetch_satellite_image(latitude=19.0, output_dir=str(tmp_path), settings=FetcherSettings())


def test_fetch_rejects_invalid_coordinates(tmp_path):
    with pytest.raises(SatelliteFetchError, match="Latitude"):
        fetch_satellite_image(
            latitude=91.0,
            longitude=72.0,
            output_dir=str(tmp_path),
            settings=FetcherSettings(),
        )