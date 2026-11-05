import asyncio
import base64
import gc
import hashlib
import json
import sqlite3
import weakref
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from satquery.agent import (
    AgentEarthContext,
    AgentImageAttachment,
    AgentImageInput,
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
from satquery.errors import ValidationError as EngineValidationError
from satquery.platform.registry import ComponentRegistry
from satquery.platform.runtime import PlatformRuntime


class ScriptedReasoner:
    model_id = "fixture.reasoner"
    supports_vision = True

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []

    async def stream(self, messages, tools, *, system_prompt, cancellation):
        self.requests.append((messages, tools, system_prompt))
        for event in self.scripts.pop(0):
            if cancellation.is_set():
                return
            yield event


def _service(*scripts, **service_options):
    runtime = PlatformRuntime()
    models = ComponentRegistry()
    model = ScriptedReasoner(scripts)
    models.register(model.model_id, model)
    sessions = InMemoryAgentSessionStore()
    return (
        AgentTurnService(runtime, models, sessions, **service_options),
        model,
        sessions,
    )


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


def test_agent_turn_delivers_image_bytes_and_persists_only_attachment_reference(tmp_path):
    async def run():
        runtime = PlatformRuntime()
        models = ComponentRegistry()
        model = ScriptedReasoner(
            ((AgentModelEvent(kind="text_delta", text="The image is available."),),)
        )
        models.register(model.model_id, model)
        database_path = tmp_path / "agent-images.sqlite"
        sessions = SQLiteAgentSessionStore(database_path)
        service = AgentTurnService(runtime, models, sessions)
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/rXsAAAAASUVORK5CYII="
        )
        image = AgentImageInput(
            asset_id="platform-asset-1",
            mime_type="image/png",
            size_bytes=len(image_bytes),
            width=1,
            height=1,
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            data_base64=base64.b64encode(image_bytes).decode("ascii"),
        )
        session = service.create_session()

        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Describe this image",
                model_id=model.model_id,
                attachments=(image,),
            )
        ]

        assert events[-1].kind == "turn.completed"
        model_message = model.requests[0][0][-1]
        assert model_message.images[0].data == image_bytes
        assert model_message.images[0].asset_id == "platform-asset-1"
        persisted = SQLiteAgentSessionStore(database_path).get(
            session.session_id
        ).messages[0]
        assert persisted.attachments[0].sha256 == image.sha256
        assert persisted.images == ()
        with sqlite3.connect(database_path) as connection:
            serialized = connection.execute(
                "SELECT payload_json FROM satquery_agent_sessions WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()[0]
        assert image.data_base64 not in serialized

    asyncio.run(run())


def test_agent_rejects_images_before_turn_when_model_does_not_support_vision():
    async def run():
        service, model, sessions = _service(
            (AgentModelEvent(kind="text_delta", text="Should not run."),)
        )
        model.supports_vision = False
        image_bytes = b"\x89PNG\r\n\x1a\nimage"
        image = AgentImageInput(
            asset_id="platform-asset-1",
            mime_type="image/png",
            size_bytes=len(image_bytes),
            sha256=hashlib.sha256(image_bytes).hexdigest(),
            data_base64=base64.b64encode(image_bytes).decode("ascii"),
        )
        session = service.create_session()

        with pytest.raises(EngineValidationError, match="does not support image"):
            _ = [
                event
                async for event in service.stream_turn(
                    session.session_id,
                    "Describe this image",
                    model_id=model.model_id,
                    attachments=(image,),
                )
            ]
        assert sessions.get(session.session_id).messages == ()

    asyncio.run(run())


def test_agent_emits_typed_earth_command_and_scopes_investigation_targets():
    async def run():
        service, model, sessions = _service(
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="show-call",
                        tool_id="earth.command",
                        arguments={
                            "command": {
                                "type": "show_investigation",
                                "investigation_id": "investigation-1",
                            }
                        },
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (
                AgentModelEvent(kind="text_delta", text="Showing the investigation."),
                AgentModelEvent(kind="completed"),
            ),
        )
        session = service.create_session()
        session = sessions.save(
            session.model_copy(update={"investigation_ids": ("investigation-1",)}),
            expected_revision=session.revision,
        )

        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Show investigation-1 on the Earth",
                model_id=model.model_id,
            )
        ]

        command = next(item for item in events if item.kind == "earth.command")
        assert command.payload == {
            "command": {
                "type": "show_investigation",
                "investigation_id": "investigation-1",
            }
        }
        assert command.sequence < next(
            item.sequence for item in events if item.kind == "tool.completed"
        )
        assert "earth.command" in {
            item["name"] for item in model.requests[0][1]
        }
        tool_observation = json.loads(model.requests[1][0][-1].content)
        assert tool_observation == {
            "status": "requested",
            "workspace_application": "unconfirmed",
        }
        assert "does not confirm that the Earth workspace applied it" in (
            model.requests[1][2]
        )
        assert sessions.get(session.session_id).investigation_ids == (
            "investigation-1",
        )

    asyncio.run(run())


