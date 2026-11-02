from collections.abc import Callable

from earth_platform.sessions.models import Session
from earth_platform.shared.earth import (
    EarthBookmarkRef,
    EarthCaptureMetadata,
    EarthContext,
    EarthImageryRef,
    EarthInvestigationState,
    EarthOverlay,
    EarthSplitView,
    EarthTimelinePlayback,
)


class EarthContextBuilder:
    """Builds one serializable workspace snapshot from live and persisted presentation state."""

    def build(
        self,
        session: Session,
        supplied: EarthContext | None,
        engine_investigation_ids: list[str] | None = None,
    ) -> EarthContext | None:
        persisted = session.earth_workspace
        previous = session.earth_context_snapshots[-1] if session.earth_context_snapshots else None
        camera = (
            supplied.camera
            if supplied
            else persisted.camera_history.present or (previous.camera if previous else None)
        )
        if camera is None:
            return None

        source = supplied or previous
        capture_candidates: list[EarthCaptureMetadata] = [
            *persisted.captures,
            *(previous.captures if previous else []),
            *(supplied.captures if supplied else []),
        ]
        captures = self._unique(capture_candidates, key=lambda item: item.id)
        evidence_candidates: list[str] = [
            *session.context.pinned_evidence_ids,
            *(previous.selected_evidence_ids if previous else []),
            *(supplied.selected_evidence_ids if supplied else []),
        ]
        selected_evidence = self._unique(evidence_candidates, key=lambda item: item)
        bookmark_refs = [
            EarthBookmarkRef(
                id=bookmark.id,
                name=bookmark.name,
                camera=bookmark.context.camera,
                time=bookmark.context.time,
                instant=bookmark.context.instant,
            )
            for bookmark in persisted.bookmarks
        ]
        if supplied:
            bookmark_refs = self._merge_bookmarks(bookmark_refs, supplied.bookmarks)
        imagery_candidates: list[EarthImageryRef] = list(source.imagery if source else [])
        imagery_candidates.extend(
            EarthImageryRef(
                asset_id=capture.asset_id,
                source="capture",
                captured_at=capture.captured_at,
                region=capture.region,
                camera=capture.camera,
            )
            for capture in captures
        )
        imagery = self._unique(imagery_candidates, key=lambda item: item.asset_id)
        overlays: list[EarthOverlay] = source.overlays if source else []
        visible_overlays: list[EarthOverlay] = [
            *overlays,
            *(
                source.secondary_view.overlays
                if source and source.split_view.enabled and source.secondary_view
                else []
            ),
        ]
        visible_investigation_ids: list[str] = [
            item.investigation_id
            for item in visible_overlays
            if item.investigation_id is not None
        ]
        investigation_state = EarthInvestigationState(
            known_ids=(
                engine_investigation_ids[-64:]
                if engine_investigation_ids is not None
                else (source.investigations.known_ids if source else [])
            ),
            visible_ids=self._unique(
                visible_investigation_ids,
                key=lambda item: item,
            )[-64:],
        )

        history = (
            supplied.camera_history
            if supplied
            and (
                supplied.camera_history.present is not None
                or supplied.camera_history.past
                or supplied.camera_history.future
            )
            else persisted.camera_history
        )
        return EarthContext(
            camera=camera,
            viewport=source.viewport if source else None,
            layers=source.layers if source else [],
            time=(
                supplied.time
                if supplied
                else (previous.time if previous else session.context.focus_time)
            ),
            instant=(supplied.instant if supplied else previous.instant if previous else None),
            timeline_playback=(
                source.timeline_playback if source else EarthTimelinePlayback()
            ),
            selection=(
                supplied.selection if supplied else previous.selection if previous else None
            ),
            drawings=supplied.drawings if supplied else (previous.drawings if previous else []),
            captures=captures,
            imagery=imagery,
            overlays=overlays,
            secondary_view=(
                source.secondary_view
                if source and source.split_view.enabled
                else None
            ),
            investigations=investigation_state,
            selected_evidence_ids=selected_evidence,
            bookmarks=bookmark_refs,
            camera_history=history,
            split_view=(
                supplied.split_view
                if supplied
                else previous.split_view
                if previous
                else EarthSplitView()
            ),
            measurement=(
                supplied.measurement if supplied else previous.measurement if previous else None
            ),
        )

    @staticmethod
    def _unique[T](values: list[T], key: Callable[[T], str]) -> list[T]:
        seen: set[str] = set()
        result: list[T] = []
        for value in values:
            item_key = key(value)
            if item_key not in seen:
                seen.add(item_key)
                result.append(value)
        return result

    @classmethod
    def _merge_bookmarks(
        cls, current: list[EarthBookmarkRef], incoming: list[EarthBookmarkRef]
    ) -> list[EarthBookmarkRef]:
        return cls._unique([*current, *incoming], key=lambda item: item.id)
