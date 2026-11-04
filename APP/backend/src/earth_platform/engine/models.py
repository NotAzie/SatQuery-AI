"""Platform-side view of what crosses the Engine boundary.

Deliberately thin: payloads the Platform does not need to interpret stay opaque
(``dict``). The HTTP adapter maps the published Engine Agent API shapes here so the
rest of the Platform never imports Engine types.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from earth_platform.shared.earth import EarthContext as WorkspaceEarthContext
from earth_platform.shared.geo import BoundingBox, GeoJSONGeometry, LngLat, TimeRange


class EngineHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable", "unconfigured"]
    version: str | None = None
    detail: str | None = None


class EngineImageCapability(BaseModel):
    tool: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    description: str
    requires_images: int = Field(ge=0)
    backend_preference: list[str]
    available: bool
    unavailable_reason: str | None = None


class EngineAgentToolDescriptor(BaseModel):
    tool_id: str = Field(min_length=1)
    description: str
    input_schema: dict[str, Any]
    availability: Literal["available"]
    requires_execution_authorization: bool
    model_visible_without_consent: bool
    model_visible_with_execution_consent: bool


class EngineDatasetTemporalCoverage(BaseModel):
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def validate_order(self) -> EngineDatasetTemporalCoverage:
        if self.start is not None and self.start.tzinfo is None:
            raise ValueError("dataset temporal coverage start must be timezone-aware")
        if self.end is not None and self.end.tzinfo is None:
            raise ValueError("dataset temporal coverage end must be timezone-aware")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("dataset temporal coverage start must not follow its end")
        return self


class EngineDatasetMetadata(BaseModel):
    connector_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    version: str | None = None
    variables: list[str] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    modalities: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    temporal_coverage: EngineDatasetTemporalCoverage | None = None
    historical_coverage: EngineDatasetTemporalCoverage | None = None
    forecast_coverage: EngineDatasetTemporalCoverage | None = None
    supports_historical: bool | None = None
    supports_forecast: bool | None = None
    spatial_resolution: float | None = Field(default=None, gt=0)
    resolution_unit: str | None = None
    crs: str | None = None
    update_frequency: str | None = None
    licensing: str | None = None
    citation: str | None = None
    latency: str | None = None
    deprecated: bool = False


class EngineEarthModalityCapability(BaseModel):
    modality_id: str = Field(min_length=1)
    label: str | None = None
    description: str | None = None
    status: Literal["registered", "unavailable", "declared", "not_registered"]
    implementation_ids: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)


class EngineEarthCapabilitySnapshot(BaseModel):
    revision: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    modalities: list[EngineEarthModalityCapability]
    snapshot_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    snapshot_schema_version: Literal["1.0.0"]


class EngineAgentToolCall(BaseModel):
    call_id: str
    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class EngineAgentImageRef(BaseModel):
    """Verified Platform image reference retained in the Engine Agent transcript."""

    asset_id: str = Field(min_length=1, max_length=128)
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/tiff"]
    size_bytes: int = Field(ge=1, le=20 * 1024 * 1024)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class EngineAgentImage(EngineAgentImageRef):
    """One Platform-owned image delivered with an Engine Agent turn."""

    data_base64: str = Field(min_length=4, max_length=27_962_028)


class EngineAgentMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    turn_id: str
    attachments: list[EngineAgentImageRef] = Field(default_factory=list)
    tool_calls: list[EngineAgentToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    model_id: str | None = None


class EngineAgentSession(BaseModel):
    """Conversation state returned by the Engine Agent Interface."""

    session_id: str
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime
    messages: list[EngineAgentMessage] = Field(default_factory=list)
    investigation_ids: list[str] = Field(default_factory=list)


class EngineInvestigationReport(BaseModel):
    """Engine-authored report text linked to an Engine-owned investigation."""

    report_id: str = Field(min_length=1)
    report_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    investigation_id: str = Field(min_length=1)
    markdown: str = Field(min_length=1)


class EngineInvestigationComparisonRequest(BaseModel):
    investigation_ids: list[str] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_distinct_investigations(self) -> EngineInvestigationComparisonRequest:
        if len(self.investigation_ids) != len(set(self.investigation_ids)):
            raise ValueError("investigation_ids must be unique")
        return self


class EngineComparisonMeasurement(BaseModel):
    investigation_id: str
    observation_id: str
    canonical_variable: str
    value: Any = None
    unit: str
    observed_at: str | None = None
    dataset: dict[str, Any] | None = None
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class EngineMeasurementComparisonGroup(BaseModel):
    canonical_variable: str
    unit: str
    records: list[EngineComparisonMeasurement] = Field(default_factory=list)
    investigation_ids: list[str] = Field(default_factory=list)
    coverage: Literal[
        "present_in_all_selected_investigations",
        "present_in_subset_of_selected_investigations",
    ]
    interpretation: str = Field(min_length=1)


class EngineInvestigationComparison(BaseModel):
    comparison_id: str = Field(min_length=1)
    comparison_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    schema_version: str = Field(min_length=1)
    stack_builder_version: str = Field(min_length=1)
    temporal_method_id: str = Field(min_length=1)
    temporal_method_version: str = Field(min_length=1)
    investigation_reports: list[dict[str, Any]]
    measurement_groups: list[EngineMeasurementComparisonGroup] = Field(default_factory=list)
    observation_stacks: list[dict[str, Any]] = Field(default_factory=list)
    temporal_diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    alignment_issues: list[dict[str, Any]] = Field(default_factory=list)
    temporal_issues: list[dict[str, Any]] = Field(default_factory=list)
    observation_identity_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    unmatched_observation_ids: list[str] = Field(default_factory=list)
    limitations: list[str]
    markdown: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_id_matches_digest(self) -> EngineInvestigationComparison:
        expected_id = f"investigation-comparison:{self.comparison_sha256[:20]}"
        if self.comparison_id != expected_id:
            raise ValueError("comparison_id does not match the comparison digest")
        return self


class EngineScientificFinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    finding_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    hypothesis_statement: str = Field(min_length=1)
    evidential_relation: Literal["supports", "contradicts", "contextual", "inconclusive"]
    observation_ids: list[str] = Field(min_length=1)
    supporting_observation_ids: list[str] = Field(default_factory=list)
    contradicting_observation_ids: list[str] = Field(default_factory=list)
    unresolved_observation_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EngineScientificConclusion(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["unresolved", "findings_available"]
    explanation: str
    missing_evidence: list[str] = Field(default_factory=list)
    additional_observation_targets: list[str] = Field(default_factory=list)


class EngineEvidenceSufficiencyAssessment(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["method_inputs_satisfied", "insufficient", "not_assessable"]
    explanation: str
    applicable_validated_rule_ids: list[str] = Field(default_factory=list)
    unmet_preconditions: list[str] = Field(default_factory=list)


class EngineScientificReasoningReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    reasoning_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    engine_id: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    status: Literal["evaluated", "insufficient_evidence", "not_evaluable"]
    findings: list[EngineScientificFinding] = Field(default_factory=list)
    sufficiency: EngineEvidenceSufficiencyAssessment
    conclusion: EngineScientificConclusion
    limitations: list[str] = Field(default_factory=list)


class EngineInvestigationReasoningResponse(BaseModel):
    status: Literal["not_evaluated", "evaluated", "insufficient_evidence", "not_evaluable"]
    reasoning: EngineScientificReasoningReport | None = None

    @model_validator(mode="after")
    def validate_reasoning_status(self) -> EngineInvestigationReasoningResponse:
        if self.status == "not_evaluated":
            if self.reasoning is not None:
                raise ValueError("not_evaluated reasoning response cannot include a report")
        elif self.reasoning is None or self.reasoning.status != self.status:
            raise ValueError("reasoning status must match the Engine report")
        return self


class EngineInvestigationReproducibilityBundle(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    capability_matrix_revision: str | None = None
    capability_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    earth_objects: list[dict[str, Any]] = Field(default_factory=list)
    earth_object_graph: dict[str, Any] | None = None
    earth_object_extractions: list[dict[str, Any]] = Field(default_factory=list)
    earth_object_transitions: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    scientific_methods: list[dict[str, Any]] = Field(default_factory=list)
    evidence_graph: dict[str, Any] | None = None
    reasoning_report: dict[str, Any] | None = None
    uncertainty_inventory: dict[str, Any] | None = None
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    audit_events: list[dict[str, Any]] = Field(default_factory=list)
    monitoring_schedules: list[dict[str, Any]] | None = None
    monitoring_runs: list[dict[str, Any]] = Field(default_factory=list)
    monitoring_events: list[dict[str, Any]] = Field(default_factory=list)
    monitoring_notifications: list[dict[str, Any]] = Field(default_factory=list)
    monitoring_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    investigation_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    missing_artifacts: list[str] = Field(default_factory=list)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    bundle_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    exported_at: datetime

    @field_validator("artifact_hashes")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
            for digest in value.values()
        ):
            raise ValueError("artifact hashes must be SHA-256 digests")
        return value

    @field_validator("exported_at")
    @classmethod
    def validate_exported_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("reproducibility export time must be timezone-aware")
        return value


class EngineHypothesisRecord(BaseModel):
    hypothesis_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    proposition: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    origin: Literal["explicit", "question_derived", "composite"]
    lifecycle: Literal["proposed", "active", "under_review", "superseded", "withdrawn", "closed"]
    competing_group_id: str | None = None
    parent_hypothesis_ids: list[str] = Field(default_factory=list)
    composition: Literal["all", "any"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineHypothesisGraph(BaseModel):
    hypotheses: list[EngineHypothesisRecord] = Field(default_factory=list)


class EngineHypothesisLifecycleEvent(BaseModel):
    event_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    prior_version: int = Field(ge=0)
    version: int = Field(ge=1)
    from_status: str | None = None
    to_status: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    occurred_at: datetime


class EngineHypothesisLifecycleResponse(BaseModel):
    status: Literal["available", "not_initialized", "unavailable"]
    graph: EngineHypothesisGraph | None = None
    events: list[EngineHypothesisLifecycleEvent] = Field(default_factory=list)
    restoration_error: str | None = None


class EngineHypothesisCreateRequest(BaseModel):
    hypothesis_id: str = Field(min_length=1)
    proposition: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    origin: Literal["explicit", "question_derived", "composite"]
    competing_group_id: str | None = None
    parent_hypothesis_ids: list[str] = Field(default_factory=list)
    composition: Literal["all", "any"] | None = None
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class EngineHypothesisTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal["active", "under_review", "superseded", "withdrawn", "closed"]
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class EngineHypothesisMutationResponse(BaseModel):
    hypothesis: EngineHypothesisRecord
    events: list[EngineHypothesisLifecycleEvent] = Field(default_factory=list)


class EngineObservationDataset(BaseModel):
    connector_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    version: str | None = None
    uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineObservationTemporalExtent(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class EngineObservationAsset(BaseModel):
    uri: str = Field(min_length=1)
    media_type: str | None = None
    roles: list[str] = Field(default_factory=list)
    title: str | None = None
    description: str | None = None
    checksum: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineObservation(BaseModel):
    """Typed source record view; values and provenance remain Engine-owned."""

    model_config = ConfigDict(extra="allow")

    observation_id: str = Field(min_length=1)
    source_id: str | None = None
    dataset: EngineObservationDataset | None = None
    observed_at: datetime | None = None
    geometry: dict[str, Any] | None = None
    bbox: tuple[float, ...] | None = Field(default=None, min_length=4, max_length=6)
    crs: str | None = None
    temporal_extent: EngineObservationTemporalExtent | None = None
    observation_type: str | None = None
    measured_variables: dict[str, Any] = Field(default_factory=dict)
    modalities: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    assets: dict[str, EngineObservationAsset] = Field(default_factory=dict)
    source_document: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bbox")
    @classmethod
    def validate_bbox_dimensions(cls, value: tuple[float, ...] | None) -> tuple[float, ...] | None:
        if value is not None and len(value) not in {4, 6}:
            raise ValueError("observation bbox must contain four or six coordinates")
        return value


class EngineEarthQuery(BaseModel):
    bbox: tuple[float, ...] | None = Field(default=None, min_length=4, max_length=6)
    point: tuple[float, float] | None = None
    geometry: dict[str, Any] | None = None
    temporal_start: datetime | None = None
    temporal_end: datetime | None = None
    crs: str = "OGC:CRS84"
    spatial_resolution: float | None = Field(default=None, gt=0)
    resolution_unit: str | None = None
    requested_dataset_ids: tuple[str, ...] = ()
    requested_variables: tuple[str, ...] = ()
    requested_modalities: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    region: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    asset_preferences: tuple[str, ...] = ()
    asset_sampling: Literal["point"] | None = None
    raster_analysis: Literal["zonal_descriptive"] | None = None
    raster_pixel_selection: Literal["pixel_center", "all_touched"] | None = None
    raster_weighting: Literal["equal_cell", "geodesic_cell_area"] | None = None
    raster_semantics: dict[str, Literal["numeric", "categorical"]] = Field(default_factory=dict)
    raster_component_extraction: tuple[dict[str, Any], ...] = ()


class EngineMission(BaseModel):
    mission_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    status: Literal["active", "completed", "cancelled"] = "active"
    created_at: datetime
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineMissionCreate(BaseModel):
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)


class EngineMonitoringTriggerPolicy(BaseModel):
    policy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    canonical_variable: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    operator: Literal["gt", "gte", "lt", "lte", "abs_gt", "abs_gte"]
    threshold: float = Field(allow_inf_nan=False)
    follow_up_query: EngineEarthQuery
    cooldown_seconds: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1, le=5)
    retry_safe: bool = False


class EngineMonitoringScheduleCreate(BaseModel):
    mission_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    earth_query: EngineEarthQuery
    interval_seconds: int = Field(gt=0)
    rolling_window_seconds: int | None = Field(default=None, gt=0)
    priority: int = Field(default=0, ge=0, le=100)
    overlap_policy: Literal["skip_while_running", "allow"] = "skip_while_running"
    trigger_policies: tuple[EngineMonitoringTriggerPolicy, ...] = ()

    @model_validator(mode="after")
    def validate_rolling_window(self) -> EngineMonitoringScheduleCreate:
        if self.rolling_window_seconds is not None and (
            self.earth_query.temporal_start is not None or self.earth_query.temporal_end is not None
        ):
            raise ValueError(
                "rolling temporal windows cannot be combined with fixed EarthQuery times"
            )
        return self


class EngineMonitoringScheduleUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1)
    earth_query: EngineEarthQuery | None = None
    interval_seconds: int | None = Field(default=None, gt=0)
    rolling_window_seconds: int | None = Field(default=None, gt=0)
    priority: int | None = Field(default=None, ge=0, le=100)
    overlap_policy: Literal["skip_while_running", "allow"] | None = None
    trigger_policies: tuple[EngineMonitoringTriggerPolicy, ...] | None = None

    @model_validator(mode="after")
    def require_update_fields(self) -> EngineMonitoringScheduleUpdate:
        changed = self.model_fields_set - {"expected_revision"}
        if not changed:
            raise ValueError("at least one schedule field must be updated")
        if any(
            getattr(self, field) is None for field in changed if field != "rolling_window_seconds"
        ):
            raise ValueError("updated schedule fields cannot be null")
        return self


class EngineMonitoringSchedule(EngineMonitoringScheduleCreate):
    schedule_id: str = Field(min_length=1)
    enabled: bool = True
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime
    revision: int = Field(default=1, ge=1)

    @field_validator("next_run_at", "created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("monitoring schedule timestamps must be timezone-aware")
        return value


class EngineMonitoringRun(BaseModel):
    run_id: str = Field(min_length=1)
    schedule_id: str = Field(min_length=1)
    schedule_revision: int = Field(default=1, ge=1)
    mission_id: str = Field(min_length=1)
    scheduled_at: datetime
    started_at: datetime
    effective_temporal_start: datetime | None = None
    effective_temporal_end: datetime | None = None
    finished_at: datetime | None = None
    status: Literal["running", "completed", "partial", "failed", "skipped"]
    investigation_id: str | None = None
    execution_id: str | None = None
    missed_intervals: int = Field(default=0, ge=0)
    failure_type: str | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None

    @field_validator(
        "scheduled_at",
        "started_at",
        "effective_temporal_start",
        "effective_temporal_end",
        "finished_at",
        "lease_expires_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("monitoring run timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_effective_window(self) -> EngineMonitoringRun:
        if (self.effective_temporal_start is None) != (self.effective_temporal_end is None):
            raise ValueError("effective temporal window bounds must be provided together")
        if (
            self.effective_temporal_start is not None
            and self.effective_temporal_end is not None
            and self.effective_temporal_start >= self.effective_temporal_end
        ):
            raise ValueError("effective temporal window must have positive duration")
        return self


class EngineMonitoringComparison(BaseModel):
    comparison_id: str = Field(min_length=1)
    comparison_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    limitations: tuple[str, ...]
    markdown: str


class EngineMonitoringNotification(BaseModel):
    notification_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    schedule_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    severity: Literal["warning", "error"]
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    status: Literal["unread", "acknowledged"] = "unread"
    created_at: datetime
    acknowledged_at: datetime | None = None

    @field_validator("created_at", "acknowledged_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("monitoring notification timestamps must be timezone-aware")
        return value


class EngineMonitoringTriggerEvent(BaseModel):
    event_id: str = Field(min_length=1)
    event_type: Literal[
        "trigger_evaluated",
        "trigger_matched",
        "trigger_suppressed_cooldown",
        "trigger_investigation_created",
        "trigger_investigation_completed",
        "trigger_investigation_failed",
    ]
    schedule_id: str = Field(min_length=1)
    run_id: str | None = None
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("monitoring trigger timestamps must be timezone-aware")
        return value


class EngineMonitoringTriggerHistory(BaseModel):
    schedule_id: str = Field(min_length=1)
    schedule_revision: int = Field(ge=1)
    policies: tuple[EngineMonitoringTriggerPolicy, ...] = ()
    events: tuple[EngineMonitoringTriggerEvent, ...] = ()
    next_cursor: str | None = None
    has_more: bool = False


class EngineEarthObjectProperties(BaseModel):
    object_id: str | None = None
    object_type: str | None = None
    revision: int | None = Field(default=None, ge=1)
    lifecycle: str | None = None
    investigation_ids: list[str] = Field(default_factory=list)
    source_observation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class EngineEarthObjectFeature(BaseModel):
    type: Literal["Feature"]
    id: str = Field(min_length=1)
    geometry: dict[str, Any]
    properties: EngineEarthObjectProperties = Field(default_factory=EngineEarthObjectProperties)


class EngineInvestigationEvent(BaseModel):
    sequence: int = Field(ge=1)
    plan_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    previous_event_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    event_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class EngineInvestigationEventPage(BaseModel):
    investigation_id: str = Field(min_length=1)
    plan_id: str | None = None
    events: list[EngineInvestigationEvent] = Field(default_factory=list)
    next_sequence: int = Field(ge=0)
    has_more: bool = False


class EngineGeoJSONOmission(BaseModel):
    object_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EngineEarthObjectGeoJSON(BaseModel):
    """Engine-exported GeoJSON limited to verified WGS 84 object geometries."""

    type: Literal["FeatureCollection"]
    features: list[EngineEarthObjectFeature] = Field(default_factory=list)
    omitted_objects: list[EngineGeoJSONOmission] = Field(alias="satquery:omitted_objects")
    geometry_policy: str = Field(alias="satquery:geometry_policy", min_length=1)


EngineAgentEventKind = Literal[
    "turn.started",
    "assistant.delta",
    "earth.command",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "investigation.progress",
    "turn.completed",
    "turn.cancelled",
    "agent.error",
]


class EngineAgentEvent(BaseModel):
    """One event in the Engine-owned model/tool turn stream."""

    kind: EngineAgentEventKind
    session_id: str
    turn_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class EngineEarthCamera(BaseModel):
    position: LngLat
    height_m: float = Field(allow_inf_nan=False)
    heading_deg: float = Field(default=0, allow_inf_nan=False)
    pitch_deg: float = Field(default=-90, allow_inf_nan=False)
    roll_deg: float = Field(default=0, allow_inf_nan=False)
    view_rect: BoundingBox | None = None


class EngineEarthSelection(BaseModel):
    entity_id: str = Field(min_length=1, max_length=256)
    position: LngLat | None = None
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EngineEarthDrawing(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=256)
    kind: Literal["point", "line", "polygon", "rectangle", "circle"]
    geometry: GeoJSONGeometry


class EngineEarthViewport(BaseModel):
    width_px: int = Field(gt=0, le=16384)
    height_px: int = Field(gt=0, le=16384)
    pixel_ratio: float = Field(default=1.0, ge=0.1, le=8, allow_inf_nan=False)


class EngineEarthLayer(BaseModel):
    layer_id: str = Field(min_length=1, max_length=128)
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)


class EngineEarthTimelinePlayback(BaseModel):
    playing: bool = False
    speed: float = Field(default=1.0, gt=0, le=10000, allow_inf_nan=False)


class EngineEarthImageryRef(BaseModel):
    asset_id: str = Field(min_length=1, max_length=128)
    source: Literal["capture", "attachment"]
    attached: bool = False
    captured_at: datetime | None = None
    region: BoundingBox | None = None
    camera: EngineEarthCamera | None = None
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/tiff"] | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class EngineEarthOverlayFeature(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)


class EngineEarthOverlayOmission(BaseModel):
    object_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=512)


class EngineEarthOverlay(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=256)
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)
    features: list[EngineEarthOverlayFeature] = Field(default_factory=list, max_length=4096)
    omitted_objects: list[EngineEarthOverlayOmission] = Field(default_factory=list, max_length=4096)
    geometry_policy: str | None = Field(default=None, max_length=512)


class EngineEarthInvestigationState(BaseModel):
    known_ids: list[str] = Field(default_factory=list, max_length=64)
    visible_ids: list[str] = Field(default_factory=list, max_length=64)


class EngineEarthSecondaryView(BaseModel):
    camera: EngineEarthCamera
    viewport: EngineEarthViewport | None = None
    layers: list[EngineEarthLayer] = Field(default_factory=list, max_length=64)
    overlays: list[EngineEarthOverlay] = Field(default_factory=list, max_length=32)
    selected_evidence_ids: list[str] = Field(default_factory=list, max_length=64)


class EngineEarthCameraHistory(BaseModel):
    past: list[EngineEarthCamera] = Field(default_factory=list, max_length=100)
    present: EngineEarthCamera | None = None
    future: list[EngineEarthCamera] = Field(default_factory=list, max_length=100)


class EngineEarthBookmarkRef(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(max_length=256)
    camera: EngineEarthCamera
    time: TimeRange | None = None
    instant: datetime | None = None


class EngineEarthSplitView(BaseModel):
    enabled: bool = False
    sync_cameras: bool = False


class EngineEarthMeasurement(BaseModel):
    kind: Literal["distance", "area", "coordinates", "elevation"]
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["m", "km", "m2", "km2", "degrees", "m elevation"]
    position: LngLat


class EngineEarthContext(BaseModel):
    """The Platform's model-relevant Earth state sent through the Engine API."""

    camera: EngineEarthCamera
    viewport: EngineEarthViewport | None = None
    layers: list[EngineEarthLayer] = Field(default_factory=list, max_length=64)
    time_range: TimeRange | None = None
    instant: datetime | None = None
    timeline_playback: EngineEarthTimelinePlayback = Field(
        default_factory=EngineEarthTimelinePlayback
    )
    selection: EngineEarthSelection | None = None
    drawings: list[EngineEarthDrawing] = Field(default_factory=list, max_length=32)
    imagery: list[EngineEarthImageryRef] = Field(default_factory=list, max_length=136)
    overlays: list[EngineEarthOverlay] = Field(default_factory=list, max_length=32)
    secondary_view: EngineEarthSecondaryView | None = None
    investigations: EngineEarthInvestigationState = Field(
        default_factory=EngineEarthInvestigationState
    )
    selected_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    bookmarks: list[EngineEarthBookmarkRef] = Field(default_factory=list, max_length=32)
    camera_history: EngineEarthCameraHistory = Field(default_factory=EngineEarthCameraHistory)
    split_view: EngineEarthSplitView = Field(default_factory=EngineEarthSplitView)
    measurement: EngineEarthMeasurement | None = None

    @classmethod
    def from_workspace(
        cls,
        context: WorkspaceEarthContext,
        attached_images: Sequence[EngineAgentImageRef] | None = None,
    ) -> EngineEarthContext:
        imagery_by_asset = {
            item.asset_id: EngineEarthImageryRef.model_validate(item.model_dump())
            for item in context.imagery
        }
        for capture in context.captures:
            imagery_by_asset.setdefault(
                capture.asset_id,
                EngineEarthImageryRef(
                    asset_id=capture.asset_id,
                    source="capture",
                    captured_at=capture.captured_at,
                    region=capture.region,
                    camera=EngineEarthCamera.model_validate(capture.camera.model_dump()),
                ),
            )
        for image in attached_images or []:
            existing = imagery_by_asset.get(image.asset_id)
            if existing is None:
                imagery_by_asset[image.asset_id] = EngineEarthImageryRef(
                    asset_id=image.asset_id,
                    source="attachment",
                    attached=True,
                    mime_type=image.mime_type,
                    width=image.width,
                    height=image.height,
                )
            else:
                imagery_by_asset[image.asset_id] = existing.model_copy(
                    update={
                        "attached": True,
                        "mime_type": image.mime_type,
                        "width": image.width,
                        "height": image.height,
                    }
                )
        return cls(
            camera=EngineEarthCamera.model_validate(context.camera.model_dump()),
            viewport=(
                EngineEarthViewport.model_validate(context.viewport.model_dump())
                if context.viewport
                else None
            ),
            layers=[EngineEarthLayer.model_validate(item.model_dump()) for item in context.layers],
            time_range=context.time,
            instant=context.instant,
            timeline_playback=EngineEarthTimelinePlayback.model_validate(
                context.timeline_playback.model_dump()
            ),
            selection=(
                EngineEarthSelection(
                    entity_id=context.selection.entity_id,
                    position=context.selection.position,
                    properties=context.selection.properties,
                )
                if context.selection
                else None
            ),
            drawings=[
                EngineEarthDrawing.model_validate(item.model_dump()) for item in context.drawings
            ],
            imagery=list(imagery_by_asset.values()),
            overlays=[
                EngineEarthOverlay.model_validate(item.model_dump()) for item in context.overlays
            ],
            secondary_view=(
                EngineEarthSecondaryView(
                    camera=EngineEarthCamera.model_validate(
                        context.secondary_view.camera.model_dump()
                    ),
                    viewport=(
                        EngineEarthViewport.model_validate(
                            context.secondary_view.viewport.model_dump()
                        )
                        if context.secondary_view.viewport
                        else None
                    ),
                    layers=[
                        EngineEarthLayer.model_validate(item.model_dump())
                        for item in context.secondary_view.layers
                    ],
                    overlays=[
                        EngineEarthOverlay.model_validate(item.model_dump())
                        for item in context.secondary_view.overlays
                    ],
                    selected_evidence_ids=(context.secondary_view.selected_evidence_ids),
                )
                if context.secondary_view
                else None
            ),
            investigations=EngineEarthInvestigationState.model_validate(
                context.investigations.model_dump()
            ),
            selected_evidence_ids=context.selected_evidence_ids,
            bookmarks=[
                EngineEarthBookmarkRef.model_validate(item.model_dump())
                for item in context.bookmarks
            ],
            camera_history=EngineEarthCameraHistory(
                past=[
                    EngineEarthCamera.model_validate(item.model_dump())
                    for item in context.camera_history.past
                ],
                present=(
                    EngineEarthCamera.model_validate(context.camera_history.present.model_dump())
                    if context.camera_history.present
                    else None
                ),
                future=[
                    EngineEarthCamera.model_validate(item.model_dump())
                    for item in context.camera_history.future
                ],
            ),
            split_view=EngineEarthSplitView.model_validate(context.split_view.model_dump()),
            measurement=(
                EngineEarthMeasurement.model_validate(context.measurement.model_dump())
                if context.measurement
                else None
            ),
        )