def test_agent_changes_visibility_only_for_a_layer_in_the_current_earth_context():
    async def run():
        service, model, _ = _service(
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="layer-call",
                        tool_id="earth.command",
                        arguments={
                            "command": {
                                "type": "set_layer_visibility",
                                "layer_id": "flights",
                                "visible": True,
                            }
                        },
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (
                AgentModelEvent(kind="text_delta", text="Aircraft are visible."),
                AgentModelEvent(kind="completed"),
            ),
        )
        session = service.create_session()
        earth_context = AgentEarthContext(
            camera={"position": {"lng": 0, "lat": 0}, "height_m": 1000},
            layers=({"layer_id": "flights", "visible": False},),
        )

        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Show aircraft",
                model_id=model.model_id,
                earth_context=earth_context,
            )
        ]

        command = next(item for item in events if item.kind == "earth.command")
        assert command.payload == {
            "command": {
                "type": "set_layer_visibility",
                "layer_id": "flights",
                "visible": True,
            }
        }

    asyncio.run(run())


def test_agent_rejects_layer_visibility_commands_outside_current_earth_context():
    async def run():
        service, _, _ = _service(
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="layer-call",
                        tool_id="earth.command",
                        arguments={
                            "command": {
                                "type": "set_layer_visibility",
                                "layer_id": "ships",
                                "visible": True,
                            }
                        },
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (
                AgentModelEvent(kind="text_delta", text="That layer is unavailable."),
                AgentModelEvent(kind="completed"),
            ),
        )
        session = service.create_session()
        earth_context = AgentEarthContext(
            camera={"position": {"lng": 0, "lat": 0}, "height_m": 1000},
            layers=({"layer_id": "flights", "visible": False},),
        )

        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Show ships",
                model_id="fixture.reasoner",
                earth_context=earth_context,
            )
        ]

        assert not any(item.kind == "earth.command" for item in events)
        assert any(
            item.kind == "tool.failed"
            and item.payload["detail"]
            == "earth.command can change visibility only for a layer in the current Earth context"
            for item in events
        )

    asyncio.run(run())


def test_agent_rejects_earth_commands_for_unlinked_investigations():
    async def run():
        service, model, _ = _service(
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="show-call",
                        tool_id="earth.command",
                        arguments={
                            "command": {
                                "type": "show_investigation",
                                "investigation_id": "not-linked",
                            }
                        },
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (
                AgentModelEvent(kind="text_delta", text="That investigation is unavailable."),
                AgentModelEvent(kind="completed"),
            ),
        )
        session = service.create_session()

        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Show not-linked on the Earth",
                model_id=model.model_id,
            )
        ]

        assert not any(item.kind == "earth.command" for item in events)
        assert any(
            item.kind == "tool.failed"
            and item.payload["detail"]
            == "earth.command can show only investigations linked to this Agent session"
            for item in events
        )

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


