import asyncio
import json
import sqlite3
import gc
import weakref
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from satquery.agent import (
    AgentMessage,
    AgentModelEvent,
    AgentSession,
    AgentSessionConflict,
    AgentToolCall,
    AgentToolRegistry,
    AgentTurnService,
    InMemoryAgentSessionStore,
    SQLiteAgentSessionStore,
    build_satquery_agent_tools,
)
from satquery.errors import ExtensionError
from satquery.platform.registry import ComponentRegistry
from satquery.platform.runtime import PlatformRuntime


class ScriptedReasoner:
    model_id = "fixture.reasoner"

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []

    async def stream(self, messages, tools, *, system_prompt, cancellation):
        self.requests.append((messages, tools, system_prompt))
        for event in self.scripts.pop(0):
            if cancellation.is_set():
                return
            yield event


def _service(*scripts):
    runtime = PlatformRuntime()
    models = ComponentRegistry()
    model = ScriptedReasoner(scripts)
    models.register(model.model_id, model)
    sessions = InMemoryAgentSessionStore()
    return AgentTurnService(runtime, models, sessions), model, sessions


def test_agent_loop_validates_dispatches_and_returns_tool_observation():
    async def run():
        service, model, sessions = _service(
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="call-1",
                        tool_id="platform.capabilities",
                        arguments={},
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (
                AgentModelEvent(kind="text_delta", text="I found the declared capabilities."),
                AgentModelEvent(kind="completed"),
            ),
        )
        session = service.create_session()
        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "What can SatQuery observe?",
                model_id=model.model_id,
            )
        ]

        assert [item.sequence for item in events] == list(range(1, len(events) + 1))
        assert [item.kind for item in events][-2:] == [
            "assistant.delta",
            "turn.completed",
        ]
        assert any(item.kind == "tool.completed" for item in events)
        assert "reasoning" not in {item.kind for item in events}
        assert "platform.capabilities" in {
            item["name"] for item in model.requests[0][1]
        }
        assert "investigation.execute" not in {
            item["name"] for item in model.requests[0][1]
        }
        assert "deterministic engine owns" in model.requests[0][2]
        stored = sessions.get(session.session_id)
        assert [message.role for message in stored.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert stored.messages[2].tool_call_id == "call-1"
        assert stored.messages[2].content.startswith('{"')

    asyncio.run(run())


def test_execution_requires_explicit_turn_authorization_and_tool_schemas_are_validated():
    async def run():
        service, model, _ = _service(
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="call-1",
                        tool_id="investigation.execute",
                        arguments={"investigation_id": "not-real"},
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (AgentModelEvent(kind="text_delta", text="Execution was not authorized."),),
        )
        session = service.create_session()
        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Run it",
                model_id=model.model_id,
                execution_authorized=False,
            )
        ]
        assert any(
            item.kind == "tool.failed"
            and item.payload["detail"]
            == "investigation execution requires caller authorization"
            for item in events
        )
        assert "investigation.execute" not in {
            item["name"] for item in model.requests[0][1]
        }

    asyncio.run(run())


def test_turn_reports_model_failures_as_explicit_events():
    class BrokenReasoner:
        model_id = "fixture.broken"

        async def stream(self, *_args, **_kwargs):
            yield AgentModelEvent(kind="text_delta", text="Partial result.")
            raise RuntimeError("provider unavailable")

    async def run():
        runtime = PlatformRuntime()
        models = ComponentRegistry()
        models.register("fixture.broken", BrokenReasoner())
        service = AgentTurnService(runtime, models, InMemoryAgentSessionStore())
        session = service.create_session()
        events = [
            item
            async for item in service.stream_turn(
                session.session_id, "Inspect a flood", model_id="fixture.broken"
            )
        ]
        assert events[-1].kind == "agent.error"
        assert events[-1].payload["code"] == "reasoning_model_error"
        assert events[-1].payload["detail"] == (
            "Reasoning model stream failed; consult service logs."
        )
        stored = service.get_session(session.session_id)
        assert [(message.role, message.content) for message in stored.messages] == [
            ("user", "Inspect a flood"),
            ("assistant", "Partial result."),
        ]

    asyncio.run(run())


