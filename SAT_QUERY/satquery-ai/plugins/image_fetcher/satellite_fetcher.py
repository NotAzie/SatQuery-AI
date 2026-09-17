"""Optional utility for downloading one detailed static satellite snapshot."""

from __future__ import annotations

import io
import json
import math
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

TARGET_ZOOMS = {"general": 18, "water": 18, "road": 19, "building": 20, "vehicle": 20}


class SatelliteFetchError(RuntimeError):
    """Raised when the optional image fetcher cannot produce an image."""

    def __init__(self, message: str, remediation: Optional[list[str]] = None):
        super().__init__(message)
        self.remediation = remediation or []


@dataclass(frozen=True)
class FetcherSettings:
    output_dir: str = "data/fetched_images"
    provider_url: str = (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
    )
    geocoder_url: str = "https://nominatim.openstreetmap.org/search"
    alternate_geocoder_url: str = "https://photon.komoot.io/api/"
    user_agent: str = "SatQuery-AI-image-fetcher/1.0"
    timeout_s: float = 30.0
    default_zoom: int = 18
    image_size: int = 2048

    @classmethod
    def from_env(cls) -> "FetcherSettings":
        return cls(
            output_dir=os.getenv("SATQUERY_FETCH_OUTPUT_DIR", cls.output_dir),
            provider_url=os.getenv("SATQUERY_FETCH_PROVIDER_URL", cls.provider_url),
            geocoder_url=os.getenv("SATQUERY_FETCH_GEOCODER_URL", cls.geocoder_url),
            alternate_geocoder_url=os.getenv("SATQUERY_FETCH_ALTERNATE_GEOCODER_URL", cls.alternate_geocoder_url),
            user_agent=os.getenv("SATQUERY_FETCH_USER_AGENT", cls.user_agent),
            timeout_s=float(os.getenv("SATQUERY_FETCH_TIMEOUT", cls.timeout_s)),
            default_zoom=int(os.getenv("SATQUERY_FETCH_ZOOM", cls.default_zoom)),
            image_size=int(os.getenv("SATQUERY_FETCH_IMAGE_SIZE", cls.image_size)),
        )


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    label: str
    query_used: str = ""
    candidates: tuple[str, ...] = ()


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not -90.0 <= latitude <= 90.0:
        raise SatelliteFetchError("Latitude must be between -90 and 90.", ["Pass a valid --lat value."])
    if not -180.0 <= longitude <= 180.0:
        raise SatelliteFetchError("Longitude must be between -180 and 180.", ["Pass a valid --lon value."])


def _request_bytes(request: Request, settings: FetcherSettings, purpose: str) -> bytes:
    try:
        with urlopen(request, timeout=settings.timeout_s) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SatelliteFetchError(
            f"The {purpose} request failed: {exc}",
            [
                "Check your internet connection and try again.",
                "For place names, try latitude/longitude if geocoding is unavailable.",
            ],
        ) from exc


def _query_variants(place: str) -> list[str]:
    """Create bounded fallbacks for full addresses and institution names."""
    cleaned = re.sub(r"\s+", " ", place.replace(";", ",")).strip(" ,")
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    without_number = re.sub(r"^\s*\d+[A-Za-z]?(?:[-/]\d+)?\s*[,.-]?\s*", "", cleaned)
    first_part = re.sub(r"^\s*\d+[A-Za-z]?(?:[-/]\d+)?\s*[,.-]?\s*", "", parts[0]) if parts else ""
    parts_without_number = [first_part, *parts[1:]] if first_part else parts
    parts_without_pincode = [re.sub(r"\b\d{5,6}\b", "", part).strip() for part in parts_without_number]
    variants = [cleaned, without_number]
    if len(parts) >= 3:
        variants.extend((", ".join(parts[1:]), ", ".join(parts[:2] + parts[-2:])))
    if len(parts) >= 2:
        variants.append(", ".join(parts[:2] + parts[-1:]))
    if len(parts_without_number) >= 3:
        variants.extend(
            (
                ", ".join(parts_without_number[:1] + parts_without_number[-3:]),
                ", ".join(parts_without_pincode[:1] + parts_without_pincode[-3:]),
            )
        )
    return list(OrderedDict.fromkeys(item for item in variants if item))


def _candidate_score(candidate: dict, query: str, original: str) -> float:
    display = str(candidate.get("display_name", "")).lower()
    tokens = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) > 2}
    score = sum(token in display for token in tokens) / max(1, len(tokens)) * 60.0
    if query.casefold() == original.casefold():
        score += 5.0
    score += float(candidate.get("importance") or 0.0) * 20.0
    result_type = f"{candidate.get('type', '')} {candidate.get('class', '')}".lower()
    if any(word in result_type for word in ("college", "university", "school", "hospital", "airport", "campus")):
        score += 18.0
    if candidate.get("addresstype") in {"building", "amenity", "aeroway", "education"}:
        score += 8.0
    return score


