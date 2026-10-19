"""Optional satellite image fetcher.

This package is independent from the core ``satquery`` query pipeline. It
only produces an image path that can be passed to SatQuery separately.
"""

from .satellite_fetcher import fetch_satellite_image, geocode_place

__all__ = ["fetch_satellite_image", "geocode_place"]