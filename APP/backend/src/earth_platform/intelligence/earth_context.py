from collections.abc import Callable

from earth_platform.sessions.models import Session
from earth_platform.shared.earth import (
    EarthBookmarkRef,
    EarthContext,
    EarthSplitView,
)


class EarthContextBuilder:
    """Builds one serializable workspace snapshot from live and persisted presentation state."""

    def build(
        self,
        session: Session,
        supplied: EarthContext | None,
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
        captures = self._unique(
            [
                *persisted.captures,
                *(previous.captures if previous else []),
                *(supplied.captures if supplied else []),
            ],
            key=lambda item: item.id,
        )
        selected_evidence = self._unique(
            [
                *session.context.pinned_evidence_ids,
                *(previous.selected_evidence_ids if previous else []),
                *(supplied.selected_evidence_ids if supplied else []),
            ],
            key=lambda item: item,
        )
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
            layers=source.layers if source else [],
            time=(
                supplied.time
                if supplied
                else (previous.time if previous else session.context.focus_time)
            ),
            instant=(supplied.instant if supplied else previous.instant if previous else None),
            selection=(
                supplied.selection if supplied else previous.selection if previous else None
            ),
            drawings=supplied.drawings if supplied else (previous.drawings if previous else []),
            captures=captures,
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
