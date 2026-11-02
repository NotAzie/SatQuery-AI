import asyncio
from typing import Annotated

from fastapi import APIRouter, Query

from earth_platform.api.deps import (
    AgentRuntimeDep,
    CapabilityDiscoveryDep,
    EngineDep,
    SessionStoreDep,
    WorkspaceMemoryDep,
)
from earth_platform.intelligence.models import (
    CapabilitySnapshot,
    EngineDiscoveryResponse,
    MemorySearchResponse,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/capabilities", response_model=CapabilitySnapshot)
async def get_capabilities(discovery: CapabilityDiscoveryDep) -> CapabilitySnapshot:
    return discovery.snapshot()


@router.get("/engine-discovery", response_model=EngineDiscoveryResponse)
async def get_engine_discovery(engine: EngineDep) -> EngineDiscoveryResponse:
    image_capabilities, datasets, earth_capabilities, agent_tools = await asyncio.gather(
        engine.list_engine_image_capabilities(),
        engine.list_engine_datasets(),
        engine.get_engine_earth_capabilities(),
        engine.list_engine_agent_tools(),
    )
    return EngineDiscoveryResponse(
        image_capabilities=image_capabilities,
        datasets=datasets,
        earth_capabilities=earth_capabilities,
        agent_tools=agent_tools,
    )


@router.get(
    "/sessions/{session_id}/memory",
    response_model=MemorySearchResponse,
)
async def search_workspace_memory(
    session_id: str,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    sessions: SessionStoreDep,
    memory: WorkspaceMemoryDep,
    runtime: AgentRuntimeDep,
) -> MemorySearchResponse:
    session = await sessions.sessions.get(session_id)
    transcript = (
        await runtime.get_engine_session(session_id)
        if session.engine_agent_session_id is not None
        else None
    )
    return MemorySearchResponse(
        query=query,
        results=await memory.search(
            query,
            current_session_id=session.id,
            context=session.earth_context_snapshots[-1]
            if session.earth_context_snapshots
            else None,
            transcript=transcript,
            current_message=query,
        ),
    )
