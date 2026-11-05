from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from earth_platform.settings.models import (
    AgentSettings,
    EngineSettings,
    Environment,
    IntelligenceSettings,
    LLMSettings,
    LoggingSettings,
    PluginSettings,
    ServerSettings,
    SessionSettings,
    StreamingSettings,
    VisionSettings,
)

_APP_ROOT = Path(__file__).resolve().parents[4]
_REPOSITORY_ROOT = _APP_ROOT.parent


class _SharedDotEnvSource(PydanticBaseSettingsSource):
    """Keep the Platform fields from a dotenv shared with other services."""

    def __init__(self, source: PydanticBaseSettingsSource) -> None:
        super().__init__(source.settings_cls)
        self._source = source

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self._source.get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        values = self._source()
        return {
            name: value
            for name, value in values.items()
            if name in self.settings_cls.model_fields
        }


class Settings(BaseSettings):
    """Precedence (highest first): init kwargs > environment (``EARTH_*``, ``__`` nests)
    > ``.env`` > layered YAML files (deep-merged, later files win) > defaults.

    The YAML layer is added by :func:`earth_platform.settings.loader.load_settings`.
    """

    model_config = SettingsConfigDict(
        env_prefix="EARTH_",
        env_nested_delimiter="__",
        env_file=(str(_APP_ROOT / ".env"), str(_REPOSITORY_ROOT / ".env")),
        extra="forbid",
    )

    app_name: str = "Earth Intelligence Platform"
    environment: Environment = "development"
    debug: bool = False

    server: ServerSettings = Field(default_factory=ServerSettings)
    engine: EngineSettings = Field(default_factory=EngineSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    intelligence: IntelligenceSettings = Field(default_factory=IntelligenceSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    sessions: SessionSettings = Field(default_factory=SessionSettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    plugins: PluginSettings = Field(default_factory=PluginSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            _SharedDotEnvSource(dotenv_settings),
            file_secret_settings,
        )
