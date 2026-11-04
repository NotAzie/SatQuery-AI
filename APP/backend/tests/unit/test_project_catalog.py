from datetime import UTC, datetime

import pytest

from earth_platform.api.v1.projects import list_project_investigations
from earth_platform.engine.models import EngineAgentSession
from earth_platform.projects.models import ProjectSessionLink
from earth_platform.sessions.models import Session
from earth_platform.shared.clock import utcnow


class ProjectPage:
    def __init__(self, links: list[ProjectSessionLink]) -> None:
        self.links = links
        self.requested_page: tuple[int, int] | None = None

    async def list_sessions(
        self, project_id: str, *, limit: int, offset: int
    ) -> list[ProjectSessionLink]:
        self.requested_page = (limit, offset)
        return self.links


class EngineTranscripts:
    def __init__(self) -> None:
        self.session_ids: list[str] = []

    async def get_engine_session(self, session_id: str) -> EngineAgentSession:
        self.session_ids.append(session_id)
        now = datetime.now(UTC)
        return EngineAgentSession(
            session_id=f"engine-{session_id}",
            created_at=now,
            updated_at=now,
            investigation_ids=["investigation-z", "investigation-a", "investigation-a"],
        )


@pytest.mark.asyncio
async def test_project_catalog_uses_only_engine_linked_sessions_and_sorts_ids():
    links = [
        ProjectSessionLink(
            project_id="project-1",
            session_id="session-linked",
            linked_at=utcnow(),
            session=Session(
                id="session-linked",
                engine_agent_session_id="engine-session-linked",
            ),
        ),
        ProjectSessionLink(
            project_id="project-1",
            session_id="session-empty",
            linked_at=utcnow(),
            session=Session(id="session-empty"),
        ),
    ]
    projects = ProjectPage(links)
    runtime = EngineTranscripts()

    results = await list_project_investigations("project-1", projects, runtime, 25, 50)

    assert projects.requested_page == (25, 50)
    assert runtime.session_ids == ["session-linked"]
    assert [(item.session_id, item.investigation_id) for item in results] == [
        ("session-linked", "investigation-a"),
        ("session-linked", "investigation-z"),
    ]
