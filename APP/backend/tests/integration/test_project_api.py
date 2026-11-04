import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from earth_platform.api.deps import get_agent_runtime, get_engine
from earth_platform.engine.models import (
    EngineAgentSession,
    EngineHypothesisCreateRequest,
    EngineHypothesisLifecycleResponse,
    EngineHypothesisMutationResponse,
    EngineHypothesisRecord,
    EngineHypothesisTransitionRequest,
    EngineInvestigationComparison,
    EngineInvestigationComparisonRequest,
    EngineMonitoringSchedule,
)
from earth_platform.main import create_app
from earth_platform.settings import Settings
from earth_platform.settings.models import SessionSettings
from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import (
    CameraState,
    EarthBookmark,
    EarthContext,
    EarthImageryRef,
    EarthMeasurement,
    EarthWorkspaceState,
)
from earth_platform.shared.errors import NotFoundError
from earth_platform.shared.geo import LngLat


class MonitoringEngineStub:
    def __init__(self) -> None:
        timestamp = utcnow()
        self._schedules = [
            EngineMonitoringSchedule.model_construct(
                schedule_id="schedule-1",
                mission_id="mission-1",
                name="Daily shoreline check",
                earth_query={},
                interval_seconds=86400,
                rolling_window_seconds=None,
                priority=0,
                overlap_policy="skip_while_running",
                enabled=True,
                next_run_at=timestamp,
                created_at=timestamp,
                updated_at=timestamp,
                revision=1,
            )
        ]

    async def list_monitoring_schedules(self) -> list[EngineMonitoringSchedule]:
        return self._schedules


class InvestigationRuntimeStub:
    def __init__(self, investigation_ids_by_session: dict[str, list[str]] | None = None) -> None:
        self.requested_sessions: list[str] = []
        self.investigation_ids_by_session = investigation_ids_by_session or {}
        self.hypothesis_calls: list[tuple[str, str, str]] = []

    async def get_engine_session(self, session_id: str) -> EngineAgentSession:
        self.requested_sessions.append(session_id)
        now = datetime.now(UTC)
        return EngineAgentSession(
            session_id="engine-session-1",
            created_at=now,
            updated_at=now,
            investigation_ids=self.investigation_ids_by_session.get(
                session_id, ["investigation-1"]
            ),
        )

    async def _require_hypothesis_investigation(
        self, session_id: str, investigation_id: str
    ) -> None:
        transcript = await self.get_engine_session(session_id)
        if investigation_id not in transcript.investigation_ids:
            raise NotFoundError(f"Investigation '{investigation_id}' is not linked to this session")

    async def get_investigation_hypotheses(
        self, session_id: str, investigation_id: str
    ) -> EngineHypothesisLifecycleResponse:
        await self._require_hypothesis_investigation(session_id, investigation_id)
        self.hypothesis_calls.append(("get", session_id, investigation_id))
        return EngineHypothesisLifecycleResponse(
            status="not_initialized",
            graph=None,
            events=[],
            restoration_error=None,
        )

    async def add_investigation_hypothesis(
        self,
        session_id: str,
        investigation_id: str,
        request: EngineHypothesisCreateRequest,
    ) -> EngineHypothesisMutationResponse:
        await self._require_hypothesis_investigation(session_id, investigation_id)
        self.hypothesis_calls.append(("add", session_id, investigation_id))
        hypothesis = EngineHypothesisRecord(
            hypothesis_id=request.hypothesis_id,
            version=1,
            proposition=request.proposition,
            source_text=request.source_text,
            origin=request.origin,
            lifecycle="proposed",
            competing_group_id=request.competing_group_id,
            parent_hypothesis_ids=request.parent_hypothesis_ids,
            composition=request.composition,
        )
        return EngineHypothesisMutationResponse(hypothesis=hypothesis, events=[])

    async def transition_investigation_hypothesis(
        self,
        session_id: str,
        investigation_id: str,
        hypothesis_id: str,
        request: EngineHypothesisTransitionRequest,
    ) -> EngineHypothesisMutationResponse:
        await self._require_hypothesis_investigation(session_id, investigation_id)
        self.hypothesis_calls.append(("transition", session_id, investigation_id))
        hypothesis = EngineHypothesisRecord(
            hypothesis_id=hypothesis_id,
            version=request.expected_version + 1,
            proposition="Proposition",
            source_text="Researcher source text",
            origin="explicit",
            lifecycle=request.status,
        )
        return EngineHypothesisMutationResponse(hypothesis=hypothesis, events=[])


