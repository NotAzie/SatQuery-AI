import asyncio

import pytest

from earth_platform.agent.events import RunCompleted
from earth_platform.sessions.models import Session
from earth_platform.sessions.sqlite import SQLiteSessionStore
from earth_platform.streaming.memory import InMemoryEventBus


@pytest.mark.asyncio
async def test_event_bus_replays_persisted_events_then_delivers_live_events(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    bus = InMemoryEventBus(store.events)
    first = RunCompleted(
        session_id=session.id,
        conversation_id="conversation-1",
        run_id="run-1",
    )
    saved = await bus.publish(session.id, first)
    assert saved.seq == 1

    replay = bus.subscribe(session.id, after_seq=0)
    assert (await anext(replay)).seq == 1
    live = asyncio.create_task(anext(replay))
    await asyncio.sleep(0)
    second = first.model_copy(update={"run_id": "run-2", "seq": None})
    published = await bus.publish(session.id, second)
    assert published.seq == 2
    assert (await asyncio.wait_for(live, timeout=1)).run_id == "run-2"

    await replay.aclose()
    await bus.aclose()
    await store.aclose()


@pytest.mark.asyncio
async def test_event_bus_rejects_mismatched_session_and_invalid_resume_cursor(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    bus = InMemoryEventBus(store.events)
    event = RunCompleted(
        session_id="session-1",
        conversation_id="conversation-1",
        run_id="run-1",
    )
    with pytest.raises(ValueError, match="session_id"):
        await bus.publish("session-2", event)
    with pytest.raises(ValueError, match="after_seq"):
        await anext(bus.subscribe("session-1", after_seq=-1))
    await bus.aclose()
    await store.aclose()


@pytest.mark.asyncio
async def test_event_bus_closes_subscriber_with_a_full_queue(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    bus = InMemoryEventBus(store.events)
    bus._subscriber_queue_size = 1
    replay = bus.subscribe(session.id)
    waiting = asyncio.create_task(anext(replay))
    await asyncio.sleep(0)

    event = RunCompleted(
        session_id=session.id,
        conversation_id="conversation-1",
        run_id="run-1",
    )
    await bus.publish(session.id, event)
    assert (await asyncio.wait_for(waiting, timeout=1)).seq == 1
    await bus.publish(session.id, event.model_copy(update={"run_id": "run-2", "seq": None}))

    await bus.aclose()
    await bus.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(replay)

    await store.aclose()


@pytest.mark.asyncio
async def test_event_bus_replays_in_bounded_pages_without_gaps_or_duplicates(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    bus = InMemoryEventBus(store.events, replay_window_events=2)
    event = RunCompleted(
        session_id=session.id,
        conversation_id="conversation-1",
        run_id="run-0",
    )
    for index in range(5):
        await bus.publish(
            session.id,
            event.model_copy(update={"run_id": f"run-{index}", "seq": None}),
        )

    replay = bus.subscribe(session.id, after_seq=0)
    received = [await anext(replay) for _ in range(5)]
    assert [item.seq for item in received] == [1, 2, 3, 4, 5]
    assert [item.run_id for item in received] == [f"run-{index}" for index in range(5)]

    await bus.aclose()
    with pytest.raises(StopAsyncIteration):
        await anext(replay)
    await store.aclose()
