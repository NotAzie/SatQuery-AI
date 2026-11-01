from earth_platform.shared.errors import UpstreamUnavailableError


class EngineUnavailableError(UpstreamUnavailableError):
    code = "engine_unavailable"
