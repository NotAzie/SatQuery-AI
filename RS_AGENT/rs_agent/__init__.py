"""Compatibility namespace for the former RS-Agent package name."""

from satquery_ai import SatQueryAI, SatQueryEngine

RSAgent = SatQueryAI

__all__ = ["RSAgent", "SatQueryAI", "SatQueryEngine"]

"""Compatibility package for SatQuery AI."""

__version__ = "0.2.0"
