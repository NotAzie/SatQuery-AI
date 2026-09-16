"""SatQuery AI - an interactive vision-language assistant for remote sensing.

Built by Az for Smart India Hackathon problem statement SIH26167.

Ask a satellite or aerial image a question in natural language. SatQuery
understands the query, picks a specialist vision capability, runs it against
the actual pixels, and returns the answer with an execution trace showing
which capability produced it.

Quick start::

    from satquery import SatQueryEngine

    engine = SatQueryEngine()
    response = engine.answer(
        "where are the buildings",
        image_paths=["/data/scenes/tile_01.png"],
    )
    print(response.answer)
    print(response.tools_used)

Or serve the API and demo console::

    python -m satquery
"""

from .config import Settings, get_settings, load_dotenv, set_settings
from .errors import (
    ConfigurationError,
    DependencyMissingError,
    ImageError,
    ImageNotFoundError,
    ModelLoadError,
    QueryError,
    ResourceNotConfiguredError,
    RoutingError,
    SatQueryError,
    ToolExecutionError,
)
from .orchestrator import SatQueryEngine
from .registry import ModelRegistry, probe_dependencies
from .router import QueryRouter, extract_target
from .schemas import (
    BackendKind,
    Intent,
    Modality,
    QueryPlan,
    QueryRequest,
    QueryResponse,
    Region,
    ToolName,
    ToolResult,
    TraceStep,
)

__version__ = "1.0.0"
__author__ = "Az"
__all__ = [
    "__version__",
    "__author__",
    "SatQueryEngine",
    "Settings",
    "get_settings",
    "set_settings",
    "load_dotenv",
    "ModelRegistry",
    "probe_dependencies",
    "QueryRouter",
    "extract_target",
    "BackendKind",
    "Intent",
    "Modality",
    "QueryPlan",
    "QueryRequest",
    "QueryResponse",
    "Region",
    "ToolName",
    "ToolResult",
    "TraceStep",
    "SatQueryError",
    "ConfigurationError",
    "DependencyMissingError",
    "ImageError",
    "ImageNotFoundError",
    "ModelLoadError",
    "QueryError",
    "ResourceNotConfiguredError",
    "RoutingError",
    "ToolExecutionError",
]


def create_app(settings: "Settings | None" = None):
    """Build the FastAPI application. Imported lazily to keep startup light."""
    from .api import create_app as _create_app

    return _create_app(settings)
