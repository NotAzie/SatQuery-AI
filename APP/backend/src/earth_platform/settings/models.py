"""Typed configuration sections. Secrets are never stored in config files: sections name an
environment variable (``*_env``) and the value is resolved at use time."""

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

Environment = Literal["development", "production", "test"]


def _secret_from_env(name: str | None) -> SecretStr | None:
    value = os.environ.get(name) if name else None
    return SecretStr(value) if value else None


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=list)


class EngineSettings(BaseModel):
    """How the Platform reaches SatQuery Engine. ``kind`` selects an adapter in
    ``earth_platform.engine.factory``; ``unconfigured`` is the explicit not-connected state."""

    kind: str = "unconfigured"
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_s: float = 30.0
    options: dict[str, Any] = Field(default_factory=dict)

    def api_key(self) -> SecretStr | None:
        return _secret_from_env(self.api_key_env)


class ProviderSettings(BaseModel):
    """One configured LLM endpoint. The dict key in ``llm.providers`` is its identifier."""

    kind: str  # selects a ProviderFactory: "openai", "anthropic", "google", "ollama", ...
    enabled: bool = False
    local: bool = False  # runs on this machine / network; no data leaves it
    base_url: str | None = None
    api_key_env: str | None = None
    default_model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    def api_key(self) -> SecretStr | None:
        return _secret_from_env(self.api_key_env)


class LLMSettings(BaseModel):
    default_provider: str | None = None
    default_model: str | None = None
    providers: dict[str, ProviderSettings] = Field(default_factory=dict)


class AgentSettings(BaseModel):
    """Default model identifier registered with the Engine's Agent Interface."""

    model_id: str | None = None


class IntelligenceSettings(BaseModel):
    history_message_limit: int = Field(default=20, ge=0, le=200)
    context_token_budget: int = Field(default=6000, ge=256, le=100_000)
    retrieval_limit: int = Field(default=12, ge=1, le=100)
    earth_snapshot_limit: int = Field(default=20, ge=1, le=20)


class VisionSettings(BaseModel):
    max_image_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_images_per_message: int = Field(default=8, ge=1, le=8)
    max_message_bytes: int = Field(default=40 * 1024 * 1024, gt=0)
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: ["image/png", "image/jpeg", "image/webp", "image/tiff"]
    )
    store_kind: str = "filesystem"
    store_path: Path = Path("./var/images")


class SessionSettings(BaseModel):
    store_kind: Literal["sqlite"] = "sqlite"
    dsn: str = "./var/platform.sqlite3"


class StreamingSettings(BaseModel):
    bus_kind: str = "memory"
    heartbeat_interval_s: float = 15.0
    replay_window_events: int = 2000


class PluginSettings(BaseModel):
    enabled: bool = True
    search_paths: list[Path] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)
    config: dict[str, dict[str, Any]] = Field(default_factory=dict)  # keyed by plugin id


class LoggingSettings(BaseModel):
    level: str = "INFO"
    json_format: bool = False
