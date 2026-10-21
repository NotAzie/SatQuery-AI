"""Configuration loading and validation."""

from __future__ import annotations

import pytest

from satquery.config import Settings, load_dotenv
from satquery.errors import ConfigurationError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("SATQUERY_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)


def test_defaults_are_usable_without_any_env():
    settings = Settings.from_env(dotenv_path=None)
    assert settings.profile == "quality"
    assert settings.clip_model == "openai/clip-vit-large-patch14"
    assert settings.grounding_scales == (0.5, 0.35, 0.25, 0.18)
    assert settings.grounding_max_windows == 320
    assert settings.device == "auto"
    assert settings.router_mode == "hybrid"
    assert settings.rsvlm_enabled is False
    assert settings.strong_backend_requested is False
    assert settings.llm_available is False


def test_platform_audit_storage_follows_durable_platform_configuration(tmp_path):
    from satquery.platform.config import PlatformConfig
    from satquery.platform.scientific_governance import SQLiteAuditTrail

    database = tmp_path / "platform.sqlite"
    config = PlatformConfig.load(
        environ={}, overrides={"storage": {"earth_memory_path": str(database)}}
    )
    audit = config.create_audit_trail()
    assert isinstance(audit, SQLiteAuditTrail)
    audit.append(
        aggregate_id="investigation-1", event_type="planning", actor="planner",
        payload={"plan": "p1"},
    )
    assert SQLiteAuditTrail(database).verify("investigation-1")

    dedicated_path = tmp_path / "audit-only.sqlite"
    dedicated = PlatformConfig.load(
        environ={}, overrides={"storage": {"audit_path": str(dedicated_path)}}
    )
    assert isinstance(dedicated.create_audit_trail(), SQLiteAuditTrail)
    assert dedicated.create_audit_trail().path == dedicated_path


def test_effective_storage_paths_are_the_same_paths_used_by_store_factories():
    from satquery.platform.config import PlatformConfig

    shared_path = ".satquery-shared.sqlite"
    shared = PlatformConfig.load(
        environ={}, overrides={"storage": {"monitoring_path": str(shared_path)}}
    )
    assert set(shared.effective_storage_paths().values()) == {str(shared_path)}

    execution_path = ".satquery-execution.sqlite"
    dedicated = PlatformConfig.load(
        environ={}, overrides={"storage": {"execution_path": str(execution_path)}}
    )
    assert dedicated.effective_storage_paths() == {
        "earth_memory": None,
        "lifecycle": None,
        "execution": execution_path,
        "audit": execution_path,
        "monitoring": execution_path,
    }


def test_env_overrides_are_typed(monkeypatch):
    monkeypatch.setenv("SATQUERY_DEVICE", "cpu")
    monkeypatch.setenv("SATQUERY_BATCH_SIZE", "4")
    monkeypatch.setenv("SATQUERY_MAX_UPLOAD_MB", "2.5")
    monkeypatch.setenv("SATQUERY_ALLOW_IMAGE_PATHS", "no")
    monkeypatch.setenv("SATQUERY_GROUNDING_SCALES", "0.6, 0.4 ,0.2")

    settings = Settings.from_env(dotenv_path=None)
    assert settings.device == "cpu"
    assert settings.inference_batch_size == 4
    assert settings.max_upload_mb == 2.5
    assert settings.allow_image_paths is False
    assert settings.grounding_scales == (0.6, 0.4, 0.2)


def test_fast_profile_is_explicit_and_latency_first(monkeypatch):
    monkeypatch.setenv("SATQUERY_PROFILE", "fast")
    settings = Settings.from_env(dotenv_path=None)
    assert settings.clip_model == "openai/clip-vit-base-patch32"
    assert settings.grounding_scales == (0.5,)
    assert settings.grounding_max_windows == 16
    assert settings.grounding_stride_ratio == 0.9


def test_invalid_device_is_rejected_with_guidance(monkeypatch):
    monkeypatch.setenv("SATQUERY_DEVICE", "tpu")
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env(dotenv_path=None)
    assert excinfo.value.remediation


def test_invalid_integer_is_rejected(monkeypatch):
    monkeypatch.setenv("SATQUERY_BATCH_SIZE", "lots")
    with pytest.raises(ConfigurationError):
        Settings.from_env(dotenv_path=None)


def test_invalid_boolean_is_rejected(monkeypatch):
    monkeypatch.setenv("SATQUERY_RSVLM_ENABLED", "perhaps")
    with pytest.raises(ConfigurationError):
        Settings.from_env(dotenv_path=None)


def test_rsvlm_enabled_without_path_is_rejected(monkeypatch):
    monkeypatch.setenv("SATQUERY_RSVLM_ENABLED", "true")
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env(dotenv_path=None)
    assert "SATQUERY_RSVLM_PATH" in excinfo.value.message


def test_rsvlm_path_implies_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("SATQUERY_RSVLM_PATH", str(tmp_path))
    settings = Settings.from_env(dotenv_path=None)
    assert settings.rsvlm_enabled is True
    assert settings.strong_backend_requested is True


def test_llm_router_without_key_is_rejected(monkeypatch):
    monkeypatch.setenv("SATQUERY_ROUTER", "llm")
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env(dotenv_path=None)
    assert any("OPENAI_API_KEY" in line for line in excinfo.value.remediation)


def test_llm_router_with_key_is_accepted(monkeypatch):
    monkeypatch.setenv("SATQUERY_ROUTER", "llm")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings.from_env(dotenv_path=None)
    assert settings.llm_available is True


def test_missing_image_root_directory_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("SATQUERY_IMAGE_ROOT", str(tmp_path / "nowhere"))
    with pytest.raises(ConfigurationError):
        Settings.from_env(dotenv_path=None)


def test_out_of_range_grounding_percentile_is_rejected(monkeypatch):
    monkeypatch.setenv("SATQUERY_GROUNDING_PERCENTILE", "140")
    with pytest.raises(ConfigurationError):
        Settings.from_env(dotenv_path=None)


def test_dotenv_is_parsed_without_python_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# a comment",
                "SATQUERY_DEVICE=cpu",
                'export SATQUERY_CLIP_MODEL="my-org/clip-rs"',
                "SATQUERY_PORT=9100",
                "malformed line without equals",
            ]
        ),
        encoding="utf-8",
    )
    load_dotenv(env_file, override=True)
    settings = Settings.from_env(dotenv_path=None)
    assert settings.device == "cpu"
    assert settings.clip_model == "my-org/clip-rs"
    assert settings.port == 9100


def test_describe_redacts_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.setenv("HF_TOKEN", "hf_secret_value")
    described = Settings.from_env(dotenv_path=None).describe()
    assert described["llm_api_key"] == "set"
    assert described["hf_token"] == "set"
    assert "sk-secret-value" not in str(described)
    assert "hf_secret_value" not in str(described)
