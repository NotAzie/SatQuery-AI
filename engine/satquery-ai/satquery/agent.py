"""Model-neutral conversational bridge to SatQuery's deterministic engine."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import sqlite3
import threading
import weakref
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import Field, model_validator

from .errors import ExtensionError, SatQueryError, ValidationError
from .platform.contracts import Contract, EarthQuery
from .platform.earth_memory import EarthMemoryQuery
from .platform.registry import ComponentRegistry
from .platform.runtime import PlatformRuntime

logger = logging.getLogger("satquery.agent")

AgentEventKind = Literal[
    "turn.started",
    "assistant.delta",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "investigation.progress",
    "turn.completed",
    "turn.cancelled",
    "agent.error",
]

AGENT_SYSTEM_PROMPT = """You are the conversational reasoning interface for SatQuery, an Earth Intelligence platform.
SatQuery's deterministic engine owns planning, investigation design, execution, scheduling, evidence assessment, scientific reasoning, reports, and Earth Memory. Never reproduce or simulate those systems yourself: use the available tools.
Treat tool outputs as the source of truth. Distinguish recorded evidence from interpretation, preserve unknowns and limitations, and never claim scientific validation or confidence that the engine did not provide.
Create an investigation only when useful. Execute it only when the caller supplied execution authorization and the user requested acquisition. Otherwise explain the plan and ask the user to authorize execution.
Use investigation identifiers and source/evidence references when reporting results. Do not invent observations, datasets, or provider availability."""


class AgentToolCall(Contract):
    call_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(Contract):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    turn_id: str = Field(min_length=1)
    tool_calls: tuple[AgentToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    model_id: str | None = None


class AgentModelEvent(Contract):
    """Normalized user-visible text, a tool request, or model turn completion.

    Provider adapters must not map private reasoning or hidden tokens to
    ``text_delta``.
    """

    kind: Literal["text_delta", "tool_call", "completed"]
    text: str | None = None
    tool_call: AgentToolCall | None = None

    @model_validator(mode="after")
    def validate_event_payload(self) -> AgentModelEvent:
        if self.kind == "text_delta" and self.text is None:
            raise ValueError("text_delta events require text")
        if self.kind == "tool_call" and self.tool_call is None:
            raise ValueError("tool_call events require a tool call")
        if self.kind == "completed" and (self.text is not None or self.tool_call is not None):
            raise ValueError("completed events cannot carry text or a tool call")
        return self


class AgentModel(Protocol):
    """Provider adapter; models reason and request tools but never execute them."""

    model_id: str

    def stream(
        self,
        messages: tuple[AgentMessage, ...],
        tools: tuple[dict[str, Any], ...],
        *,
        system_prompt: str,
        cancellation: asyncio.Event,
    ) -> AsyncIterator[AgentModelEvent]: ...


class AgentSession(Contract):
    session_id: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime
    messages: tuple[AgentMessage, ...] = ()
    investigation_ids: tuple[str, ...] = ()


class AgentEvent(Contract):
    kind: AgentEventKind
    session_id: str
    turn_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentSessionConflict(ValueError):
    """The session changed since it was loaded by a concurrent turn."""


class AgentModelTimeout(TimeoutError):
    """A reasoning adapter exceeded the configured per-round deadline."""


class AgentSessionStore(Protocol):
    def create(self) -> AgentSession: ...
    def get(self, session_id: str) -> AgentSession: ...
    def save(self, session: AgentSession, *, expected_revision: int) -> AgentSession: ...


class InMemoryAgentSessionStore:
    """Process-local session repository with optimistic revision checks."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.RLock()

    def create(self) -> AgentSession:
        now = datetime.now(timezone.utc)
        session = AgentSession(
            session_id=f"agent-{uuid4().hex}",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AgentSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"agent session {session_id!r} was not found")
        return session

    def save(self, session: AgentSession, *, expected_revision: int) -> AgentSession:
        with self._lock:
            current = self._sessions.get(session.session_id)
            if current is None:
                raise KeyError(f"agent session {session.session_id!r} was not found")
            if current.revision != expected_revision:
                raise AgentSessionConflict(
                    f"agent session revision changed from {expected_revision} "
                    f"to {current.revision}"
                )
            updated = session.model_copy(update={
                "revision": expected_revision + 1,
                "updated_at": datetime.now(timezone.utc),
            })
            self._sessions[session.session_id] = updated
            return updated


