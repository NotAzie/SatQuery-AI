import math
import re
from datetime import UTC, datetime
from typing import Any

from earth_platform.engine.models import EngineAgentSession
from earth_platform.intelligence.models import MemoryRecord, RankedMemoryRecord
from earth_platform.sessions.models import Session
from earth_platform.sessions.repository import SessionStore
from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import EarthContext, EarthDrawing
from earth_platform.shared.geo import LngLat, TimeRange
from earth_platform.shared.messages import ImagePart, TextPart, ToolResultPart
from earth_platform.vision.store import ImageStore

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "with",
}
_PLATFORM_CONTEXT_MARKER = "\n\n--- Platform workspace context (JSON) ---\n"


class WorkspaceMemory:
    """Deterministic lexical, geographic and temporal retrieval over recorded Platform facts."""

    def __init__(self, sessions: SessionStore, images: ImageStore) -> None:
        self._sessions = sessions
        self._images = images

    async def search(
        self,
        query: str,
        *,
        current_session_id: str | None = None,
        context: EarthContext | None = None,
        engine_investigation_ids: list[str] | None = None,
        transcript: EngineAgentSession | None = None,
        current_message: str | None = None,
        limit: int = 12,
    ) -> list[RankedMemoryRecord]:
        records = await self._build_index(current_session_id=current_session_id)
        if current_session_id is not None and transcript is not None:
            latest_user_index = next(
                (
                    index
                    for index in range(len(transcript.messages) - 1, -1, -1)
                    if transcript.messages[index].role == "user"
                ),
                -1,
            )
            for index, message in enumerate(transcript.messages):
                if message.role not in {"user", "assistant"} or not message.content:
                    continue
                content = message.content.split(_PLATFORM_CONTEXT_MARKER, maxsplit=1)[0]
                if (
                    index == latest_user_index
                    and current_message is not None
                    and content == current_message
                ):
                    continue
                records.append(
                    MemoryRecord(
                        id=f"conversation:{current_session_id}:{message.turn_id}:{index}",
                        kind="conversation",
                        session_id=current_session_id,
                        title=f"{message.role} message",
                        content=content,
                        created_at=transcript.updated_at,
                        location=context.camera.position if context else None,
                    )
                )
        if current_session_id is not None and engine_investigation_ids:
            location = context.camera.position if context else None
            records.extend(
                MemoryRecord(
                    id=f"investigation:{current_session_id}:{investigation_id}",
                    kind="investigation",
                    session_id=current_session_id,
                    title=f"Engine investigation {investigation_id}",
                    content=f"Previously recorded Engine investigation {investigation_id}",
                    created_at=utcnow(),
                    location=location,
                    time_reference=(
                        context.instant
                        if context and context.instant
                        else context.time.start
                        if context and context.time
                        else None
                    ),
                    time_range=context.time if context else None,
                )
                for investigation_id in engine_investigation_ids
            )
        terms = set(_TOKEN.findall(query.casefold())) - _STOP_WORDS
        target_location = context.camera.position if context else None
        target_time = (
            context.instant
            if context and context.instant
            else context.time.start
            if context and context.time
            else None
        )
        target_range = context.time if context else None
        ranked: list[RankedMemoryRecord] = []
        for record in records:
            score = self._score(record, terms, target_location, target_time, target_range)
            if score > 0:
                ranked.append(RankedMemoryRecord(record=record, score=score))
        ranked.sort(key=lambda result: (-result.score, -result.record.created_at.timestamp()))
        return ranked[:limit]

    async def _build_index(self, *, current_session_id: str | None) -> list[MemoryRecord]:
        sessions: list[Session] = []
        offset = 0
        while True:
            page = await self._sessions.sessions.list(
                include_archived=True,
                limit=500,
                offset=offset,
            )
            sessions.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
        assets = await self._images.list_all()
        assets_by_session: dict[str, list[Any]] = {}
        for asset in assets:
            if asset.session_id is not None:
                assets_by_session.setdefault(asset.session_id, []).append(asset)

        records: list[MemoryRecord] = []
        for session in sessions:
            session_records = self._session_records(session)
            if session.id == current_session_id:
                session_records = [
                    record for record in session_records if record.kind != "earth_context"
                ]
            records.extend(session_records)
            for asset in assets_by_session.get(session.id, []):
                position = asset.georef.center if asset.georef else None
                title = asset.filename or f"{asset.mime_type} image"
                metadata = " ".join(
                    f"{key} {value}" for key, value in asset.source_metadata.items()
                )
                georef_text = ""
                if asset.georef:
                    georef_text = (
                        f" CRS {asset.georef.crs} orientation {asset.georef.orientation_deg}"
                    )
                records.append(
                    MemoryRecord(
                        id=f"asset:{asset.id}",
                        kind="asset",
                        session_id=session.id,
                        title=title,
                        content=f"{title} {asset.origin} {metadata}{georef_text}",
                        created_at=asset.created_at,
                        location=position,
                    )
                )
            for conversation in await self._sessions.conversations.list_for_session(session.id):
                for message in conversation.messages:
                    text_parts: list[str] = []
                    evidence_ids: list[str] = []
                    for part in message.content:
                        if isinstance(part, TextPart):
                            text_parts.append(part.text)
                        elif isinstance(part, ImagePart):
                            text_parts.append(part.alt or f"image {part.asset_id}")
                        elif isinstance(part, ToolResultPart):
                            evidence_ids.extend(part.evidence_ids)
                    if text_parts:
                        records.append(
                            MemoryRecord(
                                id=f"conversation:{conversation.id}:{message.id}",
                                kind="conversation",
                                session_id=session.id,
                                title=conversation.title or f"{message.role} message",
                                content=" ".join(text_parts + evidence_ids),
                                created_at=message.created_at,
                            )
                        )
            async for event in self._sessions.events.read_after(session.id, 0):
                event_time = _event_time(event.payload, event.at)
                if event.type == "investigation.updated":
                    investigation_id = event.payload.get("investigation_id")
                    if isinstance(investigation_id, str):
                        status = event.payload.get("status", "unknown")
                        records.append(
                            MemoryRecord(
                                id=f"investigation:{session.id}:{investigation_id}",
                                kind="investigation",
                                session_id=session.id,
                                title=f"Investigation {investigation_id}",
                                content=f"Investigation {investigation_id} status {status}",
                                created_at=event_time,
                                time_reference=session.context.focus_time.start
                                if session.context.focus_time
                                else None,
                                time_range=session.context.focus_time,
                            )
                        )
                elif event.type == "engine.event":
                    engine_kind = event.payload.get("engine_kind")
                    payload = event.payload.get("payload")
                    if engine_kind == "investigation.progress" and isinstance(payload, dict):
                        investigation_id = payload.get("investigation_id")
                        if isinstance(investigation_id, str):
                            records.append(
                                MemoryRecord(
                                    id=f"investigation:{session.id}:{investigation_id}",
                                    kind="investigation",
                                    session_id=session.id,
                                    title=f"Investigation {investigation_id}",
                                    content=f"Engine investigation progress {investigation_id}",
                                    created_at=event_time,
                                    time_reference=session.context.focus_time.start
                                    if session.context.focus_time
                                    else None,
                                    time_range=session.context.focus_time,
                                )
                            )
        return records

    @classmethod
    def _session_records(cls, session: Session) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        if session.title:
            records.append(
                MemoryRecord(
                    id=f"session:{session.id}",
                    kind="session",
                    session_id=session.id,
                    title=session.title,
                    content=session.title,
                    created_at=session.updated_at,
                )
            )
        focus = session.context.focus_region
        focus_location = None
        if focus:
            longitude = (
                (focus.west + focus.east) / 2
                if focus.west <= focus.east
                else ((focus.west + focus.east + 360) / 2 + 180) % 360 - 180
            )
            focus_location = LngLat(lng=longitude, lat=(focus.south + focus.north) / 2)
        for investigation_id in session.context.active_investigation_ids:
            records.append(
                MemoryRecord(
                    id=f"investigation:{session.id}:{investigation_id}",
                    kind="investigation",
                    session_id=session.id,
                    title=f"Investigation {investigation_id}",
                    content=cls._focus_text(session) + f" investigation {investigation_id}",
                    created_at=session.updated_at,
                    location=focus_location,
                    time_reference=session.context.focus_time.start
                    if session.context.focus_time
                    else None,
                    time_range=session.context.focus_time,
                )
            )
        for evidence_id in session.context.pinned_evidence_ids:
            records.append(
                MemoryRecord(
                    id=f"evidence:{session.id}:{evidence_id}",
                    kind="evidence",
                    session_id=session.id,
                    title=f"Evidence {evidence_id}",
                    content=f"Engine evidence reference {evidence_id} {cls._focus_text(session)}",
                    created_at=session.updated_at,
                    location=focus_location,
                    time_reference=session.context.focus_time.start
                    if session.context.focus_time
                    else None,
                    time_range=session.context.focus_time,
                )
            )
        for bookmark in session.earth_workspace.bookmarks:
            records.append(
                MemoryRecord(
                    id=f"bookmark:{session.id}:{bookmark.id}",
                    kind="bookmark",
                    session_id=session.id,
                    title=bookmark.name,
                    content=cls._context_text(bookmark.context),
                    created_at=bookmark.updated_at,
                    location=bookmark.context.camera.position,
                    time_reference=bookmark.context.instant
                    or (bookmark.context.time.start if bookmark.context.time else None),
                    time_range=bookmark.context.time,
                )
            )
            records.extend(
                cls._drawing_records(
                    session.id,
                    bookmark.context.drawings,
                    bookmark.updated_at,
                    bookmark.context.camera.position,
                    bookmark.context.instant
                    or (bookmark.context.time.start if bookmark.context.time else None),
                    bookmark.context.time,
                )
            )
        for index, context in enumerate(session.earth_context_snapshots):
            records.append(
                MemoryRecord(
                    id=f"earth-context:{session.id}:{index}",
                    kind="earth_context",
                    session_id=session.id,
                    title=f"Earth workspace snapshot {index + 1}",
                    content=cls._context_text(context),
                    created_at=session.updated_at,
                    location=context.camera.position,
                    time_reference=context.instant
                    or (context.time.start if context.time else None),
                    time_range=context.time,
                )
            )
            records.extend(
                cls._drawing_records(
                    session.id,
                    context.drawings,
                    session.updated_at,
                    context.camera.position,
                    context.instant or (context.time.start if context.time else None),
                    context.time,
                )
            )
        return records

    @staticmethod
    def _focus_text(session: Session) -> str:
        values = (
            [f"region {session.context.focus_region.model_dump_json()}"]
            if session.context.focus_region
            else []
        )
        if session.context.focus_time:
            values.append(f"time {session.context.focus_time.model_dump_json()}")
        return " ".join(values)

    @staticmethod
    def _context_text(context: EarthContext) -> str:
        parts = [
            f"camera {context.camera.position.lng},{context.camera.position.lat}",
            f"height {context.camera.height_m}",
        ]
        if context.instant:
            parts.append(f"time {context.instant.isoformat()}")
        if context.time:
            parts.append(
                f"time range {context.time.start.isoformat()} {context.time.end.isoformat()}"
            )
        parts.extend(f"bookmark {item.name}" for item in context.bookmarks)
        parts.extend(f"evidence {item}" for item in context.selected_evidence_ids)
        parts.extend(drawing.name for drawing in context.drawings)
        return " ".join(parts)

    @staticmethod
    def _drawing_records(
        session_id: str,
        drawings: list[EarthDrawing],
        created_at: datetime,
        fallback_location: LngLat,
        time_reference: datetime | None,
        time_range: TimeRange | None,
    ) -> list[MemoryRecord]:
        return [
            MemoryRecord(
                id=f"drawing:{session_id}:{drawing.id}",
                kind="drawing",
                session_id=session_id,
                title=drawing.name,
                content=f"{drawing.name} {drawing.kind}",
                created_at=created_at,
                location=_first_geometry_position(drawing.geometry) or fallback_location,
                time_reference=time_reference,
                time_range=time_range,
            )
            for drawing in drawings
        ]

    @staticmethod
    def _score(
        record: MemoryRecord,
        terms: set[str],
        target_location: LngLat | None,
        target_time: datetime | None,
        target_range: TimeRange | None,
    ) -> float:
        score = 0.0
        searchable = f"{record.title} {record.content}".casefold()
        record_terms = set(_TOKEN.findall(searchable)) - _STOP_WORDS
        if terms and record_terms:
            score += len(terms & record_terms) / len(terms)
        if target_location and record.location:
            distance_km = _distance_km(target_location, record.location)
            score += max(0.0, 1.0 - distance_km / 2000.0)
        if target_range and record.time_range:
            if (
                target_range.start <= record.time_range.end
                and record.time_range.start <= target_range.end
            ):
                score += 0.25
        elif target_time and record.time_reference:
            if target_time.tzinfo is None:
                target_time = target_time.replace(tzinfo=UTC)
            time_reference = record.time_reference
            if time_reference.tzinfo is None:
                time_reference = time_reference.replace(tzinfo=UTC)
            elapsed_days = abs((time_reference - target_time).total_seconds()) / 86400
            score += max(0.0, 0.25 * (1.0 - elapsed_days / 365.0))
        return score


def _first_geometry_position(geometry: dict[str, Any]) -> LngLat | None:
    coordinates = geometry.get("coordinates")
    while isinstance(coordinates, list) and coordinates:
        first = coordinates[0]
        if (
            isinstance(first, (int, float))
            and len(coordinates) >= 2
            and isinstance(coordinates[1], (int, float))
        ):
            longitude, latitude = float(first), float(coordinates[1])
            if -180 <= longitude <= 180 and -90 <= latitude <= 90:
                return LngLat(lng=longitude, lat=latitude)
            return None
        coordinates = first
    return None


def _event_time(payload: dict[str, Any], fallback: datetime) -> datetime:
    value = payload.get("at")
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return fallback


def _distance_km(first: LngLat, second: LngLat) -> float:
    latitude1, latitude2 = math.radians(first.lat), math.radians(second.lat)
    delta_lat = latitude2 - latitude1
    delta_lng = math.radians(second.lng - first.lng)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(latitude1) * math.cos(latitude2) * math.sin(delta_lng / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(haversine)))
