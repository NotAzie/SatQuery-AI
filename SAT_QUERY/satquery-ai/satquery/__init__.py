"""SatQuery's Earth Intelligence platform and retained image capability.

Use :class:`SatQueryClient` to connect to the running platform API, or
:class:`SatQueryEngine` for the local image-analysis compatibility workflow.
"""

from .client import CLIENT_API_VERSION, PlatformAPIError, SatQueryClient
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
    "CLIENT_API_VERSION",
    "BackendKind",
    "ConfigurationError",
    "DependencyMissingError",
    "ImageError",
    "ImageNotFoundError",
    "Intent",
    "Modality",
    "ModelLoadError",
    "ModelRegistry",
    "PlatformAPIError",
    "QueryError",
    "QueryPlan",
    "QueryRequest",
    "QueryResponse",
    "QueryRouter",
    "Region",
    "ResourceNotConfiguredError",
    "RoutingError",
    "SatQueryClient",
    "SatQueryEngine",
    "SatQueryError",
    "Settings",
    "ToolExecutionError",
    "ToolName",
    "ToolResult",
    "TraceStep",
    "__author__",
    "__version__",
    "extract_target",
    "get_settings",
    "load_dotenv",
    "probe_dependencies",
    "set_settings",
]


def create_app(settings: "Settings | None" = None):
    """Build the FastAPI application. Imported lazily to keep startup light."""
    from .api import create_app as _create_app

    return _create_app(settings)
