from pydantic import Field
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


class Settings(BaseSettings):
    """Precedence (highest first): init kwargs > environment (``EARTH_*``, ``__`` nests)
    > ``.env`` > layered YAML files (deep-merged, later files win) > defaults.

    The YAML layer is added by :func:`earth_platform.settings.loader.load_settings`.
    """

    model_config = SettingsConfigDict(
        env_prefix="EARTH_",
        env_nested_delimiter="__",
        env_file=".env",
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
            dotenv_settings,
            file_secret_settings,
        )
