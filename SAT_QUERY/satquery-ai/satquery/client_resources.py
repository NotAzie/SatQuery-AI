"""Route-complete, grouped access to the versioned SatQuery platform API.

These resources are intentionally transport-only. They return decoded server
contracts unchanged so the SDK does not silently reinterpret scientific data.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import SatQueryClient


class _Resource:
    def __init__(self, client: SatQueryClient) -> None:
        self._client = client

    def _id(self, value: str) -> str:
        return self._client._path_segment(value)

    def _get(self, path: str, **params: Any) -> Any:
        return self._client.get(path, params=_nonempty(params))

    def _post(self, path: str, payload: Any = None, **params: Any) -> Any:
        body = self._client._json_value(payload) if _is_contract(payload) else payload
        return self._client.post(path, payload=body, params=_nonempty(params))

    def _patch(self, path: str, payload: Any, **params: Any) -> Any:
        body = self._client._json_value(payload) if _is_contract(payload) else payload
        return self._client.patch(path, payload=body, params=_nonempty(params))


class PlatformResource(_Resource):
    """Runtime, capability, connector, dataset, and platform inspection."""

    def modalities(self) -> Any:
        return self._get("/api/v1/platform/modalities")

    def connectors(self) -> Any:
        return self._get("/api/v1/platform/connectors")

    def connector_health(self) -> Any:
        return self._get("/api/v1/platform/connectors/health")

    def probe_connector(self, connector_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/connectors/{self._id(connector_id)}/health-check"
        )

    def discover_connector(self, connector_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/connectors/{self._id(connector_id)}/discover"
        )

    def datasets(self) -> Any:
        return self._get("/api/v1/platform/datasets")

    def search_datasets(self, query: str) -> Any:
        return self._get("/api/v1/platform/datasets/search", q=_required(query))

    def capability_matrix(self) -> Any:
        return self._get("/api/v1/platform/earth/capabilities")

    def inspect(self) -> Any:
        return self._get("/api/v1/platform/inspect")

    def execution_workflows(self) -> Any:
        return self._get("/api/v1/platform/execution/workflows")

    def runtime_health(self) -> Any:
        return self._get("/api/v1/platform/runtime")

    def scientific_methods(self) -> Any:
        return self._get("/api/v1/platform/scientific-methods")

    def method_governance(self, method_id: str, version: str) -> Any:
        return self._get(
            f"/api/v1/platform/scientific-methods/{self._id(method_id)}/{self._id(version)}/governance"
        )

    def assess_method(self, request: Any) -> Any:
        return self._post("/api/v1/platform/scientific-methods/assess", request)

    def health(self) -> Any:
        return self._get("/api/v1/health")

    def config(self) -> Any:
        return self._get("/api/v1/config")

    def warmup(self) -> Any:
        return self._post("/api/v1/warmup")


class EarthResource(_Resource):
    """Canonical EarthQuery planning and acquisition endpoints."""

    def plan(self, query: Any, *, explain: bool = False) -> Any:
        return self._post(
            "/api/v1/platform/earth/plan/explain"
            if explain
            else "/api/v1/platform/earth/plan",
            query,
        )

    def observe(self, query: Any) -> Any:
        return self._post("/api/v1/platform/earth/observe", query)


class MissionsResource(_Resource):
    """Mission and mission-scoped investigation lifecycle calls."""

    def create(self, mission: Any) -> Any:
        return self._post("/api/v1/platform/missions", mission)

    def list(self) -> Any:
        return self._get("/api/v1/platform/missions")

    def get(self, mission_id: str) -> Any:
        return self._get(f"/api/v1/platform/missions/{self._id(mission_id)}")

    def create_investigation(self, mission_id: str, earth_query: Any) -> Any:
        return self._post(
            f"/api/v1/platform/missions/{self._id(mission_id)}/investigations",
            earth_query,
        )

    def investigations(self, mission_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/missions/{self._id(mission_id)}/investigations"
        )


class InvestigationsResource(_Resource):
    """Planning, execution, evidence, reasoning, and record inspection."""

    def start(
        self,
        question: str,
        *,
        earth_query: Any = None,
        mission_name: str | None = None,
        mission_id: str | None = None,
    ) -> Any:
        query = (
            self._client._json_value(earth_query)
            if earth_query is not None and _is_contract(earth_query)
            else earth_query
        )
        return self._post(
            "/api/v1/platform/investigate",
            {
                "question": _required(question),
                "earth_query": query,
                "mission_name": mission_name,
                "mission_id": mission_id,
            },
        )

    def plan(self, request: Any) -> Any:
        return self._post("/api/v1/platform/planning/investigations", request)

    def begin(self, request: Any) -> Any:
        """Create a mission, plan, and investigation without acquiring data."""
        return self._post("/api/v1/platform/investigate", request)

    def design(self, request: Any) -> Any:
        return self._post("/api/v1/platform/intelligence/design", request)

    def get_plan(self, plan_id: str) -> Any:
        return self._get(f"/api/v1/platform/investigation-plans/{self._id(plan_id)}")

    def get_design(self, design_id: str) -> Any:
        return self._get(f"/api/v1/platform/intelligence/designs/{self._id(design_id)}")

    def get(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}"
        )

    def report(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/report"
        )

    def intelligence(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/intelligence"
        )

    def reasoning(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/reasoning"
        )

    def reevaluate_reasoning(self, investigation_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/reasoning/evaluate"
        )

    def hypotheses(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/hypotheses"
        )

    def add_hypothesis(self, investigation_id: str, request: Any) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/hypotheses",
            request,
        )

    def transition_hypothesis(
        self, investigation_id: str, hypothesis_id: str, request: Any
    ) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/hypotheses/{self._id(hypothesis_id)}/transitions",
            request,
        )

    def audit(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/audit"
        )

    def reproducibility(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/reproducibility"
        )

    def observations(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/observations"
        )

    def observation_stacks(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/observation-stacks"
        )

    def temporal_differences(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/temporal-differences"
        )

    def provenance(self, investigation_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/provenance"
        )

    def execution(self, execution_id: str) -> Any:
        return self._get(f"/api/v1/platform/executions/{self._id(execution_id)}")

    def execution_events(self, execution_id: str, *, after_sequence: int = 0) -> Any:
        return self._get(
            f"/api/v1/platform/executions/{self._id(execution_id)}/events",
            after_sequence=after_sequence,
        )

    def execute(self, investigation_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/execute"
        )

    def resume(self, investigation_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/resume"
        )

    def cancel(self, investigation_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/cancel"
        )

    def compare(self, investigation_ids: tuple[str, ...] | list[str]) -> Any:
        payload = {"investigation_ids": list(investigation_ids)}
        return self._post("/api/v1/platform/investigation-comparisons", payload)

    def method_sufficiency(
        self, investigation_id: str, method_id: str, version: str, request: Any
    ) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/scientific-methods/{self._id(method_id)}/{self._id(version)}/sufficiency",
            request,
        )


class MonitoringResource(_Resource):
    """Recurring schedule lifecycle, history, notifications, and dispatch."""

    def create(self, schedule: Any) -> Any:
        return self._post("/api/v1/platform/monitoring/schedules", schedule)

    def schedules(self, *, mission_id: str | None = None) -> Any:
        return self._get("/api/v1/platform/monitoring/schedules", mission_id=mission_id)

    def revise(self, schedule_id: str, update: Any) -> Any:
        return self._patch(
            f"/api/v1/platform/monitoring/schedules/{self._id(schedule_id)}", update
        )

    def enable(self, schedule_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/monitoring/schedules/{self._id(schedule_id)}/enable"
        )

    def disable(self, schedule_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/monitoring/schedules/{self._id(schedule_id)}/disable"
        )

    def runs(self, schedule_id: str) -> Any:
        return self._get(
            f"/api/v1/platform/monitoring/schedules/{self._id(schedule_id)}/runs"
        )

    def comparison(self, schedule_id: str, *, limit: int = 10) -> Any:
        return self._get(
            f"/api/v1/platform/monitoring/schedules/{self._id(schedule_id)}/comparison",
            limit=limit,
        )

    def triggers(
        self, schedule_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> Any:
        return self._get(
            f"/api/v1/platform/monitoring/schedules/{self._id(schedule_id)}/triggers",
            limit=limit,
            cursor=cursor,
        )

    def health(self) -> Any:
        return self._get("/api/v1/platform/monitoring/health")

    def events(
        self,
        *,
        schedule_id: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> Any:
        return self._get(
            "/api/v1/platform/monitoring/events",
            schedule_id=schedule_id,
            run_id=run_id,
            limit=limit,
        )

    def event_page(
        self,
        *,
        schedule_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Any:
        return self._get(
            "/api/v1/platform/monitoring/events/page",
            schedule_id=schedule_id,
            run_id=run_id,
            limit=limit,
            cursor=cursor,
        )

    def notifications(
        self,
        *,
        schedule_id: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> Any:
        return self._get(
            "/api/v1/platform/monitoring/notifications",
            schedule_id=schedule_id,
            unread_only=unread_only,
            limit=limit,
        )

    def acknowledge(self, notification_id: str) -> Any:
        return self._post(
            f"/api/v1/platform/monitoring/notifications/{self._id(notification_id)}/acknowledge"
        )

    def run_due(self, *, limit: int = 100) -> Any:
        return self._post("/api/v1/platform/monitoring/run-due", limit=limit)


class EarthObjectsResource(_Resource):
    """Canonical object materialization, revision, and relationship records."""

    def list(self, *, investigation_id: str | None = None) -> Any:
        return self._get(
            "/api/v1/platform/earth-objects", investigation_id=investigation_id
        )

    def get(self, object_id: str) -> Any:
        return self._get(f"/api/v1/platform/earth-objects/id/{self._id(object_id)}")

    def graph(self, *, investigation_id: str | None = None) -> Any:
        return self._get(
            "/api/v1/platform/earth-objects/graph", investigation_id=investigation_id
        )

    def materialize(self, investigation_id: str, declaration: Any) -> Any:
        return self._post(
            f"/api/v1/platform/investigations/{self._id(investigation_id)}/earth-objects",
            declaration,
        )

    def transition(self, object_id: str, request: Any) -> Any:
        return self._post(
            f"/api/v1/platform/earth-objects/id/{self._id(object_id)}/transitions",
            request,
        )

    def add_relationship(self, request: Any) -> Any:
        return self._post("/api/v1/platform/earth-objects/relationships", request)


class EarthMemoryResource(_Resource):
    def search(self, query: Any) -> Any:
        return self._post("/api/v1/platform/earth-memory/search", query)


class ScientificResource(_Resource):
    def methods(self, *, domain: str | None = None) -> Any:
        return self._get("/api/v1/platform/scientific-knowledge/methods", domain=domain)

    def domains(self) -> Any:
        return self._get("/api/v1/platform/scientific-knowledge/domains")

    def workflows(self) -> Any:
        return self._get("/api/v1/platform/scientific-workflows")

    def instantiate_workflow(
        self, template_id: str, configuration: Mapping[str, Any]
    ) -> Any:
        return self._post(
            f"/api/v1/platform/scientific-workflows/{self._id(template_id)}/instantiate",
            {"configuration": dict(configuration)},
        )


def _is_contract(value: Any) -> bool:
    return callable(getattr(value, "model_dump", None))


def _required(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must not be empty")
    return value


def _nonempty(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
