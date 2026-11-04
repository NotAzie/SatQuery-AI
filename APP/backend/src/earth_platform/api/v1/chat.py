"""Conversation runs delegated to SatQuery Engine's Agent Interface."""

from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError as PydanticValidationError

from earth_platform.agent.runtime import AgentTurnRequest
from earth_platform.api.deps import (
    AgentRuntimeDep,
    ContainerDep,
    RequestPlannerDep,
    SessionStoreDep,
    SettingsDep,
)
from earth_platform.engine.models import (
    EngineAgentImage,
    EngineAgentSession,
    EngineEarthContext,
    EngineEarthObjectGeoJSON,
    EngineHypothesisCreateRequest,
    EngineHypothesisLifecycleResponse,
    EngineHypothesisMutationResponse,
    EngineHypothesisTransitionRequest,
    EngineInvestigationEventPage,
    EngineInvestigationReasoningResponse,
    EngineInvestigationReport,
    EngineInvestigationReproducibilityBundle,
    EngineObservation,
)
from earth_platform.intelligence.models import RequestPlanResponse
from earth_platform.shared.errors import UpstreamUnavailableError, ValidationFailedError
from earth_platform.streaming.sse import SSEEventEncoder
from earth_platform.vision.types import PrepareVisionRequest

_encoder = SSEEventEncoder()
router = APIRouter(prefix="/chat", tags=["chat"])


def _engine_image_mime_type(
    value: str,
) -> Literal["image/png", "image/jpeg", "image/webp", "image/tiff"]:
    match value:
        case "image/png":
            return "image/png"
        case "image/jpeg":
            return "image/jpeg"
        case "image/webp":
            return "image/webp"
        case "image/tiff":
            return "image/tiff"
        case _:
            raise ValidationFailedError(
                f"Image MIME type '{value}' is not supported by the Engine Agent API."
            )


@router.get("/sessions/{session_id}", response_model=EngineAgentSession)
async def get_agent_session(
    session_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineAgentSession:
    await store.sessions.get(session_id)
    return await runtime.get_engine_session(session_id)


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/report",
    response_model=EngineInvestigationReport,
)
async def get_investigation_report(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineInvestigationReport:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_report(session_id, investigation_id)


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/reasoning",
    response_model=EngineInvestigationReasoningResponse,
)
async def get_investigation_reasoning(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineInvestigationReasoningResponse:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_reasoning(session_id, investigation_id)


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/reproducibility",
    response_model=EngineInvestigationReproducibilityBundle,
)
async def get_investigation_reproducibility(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineInvestigationReproducibilityBundle:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_reproducibility(session_id, investigation_id)


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/observations",
    response_model=list[EngineObservation],
)
async def get_investigation_observations(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> list[EngineObservation]:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_observations(session_id, investigation_id)


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/earth-objects",
    response_model=EngineEarthObjectGeoJSON,
)
async def get_investigation_earth_objects(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineEarthObjectGeoJSON:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_earth_objects(session_id, investigation_id)


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/events",
    response_model=EngineInvestigationEventPage,
)
async def get_investigation_events(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> EngineInvestigationEventPage:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_events(
        session_id,
        investigation_id,
        after_sequence=after_sequence,
        limit=limit,
    )


@router.get(
    "/sessions/{session_id}/investigations/{investigation_id}/hypotheses",
    response_model=EngineHypothesisLifecycleResponse,
)
async def get_investigation_hypotheses(
    session_id: str,
    investigation_id: str,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineHypothesisLifecycleResponse:
    await store.sessions.get(session_id)
    return await runtime.get_investigation_hypotheses(session_id, investigation_id)


@router.post(
    "/sessions/{session_id}/investigations/{investigation_id}/hypotheses",
    response_model=EngineHypothesisMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_investigation_hypothesis(
    session_id: str,
    investigation_id: str,
    body: EngineHypothesisCreateRequest,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineHypothesisMutationResponse:
    await store.sessions.get(session_id)
    return await runtime.add_investigation_hypothesis(session_id, investigation_id, body)


@router.post(
    "/sessions/{session_id}/investigations/{investigation_id}/hypotheses/"
    "{hypothesis_id}/transitions",
    response_model=EngineHypothesisMutationResponse,
)
async def transition_investigation_hypothesis(
    session_id: str,
    investigation_id: str,
    hypothesis_id: str,
    body: EngineHypothesisTransitionRequest,
    store: SessionStoreDep,
    runtime: AgentRuntimeDep,
) -> EngineHypothesisMutationResponse:
    await store.sessions.get(session_id)
    return await runtime.transition_investigation_hypothesis(
        session_id, investigation_id, hypothesis_id, body
    )


@router.post("/sessions/{session_id}/turns")
async def stream_agent_turn(
    session_id: str,
    body: AgentTurnRequest,
    store: SessionStoreDep,
    settings: SettingsDep,
    runtime: AgentRuntimeDep,
    planner: RequestPlannerDep,
    container: ContainerDep,
) -> StreamingResponse:
    session = await store.sessions.get(session_id)
    model_id = body.model_id or settings.agent.model_id
    if not model_id:
        raise UpstreamUnavailableError(
            "No Engine Agent model is configured; set agent.model_id or provide model_id"
        )
    transcript = await runtime.get_engine_session(session_id)
    plan = await planner.plan(session, body, transcript)
    attachments: list[EngineAgentImage] = []
    if body.asset_ids:
        prepared = await container.vision_preparer.prepare(
            session_id,
            PrepareVisionRequest(
                asset_ids=body.asset_ids,
                context=plan.request.vision_context,
            ),
        )
        try:
            attachments = [
                EngineAgentImage(
                    asset_id=item.asset.id,
                    mime_type=_engine_image_mime_type(item.asset.mime_type),
                    size_bytes=item.asset.size_bytes,
                    width=item.asset.width,
                    height=item.asset.height,
                    sha256=item.asset.sha256,
                    data_base64=item.data_base64,
                )
                for item in prepared.assets
            ]
        except PydanticValidationError as exc:
            raise ValidationFailedError(
                "Image attachments exceed the Engine's supported structure or size limits."
            ) from exc
        if sum(item.size_bytes for item in attachments) > 40 * 1024 * 1024:
            raise ValidationFailedError(
                "Attached images exceed the Engine's 40 MiB per-turn limit."
            )
    try:
        earth_context = (
            EngineEarthContext.from_workspace(
                plan.request.earth_context,
                attached_images=attachments,
            )
            if plan.request.earth_context is not None
            else None
        )
    except PydanticValidationError as exc:
        raise ValidationFailedError(
            "EarthContext exceeds the Engine's supported structure or size limits."
        ) from exc

    async def events() -> AsyncIterator[bytes]:
        async for event in runtime.stream_turn(
            session_id,
            message=plan.request.engine_message,
            model_id=model_id,
            execution_authorized=body.execution_authorized,
            earth_context=earth_context,
            attachments=attachments,
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