def test_model_stream_deadline_emits_timeout_and_cleans_up_turn_state():
    async def run():
        class SlowReasoner:
            model_id = "fixture.slow"

            def __init__(self):
                self.cancellation = None

            async def stream(self, _messages, _tools, *, cancellation, **_kwargs):
                self.cancellation = cancellation
                yield AgentModelEvent(kind="text_delta", text="Partial before timeout.")
                await asyncio.Event().wait()

        model = SlowReasoner()
        models = ComponentRegistry()
        models.register(model.model_id, model)
        service = AgentTurnService(
            PlatformRuntime(),
            models,
            InMemoryAgentSessionStore(),
            model_timeout_seconds=0.02,
        )
        session = service.create_session()
        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Inspect the area",
                model_id=model.model_id,
            )
        ]

        assert events[-1].kind == "agent.error"
        assert events[-1].payload["code"] == "reasoning_model_timeout"
        assert "0.02-second per-round deadline" in events[-1].payload["detail"]
        assert model.cancellation is not None
        assert model.cancellation.is_set()
        assert session.session_id not in service._active_cancellations
        messages = service.get_session(session.session_id).messages
        assert [(message.role, message.content) for message in messages] == [
            ("user", "Inspect the area"),
            ("assistant", "Partial before timeout."),
        ]

    asyncio.run(run())


def test_task_cancellation_closes_provider_stream_and_sets_cancellation_token():
    async def run():
        started = asyncio.Event()
        closed = asyncio.Event()
        cancellation_tokens = []

        class WaitingReasoner:
            model_id = "fixture.cancellable"

            async def stream(self, _messages, _tools, *, cancellation, **_kwargs):
                cancellation_tokens.append(cancellation)
                started.set()
                try:
                    yield AgentModelEvent(kind="text_delta", text="Partial output.")
                    await asyncio.Event().wait()
                finally:
                    closed.set()

        models = ComponentRegistry()
        models.register("fixture.cancellable", WaitingReasoner())
        service = AgentTurnService(
            PlatformRuntime(),
            models,
            InMemoryAgentSessionStore(),
            model_timeout_seconds=1,
        )
        session = service.create_session()

        stream = service.stream_turn(
            session.session_id,
            "Wait for data",
            model_id="fixture.cancellable",
        )
        assert (await anext(stream)).kind == "turn.started"
        assert (await anext(stream)).kind == "assistant.delta"
        await started.wait()
        pending_event = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        pending_event.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending_event

        assert closed.is_set()
        assert cancellation_tokens[0].is_set()
        assert session.session_id not in service._active_cancellations
        messages = service.get_session(session.session_id).messages
        assert [(message.role, message.content) for message in messages] == [
            ("user", "Wait for data"),
            ("assistant", "Partial output."),
        ]

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_agent_service_rejects_invalid_model_deadlines(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        AgentTurnService(
            PlatformRuntime(),
            ComponentRegistry(),
            InMemoryAgentSessionStore(),
            model_timeout_seconds=timeout,
        )


def test_agent_cancellation_is_cooperative_and_emits_terminal_event():
    async def run():
        started = asyncio.Event()

        class WaitingReasoner:
            model_id = "fixture.waiting"

            async def stream(self, _messages, _tools, *, cancellation, **_kwargs):
                started.set()
                await cancellation.wait()
                if not cancellation.is_set():
                    yield AgentModelEvent(kind="text_delta", text="unreachable")

        models = ComponentRegistry()
        models.register("fixture.waiting", WaitingReasoner())
        service = AgentTurnService(
            PlatformRuntime(), models, InMemoryAgentSessionStore()
        )
        session = service.create_session()

        async def collect():
            return [
                event
                async for event in service.stream_turn(
                    session.session_id, "Wait", model_id="fixture.waiting"
                )
            ]

        task = asyncio.create_task(collect())
        await started.wait()
        service.cancel(session.session_id)
        events = await task
        assert events[-1].kind == "turn.cancelled"
        assert service.get_session(session.session_id).messages[0].role == "user"

    asyncio.run(run())


def test_investigation_progress_is_forwarded_from_the_existing_journal():
    class Journal:
        def __init__(self):
            self.items = []

        def events(self, _plan_id, *, after_sequence=0):
            return tuple(
                item for item in self.items if item["sequence"] > after_sequence
            )

    class Runtime:
        def __init__(self):
            self.execution_journal = Journal()
            self.investigation_service = SimpleNamespace(
                get=lambda investigation_id: SimpleNamespace(
                    investigation_id=investigation_id
                )
            )

        def compile_investigation_execution_plan(self, _investigation):
            return SimpleNamespace(plan_id="plan-1")

        def cancel_investigation(self, _investigation_id):
            return {"status": "cancellation_requested"}

        async def execute_investigation(self, investigation_id, *, resume=False):
            self.execution_journal.items.extend((
                {
                    "sequence": 1,
                    "plan_id": "plan-1",
                    "event_type": "execution.started",
                    "payload": {},
                },
                {
                    "sequence": 2,
                    "plan_id": "plan-1",
                    "event_type": "task.completed",
                    "payload": {"task_id": "observe-1"},
                },
            ))
            await asyncio.sleep(0)
            return {
                "investigation_id": investigation_id,
                "status": "succeeded",
                "resumed": resume,
            }

    async def run():
        runtime = Runtime()
        models = ComponentRegistry()
        model = ScriptedReasoner(
            (
                (
                    AgentModelEvent(
                        kind="tool_call",
                        tool_call=AgentToolCall(
                            call_id="execute-1",
                            tool_id="investigation.execute",
                            arguments={"investigation_id": "investigation-1"},
                        ),
                    ),
                    AgentModelEvent(kind="completed"),
                ),
                (AgentModelEvent(kind="text_delta", text="Completed."),),
            )
        )
        models.register(model.model_id, model)
        service = AgentTurnService(runtime, models, InMemoryAgentSessionStore())
        session = service.create_session()
        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Run the investigation",
                model_id=model.model_id,
                execution_authorized=True,
            )
        ]
        progress = [item.payload for item in events if item.kind == "investigation.progress"]
        assert [item["event_type"] for item in progress] == [
            "execution.started",
            "task.completed",
        ]
        assert any(item.kind == "tool.completed" for item in events)

    asyncio.run(run())


