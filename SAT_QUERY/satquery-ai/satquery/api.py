"""FastAPI surface for SatQuery AI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .connector_bootstrap import load_configured_connectors
from .errors import QueryError, SatQueryError
from .orchestrator import SatQueryEngine
from .platform.comparisons import (
    InvestigationComparisonRequest,
    compare_investigations,
)
from .platform.contracts import (
    EarthObjectRelationship,
    EarthQuery,
    Evidence,
    Mission,
    Task,
)
from .platform.earth_memory import EarthMemoryQuery
from .platform.earth_objects import EarthObjectDeclaration
from .platform.reasoning import ReasoningContext
from .platform.reports import build_investigation_report
from .platform.scientific_governance import build_reproducibility_bundle
from .platform.scientific_inference import HypothesisRecord
from .platform.scientific_knowledge import (
    ScientificMethodCapabilityPlanner,
    ScientificWorkflowInstance,
)
from .schemas import (
    CapabilityInfo,
    ErrorResponse,
    HealthResponse,
    Modality,
    QueryRequest,
    QueryResponse,
    ToolName,
    utc_now_iso,
)
from .ui import DASHBOARD_HTML

logger = logging.getLogger("satquery.api")


class EarthInvestigationRequest(BaseModel):
    """Natural-language objective plus optional explicit acquisition criteria.

    The platform preserves the question verbatim. It does not guess spatial or
    temporal scope from prose; an EarthQuery is needed to plan acquisitions.
    """

    question: str = Field(min_length=1)
    earth_query: Optional[EarthQuery] = None
    mission_id: Optional[str] = None
    mission_name: Optional[str] = None


class HypothesisTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    status: Literal[
        "active", "under_review", "superseded", "withdrawn", "closed"
    ]
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class EarthObjectMaterializationRequest(BaseModel):
    declaration: EarthObjectDeclaration
    evidence: tuple[Evidence, ...] = ()


class EarthObjectRelationshipRequest(BaseModel):
    relationship: EarthObjectRelationship


class HypothesisCreateRequest(BaseModel):
    hypothesis_id: str = Field(min_length=1)
    proposition: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    origin: Literal["explicit", "question_derived", "composite"]
    competing_group_id: Optional[str] = None
    parent_hypothesis_ids: tuple[str, ...] = ()
    composition: Optional[Literal["all", "any"]] = None
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ScientificMethodAssessmentRequest(BaseModel):
    method_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    earth_query: EarthQuery


class MethodEvidenceSufficiencyRequest(BaseModel):
    earth_query: EarthQuery


class ScientificWorkflowInstantiateRequest(BaseModel):
    configuration: dict[str, object] = Field(default_factory=dict)


_engine: Optional[SatQueryEngine] = None


def get_engine() -> SatQueryEngine:
    """Process-wide engine singleton.

    Built once so the model registry, and therefore every loaded checkpoint,
    survives across requests.
    """
    global _engine
    if _engine is None:
        _engine = SatQueryEngine(get_settings())
    return _engine


def set_engine(engine: Optional[SatQueryEngine]) -> None:
    """Inject an engine. Used by tests and embedding applications."""
    global _engine
    _engine = engine


def _connector_health_summary(diagnostic) -> dict[str, object]:
    """Return operational metrics without exposing raw provider error text."""
    return {
        "connector_id": diagnostic.connector_id,
        "state": diagnostic.state,
        "health": diagnostic.health,
        "calls": diagnostic.calls,
        "failures": diagnostic.failures,
        "retries": diagnostic.retries,
        "last_success_at": diagnostic.last_success_at,
        "last_failure_at": diagnostic.last_failure_at,
        "last_error_type": diagnostic.last_error_type,
        "last_duration_seconds": diagnostic.last_duration_seconds,
        "average_duration_seconds": diagnostic.average_duration_seconds,
        "availability_ratio": diagnostic.availability_ratio,
        "health_probe_count": diagnostic.health_probe_count,
        "last_health_probe_at": diagnostic.last_health_probe_at,
        "last_health_probe_duration_seconds": (
            diagnostic.last_health_probe_duration_seconds
        ),
    }


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        engine = get_engine()
        load_configured_connectors(engine.platform_runtime)
        await engine.platform_runtime.start()
        try:
            yield
        finally:
            await engine.close()

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        description=(
            "An Earth Intelligence platform for observing Earth through sensing modalities, "
            "datasets, and evidence. Platform APIs expose perception planning and execution, "
            "mission and investigation lifecycles, and developer inspection. Existing image "
            "analysis remains available as one capability.\n\n"
            f"Problem statement {resolved.problem_statement}. Built by {resolved.owner}."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    if resolved.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    # -- Error handling ----------------------------------------------------

    @app.exception_handler(SatQueryError)
    async def satquery_error_handler(
        request: Request, exc: SatQueryError
    ) -> JSONResponse:
        """Every failure explains itself and says what to do next."""
        logger.info("%s on %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=exc.code,
                detail=exc.message,
                remediation=exc.remediation,
                context=exc.context,
            ).model_dump(mode="json"),
        )

    # -- Routes ------------------------------------------------------------

    @app.get("/api/v1/platform/modalities", summary="List Earth sensing modalities")
    async def platform_modalities() -> JSONResponse:
        registry = get_engine().platform_runtime.perception_engine.modality_registry
        return JSONResponse(jsonable_encoder(registry.modalities()))

    @app.get(
        "/api/v1/platform/connectors", summary="Inspect registered data implementations"
    )
    async def platform_connectors() -> JSONResponse:
        manager = get_engine().platform_runtime.connector_manager
        return JSONResponse(jsonable_encoder(manager.manifests()))

    @app.get(
        "/api/v1/platform/connectors/health",
        summary="Read local connector health and acquisition diagnostics",
    )
    async def connector_health() -> JSONResponse:
        manager = get_engine().platform_runtime.connector_manager
        diagnostics = await manager.health_snapshot(active=False)
        return JSONResponse([_connector_health_summary(item) for item in diagnostics])

    @app.post(
        "/api/v1/platform/connectors/{connector_id}/health-check",
        summary="Run an explicit connector health probe",
    )
    async def connector_health_check(connector_id: str) -> JSONResponse:
        manager = get_engine().platform_runtime.connector_manager
        connector = manager.registry.get(connector_id)
        diagnostic = await connector.health_check(active=True)
        return JSONResponse(_connector_health_summary(diagnostic))

    @app.post(
        "/api/v1/platform/connectors/{connector_id}/discover",
        summary="Discover datasets from one registered implementation",
    )
    async def discover_connector(connector_id: str) -> JSONResponse:
        references = await get_engine().platform_runtime.connector_manager.discover(
            connector_id
        )
        return JSONResponse(jsonable_encoder(references))

    @app.get("/api/v1/platform/datasets", summary="List known Earth datasets")
    async def platform_datasets() -> JSONResponse:
        datasets = get_engine().platform_runtime.registries.datasets.list()
        return JSONResponse(jsonable_encoder(datasets))

    @app.get(
        "/api/v1/platform/datasets/search", summary="Search registered dataset metadata"
    )
    async def search_platform_datasets(q: str) -> JSONResponse:
        query = q.strip()
        if not query:
            raise QueryError("Dataset search text must not be empty.")
        datasets = get_engine().platform_runtime.registries.datasets.semantic_search(
            query
        )
        return JSONResponse(jsonable_encoder(datasets))

    @app.get(
        "/api/v1/platform/earth/capabilities",
        summary="Read the registered Earth capability matrix",
    )
    async def earth_capabilities() -> JSONResponse:
        matrix = (
            get_engine().platform_runtime.perception_engine.build_capability_matrix()
        )
        return JSONResponse(jsonable_encoder(matrix))

    @app.get("/api/v1/platform/inspect", summary="Inspect local platform registrations")
    async def platform_inspect() -> JSONResponse:
        runtime = get_engine().platform_runtime
        matrix = runtime.perception_engine.build_capability_matrix()
        return JSONResponse(
            {
                "modalities": [
                    item.modality_id
                    for item in runtime.perception_engine.modality_registry.modalities()
                ],
                "connectors": list(runtime.registries.connectors.names()),
                "datasets": len(runtime.registries.datasets.list()),
                "capability_matrix_revision": matrix.revision,
                "models": list(runtime.registries.models.names()),
                "tools": list(runtime.registries.tools.names()),
                "task_handlers": list(runtime.task_handlers.names()),
                "workflow_compilers": [
                    {"workflow_id": workflow_id, "version": version}
                    for workflow_id, version in runtime.workflow_compilers.versions()
                ],
                "missions": len(runtime.mission_service.list()),
                "scientific_rules": [
                    rule.manifest for rule in runtime.scientific_reasoning.rules.all()
                ],
                "scientific_operators": [
                    {"operator_id": item.operator_id, "version": item.version}
                    for item in runtime.scientific_reasoning.operators.all()
                ],
                "uncertainty_methods": runtime.scientific_reasoning.uncertainty_methods.versions(),
                "runtime_state": "closed" if runtime.is_closed else "open",
            }
        )

    @app.get(
        "/api/v1/platform/execution/workflows",
        summary="Inspect registered workflow compilers and executable task handlers",
    )
    async def execution_workflows() -> JSONResponse:
        runtime = get_engine().platform_runtime
        return JSONResponse({
            "workflow_compilers": [
                {"workflow_id": workflow_id, "version": version}
                for workflow_id, version in runtime.workflow_compilers.versions()
            ],
            "task_handlers": list(runtime.task_handlers.names()),
        })

    @app.get(
        "/api/v1/platform/scientific-methods",
        summary="Inspect registered scientific rules, operators, and uncertainty methods",
    )
    async def scientific_methods() -> JSONResponse:
        runtime = get_engine().platform_runtime
        return JSONResponse(
            jsonable_encoder(
                {
                    "rules": [
                        rule.manifest
                        for rule in runtime.scientific_reasoning.rules.all()
                    ],
                    "operators": [
                        {
                            "operator_id": item.operator_id,
                            "version": item.version,
                        }
                        for item in runtime.scientific_reasoning.operators.all()
                    ],
                    "uncertainty_methods": runtime.scientific_reasoning.uncertainty_methods.versions(),
                    "method_registry_revision": runtime.scientific_methods.revision,
                    "domains": runtime.scientific_methods.domain_catalog(),
                    "methods": runtime.scientific_methods.all(),
                    "certification": [
                        {
                            "method_id": item.method_id,
                            "version": item.version,
                            "state": runtime.method_certifications.state(item.method_id, item.version),
                            "history": runtime.method_certifications.history(item.method_id, item.version),
                            "benchmark_reports": runtime.method_certifications.reports(item.method_id, item.version),
                        }
                        for item in runtime.scientific_methods.all()
                    ],
                    "operator_manifests": runtime.scientific_operator_manifests.all(),
                    "operator_catalog": runtime.scientific_operator_manifests.catalog(),
                    "workflow_templates": runtime.scientific_workflow_templates,
                    "policy": "Platform findings require an executable method version in peer_reviewed or reference_implementation certification state, plus applicable evidence, uncertainty, and capability preconditions. Manifest validation labels alone are insufficient.",
                    "plugins": [
                        {"manifest": item[0], "signature_verification": item[1], "compatibility": item[2]}
                        for item in runtime.scientific_plugins.all()
                    ],
                }
            )
        )

    @app.get(
        "/api/v1/platform/scientific-methods/{method_id}/{version}/governance",
        summary="Inspect method certification history and benchmark reports",
    )
    async def scientific_method_governance(method_id: str, version: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        if runtime.scientific_methods.get(method_id, version) is None:
            return JSONResponse({"error": "scientific method not found"}, status_code=404)
        return JSONResponse(jsonable_encoder({
            "method_id": method_id,
            "version": version,
            "state": runtime.method_certifications.state(method_id, version),
            "history": runtime.method_certifications.history(method_id, version),
            "benchmark_reports": runtime.method_certifications.reports(method_id, version),
        }))

    @app.post(
        "/api/v1/platform/scientific-methods/assess",
        summary="Assess declared method compatibility without executing a method",
    )
    async def assess_scientific_method(
        request: ScientificMethodAssessmentRequest,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        method = runtime.scientific_methods.get(request.method_id, request.version)
        if method is None:
            return JSONResponse(
                {"status": "rejected", "reason": "scientific method is not registered"},
                status_code=404,
            )
        result = ScientificMethodCapabilityPlanner().assess(
            method,
            request.earth_query,
            runtime.perception_engine.build_capability_matrix(),
            registered_uncertainty_methods=runtime.scientific_reasoning.uncertainty_methods.versions(),
            dataset_trust_assertions=runtime.scientific_reasoning.evidence_evaluation.dataset_trust.all(),
        )
        return JSONResponse(jsonable_encoder(result))

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/scientific-methods/{method_id}/{version}/sufficiency",
        summary="Assess observed evidence sufficiency and recommend missing observations",
    )
    async def assess_method_evidence_sufficiency(
        investigation_id: str, method_id: str, version: str,
        request: MethodEvidenceSufficiencyRequest,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        observations = tuple(
            observation
            for result_id in investigation.result_ids
            for task in runtime.get_execution_result(result_id).tasks
            for observation in getattr(task.output, "observations", ())
        )
        try:
            sufficiency, recommendations = runtime.assess_method_evidence(
                method_id, version, observations=observations,
                query=request.earth_query,
            )
        except SatQueryError as exc:
            return JSONResponse(jsonable_encoder({"error": exc.message, "context": exc.context}), status_code=404)
        runtime.audit_trail.append(
            aggregate_id=investigation_id, event_type="evidence_sufficiency",
            actor="satquery.method-readiness", payload={
                "method_id": method_id, "method_version": version,
                "status": sufficiency.status,
                "capability_matrix_revision": sufficiency.capability_matrix_revision,
                "recommendation_ids": [item.recommendation_id for item in recommendations],
            },
        )
        return JSONResponse(jsonable_encoder({"sufficiency": sufficiency, "recommendations": recommendations}))

    @app.get(
        "/api/v1/platform/scientific-workflows",
        summary="List configuration-only scientific investigation templates",
    )
    async def scientific_workflows() -> JSONResponse:
        return JSONResponse(
            jsonable_encoder(get_engine().platform_runtime.scientific_workflow_templates)
        )

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/audit",
        summary="Read the append-only investigation audit chain",
    )
    async def investigation_audit(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        aggregate_ids = [investigation_id]
        if investigation.investigation_plan_id:
            aggregate_ids.append(investigation.investigation_plan_id)
        chains = {
            aggregate_id: {
                "events": runtime.audit_trail.events(aggregate_id),
                "valid": runtime.audit_trail.verify(aggregate_id),
            }
            for aggregate_id in aggregate_ids
        }
        return JSONResponse(jsonable_encoder({
            "investigation_id": investigation_id,
            "chains": chains,
        }))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/reproducibility",
        summary="Export investigation artifacts and integrity hashes",
    )
    async def investigation_reproducibility(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        plan = (
            runtime.get_investigation_plan(investigation.investigation_plan_id)
            if investigation.investigation_plan_id else None
        )
        design = (
            runtime.get_investigation_design(investigation.investigation_design_id)
            if investigation.investigation_design_id else None
        )
        reasoning = runtime.get_scientific_reasoning(investigation_id)
        ledger = runtime.get_hypothesis_ledger(investigation_id)
        executions = tuple(
            runtime.get_execution_result(result_id)
            for result_id in investigation.result_ids
        )
        observations = tuple(
            observation
            for execution in executions
            for task in execution.tasks
            for observation in getattr(task.output, "observations", ())
        )
        capability_revision = plan.capability_matrix_revision if plan else next(
            (
                task.output.plan.capability_matrix_revision
                for execution in executions for task in execution.tasks
                if getattr(task.output, "plan", None) is not None
                and task.output.plan.capability_matrix_revision
            ),
            None,
        )
        dataset_records = {
            (item.connector_id, item.dataset_id, item.version or ""): item.model_dump(mode="json")
            for item in (observation.dataset for observation in observations)
            if item is not None
        }
        rule_versions = (reasoning.reproducibility.get("rule_versions", {}) if reasoning else {})
        methods = tuple(
            method.model_dump(mode="json")
            for (method_id, version) in (
                tuple(key.rsplit("@", 1)) for key in rule_versions
            )
            if (method := runtime.scientific_methods.get(method_id, version)) is not None
        )
        provenance = tuple({
            "observation_id": item.observation_id,
            "source_id": item.source_id,
            "dataset": item.dataset.model_dump(mode="json") if item.dataset else None,
            "provenance": item.provenance,
            "provider_metadata": item.provider_metadata,
            "reproducibility": item.reproducibility,
        } for item in observations)
        plans = tuple(
            item.model_dump(mode="json")
            for item in (plan, design) if item is not None
        )
        event_records = runtime.audit_trail.events(investigation_id)
        if plan is not None:
            event_records = (*event_records, *runtime.audit_trail.events(plan.plan_id))
        bundle = build_reproducibility_bundle(
            investigation_id=investigation_id,
            capability_matrix_revision=capability_revision,
            hypotheses=tuple(
                item.model_dump(mode="json") for item in ledger.graph().hypotheses
            ) if ledger else (),
            plans=plans,
            datasets=tuple(dataset_records[key] for key in sorted(dataset_records)),
            observations=tuple(item.model_dump(mode="json") for item in observations),
            provenance=provenance,
            scientific_methods=methods,
            evidence_graph=design.evidence_graph.model_dump(mode="json") if design else None,
            reasoning_report=reasoning.model_dump(mode="json") if reasoning else None,
            uncertainty_inventory=reasoning.uncertainty_budget.model_dump(mode="json") if reasoning else None,
            execution_trace=tuple(item.model_dump(mode="json") for result in executions for item in result.tasks),
            audit_events=tuple(item.model_dump(mode="json") for item in event_records),
        )
        runtime.index_reproducibility_bundle(bundle)
        return JSONResponse(jsonable_encoder(bundle))

    @app.get(
        "/api/v1/platform/scientific-knowledge/methods",
        summary="List cited Earth-science method records and implementation status",
    )
    async def scientific_knowledge_methods(domain: str | None = None) -> JSONResponse:
        library = get_engine().platform_runtime.scientific_knowledge_library
        records = library.for_domain(domain) if domain else library.all()
        return JSONResponse(jsonable_encoder(records))

    @app.get(
        "/api/v1/platform/scientific-knowledge/domains",
        summary="Inspect domain coverage and distinguish references from executable certified methods",
    )
    async def scientific_knowledge_domains() -> JSONResponse:
        library = get_engine().platform_runtime.scientific_knowledge_library
        return JSONResponse(jsonable_encoder(library.domain_catalog()))

    @app.post(
        "/api/v1/platform/earth-memory/search",
        summary="Search indexed investigation and scientific artifacts deterministically",
    )
    async def earth_memory_search(query: EarthMemoryQuery) -> JSONResponse:
        result = get_engine().platform_runtime.search_earth_memory(query)
        # The canonical search index text duplicates the full payload and is an
        # internal implementation detail; return the artifact payload once.
        public_result = result.model_dump(
            mode="json", exclude={"artifacts": {"__all__": {"search_text"}}}
        )
        return JSONResponse(jsonable_encoder(public_result))

    @app.post(
        "/api/v1/platform/scientific-workflows/{template_id}/instantiate",
        summary="Instantiate investigation structure without methods or conclusions",
    )
    async def instantiate_scientific_workflow(
        template_id: str, request: ScientificWorkflowInstantiateRequest
    ) -> JSONResponse:
        import hashlib
        import json

        templates = get_engine().platform_runtime.scientific_workflow_templates
        template = next((item for item in templates if item.template_id == template_id), None)
        if template is None:
            return JSONResponse({"error": "workflow template not found"}, status_code=404)
        supplied = request.configuration
        unresolved = tuple(
            key for key in template.required_configuration
            if key not in supplied or supplied[key] is None or supplied[key] == ""
        )
        identity = hashlib.sha256(
            json.dumps(
                [template.template_id, template.version, supplied],
                sort_keys=True, separators=(",", ":"), default=str,
            ).encode("utf-8")
        ).hexdigest()
        instance = ScientificWorkflowInstance(
            instance_id=f"workflow-{identity[:24]}",
            template_id=template.template_id,
            template_version=template.version,
            supplied_configuration=supplied,
            unresolved_configuration=unresolved,
        )
        get_engine().platform_runtime.audit_trail.append(
            aggregate_id=instance.instance_id, event_type="workflow_change",
            actor="api.client", payload=instance.model_dump(mode="json"),
        )
        return JSONResponse(jsonable_encoder(instance))

    @app.get(
        "/api/v1/platform/runtime",
        summary="Inspect runtime health, local state, and storage durability",
    )
    async def platform_runtime_health() -> JSONResponse:
        runtime = get_engine().platform_runtime
        diagnostics = await runtime.connector_manager.health_snapshot(active=False)
        return JSONResponse(
            {
                "state": "closed" if runtime.is_closed else "open",
                "connector_count": len(runtime.registries.connectors.names()),
                "dataset_count": len(runtime.registries.datasets.list()),
                "mission_count": len(runtime.mission_service.list()),
                "execution_count": len(runtime.execution_results()),
                "storage": {
                    "earth_memory": {
                        "backend": "sqlite" if runtime.config.storage.earth_memory_path else "in_memory",
                        "durable": runtime.config.storage.earth_memory_path is not None,
                    },
                    "lifecycle": {
                        "backend": "sqlite"
                        if runtime.config.storage.lifecycle_path or runtime.config.storage.earth_memory_path
                        else "in_memory",
                        "durable": (
                            runtime.config.storage.lifecycle_path is not None
                            or runtime.config.storage.earth_memory_path is not None
                        ),
                    },
                },
                "connectors": [_connector_health_summary(item) for item in diagnostics],
            }
        )

    @app.post("/api/v1/platform/earth/plan", summary="Plan perception coverage")
    async def earth_plan(query: EarthQuery) -> JSONResponse:
        plan = get_engine().platform_runtime.perception_engine.plan(query)
        return JSONResponse(jsonable_encoder(plan))

    @app.post(
        "/api/v1/platform/earth/plan/explain",
        summary="Explain coverage selection for an EarthQuery",
    )
    async def explain_earth_plan(query: EarthQuery) -> JSONResponse:
        engine = get_engine().platform_runtime.perception_engine
        plan = engine.plan(query)
        matrix = engine.build_capability_matrix()
        selected = set(plan.implementation_ids)
        entries = [
            item.model_dump(mode="json")
            for item in matrix.entries
            if item.connector_id in selected
        ]
        return JSONResponse(
            jsonable_encoder(
                {
                    "query": query,
                    "plan": plan,
                    "capability_matrix_revision": matrix.revision,
                    "selection_basis": "declared modality, variable, dataset, and query coverage",
                    "selected_implementations": entries,
                    "limitations": [
                        "Coverage is based on registered metadata and does not guarantee upstream availability.",
                        "No acquisition or scientific conclusion is produced by planning.",
                    ],
                }
            )
        )

    @app.post("/api/v1/platform/earth/observe", summary="Acquire Earth observations")
    async def earth_observe(query: EarthQuery) -> JSONResponse:
        result = await get_engine().platform_runtime.perception_engine.observe(query)
        return JSONResponse(jsonable_encoder(result))

    @app.post(
        "/api/v1/platform/planning/investigations",
        summary="Produce a deterministic, evidence-scoped investigation plan",
    )
    async def plan_investigation(
        request: EarthInvestigationRequest,
    ) -> JSONResponse:
        plan = get_engine().platform_runtime.investigation_planner.plan(
            request.question,
            earth_query=request.earth_query,
        )
        get_engine().platform_runtime.record_investigation_plan(plan)
        return JSONResponse(jsonable_encoder(plan))

    @app.post(
        "/api/v1/platform/intelligence/design",
        summary="Design evidence strategies from a deterministic investigation plan",
    )
    async def design_investigation(
        request: EarthInvestigationRequest,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        plan = runtime.investigation_planner.plan(
            request.question,
            earth_query=request.earth_query,
        )
        design = runtime.investigation_intelligence.design(plan)
        runtime.record_investigation_plan(plan)
        runtime.record_investigation_design(design)
        return JSONResponse(jsonable_encoder({"plan": plan, "design": design}))

    @app.get(
        "/api/v1/platform/intelligence/designs/{design_id}",
        summary="Inspect a stored, reproducible investigation design",
    )
    async def get_investigation_design(design_id: str) -> JSONResponse:
        design = get_engine().platform_runtime.get_investigation_design(design_id)
        return JSONResponse(jsonable_encoder(design))

    @app.get(
        "/api/v1/platform/investigation-plans/{plan_id}",
        summary="Retrieve a stored investigation plan and reproducibility manifest",
    )
    async def get_investigation_plan(plan_id: str) -> JSONResponse:
        plan = get_engine().platform_runtime.get_investigation_plan(plan_id)
        return JSONResponse(jsonable_encoder(plan))

    @app.post(
        "/api/v1/platform/investigate",
        summary="Plan an Earth investigation and create its mission lifecycle record",
    )
    async def start_earth_investigation(
        request: EarthInvestigationRequest,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        question = request.question.strip()
        if not question:
            raise QueryError("The investigation question must not be empty.")
        plan = runtime.investigation_planner.plan(
            question,
            earth_query=request.earth_query,
        )
        design = runtime.investigation_intelligence.design(plan)
        runtime.record_investigation_plan(plan)
        runtime.record_investigation_design(design)
        if request.mission_id:
            mission = runtime.mission_service.get(request.mission_id)
        else:
            mission = runtime.mission_service.create(
                Mission(
                    name=(request.mission_name or question[:120]),
                    objective=question,
                    metadata={"entrypoint": "earth-investigate", "question": question},
                )
            )
        tasks = ()
        selected = None
        if (
            plan.status == "ready"
            and design.status == "ready_for_acquisition"
            and plan.selected_candidate_plan_id
        ):
            selected = next(
                item
                for item in plan.candidate_plans
                if item.candidate_plan_id == plan.selected_candidate_plan_id
            )
            selected_strategy = next(
                item
                for item in design.candidate_strategies
                if item.candidate_plan_id == selected.candidate_plan_id
            )
            if selected_strategy.status != "ready_for_acquisition":
                selected = None
        if selected is not None:
            tasks = tuple(
                Task(
                    handler="earth.observe",
                    description=step.description,
                    parameters={
                        "earth_query": step.earth_query.model_dump(mode="json"),
                        "investigation_plan_id": plan.plan_id,
                        "investigation_design_id": design.design_id,
                        "candidate_plan_id": selected.candidate_plan_id,
                        "planner_step_id": step.step_id,
                        "natural_language_objective": question,
                    },
                )
                for step in selected.steps
            )
        investigation = runtime.mission_service.create_investigation(
            mission.mission_id,
            tasks,
            investigation_plan_id=plan.plan_id,
            investigation_design_id=design.design_id,
        )
        runtime.index_investigation(investigation)
        response_state = (
            plan.status if tasks or plan.status != "ready" else design.status
        )
        return JSONResponse(
            jsonable_encoder(
                {
                    "mission": mission,
                    "investigation": investigation,
                    "plan": plan,
                    "design": design,
                    "state": response_state,
                    "design_state": design.status,
                    "next_step": (
                        "Review the plan, then execute the investigation explicitly."
                        if design.status == "ready_for_acquisition"
                        else "Resolve the listed missing information and submit the revised objective or EarthQuery."
                    ),
                }
            ),
            status_code=201,
        )

    @app.post(
        "/api/v1/platform/missions", summary="Create an Earth intelligence mission"
    )
    async def create_mission(mission: Mission) -> JSONResponse:
        created = get_engine().platform_runtime.mission_service.create(mission)
        return JSONResponse(jsonable_encoder(created), status_code=201)

    @app.get("/api/v1/platform/missions", summary="List local missions")
    async def list_missions() -> JSONResponse:
        missions = get_engine().platform_runtime.mission_service.list()
        return JSONResponse(jsonable_encoder(missions))

    @app.get("/api/v1/platform/missions/{mission_id}", summary="Get a mission")
    async def get_mission(mission_id: str) -> JSONResponse:
        mission = get_engine().platform_runtime.mission_service.get(mission_id)
        return JSONResponse(jsonable_encoder(mission))

    @app.post(
        "/api/v1/platform/missions/{mission_id}/investigations",
        summary="Create an investigation for a mission",
    )
    async def create_investigation(
        mission_id: str,
        query: EarthQuery,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.mission_service.create_investigation(
            mission_id,
            (
                Task(
                    handler="earth.observe",
                    description="Acquire observations matching the EarthQuery.",
                    parameters={"earth_query": query.model_dump(mode="json")},
                ),
            ),
        )
        runtime.index_investigation(investigation)
        return JSONResponse(jsonable_encoder(investigation), status_code=201)

    @app.get(
        "/api/v1/platform/missions/{mission_id}/investigations",
        summary="List investigations for a mission",
    )
    async def list_investigations(mission_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        runtime.mission_service.get(mission_id)
        investigations = runtime.investigation_service.list_for_mission(mission_id)
        return JSONResponse(jsonable_encoder(investigations))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}",
        summary="Inspect an investigation",
    )
    async def get_investigation(investigation_id: str) -> JSONResponse:
        investigation = get_engine().platform_runtime.investigation_service.get(
            investigation_id
        )
        return JSONResponse(jsonable_encoder(investigation))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/report",
        summary="Build an evidence-linked investigation report from recorded artifacts",
    )
    async def get_investigation_report(investigation_id: str) -> JSONResponse:
        report = build_investigation_report(
            get_engine().platform_runtime, investigation_id
        )
        return JSONResponse(jsonable_encoder(report))

    @app.post(
        "/api/v1/platform/investigation-comparisons",
        summary="Align explicit canonical measurements across recorded investigations",
    )
    async def create_investigation_comparison(
        request: InvestigationComparisonRequest,
    ) -> JSONResponse:
        comparison = compare_investigations(
            get_engine().platform_runtime, request
        )
        return JSONResponse(jsonable_encoder(comparison))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/intelligence",
        summary="Inspect the investigation design and evidence coverage audit",
    )
    async def get_investigation_intelligence(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        design = (
            runtime.get_investigation_design(investigation.investigation_design_id)
            if investigation.investigation_design_id
            else None
        )
        assessment = runtime.get_evidence_assessment(investigation_id)
        reasoning = runtime.get_scientific_reasoning(investigation_id)
        return JSONResponse(
            jsonable_encoder(
                {"design": design, "assessment": assessment, "reasoning": reasoning}
            )
        )

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/reasoning",
        summary="Inspect deterministic scientific evaluations and unresolved conclusions",
    )
    async def get_investigation_reasoning(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        runtime.investigation_service.get(investigation_id)
        report = runtime.get_scientific_reasoning(investigation_id)
        if report is None:
            return JSONResponse({"status": "not_evaluated", "reasoning": None})
        return JSONResponse(jsonable_encoder(report))

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/reasoning/evaluate",
        summary="Re-evaluate stored investigation evidence with current canonical Earth Objects",
    )
    async def reevaluate_investigation_reasoning(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        if not investigation.investigation_design_id:
            raise QueryError("Investigation has no stored design to evaluate.")
        design = runtime.get_investigation_design(investigation.investigation_design_id)
        assessment = runtime.get_evidence_assessment(investigation_id)
        if assessment is None:
            raise QueryError("Investigation has no evidence assessment to evaluate.")
        observations = []
        for result_id in investigation.result_ids:
            result = runtime.get_execution_result(result_id)
            for task_result in result.tasks:
                observations.extend(getattr(task_result.output, "observations", ()))
        ledger = runtime.get_hypothesis_ledger(investigation_id)
        report = runtime.scientific_reasoning.evaluate(ReasoningContext(
            investigation_id=investigation_id,
            observations=tuple(observations),
            earth_objects=tuple(
                item for item in runtime.earth_objects.all()
                if investigation_id in item.investigation_ids or item.investigation_id == investigation_id
            ),
            design=design,
            assessment=assessment,
            hypothesis_graph=ledger.graph() if ledger else None,
            hypothesis_lifecycle_events=ledger.events() if ledger else (),
        ))
        runtime.record_scientific_reasoning(investigation_id, report)
        return JSONResponse(jsonable_encoder(report))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/hypotheses",
        summary="Inspect versioned hypothesis lifecycle and event history",
    )
    async def get_investigation_hypotheses(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        runtime.investigation_service.get(investigation_id)
        ledger = runtime.get_hypothesis_ledger(investigation_id)
        if ledger is None:
            return JSONResponse({"status": "not_initialized", "graph": None, "events": []})
        return JSONResponse(
            jsonable_encoder({"status": "available", "graph": ledger.graph(), "events": ledger.events()})
        )

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/hypotheses",
        summary="Register an explicit hypothesis in the investigation lifecycle",
    )
    async def add_investigation_hypothesis(
        investigation_id: str,
        request: HypothesisCreateRequest,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        if investigation.investigation_design_id is None:
            return JSONResponse({"error": "investigation_design_not_found"}, status_code=409)
        design = runtime.get_investigation_design(investigation.investigation_design_id)
        ledger = runtime.ensure_hypothesis_ledger(
            investigation_id, (item.hypothesis for item in design.hypotheses)
        )
        record = HypothesisRecord(
            hypothesis_id=request.hypothesis_id,
            proposition=request.proposition,
            source_text=request.source_text,
            origin=request.origin,
            competing_group_id=request.competing_group_id,
            parent_hypothesis_ids=request.parent_hypothesis_ids,
            composition=request.composition,
            lifecycle="proposed",
        )
        try:
            ledger.add(record, actor=request.actor, rationale=request.rationale)
        except ValueError as exc:
            return JSONResponse(
                {"error": "hypothesis_registration_rejected", "detail": str(exc)},
                status_code=409,
            )
        runtime.audit_trail.append(
            aggregate_id=investigation_id, event_type="hypothesis_transition",
            actor=request.actor, payload={
                "hypothesis_id": record.hypothesis_id, "version": record.version,
                "state": record.lifecycle, "rationale": request.rationale,
                "event_ids": [item.event_id for item in ledger.events(record.hypothesis_id)],
            },
        )
        runtime.index_hypothesis(
            investigation_id, record, mission_id=investigation.mission_id
        )
        return JSONResponse(
            jsonable_encoder({"hypothesis": record, "events": ledger.events(record.hypothesis_id)}),
            status_code=201,
        )

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/hypotheses/{hypothesis_id}/transitions",
        summary="Append a version-checked hypothesis lifecycle transition",
    )
    async def transition_investigation_hypothesis(
        investigation_id: str,
        hypothesis_id: str,
        request: HypothesisTransitionRequest,
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        runtime.investigation_service.get(investigation_id)
        ledger = runtime.get_hypothesis_ledger(investigation_id)
        if ledger is None:
            return JSONResponse(
                {"error": "hypothesis_lifecycle_not_initialized"}, status_code=409
            )
        try:
            record = ledger.transition(
                hypothesis_id,
                expected_version=request.expected_version,
                status=request.status,
                actor=request.actor,
                rationale=request.rationale,
            )
        except KeyError:
            return JSONResponse({"error": "hypothesis_not_found"}, status_code=404)
        except ValueError as exc:
            return JSONResponse(
                {"error": "invalid_hypothesis_transition", "detail": str(exc)},
                status_code=409,
            )
        runtime.audit_trail.append(
            aggregate_id=investigation_id, event_type="hypothesis_transition",
            actor=request.actor, payload={
                "hypothesis_id": hypothesis_id, "version": record.version,
                "state": record.lifecycle, "rationale": request.rationale,
                "event_ids": [item.event_id for item in ledger.events(hypothesis_id)],
            },
        )
        runtime.index_hypothesis(
            investigation_id, record,
            mission_id=runtime.investigation_service.get(investigation_id).mission_id,
        )
        return JSONResponse(jsonable_encoder({"hypothesis": record, "events": ledger.events(hypothesis_id)}))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/observations",
        summary="Read acquired observations attached to an investigation execution",
    )
    async def investigation_observations(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        observations = []
        for result_id in investigation.result_ids:
            result = runtime.get_execution_result(result_id)
            for task_result in result.tasks:
                output = task_result.output
                if hasattr(output, "observations"):
                    observations.extend(output.observations)
        return JSONResponse(jsonable_encoder(observations))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/temporal-differences",
        summary="Read exact-support descriptive differences between consecutive raster samples",
    )
    async def investigation_temporal_differences(investigation_id: str) -> JSONResponse:
        differences = get_engine().platform_runtime.temporal_differences_for_investigation(
            investigation_id
        )
        return JSONResponse(jsonable_encoder(differences))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/observation-stacks",
        summary="Read exact-support temporal observation groupings for an investigation",
    )
    async def investigation_observation_stacks(investigation_id: str) -> JSONResponse:
        stacks = get_engine().platform_runtime.observation_stacks_for_investigation(
            investigation_id
        )
        return JSONResponse(jsonable_encoder(stacks))

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/earth-objects",
        summary="Materialize an explicitly declared Earth Object from cited investigation evidence",
    )
    async def materialize_investigation_earth_object(
        investigation_id: str, request: EarthObjectMaterializationRequest
    ) -> JSONResponse:
        runtime = get_engine().platform_runtime
        runtime.investigation_service.get(investigation_id)
        if any(item.investigation_id != investigation_id for item in request.evidence):
            raise QueryError("Every supplied evidence record must belong to the requested investigation.")
        observations = []
        investigation = runtime.investigation_service.get(investigation_id)
        for result_id in investigation.result_ids:
            result = runtime.get_execution_result(result_id)
            for task_result in result.tasks:
                observations.extend(getattr(task_result.output, "observations", ()))
        selected = tuple(item for item in observations if item.observation_id in request.declaration.observation_ids)
        if len({item.observation_id for item in selected}) != len(request.declaration.observation_ids):
            raise QueryError("Every declared source observation must exist in the investigation execution.")
        if request.declaration.investigation_id not in {None, investigation_id}:
            raise QueryError("Earth Object declaration investigation_id does not match the route.")
        declaration = request.declaration.model_copy(update={"investigation_id": investigation_id})
        try:
            item = runtime.materialize_earth_object(
                declaration, selected, evidence=request.evidence,
            )
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        return JSONResponse(jsonable_encoder(item))

    @app.get(
        "/api/v1/platform/earth-objects",
        summary="List canonical evidence-backed Earth Object revisions",
    )
    async def list_earth_objects(investigation_id: str | None = None) -> JSONResponse:
        objects = get_engine().platform_runtime.earth_objects.all()
        if investigation_id:
            objects = tuple(item for item in objects if investigation_id in item.investigation_ids or item.investigation_id == investigation_id)
        return JSONResponse(jsonable_encoder(objects))

    @app.get(
        "/api/v1/platform/earth-objects/id/{object_id}",
        summary="Inspect an Earth Object, its assertions, evidence, and provenance",
    )
    async def get_earth_object(object_id: str) -> JSONResponse:
        item = get_engine().platform_runtime.earth_objects.get(object_id)
        if item is None:
            return JSONResponse({"error": "Earth Object not found"}, status_code=404)
        return JSONResponse(jsonable_encoder(item))

    @app.get(
        "/api/v1/platform/earth-objects/graph",
        summary="Read the validated Earth Object relationship graph",
    )
    async def get_earth_object_graph(investigation_id: str | None = None) -> JSONResponse:
        runtime = get_engine().platform_runtime
        selected = tuple(
            item.object_id for item in runtime.earth_objects.all()
            if investigation_id is None or investigation_id in item.investigation_ids or item.investigation_id == investigation_id
        )
        graph = runtime.earth_objects.graph(selected)
        return JSONResponse(jsonable_encoder(graph))

    @app.post(
        "/api/v1/platform/earth-objects/relationships",
        summary="Record an explicitly asserted, evidence-backed Earth Object relationship",
    )
    async def add_earth_object_relationship(request: EarthObjectRelationshipRequest) -> JSONResponse:
        try:
            relationship = get_engine().platform_runtime.add_earth_object_relationship(request.relationship)
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        return JSONResponse(jsonable_encoder(relationship))

    @app.get(
        "/api/v1/platform/investigations/{investigation_id}/provenance",
        summary="Read provenance carried by acquired observations",
    )
    async def investigation_provenance(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        records = []
        for result_id in investigation.result_ids:
            result = runtime.get_execution_result(result_id)
            for task_result in result.tasks:
                output = task_result.output
                for observation in getattr(output, "observations", ()):
                    records.append(
                        {
                            "observation_id": observation.observation_id,
                            "source_id": observation.source_id,
                            "dataset": observation.dataset,
                            "provenance": observation.provenance,
                            "provider_metadata": observation.provider_metadata,
                            "reproducibility": observation.reproducibility,
                        }
                    )
        return JSONResponse(jsonable_encoder(records))

    @app.get(
        "/api/v1/platform/executions/{execution_id}",
        summary="Inspect execution status, task outputs, and trace identifier",
    )
    async def get_execution(execution_id: str) -> JSONResponse:
        result = get_engine().platform_runtime.get_execution_result(execution_id)
        return JSONResponse(jsonable_encoder(result))

    @app.get(
        "/api/v1/platform/executions/{execution_id}/events",
        summary="Poll the append-only execution event journal",
    )
    async def get_execution_events(
        execution_id: str, after_sequence: int = 0
    ) -> JSONResponse:
        if after_sequence < 0:
            raise QueryError("after_sequence must be zero or greater.")
        events = get_engine().platform_runtime.execution_events(
            execution_id, after_sequence=after_sequence
        )
        return JSONResponse(jsonable_encoder({
            "execution_id": execution_id,
            "events": events,
            "next_sequence": events[-1]["sequence"] if events else after_sequence,
        }))

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/execute",
        summary="Execute registered investigation task handlers",
    )
    async def execute_investigation(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        investigation = runtime.investigation_service.get(investigation_id)
        if not investigation.tasks:
            plan = (
                runtime.get_investigation_plan(investigation.investigation_plan_id)
                if investigation.investigation_plan_id else None
            )
            raise QueryError(
                "The investigation plan is not executable.",
                remediation=(
                    [item.question for item in plan.missing_information]
                    if plan and plan.missing_information
                    else ["Revise the observation target or scope, then create a new plan."]
                ),
            )
        try:
            result = await runtime.execute_investigation(investigation_id)
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        return JSONResponse(jsonable_encoder(result))

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/resume",
        summary="Resume an interrupted workflow from compatible successful task checkpoints",
    )
    async def resume_investigation(investigation_id: str) -> JSONResponse:
        runtime = get_engine().platform_runtime
        try:
            result = await runtime.execute_investigation(investigation_id, resume=True)
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        return JSONResponse(jsonable_encoder(result))

    @app.post(
        "/api/v1/platform/investigations/{investigation_id}/cancel",
        summary="Request cooperative cancellation of an investigation",
    )
    async def cancel_investigation(investigation_id: str) -> JSONResponse:
        result = get_engine().platform_runtime.cancel_investigation(investigation_id)
        status_code = 202 if result["status"] == "cancellation_requested" else 200
        return JSONResponse(result, status_code=status_code)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(content=DASHBOARD_HTML)

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        summary="Readiness and setup state",
    )
    async def health() -> HealthResponse:
        engine = get_engine()
        report = engine.health()
        return HealthResponse(
            status=report["status"],
            app=resolved.app_name,
            version=resolved.app_version,
            owner=resolved.owner,
            problem_statement=resolved.problem_statement,
            timestamp_utc=utc_now_iso(),
            device=report["device"],
            backends=report["backends"],
            dependencies=report["dependencies"],
            ready=report["ready"],
            setup_actions=report["setup_actions"],
        )

    @app.get(
        "/api/v1/capabilities",
        response_model=List[CapabilityInfo],
        summary="What SatQuery can do right now",
    )
    async def capabilities() -> List[CapabilityInfo]:
        return get_engine().capabilities()

    @app.get("/api/v1/config", summary="Effective configuration, with secrets redacted")
    async def config() -> JSONResponse:
        return JSONResponse(resolved.describe())

    @app.post("/api/v1/warmup", summary="Load models now instead of on first query")
    async def warmup() -> JSONResponse:
        return JSONResponse(get_engine().warmup())

    @app.post(
        "/api/v1/query",
        response_model=QueryResponse,
        summary="Ask a question about uploaded imagery",
    )
    async def query_multipart(
        query: str = Form(
            ..., description="Natural-language question about the image."
        ),
        files: List[UploadFile] = File(
            default=[], description="One image, or two for change detection."
        ),
        image_paths: Optional[str] = Form(
            None,
            description="Comma-separated server-side paths, as an alternative to uploads.",
        ),
        modality_hint: Optional[str] = Form(
            None, description="OPTICAL or SAR. Overrides the pixel heuristic."
        ),
        force_tool: Optional[str] = Form(
            None, description="Pin a capability and bypass routing."
        ),
        include_trace: bool = Form(True),
    ) -> QueryResponse:
        engine = get_engine()

        uploads = []
        for upload in files or []:
            if not upload or not upload.filename:
                continue
            payload = await upload.read()
            await upload.close()
            uploads.append((upload.filename, payload))

        paths = [
            piece.strip()
            for piece in (image_paths or "").replace(";", ",").split(",")
            if piece.strip()
        ]

        return await engine.answer_on_platform(
            query,
            uploads=uploads,
            image_paths=paths,
            modality_hint=_parse_modality(modality_hint),
            force_tool=_parse_tool(force_tool),
            include_trace=include_trace,
        )

    @app.post(
        "/api/v1/query/json",
        response_model=QueryResponse,
        summary="Ask a question about imagery already on the server",
    )
    async def query_json(body: QueryRequest) -> QueryResponse:
        engine = get_engine()
        if not body.image_paths:
            raise QueryError(
                "The JSON endpoint needs image_paths; it has no upload channel.",
                remediation=[
                    "Use POST /api/v1/query with multipart form data to upload files.",
                    "Or list server-side paths in image_paths.",
                ],
            )
        return await engine.answer_on_platform(
            body.query,
            image_paths=body.image_paths,
            modality_hint=body.modality_hint,
            force_tool=body.force_tool,
            include_trace=body.include_trace,
        )

    @app.post(
        "/api/v1/query/location",
        response_model=QueryResponse,
        summary="Fetch satellite imagery for a location, then analyze it",
    )
    async def query_location(
        query: str = Form(
            ..., description="Question about the fetched satellite image."
        ),
        place: Optional[str] = Form(None, description="Place name or address."),
        latitude: Optional[float] = Form(
            None, description="Latitude in decimal degrees."
        ),
        longitude: Optional[float] = Form(
            None, description="Longitude in decimal degrees."
        ),
        zoom: Optional[int] = Form(None, description="Satellite imagery zoom level."),
        modality_hint: Optional[str] = Form(None, description="OPTICAL or SAR."),
        force_tool: Optional[str] = Form(None, description="Pin a capability."),
        include_trace: bool = Form(True),
    ) -> QueryResponse:
        """Optional no-upload flow: fetch one image, then use normal orchestration."""
        place = place.strip() or None if place is not None else None
        try:
            from connectors.image_fetcher.satellite_fetcher import fetch_satellite_image
        except ImportError as exc:
            raise QueryError(
                "The optional image-fetcher plugin is not installed.",
                remediation=[
                    "Run this endpoint from the canonical satquery-ai directory.",
                    "Install the local package with: python -m pip install -e .",
                ],
            ) from exc

        try:
            image_path = fetch_satellite_image(
                place=place,
                latitude=latitude,
                longitude=longitude,
                zoom=zoom,
            )
        except Exception as exc:
            message = getattr(exc, "message", str(exc))
            remediation = list(getattr(exc, "remediation", []))
            raise QueryError(
                f"Could not fetch satellite imagery: {message}",
                remediation=remediation
                or ["Try a more specific place or pass coordinates."],
            ) from exc

        return await get_engine().answer_on_platform(
            query,
            image_paths=[str(image_path)],
            modality_hint=_parse_modality(modality_hint),
            force_tool=_parse_tool(force_tool),
            include_trace=include_trace,
        )

    return app


def _parse_modality(raw: Optional[str]) -> Optional[Modality]:
    if not raw or not raw.strip():
        return None
    try:
        return Modality(raw.strip().upper())
    except ValueError as exc:
        raise QueryError(
            f"modality_hint must be OPTICAL or SAR, got {raw!r}.",
            remediation=[
                "Leave it blank to let SatQuery infer modality from the pixels."
            ],
        ) from exc


def _parse_tool(raw: Optional[str]) -> Optional[ToolName]:
    if not raw or not raw.strip():
        return None
    try:
        return ToolName(raw.strip().lower())
    except ValueError as exc:
        valid = ", ".join(item.value for item in ToolName)
        raise QueryError(
            f"force_tool must be one of: {valid}. Got {raw!r}.",
            remediation=["Leave it blank to let the router choose."],
        ) from exc


app = create_app()
