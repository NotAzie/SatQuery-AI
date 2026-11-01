from collections.abc import Callable

from earth_platform.engine.client import EngineClient
from earth_platform.engine.http import HttpEngineClient
from earth_platform.engine.unavailable import UnavailableEngineClient
from earth_platform.settings.models import EngineSettings
from earth_platform.shared.errors import ConfigurationError

EngineAdapterBuilder = Callable[[EngineSettings], EngineClient]

# Adapters register here when they land, e.g. "http" and "sdk".
_ADAPTERS: dict[str, EngineAdapterBuilder] = {
    "unconfigured": lambda _settings: UnavailableEngineClient(),
    "http": lambda settings: HttpEngineClient(settings),
}


def build_engine_client(settings: EngineSettings) -> EngineClient:
    try:
        return _ADAPTERS[settings.kind](settings)
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS))
        raise ConfigurationError(
            f"unknown engine.kind '{settings.kind}' (available: {known})"
        ) from None