class InvestigationComparisonEngineStub:
    comparison_sha256 = "d" * 64

    def __init__(self) -> None:
        self.create_requests: list[EngineInvestigationComparisonRequest] = []
        self.read_digests: list[str] = []
        self.comparison = EngineInvestigationComparison(
            comparison_id=f"investigation-comparison:{self.comparison_sha256[:20]}",
            comparison_sha256=self.comparison_sha256,
            schema_version="1.2",
            stack_builder_version="1.1.0",
            temporal_method_id="satquery.temporal.consecutive-difference",
            temporal_method_version="1.0.0",
            investigation_reports=[],
            measurement_groups=[],
            observation_stacks=[],
            temporal_diagnostics=[],
            alignment_issues=[],
            temporal_issues=[],
            observation_identity_conflicts=[],
            unmatched_observation_ids=[],
            limitations=["No scientific conclusions are generated."],
            markdown="# Engine comparison",
        )

    async def create_investigation_comparison(
        self, request: EngineInvestigationComparisonRequest
    ) -> EngineInvestigationComparison:
        self.create_requests.append(request)
        return self.comparison

    async def get_investigation_comparison(
        self, comparison_sha256: str
    ) -> EngineInvestigationComparison:
        self.read_digests.append(comparison_sha256)
        return self.comparison


def test_project_api_creates_sessions_and_links_existing_work(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/projects",
            json={"title": "River flood analysis", "description": "Seasonal review"},
        )
        assert created.status_code == 201
        project = created.json()

        created_session = client.post(
            f"/api/v1/projects/{project['id']}/sessions",
            json={"title": "2025 flood event"},
        )
        assert created_session.status_code == 201
        session_id = created_session.json()["session_id"]
        assert created_session.json()["session"]["title"] == "2025 flood event"
        assert client.get("/api/v1/projects/unlinked-sessions").json() == []
        assert client.get(f"/api/v1/projects/{project['id']}/investigations").json() == []

        standalone = client.post("/api/v1/sessions", json={"title": "Legacy work"})
        standalone_id = standalone.json()["id"]
        linked = client.post(
            f"/api/v1/projects/{project['id']}/sessions/link",
            json={"session_id": standalone_id},
        )
        assert linked.status_code == 200
        assert linked.json()["session_id"] == standalone_id
        assert {
            item["session_id"]
            for item in client.get(f"/api/v1/projects/{project['id']}/sessions").json()
        } == {session_id, standalone_id}

        updated = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"expected_revision": 1, "title": "Flood archive"},
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        stale = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"expected_revision": 1, "title": "Stale edit"},
        )
        assert stale.status_code == 409


def test_project_api_rejects_empty_update_and_archived_session_creation(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    with TestClient(create_app(settings)) as client:
        project = client.post("/api/v1/projects", json={"title": "Archive"}).json()
        empty_update = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"expected_revision": 1},
        )
        assert empty_update.status_code == 422

        archived = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"expected_revision": 1, "archived": True},
        )
        assert archived.status_code == 200
        rejected = client.post(f"/api/v1/projects/{project['id']}/sessions", json={})
        assert rejected.status_code == 409


