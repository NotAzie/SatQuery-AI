"""Dependency-injected composition root for local SatQuery platform services."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from collections.abc import Iterable
from datetime import timedelta

from ..errors import ExtensionError, ValidationError
from .config import PlatformConfig
from .connectors import AuthenticationProvider, Connector, ConnectorManager
from .contracts import (
    EarthObject,
    EarthObjectRelationship,
    EarthQuery,
    Evidence,
    ExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    Investigation,
    Observation,
    ObservationSearchResult,
    ObservationStack,
    PerceptionResult,
    Task,
    TaskExecution,
    TemporalDifferenceDiagnostic,
    utc_now,
)
from .earth_memory import (
    EarthMemoryQuery,
    EarthMemoryRepository,
    artifact_from_payload,
)
from .earth_objects import (
    EarthObjectCatalog,
    EarthObjectDeclaration,
    EarthObjectExtractionBatch,
    EarthObjectExtractionIssue,
    EarthObjectExtractionPipeline,
    EarthObjectMaterializer,
)
from .execution import (
    ExecutionCancellationToken,
    ExecutionEngine,
    ProgressCallback,
    TaskHandler,
)
from .intelligence import (
    EvidenceAssessment,
    InvestigationDesign,
    InvestigationIntelligenceEngine,
)
from .investigations import (
    InMemoryInvestigationRepository,
    InMemoryMissionRepository,
    InvestigationRepository,
    InvestigationService,
    MissionRepository,
    MissionService,
    SQLiteInvestigationRepository,
    SQLiteMissionRepository,
)
from .method_readiness import AdaptiveInvestigationRefiner, EvidenceSufficiencyEngine
from .models import ModelAdapter, ModelRuntime
from .monitoring import (
    MonitoringEvent,
    MonitoringNotification,
    MonitoringRun,
    MonitoringSchedule,
    MonitoringScheduleUpdate,
    MonitoringService,
    MonitoringTriggerEvaluation,
    monitoring_run_identity,
    monitoring_schedule_definition,
    monitoring_schedule_identity,
    monitoring_schedule_revision_identity,
)
from .normalization import SemanticNormalizer
from .observability import configure_logging
from .perception import MemoryObservationCache, PerceptionEngine
from .planning import (
    CandidateHypothesis,
    InvestigationPlan,
    InvestigationPlanner,
)
from .reasoning import (
    ReasoningContext,
    ScientificOperator,
    ScientificReasoningEngine,
    ScientificReasoningReport,
    ScientificRule,
    UncertaintyPropagationMethod,
)
from .registry import ComponentRegistry, PlatformRegistries
from .scientific_governance import (
    CertificationState,
    MethodCertificationEvent,
    PeerReviewArtifact,
    ReproducibilityReport,
    ScientificBenchmarkSuite,
    ScientificMethodCertificationLedger,
    ScientificMethodRunner,
    ScientificPluginManifest,
    ScientificPluginRegistry,
    SignatureVerifier,
    ValidationDatasetLoader,
    canonical_digest,
)
from .scientific_inference import (
    DatasetTrustAssertion,
    HypothesisLifecycleEvent,
    HypothesisLifecycleLedger,
    HypothesisRecord,
    ObservationIndependenceAssertion,
    hypothesis_graph_from_candidates,
)
from .scientific_knowledge import (
    ScientificMethodManifest,
    ScientificMethodRegistry,
    ScientificOperatorManifest,
    ScientificOperatorManifestRegistry,
    earth_science_workflow_templates,
)
from .scientific_library import ScientificKnowledgeLibrary, documented_reference_methods
from .tools import PlatformTool, ToolRuntime
from .workflows import (
    ScientificInvestigationWorkflowCompiler,
    WorkflowCompilationContext,
    WorkflowCompilerRegistry,
)

logger = logging.getLogger(__name__)


def _memory_object_revision(artifact) -> int:
    try:
        return int(artifact.metadata.get("revision", 1))
    except (TypeError, ValueError):
        return 0


def _declared_extraction_method(declaration: EarthObjectDeclaration) -> tuple[str | None, str | None, tuple[str, ...]]:
    metadata = declaration.declared_provenance.get("extraction_pipeline", {})
    if not isinstance(metadata, dict):
        metadata = {}
    raw_methods = metadata.get("method_identities", ())
    if not raw_methods and metadata.get("method_identity"):
        raw_methods = (metadata["method_identity"],)
    elif isinstance(raw_methods, str):
        raw_methods = (raw_methods,)
    method_ids = tuple(sorted({item for item in raw_methods if isinstance(item, str) and item}))
    if len(method_ids) != 1:
        return None, None, method_ids
    method_id, separator, version = method_ids[0].rpartition("@")
    return (method_id or method_ids[0], version if separator and version else None, method_ids)


def _execution_result_from_payload(payload: dict) -> ExecutionResult:
    """Restore known canonical task outputs while leaving extension outputs opaque."""
    tasks = []
    for raw_task in payload.get("tasks", ()):
        task = dict(raw_task)
        output = task.get("output")
        if isinstance(output, dict) and "observations" in output:
            output_contract = (
                PerceptionResult
                if "query_fingerprint" in output
                else ObservationSearchResult
            )
            task["output"] = output_contract.model_validate(output)
        elif isinstance(output, dict) and "assessment_id" in output:
            task["output"] = EvidenceAssessment.model_validate(output)
        elif isinstance(output, dict) and "reasoning_id" in output:
            task["output"] = ScientificReasoningReport.model_validate(output)
        elif (
            isinstance(output, dict)
            and "pipeline_id" in output
            and "materialized_object_ids" in output
        ):
            task["output"] = EarthObjectExtractionBatch.model_validate(output)
        tasks.append(TaskExecution.model_validate(task))
    return ExecutionResult.model_validate({**payload, "tasks": tasks})


class PlatformRuntime:
    """Wire replaceable platform services around a shared registry set.

    The runtime is intentionally local and in-process. It owns service
    composition and connector shutdown; storage, worker queues, and remote
    scheduling remain replaceable adapters rather than runtime assumptions.
    Connectors are still started lazily on first use.
    """

    def __init__(
        self,
        *,
        config: PlatformConfig | None = None,
        registries: PlatformRegistries | None = None,
        investigation_repository: InvestigationRepository | None = None,
        mission_repository: MissionRepository | None = None,
        authentication_provider: AuthenticationProvider | None = None,
        progress_callback: ProgressCallback | None = None,
        earth_memory: EarthMemoryRepository | None = None,
        semantic_normalizer: SemanticNormalizer | None = None,
        raster_component_extractor=None,
    ) -> None:
        self.config = config or PlatformConfig.load()
        self.registries = registries or PlatformRegistries()
        self.earth_memory = (
            earth_memory if earth_memory is not None else self.config.create_earth_memory()
        )
        self.execution_journal = self.config.create_execution_journal()
        lifecycle_repository = (
            self.config.create_lifecycle_repository()
            if investigation_repository is None and mission_repository is None
            else None
        )
        self._closed = False
        self._execution_results: dict[str, ExecutionResult] = {}
        self._execution_results_lock = threading.RLock()
        self._monitoring_trigger_lock = asyncio.Lock()
        self._active_execution_cancellations: dict[str, ExecutionCancellationToken] = {}
        self.task_handlers: ComponentRegistry[TaskHandler] = ComponentRegistry()
        self.cache = self.config.create_cache()
        self.connector_manager = ConnectorManager(
            self.registries.connectors,
            dataset_registry=self.registries.datasets,
            authentication_provider=authentication_provider,
        )
        self.model_runtime = ModelRuntime(self.registries.models)
        self.tool_runtime = ToolRuntime(self.registries.tools)
        self.execution_engine = ExecutionEngine(
            self.task_handlers,
            progress_callback=progress_callback,
            platform_config=self.config,
            journal=self.execution_journal,
        )
        self.investigation_service = InvestigationService(
            investigation_repository
            or (
                SQLiteInvestigationRepository(lifecycle_repository)
                if lifecycle_repository is not None
                else InMemoryInvestigationRepository()
            )
        )
        self.mission_service = MissionService(
            mission_repository
            or (
                SQLiteMissionRepository(lifecycle_repository)
                if lifecycle_repository is not None
                else InMemoryMissionRepository()
            ),
            self.investigation_service,
        )
        self.monitoring_service = MonitoringService(
            self.config.create_monitoring_repository(),
            self.mission_service,
            self.investigation_service,
            max_concurrency=self.config.monitoring.max_concurrency,
            lease_seconds=self.config.monitoring.lease_seconds,
        )
        self._lifecycle_repository = lifecycle_repository
        self.perception_cache = (
            MemoryObservationCache(backend=self.cache)
            if self.cache is not None
            else None
        )
        self.perception_engine = PerceptionEngine(
            self.connector_manager,
            cache=self.perception_cache,
            cache_ttl_seconds=self.config.cache.ttl_seconds or 300,
            max_concurrency=self.config.execution.max_concurrency,
            normalizer=semantic_normalizer,
        )
        self.investigation_planner = InvestigationPlanner(
            modality_registry=self.perception_engine.modality_registry,
            capability_matrix=self.perception_engine.build_capability_matrix,
            capability_plan=self.perception_engine.plan,
        )
        self.investigation_intelligence = InvestigationIntelligenceEngine()
        self.method_certifications = ScientificMethodCertificationLedger()
        self.audit_trail = self.config.create_audit_trail()
        self._restore_scientific_certifications_from_audit()
        self.earth_objects = EarthObjectCatalog()
        self.earth_object_materializer = EarthObjectMaterializer()
        self.earth_object_extraction_pipeline = EarthObjectExtractionPipeline(
            raster_component_extractor=raster_component_extractor
        )
        self._earth_object_materialization_lock = threading.RLock()
        self._restore_earth_objects_from_memory()
        self.scientific_reasoning = ScientificReasoningEngine(
            certification_check=self.method_certifications.can_emit_findings
        )
        self.scientific_methods = ScientificMethodRegistry()
        self.scientific_knowledge_library = ScientificKnowledgeLibrary(
            documented_reference_methods()
        )
        for knowledge in self.scientific_knowledge_library.all():
            self._index_memory_artifact(
                artifact_id=f"knowledge:{knowledge.method_id}@{knowledge.version}",
                artifact_type="scientific_method", payload=knowledge,
                method_id=knowledge.method_id, method_version=knowledge.version,
                metadata={"record_kind": "cited_knowledge_not_executable"},
            )
        self.scientific_operator_manifests = ScientificOperatorManifestRegistry()
        self.scientific_plugins = ScientificPluginRegistry()
        self.scientific_workflow_templates = earth_science_workflow_templates()
        self._benchmark_suites: dict[tuple[str, str], ScientificBenchmarkSuite] = {}
        self._investigation_plans: dict[str, InvestigationPlan] = {}
        self._investigation_plans_lock = threading.RLock()
        self._investigation_designs: dict[str, InvestigationDesign] = {}
        self._investigation_designs_lock = threading.RLock()
        self._evidence_assessments: dict[str, EvidenceAssessment] = {}
        self._evidence_assessments_lock = threading.RLock()
        self._scientific_reasoning_reports: dict[str, ScientificReasoningReport] = {}
        self._scientific_reasoning_lock = threading.RLock()
        self._hypothesis_ledgers: dict[str, HypothesisLifecycleLedger] = {}
        self._hypothesis_ledgers_lock = threading.RLock()
        self._hypothesis_restore_errors: dict[str, str] = {}
        self.workflow_compilers = WorkflowCompilerRegistry()
        self.workflow_compilers.register(ScientificInvestigationWorkflowCompiler())
        self.register_task_handler("earth.observe", self._observe_task)
        self.register_task_handler(
            "earth.objects.extract", self._earth_object_extraction_task
        )
        self.register_task_handler("earth.assess", self._assess_task)
        self.register_task_handler("earth.reason", self._reason_task)

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def start(self) -> PlatformRuntime:
        """Configure local services without eagerly opening remote connectors."""
        self._ensure_open()
        configure_logging(self.config.logging.level)
        return self

    async def close(self) -> None:
        """Stop every started connector, attempting cleanup for all of them."""
        if self._closed:
            return
        try:
            await self.connector_manager.stop_all()
        finally:
            self._closed = True

    async def __aenter__(self) -> PlatformRuntime:
        return await self.start()

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def register_connector(self, connector: Connector) -> None:
        self._ensure_open()
        self.connector_manager.register(connector)

    def register_model(self, adapter: ModelAdapter) -> None:
        self._ensure_open()
        model_id = adapter.metadata.model_id
        self.registries.models.register(model_id, adapter)

    def register_tool(self, tool: PlatformTool) -> None:
        self._ensure_open()
        tool_id = tool.metadata.tool_id
        self.registries.tools.register(tool_id, tool)

    def register_scientific_operator(self, operator: ScientificOperator) -> None:
        self._ensure_open()
        self.scientific_reasoning.operators.register(operator)

    def register_scientific_operator_manifest(
        self, manifest: ScientificOperatorManifest
    ) -> None:
        self._ensure_open()
        self.scientific_operator_manifests.register(manifest)

    def register_scientific_plugin(
        self, manifest: ScientificPluginManifest, *, verifier: SignatureVerifier,
        platform_api_version: str, installed_dependencies: dict[str, str],
    ):
        self._ensure_open()
        result = self.scientific_plugins.register(
            manifest, verifier=verifier, platform_api_version=platform_api_version,
            installed_dependencies=installed_dependencies,
        )
        self.audit_trail.append(
            aggregate_id=f"plugin:{manifest.package_id}@{manifest.version}",
            event_type="plugin_registration", actor=verifier.verifier_id,
            payload={"manifest": manifest.model_dump(mode="json"),
                     "signature_verification": result[0].model_dump(mode="json"),
                     "compatibility": result[1].model_dump(mode="json")},
        )
        return result

    def register_scientific_rule(self, rule: ScientificRule) -> None:
        self._ensure_open()
        manifest = rule.manifest
        self.register_scientific_method(
            ScientificMethodManifest(
                method_id=manifest.rule_id,
                version=manifest.version,
                domain=manifest.domain,
                rule=manifest,
                expected_outputs=manifest.output_semantics,
            ),
            rule,
        )

    def register_scientific_method(
        self, manifest: ScientificMethodManifest, rule: ScientificRule
    ) -> None:
        """Register method metadata and implementation as one atomic catalog unit."""
        self._ensure_open()
        if rule.manifest != manifest.rule:
            raise ValueError("scientific method manifest must describe the supplied rule")
        # Validate both registries before mutation to avoid a split catalog.
        key = (manifest.method_id, manifest.version)
        restoration_error = self.method_certifications.restoration_error(*key)
        if restoration_error is not None:
            raise ValueError(
                "cannot re-register a method version with unrestorable certification "
                f"history: {restoration_error}"
            )
        if self.scientific_methods.get(*key) is not None:
            raise ValueError(f"scientific method already registered: {key[0]}@{key[1]}")
        if any(
            item.manifest.rule_id == key[0] and item.manifest.version == key[1]
            for item in self.scientific_reasoning.rules.all()
        ):
            raise ValueError(f"scientific rule already registered: {key[0]}@{key[1]}")
        implementation_sha256 = manifest.rule.implementation_sha256
        certification_history = self.method_certifications.history(*key)
        if certification_history:
            self.method_certifications.bind_implementation(
                *key, implementation_sha256=implementation_sha256
            )
        self.scientific_reasoning.rules.register(rule)
        self.scientific_methods.register(manifest)
        if certification_history:
            event = None
        else:
            event = self.method_certifications.register(
                manifest.method_id,
                manifest.version,
                implementation_sha256=implementation_sha256,
            )
        self._index_memory_artifact(
            artifact_id=f"method:{manifest.method_id}@{manifest.version}",
            artifact_type="scientific_method", payload=manifest,
            method_id=manifest.method_id, method_version=manifest.version,
        )
        if event is not None:
            self.audit_trail.append(
                aggregate_id=f"method:{manifest.method_id}@{manifest.version}",
                event_type="method_certification", actor="satquery.registry",
                payload=event.model_dump(mode="json"),
            )

    def register_scientific_benchmark_suite(self, suite: ScientificBenchmarkSuite) -> None:
        self._ensure_open()
        key = (suite.suite_id, suite.version)
        if key in self._benchmark_suites:
            raise ValueError(f"benchmark suite already registered: {key[0]}@{key[1]}")
        method = self.scientific_methods.get(suite.method_id, suite.method_version)
        if method is None:
            raise ValueError("benchmark suite references an unregistered method version")
        if method.rule.implementation_sha256 is None:
            raise ValueError("benchmark execution requires a content-addressed implementation")
        self._benchmark_suites[key] = suite

    def validate_scientific_method(
        self, suite_id: str, suite_version: str, runner: ScientificMethodRunner,
        *, dataset_loader: ValidationDatasetLoader,
        execution_environment: dict[str, str],
    ) -> ReproducibilityReport:
        self._ensure_open()
        suite = self._benchmark_suites[(suite_id, suite_version)]
        method = self.scientific_methods.get(suite.method_id, suite.method_version)
        report = self.method_certifications.execute_benchmark(
            suite, implementation_sha256=method.rule.implementation_sha256 or "",
            runner=runner, dataset_loader=dataset_loader,
            execution_environment=execution_environment,
        )
        self.audit_trail.append(
            aggregate_id=f"method:{report.method_id}@{report.method_version}",
            event_type="method_certification", actor=runner.runner_id,
            payload={
                "report_id": report.report_id,
                "report_sha256": report.report_sha256,
                "status": report.status,
                "suite_id": report.suite_id,
                "suite_version": report.suite_version,
                "report": report.model_dump(mode="json"),
            },
        )
        return report

    def transition_scientific_method(
        self, method_id: str, method_version: str, *, expected_version: int,
        state: CertificationState, actor: str, rationale: str,
        benchmark_report_ids: tuple[str, ...] = (),
        peer_review: PeerReviewArtifact | None = None,
    ) -> MethodCertificationEvent:
        if self.scientific_methods.get(method_id, method_version) is None:
            raise ValueError("cannot certify an unregistered scientific method version")
        event = self.method_certifications.transition(
            method_id, method_version, expected_version=expected_version,
            state=state, actor=actor, rationale=rationale,
            benchmark_report_ids=benchmark_report_ids, peer_review=peer_review,
        )
        self.audit_trail.append(
            aggregate_id=f"method:{method_id}@{method_version}",
            event_type="method_certification", actor=actor,
            payload=event.model_dump(mode="json"),
        )
        return event

    def register_uncertainty_method(self, method: UncertaintyPropagationMethod) -> None:
        self._ensure_open()
        self.scientific_reasoning.uncertainty_methods.register(method)

    def register_dataset_trust_assertion(
        self, assertion: DatasetTrustAssertion
    ) -> None:
        self._ensure_open()
        self.scientific_reasoning.evidence_evaluation.dataset_trust.register(assertion)

    def register_observation_independence_assertion(
        self, assertion: ObservationIndependenceAssertion
    ) -> None:
        self._ensure_open()
        self.scientific_reasoning.evidence_evaluation.observation_independence.register(
            assertion
        )

    def register_task_handler(self, name: str, handler: TaskHandler) -> None:
        self._ensure_open()
        if not callable(handler):
            raise ExtensionError(
                f"Task handler {name!r} is not callable.",
                context={"handler": name},
            )
        self.task_handlers.register(name, handler)

    def register_task_output_codec(self, codec) -> None:
        """Register a versioned codec required to checkpoint an extension output."""
        self._ensure_open()
        codecs = getattr(self.execution_journal, "codecs", None)
        if codecs is None:
            raise ExtensionError("The configured execution journal does not expose output codecs.")
        codecs.register(codec)

    def record_execution_result(
        self, result: ExecutionResult, *, investigation_id: str | None = None
    ) -> None:
        """Index execution records and observations for durable local inspection."""
        with self._execution_results_lock:
            self._execution_results[result.plan_id] = result
        mission_id = None
        if investigation_id:
            try:
                mission_id = self.investigation_service.get(investigation_id).mission_id
            except Exception:
                mission_id = None
        execution_artifact_id = f"execution:{result.plan_id}:{result.trace_id}"
        self._index_memory_artifact(
            artifact_id=execution_artifact_id, artifact_type="evidence",
            payload=result, investigation_id=investigation_id, mission_id=mission_id,
            metadata={"trace_id": result.trace_id, "status": result.status},
        )
        all_observations: dict[str, Observation] = {}
        all_observation_artifacts: dict[str, str] = {}
        for task in result.tasks:
            output = task.output
            if isinstance(output, dict) and "query_fingerprint" in output:
                try:
                    output = PerceptionResult.model_validate(output)
                except Exception:
                    output = task.output
            elif isinstance(output, dict) and "assessment_id" in output:
                output = EvidenceAssessment.model_validate(output)
            elif isinstance(output, dict) and "reasoning_id" in output:
                output = ScientificReasoningReport.model_validate(output)
            elif (
                isinstance(output, dict)
                and "pipeline_id" in output
                and "materialized_object_ids" in output
            ):
                output = EarthObjectExtractionBatch.model_validate(output)
            observations = getattr(output, "observations", ())
            observation_artifacts: dict[str, str] = {}
            for observation in observations:
                observation_digest = canonical_digest(observation.model_dump(mode="json"))
                observation_artifact_id = (
                    f"observation:{observation.observation_id}:"
                    f"{observation_digest[:16]}:{result.trace_id}"
                )
                observation_artifacts[observation.observation_id] = observation_artifact_id
                previous_observation = all_observations.get(observation.observation_id)
                if previous_observation is not None and previous_observation != observation:
                    raise ValueError(
                        "an execution rebound an observation ID to different content"
                    )
                all_observations[observation.observation_id] = observation
                all_observation_artifacts[observation.observation_id] = observation_artifact_id
                self._index_memory_artifact(
                    artifact_id=observation_artifact_id,
                    artifact_type="observation", payload=observation,
                    investigation_id=investigation_id, mission_id=mission_id,
                    source_artifact_ids=(execution_artifact_id,),
                    observed_at=(observation.observed_at.isoformat() if observation.observed_at else None),
                    metadata={
                        "observation_id": observation.observation_id,
                        "dataset_id": observation.dataset.dataset_id if observation.dataset else None,
                        "canonical_variables": tuple(sorted({
                            item.canonical_variable
                            for item in observation.canonical_measurements
                            if item.semantic_status == "resolved"
                        })),
                    },
                )
            for stack in getattr(output, "observation_stacks", ()):
                self._index_memory_artifact(
                    artifact_id=f"observation-stack:{stack.stack_id}",
                    artifact_type="observation_stack",
                    payload=stack,
                    investigation_id=investigation_id,
                    mission_id=mission_id,
                    source_artifact_ids=tuple(
                        observation_artifacts[member.observation_id]
                        for member in stack.members
                        if member.observation_id in observation_artifacts
                    ),
                    metadata={
                        "stack_id": stack.stack_id,
                        "variable_key": stack.variable_key,
                        "canonical_variable": stack.canonical_variable,
                        "member_count": len(stack.members),
                    },
                )
            for diagnostic in getattr(output, "temporal_differences", ()):
                source_ids = [f"observation-stack:{diagnostic.stack_id}"]
                source_ids.extend(
                    observation_artifacts[member.observation_id]
                    for member in (diagnostic.earlier, diagnostic.later)
                    if member.observation_id in observation_artifacts
                )
                self._index_memory_artifact(
                    artifact_id=f"temporal-difference:{diagnostic.diagnostic_id}",
                    artifact_type="temporal_difference",
                    payload=diagnostic,
                    investigation_id=investigation_id,
                    mission_id=mission_id,
                    method_id=diagnostic.method_id,
                    method_version=diagnostic.method_version,
                    source_artifact_ids=tuple(source_ids),
                    observed_at=diagnostic.later.observed_at.isoformat(),
                    metadata={
                        "stack_id": diagnostic.stack_id,
                        "canonical_variable": diagnostic.canonical_variable,
                        "canonical_variables": (
                            (diagnostic.canonical_variable,)
                            if diagnostic.canonical_variable else ()
                        ),
                        "unit": diagnostic.unit,
                        "interpretation_status": diagnostic.interpretation_status,
                        "uncertainty_status": diagnostic.uncertainty_status,
                    },
                )
            if isinstance(output, EarthObjectExtractionBatch):
                extraction_digest = canonical_digest(output.model_dump(mode="json"))
                self._index_memory_artifact(
                    artifact_id=(
                        f"earth-object-extraction:{result.plan_id}:"
                        f"{extraction_digest[:16]}"
                    ),
                    artifact_type="earth_object_extraction",
                    payload=output,
                    investigation_id=investigation_id,
                    mission_id=mission_id,
                    method_id=output.pipeline_id,
                    method_version=output.pipeline_version,
                    source_artifact_ids=tuple(
                        all_observation_artifacts[item]
                        for item in output.input_observation_ids
                        if item in all_observation_artifacts
                    ),
                    metadata={
                        "pipeline_id": output.pipeline_id,
                        "pipeline_version": output.pipeline_version,
                        "input_count": len(output.input_observation_ids),
                        "declaration_count": len(output.declarations),
                        "issue_count": len(output.issues),
                        "materialized_object_ids": output.materialized_object_ids,
                    },
                )
            if isinstance(output, EvidenceAssessment) and investigation_id:
                self.record_evidence_assessment(investigation_id, output)
            elif isinstance(output, ScientificReasoningReport) and investigation_id:
                self.record_scientific_reasoning(investigation_id, output)
        try:
            execution_digest = canonical_digest(result.model_dump(mode="json"))
            digest_status = "available"
        except Exception as exc:
            execution_digest = None
            digest_status = f"unavailable:{type(exc).__name__}"
        self.audit_trail.append(
            aggregate_id=investigation_id or result.plan_id,
            event_type="execution", actor="satquery.runtime",
            payload={"plan_id": result.plan_id, "status": result.status, "trace_id": result.trace_id,
                     "execution_result_sha256": execution_digest,
                     "execution_result_digest_status": digest_status,
                     "tasks": [{"task_id": task.task_id, "status": task.status, "attempts": task.attempts} for task in result.tasks]},
        )

    def record_investigation_plan(self, plan: InvestigationPlan) -> None:
        with self._investigation_plans_lock:
            self._investigation_plans[plan.plan_id] = plan
        self._index_memory_artifact(
            artifact_id=f"plan:{plan.plan_id}", artifact_type="plan", payload=plan,
        )
        self.audit_trail.append(
            aggregate_id=plan.plan_id, event_type="planning", actor="satquery.planner",
            payload={"plan_id": plan.plan_id, "planner_version": plan.planner_version,
                     "capability_matrix_revision": plan.capability_matrix_revision,
                     "plan_sha256": hashlib.sha256(plan.model_dump_json().encode()).hexdigest()},
        )

    def get_investigation_plan(self, plan_id: str) -> InvestigationPlan:
        from ..errors import ValidationError

        with self._investigation_plans_lock:
            plan = self._investigation_plans.get(plan_id)
        if plan is None:
            artifact = self.earth_memory.get(f"plan:{plan_id}")
            if artifact is not None:
                plan = InvestigationPlan.model_validate(artifact.payload)
                with self._investigation_plans_lock:
                    self._investigation_plans[plan_id] = plan
        if plan is None:
            raise ValidationError(
                "Investigation plan was not found.",
                context={"plan_id": plan_id},
            )
        return plan

    def record_investigation_design(self, design: InvestigationDesign) -> None:
        with self._investigation_designs_lock:
            self._investigation_designs[design.design_id] = design
        self._index_memory_artifact(
            artifact_id=f"design:{design.design_id}", artifact_type="evidence",
            payload=design, source_artifact_ids=(f"plan:{design.plan_id}",),
        )
        self.audit_trail.append(
            aggregate_id=design.plan_id, event_type="workflow_change", actor="satquery.intelligence-design",
            payload={"design_id": design.design_id, "design_sha256": hashlib.sha256(design.model_dump_json().encode()).hexdigest()},
        )

    def get_investigation_design(self, design_id: str) -> InvestigationDesign:
        from ..errors import ValidationError

        with self._investigation_designs_lock:
            design = self._investigation_designs.get(design_id)
        if design is None:
            artifact = self.earth_memory.get(f"design:{design_id}")
            if artifact is not None:
                design = InvestigationDesign.model_validate(artifact.payload)
                with self._investigation_designs_lock:
                    self._investigation_designs[design_id] = design
        if design is None:
            raise ValidationError(
                "Investigation design was not found.",
                context={"design_id": design_id},
            )
        return design

    def record_evidence_assessment(
        self, investigation_id: str, assessment: EvidenceAssessment
    ) -> None:
        with self._evidence_assessments_lock:
            self._evidence_assessments[investigation_id] = assessment
        mission_id = self.investigation_service.get(investigation_id).mission_id
        self._index_memory_artifact(
            artifact_id=f"assessment:{assessment.assessment_id}:{canonical_digest(assessment.model_dump(mode='json'))[:16]}",
            artifact_type="evidence", payload=assessment,
            investigation_id=investigation_id, mission_id=mission_id,
            source_artifact_ids=self._observation_memory_ids(
                assessment.observation_ids, investigation_id=investigation_id
            ),
        )
        assessment_payload = {
            "assessment_id": assessment.assessment_id,
            "status": assessment.status,
            "observation_ids": assessment.observation_ids,
            "assessment_sha256": canonical_digest(assessment.model_dump(mode="json")),
        }
        self.audit_trail.append(
            aggregate_id=investigation_id, event_type="assessment", actor="satquery.evidence-assessment",
            payload=assessment_payload,
        )
        self.audit_trail.append(
            aggregate_id=investigation_id, event_type="evidence_change",
            actor="satquery.evidence-assessment", payload=assessment_payload,
        )

    def get_evidence_assessment(
        self, investigation_id: str
    ) -> EvidenceAssessment | None:
        with self._evidence_assessments_lock:
            assessment = self._evidence_assessments.get(investigation_id)
        if assessment is None:
            candidates = tuple(
                item for item in self.earth_memory.all()
                if item.artifact_type == "evidence"
                and item.investigation_id == investigation_id
                and item.artifact_id.startswith("assessment:")
            )
            if candidates:
                latest = max(candidates, key=lambda item: (item.indexed_at, item.artifact_id))
                assessment = EvidenceAssessment.model_validate(latest.payload)
                with self._evidence_assessments_lock:
                    self._evidence_assessments[investigation_id] = assessment
        return assessment

    def record_scientific_reasoning(
        self, investigation_id: str, report: ScientificReasoningReport
    ) -> None:
        with self._scientific_reasoning_lock:
            self._scientific_reasoning_reports[investigation_id] = report
        mission_id = self.investigation_service.get(investigation_id).mission_id
        self._index_memory_artifact(
            artifact_id=f"reasoning:{report.reasoning_id}", artifact_type="evidence",
            payload=report, investigation_id=investigation_id, mission_id=mission_id,
            source_artifact_ids=self._observation_memory_ids(
                report.observation_ids, investigation_id=investigation_id
            ),
        )
        for hypothesis in report.hypothesis_graph.hypotheses:
            self.index_hypothesis(
                investigation_id, hypothesis, mission_id=mission_id,
            )
        for evaluation in report.rule_evaluations:
            self._index_memory_artifact(
                artifact_id=f"method-use:{investigation_id}:{evaluation.rule_id}@{evaluation.rule_version}:{report.reasoning_id}",
                artifact_type="scientific_method", payload=evaluation,
                investigation_id=investigation_id, mission_id=mission_id,
                method_id=evaluation.rule_id, method_version=evaluation.rule_version,
                source_artifact_ids=self._observation_memory_ids(
                    evaluation.observation_ids, investigation_id=investigation_id
                ),
            )
        self.audit_trail.append(
            aggregate_id=investigation_id, event_type="reasoning", actor="satquery.scientific-reasoning",
            payload={"reasoning_id": report.reasoning_id,
                     "reasoning_report_sha256": canonical_digest(report.model_dump(mode="json")),
                     "reproducibility": report.reproducibility},
        )
        for item in report.rule_evaluations:
            self.audit_trail.append(
                aggregate_id=investigation_id, event_type="rule_execution", actor="satquery.scientific-reasoning",
                payload={"rule_id": item.rule_id, "rule_version": item.rule_version,
                         "status": item.status, "observation_ids": item.observation_ids,
                         "rule_result_sha256": canonical_digest(item.model_dump(mode="json"))},
            )

    def get_scientific_reasoning(
        self, investigation_id: str
    ) -> ScientificReasoningReport | None:
        with self._scientific_reasoning_lock:
            report = self._scientific_reasoning_reports.get(investigation_id)
        if report is None:
            candidates = tuple(
                item for item in self.earth_memory.all()
                if item.artifact_type == "evidence"
                and item.investigation_id == investigation_id
                and item.artifact_id.startswith("reasoning:")
            )
            if candidates:
                latest = max(candidates, key=lambda item: (item.indexed_at, item.artifact_id))
                report = ScientificReasoningReport.model_validate(latest.payload)
                with self._scientific_reasoning_lock:
                    self._scientific_reasoning_reports[investigation_id] = report
        return report

    def ensure_hypothesis_ledger(
        self,
        investigation_id: str,
        candidates: Iterable[CandidateHypothesis],
    ) -> HypothesisLifecycleLedger:
        """Initialize versioned lifecycle records once from the investigation design."""
        design_graph = hypothesis_graph_from_candidates(tuple(candidates))
        with self._hypothesis_ledgers_lock:
            restoration_error = self._hypothesis_restore_errors.get(investigation_id)
            if restoration_error is not None:
                raise ValueError(
                    "hypothesis lifecycle cannot be safely restored: "
                    f"{restoration_error}"
                )
            ledger = self._hypothesis_ledgers.get(investigation_id)
            if ledger is None:
                ledger = self.get_hypothesis_ledger(investigation_id)
                restoration_error = self._hypothesis_restore_errors.get(investigation_id)
                if restoration_error is not None:
                    raise ValueError(
                        "hypothesis lifecycle cannot be safely restored: "
                        f"{restoration_error}"
                    )
            if ledger is not None:
                for expected in design_graph.hypotheses:
                    restored = ledger.get(expected.hypothesis_id)
                    if (
                        restored is None
                        or restored.model_dump(exclude={"version", "lifecycle"})
                        != expected.model_dump(exclude={"version", "lifecycle"})
                    ):
                        message = (
                            "replayed hypothesis lifecycle does not contain the exact "
                            "hypotheses declared by the investigation design"
                        )
                        self._hypothesis_restore_errors[investigation_id] = message
                        raise ValueError(message)
                return ledger
            ledger = HypothesisLifecycleLedger()
            graph = design_graph
            mission_id = self.investigation_service.get(investigation_id).mission_id
            for record in graph.topological_order():
                proposed = record.model_copy(update={"lifecycle": "proposed"})
                ledger.add(
                    proposed,
                    actor="satquery.investigation-design",
                    rationale="Hypothesis preserved from the investigation design.",
                )
                self.record_hypothesis_lifecycle_event(
                    investigation_id, ledger, ledger.events(record.hypothesis_id)[-1],
                    mission_id=mission_id,
                )
                ledger.transition(
                    proposed.hypothesis_id,
                    expected_version=1,
                    status="active",
                    actor="satquery.investigation-design",
                    rationale="Hypothesis entered the active evaluation lifecycle.",
                )
                self.record_hypothesis_lifecycle_event(
                    investigation_id, ledger, ledger.events(record.hypothesis_id)[-1],
                    mission_id=mission_id,
                )
            self._hypothesis_ledgers[investigation_id] = ledger
            return ledger

    def record_hypothesis_lifecycle_event(
        self,
        investigation_id: str,
        ledger: HypothesisLifecycleLedger,
        event: HypothesisLifecycleEvent,
        *,
        mission_id: str | None = None,
    ) -> HypothesisRecord:
        record = ledger.get(event.hypothesis_id)
        if (
            record is None
            or record.version != event.version
            or event not in ledger.events(event.hypothesis_id)
        ):
            raise ValueError("hypothesis lifecycle event does not match its current record")
        try:
            self.audit_trail.append(
                aggregate_id=investigation_id,
                event_type="hypothesis_transition",
                actor=event.actor,
                payload={
                    "hypothesis_id": event.hypothesis_id,
                    "version": event.version,
                    "state": event.to_status,
                    "rationale": event.rationale,
                    "record": record.model_dump(mode="json"),
                    "event": event.model_dump(mode="json"),
                },
            )
        except Exception as exc:
            with self._hypothesis_ledgers_lock:
                self._hypothesis_restore_errors[investigation_id] = (
                    "hypothesis transition could not be committed to the audit trail: "
                    f"{exc}"
                )
            raise
        self.index_hypothesis(investigation_id, record, mission_id=mission_id)
        return record

    def index_investigation(self, investigation) -> None:
        """Index stable identity and an immutable investigation lifecycle snapshot."""
        identity_id = f"investigation:{investigation.investigation_id}"
        if self.earth_memory.get(identity_id) is None:
            self._index_memory_artifact(
                artifact_id=identity_id,
                artifact_type="investigation",
                payload={
                    "investigation_id": investigation.investigation_id,
                    "mission_id": investigation.mission_id,
                },
                investigation_id=investigation.investigation_id,
                mission_id=investigation.mission_id,
                source_artifact_ids=(f"mission:{investigation.mission_id}",),
                metadata={"record_kind": "identity"},
            )
        snapshot_digest = canonical_digest(investigation.model_dump(mode="json"))
        self._index_memory_artifact(
            artifact_id=(
                f"investigation-snapshot:{investigation.investigation_id}:"
                f"{snapshot_digest[:20]}"
            ),
            artifact_type="investigation", payload=investigation,
            investigation_id=investigation.investigation_id,
            mission_id=investigation.mission_id,
            source_artifact_ids=(identity_id, f"mission:{investigation.mission_id}"),
            metadata={"record_kind": "lifecycle_snapshot", "snapshot_sha256": snapshot_digest},
        )

    def _latest_investigation_snapshot_id(self, investigation_id: str) -> str | None:
        candidates = [
            item for item in self.earth_memory.all()
            if item.artifact_type == "investigation"
            and item.investigation_id == investigation_id
            and item.metadata.get("record_kind") == "lifecycle_snapshot"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.indexed_at, item.artifact_id)).artifact_id

    def index_mission(self, mission) -> None:
        """Index the exact mission lifecycle snapshot without semantic expansion."""
        self._index_memory_artifact(
            artifact_id=f"mission:{mission.mission_id}",
            artifact_type="mission",
            payload=mission,
            mission_id=mission.mission_id,
        )

    def index_hypothesis(self, investigation_id: str, hypothesis, *, mission_id: str | None = None) -> None:
        digest = canonical_digest(hypothesis.model_dump(mode="json"))
        self._index_memory_artifact(
            artifact_id=f"hypothesis:{investigation_id}:{hypothesis.hypothesis_id}:v{hypothesis.version}:{digest[:16]}",
            artifact_type="hypothesis", payload=hypothesis,
            investigation_id=investigation_id, mission_id=mission_id,
            source_artifact_ids=tuple(
                f"hypothesis:{investigation_id}:{parent}"
                for parent in hypothesis.parent_hypothesis_ids
            ),
        )

    def index_reproducibility_bundle(self, bundle) -> None:
        artifact_id = f"reproducibility:{bundle.investigation_id}:{bundle.bundle_sha256}"
        existing = self.earth_memory.get(artifact_id)
        if existing is not None:
            if (
                existing.artifact_type != "reproducibility_artifact"
                or existing.payload.get("bundle_sha256") != bundle.bundle_sha256
            ):
                raise ValueError(
                    "reproducibility bundle artifact ID is already bound to different content"
                )
            # Export timestamps are intentionally outside the reproducibility
            # digest, so repeated exports of the same scientific snapshot reuse
            # its immutable memory artifact.
            return
        self._index_memory_artifact(
            artifact_id=artifact_id,
            artifact_type="reproducibility_artifact", payload=bundle,
            investigation_id=bundle.investigation_id,
            source_artifact_ids=tuple(
                f"artifact:{name}:{digest}"
                for name, digest in sorted(bundle.artifact_hashes.items())
            ),
            metadata={"bundle_sha256": bundle.bundle_sha256},
        )

    def materialize_earth_object(
        self,
        declaration: EarthObjectDeclaration,
        observations: tuple[Observation, ...],
        *,
        evidence: tuple[Evidence, ...] = (),
        index_memory: bool = True,
    ):
        """Materialize and index an explicitly declared, evidence-backed object."""
        identity = f"{declaration.identity_namespace}:{declaration.identity_value}"
        # Serialize identity lookup, revision construction, and catalog append.
        # Without this boundary two concurrent investigations can both derive
        # revision N+1 from revision N and one would fail as a false branch.
        with self._earth_object_materialization_lock:
            previous = next(
                (
                    item
                    for item in sorted(
                        self.earth_objects.all(),
                        key=lambda value: value.revision,
                        reverse=True,
                    )
                    if item.stable_identity == identity
                ),
                None,
            )
            item = self.earth_object_materializer.materialize(
                declaration, observations, evidence=evidence, previous=previous,
            )
            if (
                previous is not None
                and item.object_id == previous.object_id
                and index_memory
                and self.earth_memory.get(item.object_id) is not None
            ):
                return previous
            self.earth_objects.put(item)
        if not index_memory:
            return item
        investigation_ids = {record.investigation_id for record in evidence if record.evidence_id in declaration.evidence_ids}
        investigation_id = declaration.investigation_id or (
            next(iter(investigation_ids)) if len(investigation_ids) == 1 else None
        )
        source_artifacts = tuple(sorted(set(
            self._observation_memory_ids(
                item.source_observation_ids,
                item.provenance.get("source_records", ()),
            )
            + tuple(f"evidence:{evidence_id}" for evidence_id in item.evidence_ids)
        )))
        extraction_method_id, extraction_method_version, extraction_method_ids = (
            _declared_extraction_method(declaration)
        )
        for record in evidence:
            if record.evidence_id in declaration.evidence_ids:
                self._index_memory_artifact(
                    artifact_id=f"evidence:{record.evidence_id}", artifact_type="evidence",
                    payload=record, investigation_id=record.investigation_id,
                    source_artifact_ids=(f"observation:{record.observation_id}",) if record.observation_id else (),
                )
        self._index_memory_artifact(
            artifact_id=item.object_id, artifact_type="earth_object", payload=item,
            investigation_id=investigation_id,
            method_id=extraction_method_id,
            method_version=extraction_method_version,
            source_artifact_ids=source_artifacts,
            metadata={"stable_identity": identity, "object_type": item.object_type,
                      "declared_by": declaration.declared_by,
                      "extraction_method_ids": extraction_method_ids,
                      "revision": item.revision, "content_sha256": item.content_sha256,
                      "investigation_ids": item.investigation_ids},
        )
        self.audit_trail.append(
            aggregate_id=item.object_id, event_type="earth_object_materialized",
            actor=self.earth_object_materializer.MATERIALIZER_ID,
            payload={"stable_identity": identity, "revision": item.revision,
                     "declared_by": declaration.declared_by,
                     "content_sha256": item.content_sha256,
                     "lifecycle": item.lifecycle,
                     "source_observation_ids": item.source_observation_ids,
                     "evidence_ids": item.evidence_ids},
        )
        if declaration.revision_transition is not None:
            transition = declaration.revision_transition
            self.audit_trail.append(
                aggregate_id=(
                    declaration.investigation_id
                    or item.investigation_id
                    or item.stable_identity
                    or item.object_id
                ),
                event_type="earth_object_transition",
                actor=transition.actor,
                payload={
                    "transition": transition.model_dump(mode="json"),
                    "result_object_id": item.object_id,
                    "result_revision": item.revision,
                    "content_sha256": item.content_sha256,
                },
            )
            mission_id = None
            if investigation_id:
                try:
                    mission_id = self.investigation_service.get(
                        investigation_id
                    ).mission_id
                except Exception:
                    mission_id = None
            transition_sources = set(
                self._observation_memory_ids(
                    transition.observation_ids, investigation_id=investigation_id
                )
            )
            transition_sources.update(
                f"evidence:{evidence_id}" for evidence_id in transition.evidence_ids
            )
            transition_sources.add(transition.prior_object_id)
            transition_sources.add(item.object_id)
            self._index_memory_artifact(
                artifact_id=f"earth-object-transition:{item.object_id}",
                artifact_type="earth_object_transition",
                payload=transition,
                investigation_id=investigation_id,
                mission_id=mission_id,
                source_artifact_ids=tuple(sorted(transition_sources)),
                metadata={
                    "transition_type": transition.transition_type,
                    "prior_object_id": transition.prior_object_id,
                    "result_object_id": item.object_id,
                    "result_revision": item.revision,
                },
            )
        return item

    def _extract_earth_objects(
        self,
        observations: tuple[Observation, ...],
        *,
        investigation_id: str | None,
        index_memory: bool = True,
        query: EarthQuery | None = None,
    ):
        """Run explicit-candidate extraction and commit its canonical objects."""
        extraction = self.earth_object_extraction_pipeline.extract(
            observations, investigation_id=investigation_id, query=query
        )
        observations_by_id = {item.observation_id: item for item in observations}
        materialized_object_ids: list[str] = []
        for declaration in extraction.declarations:
            selected_observations = tuple(
                observations_by_id[item] for item in declaration.observation_ids
            )
            try:
                materialized = self.materialize_earth_object(
                    declaration,
                    selected_observations,
                    index_memory=index_memory,
                )
                materialized_object_ids.append(materialized.object_id)
            except ValueError as exc:
                rejection = EarthObjectExtractionIssue(
                    identity=(
                        f"{declaration.identity_namespace}:"
                        f"{declaration.identity_value}"
                    ),
                    observation_ids=declaration.observation_ids,
                    code="materialization_rejected",
                    message=f"Earth Object materialization was rejected: {exc}",
                )
                extraction = extraction.model_copy(
                    update={"issues": (*extraction.issues, rejection)}
                )
                if index_memory:
                    self.audit_trail.append(
                        aggregate_id=declaration.identity_value,
                        event_type="earth_object_candidate_rejected",
                        actor=declaration.declared_by,
                        payload={
                            "declaration": declaration.model_dump(mode="json"),
                            "reason": str(exc),
                        },
                    )
        for issue in extraction.issues:
            if index_memory:
                self.audit_trail.append(
                    aggregate_id=issue.identity,
                    event_type="earth_object_candidate_rejected",
                    actor=self.earth_object_extraction_pipeline.PIPELINE_ID,
                    payload=issue.model_dump(mode="json"),
                )
        return extraction.model_copy(
            update={"materialized_object_ids": tuple(materialized_object_ids)}
        )

    def _restore_earth_objects_from_memory(self) -> None:
        """Restore immutable object snapshots and edges from the configured memory store."""
        artifacts = self.earth_memory.all()
        object_artifacts = sorted(
            (item for item in artifacts if item.artifact_type == "earth_object"),
            key=lambda item: (_memory_object_revision(item), item.artifact_id),
        )
        for artifact in object_artifacts:
            try:
                self.earth_objects.put(EarthObject.model_validate(artifact.payload))
            except ValueError as exc:
                self.audit_trail.append(
                    aggregate_id=artifact.artifact_id,
                    event_type="earth_object_restore_rejected",
                    actor="satquery.runtime",
                    payload={"artifact_type": "earth_object", "reason": str(exc)},
                )
        for artifact in artifacts:
            if artifact.artifact_type == "object_relationship":
                relationship = EarthObjectRelationship.model_validate(artifact.payload)
                # A corrupt or incomplete old index must not prevent the runtime
                # from starting; integrity remains visible through memory audit.
                try:
                    self.earth_objects.put_relationship(relationship)
                except ValueError as exc:
                    self.audit_trail.append(
                        aggregate_id=artifact.artifact_id,
                        event_type="earth_object_restore_rejected",
                        actor="satquery.runtime",
                        payload={"artifact_type": "object_relationship", "reason": str(exc)},
                    )

    def _restore_scientific_certifications_from_audit(self) -> None:
        """Rebuild certification state only from verified, complete audit records."""
        for aggregate_id in self.audit_trail.aggregate_ids():
            if not aggregate_id.startswith("method:"):
                continue
            identity = aggregate_id.removeprefix("method:")
            if "@" not in identity:
                raise ValueError(f"invalid scientific method audit aggregate: {aggregate_id}")
            method_id, method_version = identity.rsplit("@", maxsplit=1)
            try:
                for audit_event in self.audit_trail.events(aggregate_id):
                    if audit_event.event_type != "method_certification":
                        continue
                    payload = audit_event.payload
                    report_payload = payload.get("report")
                    if report_payload is not None:
                        report = ReproducibilityReport.model_validate(report_payload)
                        if (
                            f"{report.method_id}@{report.method_version}" != identity
                            or payload.get("report_id") != report.report_id
                            or payload.get("report_sha256") != report.report_sha256
                            or payload.get("status") != report.status
                            or payload.get("suite_id") != report.suite_id
                            or payload.get("suite_version") != report.suite_version
                            or audit_event.actor != report.runner_id
                        ):
                            raise ValueError(
                                "scientific benchmark audit record is inconsistent"
                            )
                        self.method_certifications.restore_report(report)
                    elif "event_id" in payload and "state" in payload:
                        event = MethodCertificationEvent.model_validate(payload)
                        if (
                            f"{event.method_id}@{event.method_version}" != identity
                            or event.actor != audit_event.actor
                        ):
                            raise ValueError(
                                "scientific certification audit record is inconsistent"
                            )
                        self.method_certifications.restore_event(event)
                    elif "report_id" in payload:
                        raise ValueError(
                            "summary-only benchmark history has no replayable report; "
                            "revalidation is required"
                        )
                    else:
                        raise ValueError(
                            "unrecognized scientific certification audit record"
                        )
            except ValueError as exc:
                self.method_certifications.mark_unrestorable(
                    method_id, method_version, str(exc)
                )

    def add_earth_object_relationship(self, relationship: EarthObjectRelationship):
        self.earth_objects.put_relationship(relationship)
        self._index_memory_artifact(
            artifact_id=f"object-relationship:{relationship.relationship_id}",
            artifact_type="object_relationship", payload=relationship,
            source_artifact_ids=tuple(
                [relationship.source_object_id, relationship.target_object_id]
                + [f"evidence:{item}" for item in relationship.evidence_ids]
                + [f"observation:{item}" for item in relationship.observation_ids]
            ),
        )
        self.audit_trail.append(
            aggregate_id=relationship.relationship_id,
            event_type="earth_object_relationship_asserted",
            actor=relationship.asserted_by,
            payload=relationship.model_dump(mode="json"),
        )
        return relationship

    def _index_memory_artifact(
        self, *, artifact_id: str, artifact_type: str, payload,
        investigation_id: str | None = None, mission_id: str | None = None,
        method_id: str | None = None, method_version: str | None = None,
        source_artifact_ids=(), observed_at: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        from .contracts import utc_now

        candidate = artifact_from_payload(
            artifact_id=artifact_id, artifact_type=artifact_type, payload=payload,
            indexed_at=utc_now().isoformat(), investigation_id=investigation_id,
            mission_id=mission_id, method_id=method_id, method_version=method_version,
            source_artifact_ids=source_artifact_ids, observed_at=observed_at,
            metadata=metadata,
        )
        existing = self.earth_memory.get(artifact_id)
        # Re-indexing an unchanged source object is idempotent across runtime
        # restarts; preserve the original immutable index timestamp.
        if (
            existing is not None
            and candidate.model_copy(update={"indexed_at": existing.indexed_at}) == existing
        ):
            return
        self.earth_memory.upsert(candidate)

    def search_earth_memory(self, query: EarthMemoryQuery):
        return self.earth_memory.search(query)

    def create_monitoring_schedule(self, schedule: MonitoringSchedule) -> MonitoringSchedule:
        self.index_mission(self.mission_service.get(schedule.mission_id))
        created = self.monitoring_service.create(schedule)
        self._index_monitoring_schedule(created)
        self._index_monitoring_events(created.schedule_id)
        return created

    def set_monitoring_schedule_enabled(
        self, schedule_id: str, enabled: bool
    ) -> MonitoringSchedule:
        updated = self.monitoring_service.set_enabled(schedule_id, enabled)
        self._index_monitoring_schedule(updated)
        self._index_monitoring_events(schedule_id)
        return updated

    def revise_monitoring_schedule(
        self, schedule_id: str, update: MonitoringScheduleUpdate
    ) -> MonitoringSchedule:
        revised = self.monitoring_service.revise(schedule_id, update)
        self._index_monitoring_schedule(revised)
        self._index_monitoring_events(schedule_id)
        return revised

    def acknowledge_monitoring_notification(
        self, notification_id: str
    ) -> MonitoringNotification:
        updated = self.monitoring_service.acknowledge_notification(notification_id)
        self._index_monitoring_notification(updated)
        schedule = self.monitoring_service.get(updated.schedule_id)
        self._index_monitoring_events(schedule.schedule_id, updated.run_id)
        return updated

    def compare_monitoring_schedule(
        self, schedule_id: str, *, limit: int = 10
    ):
        """Align recorded measurements from recent successful schedule runs.

        The comparison engine reports exact canonical variable/unit matches
        only; it does not infer a trend or scientifically comparable change.
        """
        if not 2 <= limit <= 20:
            raise ValueError("monitoring comparison limit must be between 2 and 20")
        schedule = self.monitoring_service.get(schedule_id)
        runs = sorted(
            (
                run for run in self.monitoring_service.runs(schedule_id)
                if run.investigation_id is not None
                and run.status in {"completed", "partial"}
            ),
            key=lambda run: (run.started_at, run.run_id),
        )[-limit:]
        if len(runs) < 2:
            raise ValueError(
                "at least two completed or partial monitoring investigations are required"
            )
        from .comparisons import InvestigationComparisonRequest

        comparison = self.compare_investigations(
            InvestigationComparisonRequest(investigation_ids=tuple(
                run.investigation_id for run in runs if run.investigation_id
            )),
        )
        payload = comparison.model_dump(mode="json")
        self._index_memory_artifact(
            artifact_id=f"monitoring-comparison:{comparison.comparison_sha256}",
            artifact_type="monitoring_comparison",
            payload=payload,
            mission_id=schedule.mission_id,
            source_artifact_ids=tuple(
                [run.run_id for run in runs]
                + [f"investigation:{run.investigation_id}" for run in runs]
                + [
                    snapshot_id
                    for run in runs
                    if run.investigation_id
                    for snapshot_id in (
                        self._latest_investigation_snapshot_id(run.investigation_id),
                    )
                    if snapshot_id is not None
                ]
            ),
            metadata={
                "schedule_id": schedule_id,
                "run_ids": [run.run_id for run in runs],
                "comparison_sha256": comparison.comparison_sha256,
            },
        )
        return comparison

    def compare_investigations(self, request):
        """Create and persist a deterministic comparison of recorded investigations."""
        from .comparisons import compare_investigations

        comparison = compare_investigations(self, request)
        investigations = tuple(
            self.investigation_service.get(identifier)
            for identifier in sorted(request.investigation_ids)
        )
        mission_ids = {item.mission_id for item in investigations}
        source_ids = set()
        observation_ids_by_investigation: dict[str, set[str]] = {}
        for investigation in investigations:
            source_ids.add(f"investigation:{investigation.investigation_id}")
            observation_ids = set()
            for result_id in investigation.result_ids:
                result = self.get_execution_result(result_id)
                for task in result.tasks:
                    for observation in getattr(task.output, "observations", ()):
                        observation_ids.add(observation.observation_id)
            observation_ids_by_investigation[investigation.investigation_id] = observation_ids
            source_ids.update(self._observation_memory_ids(
                observation_ids, investigation_id=investigation.investigation_id
            ))
        artifact_id = f"investigation-comparison:{comparison.comparison_sha256}"
        existing = self.earth_memory.get(artifact_id)
        self._index_memory_artifact(
            artifact_id=artifact_id,
            artifact_type="investigation_comparison",
            payload=comparison.model_dump(mode="json"),
            mission_id=next(iter(mission_ids)) if len(mission_ids) == 1 else None,
            source_artifact_ids=tuple(source_ids),
            metadata={"comparison_sha256": comparison.comparison_sha256},
        )
        for diagnostic in comparison.temporal_diagnostics:
            member_ids = {
                diagnostic.earlier.observation_id,
                diagnostic.later.observation_id,
            }
            linked_investigations = tuple(
                item for item in investigations
                if observation_ids_by_investigation[item.investigation_id].intersection(member_ids)
            )
            diagnostic_sources = {artifact_id}
            for item in linked_investigations:
                diagnostic_sources.add(f"investigation:{item.investigation_id}")
                linked_observation_ids = observation_ids_by_investigation[
                    item.investigation_id
                ].intersection(member_ids)
                diagnostic_sources.update(self._observation_memory_ids(
                    linked_observation_ids,
                    investigation_id=item.investigation_id,
                ))
            self._index_memory_artifact(
                artifact_id=(
                    f"investigation-comparison-temporal-difference:"
                    f"{comparison.comparison_sha256}:{diagnostic.diagnostic_id}"
                ),
                artifact_type="temporal_difference",
                payload=diagnostic,
                mission_id=(next(iter(mission_ids)) if len(mission_ids) == 1 else None),
                method_id=diagnostic.method_id,
                method_version=diagnostic.method_version,
                source_artifact_ids=tuple(diagnostic_sources),
                observed_at=diagnostic.later.observed_at.isoformat(),
                metadata={
                    "comparison_id": comparison.comparison_id,
                    "comparison_sha256": comparison.comparison_sha256,
                    "interpretation_status": diagnostic.interpretation_status,
                    "uncertainty_status": diagnostic.uncertainty_status,
                },
            )
        if existing is None:
            for investigation in investigations:
                self.audit_trail.append(
                    aggregate_id=investigation.investigation_id,
                    event_type="investigation_comparison",
                    actor="satquery.investigation-comparison",
                    payload={
                        "comparison_id": comparison.comparison_id,
                        "comparison_sha256": comparison.comparison_sha256,
                        "investigation_ids": tuple(sorted(request.investigation_ids)),
                        "source_artifact_ids": tuple(sorted(source_ids)),
                    },
                )
        return comparison

    async def run_due_monitoring(
        self, *, limit: int = 100, now=None
    ) -> tuple[MonitoringRun, ...]:
        if limit < 1:
            raise ValueError("monitoring run limit must be positive")
        # Callers may request a smaller batch, but cannot bypass the configured
        # per-tick resource budget through the API or a manual scheduler call.
        effective_limit = min(limit, self.config.monitoring.max_runs_per_tick)
        try:
            runs = await self.monitoring_service.run_due(
                self.execute_investigation, limit=effective_limit, now=now
            )
        except asyncio.CancelledError:
            # Persisted run state is finalized by the service before cancellation
            # propagates; mirror it into Earth Memory for replay and inspection.
            for schedule in self.monitoring_service.list():
                for run in self.monitoring_service.runs(schedule.schedule_id):
                    if run.failure_type == "scheduler_cancelled":
                        self._index_monitoring_run(run)
                        self._index_monitoring_events(run.schedule_id, run.run_id)
            raise
        for run in runs:
            self._index_monitoring_run(run)
            self._index_monitoring_events(run.schedule_id, run.run_id)
        for schedule in self.monitoring_service.list():
            self._index_monitoring_schedule(schedule)
        async with self._monitoring_trigger_lock:
            trigger_budget = self.config.monitoring.max_triggered_investigations_per_tick
            recovered = await self._recover_monitoring_trigger_chains(
                limit=trigger_budget,
                now=now or utc_now(),
            )
            await self._run_monitoring_trigger_policies(
                now=now,
                limit=max(0, trigger_budget - recovered),
            )
        return runs

    async def _run_monitoring_trigger_policies(
        self, *, now=None, limit: int
    ) -> None:
        """Evaluate explicit policies over recorded exact-support differences.

        Policy values and follow-up EarthQueries are operator supplied. This
        method performs no statistical test and does not infer scientific
        significance. Deterministic event and investigation identities make
        restarts resume the same follow-up instead of duplicating it.
        """
        instant = now or utc_now()
        if instant.tzinfo is None:
            raise ValueError("monitoring trigger clock must be timezone-aware")
        launched = 0
        for schedule in self.monitoring_service.list():
            if not schedule.enabled or not schedule.trigger_policies:
                continue
            try:
                comparison = self.compare_monitoring_schedule(schedule.schedule_id)
            except ValueError:
                # Fewer than two usable monitoring investigations is an
                # explicit absence of evaluable evidence, not a trigger miss.
                continue
            latest_runs = [
                run for run in self.monitoring_service.runs(schedule.schedule_id)
                if run.investigation_id and run.status in {"completed", "partial"}
            ]
            source_run = latest_runs[-1] if latest_runs else None
            for policy in schedule.trigger_policies:
                for diagnostic in comparison.temporal_diagnostics:
                    if launched >= limit:
                        return
                    identity = canonical_digest({
                        "schedule_id": schedule.schedule_id,
                        "policy_id": policy.policy_id,
                        "policy_sha256": canonical_digest(
                            policy.model_dump(mode="json")
                        ),
                        "diagnostic_id": diagnostic.diagnostic_id,
                    })
                    evaluation = MonitoringTriggerEvaluation(
                        evaluation_id=identity,
                        schedule_id=schedule.schedule_id,
                        schedule_revision=schedule.revision,
                        policy_id=policy.policy_id,
                        policy_name=policy.name,
                        diagnostic_id=diagnostic.diagnostic_id,
                        source_observation_ids=(
                            diagnostic.earlier.observation_id,
                            diagnostic.later.observation_id,
                        ),
                        source_run_id=source_run.run_id if source_run else None,
                        comparison_sha256=comparison.comparison_sha256,
                        matched=policy.matches(diagnostic),
                        reason=(
                            "exact canonical variable and unit matched the configured "
                            "scalar predicate"
                            if policy.matches(diagnostic)
                            else "diagnostic did not satisfy the configured variable, "
                            "unit, or scalar predicate"
                        ),
                        evaluated_at=instant,
                    )
                    evaluation_event = MonitoringEvent(
                        event_id=f"trigger:{identity}:evaluated",
                        event_type="trigger_evaluated",
                        schedule_id=schedule.schedule_id,
                        run_id=source_run.run_id if source_run else None,
                        occurred_at=instant,
                        payload={
                            **evaluation.model_dump(mode="json"),
                            "policy_name": policy.name,
                            "source_observation_ids": list(
                                evaluation.source_observation_ids
                            ),
                        },
                    )
                    inserted_evaluation = self._record_monitoring_event(evaluation_event)
                    if not inserted_evaluation:
                        prior_evaluation = self.monitoring_service.get_event(
                            evaluation_event.event_id
                        )
                        if prior_evaluation is None:
                            # Never create a second trigger if the durable record
                            # cannot be read after an idempotent insert.
                            continue
                        evaluation = MonitoringTriggerEvaluation.model_validate(
                            prior_evaluation.payload
                        )
                    if not evaluation.matched:
                        continue
                    if self.monitoring_service.get_event(
                        f"trigger:{identity}:cooldown"
                    ) is not None:
                        continue
                    if self.monitoring_service.get_event(
                        f"trigger:{identity}:investigation-terminal"
                    ) is not None:
                        continue
                    if self._monitoring_trigger_in_cooldown(
                        schedule.schedule_id, policy.policy_id, instant,
                        policy.cooldown_seconds,
                        exclude_evaluation_id=identity,
                    ):
                        suppression = MonitoringEvent(
                            event_id=f"trigger:{identity}:cooldown",
                            event_type="trigger_suppressed_cooldown",
                            schedule_id=schedule.schedule_id,
                            run_id=source_run.run_id if source_run else None,
                            occurred_at=instant,
                            payload={
                                "policy_id": policy.policy_id,
                                "diagnostic_id": diagnostic.diagnostic_id,
                                "comparison_sha256": comparison.comparison_sha256,
                                "source_observation_ids": [
                                    diagnostic.earlier.observation_id,
                                    diagnostic.later.observation_id,
                                ],
                                "cooldown_seconds": policy.cooldown_seconds,
                                "evaluation_id": identity,
                            },
                        )
                        self._record_monitoring_event(suppression)
                        continue
                    matched_event = MonitoringEvent(
                        event_id=f"trigger:{identity}:matched",
                        event_type="trigger_matched",
                        schedule_id=schedule.schedule_id,
                        run_id=source_run.run_id if source_run else None,
                        occurred_at=instant,
                        payload={
                            "policy_id": policy.policy_id,
                            "policy_name": policy.name,
                            "diagnostic_id": diagnostic.diagnostic_id,
                            "comparison_sha256": comparison.comparison_sha256,
                            "difference_value": diagnostic.difference_value,
                            "unit": diagnostic.unit,
                            "source_observation_ids": [
                                diagnostic.earlier.observation_id,
                                diagnostic.later.observation_id,
                            ],
                            "detail": (
                                f"{diagnostic.canonical_variable} difference "
                                f"{diagnostic.difference_value} {diagnostic.unit} "
                                f"matched operator-authored policy {policy.name!r}."
                            ),
                            "evaluation_id": identity,
                        },
                    )
                    self._record_monitoring_event(matched_event)
                    investigation_id = f"triggered-{identity[:32]}"
                    task = Task(
                        task_id=f"trigger-task-{identity[:24]}",
                        handler="earth.observe",
                        description=f"Monitoring follow-up: {policy.name}",
                        max_attempts=policy.max_attempts,
                        retry_safe=policy.retry_safe,
                        parameters={
                            "earth_query": policy.follow_up_query.model_dump(mode="json"),
                            "monitoring_trigger": {
                                "evaluation_id": identity,
                                "schedule_id": schedule.schedule_id,
                                "schedule_revision": schedule.revision,
                                "policy_id": policy.policy_id,
                                "diagnostic_id": diagnostic.diagnostic_id,
                                "comparison_sha256": comparison.comparison_sha256,
                                "source_observation_ids": [
                                    diagnostic.earlier.observation_id,
                                    diagnostic.later.observation_id,
                                ],
                                "source_run_id": source_run.run_id if source_run else None,
                                "matched_difference": diagnostic.difference_value,
                                "unit": diagnostic.unit,
                                "interpretation_status": "descriptive_only",
                                "uncertainty_status": "not_propagated",
                            },
                        },
                    )
                    try:
                        try:
                            investigation = self.investigation_service.get(investigation_id)
                        except ValidationError:
                            existing = {
                                item.investigation_id
                                for item in self.investigation_service.list_for_mission(
                                    schedule.mission_id
                                )
                            }
                            if investigation_id in existing:
                                raise
                            try:
                                investigation = self.mission_service.create_investigation(
                                    schedule.mission_id, (task,),
                                    investigation_id=investigation_id,
                                )
                            except ValueError:
                                # A second process may have committed the same
                                # deterministic child between lookup and create.
                                investigation = self.investigation_service.get(
                                    investigation_id
                                )
                        created = MonitoringEvent(
                            event_id=f"trigger:{identity}:investigation-created",
                            event_type="trigger_investigation_created",
                            schedule_id=schedule.schedule_id,
                            run_id=source_run.run_id if source_run else None,
                            occurred_at=instant,
                            payload={
                                "evaluation_id": identity,
                                "policy_id": policy.policy_id,
                                "policy": policy.model_dump(mode="json"),
                                "diagnostic_id": diagnostic.diagnostic_id,
                                "comparison_sha256": comparison.comparison_sha256,
                                "source_observation_ids": [
                                    diagnostic.earlier.observation_id,
                                    diagnostic.later.observation_id,
                                ],
                                "investigation_id": investigation.investigation_id,
                                "parent_investigation_ids": [
                                    run.investigation_id for run in latest_runs[-2:]
                                ],
                            },
                        )
                        self._record_monitoring_event(created)
                        if investigation.status.value not in {"completed", "partial"}:
                            current = self.investigation_service.get(investigation_id)
                            await self.execute_investigation(
                                investigation_id,
                                resume=current.status.value != "pending",
                            )
                        final = self.investigation_service.get(investigation_id)
                        if final.status.value in {"failed", "cancelled"}:
                            self._record_monitoring_event(MonitoringEvent(
                                event_id=f"trigger:{identity}:investigation-failed:1",
                                event_type="trigger_investigation_failed",
                                schedule_id=schedule.schedule_id,
                                run_id=source_run.run_id if source_run else None,
                                occurred_at=final.finished_at or instant,
                                payload={
                                    "evaluation_id": identity,
                                    "policy_id": policy.policy_id,
                                    "investigation_id": investigation_id,
                                    "failure_type": final.status.value,
                                    "attempt_limit": policy.max_attempts,
                                    "retry_safe": policy.retry_safe,
                                    "final": True,
                                },
                            ))
                        terminal_event_type = (
                            "trigger_investigation_completed"
                            if final.status.value in {"completed", "partial"}
                            else "trigger_investigation_failed"
                        )
                        terminal = MonitoringEvent(
                            event_id=f"trigger:{identity}:investigation-terminal",
                            event_type=terminal_event_type,
                            schedule_id=schedule.schedule_id,
                            run_id=source_run.run_id if source_run else None,
                            occurred_at=final.finished_at or instant,
                            payload={
                                "evaluation_id": identity,
                                "policy_id": policy.policy_id,
                                "investigation_id": investigation_id,
                                "investigation_status": final.status.value,
                            },
                        )
                        self._record_monitoring_event(terminal)
                    except Exception as exc:
                        logger.exception(
                            "monitoring trigger follow-up failed",
                            extra={
                                "schedule_id": schedule.schedule_id,
                                "policy_id": policy.policy_id,
                                "evaluation_id": identity,
                                "investigation_id": investigation_id,
                            },
                        )
                        prior_failures = sum(
                            event.event_type == "trigger_investigation_failed"
                            and event.payload.get("evaluation_id") == identity
                            for event in self.monitoring_service.iter_events(
                                schedule.schedule_id
                            )
                        )
                        failed = MonitoringEvent(
                            event_id=(
                                f"trigger:{identity}:investigation-failed:"
                                f"{prior_failures + 1}"
                            ),
                            event_type="trigger_investigation_failed",
                            schedule_id=schedule.schedule_id,
                            run_id=source_run.run_id if source_run else None,
                            occurred_at=instant,
                            payload={
                                "evaluation_id": identity,
                                "policy_id": policy.policy_id,
                                "investigation_id": investigation_id,
                                "failure_type": type(exc).__name__,
                                "final": False,
                            },
                        )
                        self._record_monitoring_event(failed)
                        try:
                            current = self.investigation_service.get(investigation_id)
                        except ValidationError:
                            current = None
                        if current is not None and current.status.value in {
                            "completed", "partial", "failed", "cancelled"
                        }:
                            self._record_monitoring_event(MonitoringEvent(
                                event_id=f"trigger:{identity}:investigation-terminal",
                                event_type=(
                                    "trigger_investigation_completed"
                                    if current.status.value in {"completed", "partial"}
                                    else "trigger_investigation_failed"
                                ),
                                schedule_id=schedule.schedule_id,
                                run_id=source_run.run_id if source_run else None,
                                occurred_at=current.finished_at or instant,
                                payload={
                                    "evaluation_id": identity,
                                    "policy_id": policy.policy_id,
                                    "investigation_id": investigation_id,
                                    "investigation_status": current.status.value,
                                    "failure_type": type(exc).__name__,
                                },
                            ))
                    launched += 1

    async def _recover_monitoring_trigger_chains(self, *, limit: int, now) -> int:
        """Resume trigger-created investigations left nonterminal by a restart."""
        if limit < 0:
            raise ValueError("monitoring trigger recovery limit cannot be negative")
        recovered = 0
        for schedule in self.monitoring_service.list():
            created_by_evaluation: dict[str, MonitoringEvent] = {}
            for event in self.monitoring_service.iter_events(schedule.schedule_id):
                evaluation_value = event.payload.get("evaluation_id")
                if (
                    event.event_type == "trigger_investigation_created"
                    and isinstance(evaluation_value, str)
                    and self.monitoring_service.get_event(
                        f"trigger:{evaluation_value}:investigation-terminal"
                    ) is None
                ):
                    created_by_evaluation.setdefault(evaluation_value, event)
            failed_attempts_by_evaluation: dict[str, int] = {}
            if created_by_evaluation:
                for event in self.monitoring_service.iter_events(schedule.schedule_id):
                    evaluation_value = event.payload.get("evaluation_id")
                    if (
                        event.event_type == "trigger_investigation_failed"
                        and isinstance(evaluation_value, str)
                        and evaluation_value in created_by_evaluation
                    ):
                        failed_attempts_by_evaluation[evaluation_value] = (
                            failed_attempts_by_evaluation.get(evaluation_value, 0) + 1
                        )
            for evaluation_id, created in created_by_evaluation.items():
                investigation_id = created.payload.get("investigation_id")
                if not isinstance(investigation_id, str):
                    continue
                investigation = None
                try:
                    investigation = self.investigation_service.get(investigation_id)
                except ValidationError:
                    status = "missing"
                    failure_type = "triggered_investigation_missing"
                else:
                    status = investigation.status.value
                    failure_type = None
                failed_attempts = failed_attempts_by_evaluation.get(evaluation_id, 0)
                policy_snapshot = created.payload.get("policy", {})
                max_attempts = (
                    int(policy_snapshot.get("max_attempts", 1))
                    if isinstance(policy_snapshot, dict) else 1
                )
                retries_exhausted = failed_attempts >= max_attempts
                if (
                    status in {"pending", "running"}
                    and not retries_exhausted
                    and recovered < limit
                ):
                    try:
                        await self.execute_investigation(
                            investigation_id, resume=status == "running"
                        )
                        investigation = self.investigation_service.get(investigation_id)
                        status = investigation.status.value
                    except Exception as exc:
                        failure_type = type(exc).__name__
                        logger.exception(
                            "monitoring trigger recovery failed",
                            extra={
                                "schedule_id": schedule.schedule_id,
                                "evaluation_id": evaluation_id,
                                "investigation_id": investigation_id,
                            },
                        )
                        try:
                            investigation = self.investigation_service.get(investigation_id)
                            status = investigation.status.value
                        except ValidationError:
                            investigation = None
                            status = "missing"
                            failure_type = "triggered_investigation_missing"
                    recovered += 1
                completed = status in {"completed", "partial"}
                terminal = MonitoringEvent(
                    event_id=f"trigger:{evaluation_id}:investigation-terminal",
                    event_type=(
                        "trigger_investigation_completed"
                        if completed else "trigger_investigation_failed"
                    ),
                    schedule_id=schedule.schedule_id,
                    run_id=created.run_id,
                    occurred_at=getattr(investigation, "finished_at", None)
                    or created.occurred_at,
                    payload={
                        "evaluation_id": evaluation_id,
                        "policy_id": created.payload.get("policy_id"),
                        "investigation_id": investigation_id,
                        "investigation_status": status,
                        "failure_type": failure_type,
                        "recovered": True,
                    },
                )
                if (
                    status not in {"pending", "running"}
                    or retries_exhausted
                ):
                    self._record_monitoring_event(terminal)
            if recovered >= limit:
                return recovered
        return recovered

    def _monitoring_trigger_in_cooldown(
        self, schedule_id: str, policy_id: str, now, cooldown_seconds: int,
        *, exclude_evaluation_id: str,
    ) -> bool:
        if cooldown_seconds <= 0:
            return False
        threshold = now - timedelta(seconds=cooldown_seconds)
        cursor = None
        while True:
            page = self.monitoring_service.event_page(
                schedule_id, limit=500, cursor=cursor
            )
            if any(
                event.event_type == "trigger_matched"
                and event.payload.get("policy_id") == policy_id
                and event.payload.get("evaluation_id") != exclude_evaluation_id
                and event.occurred_at >= threshold
                for event in page.events
            ):
                return True
            if (
                not page.has_more or page.next_cursor is None or not page.events
                or page.events[0].occurred_at < threshold
            ):
                return False
            cursor = page.next_cursor

    def _record_monitoring_event(self, event: MonitoringEvent) -> bool:
        """Append once and index the canonical persisted event representation."""
        inserted = self.monitoring_service.record_event(event)
        persisted = self.monitoring_service.get_event(event.event_id)
        if persisted is not None:
            self._index_monitoring_event(persisted)
        return inserted

    def _index_monitoring_run(self, run: MonitoringRun) -> None:
        source_ids = [monitoring_schedule_revision_identity(
            run.schedule_id, run.schedule_revision
        )]
        if run.investigation_id:
            source_ids.append(f"investigation:{run.investigation_id}")
            snapshot_id = self._latest_investigation_snapshot_id(run.investigation_id)
            if snapshot_id is not None:
                source_ids.append(snapshot_id)
        self._index_memory_artifact(
            artifact_id=monitoring_run_identity(run),
            artifact_type="monitoring_run",
            payload=run,
            mission_id=run.mission_id,
            investigation_id=run.investigation_id,
            source_artifact_ids=tuple(source_ids),
            observed_at=run.finished_at.isoformat() if run.finished_at else None,
        )

    def _index_monitoring_events(
        self, schedule_id: str, run_id: str | None = None
    ) -> None:
        for event in self.monitoring_service.events(
            schedule_id, limit=1000, run_id=run_id
        ):
            self._index_monitoring_event(event)

    def _index_monitoring_event(self, event: MonitoringEvent) -> None:
        source_ids = [event.run_id] if event.run_id else []
        investigation_id = event.payload.get("investigation_id")
        if isinstance(investigation_id, str):
            source_ids.append(f"investigation:{investigation_id}")
        comparison_sha = event.payload.get("comparison_sha256")
        diagnostic_id = event.payload.get("diagnostic_id")
        if isinstance(comparison_sha, str):
            source_ids.extend((
                f"monitoring-comparison:{comparison_sha}",
                f"investigation-comparison:{comparison_sha}",
            ))
            if isinstance(diagnostic_id, str):
                source_ids.append(
                    f"investigation-comparison-temporal-difference:"
                    f"{comparison_sha}:{diagnostic_id}"
                )
        observation_ids = event.payload.get("source_observation_ids", ())
        if isinstance(observation_ids, (tuple, list)):
            source_ids.extend(self._observation_memory_ids(observation_ids))
        revision = event.payload.get("revision")
        if revision is not None:
            source_ids.append(
                monitoring_schedule_revision_identity(event.schedule_id, int(revision))
            )
        self._index_memory_artifact(
            artifact_id=f"monitor-event:{event.event_id}",
            artifact_type="monitoring_event",
            payload=event,
            mission_id=self.monitoring_service.get(event.schedule_id).mission_id,
            source_artifact_ids=tuple(source_ids),
            observed_at=event.occurred_at.isoformat(),
        )
        notification_id = f"monitor-notification:{event.event_id}"
        try:
            notification = self.monitoring_service.get_notification(notification_id)
        except KeyError:
            return
        self._index_monitoring_notification(notification)

    def _index_monitoring_notification(
        self, notification: MonitoringNotification
    ) -> None:
        artifact_id = f"{notification.notification_id}:status:{notification.status}"
        source_ids = [notification.event_id, notification.run_id]
        if notification.status == "acknowledged":
            source_ids.append(
                f"monitor-event:notification-ack:{notification.notification_id}"
            )
        self._index_memory_artifact(
            artifact_id=artifact_id,
            artifact_type="monitoring_notification",
            payload=notification,
            mission_id=self.monitoring_service.get(
                notification.schedule_id
            ).mission_id,
            source_artifact_ids=tuple(source_ids),
            observed_at=notification.created_at.isoformat(),
            metadata={"status": notification.status, "severity": notification.severity},
        )

    def _index_monitoring_schedule(self, schedule: MonitoringSchedule) -> None:
        source_ids = [f"mission:{schedule.mission_id}"]
        if schedule.revision > 1:
            source_ids.append(
                monitoring_schedule_identity(
                    schedule.model_copy(update={"revision": schedule.revision - 1})
                )
            )
        self._index_memory_artifact(
            artifact_id=monitoring_schedule_identity(schedule),
            artifact_type="monitoring_schedule",
            payload=monitoring_schedule_definition(schedule),
            mission_id=schedule.mission_id,
            source_artifact_ids=tuple(source_ids),
            observed_at=schedule.updated_at.isoformat(),
            metadata={"schedule_id": schedule.schedule_id, "revision": schedule.revision},
        )

    def temporal_differences_for_investigation(self, investigation_id: str):
        """Return retained descriptive temporal comparisons for one investigation."""
        investigation = self.investigation_service.get(investigation_id)
        differences = {}
        for execution_id in investigation.result_ids:
            result = self.get_execution_result(execution_id)
            for task_result in result.tasks:
                output = task_result.output
                if isinstance(output, dict):
                    records = output.get("temporal_differences", ())
                else:
                    records = getattr(output, "temporal_differences", ())
                for item in records:
                    diagnostic = (
                        item if isinstance(item, TemporalDifferenceDiagnostic)
                        else TemporalDifferenceDiagnostic.model_validate(item)
                    )
                    differences[diagnostic.diagnostic_id] = diagnostic
        return tuple(differences[key] for key in sorted(differences))

    def observation_stacks_for_investigation(self, investigation_id: str):
        """Return exact-support temporal groupings retained for an investigation."""
        investigation = self.investigation_service.get(investigation_id)
        stacks = {}
        for execution_id in investigation.result_ids:
            result = self.get_execution_result(execution_id)
            for task_result in result.tasks:
                output = task_result.output
                records = (
                    output.get("observation_stacks", ())
                    if isinstance(output, dict)
                    else getattr(output, "observation_stacks", ())
                )
                for item in records:
                    stack = item if isinstance(item, ObservationStack) else ObservationStack.model_validate(item)
                    stacks[stack.stack_id] = stack
        return tuple(stacks[key] for key in sorted(stacks))

    def _observation_memory_ids(
        self,
        observation_ids: Iterable[str],
        source_records: Iterable[dict] = (),
        *,
        investigation_id: str | None = None,
    ) -> tuple[str, ...]:
        wanted = set(observation_ids)
        candidates: dict[str, list] = {}
        for item in self.earth_memory.all():
            observation_id = item.metadata.get("observation_id")
            if item.artifact_type == "observation" and observation_id in wanted:
                candidates.setdefault(observation_id, []).append(item)
        known = {}
        for observation_id, items in candidates.items():
            matching = [
                item for item in items
                if investigation_id is not None
                and item.investigation_id == investigation_id
            ]
            selected = sorted(matching or items, key=lambda item: item.artifact_id)[0]
            known[observation_id] = selected.artifact_id
        for record in source_records:
            try:
                observation = Observation.model_validate(record)
            except (TypeError, ValueError):
                continue
            if observation.observation_id in wanted and observation.observation_id not in known:
                digest = canonical_digest(observation.model_dump(mode="json"))
                known[observation.observation_id] = (
                    f"observation:{observation.observation_id}:{digest[:16]}"
                )
        return tuple(sorted(known.values()))

    def assess_method_evidence(self, method_id: str, version: str, *, observations, query):
        method = self.scientific_knowledge_library.get(method_id, version)
        if method is None:
            from ..errors import ValidationError
            raise ValidationError("Scientific knowledge method was not found.", context={"method_id": method_id, "version": version})
        executable_keys = tuple((item.method_id, item.version) for item in self.scientific_methods.all())
        certified_keys = tuple(
            key for key in executable_keys
            if self.method_certifications.can_emit_findings(*key)
        )
        # An external study or citation is not a runnable benchmark suite.
        benchmark_status = "unknown"
        sufficiency = EvidenceSufficiencyEngine().assess(
            method, observations, query,
            self.perception_engine.build_capability_matrix(),
            benchmark_suite_status=benchmark_status,
            executable_method_ids=executable_keys,
            certified_method_ids=certified_keys,
        )
        recommendations = AdaptiveInvestigationRefiner().recommend(
            (sufficiency,), (method,), self.perception_engine.build_capability_matrix(),
        )
        return sufficiency, recommendations

    def get_hypothesis_ledger(
        self, investigation_id: str
    ) -> HypothesisLifecycleLedger | None:
        with self._hypothesis_ledgers_lock:
            if investigation_id in self._hypothesis_restore_errors:
                return None
            ledger = self._hypothesis_ledgers.get(investigation_id)
            if ledger is not None:
                return ledger
        restored = HypothesisLifecycleLedger()
        try:
            audit_events = self.audit_trail.events(investigation_id)
            lifecycle_events = tuple(
                item for item in audit_events if item.event_type == "hypothesis_transition"
            )
            if not lifecycle_events:
                has_hypothesis_snapshot = any(
                    item.artifact_type == "hypothesis"
                    and item.investigation_id == investigation_id
                    for item in self.earth_memory.all()
                )
                if has_hypothesis_snapshot:
                    raise ValueError(
                        "hypothesis snapshots exist without replayable lifecycle audit events"
                    )
                return None
            for audit_event in lifecycle_events:
                record_payload = audit_event.payload.get("record")
                event_payload = audit_event.payload.get("event")
                if record_payload is None or event_payload is None:
                    raise ValueError(
                        "hypothesis audit event lacks a replayable record and lifecycle event"
                    )
                record = HypothesisRecord.model_validate(record_payload)
                event = HypothesisLifecycleEvent.model_validate(event_payload)
                if (
                    event.actor != audit_event.actor
                    or audit_event.payload.get("hypothesis_id") != event.hypothesis_id
                    or audit_event.payload.get("version") != event.version
                    or audit_event.payload.get("state") != event.to_status
                    or audit_event.payload.get("rationale") != event.rationale
                ):
                    raise ValueError("hypothesis audit envelope does not match its event")
                restored.restore_event(record, event)
        except ValueError as exc:
            with self._hypothesis_ledgers_lock:
                self._hypothesis_restore_errors[investigation_id] = str(exc)
            return None
        with self._hypothesis_ledgers_lock:
            ledger = self._hypothesis_ledgers.setdefault(investigation_id, restored)
            return ledger

    def hypothesis_restore_error(self, investigation_id: str) -> str | None:
        with self._hypothesis_ledgers_lock:
            return self._hypothesis_restore_errors.get(investigation_id)

    def get_execution_result(self, execution_id: str) -> ExecutionResult:
        from ..errors import ValidationError

        with self._execution_results_lock:
            result = self._execution_results.get(execution_id)
        if result is None:
            artifact = self.earth_memory.get(f"execution:{execution_id}")
            candidates = [artifact] if artifact is not None else []
            candidates.extend(
                item for item in self.earth_memory.all()
                if item.artifact_type == "evidence"
                and item.artifact_id.startswith(f"execution:{execution_id}:")
            )
            restored = [
                self._hydrate_execution_result(
                    _execution_result_from_payload(item.payload)
                )
                for item in candidates if item is not None
            ]
            matching = [item for item in restored if item.plan_id == execution_id]
            if matching:
                result = max(matching, key=lambda item: item.finished_at)
                with self._execution_results_lock:
                    self._execution_results[execution_id] = result
        if result is None:
            raise ValidationError(
                "Execution result was not found.",
                context={"execution_id": execution_id},
            )
        return result

    def execution_results(self) -> tuple[ExecutionResult, ...]:
        with self._execution_results_lock:
            results = dict(self._execution_results)
        for artifact in self.earth_memory.all():
            if artifact.artifact_type == "evidence" and artifact.artifact_id.startswith("execution:"):
                restored = self._hydrate_execution_result(
                    _execution_result_from_payload(artifact.payload)
                )
                existing = results.get(restored.plan_id)
                if existing is None or restored.finished_at > existing.finished_at:
                    results[restored.plan_id] = restored
        with self._execution_results_lock:
            self._execution_results.update(results)
        return tuple(results[key] for key in sorted(results))

    def _hydrate_execution_result(
        self, result: ExecutionResult
    ) -> ExecutionResult:
        """Restore typed successful outputs through their declared journal codecs."""
        checkpoints = self.execution_journal.checkpoints(result.plan_id)
        if not checkpoints:
            return result
        tasks = tuple(
            checkpoints.get(task.task_id, task)
            for task in result.tasks
        )
        return result.model_copy(update={"tasks": tasks})

    def execution_events(
        self, execution_id: str, *, after_sequence: int = 0
    ) -> tuple[dict, ...]:
        """Read durable workflow events for polling or a future streaming adapter."""
        return self.execution_journal.events(
            execution_id, after_sequence=after_sequence
        )

    async def _observe_task(self, context):
        query = EarthQuery.model_validate(context.task.parameters["earth_query"])
        return await self.perception_engine.observe(query)

    def _earth_object_extraction_task(self, context):
        observations: dict[str, Observation] = {}
        for dependency_output in context.dependencies.values():
            raw_observations = (
                dependency_output.get("observations", ())
                if isinstance(dependency_output, dict)
                else getattr(dependency_output, "observations", ())
            )
            for raw_observation in raw_observations:
                observation = (
                    raw_observation
                    if isinstance(raw_observation, Observation)
                    else Observation.model_validate(raw_observation)
                )
                previous = observations.get(observation.observation_id)
                if previous is not None and previous != observation:
                    raise ValueError(
                        "Earth Object extraction received a rebound observation ID"
                    )
                observations[observation.observation_id] = observation
        return self._extract_earth_objects(
            tuple(observations[key] for key in sorted(observations)),
            investigation_id=context.investigation_id,
            query=(
                EarthQuery.model_validate(context.task.parameters["earth_query"])
                if context.task.parameters.get("earth_query")
                else None
            ),
        )

    def compile_investigation_execution_plan(
        self, investigation: Investigation
    ) -> ExecutionPlan:
        """Compile the current investigation using its registered workflow version."""
        if not investigation.tasks:
            raise ValueError("investigation has no executable acquisition tasks")
        plan = (
            self.get_investigation_plan(investigation.investigation_plan_id)
            if investigation.investigation_plan_id else None
        )
        design = (
            self.get_investigation_design(investigation.investigation_design_id)
            if investigation.investigation_design_id else None
        )
        return self.workflow_compilers.compile(
            "satquery.scientific-investigation",
            "1.2.0",
            WorkflowCompilationContext(
                investigation=investigation, plan=plan, design=design
            ),
        )

    async def execute_investigation(
        self, investigation_id: str, *, resume: bool = False
    ) -> ExecutionResult:
        """Run the complete registered investigation workflow and record its lifecycle."""
        service = self.investigation_service
        investigation = service.get(investigation_id)
        if not investigation.tasks:
            raise ValueError("investigation has no executable acquisition tasks")
        execution_plan = self.compile_investigation_execution_plan(investigation)
        if resume and not self.execution_journal.has_execution(execution_plan.plan_id):
            raise ValidationError(
                "No durable execution exists for this investigation to resume.",
                context={"investigation_id": investigation_id},
            )
        cancellation = ExecutionCancellationToken()
        with self._execution_results_lock:
            if investigation_id in self._active_execution_cancellations:
                raise ValidationError(
                    "Investigation execution is already active.",
                    context={"investigation_id": investigation_id},
                )
            self._active_execution_cancellations[investigation_id] = cancellation
        try:
            service.resume_start(investigation_id) if resume else service.start(investigation_id)
            self.index_investigation(service.get(investigation_id))
            result = await self.execution_engine.execute(
                execution_plan, cancellation=cancellation, resume=resume
            )
            self.record_execution_result(result, investigation_id=investigation_id)
            if result.plan_id not in service.get(investigation_id).result_ids:
                service.add_result(investigation_id, result.plan_id)
            succeeded = sum(item.status.value == "succeeded" for item in result.tasks)
            failed = sum(item.status.value == "failed" for item in result.tasks)
            skipped = sum(item.status.value == "skipped" for item in result.tasks)
            report = (
                f"Investigation workflow finished: {succeeded} tasks succeeded, "
                f"{failed} failed, {skipped} skipped. The report records acquired "
                "evidence and bounded scientific evaluation. This is not a scientific "
                "conclusion unless a certified method produced one."
            )
            if result.status == ExecutionStatus.SUCCEEDED:
                service.complete(investigation_id, report)
            elif result.status == ExecutionStatus.PARTIAL:
                service.complete_partial(investigation_id, report)
            elif result.status == ExecutionStatus.CANCELLED:
                service.cancel(investigation_id)
            else:
                service.fail(investigation_id, report)
            self.index_investigation(service.get(investigation_id))
            return result
        except Exception as exc:
            current = service.get(investigation_id)
            if current.status.value == "running":
                service.fail(investigation_id, f"Execution raised {type(exc).__name__}.")
            self.index_investigation(service.get(investigation_id))
            raise
        finally:
            with self._execution_results_lock:
                self._active_execution_cancellations.pop(investigation_id, None)

    def cancel_investigation(self, investigation_id: str) -> dict[str, str]:
        service = self.investigation_service
        investigation = service.get(investigation_id)
        with self._execution_results_lock:
            cancellation = self._active_execution_cancellations.get(investigation_id)
        if cancellation is not None:
            cancellation.cancel()
            return {"investigation_id": investigation_id, "status": "cancellation_requested"}
        if investigation.status.value == "pending":
            service.cancel(investigation_id)
            return {"investigation_id": investigation_id, "status": "cancelled"}
        raise ValidationError(
            "Investigation is not pending or actively executing.",
            context={"investigation_id": investigation_id, "status": investigation.status.value},
        )

    @staticmethod
    def _perception_dependencies(context) -> tuple[PerceptionResult, ...]:
        results = []
        for output in context.dependencies.values():
            if isinstance(output, PerceptionResult):
                results.append(output)
            elif isinstance(output, dict) and "query_fingerprint" in output:
                results.append(PerceptionResult.model_validate(output))
            elif isinstance(output, ObservationSearchResult):
                results.append(PerceptionResult(
                    query_fingerprint=f"search:{context.task.task_id}",
                    observations=output.observations,
                    status="complete",
                ))
        return tuple(results)

    def _assess_task(self, context):
        design = self.get_investigation_design(context.task.parameters["design_id"])
        plan = self.get_investigation_plan(design.plan_id)
        candidate_id = context.task.parameters["candidate_plan_id"]
        candidate = next(
            (item for item in plan.candidate_plans if item.candidate_plan_id == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("selected candidate plan is absent from the stored investigation plan")
        return self.investigation_intelligence.assess(
            design, candidate, self._perception_dependencies(context)
        )

    def _reason_task(self, context):
        design = self.get_investigation_design(context.task.parameters["design_id"])
        assessment = next(
            (item for item in context.dependencies.values()
             if isinstance(item, EvidenceAssessment)),
            None,
        )
        if assessment is None:
            assessment = next(
                (EvidenceAssessment.model_validate(item)
                 for item in context.dependencies.values()
                 if isinstance(item, dict) and "assessment_id" in item),
                None,
            )
        if assessment is None:
            raise ValueError("evidence assessment dependency is unavailable")
        observations_by_id = {
            observation.observation_id: observation
            for result in self._perception_dependencies(context)
            for observation in result.observations
        }
        investigation_id = context.investigation_id
        if investigation_id is None:
            raise ValueError("scientific reasoning requires an investigation identity")
        self._extract_earth_objects(
            tuple(observations_by_id[key] for key in sorted(observations_by_id)),
            investigation_id=investigation_id,
            index_memory=False,
        )
        self.ensure_hypothesis_ledger(
            investigation_id, (item.hypothesis for item in design.hypotheses)
        )
        ledger = self.get_hypothesis_ledger(investigation_id)
        return self.scientific_reasoning.evaluate(ReasoningContext(
            investigation_id=investigation_id,
            observations=tuple(observations_by_id[key] for key in sorted(observations_by_id)),
            earth_objects=tuple(
                item for item in self.earth_objects.current()
                if investigation_id in item.investigation_ids
                or item.investigation_id == investigation_id
            ),
            design=design,
            assessment=assessment,
            hypothesis_graph=ledger.graph() if ledger else None,
            hypothesis_lifecycle_events=ledger.events() if ledger else (),
        ))

    def _ensure_open(self) -> None:
        if self._closed:
            raise ExtensionError("The SatQuery platform runtime is closed.")
