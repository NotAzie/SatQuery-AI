"""Compatibility exports for SatQuery AI configuration."""

from __future__ import annotations

import os
from pathlib import Path
from satquery_ai.configuration import PROJECT_ROOT, load_config, resolve_path

__all__ = ["PROJECT_ROOT", "load_config", "resolve_path"]


