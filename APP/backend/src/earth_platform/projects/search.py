from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from earth_platform.projects.models import (
    ProjectEarthView,
    ProjectInvestigationCollection,
    ProjectInvestigationComparison,
    ProjectInvestigationRelationship,
    ProjectInvestigationTemplate,
    ProjectNote,
    ProjectSearchHit,
    ProjectSearchKind,
    ProjectSearchResponse,
    ProjectSessionLink,
)
from earth_platform.projects.repository import ProjectRepository

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_PAGE_SIZE = 500
_SUMMARY_LENGTH = 280
_T = TypeVar("_T")
_Candidate = tuple[
    ProjectSearchKind,
    str,
    str,
    str,
    datetime,
    str | None,
    str | None,
]


class ProjectSearch:
    """Deterministic lexical search over saved Platform Project records."""

    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects

    async def search(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> ProjectSearchResponse:
        project = await self._projects.get(project_id)
        terms = set(_TOKEN.findall(query.casefold()))
        candidates: list[_Candidate] = []
        candidates.append(
            (
                "project",
                project.id,
                project.title,
                f"{project.title} {project.description or ''}",
                project.updated_at,
                None,
                None,
            )
        )

        for session in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_sessions(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._session_candidate(session))
        for note in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_notes(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._note_candidate(note))
        for view in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_views(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._view_candidate(view))
        for comparison in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_investigation_comparisons(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._comparison_candidate(comparison))
        for relationship in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_investigation_relationships(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._relationship_candidate(relationship))
        for collection in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_investigation_collections(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._collection_candidate(collection))
        for template in await self._list_all(
            lambda page_limit, page_offset: self._projects.list_investigation_templates(
                project_id, limit=page_limit, offset=page_offset
            )
        ):
            candidates.append(self._template_candidate(template))

        results = []
        for kind, record_id, title, content, created_at, session_id, investigation_id in candidates:
            hit = self._rank(
                kind,
                record_id,
                title,
                content,
                created_at,
                session_id,
                investigation_id,
                terms,
            )
            if hit is not None:
                results.append(hit)
        results.sort(
            key=lambda hit: (
                -hit.score,
                -hit.created_at.timestamp(),
                hit.kind,
                hit.id,
            )
        )
        return ProjectSearchResponse(
            project_id=project_id,
            query=query,
            results=results[offset : offset + limit],
            total_count=len(results),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    async def _list_all(
        fetch_page: Callable[[int, int], Awaitable[list[_T]]],
    ) -> list[_T]:
        records: list[_T] = []
        offset = 0
        while True:
            page = await fetch_page(_PAGE_SIZE, offset)
            records.extend(page)
            if len(page) < _PAGE_SIZE:
                return records
            offset += len(page)

    @staticmethod
    def _session_candidate(link: ProjectSessionLink) -> _Candidate:
        session = link.session
        title = session.title or "Untitled session"
        context_parts: list[str] = []
        if session.context.focus_region:
            context_parts.append(session.context.focus_region.model_dump_json())
        if session.context.focus_time:
            context_parts.append(session.context.focus_time.model_dump_json())
        context_parts.extend(session.context.active_investigation_ids)
        context_parts.extend(session.context.pinned_evidence_ids)
        context_parts.extend(bookmark.name for bookmark in session.earth_workspace.bookmarks)
        return (
            "session",
            session.id,
            title,
            " ".join((title, *context_parts)),
            session.updated_at,
            session.id,
            None,
        )

    @staticmethod
    def _note_candidate(note: ProjectNote) -> _Candidate:
        return (
            "note",
            note.id,
            note.title,
            f"{note.title} {note.body}",
            note.updated_at,
            note.investigation_session_id,
            note.investigation_id,
        )

    @staticmethod
    def _view_candidate(view: ProjectEarthView) -> _Candidate:
        context = view.context
        searchable_context = [
            f"{context.camera.position.lng} {context.camera.position.lat}",
            *context.selected_evidence_ids,
            *(bookmark.name for bookmark in context.bookmarks),
            *(drawing.name for drawing in context.drawings),
            *(layer.layer_id for layer in context.layers),
            *(image.asset_id for image in context.imagery),
        ]
        if context.time:
            searchable_context.extend(
                [context.time.start.isoformat(), context.time.end.isoformat()]
            )
        if context.instant:
            searchable_context.append(context.instant.isoformat())
        content_parts = [view.title]
        if context.time:
            content_parts.append(
                f"Time range {context.time.start.isoformat()} to {context.time.end.isoformat()}"
            )
        if context.instant:
            content_parts.append(f"Time {context.instant.isoformat()}")
        if context.bookmarks:
            content_parts.append(
                "Bookmarks: " + ", ".join(bookmark.name for bookmark in context.bookmarks)
            )
        if context.drawings:
            content_parts.append(
                "Drawings: " + ", ".join(drawing.name for drawing in context.drawings)
            )
        if context.selected_evidence_ids:
            content_parts.append(
                "Selected evidence: " + ", ".join(context.selected_evidence_ids)
            )
        if context.layers:
            content_parts.append(
                "Layers: " + ", ".join(layer.layer_id for layer in context.layers)
            )
        if context.imagery:
            content_parts.append(
                "Images: " + ", ".join(image.asset_id for image in context.imagery)
            )
        if context.measurement:
            measurement = context.measurement
            measurement_text = (
                f"Measurement: {measurement.kind} {measurement.value} {measurement.unit}"
            )
            content_parts.append(measurement_text)
            searchable_context.append(measurement_text)
        return (
            "earth_view",
            view.id,
            view.title,
            " ".join((*content_parts, *searchable_context)),
            view.created_at,
            view.source_session_id,
            view.investigation_id,
        )

    @staticmethod
    def _comparison_candidate(comparison: ProjectInvestigationComparison) -> _Candidate:
        return (
            "comparison",
            comparison.id,
            comparison.title,
            " ".join(
                (
                    comparison.title,
                    comparison.left.investigation_id,
                    comparison.left.session_id,
                    comparison.right.investigation_id,
                    comparison.right.session_id,
                )
            ),
            comparison.created_at,
            None,
            None,
        )

    @staticmethod
    def _relationship_candidate(
        relationship: ProjectInvestigationRelationship,
    ) -> _Candidate:
        title = relationship.relationship_type.replace("_", " ")
        from_ref = relationship.from_investigation
        to_ref = relationship.to_investigation
        return (
            "relationship",
            relationship.id,
            title,
            " ".join(
                (
                    title,
                    from_ref.investigation_id,
                    from_ref.session_id,
                    to_ref.investigation_id,
                    to_ref.session_id,
                    relationship.rationale,
                )
            ),
            relationship.created_at,
            None,
            None,
        )

    @staticmethod
    def _template_candidate(template: ProjectInvestigationTemplate) -> _Candidate:
        return (
            "investigation_template",
            template.id,
            template.title,
            " ".join(
                (
                    template.title,
                    template.description,
                    *(step.title for step in template.steps),
                )
            ),
            template.updated_at,
            None,
            None,
        )

    @staticmethod
    def _collection_candidate(collection: ProjectInvestigationCollection) -> _Candidate:
        return (
            "investigation_collection",
            collection.id,
            collection.title,
            " ".join(
                [
                    collection.title,
                    collection.description,
                    *(
                        reference.investigation_id
                        for reference in collection.investigations
                    ),
                ]
            ),
            collection.updated_at,
            None,
            None,
        )

    @staticmethod
    def _rank(
        kind: ProjectSearchKind,
        record_id: str,
        title: str,
        content: str,
        created_at: datetime,
        session_id: str | None,
        investigation_id: str | None,
        query_terms: set[str],
    ) -> ProjectSearchHit | None:
        title_terms = set(_TOKEN.findall(title.casefold()))
        content_terms = set(_TOKEN.findall(content.casefold()))
        matched_title = query_terms & title_terms
        matched_content = query_terms & content_terms
        matched = matched_title | matched_content
        if not matched or not query_terms:
            return None
        score = (2 * len(matched_title) + len(matched_content)) / (
            3 * len(query_terms)
        )
        return ProjectSearchHit(
            kind=kind,
            id=record_id,
            title=title,
            summary=_excerpt(content, matched),
            score=score,
            matched_terms=sorted(matched),
            matched_fields=[
                field
                for field, hits in (("title", matched_title), ("content", matched_content))
                if hits
            ],
            created_at=created_at,
            session_id=session_id,
            investigation_id=investigation_id,
        )


def _excerpt(content: str, terms: set[str]) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= _SUMMARY_LENGTH:
        return normalized
    lowered = normalized.casefold()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, min(positions, default=0) - 80)
    end = min(len(normalized), start + _SUMMARY_LENGTH)
    excerpt = normalized[start:end]
    if start:
        excerpt = f"…{excerpt}"
    if end < len(normalized):
        excerpt = f"{excerpt}…"
    return excerpt
