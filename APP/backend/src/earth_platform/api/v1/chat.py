"""Conversation runs delegated to SatQuery Engine's Agent Interface."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from earth_platform.agent.runtime import AgentTurnRequest
from earth_platform.api.deps import (
    AgentRuntimeDep,
    RequestPlannerDep,
    SessionStoreDep,
    SettingsDep,
)
from earth_platform.engine.models import EngineAgentSession
from earth_platform.intelligence.models import RequestPlanResponse
from earth_platform.shared.errors import UpstreamUnavailableError, ValidationFailedError
from earth_platform.streaming.sse import SSEEventEncoder

_encoder = SSEEventEncoder()
router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions/{session_id}", response_model=EngineAgentSession)
async def get_agent_session(
    session_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineAgentSession:
    await store.sessions.get(session_id)
    return await runtime.get_engine_session(session_id)


@router.post("/sessions/{session_id}/turns")
async def stream_agent_turn(
    session_id: str,
    body: AgentTurnRequest,
    store: SessionStoreDep,
    settings: SettingsDep,
    runtime: AgentRuntimeDep,
    planner: RequestPlannerDep,
) -> StreamingResponse:
    session = await store.sessions.get(session_id)
    model_id = body.model_id or settings.agent.model_id
    if not model_id:
        raise UpstreamUnavailableError(
            "No Engine Agent model is configured; set agent.model_id or provide model_id"
        )
    transcript = await runtime.get_engine_session(session_id)
    plan = await planner.plan(session, body, transcript)
    if body.asset_ids:
        raise ValidationFailedError(
            "Image attachments are not accepted by the current Engine Agent API; no turn was sent."
        )

    async def events() -> AsyncIterator[bytes]:
        async for event in runtime.stream_turn(
            session_id,
            message=plan.request.engine_message,
            model_id=model_id,
            execution_authorized=body.execution_authorized,
        ):
            yield _encoder.encode(event)

    return StreamingResponse(
        events(),
        status_code=status.HTTP_200_OK,
        media_type=_encoder.content_type,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/sessions/{session_id}/plan",
    response_model=RequestPlanResponse,
)
async def plan_agent_turn(
    session_id: str,
    body: AgentTurnRequest,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
    planner: RequestPlannerDep,
) -> RequestPlanResponse:
    session = await store.sessions.get(session_id)
    transcript = await runtime.get_engine_session(session_id)
    return await planner.plan(session, body, transcript)


@router.post("/sessions/{session_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_agent_turn(
    session_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> None:
    await store.sessions.get(session_id)
    await runtime.cancel_turn(session_id)
