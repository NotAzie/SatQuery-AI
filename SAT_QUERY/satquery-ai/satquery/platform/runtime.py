"""Dependency-injected composition root for local SatQuery platform services."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable

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
    TaskExecution,
    TemporalDifferenceDiagnostic,
)
from .earth_memory import (
    EarthMemoryQuery,
    EarthMemoryRepository,
    artifact_from_payload,
)
from .earth_objects import (
    EarthObjectCatalog,
    EarthObjectDeclaration,
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
    InMemoryAuditTrail,
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
    HypothesisLifecycleLedger,
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


def _memory_object_revision(artifact) -> int:
    try:
        return int(artifact.metadata.get("revision", 1))
    except (TypeError, ValueError):
        return 0


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
        self.audit_trail = InMemoryAuditTrail()
        self.earth_objects = EarthObjectCatalog()
        self.earth_object_materializer = EarthObjectMaterializer()
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
        self.workflow_compilers = WorkflowCompilerRegistry()
        self.workflow_compilers.register(ScientificInvestigationWorkflowCompiler())
        self.register_task_handler("earth.observe", self._observe_task)
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
        if self.scientific_methods.get(*key) is not None:
            raise ValueError(f"scientific method already registered: {key[0]}@{key[1]}")
        if any(
            item.manifest.rule_id == key[0] and item.manifest.version == key[1]
            for item in self.scientific_reasoning.rules.all()
        ):
            raise ValueError(f"scientific rule already registered: {key[0]}@{key[1]}")
        self.scientific_reasoning.rules.register(rule)
        self.scientific_methods.register(manifest)
        event = self.method_certifications.register(manifest.method_id, manifest.version)
        self._index_memory_artifact(
            artifact_id=f"method:{manifest.method_id}@{manifest.version}",
            artifact_type="scientific_method", payload=manifest,
            method_id=manifest.method_id, method_version=manifest.version,
        )
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
            payload={"report_id": report.report_id, "report_sha256": report.report_sha256,
                     "status": report.status, "suite_id": report.suite_id,
                     "suite_version": report.suite_version},
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
            observations = getattr(output, "observations", ())
            observation_artifacts: dict[str, str] = {}
            for observation in observations:
                observation_digest = canonical_digest(observation.model_dump(mode="json"))
                observation_artifact_id = (
                    f"observation:{observation.observation_id}:{observation_digest[:16]}"
                )
                observation_artifacts[observation.observation_id] = observation_artifact_id
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
                candidate = observation.earth_object_candidate
                if candidate is not None:
                    try:
                        self.materialize_earth_object(
                            EarthObjectDeclaration(
                                identity_namespace=candidate.identity_namespace,
                                identity_value=candidate.identity_value,
                                object_type=candidate.object_type,
                                declared_by=candidate.declared_by,
                                investigation_id=investigation_id,
                                observation_ids=(observation.observation_id,),
                                declared_provenance={
                                    **candidate.provenance,
                                    "mapping_id": candidate.mapping_id,
                                },
                            ),
                            (observation,),
                        )
                    except ValueError as exc:
                        self.audit_trail.append(
                            aggregate_id=observation.observation_id,
                            event_type="earth_object_candidate_rejected",
                            actor=candidate.declared_by,
                            payload={
                                "candidate": candidate.model_dump(mode="json"),
                                "reason": str(exc),
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
            source_artifact_ids=self._observation_memory_ids(assessment.observation_ids),
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
            source_artifact_ids=self._observation_memory_ids(report.observation_ids),
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
                source_artifact_ids=self._observation_memory_ids(evaluation.observation_ids),
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
        with self._hypothesis_ledgers_lock:
            ledger = self._hypothesis_ledgers.get(investigation_id)
            if ledger is not None:
                return ledger
            ledger = HypothesisLifecycleLedger()
            graph = hypothesis_graph_from_candidates(candidates)
            for record in graph.hypotheses:
                proposed = record.model_copy(update={"lifecycle": "proposed"})
                ledger.add(
                    proposed,
                    actor="satquery.investigation-design",
                    rationale="Hypothesis preserved from the investigation design.",
                )
                ledger.transition(
                    proposed.hypothesis_id,
                    expected_version=1,
                    status="active",
                    actor="satquery.investigation-design",
                    rationale="Hypothesis entered the active evaluation lifecycle.",
                )
            self._hypothesis_ledgers[investigation_id] = ledger
            return ledger

    def index_investigation(self, investigation) -> None:
        """Index a lifecycle snapshot and retain explicit mission relationship."""
        self._index_memory_artifact(
            artifact_id=f"investigation:{investigation.investigation_id}",
            artifact_type="investigation", payload=investigation,
            investigation_id=investigation.investigation_id,
            mission_id=investigation.mission_id,
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
        self._index_memory_artifact(
            artifact_id=f"reproducibility:{bundle.investigation_id}:{bundle.bundle_sha256}",
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
    ):
        """Materialize and index an explicitly declared, evidence-backed object."""
        identity = f"{declaration.identity_namespace}:{declaration.identity_value}"
        previous = next(
            (item for item in sorted(self.earth_objects.all(), key=lambda value: value.revision, reverse=True)
             if item.stable_identity == identity),
            None,
        )
        item = self.earth_object_materializer.materialize(
            declaration, observations, evidence=evidence, previous=previous,
        )
        self.earth_objects.put(item)
        investigation_ids = {record.investigation_id for record in evidence if record.evidence_id in declaration.evidence_ids}
        investigation_id = next(iter(investigation_ids)) if len(investigation_ids) == 1 else None
        source_artifacts = tuple(sorted(set(
            self._observation_memory_ids(item.source_observation_ids)
            + tuple(f"evidence:{evidence_id}" for evidence_id in item.evidence_ids)
        )))
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
            source_artifact_ids=source_artifacts,
            metadata={"stable_identity": identity, "object_type": item.object_type,
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
        return item

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

    def _observation_memory_ids(self, observation_ids: Iterable[str]) -> tuple[str, ...]:
        wanted = set(observation_ids)
        return tuple(sorted(
            item.artifact_id for item in self.earth_memory.all()
            if item.artifact_type == "observation"
            and item.metadata.get("observation_id") in wanted
        ))

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
            return self._hypothesis_ledgers.get(investigation_id)

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
            "1.0.0",
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
            return result
        except Exception as exc:
            current = service.get(investigation_id)
            if current.status.value == "running":
                service.fail(investigation_id, f"Execution raised {type(exc).__name__}.")
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
        self.ensure_hypothesis_ledger(
            investigation_id, (item.hypothesis for item in design.hypotheses)
        )
        ledger = self.get_hypothesis_ledger(investigation_id)
        return self.scientific_reasoning.evaluate(ReasoningContext(
            investigation_id=investigation_id,
            observations=tuple(observations_by_id[key] for key in sorted(observations_by_id)),
            earth_objects=tuple(
                item for item in self.earth_objects.all()
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
