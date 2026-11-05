from earth_platform.settings.loader import load_settings
from earth_platform.settings.settings import Settings


def test_shared_dotenv_ignores_other_services_but_loads_platform_settings(
    tmp_path, monkeypatch
):
    app_env = tmp_path / "APP" / ".env"
    shared_env = tmp_path / ".env"
    app_env.parent.mkdir()
    app_env.write_text(
        "EARTH_ENGINE__BASE_URL=http://127.0.0.1:8001\n",
        encoding="utf-8",
    )
    shared_env.write_text(
        "\n".join(
            [
                "SATQUERY_PROFILE=quality",
                "GOOGLE_MAPS_API_KEY=not-a-platform-setting",
                "EARTH_ENGINE__KIND=http",
                "EARTH_ENGINE__BASE_URL=http://127.0.0.1:9000",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("EARTH_ENGINE__KIND", raising=False)
    monkeypatch.delenv("EARTH_ENGINE__BASE_URL", raising=False)

    settings = Settings(_env_file=(app_env, shared_env))

    assert settings.engine.kind == "http"
    assert settings.engine.base_url == "http://127.0.0.1:9000"


def test_layered_settings_filters_shared_dotenv_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    environments = config_dir / "environments"
    environments.mkdir(parents=True)
    (config_dir / "base.yaml").write_text("{}\n", encoding="utf-8")
    (environments / "development.yaml").write_text("{}\n", encoding="utf-8")

    shared_env = tmp_path / ".env"
    shared_env.write_text(
        "\n".join(
            [
                "SATQUERY_PROFILE=quality",
                "SATQUERY_HF_TOKEN=not-a-real-secret",
                "EARTH_ENGINE__KIND=http",
                "EARTH_ENGINE__BASE_URL=http://127.0.0.1:9000",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "env_file", (shared_env,))
    for name in ("EARTH_ENGINE__KIND", "EARTH_ENGINE__BASE_URL", "EARTH_ENV"):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings(
        environment="development",
        profiles=[],
        config_dir=config_dir,
    )

    assert settings.engine.kind == "http"
    assert settings.engine.base_url == "http://127.0.0.1:9000"
