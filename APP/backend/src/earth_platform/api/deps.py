from typing import Annotated

from fastapi import Depends, Request

from earth_platform.agent.runtime import AgentRuntime
from earth_platform.container import Container
from earth_platform.engine import EngineClient
from earth_platform.intelligence.capabilities import CapabilityDiscovery
from earth_platform.intelligence.memory import WorkspaceMemory
from earth_platform.intelligence.planner import RequestPlanner
from earth_platform.sessions.repository import SessionStore
from earth_platform.settings import Settings
from earth_platform.streaming.bus import EventBus


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def get_settings(container: Annotated[Container, Depends(get_container)]) -> Settings:
    return container.settings


def get_engine(container: Annotated[Container, Depends(get_container)]) -> EngineClient:
    return container.engine


def get_agent_runtime(container: Annotated[Container, Depends(get_container)]) -> AgentRuntime:
    return container.agent_runtime


def get_sessions(container: Annotated[Container, Depends(get_container)]) -> SessionStore:
    return container.sessions


def get_event_bus(container: Annotated[Container, Depends(get_container)]) -> EventBus:
    return container.event_bus


def get_request_planner(container: Annotated[Container, Depends(get_container)]) -> RequestPlanner:
    return container.request_planner


def get_workspace_memory(
    container: Annotated[Container, Depends(get_container)],
) -> WorkspaceMemory:
    return container.workspace_memory


def get_capability_discovery(
    container: Annotated[Container, Depends(get_container)],
) -> CapabilityDiscovery:
    return container.capability_discovery


ContainerDep = Annotated[Container, Depends(get_container)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[EngineClient, Depends(get_engine)]
AgentRuntimeDep = Annotated[AgentRuntime, Depends(get_agent_runtime)]
SessionStoreDep = Annotated[SessionStore, Depends(get_sessions)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
RequestPlannerDep = Annotated[RequestPlanner, Depends(get_request_planner)]
WorkspaceMemoryDep = Annotated[WorkspaceMemory, Depends(get_workspace_memory)]
CapabilityDiscoveryDep = Annotated[CapabilityDiscovery, Depends(get_capability_discovery)]