def test_agent_tool_call_budget_rejects_over_budget_batch_before_dispatch():
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
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="call-2",
                        tool_id="platform.capabilities",
                        arguments={},
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            max_tool_calls_per_turn=1,
        )
        session = service.create_session()

        events = [
            item
            async for item in service.stream_turn(
                session.session_id,
                "Inspect capabilities",
                model_id=model.model_id,
            )
        ]

        error = next(item for item in events if item.kind == "agent.error")
        assert error.payload["code"] == "tool_call_limit"
        assert not any(item.kind == "tool.started" for item in events)
        stored = sessions.get(session.session_id)
        assert [message.role for message in stored.messages] == ["user"]

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
                    attachments=(
                        AgentImageAttachment(
                            asset_id="platform-image",
                            mime_type="image/png",
                            size_bytes=12,
                            width=1,
                            height=1,
                            sha256="a" * 64,
                        ),
                    ),
                ),
            )
        }),
        expected_revision=created.revision,
    )

    restored = SQLiteAgentSessionStore(path).get(created.session_id)
    assert restored.revision == 2
    assert restored.messages[0].content == "Find drought indicators"
    assert restored.messages[0].attachments[0].asset_id == "platform-image"
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
    descriptors = tools.descriptors()
    assert [item.tool_id for item in descriptors] == sorted(
        item.tool_id for item in descriptors
    )
    execute = next(
        item for item in descriptors if item.tool_id == "investigation.execute"
    )
    assert execute.availability == "available"
    assert execute.requires_execution_authorization is True
    assert execute.model_visible_without_consent is False
    assert execute.model_visible_with_execution_consent is True
    assert execute.input_schema["required"] == ["investigation_id"]
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


