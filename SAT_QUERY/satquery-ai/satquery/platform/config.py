"""Hierarchical, validated configuration for platform infrastructure."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ConfigurationError

PLATFORM_PROFILES = {"local", "development", "testing", "production"}
_PROFILE_DEFAULTS = {
    "local": {"logging": {"level": "INFO"}},
    "development": {"logging": {"level": "DEBUG"}},
    "testing": {"logging": {"level": "WARNING"}},
    "production": {"logging": {"level": "INFO"}},
}
_SECTIONS = {"execution", "connector", "cache", "logging", "storage", "monitoring"}


@dataclass(frozen=True)
class ExecutionConfig:
    max_concurrency: int


@dataclass(frozen=True)
class ConnectorConfig:
    timeout_seconds: float | None = None
    max_attempts: int = 1
    retry_safe: bool = False
    retry_delay_seconds: float = 0.25
    requests_per_second: float | None = None


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = True
    max_entries: int | None = 128
    ttl_seconds: float | None = None


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(frozen=True)
class StorageConfig:
    earth_memory_path: str | None = None
    lifecycle_path: str | None = None
    execution_path: str | None = None
    audit_path: str | None = None
    monitoring_path: str | None = None


@dataclass(frozen=True)
class MonitoringConfig:
    enabled: bool = False
    poll_interval_seconds: float = 15.0
    max_runs_per_tick: int = 10
    max_triggered_investigations_per_tick: int = 5
    max_concurrency: int = 2
    lease_seconds: float = 120.0


@dataclass(frozen=True)
class PlatformConfig:
    """Immutable snapshot merged from defaults, profile, file, and environment."""

    profile: str
    execution: ExecutionConfig
    connector: ConnectorConfig
    cache: CacheConfig
    logging: LoggingConfig
    storage: StorageConfig
    monitoring: MonitoringConfig

    @classmethod
    def load(
        cls,
        *,
        config_path: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> PlatformConfig:
        environment = os.environ if environ is None else environ
        file_config: dict[str, Any] = {}
        if config_path is None:
            config_path = environment.get("SATQUERY_PLATFORM_CONFIG")
        if config_path is not None:
            try:
                file_config = json.loads(Path(config_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigurationError(
                    f"Could not read platform configuration {str(config_path)!r}: {exc}",
                    context={"config_path": str(config_path)},
                ) from exc
            if not isinstance(file_config, dict):
                raise ConfigurationError("Platform configuration file must contain a JSON object.")

        env_config, env_profile = _environment_overrides(environment)
        selected_profile = (
            env_profile
            or _string_value(overrides, "profile")
            or _string_value(file_config, "profile")
            or "local"
        )
        if selected_profile not in PLATFORM_PROFILES:
            raise ConfigurationError(
                f"Unknown platform profile {selected_profile!r}.",
                context={"profile": selected_profile, "allowed": sorted(PLATFORM_PROFILES)},
            )

        profiles = file_config.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigurationError("The platform profiles setting must be an object.")
        profile_overrides = profiles.get(selected_profile, {})
        if not isinstance(profile_overrides, dict):
            raise ConfigurationError(
                f"Configuration for profile {selected_profile!r} must be an object."
            )

        effective: dict[str, Any] = {
            "profile": selected_profile,
            "execution": {"max_concurrency": os.cpu_count() or 1},
            "connector": {},
            "cache": {},
            "logging": {},
            "storage": {},
            "monitoring": {},
        }
        effective["cache"]["max_entries"] = 128
        _merge(effective, _PROFILE_DEFAULTS[selected_profile])
        _merge(effective, _without_control_keys(file_config))
        _merge(effective, profile_overrides)
        _merge(effective, _without_control_keys(dict(overrides or {})))
        _merge(effective, env_config)
        effective["profile"] = selected_profile
        return _validated_config(effective)

    def connector_policy(self):
        from .connectors import ConnectorPolicy

        return ConnectorPolicy(
            timeout_seconds=self.connector.timeout_seconds,
            max_attempts=self.connector.max_attempts,
            retry_safe=self.connector.retry_safe,
            retry_delay_seconds=self.connector.retry_delay_seconds,
            requests_per_second=self.connector.requests_per_second,
            cache_ttl_seconds=self.cache.ttl_seconds,
        )

    def create_cache(self):
        from .cache import MemoryCache

        if not self.cache.enabled:
            return None
        return MemoryCache(max_entries=self.cache.max_entries)

    def effective_storage_paths(self) -> dict[str, str | None]:
        """Return the database path each platform store will actually use.

        Unspecified stores intentionally share a configured database so local
        users can enable durable operation with one path. Keeping the fallback
        order here gives constructors and runtime diagnostics one source of
        truth.
        """
        storage = self.storage
        return {
            "earth_memory": storage.earth_memory_path or storage.monitoring_path,
            "lifecycle": (
                storage.lifecycle_path
                or storage.earth_memory_path
                or storage.monitoring_path
            ),
            "execution": (
                storage.execution_path
                or storage.earth_memory_path
                or storage.lifecycle_path
                or storage.monitoring_path
            ),
            "audit": (
                storage.audit_path
                or storage.earth_memory_path
                or storage.lifecycle_path
                or storage.execution_path
                or storage.monitoring_path
            ),
            "monitoring": (
                storage.monitoring_path
                or storage.earth_memory_path
                or storage.lifecycle_path
                or storage.execution_path
            ),
        }

    def create_earth_memory(self):
        from .earth_memory import InMemoryEarthMemory, SQLiteEarthMemory

        path = self.effective_storage_paths()["earth_memory"]
        if path is None:
            return InMemoryEarthMemory()
        return SQLiteEarthMemory(path)

    def create_lifecycle_repository(self):
        """Use the configured lifecycle path, or share durable Earth Memory storage."""
        from .investigations import SQLiteLifecycleRepository

        path = self.effective_storage_paths()["lifecycle"]
        return SQLiteLifecycleRepository(path) if path is not None else None

    def create_execution_journal(self):
        """Use durable local execution records when a platform storage path exists."""
        from .execution_journal import InMemoryExecutionJournal, SQLiteExecutionJournal

        path = self.effective_storage_paths()["execution"]
        return SQLiteExecutionJournal(path) if path is not None else InMemoryExecutionJournal()

    def create_audit_trail(self):
        """Use durable local audit storage when any platform store is configured."""
        from .scientific_governance import InMemoryAuditTrail, SQLiteAuditTrail

        path = self.effective_storage_paths()["audit"]
        return SQLiteAuditTrail(path) if path is not None else InMemoryAuditTrail()

    def create_monitoring_repository(self):
        """Use a durable schedule journal when any shared platform store is configured."""
        from .monitoring import InMemoryMonitoringRepository, SQLiteMonitoringRepository

        path = self.effective_storage_paths()["monitoring"]
        return SQLiteMonitoringRepository(path) if path is not None else InMemoryMonitoringRepository()


def _environment_overrides(
    environ: Mapping[str, str],
) -> tuple[dict[str, Any], str | None]:
    config: dict[str, Any] = {}
    profile = environ.get("SATQUERY_PLATFORM_PROFILE")
    for name, raw in environ.items():
        prefix = "SATQUERY_PLATFORM__"
        if not name.startswith(prefix):
            continue
        parts = name[len(prefix) :].lower().split("__")
        if len(parts) != 2 or parts[0] not in _SECTIONS or not parts[1]:
            raise ConfigurationError(
                f"Invalid platform environment setting {name!r}.",
                context={"setting": name},
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        config.setdefault(parts[0], {})[parts[1]] = value
    return config, profile


def _without_control_keys(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key not in {"profile", "profiles"}}


def _merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if key == "profile":
            continue
        if key not in _SECTIONS:
            raise ConfigurationError(
                f"Unknown platform configuration section {key!r}.",
                context={"section": key},
            )
        if not isinstance(value, Mapping):
            raise ConfigurationError(
                f"Platform configuration section {key!r} must be an object.",
                context={"section": key},
            )
        section = target.setdefault(key, {})
        section.update(value)


def _string_value(values: Mapping[str, Any] | None, key: str) -> str | None:
    if values is None or key not in values:
        return None
    value = values[key]
    if not isinstance(value, str):
        raise ConfigurationError(f"Platform setting {key!r} must be a string.")
    return value


def _validated_config(values: Mapping[str, Any]) -> PlatformConfig:
    allowed_fields = {
        "execution": {"max_concurrency"},
        "connector": {
            "timeout_seconds",
            "max_attempts",
            "retry_safe",
            "retry_delay_seconds",
            "requests_per_second",
        },
        "cache": {"enabled", "max_entries", "ttl_seconds"},
        "logging": {"level"},
        "storage": {
            "earth_memory_path", "lifecycle_path", "execution_path", "audit_path",
            "monitoring_path",
        },
        "monitoring": {
            "enabled", "poll_interval_seconds", "max_runs_per_tick",
            "max_triggered_investigations_per_tick", "max_concurrency", "lease_seconds",
        },
    }
    for section, fields in allowed_fields.items():
        section_values = values.get(section, {})
        if not isinstance(section_values, Mapping):
            raise ConfigurationError(f"Platform configuration {section!r} must be an object.")
        unknown = set(section_values).difference(fields)
        if unknown:
            raise ConfigurationError(
                f"Unknown platform settings in {section!r}: {sorted(unknown)}.",
                context={"section": section, "settings": sorted(unknown)},
            )

    execution = values["execution"]
    connector = values["connector"]
    cache = values["cache"]
    logging_values = values["logging"]
    storage = values["storage"]
    monitoring = values["monitoring"]

    concurrency = execution.get("max_concurrency")
    if type(concurrency) is not int or concurrency < 1:
        raise ConfigurationError("execution.max_concurrency must be a positive integer.")
    attempts = connector.get("max_attempts", 1)
    if type(attempts) is not int or attempts < 1:
        raise ConfigurationError("connector.max_attempts must be a positive integer.")
    retry_safe = connector.get("retry_safe", False)
    if type(retry_safe) is not bool:
        raise ConfigurationError("connector.retry_safe must be a boolean.")
    if attempts > 1 and not retry_safe:
        raise ConfigurationError(
            "connector.max_attempts greater than one requires connector.retry_safe=true."
        )
    retry_delay = _optional_number(connector.get("retry_delay_seconds", 0.25), "connector.retry_delay_seconds")
    if retry_delay < 0:
        raise ConfigurationError("connector.retry_delay_seconds must not be negative.")
    timeout = _optional_positive(connector.get("timeout_seconds"), "connector.timeout_seconds")
    rate = _optional_positive(connector.get("requests_per_second"), "connector.requests_per_second")
    ttl = _optional_positive(cache.get("ttl_seconds"), "cache.ttl_seconds")
    max_entries = cache.get("max_entries")
    if max_entries is not None and (type(max_entries) is not int or max_entries < 1):
        raise ConfigurationError("cache.max_entries must be a positive integer or null.")
    enabled = cache.get("enabled", True)
    if type(enabled) is not bool:
        raise ConfigurationError("cache.enabled must be a boolean.")
    level = logging_values.get("level", "INFO")
    if not isinstance(level, str) or level.upper() not in {
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    }:
        raise ConfigurationError("logging.level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")
    earth_memory_path = storage.get("earth_memory_path")
    lifecycle_path = storage.get("lifecycle_path")
    execution_path = storage.get("execution_path")
    audit_path = storage.get("audit_path")
    monitoring_path = storage.get("monitoring_path")
    for name, value in (
        ("storage.earth_memory_path", earth_memory_path),
        ("storage.lifecycle_path", lifecycle_path),
        ("storage.execution_path", execution_path),
        ("storage.audit_path", audit_path),
        ("storage.monitoring_path", monitoring_path),
    ):
        if value is not None and (
            not isinstance(value, str) or not value.strip() or value.strip() == ":memory:"
        ):
            raise ConfigurationError(
                f"{name} must be a non-empty durable file path or null."
            )
    monitoring_enabled = monitoring.get("enabled", False)
    if type(monitoring_enabled) is not bool:
        raise ConfigurationError("monitoring.enabled must be a boolean.")
    poll_interval = _optional_positive(
        monitoring.get("poll_interval_seconds", 15.0),
        "monitoring.poll_interval_seconds",
    )
    max_runs_per_tick = monitoring.get("max_runs_per_tick", 10)
    if type(max_runs_per_tick) is not int or max_runs_per_tick < 1:
        raise ConfigurationError("monitoring.max_runs_per_tick must be a positive integer.")
    max_triggered_investigations = monitoring.get(
        "max_triggered_investigations_per_tick", 5
    )
    if type(max_triggered_investigations) is not int or max_triggered_investigations < 1:
        raise ConfigurationError(
            "monitoring.max_triggered_investigations_per_tick must be a positive integer."
        )
    monitoring_concurrency = monitoring.get("max_concurrency", 2)
    if type(monitoring_concurrency) is not int or monitoring_concurrency < 1:
        raise ConfigurationError("monitoring.max_concurrency must be a positive integer.")
    monitoring_lease_seconds = _optional_positive(
        monitoring.get("lease_seconds", 120.0), "monitoring.lease_seconds"
    )
    if (
        monitoring_enabled
        and values["profile"] == "production"
        and not any((monitoring_path, earth_memory_path, lifecycle_path, execution_path))
    ):
        raise ConfigurationError(
            "Production monitoring requires a durable storage path for schedules and runs."
        )
    return PlatformConfig(
        profile=values["profile"],
        execution=ExecutionConfig(max_concurrency=concurrency),
        connector=ConnectorConfig(
            timeout_seconds=timeout,
            max_attempts=attempts,
            retry_safe=retry_safe,
            retry_delay_seconds=retry_delay,
            requests_per_second=rate,
        ),
        cache=CacheConfig(
            enabled=enabled,
            max_entries=max_entries,
            ttl_seconds=ttl,
        ),
        logging=LoggingConfig(level=level.upper()),
        storage=StorageConfig(
            earth_memory_path=earth_memory_path,
            lifecycle_path=lifecycle_path,
            execution_path=execution_path,
            audit_path=audit_path,
            monitoring_path=monitoring_path,
        ),
        monitoring=MonitoringConfig(
            enabled=monitoring_enabled,
            poll_interval_seconds=poll_interval,
            max_runs_per_tick=max_runs_per_tick,
            max_triggered_investigations_per_tick=max_triggered_investigations,
            max_concurrency=monitoring_concurrency,
            lease_seconds=monitoring_lease_seconds,
        ),
    )


def _optional_number(value: Any, name: str) -> float:
    if type(value) not in (int, float):
        raise ConfigurationError(f"{name} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigurationError(f"{name} must be finite.")
    return number


def _optional_positive(value: Any, name: str) -> float | None:
    if value is None:
        return None
    number = _optional_number(value, name)
    if number <= 0:
        raise ConfigurationError(f"{name} must be greater than zero or null.")
    return number
