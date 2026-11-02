"""Export the backend's wire contracts as one JSON Schema (contracts/schema.json).

The frontend generates its TypeScript types from this file (`npm run gen:contracts`), so the two
sides cannot drift. Add a model here when it crosses the HTTP/stream boundary.
"""

import json
from pathlib import Path

from earth_platform.agent.events import AgentEvent
from earth_platform.agent.runtime import AgentTurnRequest
from earth_platform.earth.commands import EarthCommand
from earth_platform.earth.layers import LayerSpec
from earth_platform.earth.state import EarthContext
from earth_platform.engine.models import (
    EngineAgentSession,
    EngineAgentToolDescriptor,
    EngineDatasetMetadata,
    EngineEarthCapabilitySnapshot,
    EngineEarthObjectGeoJSON,
    EngineEarthQuery,
    EngineHealth,
    EngineImageCapability,
    EngineInvestigationEventPage,
    EngineInvestigationReport,
    EngineMission,
    EngineMissionCreate,
    EngineMonitoringComparison,
    EngineMonitoringNotification,
    EngineMonitoringRun,
    EngineMonitoringSchedule,
    EngineMonitoringScheduleCreate,
    EngineMonitoringScheduleUpdate,
    EngineMonitoringTriggerHistory,
    EvidenceRef,
)
from earth_platform.intelligence.models import EngineDiscoveryResponse
from earth_platform.llm.types import ModelInfo
from earth_platform.plugins.api import PanelContribution, PluginManifest
from earth_platform.sessions.models import ActiveTask, Conversation, Session
from earth_platform.shared.messages import Message
from earth_platform.streaming.messages import ClientMessage, ControlMessage
from earth_platform.vision.types import (
    ImageAsset,
    PreparedVisionPayload,
    PrepareVisionRequest,
    UpdateImageAssetRequest,
    VisionContext,
)
from pydantic import BaseModel


class Contracts(BaseModel):
    agent_event: AgentEvent
    agent_turn_request: AgentTurnRequest
    client_message: ClientMessage
    control_message: ControlMessage
    earth_command: EarthCommand
    earth_context: EarthContext
    layer_spec: LayerSpec
    evidence: EvidenceRef
    engine_health: EngineHealth
    engine_agent_tool_descriptor: EngineAgentToolDescriptor
    engine_image_capability: EngineImageCapability
    engine_dataset_metadata: EngineDatasetMetadata
    engine_earth_capability_snapshot: EngineEarthCapabilitySnapshot
    engine_discovery_response: EngineDiscoveryResponse
    engine_agent_session: EngineAgentSession
    engine_earth_query: EngineEarthQuery
    engine_mission: EngineMission
    engine_mission_create: EngineMissionCreate
    engine_monitoring_run: EngineMonitoringRun
    engine_monitoring_comparison: EngineMonitoringComparison
    engine_monitoring_notification: EngineMonitoringNotification
    engine_monitoring_trigger_history: EngineMonitoringTriggerHistory
    engine_monitoring_schedule: EngineMonitoringSchedule
    engine_monitoring_schedule_create: EngineMonitoringScheduleCreate
    engine_monitoring_schedule_update: EngineMonitoringScheduleUpdate
    engine_earth_object_geojson: EngineEarthObjectGeoJSON
    engine_investigation_event_page: EngineInvestigationEventPage
    engine_investigation_report: EngineInvestigationReport
    message: Message
    model_info: ModelInfo
    image_asset: ImageAsset
    vision_context: VisionContext
    prepared_vision_payload: PreparedVisionPayload
    prepare_vision_request: PrepareVisionRequest
    update_image_asset_request: UpdateImageAssetRequest
    session: Session
    conversation: Conversation
    active_task: ActiveTask
    plugin_manifest: PluginManifest
    panel: PanelContribution


def _require_defaulted_fields(schema: dict) -> None:
    """The server always serialises every field (never exclude_defaults / exclude_unset), so all
    properties are present on the wire. Mark them required so TypeScript discriminated unions
    narrow on ``type`` and consumers never see spurious ``undefined``. Fields excluded from
    serialisation are removed first."""
    for name, definition in schema.get("$defs", {}).items():
        props = definition.get("properties")
        if not props:
            continue
        if name == "AgentTurnRequest":
            definition["required"] = ["message"]
            continue
        if name == "EngineMonitoringScheduleUpdate":
            definition["required"] = ["expected_revision"]
            continue
        if name == "ImagePart":
            props.pop("data", None)  # transient, never serialised (see shared.messages)
        definition["required"] = sorted(props)


def main() -> None:
    schema = Contracts.model_json_schema(mode="serialization")
    _require_defaulted_fields(schema)
    schema["title"] = "Contracts"
    out = Path(__file__).resolve().parent.parent / "contracts" / "schema.json"
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