def test_earth_context_rejects_payloads_over_the_encoded_size_limit():
    with pytest.raises(ValueError, match="512 KiB"):
        AgentEarthContext.model_validate(
            {
                "camera": {
                    "position": {"lng": 0, "lat": 0},
                    "height_m": 500000,
                },
                "overlays": [
                    {
                        "id": "overlay-1",
                        "features": [
                            {
                                "id": "feature-1",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [0, 0],
                                },
                                "properties": {"description": "x" * (512 * 1024)},
                            }
                        ],
                    }
                ],
            }
        )


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
            descriptors = client.get("/api/v1/agent/tools")
            assert descriptors.status_code == 200
            tools = descriptors.json()
            assert [item["tool_id"] for item in tools] == sorted(
                item["tool_id"] for item in tools
            )
            execute = next(
                item for item in tools
                if item["tool_id"] == "investigation.execute"
            )
            assert execute["requires_execution_authorization"] is True
            assert execute["model_visible_without_consent"] is False
            assert execute["model_visible_with_execution_consent"] is True
            assert "investigation_id" in execute["input_schema"]["properties"]
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
            invalid_context = client.post(
                f"/api/v1/agent/sessions/{session_id}/turns",
                json={
                    "message": "Do work",
                    "model_id": model.model_id,
                    "earth_context": {
                        "camera": {
                            "position": {"lng": 181, "lat": 0},
                            "height_m": 500000,
                        }
                    },
                },
            )
            invalid_overlay = client.post(
                f"/api/v1/agent/sessions/{session_id}/turns",
                json={
                    "message": "Inspect the visible overlay",
                    "model_id": model.model_id,
                    "earth_context": {
                        "camera": {
                            "position": {"lng": 0, "lat": 0},
                            "height_m": 500000,
                        },
                        "overlays": [
                            {
                                "id": "overlay-1",
                                "features": [
                                    {
                                        "id": "feature-1",
                                        "geometry": {
                                            "type": "Point",
                                            "coordinates": [181, 0],
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                },
            )
            assert invalid_context.status_code == 422
            assert invalid_overlay.status_code == 422
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


def test_agent_investigation_history_is_paged_and_session_scoped(monkeypatch):
    from fastapi.testclient import TestClient
    from satquery.api import create_app, set_engine
    from satquery.config import get_settings
    from satquery.orchestrator import SatQueryEngine

    engine = SatQueryEngine(get_settings())
    service = engine.agent_turn_service
    session = service.create_session()
    service.sessions.save(
        session.model_copy(
            update={
                "investigation_ids": (
                    "investigation-owned",
                    "investigation-empty",
                )
            }
        ),
        expected_revision=session.revision,
    )
    monkeypatch.setattr(
        engine.platform_runtime.investigation_service,
        "get",
        lambda investigation_id: SimpleNamespace(
            tasks=() if investigation_id == "investigation-empty" else ("task",)
        ),
    )
    monkeypatch.setattr(
        engine.platform_runtime,
        "compile_investigation_execution_plan",
        lambda _investigation: SimpleNamespace(plan_id="execution-1"),
    )
    records = [
        {
            "sequence": index,
            "plan_id": "execution-1",
            "event_type": f"task.completed-{index}",
            "timestamp": "2026-05-01T10:00:00Z",
            "payload": {"index": index},
            "previous_event_sha256": "0" * 64,
            "event_sha256": f"{index:064x}",
        }
        for index in range(1, 4)
    ]

    def execution_events(
        _plan_id: str, *, after_sequence: int = 0, limit: int | None = None
    ):
        events = [item for item in records if item["sequence"] > after_sequence]
        return tuple(events[:limit] if limit is not None else events)

    monkeypatch.setattr(
        engine.platform_runtime, "execution_events", execution_events
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            owned = client.get(
                f"/api/v1/agent/sessions/{session.session_id}/investigations/"
                "investigation-owned/events?limit=2"
            )
            continuation = client.get(
                f"/api/v1/agent/sessions/{session.session_id}/investigations/"
                "investigation-owned/events?after_sequence=2&limit=2"
            )
            empty = client.get(
                f"/api/v1/agent/sessions/{session.session_id}/investigations/"
                "investigation-empty/events"
            )
            unrelated = client.get(
                f"/api/v1/agent/sessions/{session.session_id}/investigations/"
                "investigation-unrelated/events"
            )
            invalid_limit = client.get(
                f"/api/v1/agent/sessions/{session.session_id}/investigations/"
                "investigation-owned/events?limit=201"
            )

        assert owned.status_code == 200
        assert [event["sequence"] for event in owned.json()["events"]] == [1, 2]
        assert owned.json()["next_sequence"] == 2
        assert owned.json()["has_more"] is True
        assert continuation.status_code == 200
        assert [event["sequence"] for event in continuation.json()["events"]] == [3]
        assert continuation.json()["next_sequence"] == 3
        assert continuation.json()["has_more"] is False
        assert empty.status_code == 200
        assert empty.json()["plan_id"] is None
        assert empty.json()["events"] == []
        assert unrelated.status_code == 422
        assert invalid_limit.status_code == 422
    finally:
        set_engine(None)


def test_agent_api_rejects_image_turn_before_sse_for_text_only_model():
    from fastapi.testclient import TestClient
    from satquery.api import create_app, set_engine
    from satquery.config import get_settings
    from satquery.orchestrator import SatQueryEngine

    engine = SatQueryEngine(get_settings())
    model = ScriptedReasoner(())
    model.supports_vision = False
    engine.platform_registries.reasoners.register(model.model_id, model)
    set_engine(engine)
    image_bytes = b"\x89PNG\r\n\x1a\nimage"
    try:
        with TestClient(create_app(get_settings())) as client:
            session = client.post("/api/v1/agent/sessions").json()
            response = client.post(
                f"/api/v1/agent/sessions/{session['session_id']}/turns",
                json={
                    "message": "Describe this image",
                    "model_id": model.model_id,
                    "attachments": [
                        {
                            "asset_id": "platform-image",
                            "mime_type": "image/png",
                            "size_bytes": len(image_bytes),
                            "sha256": hashlib.sha256(image_bytes).hexdigest(),
                            "data_base64": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    ],
                },
            )
            transcript = client.get(
                f"/api/v1/agent/sessions/{session['session_id']}"
            ).json()

        assert response.status_code == 422
        assert "does not support image attachments" in response.json()["detail"]
        assert transcript["messages"] == []
    finally:
        set_engine(None)


def test_agent_stream_exposes_typed_earth_command_sse_event():
    from fastapi.testclient import TestClient
    from satquery.api import create_app, set_engine
    from satquery.config import get_settings
    from satquery.orchestrator import SatQueryEngine

    engine = SatQueryEngine(get_settings())
    model = ScriptedReasoner(
        (
            (
                AgentModelEvent(
                    kind="tool_call",
                    tool_call=AgentToolCall(
                        call_id="fly-call",
                        tool_id="earth.command",
                        arguments={
                            "command": {
                                "type": "fly_to",
                                "target": {"lng": -122.4, "lat": 37.8},
                            }
                        },
                    ),
                ),
                AgentModelEvent(kind="completed"),
            ),
            (
                AgentModelEvent(kind="text_delta", text="Moved the Earth view."),
                AgentModelEvent(kind="completed"),
            ),
        )
    )
    engine.platform_registries.reasoners.register(model.model_id, model)
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post("/api/v1/agent/sessions")
            session_id = created.json()["session_id"]
            response = client.post(
                f"/api/v1/agent/sessions/{session_id}/turns",
                json={
                    "message": "Fly the globe to 37.8, -122.4",
                    "model_id": model.model_id,
                    "earth_context": {
                        "camera": {
                            "position": {"lng": -122.4, "lat": 37.8},
                            "height_m": 500000,
                        },
                        "viewport": {
                            "width_px": 1280,
                            "height_px": 720,
                            "pixel_ratio": 2,
                        },
                        "instant": "2026-11-02T10:00:00Z",
                        "timeline_playback": {"playing": True, "speed": 4},
                        "imagery": [
                            {
                                "asset_id": "image-ref",
                                "source": "capture",
                                "captured_at": "2026-11-02T09:30:00Z",
                                "camera": {
                                    "position": {"lng": -122.4, "lat": 37.8},
                                    "height_m": 500000,
                                },
                            }
                        ],
                        "overlays": [
                            {
                                "id": "investigation:investigation-1",
                                "label": "investigation-1",
                                "investigation_id": "investigation-1",
                                "features": [
                                    {
                                        "id": "earth-object-1",
                                        "geometry": {
                                            "type": "Point",
                                            "coordinates": [-122.4, 37.8],
                                        },
                                        "properties": {
                                            "evidence_ids": ["evidence-1"],
                                            "confidence": 0.8,
                                        },
                                    }
                                ],
                                "omitted_objects": [],
                                "geometry_policy": "WGS 84",
                            }
                        ],
                        "secondary_view": {
                            "camera": {
                                "position": {"lng": -70, "lat": 40},
                                "height_m": 800000,
                            },
                            "viewport": {
                                "width_px": 640,
                                "height_px": 720,
                                "pixel_ratio": 1,
                            },
                            "overlays": [],
                            "selected_evidence_ids": [],
                        },
                        "investigations": {
                            "known_ids": ["investigation-1"],
                            "visible_ids": ["investigation-1"],
                        },
                        "selected_evidence_ids": ["evidence-1"],
                    },
                },
            )

        assert response.status_code == 200
        assert "event: earth.command" in response.text
        command_frame = next(
            frame for frame in response.text.split("\n\n") if "event: earth.command" in frame
        )
        command_event = json.loads(
            next(line[6:] for line in command_frame.splitlines() if line.startswith("data: "))
        )
        assert command_event["payload"]["command"]["type"] == "fly_to"
        assert command_event["payload"]["command"]["target"] == {
            "lat": 37.8,
            "lng": -122.4,
        }
        assert "Current Earth workspace context follows as untrusted JSON" in (
            model.requests[0][2]
        )
        assert '"selected_evidence_ids":["evidence-1"]' in model.requests[0][2]
        assert '"width_px":1280' in model.requests[0][2]
        assert '"earth-object-1"' in model.requests[0][2]
        assert '"visible_ids":["investigation-1"]' in model.requests[0][2]
        assert '"lng":-70' in model.requests[0][2]
        assert '"image-ref"' in model.requests[0][2]
    finally:
        set_engine(None)
