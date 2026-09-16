"""Error types for SatQuery AI.

Every failure mode in this system is expected to say three things: what went
wrong, why it went wrong, and what the operator should do next. A vision
assistant that silently degrades into plausible-sounding prose is worse than
one that refuses, so missing resources raise loudly rather than falling back
to invented answers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class SatQueryError(Exception):
    """Base class for every error raised by SatQuery AI."""

    status_code: int = 500
    code: str = "satquery_error"

    def __init__(
        self,
        message: str,
        *,
        remediation: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.remediation = remediation or []
        self.context = context or {}

    def to_payload(self) -> Dict[str, Any]:
        return {
            "error": self.code,
            "detail": self.message,
            "remediation": self.remediation,
            "context": self.context,
        }


class ConfigurationError(SatQueryError):
    """Raised when settings are internally inconsistent or unusable."""

    status_code = 500
    code = "configuration_error"


class ResourceNotConfiguredError(SatQueryError):
    """Raised when a required model, weight file, or API key is absent.

    This is the error that keeps the system honest: if no vision backend can
    be loaded, SatQuery refuses the request instead of answering from the
    language prior alone.
    """

    status_code = 503
    code = "resource_not_configured"


class DependencyMissingError(ResourceNotConfiguredError):
    """Raised when an optional Python dependency has not been installed."""

    code = "dependency_missing"

    @classmethod
    def for_package(cls, package: str, purpose: str, install: str) -> "DependencyMissingError":
        return cls(
            f"The '{package}' package is required for {purpose} but is not installed.",
            remediation=[
                f"Install it with: {install}",
                "Then restart the SatQuery service so the model registry can load.",
            ],
            context={"package": package, "purpose": purpose},
        )


class ModelLoadError(SatQueryError):
    """Raised when a model was found but could not be instantiated."""

    status_code = 503
    code = "model_load_error"


class ImageError(SatQueryError):
    """Raised for unreadable, missing, oversized, or malformed imagery."""

    status_code = 400
    code = "image_error"


class ImageNotFoundError(ImageError):
    status_code = 404
    code = "image_not_found"


class QueryError(SatQueryError):
    """Raised when the request itself is malformed or under-specified."""

    status_code = 422
    code = "query_error"


class ToolExecutionError(SatQueryError):
    """Raised when a specialist tool fails mid-run."""

    status_code = 500
    code = "tool_execution_error"

    def __init__(self, tool: str, message: str, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.tool = tool
        self.context.setdefault("tool", tool)


class RoutingError(SatQueryError):
    """Raised when no capability can serve the query."""

    status_code = 422
    code = "routing_error"
