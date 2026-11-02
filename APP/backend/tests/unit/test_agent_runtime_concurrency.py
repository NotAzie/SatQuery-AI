import asyncio
from datetime import UTC, datetime

import pytest

from earth_platform.agent.runtime import AgentRuntime
from earth_platform.engine.models import EngineAgentSession
from earth_platform.sessions.models import Session
from earth_platform.sessions.sqlite import SQLiteSessionStore
from earth_platform.shared.errors import ConflictError
from earth_platform.streaming.memory import InMemoryEventBus


class BlockingEngine:
    def __init__(self) -> None:
        self.create_calls = 0
        self.first_call_started = asyncio.Event()
        self.two_calls_started = asyncio.Event()
        self.release_creations = asyncio.Event()

    async def create_agent_session(self) -> EngineAgentSession:
        self.create_calls += 1
        call_number = self.create_calls
        if call_number == 1:
            self.first_call_started.set()
        elif call_number == 2:
            self.two_calls_started.set()
        await self.release_creations.wait()
        now = datetime.now(UTC)
        return EngineAgentSession(
            session_id=f"engine-session-{call_number}",
            created_at=now,
            updated_at=now,
        )


@pytest.mark.asyncio
async def test_engine_session_creation_is_single_flight_per_platform_session(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    engine = BlockingEngine()
    runtime = AgentRuntime(engine, store, InMemoryEventBus(store.events), None)

    first = asyncio.create_task(runtime.engine_session_id(session.id))
    tasks = [first]
    try:
        second = asyncio.create_task(runtime.engine_session_id(session.id))
        tasks.append(second)
        await asyncio.wait_for(engine.first_call_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert engine.create_calls == 1
        engine.release_creations.set()
        result = await asyncio.gather(*tasks)

        assert result == ["engine-session-1", "engine-session-1"]
        assert engine.create_calls == 1
        assert runtime._session_locks._entries == {}
    finally:
        engine.release_creations.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.aclose()


@pytest.mark.asyncio
async def test_engine_session_creation_for_distinct_sessions_runs_concurrently(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    sessions = [await store.sessions.create(Session()) for _ in range(2)]
    engine = BlockingEngine()
    runtime = AgentRuntime(engine, store, InMemoryEventBus(store.events), None)
    tasks = [
        asyncio.create_task(runtime.engine_session_id(session.id))
        for session in sessions
    ]

    try:
        await asyncio.wait_for(engine.two_calls_started.wait(), timeout=1)
    finally:
        engine.release_creations.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await store.aclose()

    assert len(set(results)) == 2
    assert set(results) == {"engine-session-1", "engine-session-2"}
    assert engine.create_calls == 2
    assert runtime._session_locks._entries == {}


@pytest.mark.asyncio
async def test_session_deletion_waits_for_engine_session_initialization(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    engine = BlockingEngine()
    runtime = AgentRuntime(engine, store, InMemoryEventBus(store.events), None)
    initialization = asyncio.create_task(runtime.engine_session_id(session.id))
    deletion: asyncio.Task[None] | None = None

    try:
        await asyncio.wait_for(engine.first_call_started.wait(), timeout=1)
        deletion = asyncio.create_task(
            runtime.delete_platform_session(
                session.id,
                delete_session_assets=no_asset_cleanup,
            )
        )
        await asyncio.sleep(0)
        engine.release_creations.set()

        assert await initialization == "engine-session-1"
        with pytest.raises(ConflictError, match="Engine-owned transcript"):
            await deletion
        saved = await store.sessions.get(session.id)
        assert saved.engine_agent_session_id == "engine-session-1"
        assert runtime._session_locks._entries == {}
    finally:
        engine.release_creations.set()
        tasks = [initialization]
        if deletion is not None:
            tasks.append(deletion)
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.aclose()


@pytest.mark.asyncio
async def test_failed_asset_cleanup_keeps_platform_session_for_retry(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    runtime = AgentRuntime(BlockingEngine(), store, InMemoryEventBus(store.events), None)

    async def fail_cleanup(_session_id: str) -> None:
        raise OSError("image store unavailable")

    with pytest.raises(OSError, match="image store unavailable"):
        await runtime.delete_platform_session(
            session.id,
            delete_session_assets=fail_cleanup,
        )

    assert await store.sessions.get(session.id) == session
    await store.aclose()


async def no_asset_cleanup(_session_id: str) -> None:
    return None