def test_closing_agent_stream_cancels_and_joins_investigation_task():
    class Journal:
        def __init__(self):
            self.items = []

        def events(self, _plan_id, *, after_sequence=0):
            return tuple(
                item for item in self.items if item["sequence"] > after_sequence
            )

    class Runtime:
        def __init__(self):
            self.execution_journal = Journal()
            self.execution_started = asyncio.Event()
            self.execution_finished = asyncio.Event()
            self.cancel_requested = asyncio.Event()
            self.investigation_service = SimpleNamespace(
                get=lambda investigation_id: SimpleNamespace(
                    investigation_id=investigation_id
                )
            )

        def compile_investigation_execution_plan(self, _investigation):
            return SimpleNamespace(plan_id="plan-close")

        def cancel_investigation(self, _investigation_id):
            self.cancel_requested.set()
            self.execution_finished.set()
            return {"status": "cancellation_requested"}

        async def execute_investigation(self, investigation_id, *, resume=False):
            self.execution_journal.items.append({
                "sequence": 1,
                "plan_id": "plan-close",
                "event_type": "execution.started",
                "payload": {},
            })
            self.execution_started.set()
            await self.execution_finished.wait()
            return {"investigation_id": investigation_id, "status": "cancelled"}

    async def run():
        runtime = Runtime()
        models = ComponentRegistry()
        model = ScriptedReasoner(
            ((
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="execute-1",
                        tool_id="investigation.execute",
                        arguments={"investigation_id": "investigation-close"},
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),)
        )
        models.register(model.model_id, model)
        service = AgentTurnService(
            runtime,
            models,
            InMemoryAgentSessionStore(),
        )
        session = service.create_session()
        turn = service.stream_turn(
            session.session_id,
            "Execute and report progress",
            model_id=model.model_id,
            execution_authorized=True,
        )

        assert (await anext(turn)).kind == "turn.started"
        assert (await anext(turn)).kind == "tool.started"
        progress = await anext(turn)
        assert progress.kind == "investigation.progress"
        await runtime.execution_started.wait()
        await turn.aclose()

        assert runtime.cancel_requested.is_set()
        assert runtime.execution_finished.is_set()
        assert session.session_id not in service._active_cancellations
        assert all(
            task.get_name() != "satquery-agent-investigation"
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )

    asyncio.run(run())


def test_unknown_model_is_rejected_before_a_turn_is_persisted():
    async def run():
        runtime = PlatformRuntime()
        service = AgentTurnService(
            runtime, ComponentRegistry(), InMemoryAgentSessionStore()
        )
        session = service.create_session()
        with pytest.raises(ExtensionError, match="not registered"):
            _ = [
                event
                async for event in service.stream_turn(
                    session.session_id, "Hello", model_id="missing"
                )
            ]

    asyncio.run(run())


def test_agent_session_sqlite_persists_revisioned_messages_and_checks_integrity(tmp_path):
    path = tmp_path / "agent-sessions.sqlite"
    store = SQLiteAgentSessionStore(path)
    created = store.create()
    updated = store.save(
        created.model_copy(update={
            "messages": (
                AgentMessage(
                    role="user",
                    content="Find drought indicators",
                    turn_id="turn-1",
                ),
            )
        }),
        expected_revision=created.revision,
    )

    restored = SQLiteAgentSessionStore(path).get(created.session_id)
    assert restored.revision == 2
    assert restored.messages[0].content == "Find drought indicators"
    with pytest.raises(AgentSessionConflict, match="revision changed"):
        store.save(updated, expected_revision=1)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE satquery_agent_sessions SET payload_json = ? WHERE session_id = ?",
            ('{"corrupt":true}', created.session_id),
        )
    with pytest.raises(ValueError, match="integrity check"):
        store.get(created.session_id)