class SQLiteAgentSessionStore:
    """Single-host durable session repository using atomic revision updates."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, busy_timeout_seconds: float = 5.0) -> None:
        if not math.isfinite(busy_timeout_seconds) or busy_timeout_seconds <= 0:
            raise ValueError("agent session SQLite busy timeout must be positive")
        database_path = Path(path).expanduser()
        if str(database_path) == ":memory:":
            raise ValueError("SQLiteAgentSessionStore requires a durable file path")
        self.path = database_path.resolve()
        self.busy_timeout_seconds = busy_timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS satquery_agent_sessions ("
                "session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
                "payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS satquery_agent_schema ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
                "version INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO satquery_agent_schema(singleton, version) VALUES (1, ?) "
                "ON CONFLICT(singleton) DO NOTHING",
                (self.SCHEMA_VERSION,),
            )
            row = connection.execute(
                "SELECT version FROM satquery_agent_schema WHERE singleton = 1"
            ).fetchone()
            if row is None or row[0] != self.SCHEMA_VERSION:
                raise ValueError("unsupported SatQuery agent-session schema version")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.path),
            timeout=self.busy_timeout_seconds,
            isolation_level=None,
        )
        try:
            connection.execute(
                f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}"
            )
            yield connection
        finally:
            connection.close()

    def create(self) -> AgentSession:
        now = datetime.now(timezone.utc)
        session = AgentSession(
            session_id=f"agent-{uuid4().hex}",
            created_at=now,
            updated_at=now,
        )
        self._write_new(session)
        return session

    def _write_new(self, session: AgentSession) -> None:
        payload = _canonical_json(session.model_dump(mode="json"))
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO satquery_agent_sessions VALUES (?, ?, ?, ?)",
                (
                    session.session_id,
                    session.revision,
                    payload,
                    _sha256(payload),
                ),
            )

    def get(self, session_id: str) -> AgentSession:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json, payload_sha256 FROM satquery_agent_sessions "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"agent session {session_id!r} was not found")
        payload, digest = row
        if _sha256(payload) != digest:
            raise ValueError(f"agent session {session_id!r} failed its content integrity check")
        return AgentSession.model_validate_json(payload)

    def save(self, session: AgentSession, *, expected_revision: int) -> AgentSession:
        updated = session.model_copy(update={
            "revision": expected_revision + 1,
            "updated_at": datetime.now(timezone.utc),
        })
        payload = _canonical_json(updated.model_dump(mode="json"))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    "UPDATE satquery_agent_sessions SET revision = ?, payload_json = ?, "
                    "payload_sha256 = ? WHERE session_id = ? AND revision = ?",
                    (
                        updated.revision,
                        payload,
                        _sha256(payload),
                        session.session_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount == 0:
                    exists = connection.execute(
                        "SELECT revision FROM satquery_agent_sessions WHERE session_id = ?",
                        (session.session_id,),
                    ).fetchone()
                    if exists is None:
                        raise KeyError(
                            f"agent session {session.session_id!r} was not found"
                        )
                    raise AgentSessionConflict(
                        f"agent session revision changed from {expected_revision} "
                        f"to {exists[0]}"
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return updated


class AgentTool(Protocol):
    tool_id: str
    description: str
    arguments_model: type[Contract]

    async def execute(self, runtime: PlatformRuntime, arguments: Contract) -> Any: ...


class AgentToolRegistry:
    """Explicit allowlist of Earth Intelligence operations exposed to models."""

    def __init__(self, tools: tuple[AgentTool, ...] = ()) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._lock = threading.RLock()
        for tool in tools:
            self.register(tool)

    def register(self, tool: AgentTool) -> None:
        key = tool.tool_id.strip()
        if not key:
            raise ExtensionError("Agent tools require a non-empty identifier")
        with self._lock:
            if key in self._tools:
                raise ExtensionError(f"Agent tool {key!r} is already registered")
            self._tools[key] = tool

    def get(self, tool_id: str) -> AgentTool:
        with self._lock:
            tool = self._tools.get(tool_id)
        if tool is None:
            raise KeyError(f"agent tool {tool_id!r} is not registered")
        return tool

    def definitions(self, *, allow_execution: bool) -> tuple[dict[str, Any], ...]:
        with self._lock:
            tools = tuple(self._tools[key] for key in sorted(self._tools))
        return tuple(
            {
                "name": item.tool_id,
                "description": item.description,
                "input_schema": item.arguments_model.model_json_schema(),
            }
            for item in tools
            if allow_execution or item.tool_id != "investigation.execute"
        )


class AgentTurnService:
    """One model/tool/observation loop over the existing SatQuery runtime."""

    def __init__(
        self,
        runtime: PlatformRuntime,
        models: ComponentRegistry[Any],
        sessions: AgentSessionStore,
        tools: AgentToolRegistry | None = None,
        *,
        max_tool_rounds: int = 8,
        max_context_turns: int = 24,
        model_timeout_seconds: float = 120.0,
    ) -> None:
        if max_tool_rounds < 1 or max_context_turns < 1:
            raise ValueError("agent loop limits must be positive")
        if not math.isfinite(model_timeout_seconds) or model_timeout_seconds <= 0:
            raise ValueError("agent model timeout must be finite and positive")
        self.runtime = runtime
        self.models = models
        self.sessions = sessions
        self.tools = tools or build_satquery_agent_tools()
        self.max_tool_rounds = max_tool_rounds
        self.max_context_turns = max_context_turns
        self.model_timeout_seconds = model_timeout_seconds
        self._session_locks: weakref.WeakValueDictionary[
            str, asyncio.Lock
        ] = weakref.WeakValueDictionary()
        self._session_locks_lock = threading.RLock()
        self._active_cancellations: dict[str, asyncio.Event] = {}

    def create_session(self) -> AgentSession:
        return self.sessions.create()

    def get_session(self, session_id: str) -> AgentSession:
        return self.sessions.get(session_id)

    def validate_model(self, model_id: str) -> AgentModel:
        try:
            model = self.models.get(model_id)
        except ExtensionError as exc:
            raise ExtensionError(
                f"Reasoning model {model_id!r} is not registered.",
                context={"model_id": model_id},
            ) from exc
        if getattr(model, "model_id", None) != model_id:
            raise ExtensionError(
                f"Reasoning model key {model_id!r} does not match adapter identity."
            )
        if not callable(getattr(model, "stream", None)):
            raise ExtensionError(
                f"Reasoning model {model_id!r} does not implement the streaming agent protocol."
            )
        return model

    def cancel(self, session_id: str) -> None:
        cancellation = self._active_cancellations.get(session_id)
        if cancellation is None:
            raise ValidationError("agent session has no active turn")
        cancellation.set()

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        with self._session_locks_lock:
            return self._session_locks.setdefault(session_id, asyncio.Lock())

    async def stream_turn(
        self,
        session_id: str,
        user_message: str,
        *,
        model_id: str,
        execution_authorized: bool = False,
    ) -> AsyncIterator[AgentEvent]:
        text = user_message.strip()
        if not text:
            raise ValidationError("agent user message must not be empty")
        if type(execution_authorized) is not bool:
            raise ValidationError("execution_authorized must be a boolean")
        async with self._session_lock(session_id):
            model = self.validate_model(model_id)
            cancellation = asyncio.Event()
            self._active_cancellations[session_id] = cancellation
            session: AgentSession | None = None
            turn_id: str | None = None
            assistant_text: list[str] = []
            try:
                session = self.sessions.get(session_id)
                turn_id = f"turn-{uuid4().hex}"
                sequence = 0

                def event(
                    kind: AgentEventKind,
                    payload: dict[str, Any] | None = None,
                ) -> AgentEvent:
                    nonlocal sequence
                    sequence += 1
                    return AgentEvent(
                        kind=kind,
                        session_id=session_id,
                        turn_id=turn_id,
                        sequence=sequence,
                        timestamp=datetime.now(timezone.utc),
                        payload=payload or {},
                    )

                def persist_partial_assistant() -> None:
                    nonlocal session
                    content = "".join(assistant_text)
                    if not content or session is None or turn_id is None:
                        return
                    session = self.sessions.save(
                        session.model_copy(update={
                            "messages": (
                                *session.messages,
                                AgentMessage(
                                    role="assistant",
                                    content=content,
                                    turn_id=turn_id,
                                    model_id=model_id,
                                ),
                            )
                        }),
                        expected_revision=session.revision,
                    )

                recovered_messages = _recover_interrupted_tool_calls(
                    session.messages
                )
                session = self.sessions.save(
                    session.model_copy(update={
                        "messages": (
                            *session.messages,
                            *recovered_messages,
                            AgentMessage(
                                role="user", content=text, turn_id=turn_id
                            ),
                        )
                    }),
                    expected_revision=session.revision,
                )
                yield event("turn.started", {
                    "model_id": model_id,
                    "execution_authorized": execution_authorized,
                })
                for tool_round in range(self.max_tool_rounds):
                    if cancellation.is_set():
                        persist_partial_assistant()
                        yield event("turn.cancelled")
                        return
                    assistant_text: list[str] = []
                    tool_calls: list[AgentToolCall] = []
                    try:
                        async for model_event in _stream_model_events(
                            model,
                            self._model_context(session.messages),
                            self.tools.definitions(
                                allow_execution=execution_authorized
                            ),
                            system_prompt=AGENT_SYSTEM_PROMPT,
                            cancellation=cancellation,
                            timeout_seconds=self.model_timeout_seconds,
                        ):
                            if cancellation.is_set():
                                persist_partial_assistant()
                                yield event("turn.cancelled")
                                return
                            if model_event.kind == "text_delta":
                                if model_event.text:
                                    assistant_text.append(model_event.text)
                                    yield event(
                                        "assistant.delta",
                                        {"text": model_event.text},
                                    )
                            elif model_event.kind == "tool_call":
                                if model_event.tool_call is None:
                                    raise ValueError(
                                        "reasoning model emitted an empty tool call"
                                    )
                                tool_calls.append(model_event.tool_call)
                            elif model_event.kind == "completed":
                                break
                    except AgentModelTimeout:
                        persist_partial_assistant()
                        logger.warning(
                            "Reasoning model exceeded its configured deadline",
                            extra={
                                "model_id": model_id,
                                "session_id": session_id,
                                "timeout_seconds": self.model_timeout_seconds,
                            },
                        )
                        yield event("agent.error", {
                            "code": "reasoning_model_timeout",
                            "detail": (
                                "Reasoning model exceeded the configured "
                                f"{self.model_timeout_seconds:g}-second per-round "
                                "deadline."
                            ),
                        })
                        return
                    except Exception:
                        persist_partial_assistant()
                        logger.exception(
                            "Reasoning model stream failed",
                            extra={"model_id": model_id, "session_id": session_id},
                        )
                        yield event("agent.error", {
                            "code": "reasoning_model_error",
                            "detail": "Reasoning model stream failed; consult service logs.",
                        })
                        return
                    if cancellation.is_set():
                        persist_partial_assistant()
                        yield event("turn.cancelled")
                        return
                    if len({item.call_id for item in tool_calls}) != len(tool_calls):
                        yield event("agent.error", {
                            "code": "invalid_model_response",
                            "detail": "reasoning model returned duplicate tool call IDs",
                        })
                        return
                    if not assistant_text and not tool_calls:
                        yield event("agent.error", {
                            "code": "invalid_model_response",
                            "detail": "reasoning model returned neither a response nor a tool call",
                        })
                        return
                    assistant = AgentMessage(
                        role="assistant",
                        content="".join(assistant_text),
                        turn_id=turn_id,
                        tool_calls=tuple(tool_calls),
                        model_id=model_id,
                    )
                    session = self.sessions.save(
                        session.model_copy(update={
                            "messages": (*session.messages, assistant)
                        }),
                        expected_revision=session.revision,
                    )
                    if not tool_calls:
                        yield event("turn.completed", {
                            "model_id": model_id,
                            "rounds": tool_round + 1,
                        })
                        return
                    assistant_text = []
                    for call in tool_calls:
                        if cancellation.is_set():
                            yield event("turn.cancelled")
                            return
                        yield event("tool.started", {
                            "tool_id": call.tool_id,
                            "call_id": call.call_id,
                        })
                        try:
                            tool = self.tools.get(call.tool_id)
                            if call.tool_id == "investigation.execute" and not execution_authorized:
                                raise ValidationError(
                                    "investigation execution requires caller authorization"
                                )
                            arguments = tool.arguments_model.model_validate(
                                call.arguments
                            )
                            if call.tool_id == "investigation.execute":
                                progress: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                                execution = asyncio.create_task(
                                    self._execute_with_progress(
                                        tool, arguments, cancellation, progress
                                    ),
                                    name="satquery-agent-investigation",
                                )
                                try:
                                    while not execution.done() or not progress.empty():
                                        try:
                                            progress_item = await asyncio.wait_for(
                                                progress.get(), timeout=0.1
                                            )
                                        except TimeoutError:
                                            continue
                                        yield event(
                                            "investigation.progress", progress_item
                                        )
                                    tool_result = _json_value(await execution)
                                except (asyncio.CancelledError, GeneratorExit):
                                    cancellation.set()
                                    try:
                                        await asyncio.shield(execution)
                                    except Exception:
                                        logger.exception(
                                            "Investigation execution failed during agent stream cancellation",
                                            extra={"session_id": session_id},
                                        )
                                    raise
                            else:
                                output = await tool.execute(self.runtime, arguments)
                                tool_result = _json_value(output)
                            ids = _investigation_ids(tool_result)
                            if ids:
                                session = session.model_copy(update={
                                    "investigation_ids": tuple(sorted(set(
                                        (*session.investigation_ids, *ids)
                                    )))
                                })
                            result_message = AgentMessage(
                                role="tool",
                                content=_canonical_json(tool_result),
                                turn_id=turn_id,
                                tool_call_id=call.call_id,
                                tool_name=call.tool_id,
                            )
                            session = self.sessions.save(
                                session.model_copy(update={
                                    "messages": (*session.messages, result_message)
                                }),
                                expected_revision=session.revision,
                            )
                            yield event("tool.completed", {
                                "tool_id": call.tool_id,
                                "call_id": call.call_id,
                                "result": tool_result,
                            })
                        except Exception as exc:
                            logger.warning(
                                "Agent tool call failed",
                                exc_info=True,
                                extra={
                                    "tool_id": call.tool_id,
                                    "session_id": session_id,
                                },
                            )
                            safe_detail = (
                                exc.message
                                if isinstance(exc, SatQueryError)
                                else str(exc)
                                if isinstance(exc, (ValueError, KeyError))
                                else "Tool execution failed; consult service logs."
                            )
                            error = {
                                "error": type(exc).__name__,
                                "detail": safe_detail,
                            }
                            session = self.sessions.save(
                                session.model_copy(update={
                                    "messages": (
                                        *session.messages,
                                        AgentMessage(
                                            role="tool",
                                            content=_canonical_json(error),
                                            turn_id=turn_id,
                                            tool_call_id=call.call_id,
                                            tool_name=call.tool_id,
                                        ),
                                    )
                                }),
                                expected_revision=session.revision,
                            )
                            yield event("tool.failed", {
                                "tool_id": call.tool_id,
                                "call_id": call.call_id,
                                **error,
                            })
                yield event("agent.error", {
                    "code": "tool_round_limit",
                    "detail": (
                        f"reasoning model exceeded {self.max_tool_rounds} "
                        "tool-calling rounds"
                    ),
                })
            except (asyncio.CancelledError, GeneratorExit):
                cancellation.set()
                try:
                    persist_partial_assistant()
                except Exception:
                    logger.exception(
                        "Could not persist partial assistant output during cancellation",
                        extra={"session_id": session_id},
                    )
                raise
            finally:
                cancellation.set()
                self._active_cancellations.pop(session_id, None)

    async def _execute_with_progress(
        self,
        tool: AgentTool,
        arguments: Contract,
        cancellation: asyncio.Event,
        progress: asyncio.Queue[dict[str, Any]],
    ) -> Any:
        investigation_id = getattr(arguments, "investigation_id")
        investigation = self.runtime.investigation_service.get(investigation_id)
        plan = self.runtime.compile_investigation_execution_plan(investigation)
        previous_events = self.runtime.execution_journal.events(plan.plan_id)
        after_sequence = max(
            (int(item["sequence"]) for item in previous_events), default=0
        )
        task = asyncio.create_task(tool.execute(self.runtime, arguments))
        while not task.done():
            if cancellation.is_set():
                self.runtime.cancel_investigation(investigation_id)
            for item in self.runtime.execution_journal.events(
                plan.plan_id, after_sequence=after_sequence
            ):
                after_sequence = max(after_sequence, int(item["sequence"]))
                progress.put_nowait(_json_value(item))
            await asyncio.wait((task,), timeout=0.1)
        for item in self.runtime.execution_journal.events(
            plan.plan_id, after_sequence=after_sequence
        ):
            after_sequence = max(after_sequence, int(item["sequence"]))
            progress.put_nowait(_json_value(item))
        result = await task
        return _json_value(result)

    def _model_context(
        self, messages: tuple[AgentMessage, ...]
    ) -> tuple[AgentMessage, ...]:
        turn_ids: list[str] = []
        for message in reversed(messages):
            if not turn_ids or turn_ids[-1] != message.turn_id:
                if message.turn_id not in turn_ids:
                    turn_ids.append(message.turn_id)
            if len(turn_ids) >= self.max_context_turns:
                break
        retained = set(turn_ids)
        return tuple(item for item in messages if item.turn_id in retained)


def build_satquery_agent_tools() -> AgentToolRegistry:
    return AgentToolRegistry((
        _CapabilitiesTool(),
        _StartInvestigationTool(),
        _ExecuteInvestigationTool(),
        _InspectInvestigationTool(),
        _SearchEarthMemoryTool(),
        _CancelInvestigationTool(),
    ))


class _Tool:
    tool_id: str
    description: str
    arguments_model: type[Contract]


class _CapabilitiesArgs(Contract):
    pass


class _CapabilitiesTool(_Tool):
    tool_id = "platform.capabilities"
    description = "Inspect locally declared Earth sensing capabilities and known limitations."
    arguments_model = _CapabilitiesArgs

    async def execute(self, runtime: PlatformRuntime, _arguments: Contract) -> Any:
        return runtime.perception_engine.build_capability_matrix()


class _StartInvestigationArgs(Contract):
    question: str = Field(min_length=1)
    earth_query: EarthQuery | None = None
    mission_id: str | None = None
    mission_name: str | None = None


class _StartInvestigationTool(_Tool):
    tool_id = "investigation.start"
    description = "Ask SatQuery's deterministic planner to create an investigation plan and lifecycle record. This does not acquire data."
    arguments_model = _StartInvestigationArgs

    async def execute(self, runtime: PlatformRuntime, arguments: Contract) -> Any:
        args = _StartInvestigationArgs.model_validate(arguments)
        return runtime.start_investigation(
            args.question,
            earth_query=args.earth_query,
            mission_id=args.mission_id,
            mission_name=args.mission_name,
        )


class _ExecuteInvestigationArgs(Contract):
    investigation_id: str = Field(min_length=1)
    resume: bool = False


class _ExecuteInvestigationTool(_Tool):
    tool_id = "investigation.execute"
    description = "Execute or explicitly resume an existing SatQuery investigation through its compiled workflow and scheduler."
    arguments_model = _ExecuteInvestigationArgs

    async def execute(self, runtime: PlatformRuntime, arguments: Contract) -> Any:
        args = _ExecuteInvestigationArgs.model_validate(arguments)
        return await runtime.execute_investigation(
            args.investigation_id, resume=args.resume
        )


class _InspectInvestigationArgs(Contract):
    investigation_id: str = Field(min_length=1)


class _InspectInvestigationTool(_Tool):
    tool_id = "investigation.inspect"
    description = "Read the existing investigation report, evidence assessment, reasoning report, and lifecycle state."
    arguments_model = _InspectInvestigationArgs

    async def execute(self, runtime: PlatformRuntime, arguments: Contract) -> Any:
        from .platform.reports import build_investigation_report

        args = _InspectInvestigationArgs.model_validate(arguments)
        investigation = runtime.investigation_service.get(args.investigation_id)
        return {
            "report": build_investigation_report(runtime, args.investigation_id),
            "assessment": runtime.get_evidence_assessment(args.investigation_id),
            "reasoning": runtime.get_scientific_reasoning(args.investigation_id),
            "investigation": investigation,
        }


class _SearchEarthMemoryArgs(EarthMemoryQuery):
    pass


class _SearchEarthMemoryTool(_Tool):
    tool_id = "earth-memory.search"
    description = "Search SatQuery's deterministic Earth Memory index using explicit filters; this does not create or infer knowledge."
    arguments_model = _SearchEarthMemoryArgs

    async def execute(self, runtime: PlatformRuntime, arguments: Contract) -> Any:
        return runtime.search_earth_memory(
            EarthMemoryQuery.model_validate(arguments.model_dump(mode="python"))
        )


class _CancelInvestigationArgs(Contract):
    investigation_id: str = Field(min_length=1)


class _CancelInvestigationTool(_Tool):
    tool_id = "investigation.cancel"
    description = "Request cooperative cancellation of an existing pending or executing SatQuery investigation."
    arguments_model = _CancelInvestigationArgs

    async def execute(self, runtime: PlatformRuntime, arguments: Contract) -> Any:
        args = _CancelInvestigationArgs.model_validate(arguments)
        return runtime.cancel_investigation(args.investigation_id)


def _investigation_ids(value: Any) -> tuple[str, ...]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            candidate = item.get("investigation_id")
            if isinstance(candidate, str) and candidate:
                found.add(candidate)
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(sorted(found))


def _recover_interrupted_tool_calls(
    messages: tuple[AgentMessage, ...],
) -> tuple[AgentMessage, ...]:
    pending: dict[tuple[str, str], AgentToolCall] = {}
    for message in messages:
        if message.role == "assistant":
            for call in message.tool_calls:
                pending[(message.turn_id, call.call_id)] = call
        elif message.role == "tool" and message.tool_call_id is not None:
            pending.pop((message.turn_id, message.tool_call_id), None)

    return tuple(
        AgentMessage(
            role="tool",
            content=_canonical_json({
                "error": "interrupted_tool_call",
                "detail": (
                    "The prior turn ended before this tool result was persisted. "
                    "Its outcome may be unknown; inspect SatQuery state before "
                    "requesting the operation again."
                ),
            }),
            turn_id=turn_id,
            tool_call_id=call.call_id,
            tool_name=call.tool_id,
        )
        for (turn_id, _call_id), call in sorted(pending.items())
    )


async def _stream_model_events(
    model: AgentModel,
    messages: tuple[AgentMessage, ...],
    tools: tuple[dict[str, Any], ...],
    *,
    system_prompt: str,
    cancellation: asyncio.Event,
    timeout_seconds: float,
) -> AsyncIterator[AgentModelEvent]:
    """Stream normalized events against one monotonic per-round deadline."""
    iterator = model.stream(
        messages,
        tools,
        system_prompt=system_prompt,
        cancellation=cancellation,
    ).__aiter__()
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                cancellation.set()
                raise AgentModelTimeout
            try:
                event = await asyncio.wait_for(
                    iterator.__anext__(),
                    timeout=remaining,
                )
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                cancellation.set()
                raise AgentModelTimeout from exc
            yield event
    except asyncio.CancelledError:
        cancellation.set()
        raise
    finally:
        if cancellation.is_set():
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()


def _json_value(value: Any) -> Any:
    if isinstance(value, Contract):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise TypeError(
        f"Agent tool output {type(value).__name__} is not JSON serializable"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