def test_project_session_listing_is_paginated(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    with TestClient(create_app(settings)) as client:
        project = client.post("/api/v1/projects", json={"title": "Pagination"}).json()
        first = client.post(f"/api/v1/projects/{project['id']}/sessions", json={"title": "First"})
        second = client.post(f"/api/v1/projects/{project['id']}/sessions", json={"title": "Second"})

        assert first.status_code == 201
        assert second.status_code == 201
        page = client.get(f"/api/v1/projects/{project['id']}/sessions?limit=1&offset=1")
        repeated_page = client.get(f"/api/v1/projects/{project['id']}/sessions?limit=1&offset=1")
        first_page = client.get(f"/api/v1/projects/{project['id']}/sessions?limit=1&offset=0")
        assert page.json() == repeated_page.json()
        assert {
            first_page.json()[0]["session_id"],
            page.json()[0]["session_id"],
        } == {first.json()["session_id"], second.json()["session_id"]}


def test_project_investigation_comparison_validates_and_persists_references(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    app = create_app(settings)
    runtime = InvestigationRuntimeStub(
        {"session-left": ["investigation-left"], "session-right": ["investigation-right"]}
    )
    engine = InvestigationComparisonEngineStub()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"title": "Comparison"}).json()
        left_link = client.post(f"/api/v1/projects/{project['id']}/sessions", json={}).json()
        right_link = client.post(f"/api/v1/projects/{project['id']}/sessions", json={}).json()
        left_session_id = left_link["session_id"]
        right_session_id = right_link["session_id"]
        for session_id in (left_session_id, right_session_id):
            asyncio.run(
                app.state.container.sessions.sessions.mutate(
                    session_id,
                    lambda session, engine_session_id=f"engine-{session_id}": setattr(
                        session, "engine_agent_session_id", engine_session_id
                    ),
                )
            )
        runtime.investigation_ids_by_session = {
            left_session_id: ["investigation-left"],
            right_session_id: ["investigation-right"],
        }
        comparisons_url = f"/api/v1/projects/{project['id']}/comparisons"
        request = {
            "title": "Before and after",
            "left": {
                "investigation_id": "investigation-left",
                "session_id": left_session_id,
            },
            "right": {
                "investigation_id": "investigation-right",
                "session_id": right_session_id,
            },
        }
        created = client.post(comparisons_url, json=request)
        assert created.status_code == 201
        comparison = created.json()
        assert comparison["left"] == request["left"]
        assert comparison["right"] == request["right"]
        assert comparison["engine_comparison_id"] == engine.comparison.comparison_id
        assert comparison["engine_comparison_sha256"] == engine.comparison_sha256
        assert engine.create_requests[0].investigation_ids == [
            "investigation-left",
            "investigation-right",
        ]
        assert client.get(comparisons_url).json() == [comparison]
        assert client.get(f"{comparisons_url}/{comparison['id']}").json() == comparison

        engine_result = client.get(
            f"{comparisons_url}/{comparison['id']}/engine-result"
        )
        assert engine_result.status_code == 200
        assert engine_result.json()["markdown"] == "# Engine comparison"
        assert engine.read_digests == [engine.comparison_sha256]

        same_reference = {**request, "right": request["left"]}
        assert client.post(comparisons_url, json=same_reference).status_code == 422
        duplicate_investigation_id = {
            **request,
            "right": {
                "investigation_id": "investigation-left",
                "session_id": right_session_id,
            },
        }
        assert client.post(comparisons_url, json=duplicate_investigation_id).status_code == 422
        invalid_reference = {
            **request,
            "right": {
                "investigation_id": "not-in-transcript",
                "session_id": right_session_id,
            },
        }
        assert client.post(comparisons_url, json=invalid_reference).status_code == 404
        unlinked_session = client.post("/api/v1/sessions", json={}).json()["id"]
        invalid_owner = {
            **request,
            "right": {
                "investigation_id": "investigation-right",
                "session_id": unlinked_session,
            },
        }
        assert client.post(comparisons_url, json=invalid_owner).status_code == 404
        activity = client.get(f"/api/v1/projects/{project['id']}/activity").json()
        assert any(
            item["action"] == "investigation_comparison.created"
            and item["subject_id"] == comparison["id"]
            for item in activity
        )
        assert client.delete(f"{comparisons_url}/{comparison['id']}").status_code == 204
        assert client.get(comparisons_url).json() == []
        assert client.get(f"{comparisons_url}/{comparison['id']}").status_code == 404
        activity = client.get(f"/api/v1/projects/{project['id']}/activity").json()
        assert any(
            item["action"] == "investigation_comparison.deleted"
            and item["subject_id"] == comparison["id"]
            for item in activity
        )


