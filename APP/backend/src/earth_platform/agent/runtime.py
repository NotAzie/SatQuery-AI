"""Platform session and event integration for the Engine-owned Agent runtime."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from pydantic import BaseModel, Field

from earth_platform.agent.events import (
    AgentEvent,
    EarthCommandIssued,
    EngineEventReceived,
    RunFailed,
)
from earth_platform.engine import EngineClient
from earth_platform.engine.models import (
    EngineAgentImage,
    EngineAgentSession,
    EngineEarthContext,
    EngineEarthObjectGeoJSON,
    EngineInvestigationEventPage,
    EngineInvestigationReport,
)
from earth_platform.sessions.models import Session
from earth_platform.sessions.repository import SessionStore
from earth_platform.shared.clock import utcnow
from earth_platform.shared.concurrency import KeyedLock
from earth_platform.shared.earth import EarthContext
from earth_platform.shared.errors import (
    ConflictError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from earth_platform.shared.ids import new_id
from earth_platform.vision.types import VisionContext


class AgentEventPublisher(Protocol):
    async def publish(self, session_id: str, event: AgentEvent) -> AgentEvent: ...


class AgentTurnRequest(BaseModel):
    message: str = Field(min_length=1)
    model_id: str | None = None
    execution_authorized: bool = False
    earth_context: EarthContext | None = None
    asset_ids: list[str] = Field(default_factory=list, max_length=8)
    vision_context: VisionContext = Field(default_factory=VisionContext)


log = logging.getLogger(__name__)


class AgentRuntime:
    """Delegates model/tool turns to SatQuery Engine and records its stream for the UI."""

    def __init__(
        self,
        engine: EngineClient,
        sessions: SessionStore,
        event_bus: AgentEventPublisher,
        default_model_id: str | None,
    ) -> None:
        self._engine = engine
        self._sessions = sessions
        self._event_bus = event_bus
        self._default_model_id = default_model_id
        self._session_locks: KeyedLock[str] = KeyedLock()

    async def engine_session_id(self, session_id: str) -> str:
        """Return the Engine session linked to a Platform session, creating it once if needed."""
        async with self.session_operation(session_id):
            session = await self._sessions.sessions.get(session_id)
            if session.engine_agent_session_id is not None:
                return session.engine_agent_session_id

            engine_session = await self._engine.create_agent_session()

            def link_engine_session(current: Session) -> None:
                if current.engine_agent_session_id is None:
                    current.engine_agent_session_id = engine_session.session_id
                    current.updated_at = utcnow()

            updated = await self._sessions.sessions.mutate(session_id, link_engine_session)
            if updated.engine_agent_session_id is None:
                raise RuntimeError("Engine session link was not persisted")
            return updated.engine_agent_session_id

    async def delete_platform_session(
        self,
        session_id: str,
        *,
        delete_session_assets: Callable[[str], Awaitable[None]],
    ) -> None:
        async with self.session_operation(session_id):
            session = await self._sessions.sessions.get(session_id)
            if session.engine_agent_session_id is not None:
                raise ConflictError(
                    "This session has an Engine-owned transcript; archive it instead of deleting "
                    "it until the Engine Agent API supports session deletion."
                )
            await delete_session_assets(session_id)
            await self._sessions.sessions.delete(session_id)

    @asynccontextmanager
    async def session_operation(self, session_id: str) -> AsyncIterator[None]:
        async with self._session_locks.hold(session_id):
            yield

    async def get_engine_session(self, session_id: str) -> EngineAgentSession:
        engine_session_id = await self.engine_session_id(session_id)
        return await self._engine.get_agent_session(engine_session_id)

    async def get_investigation_report(
        self, session_id: str, investigation_id: str
    ) -> EngineInvestigationReport:
        await self._require_session_investigation(session_id, investigation_id)
        return await self._engine.get_investigation_report(investigation_id)

    async def get_investigation_earth_objects(
        self, session_id: str, investigation_id: str
    ) -> EngineEarthObjectGeoJSON:
        await self._require_session_investigation(session_id, investigation_id)
        return await self._engine.get_investigation_earth_objects(investigation_id)

    async def get_investigation_events(
        self,
        session_id: str,
        investigation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> EngineInvestigationEventPage:
        transcript = await self._require_session_investigation(
            session_id, investigation_id
        )
        return await self._engine.get_investigation_events(
            transcript.session_id,
            investigation_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def _require_session_investigation(
        self, session_id: str, investigation_id: str
    ) -> EngineAgentSession:
        transcript = await self.get_engine_session(session_id)
        if investigation_id not in transcript.investigation_ids:
            raise NotFoundError(
                f"Investigation '{investigation_id}' is not linked to this session"
            )
        return transcript

    async def cancel_turn(self, session_id: str) -> None:
        engine_session_id = await self.engine_session_id(session_id)
        await self._engine.cancel_agent_turn(engine_session_id)

    async def stream_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str | None,
        execution_authorized: bool = False,
        earth_context: EngineEarthContext | None = None,
        attachments: list[EngineAgentImage] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        chosen_model_id = model_id or self._default_model_id
        if not chosen_model_id:
            raise UpstreamUnavailableError(
                "No Engine Agent model is configured; set agent.model_id or provide model_id"
            )

        engine_session_id = await self.engine_session_id(session_id)
        terminal_seen = False
        try:
            async for upstream in self._engine.stream_agent_turn(
                engine_session_id,
                message=message,
                model_id=chosen_model_id,
                execution_authorized=execution_authorized,
                earth_context=earth_context,
                attachments=attachments,
            ):
                if upstream.session_id != engine_session_id:
                    raise UpstreamUnavailableError(
                        "SatQuery Engine streamed an event for a different agent session"
                    )
                event: AgentEvent
                if upstream.kind == "earth.command":
                    event = EarthCommandIssued(
                        session_id=session_id,
                        conversation_id=session_id,
                        run_id=upstream.turn_id,
                        at=upstream.timestamp,
                        command=upstream.payload["command"],
                    )
                else:
                    event = EngineEventReceived(
                        session_id=session_id,
                        conversation_id=session_id,
                        run_id=upstream.turn_id,
                        engine_session_id=upstream.session_id,
                        engine_kind=upstream.kind,
                        engine_turn_id=upstream.turn_id,
                        engine_sequence=upstream.sequence,
                        engine_timestamp=upstream.timestamp,
                        payload=upstream.payload,
                    )
                yield await self._event_bus.publish(session_id, event)
                terminal_seen = terminal_seen or upstream.kind in {
                    "turn.completed",
                    "turn.cancelled",
                    "agent.error",
                }

            if not terminal_seen:
                yield await self._publish_failure(
                    session_id,
                    new_id("run"),
                    "engine_stream_ended",
                    "SatQuery Engine ended the Agent stream without a terminal event.",
                )
        except UpstreamUnavailableError as exc:
            yield await self._publish_failure(session_id, new_id("run"), exc.code, exc.message)
        except ValidationFailedError as exc:
            yield await self._publish_failure(session_id, new_id("run"), exc.code, exc.message)
        except Exception:
            log.exception("SatQuery Engine Agent stream failed", extra={"session_id": session_id})
            yield await self._publish_failure(
                session_id,
                new_id("run"),
                "engine_stream_failed",
                "The SatQuery Engine Agent stream failed; see server logs for details.",
            )

    async def _publish_failure(
        self, session_id: str, run_id: str, code: str, message: str
    ) -> AgentEvent:
        event = RunFailed(
            session_id=session_id,
            conversation_id=session_id,
            run_id=run_id,
            code=code,
            message=message,
        )
        return await self._event_bus.publish(session_id, event)