def geocode_place(place: str, settings: Optional[FetcherSettings] = None) -> Location:
    """Resolve a place with fallback searches and ranked candidates."""
    settings = settings or FetcherSettings.from_env()
    if not place.strip():
        raise SatelliteFetchError("Place name cannot be empty.", ["Pass a name such as 'Mumbai Airport'."])

    candidates: dict[tuple[str, str], tuple[float, dict, str]] = {}
    for query_text in _query_variants(place):
        params = urlencode({"q": query_text, "format": "jsonv2", "limit": 5, "addressdetails": 1})
        request = Request(
            f"{settings.geocoder_url}?{params}",
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
        )
        try:
            results = json.loads(_request_bytes(request, settings, "place lookup"))
        except json.JSONDecodeError as exc:
            raise SatelliteFetchError("The place lookup returned invalid JSON.", ["Try coordinates instead."]) from exc
        if not isinstance(results, list):
            continue
        for candidate in results:
            if not isinstance(candidate, dict):
                continue
            key = (str(candidate.get("lat", "")), str(candidate.get("lon", "")))
            if key[0] and key[1]:
                candidates[key] = (_candidate_score(candidate, query_text, place), candidate, query_text)

    if not candidates:
        # Photon often indexes campuses, estates, and landmarks that do not
        # have a direct Nominatim address record. Use it only as a fallback.
        for query_text in _query_variants(place):
            params = urlencode({"q": query_text, "limit": 5})
            request = Request(
                f"{settings.alternate_geocoder_url}?{params}",
                headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            )
            try:
                payload = json.loads(_request_bytes(request, settings, "alternate place lookup"))
            except (json.JSONDecodeError, SatelliteFetchError):
                continue
            features = payload.get("features", []) if isinstance(payload, dict) else []
            for feature in features:
                geometry = feature.get("geometry", {})
                coordinates = geometry.get("coordinates", [])
                properties = feature.get("properties", {})
                if geometry.get("type") != "Point" or len(coordinates) < 2:
                    continue
                candidate = {
                    "lat": coordinates[1],
                    "lon": coordinates[0],
                    "display_name": ", ".join(
                        str(properties[key])
                        for key in ("name", "street", "city", "state", "country")
                        if properties.get(key)
                    ),
                    "importance": properties.get("importance", 0.0),
                    "type": properties.get("osm_value", ""),
                    "class": properties.get("osm_key", ""),
                }
                key = (str(candidate["lat"]), str(candidate["lon"]))
                candidates[key] = (_candidate_score(candidate, query_text, place), candidate, query_text)
    if not candidates:
        raise SatelliteFetchError(
            f"No location found for {place!r}.",
            ["Use a shorter landmark + city query or pass --lat and --lon."],
        )
    ranked = sorted(candidates.values(), key=lambda item: item[0], reverse=True)
    _, selected, query_used = ranked[0]
    try:
        latitude = float(selected["lat"])
        longitude = float(selected["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SatelliteFetchError("The geocoder returned an unusable location.", ["Try coordinates instead."]) from exc
    _validate_coordinates(latitude, longitude)
    suggestions = tuple(str(item[1].get("display_name", "")) for item in ranked[:3])
    return Location(latitude, longitude, selected.get("display_name", place), query_used, suggestions)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60]


def fetch_satellite_image(
    *,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    place: Optional[str] = None,
    zoom: Optional[int] = None,
    output_dir: Optional[str] = None,
    settings: Optional[FetcherSettings] = None,
) -> Path:
    """Download and save one detailed Esri World Imagery snapshot."""
    settings = settings or FetcherSettings.from_env()
    if place and (latitude is not None or longitude is not None):
        raise SatelliteFetchError("Choose either a place or coordinates, not both.")
    if place:
        location = geocode_place(place, settings)
    elif latitude is not None and longitude is not None:
        _validate_coordinates(latitude, longitude)
        location = Location(latitude, longitude, f"{latitude:.5f},{longitude:.5f}")
    else:
        raise SatelliteFetchError(
            "A place or both latitude and longitude are required.",
            ["Use --place 'Mumbai Airport' or --lat 19.09 --lon 72.87."],
        )

    selected_zoom = settings.default_zoom if zoom is None else zoom
    if not 1 <= selected_zoom <= 20:
        raise SatelliteFetchError("Zoom must be between 1 and 20.", ["Choose a web-map zoom level from 1 to 20."])
    if not 512 <= settings.image_size <= 2048:
        raise SatelliteFetchError(
            "Image size must be between 512 and 2048 pixels.",
            ["Set SATQUERY_FETCH_IMAGE_SIZE accordingly."],
        )

    # Keep extent tied to zoom and tile count. More pixels add detail instead
    # of silently widening the geographic area.
    span = 360.0 * (max(1, settings.image_size // 256) / (2**selected_zoom))
    longitude_scale = max(0.1, abs(math.cos(math.radians(location.latitude))))
    longitude_span = min(span / longitude_scale, 359.0)
    latitude_span = min(span, 179.0)
    params = {
        "bbox": ",".join(str(value) for value in (
            location.longitude - longitude_span / 2,
            max(-90.0, location.latitude - latitude_span / 2),
            location.longitude + longitude_span / 2,
            min(90.0, location.latitude + latitude_span / 2),
        )),
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{settings.image_size},{settings.image_size}",
        "format": "jpg",
        "f": "image",
    }
    request = Request(
        f"{settings.provider_url}?{urlencode(params)}",
        headers={"User-Agent": settings.user_agent},
    )
    payload = _request_bytes(request, settings, "satellite image")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
    except Exception as exc:
        raise SatelliteFetchError(
            "The imagery provider returned data that is not a readable image.",
            ["Try again or configure another SATQUERY_FETCH_PROVIDER_URL."],
        ) from exc

    target_dir = Path(output_dir or settings.output_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = target_dir / f"{_slug(location.label) or 'satellite'}-z{selected_zoom}-{timestamp}.jpg"
    path.write_bytes(payload)
    return path.resolve()


def fetch_zoomed_geotiff(*, latitude: float, longitude: float, target: str = "general", zoom: Optional[int] = None, width: int = 2048, height: int = 2048, output_dir: str = "tests/real_eo_zoom/images", settings: Optional[FetcherSettings] = None) -> tuple[Path, Path]:
    """Request a small server-rendered extent; never upscale an existing image."""
    settings = settings or FetcherSettings.from_env(); _validate_coordinates(latitude, longitude)
    target = target.strip().lower()
    if target not in TARGET_ZOOMS: raise SatelliteFetchError(f"Unknown target {target!r}.", [f"Choose one of {sorted(TARGET_ZOOMS)}."])
    selected = TARGET_ZOOMS[target] if zoom is None else zoom
    if not 1 <= selected <= 20: raise SatelliteFetchError("Zoom must be between 1 and 20.")
    if not 512 <= width <= 4096 or not 512 <= height <= 4096: raise SatelliteFetchError("width and height must each be in 512..4096.")
    span = 360.0 * (max(width, height) / 256.0) / (2**selected); lon_span = min(span / max(.1, abs(math.cos(math.radians(latitude)))), 359.0); bounds = (longitude-lon_span/2, max(-90.,latitude-span/2), longitude+lon_span/2, min(90.,latitude+span/2))
    params={"bbox":",".join(str(x) for x in bounds),"bboxSR":"4326","imageSR":"4326","size":f"{width},{height}","format":"jpg","f":"image"}
    payload=_request_bytes(Request(f"{settings.provider_url}?{urlencode(params)}",headers={"User-Agent":settings.user_agent}),settings,"zoomed satellite image")
    try:
        image=Image.open(io.BytesIO(payload)).convert("RGB")
        if image.size != (width,height): raise ValueError(image.size)
        import numpy as np; import rasterio
        from rasterio.transform import from_bounds
    except Exception as exc: raise SatelliteFetchError("Could not decode or GeoTIFF-wrap the server imagery.", ["Install rasterio and retry."]) from exc
    destination=Path(output_dir); destination.mkdir(parents=True,exist_ok=True); stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); base=destination/f"{target}-z{selected}-{latitude:.5f}-{longitude:.5f}-{stamp}"; tif,meta=base.with_suffix(".tif"),base.with_suffix(".json"); data=np.asarray(image).transpose(2,0,1)
    with rasterio.open(tif,"w",driver="GTiff",width=width,height=height,count=3,dtype=data.dtype,crs="EPSG:4326",transform=from_bounds(*bounds,width,height),compress="deflate") as dst:
        dst.write(data); dst.set_band_description(1,"red"); dst.set_band_description(2,"green"); dst.set_band_description(3,"blue"); dst.update_tags(source="Esri World Imagery export",target=target,requested_zoom=str(selected),requested_bounds=json.dumps(bounds),native_resolution_note="Provider mosaic native GSD varies by location; requested zoom is not a native-GSD guarantee.")
    meta.write_text(json.dumps({"source":"Esri World Imagery export","provider_url":settings.provider_url,"target":target,"latitude":latitude,"longitude":longitude,"requested_zoom":selected,"width":width,"height":height,"bounds":bounds,"crs":"EPSG:4326","transform":"affine derived from provider-requested bbox","tile_based":False,"note":"Server-rendered export; no client interpolation or tile stitching."},indent=2),encoding="utf-8")
    return tif.resolve(),meta.resolve()
