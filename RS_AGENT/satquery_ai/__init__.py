"""SatQuery AI public API."""

from .configuration import load_config, resolve_path
from .knowledge import configure_knowledge, search_knowledge
from .orchestration.engine import SatQueryEngine

SatQueryAI = SatQueryEngine

__all__ = ["SatQueryAI", "SatQueryEngine", "configure_knowledge", "load_config", "resolve_path", "search_knowledge"]
__version__ = "0.3.0"
