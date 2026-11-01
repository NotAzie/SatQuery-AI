from typing import Annotated

from fastapi import APIRouter, Query

from earth_platform.api.deps import (
    AgentRuntimeDep,
    CapabilityDiscoveryDep,
    SessionStoreDep,
    WorkspaceMemoryDep,
)
from earth_platform.intelligence.models import CapabilitySnapshot, MemorySearchResponse

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/capabilities", response_model=CapabilitySnapshot)
async def get_capabilities(discovery: CapabilityDiscoveryDep) -> CapabilitySnapshot:
    return discovery.snapshot()


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