def test_investigation_hypothesis_endpoints_validate_session_ownership(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    app = create_app(settings)
    runtime = InvestigationRuntimeStub()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    with TestClient(app) as client:
        session_id = client.post("/api/v1/sessions", json={}).json()["id"]
        runtime.investigation_ids_by_session = {session_id: ["investigation-1"]}
        asyncio.run(
            app.state.container.sessions.sessions.mutate(
                session_id,
                lambda session: setattr(session, "engine_agent_session_id", "engine-session-1"),
            )
        )
        base_url = f"/api/v1/chat/sessions/{session_id}/investigations/investigation-1/hypotheses"
        lifecycle = client.get(base_url)
        assert lifecycle.status_code == 200
        assert lifecycle.json()["status"] == "not_initialized"

        invalid = client.get(base_url.replace("investigation-1", "missing"))
        assert invalid.status_code == 404

        create = client.post(
            base_url,
            json={
                "hypothesis_id": "hypothesis-1",
                "proposition": "The shoreline moved inland.",
                "source_text": "Researcher's declared proposition",
                "origin": "explicit",
                "actor": "Researcher",
                "rationale": "Record an explicit hypothesis",
            },
        )
        assert create.status_code == 201
        assert create.json()["hypothesis"]["lifecycle"] == "proposed"

        transition = client.post(
            f"{base_url}/hypothesis-1/transitions",
            json={
                "expected_version": 1,
                "status": "active",
                "actor": "Researcher",
                "rationale": "Begin review",
            },
        )
        assert transition.status_code == 200
        assert transition.json()["hypothesis"]["version"] == 2
        assert runtime.hypothesis_calls == [
            ("get", session_id, "investigation-1"),
            ("add", session_id, "investigation-1"),
            ("transition", session_id, "investigation-1"),
        ]


def test_project_note_api_supports_revision_checked_edits_and_delete(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    with TestClient(create_app(settings)) as client:
        project = client.post("/api/v1/projects", json={"title": "Notes"}).json()
        notes_url = f"/api/v1/projects/{project['id']}/notes"
        created = client.post(notes_url, json={"title": "Question", "body": "Compare dates"})
        assert created.status_code == 201
        note = created.json()

        updated = client.patch(
            f"{notes_url}/{note['id']}",
            json={
                "expected_revision": note["revision"],
                "title": "Research question",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        assert updated.json()["title"] == "Research question"

        stale = client.patch(
            f"{notes_url}/{note['id']}",
            json={"expected_revision": note["revision"], "body": "Stale edit"},
        )
        assert stale.status_code == 409
        assert client.get(notes_url).json()[0]["body"] == "Compare dates"

        deleted = client.delete(f"{notes_url}/{note['id']}")
        assert deleted.status_code == 204
        assert client.get(notes_url).json() == []
        assert (
            client.patch(
                f"{notes_url}/{note['id']}",
                json={"expected_revision": 2, "body": "Missing"},
            ).status_code
            == 404
        )
        activity_url = f"/api/v1/projects/{project['id']}/activity"
        activity = client.get(activity_url)
        assert activity.status_code == 200
        assert {item["action"] for item in activity.json()} >= {
            "project.created",
            "note.created",
            "note.updated",
            "note.deleted",
        }
        first_page = client.get(f"{activity_url}?limit=2&offset=0").json()
        second_page = client.get(f"{activity_url}?limit=2&offset=2").json()
        assert len(first_page) == 2
        assert len(second_page) == 2
        assert not {item["id"] for item in first_page}.intersection(
            item["id"] for item in second_page
        )


def test_project_view_api_snapshots_linked_session_bookmarks(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    app = create_app(settings)
    runtime = InvestigationRuntimeStub()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"title": "Earth views"}).json()
        link = client.post(f"/api/v1/projects/{project['id']}/sessions", json={}).json()
        session_id = link["session_id"]
        timestamp = utcnow()
        bookmark = EarthBookmark(
            id="bookmark-shoreline",
            name="Shoreline baseline",
            context=EarthContext(
                camera=CameraState(
                    position=LngLat(lat=10.25, lng=20.5),
                    height_m=1800,
                ),
                imagery=[
                    EarthImageryRef(
                        asset_id="image-1",
                        source="attachment",
                        attached=True,
                    )
                ],
                measurement=EarthMeasurement(
                    kind="distance",
                    value=125,
                    unit="m",
                    position=LngLat(lat=10.25, lng=20.5),
                ),
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )
        workspace = EarthWorkspaceState(bookmarks=[bookmark])
        updated_session = client.patch(
            f"/api/v1/sessions/{session_id}",
            json={"earth_workspace": workspace.model_dump(mode="json")},
        )
        assert updated_session.status_code == 200
        asyncio.run(
            app.state.container.sessions.sessions.mutate(
                session_id,
                lambda session: setattr(session, "engine_agent_session_id", "engine-session-1"),
            )
        )

        views_url = f"/api/v1/projects/{project['id']}/views"
        created = client.post(
            views_url,
            json={
                "title": "Baseline",
                "source_session_id": session_id,
                "source_bookmark_id": bookmark.id,
                "investigation_id": "investigation-1",
            },
        )
        assert created.status_code == 201
        view = created.json()
        assert view["investigation_id"] == "investigation-1"
        assert view["context"]["camera"]["position"] == {"lat": 10.25, "lng": 20.5}
        assert view["context"]["imagery"][0]["asset_id"] == "image-1"
        assert view["context"]["measurement"]["value"] == 125
        unscoped = client.post(
            views_url,
            json={
                "title": "Project baseline",
                "source_session_id": session_id,
                "source_bookmark_id": bookmark.id,
            },
        )
        assert unscoped.status_code == 201
        assert unscoped.json()["investigation_id"] is None
        assert {item["id"] for item in client.get(views_url).json()} == {
            view["id"],
            unscoped.json()["id"],
        }
        assert client.get(
            views_url,
            params={
                "investigation_id": "investigation-1",
                "source_session_id": session_id,
            },
        ).json() == [view]
        assert (
            client.get(views_url, params={"investigation_id": "investigation-1"}).status_code == 422
        )
        invalid_investigation_view = client.post(
            views_url,
            json={
                "title": "Unlinked snapshot",
                "source_session_id": session_id,
                "source_bookmark_id": bookmark.id,
                "investigation_id": "missing",
            },
        )
        assert invalid_investigation_view.status_code == 404
        assert runtime.requested_sessions == [
            session_id,
            session_id,
        ]
        activity = client.get(f"/api/v1/projects/{project['id']}/activity").json()
        assert any(item["action"] == "earth_view.saved" for item in activity)

        assert client.delete(f"{views_url}/{view['id']}").status_code == 204
        assert client.delete(f"{views_url}/{unscoped.json()['id']}").status_code == 204
        assert client.get(views_url).json() == []


def test_project_monitoring_api_links_only_existing_engine_schedules(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    app = create_app(settings)
    app.dependency_overrides[get_engine] = MonitoringEngineStub
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"title": "Monitoring study"}).json()
        links_url = f"/api/v1/projects/{project['id']}/monitoring-links"
        body = {"schedule_id": "schedule-1"}
        linked = client.post(links_url, json=body)
        assert linked.status_code == 201
        assert linked.json()["mission_id"] == "mission-1"
        linked_at = linked.json()["linked_at"]

        repeated = client.post(links_url, json=body)
        assert repeated.status_code == 201
        assert repeated.json()["linked_at"] == linked_at
        assert client.get(links_url).json() == [linked.json()]
        assert client.post(links_url, json={"schedule_id": "missing"}).status_code == 404

        assert client.delete(f"{links_url}/schedule-1").status_code == 204
        assert client.get(links_url).json() == []
        actions = {
            item["action"]
            for item in client.get(f"/api/v1/projects/{project['id']}/activity").json()
        }
        assert {"monitoring.linked", "monitoring.unlinked"} <= actions

        archived = client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"expected_revision": 1, "archived": True},
        )
        assert archived.status_code == 200
        assert client.post(links_url, json=body).status_code == 409


def test_project_investigation_route_requires_project_session_ownership(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    app = create_app(settings)
    runtime = InvestigationRuntimeStub()
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"title": "Investigation workspace"}).json()
        linked_session = client.post(f"/api/v1/projects/{project['id']}/sessions", json={}).json()
        session_id = linked_session["session_id"]
        session_store = app.state.container.sessions.sessions
        awaitable = session_store.mutate(
            session_id,
            lambda session: setattr(session, "engine_agent_session_id", "engine-session-1"),
        )
        asyncio.run(awaitable)

        url = f"/api/v1/projects/{project['id']}/investigations/investigation-1"
        found = client.get(url, params={"session_id": session_id})
        assert found.status_code == 200
        assert found.json() == {
            "investigation_id": "investigation-1",
            "session_id": session_id,
        }
        assert runtime.requested_sessions == [session_id]

        other_project = client.post("/api/v1/projects", json={"title": "Another Project"}).json()
        not_linked = client.get(
            f"/api/v1/projects/{other_project['id']}/investigations/investigation-1",
            params={"session_id": session_id},
        )
        assert not_linked.status_code == 404
        assert runtime.requested_sessions == [session_id]

        missing_investigation = client.get(
            f"/api/v1/projects/{project['id']}/investigations/missing",
            params={"session_id": session_id},
        )
        assert missing_investigation.status_code == 404
        assert runtime.requested_sessions == [session_id, session_id]

        note_url = f"/api/v1/projects/{project['id']}/notes"
        scoped_note = client.post(
            note_url,
            json={
                "title": "Check flood boundary",
                "body": "Compare the report against the north bank.",
                "investigation_id": "investigation-1",
                "investigation_session_id": session_id,
            },
        )
        assert scoped_note.status_code == 201
        assert scoped_note.json()["investigation_id"] == "investigation-1"
        assert scoped_note.json()["investigation_session_id"] == session_id
        assert runtime.requested_sessions == [session_id, session_id, session_id]
        scoped_notes = client.get(
            note_url,
            params={
                "investigation_id": "investigation-1",
                "investigation_session_id": session_id,
            },
        )
        assert [note["id"] for note in scoped_notes.json()] == [scoped_note.json()["id"]]
        assert (
            client.get(note_url, params={"investigation_id": "investigation-1"}).status_code == 422
        )
        assert (
            client.post(
                note_url,
                json={
                    "title": "Wrong investigation",
                    "body": "This ID is not in the transcript.",
                    "investigation_id": "missing",
                    "investigation_session_id": session_id,
                },
            ).status_code
            == 404
        )
