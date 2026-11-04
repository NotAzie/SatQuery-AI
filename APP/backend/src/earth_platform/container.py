"""Composition root: the only place concrete implementations are chosen and wired.

Concrete adapters and stores are selected and wired here; request handlers receive only the
dependencies they need.
"""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from earth_platform.agent.runtime import AgentRuntime
from earth_platform.agent.tools import ToolSource
from earth_platform.earth.layers import LayerRegistry
from earth_platform.engine import EngineClient, EngineUnavailableError, build_engine_client
from earth_platform.intelligence.capabilities import CapabilityDiscovery
from earth_platform.intelligence.context import ConversationContextBuilder
from earth_platform.intelligence.earth_context import EarthContextBuilder
from earth_platform.intelligence.memory import WorkspaceMemory
from earth_platform.intelligence.planner import PromptAssembler, RequestPlanner
from earth_platform.intelligence.recommendations import RecommendationEngine
from earth_platform.llm.provider import ProviderFactory
from earth_platform.projects import ProjectRepository, SQLiteProjectRepository
from earth_platform.sessions import SessionStore, SQLiteSessionStore
from earth_platform.settings import Settings
from earth_platform.shared.registry import Registry
from earth_platform.streaming import EventBus
from earth_platform.streaming.memory import InMemoryEventBus
from earth_platform.vision.filesystem import FilesystemImageIngestor, FilesystemImageStore
from earth_platform.vision.multimodal import MultimodalPreparer
from earth_platform.vision.preparation import StoredImagePreparer
from earth_platform.vision.store import ImageStore

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    engine: EngineClient
    sessions: SessionStore
    projects: ProjectRepository
    event_bus: EventBus
    agent_runtime: AgentRuntime
    provider_factories: Registry[ProviderFactory]
    tool_sources: Registry[ToolSource]
    earth_layers: LayerRegistry
    image_store: ImageStore
    image_ingestor: FilesystemImageIngestor
    vision_preparer: MultimodalPreparer
    workspace_memory: WorkspaceMemory
    capability_discovery: CapabilityDiscovery
    request_planner: RequestPlanner
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack)

    async def start(self) -> None:
        self._stack.push_async_callback(self.sessions.aclose)
        self._stack.push_async_callback(self.projects.aclose)
        self._stack.push_async_callback(self.event_bus.aclose)
        self._stack.push_async_callback(self.engine.aclose)
        await self.sessions.open()
        await self.projects.open()
        try:
            await self.engine.connect()
        except EngineUnavailableError as exc:
            # The platform stays up and reports degraded readiness; chat that needs the Engine
            # will fail with a clear error rather than the whole process refusing to boot.
            log.warning("engine not reachable at startup: %s", exc.message)

    async def aclose(self) -> None:
        await self._stack.aclose()


def build_container(settings: Settings) -> Container:
    sessions = SQLiteSessionStore(settings.sessions.dsn)
    projects = SQLiteProjectRepository(settings.sessions.dsn)
    engine = build_engine_client(settings.engine)
    event_bus = InMemoryEventBus(
        sessions.events,
        replay_window_events=settings.streaming.replay_window_events,
    )
    image_store = FilesystemImageStore(settings.vision.store_path)
    provider_factories = Registry[ProviderFactory]("llm provider factory")
    tool_sources = Registry[ToolSource]("tool source")
    earth_layers = LayerRegistry("earth layer")
    vision_preparer = StoredImagePreparer(
        image_store,
        settings.vision.max_images_per_message,
        settings.vision.max_message_bytes,
    )
    workspace_memory = WorkspaceMemory(sessions, image_store)
    capability_discovery = CapabilityDiscovery(
        settings,
        provider_factories,
        tool_sources,
        earth_layers,
    )
    return Container(
        settings=settings,
        engine=engine,
        sessions=sessions,
        projects=projects,
        event_bus=event_bus,
        agent_runtime=AgentRuntime(engine, sessions, event_bus, settings.agent.model_id),
        provider_factories=provider_factories,
        tool_sources=tool_sources,
        earth_layers=earth_layers,
        image_store=image_store,
        image_ingestor=FilesystemImageIngestor(image_store, settings.vision),
        vision_preparer=vision_preparer,
        workspace_memory=workspace_memory,
        capability_discovery=capability_discovery,
        request_planner=RequestPlanner(
            sessions,
            image_store,
            EarthContextBuilder(),
            ConversationContextBuilder(),
            workspace_memory,
            capability_discovery,
            RecommendationEngine(),
            PromptAssembler(),
            settings.intelligence,
        ),
    )
