import json
from pathlib import Path
from uuid import uuid4

import pytest
from satquery.errors import ConfigurationError, ExtensionError
from satquery.platform.config import PlatformConfig
from satquery.agent import InMemoryAgentSessionStore, SQLiteAgentSessionStore
from satquery.platform.earth_memory import InMemoryEarthMemory, SQLiteEarthMemory
from satquery.platform.execution_journal import SQLiteExecutionJournal
from satquery.platform.registry import (
    ENTRY_POINT_GROUPS,
    ComponentRegistry,
    PlatformRegistries,
)


def test_configuration_precedence_and_profiles(tmp_path):
    path = tmp_path / "satquery.json"
    path.write_text(
        json.dumps(
            {
                "profile": "testing",
                "execution": {"max_concurrency": 2},
                "profiles": {
                    "testing": {
                        "execution": {"max_concurrency": 3},
                        "connector": {"max_attempts": 2, "retry_safe": True},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config = PlatformConfig.load(
        config_path=path,
        environ={
            "SATQUERY_PLATFORM__EXECUTION__MAX_CONCURRENCY": "4",
            "SATQUERY_PLATFORM__CONNECTOR__TIMEOUT_SECONDS": "12.5",
        },
    )

    assert config.profile == "testing"
    assert config.execution.max_concurrency == 4
    assert config.connector.max_attempts == 2
    assert config.connector.retry_safe
    assert config.connector.timeout_seconds == 12.5
    assert config.logging.level == "WARNING"
    assert config.connector_policy().timeout_seconds == 12.5
    assert config.create_cache() is not None


def test_invalid_profile_or_setting_fails_loudly():
    with pytest.raises(ConfigurationError, match="Unknown platform profile"):
        PlatformConfig.load(environ={"SATQUERY_PLATFORM_PROFILE": "future"})
    with pytest.raises(ConfigurationError, match="Unknown platform settings"):
        PlatformConfig.load(
            environ={"SATQUERY_PLATFORM__CACHE__UNBOUNDED": "true"}
        )


def test_agent_model_timeout_is_configurable_and_must_be_finite_positive():
    defaults = PlatformConfig.load(environ={}).agent
    assert defaults.max_tool_rounds == 8
    assert defaults.max_tool_calls_per_turn == 24
    assert defaults.max_context_turns == 24

    config = PlatformConfig.load(
        environ={
            "SATQUERY_PLATFORM__AGENT__MODEL_TIMEOUT_SECONDS": "45.5",
            "SATQUERY_PLATFORM__AGENT__MAX_TOOL_ROUNDS": "12",
            "SATQUERY_PLATFORM__AGENT__MAX_TOOL_CALLS_PER_TURN": "36",
            "SATQUERY_PLATFORM__AGENT__MAX_CONTEXT_TURNS": "40",
        }
    )
    assert config.agent.model_timeout_seconds == 45.5
    assert config.agent.max_tool_rounds == 12
    assert config.agent.max_tool_calls_per_turn == 36
    assert config.agent.max_context_turns == 40

    for invalid in ("0", "-1", "NaN", "Infinity", "null"):
        with pytest.raises(ConfigurationError):
            PlatformConfig.load(
                environ={
                    "SATQUERY_PLATFORM__AGENT__MODEL_TIMEOUT_SECONDS": invalid,
                }
            )

    for field in (
        "MAX_TOOL_ROUNDS",
        "MAX_TOOL_CALLS_PER_TURN",
        "MAX_CONTEXT_TURNS",
    ):
        for invalid in ("0", "-1", "1.5", "true"):
            with pytest.raises(ConfigurationError):
                PlatformConfig.load(
                    environ={f"SATQUERY_PLATFORM__AGENT__{field}": invalid}
                )


def test_earth_memory_storage_is_opt_in_and_configurable():
    default_config = PlatformConfig.load(environ={})
    assert isinstance(default_config.create_earth_memory(), InMemoryEarthMemory)

    database_path = Path(__file__).resolve().parent / f".earth-memory-config-{uuid4().hex}.sqlite"
    try:
        configured = PlatformConfig.load(environ={
            "SATQUERY_PLATFORM__STORAGE__EARTH_MEMORY_PATH": str(database_path),
        })
        assert configured.storage.earth_memory_path == str(database_path)
        assert isinstance(configured.create_earth_memory(), SQLiteEarthMemory)
        journal = configured.create_execution_journal()
        assert isinstance(journal, SQLiteExecutionJournal)
        assert journal.path == database_path.resolve()
        assert database_path.is_file()
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{database_path}{suffix}")
            if candidate.exists():
                candidate.unlink()


def test_agent_session_store_uses_explicit_path_or_memory_default(tmp_path):
    default_config = PlatformConfig.load(environ={})
    assert isinstance(default_config.create_agent_session_store(), InMemoryAgentSessionStore)

    database_path = tmp_path / "agent-sessions.sqlite"
    config = PlatformConfig.load(
        environ={
            "SATQUERY_PLATFORM__STORAGE__AGENT_SESSIONS_PATH": str(database_path),
        }
    )
    store = config.create_agent_session_store()
    assert isinstance(store, SQLiteAgentSessionStore)
    assert store.path == database_path.resolve()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_numeric_configuration_rejects_non_finite_values(value):
    with pytest.raises(ConfigurationError, match="finite"):
        PlatformConfig.load(
            environ={"SATQUERY_PLATFORM__CONNECTOR__TIMEOUT_SECONDS": value}
        )


def test_component_registries_cover_all_extension_categories():
    registries = PlatformRegistries()
    expected = {
        "connectors",
        "tools",
        "models",
        "agents",
        "reasoners",
        "visualizers",
        "evaluators",
    }
    assert set(ENTRY_POINT_GROUPS) == expected
    for category in expected:
        registries.registry_for(category).register("sample", category)
        assert registries.registry_for(category).get("sample") == category


def test_registration_rejects_duplicates_unless_replacement_is_explicit():
    registry = ComponentRegistry()
    registry.register("component", object())
    with pytest.raises(ExtensionError, match="already registered"):
        registry.register("component", object())
    registry.register("component", "replacement", replace=True)
    assert registry.get("component") == "replacement"


def test_entry_point_discovery_uses_explicit_builder(monkeypatch):
    class FakeEntryPoint:
        name = "sample"

        def load(self):
            return "loaded extension"

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == "satquery.tools"
            return [FakeEntryPoint()]

    monkeypatch.setattr(
        "satquery.platform.registry.importlib.metadata.entry_points",
        lambda: FakeEntryPoints(),
    )
    registry = ComponentRegistry()
    discovered = registry.discover_entry_points(
        "satquery.tools",
        lambda loaded: ("sample", {"extension": loaded}),
    )

    assert discovered == ("sample",)
    assert registry.get("sample") == {"extension": "loaded extension"}
