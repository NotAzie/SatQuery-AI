import pytest

from earth_platform.agent.events import RunCompleted
from earth_platform.api.v1.streams import stream_session_events
from earth_platform.sessions.models import Session
from earth_platform.sessions.sqlite import SQLiteSessionStore
from earth_platform.settings import Settings
from earth_platform.settings.models import SessionSettings
from earth_platform.streaming.memory import InMemoryEventBus


@pytest.mark.asyncio
async def test_sse_route_replays_events_with_resume_id(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    bus = InMemoryEventBus(store.events)
    await bus.publish(
        session.id,
        RunCompleted(
            session_id=session.id,
            conversation_id="conversation-1",
            run_id="run-1",
        ),
    )
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    response = await stream_session_events(
        session.id,
        bus,
        store,
        settings,
        after_seq=0,
        last_event_id=None,
    )

    frames = response.body_iterator
    first_frame = await anext(frames)
    assert b"id: 1" in first_frame
    assert b'"type":"run.completed"' in first_frame
    await bus.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(frames)
    await store.aclose()