def test_session_store_rejects_missing_sessions_and_database_memory_path():
    store = InMemoryAgentSessionStore()
    with pytest.raises(KeyError, match="not found"):
        store.get("missing")
    with pytest.raises(ValueError, match="durable file path"):
        SQLiteAgentSessionStore(":memory:")


def test_new_turn_repairs_unmatched_tool_calls_without_replaying_them():
    async def run():
        service, model, sessions = _service(
            (AgentModelEvent(kind="text_delta", text="I will inspect state first."),)
        )
        session = service.create_session()
        call_completed = AgentToolCall(
            call_id="already-done",
            tool_id="platform.capabilities",
        )
        call_interrupted = AgentToolCall(
            call_id="outcome-unknown",
            tool_id="investigation.execute",
            arguments={"investigation_id": "investigation-1"},
        )
        seeded = sessions.save(
            session.model_copy(update={
                "messages": (
                    AgentMessage(
                        role="user",
                        content="Original request",
                        turn_id="turn-interrupted",
                    ),
                    AgentMessage(
                        role="assistant",
                        turn_id="turn-interrupted",
                        tool_calls=(call_completed, call_interrupted),
                    ),
                    AgentMessage(
                        role="tool",
                        content='{"ok":true}',
                        turn_id="turn-interrupted",
                        tool_call_id=call_completed.call_id,
                        tool_name=call_completed.tool_id,
                    ),
                )
            }),
            expected_revision=session.revision,
        )

        events = [
            item
            async for item in service.stream_turn(
                seeded.session_id,
                "Continue safely",
                model_id=model.model_id,
            )
        ]

        assert events[-1].kind == "turn.completed"
        context = model.requests[0][0]
        assert [message.role for message in context[-2:]] == ["tool", "user"]
        recovery = json.loads(context[-2].content)
        assert recovery["error"] == "interrupted_tool_call"
        assert "outcome may be unknown" in recovery["detail"]
        assert context[-2].tool_call_id == call_interrupted.call_id
        assert context[-2].tool_name == "investigation.execute"
        assert sum(
            message.tool_call_id == call_completed.call_id
            for message in context
        ) == 1
        assert not any(item.kind == "tool.started" for item in events)

    asyncio.run(run())


def test_tool_registry_is_explicit_and_rejects_duplicate_ids():
    tools = build_satquery_agent_tools()
    assert "investigation.start" in {
        item["name"] for item in tools.definitions(allow_execution=False)
    }
    assert "investigation.execute" not in {
        item["name"] for item in tools.definitions(allow_execution=False)
    }
    assert "investigation.execute" in {
        item["name"] for item in tools.definitions(allow_execution=True)
    }
    tool = tools.get("platform.capabilities")
    with pytest.raises(ExtensionError, match="already registered"):
        AgentToolRegistry((tool, tool))


def test_session_contract_timestamps_are_explicit_and_timezone_aware():
    now = datetime.now(timezone.utc)
    session = AgentSession(
        session_id="agent-test",
        created_at=now,
        updated_at=now,
    )
    assert session.created_at.tzinfo is not None
    assert json.loads(session.model_dump_json())["session_id"] == "agent-test"


def test_idle_session_locks_are_released_instead_of_accumulating():
    service, _, _ = _service()
    lock = service._session_lock("idle-session")
    reference = weakref.ref(lock)
    assert "idle-session" in service._session_locks

    del lock
    gc.collect()

    assert reference() is None
    assert "idle-session" not in service._session_locks


def test_agent_session_and_turn_are_exposed_as_server_sent_events():
    from fastapi.testclient import TestClient

    from satquery.api import create_app, set_engine
    from satquery.config import get_settings
    from satquery.orchestrator import SatQueryEngine

    engine = SatQueryEngine(get_settings())
    model = ScriptedReasoner(
        ((AgentModelEvent(kind="text_delta", text="Hello from SatQuery."),),)
    )
    engine.platform_registries.reasoners.register(model.model_id, model)
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post("/api/v1/agent/sessions")
            assert created.status_code == 201
            session_id = created.json()["session_id"]
            restored = client.get(f"/api/v1/agent/sessions/{session_id}")
            assert restored.status_code == 200
            invalid_consent = client.post(
                f"/api/v1/agent/sessions/{session_id}/turns",
                json={
                    "message": "Do work",
                    "model_id": model.model_id,
                    "execution_authorized": 1,
                },
            )
            assert invalid_consent.status_code == 422
            stream = client.post(
                f"/api/v1/agent/sessions/{session_id}/turns",
                json={
                    "message": "Hello",
                    "model_id": model.model_id,
                },
            )
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            assert "event: assistant.delta" in stream.text
            assert "Hello from SatQuery." in stream.text
            assert "event: turn.completed" in stream.text
    finally:
        set_engine(None)
