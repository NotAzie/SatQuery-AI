"""Normalised provider failures. Adapters must map vendor exceptions onto these."""

from earth_platform.shared.errors import PlatformError, UpstreamUnavailableError


class LLMError(PlatformError):
    code = "llm_error"
    http_status = 502


class LLMAuthError(LLMError):
    code = "llm_auth_error"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    http_status = 429

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message, details={"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s


class LLMContextLengthError(LLMError):
    code = "llm_context_length_exceeded"
    http_status = 413


class LLMUnsupportedFeatureError(LLMError):
    """e.g. images sent to a model without vision, tools sent to a model without tool calling."""

    code = "llm_unsupported_feature"
    http_status = 422


class LLMProviderUnavailableError(UpstreamUnavailableError):
    code = "llm_provider_unavailable"
