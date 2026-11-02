import pytest
from fastapi import FastAPI

from earth_platform.container import build_container
from earth_platform.lifecycle import lifespan
from earth_platform.settings import Settings
from earth_platform.settings.models import SessionSettings


@pytest.mark.asyncio
async def test_failed_startup_closes_resources_in_reverse_order(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    container = build_container(settings)
    calls: list[str] = []

    async def open_sessions() -> None:
        calls.append("sessions.open")
        raise RuntimeError("session schema initialization failed")

    async def close_sessions() -> None:
        calls.append("sessions.close")

    async def close_event_bus() -> None:
        calls.append("event_bus.close")

    async def close_engine() -> None:
        calls.append("engine.close")

    monkeypatch.setattr(container.sessions, "open", open_sessions)
    monkeypatch.setattr(container.sessions, "aclose", close_sessions)
    monkeypatch.setattr(container.event_bus, "aclose", close_event_bus)
    monkeypatch.setattr(container.engine, "aclose", close_engine)
    monkeypatch.setattr("earth_platform.lifecycle.build_container", lambda _: container)

    app = FastAPI()
    app.state.settings = settings

    with pytest.raises(RuntimeError, match="schema initialization failed"):
        async with lifespan(app):
            pytest.fail("The application must not start when session initialization fails")

    assert calls == [
        "sessions.open",
        "engine.close",
        "event_bus.close",
        "sessions.close",
    ]
