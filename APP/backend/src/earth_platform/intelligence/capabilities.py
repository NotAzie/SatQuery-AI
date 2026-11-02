from typing import get_args

from earth_platform.agent.tools import ToolSource
from earth_platform.earth.commands import EarthCommand
from earth_platform.earth.layers import LayerRegistry
from earth_platform.intelligence.models import CapabilityEntry, CapabilitySnapshot
from earth_platform.llm.provider import ProviderFactory
from earth_platform.settings import Settings
from earth_platform.shared.earth import EarthContext
from earth_platform.shared.registry import Registry


class CapabilityDiscovery:
    """Reports registered or configured capability facts without probing unsupported Engine APIs."""

    def __init__(
        self,
        settings: Settings,
        providers: Registry[ProviderFactory],
        tools: Registry[ToolSource],
        layers: LayerRegistry,
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._tools = tools
        self._layers = layers

    def snapshot(self) -> CapabilitySnapshot:
        provider_entries = [
            CapabilityEntry(
                id=provider_id,
                kind=provider.kind,
                status=(
                    "configured"
                    if provider.enabled and provider.kind in self._providers
                    else "unavailable"
                ),
                detail=(
                    None
                    if provider.enabled and provider.kind in self._providers
                    else "Provider is disabled or its factory is not registered."
                ),
            )
            for provider_id, provider in self._settings.llm.providers.items()
        ]
        streaming_entries = [
            CapabilityEntry(
                id=provider_id,
                kind=provider.kind,
                status=(
                    "configured"
                    if provider.enabled and provider.kind in self._providers
                    else "unavailable"
                ),
                detail=(
                    "Registered provider factories implement the provider-neutral streaming "
                    "contract."
                ),
            )
            for provider_id, provider in self._settings.llm.providers.items()
        ]
        provider_extensions = [
            CapabilityEntry(
                id=provider_id,
                kind=provider.kind,
                status=(
                    "unknown"
                    if provider.enabled and provider.kind in self._providers
                    else "unavailable"
                ),
                detail="Provider factories do not publish vision or attachment support metadata.",
            )
            for provider_id, provider in self._settings.llm.providers.items()
        ]
        command_union = get_args(get_args(EarthCommand)[0])
        return CapabilitySnapshot(
            providers=provider_entries,
            provider_streaming=streaming_entries,
            provider_vision=provider_extensions,
            provider_attachments=provider_extensions,
            platform_tool_sources=[
                CapabilityEntry(id=tool_id, kind="platform_tool_source", status="configured")
                for tool_id in self._tools
            ],
            earth_layers=[
                CapabilityEntry(id=layer_id, kind=layer.kind, status="configured")
                for layer_id, layer in self._layers.items().items()
            ],
            earth_commands=[
                CapabilityEntry(
                    id=command.model_fields["type"].default,
                    kind="earth_command_contract",
                    status="unknown",
                    detail="The Platform API does not expose active frontend command handlers.",
                )
                for command in command_union
            ],
            workspace_capabilities=[
                CapabilityEntry(
                    id=field_name,
                    kind="earth_context_field",
                    status="available",
                )
                for field_name in EarthContext.model_fields
            ],
            vision_ingestion=CapabilityEntry(
                id="platform-vision-ingestion",
                kind="platform",
                status="available",
                detail="Session-scoped image ingestion and metadata preparation are configured.",
            ),
            vision_engine_delivery=CapabilityEntry(
                id="engine-vision-delivery",
                kind="engine_agent_api",
                status="available",
                detail=(
                    "The Engine Agent API accepts verified image attachments; the configured "
                    "reasoning adapter must declare vision support."
                ),
            ),
            streaming=CapabilityEntry(
                id="engine-agent-stream",
                kind="server_sent_events",
                status="available",
            ),
            engine_tool_discovery=CapabilityEntry(
                id="engine-tools",
                kind="engine_agent_api",
                status="unknown",
                detail=(
                    "The Engine publishes typed Agent tool descriptors through the separate live "
                    "discovery endpoint; this local snapshot does not probe Engine connectivity."
                ),
            ),
            dataset_discovery=CapabilityEntry(
                id="engine-datasets",
                kind="engine_api",
                status="unknown",
                detail=(
                    "The Engine data panel requests live dataset metadata separately; this local "
                    "capability snapshot does not probe Engine connectivity."
                ),
            ),
        )
