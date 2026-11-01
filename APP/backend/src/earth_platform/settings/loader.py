"""Layered configuration loading.

Order (later overrides earlier):
    config/base.yaml
    config/providers/*.yaml          every known LLM endpoint, disabled by default
    config/environments/<env>.yaml   development | production | test   (EARTH_ENV)
    config/profiles/<name>.yaml      composable overlays, e.g. local-models (EARTH_PROFILES=a,b)
then ``EARTH_*`` environment variables and ``.env``.
"""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from earth_platform.settings.models import Environment
from earth_platform.settings.settings import Settings
from earth_platform.shared.errors import ConfigurationError


def find_config_dir(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    if env_dir := os.environ.get("EARTH_CONFIG_DIR"):
        candidates.append(Path(env_dir))
    candidates.append(Path.cwd() / "config")
    candidates.extend(parent / "config" for parent in Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / "base.yaml").is_file():
            return candidate
    raise ConfigurationError(
        "config/base.yaml not found; set EARTH_CONFIG_DIR or run from the repository root"
    )


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _deep_merge_files(files: Sequence[Path]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for file in files:
        loaded = yaml.safe_load(file.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ConfigurationError(f"{file} must contain a mapping at the top level")
        data = _deep_merge(data, loaded)
    return data


class _MergedYamlSource(PydanticBaseSettingsSource):
    """Serves the already deep-merged YAML layers as one settings source."""

    def __init__(self, settings_cls: type[BaseSettings], data: dict[str, Any]) -> None:
        super().__init__(settings_cls)
        self._data = data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


def _profiles_from_env() -> list[str]:
    raw = os.environ.get("EARTH_PROFILES", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def load_settings(
    *,
    environment: str | None = None,
    profiles: Sequence[str] | None = None,
    config_dir: Path | None = None,
) -> Settings:
    root = find_config_dir(config_dir)
    env = environment or os.environ.get("EARTH_ENV", "development")
    chosen = list(profiles) if profiles is not None else _profiles_from_env()

    files: list[Path] = [root / "base.yaml"]
    files += sorted((root / "providers").glob("*.yaml"))
    files.append(root / "environments" / f"{env}.yaml")
    files += [root / "profiles" / f"{name}.yaml" for name in chosen]

    missing = [f for f in files if not f.is_file()]
    if missing:
        raise ConfigurationError(f"config files not found: {', '.join(str(m) for m in missing)}")

    layered = _deep_merge_files(files)

    class _LayeredSettings(Settings):
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
                _MergedYamlSource(settings_cls, layered),
                file_secret_settings,
            )

    return _LayeredSettings(environment=cast(Environment, env))
