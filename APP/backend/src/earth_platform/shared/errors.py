"""Error taxonomy. Every error that may reach a client derives from PlatformError."""

from typing import Any


class PlatformError(Exception):
    code: str = "platform_error"
    http_status: int = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(PlatformError):
    code = "configuration_error"


class NotFoundError(PlatformError):
    code = "not_found"
    http_status = 404


class ConflictError(PlatformError):
    code = "conflict"
    http_status = 409


class ValidationFailedError(PlatformError):
    code = "validation_failed"
    http_status = 422


class UpstreamUnavailableError(PlatformError):
    """A dependency (Engine, LLM provider, store) cannot currently serve the request."""

    code = "upstream_unavailable"
    http_status = 503
