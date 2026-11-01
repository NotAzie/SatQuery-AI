"""Versioned compilation of investigation intent into executable task DAGs."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Protocol

from ..errors import ExtensionError
from .contracts import ExecutionPlan, Investigation, Task
from .intelligence import InvestigationDesign
from .planning import InvestigationPlan


@dataclass(frozen=True)
class WorkflowCompilationContext:
    investigation: Investigation
    plan: InvestigationPlan | None = None
    design: InvestigationDesign | None = None


class WorkflowCompiler(Protocol):
    workflow_id: str
    version: str

    def compile(self, context: WorkflowCompilationContext) -> ExecutionPlan: ...


class WorkflowCompilerRegistry:
    """Explicit versioned compiler registry; compilation never imports plugins."""

    def __init__(self) -> None:
        self._compilers: dict[tuple[str, str], WorkflowCompiler] = {}
        self._lock = threading.RLock()

    def register(self, compiler: WorkflowCompiler) -> None:
        key = (compiler.workflow_id.strip(), compiler.version.strip())
        if not all(key):
            raise ExtensionError("Workflow compilers require an id and version.")
        with self._lock:
            if key in self._compilers:
                raise ExtensionError(
                    f"Workflow compiler {key[0]}@{key[1]} is already registered."
                )
            self._compilers[key] = compiler

    def get(self, workflow_id: str, version: str) -> WorkflowCompiler:
        with self._lock:
            compiler = self._compilers.get((workflow_id, version))
        if compiler is None:
            raise ExtensionError(
                f"Workflow compiler {workflow_id}@{version} is not registered.",
                context={"workflow_id": workflow_id, "version": version},
            )
        return compiler

    def compile(
        self,
        workflow_id: str,
        version: str,
        context: WorkflowCompilationContext,
    ) -> ExecutionPlan:
        plan = self.get(workflow_id, version).compile(context)
        if plan.investigation_id != context.investigation.investigation_id:
            raise ExtensionError("Workflow compiler returned a plan for another investigation.")
        return plan

    def versions(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(sorted(self._compilers))


class ScientificInvestigationWorkflowCompiler:
    """Compile acquisition and evidence evaluation as one dependency graph."""

    workflow_id = "satquery.scientific-investigation"
    version = "1.2.0"

    def compile(self, context: WorkflowCompilationContext) -> ExecutionPlan:
        investigation = context.investigation
        tasks = list(investigation.tasks)
        acquisition_ids = tuple(
            task.task_id for task in investigation.tasks
            if task.handler == "earth.observe"
        )
        extraction_id = f"{investigation.investigation_id}:earth-object-extraction"
        if acquisition_ids:
            acquisition_query = next(
                (
                    task.parameters["earth_query"]
                    for task in investigation.tasks
                    if task.task_id in acquisition_ids
                    and isinstance(task.parameters.get("earth_query"), dict)
                ),
                None,
            )
            tasks.append(
                Task(
                    task_id=extraction_id,
                    handler="earth.objects.extract",
                    description=(
                        "Reconcile explicit object candidates, polygonize requested categorical "
                        "raster components, and materialize evidence-linked canonical revisions."
                    ),
                    depends_on=acquisition_ids,
                    accept_partial_dependencies=True,
                    parameters={
                        "pipeline_id": "satquery.earth-object-candidate-extraction",
                        "pipeline_version": "1.1.0",
                        "materializer_id": "satquery.earth-object-materializer",
                        "materializer_version": "1.0.0",
                        "earth_query": acquisition_query,
                    },
                )
            )
        plan, design = context.plan, context.design
        if acquisition_ids and plan is not None and design is not None:
            candidate = next(
                (item for item in plan.candidate_plans
                 if item.candidate_plan_id == plan.selected_candidate_plan_id),
                None,
            )
            strategy = next(
                (item for item in design.candidate_strategies
                 if candidate and item.candidate_plan_id == candidate.candidate_plan_id),
                None,
            )
            if candidate is not None and strategy is not None:
                assessment_id = f"{investigation.investigation_id}:evidence-assessment"
                reasoning_id = f"{investigation.investigation_id}:scientific-reasoning"
                tasks.extend((
                    Task(
                        task_id=assessment_id,
                        handler="earth.assess",
                        description="Assess declared evidence coverage from acquired observations.",
                        depends_on=acquisition_ids,
                        accept_partial_dependencies=True,
                        parameters={
                            "design_id": design.design_id,
                            "candidate_plan_id": candidate.candidate_plan_id,
                        },
                    ),
                    Task(
                        task_id=reasoning_id,
                        handler="earth.reason",
                        description="Evaluate registered scientific operators and methods against the evidence assessment.",
                        depends_on=(*acquisition_ids, extraction_id, assessment_id),
                        accept_partial_dependencies=True,
                        parameters={
                            "design_id": design.design_id,
                            "candidate_plan_id": candidate.candidate_plan_id,
                        },
                    ),
                ))
        compiled = ExecutionPlan(
            mission_id=investigation.mission_id,
            investigation_id=investigation.investigation_id,
            tasks=tuple(tasks),
            metadata={
                "workflow_id": self.workflow_id,
                "workflow_version": self.version,
                "investigation_plan_id": investigation.investigation_plan_id,
                "investigation_design_id": investigation.investigation_design_id,
            },
        )
        identity = compiled.model_dump(mode="json")
        identity.pop("plan_id", None)
        fingerprint = hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()[:32]
        return compiled.model_copy(update={
            "plan_id": f"exec-{investigation.investigation_id}-{fingerprint}"
        })
