import pytest

from earth_platform.sessions.models import Conversation, Session
from earth_platform.sessions.sqlite import SQLiteSessionStore
from earth_platform.shared.errors import NotFoundError


@pytest.mark.asyncio
async def test_sqlite_store_persists_sessions_conversations_and_events(tmp_path):
    database = tmp_path / "platform.sqlite3"
    store = SQLiteSessionStore(str(database))
    await store.open()

    session = await store.sessions.create(Session(title="Flood study"))
    conversation = await store.conversations.create(
        Conversation(session_id=session.id, title="Initial discussion")
    )
    await store.events.append(session.id, "test.event", {"value": 7})
    await store.aclose()

    reopened = SQLiteSessionStore(str(database))
    await reopened.open()
    assert (await reopened.sessions.get(session.id)).title == "Flood study"
    assert (await reopened.conversations.get(conversation.id)).title == "Initial discussion"
    assert await reopened.events.latest_seq(session.id) == 1
    replayed = [event async for event in reopened.events.read_after(session.id, 0)]
    assert replayed[0].payload == {"value": 7}
    await reopened.aclose()


@pytest.mark.asyncio
async def test_sqlite_store_cascades_session_delete_and_reports_missing_records(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    session = await store.sessions.create(Session())
    conversation = await store.conversations.create(Conversation(session_id=session.id))

    await store.sessions.delete(session.id)
    with pytest.raises(NotFoundError):
        await store.sessions.get(session.id)
    with pytest.raises(NotFoundError):
        await store.conversations.get(conversation.id)
    await store.aclose()