class EngineToolDescriptor(BaseModel):
    """A capability the Engine exposes through its Agent Interface."""

    name: str
    description: str
    input_schema: dict[str, Any]
    tags: list[str] = Field(default_factory=list)


class EngineContext(BaseModel):
    """Ambient scope forwarded with an invocation so the Engine can attach work to the
    right investigation / Earth Memory scope. Opaque ids only."""

    session_id: str
    investigation_id: str | None = None
    region: BoundingBox | None = None
    time_range: TimeRange | None = None


class EngineInvocation(BaseModel):
    call_id: str
    tool: str
    arguments: dict[str, Any]
    context: EngineContext


class EvidenceRef(BaseModel):
    """Pointer to evidence held by the Engine. The Platform never recomputes or edits it."""

    id: str
    kind: str
    title: str | None = None
    geometry: GeoJSONGeometry | None = None
    time_range: TimeRange | None = None
    uri: str | None = None


class EngineProgress(BaseModel):
    type: Literal["progress"] = "progress"
    call_id: str
    fraction: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None
    investigation_id: str | None = None


class EngineEvidence(BaseModel):
    type: Literal["evidence"] = "evidence"
    call_id: str
    evidence: EvidenceRef


class EngineResult(BaseModel):
    """Always the final item of an invocation stream."""

    type: Literal["result"] = "result"
    call_id: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    error: str | None = None


EngineStreamItem = EngineProgress | EngineEvidence | EngineResult
