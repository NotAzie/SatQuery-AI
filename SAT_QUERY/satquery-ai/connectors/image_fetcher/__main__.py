"""CLI for the optional satellite image fetcher."""

from __future__ import annotations

import argparse

from .satellite_fetcher import FetcherSettings, SatelliteFetchError, fetch_satellite_image, geocode_place


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional SatQuery satellite image fetcher")
    parser.add_argument("--place", help="Place name, for example 'Mumbai Airport'.")
    parser.add_argument("--lat", type=float, help="Latitude in decimal degrees.")
    parser.add_argument("--lon", type=float, help="Longitude in decimal degrees.")
    parser.add_argument("--zoom", type=int, help="Web-map zoom level from 1 to 20.")
    parser.add_argument("--output", help="Output folder (default: data/fetched_images).")
    args = parser.parse_args()
    settings = FetcherSettings.from_env()
    try:
        if args.place:
            location = geocode_place(args.place, settings)
            latitude, longitude = location.latitude, location.longitude
        else:
            location = None
            latitude, longitude = args.lat, args.lon
        path = fetch_satellite_image(
            latitude=latitude,
            longitude=longitude,
            zoom=args.zoom,
            output_dir=args.output,
            settings=settings,
        )
    except SatelliteFetchError as exc:
        print(f"Error: {exc}")
        for line in exc.remediation:
            print(f"  - {line}")
        return 1
    if location:
        print(f"Resolved location: {location.label}")
        print(f"Coordinates: {location.latitude:.6f}, {location.longitude:.6f}")
        print(f"Geocoder query: {location.query_used}")
        if len(location.candidates) > 1:
            print("Other candidates:")
            for candidate in location.candidates[1:]:
                print(f"  - {candidate}")
    else:
        print("Resolved location: coordinates")
        print(f"Coordinates: {latitude}, {longitude}")
    print(f"Zoom used: {args.zoom if args.zoom is not None else settings.default_zoom}")
    print(f"Saved image: {path}")
    print(f'Use it with: python -m satquery ask "describe this scene" -i "{path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())