from datetime import UTC, datetime, timedelta

import pytest

from earth_platform.agent.runtime import AgentTurnRequest
from earth_platform.earth.layers import LayerRegistry
from earth_platform.engine.models import (
    EngineAgentImageRef,
    EngineAgentMessage,
    EngineAgentSession,
    EngineEarthContext,
)
from earth_platform.intelligence.capabilities import CapabilityDiscovery
from earth_platform.intelligence.context import ConversationContextBuilder
from earth_platform.intelligence.earth_context import EarthContextBuilder
from earth_platform.intelligence.memory import WorkspaceMemory
from earth_platform.intelligence.models import MemoryRecord, RankedMemoryRecord
from earth_platform.intelligence.planner import PromptAssembler, RequestPlanner
from earth_platform.intelligence.recommendations import RecommendationEngine
from earth_platform.sessions.models import InvestigationContext, Session
from earth_platform.sessions.sqlite import SQLiteSessionStore
from earth_platform.settings import Settings
from earth_platform.settings.models import IntelligenceSettings
from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import (
    CameraState,
    EarthBookmark,
    EarthContext,
    EarthDrawing,
    EarthOverlay,
    EarthSecondaryView,
    EarthViewport,
    EarthWorkspaceState,
)
from earth_platform.shared.geo import LngLat, TimeRange
from earth_platform.shared.registry import Registry
from earth_platform.vision.filesystem import FilesystemImageStore
from earth_platform.vision.types import GeoReference, ImageAsset, VisionContext


def _camera(lng: float, lat: float = 0) -> CameraState:
    return CameraState(
        position=LngLat(lng=lng, lat=lat),
        height_m=500_000,
        heading_deg=0,
        pitch_deg=-90,
        roll_deg=0,
    )


def _context(lng: float = 10, lat: float = 0) -> EarthContext:
    return EarthContext(camera=_camera(lng, lat))


def _engine_session(
    messages: list[EngineAgentMessage] | None = None,
    investigation_ids: list[str] | None = None,
) -> EngineAgentSession:
    now = utcnow()
    return EngineAgentSession(
        session_id="engine-session",
        created_at=now,
        updated_at=now,
        messages=messages or [],
        investigation_ids=investigation_ids or [],
    )


def test_earth_context_builder_merges_live_and_persisted_workspace():
    bookmark = EarthBookmark(
        id="bookmark-1",
        name="Field site",
        context=_context(11),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    saved_capture = {
        "id": "capture-1",
        "asset_id": "asset-1",
        "captured_at": utcnow(),
        "source": "viewport",
        "camera": _camera(10),
    }
    session = Session(
        earth_workspace=EarthWorkspaceState(
            camera_history={"present": _camera(9)},
            bookmarks=[bookmark],
            captures=[saved_capture],
        ),
        context=InvestigationContext(pinned_evidence_ids=["evidence-1"]),
    )
    supplied = _context(10)
    supplied.drawings = [
        EarthDrawing(
            id="drawing-1",
            name="User marker",
            kind="point",
            geometry={"type": "Point", "coordinates": [10, 0]},
        )
    ]
    supplied.viewport = EarthViewport(width_px=1200, height_px=800, pixel_ratio=2)
    supplied.timeline_playback.playing = True
    supplied.timeline_playback.speed = 4
    supplied.overlays = [
        EarthOverlay(
            id="investigation:investigation-1",
            label="investigation-1",
            investigation_id="investigation-1",
            features=[
                {
                    "id": "earth-object-1",
                    "geometry": {"type": "Point", "coordinates": [10, 0]},
                    "properties": {"evidence_ids": ["evidence-1"]},
                }
            ],
            geometry_policy="WGS 84",
        )
    ]
    supplied.secondary_view = EarthSecondaryView(
        camera=_camera(-20),
        viewport=EarthViewport(width_px=600, height_px=800),
    )
    supplied.split_view.enabled = True

    result = EarthContextBuilder().build(
        session,
        supplied,
        engine_investigation_ids=["investigation-1"],
    )

    assert result is not None
    assert result.camera == _camera(10)
    assert result.bookmarks[0].name == "Field site"
    assert result.camera_history.present == _camera(9)
    assert result.captures[0].id == "capture-1"
    assert result.selected_evidence_ids == ["evidence-1"]
    assert result.drawings[0].name == "User marker"
    assert result.viewport == EarthViewport(width_px=1200, height_px=800, pixel_ratio=2)
    assert result.timeline_playback.playing
    assert result.investigations.known_ids == ["investigation-1"]
    assert result.investigations.visible_ids == ["investigation-1"]
    assert result.overlays[0].features[0].properties["evidence_ids"] == ["evidence-1"]
    assert result.imagery[0].asset_id == "asset-1"
    assert result.secondary_view is not None
    assert result.secondary_view.camera.position.lng == -20

    forwarded = EngineEarthContext.from_workspace(
        result,
        attached_images=[
            EngineAgentImageRef(
                asset_id="asset-2",
                mime_type="image/png",
                size_bytes=128,
                width=16,
                height=8,
                sha256="a" * 64,
            )
        ],
    )
    assert forwarded.viewport is not None
    assert result.viewport is not None
    assert forwarded.viewport.model_dump() == result.viewport.model_dump()
    assert forwarded.timeline_playback.playing
    assert forwarded.investigations.visible_ids == ["investigation-1"]
    assert forwarded.overlays[0].features[0].id == "earth-object-1"
    assert forwarded.secondary_view is not None
    assert forwarded.secondary_view.camera.position.lng == -20
    assert forwarded.imagery[0].asset_id == "asset-1"
    assert forwarded.imagery[1].asset_id == "asset-2"
    assert forwarded.imagery[1].attached


def test_conversation_context_applies_history_limit_and_extractive_compression():
    now = utcnow()
    transcript = _engine_session(
        [
            EngineAgentMessage(role="user", content="Earlier question " * 120, turn_id="1"),
            EngineAgentMessage(role="assistant", content="Recorded answer", turn_id="1"),
            EngineAgentMessage(role="user", content="Recent prompt", turn_id="2"),
            EngineAgentMessage(role="assistant", content="Recent answer", turn_id="2"),
        ]
    )
    transcript.updated_at = now

    result = ConversationContextBuilder().build(
        transcript,
        history_limit=4,
        token_budget=70,
    )

    assert [message.content for message in result.messages][-2:] == [
        "Recent prompt",
        "Recent answer",
    ]
    assert result.compressed_summary is not None
    assert "user: Earlier question" in result.compressed_summary
    assert any(message.content == "Recorded answer" for message in result.messages)
    assert result.omitted_message_count == 0
    assert result.estimated_tokens <= 100


def test_conversation_context_reports_messages_omitted_by_history_limit():
    transcript = _engine_session(
        [
            EngineAgentMessage(role="user", content="one", turn_id="1"),
            EngineAgentMessage(role="assistant", content="two", turn_id="1"),
            EngineAgentMessage(role="user", content="three", turn_id="2"),
        ]
    )
    result = ConversationContextBuilder().build(
        transcript,
        history_limit=1,
        token_budget=100,
    )

    assert [message.content for message in result.messages] == ["three"]
    assert result.omitted_message_count == 2


def test_prompt_assembler_compresses_low_ranked_context_to_token_budget():
    now = utcnow()
    memory = [
        RankedMemoryRecord(
            record=MemoryRecord(
                id=f"memory-{index}",
                kind="bookmark",
                session_id="session-1",
                title=f"Bookmark {index}",
                content="workspace " * 120,
                created_at=now - timedelta(minutes=index),
            ),
            score=20 - index,
        )
        for index in range(10)
    ]
    earth = {
        "camera": {"position": {"lng": 12, "lat": 40}},
        "camera_history": {
            "past": [{"lng": index} for index in range(40)],
            "present": None,
            "future": [],
        },
        "drawings": [{"name": f"Drawing {index}"} for index in range(40)],
        "captures": [],
        "bookmarks": [],
    }

    assembled, tokens, compressed, dropped, compacted_earth = PromptAssembler().assemble(
        "Review this workspace",
        earth_context=earth,
        vision_context=VisionContext(),
        memory=memory,
        capabilities={},
        token_budget=200,
    )

    assert tokens <= 500
    assert compressed
    assert dropped > 0
    assert "omitted_drawings_count" in assembled
    assert compacted_earth is not None
    assert compacted_earth["omitted_drawings_count"] == 28


def test_prompt_assembler_keeps_vision_metadata_without_image_bytes():
    assembled, _, _, _, _ = PromptAssembler().assemble(
        "Review metadata",
        earth_context=None,
        vision_context=VisionContext(metadata={"origin": "viewport"}),
        memory=[],
        capabilities={},
        token_budget=300,
    )

    assert '"origin":"viewport"' in assembled
    assert "data_base64" not in assembled


@pytest.mark.asyncio
async def test_workspace_memory_searches_existing_records_and_asset_metadata(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    images = FilesystemImageStore(tmp_path / "images")
    try:
        bookmark = EarthBookmark(
            id="bookmark-1",
            name="Floodplain survey",
            context=_context(12, 40),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session = await store.sessions.create(
            Session(
                title="River monitoring",
                earth_workspace=EarthWorkspaceState(bookmarks=[bookmark]),
                context=InvestigationContext(
                    active_investigation_ids=["investigation-1"],
                    pinned_evidence_ids=["evidence-1"],
                    focus_region={"west": 11, "south": 39, "east": 13, "north": 41},
                ),
            )
        )
        asset = ImageAsset(
            id="a" * 32,
            session_id=session.id,
            mime_type="image/png",
            size_bytes=4,
            sha256="b" * 64,
            origin="upload",
            filename="floodplain-before.png",
            georef=GeoReference(center=LngLat(lng=12, lat=40)),
        )
        await images.put(asset, b"data", b"thumb")
        await store.events.append(
            session.id,
            "engine.event",
            {
                "type": "engine.event",
                "at": utcnow().isoformat(),
                "engine_kind": "investigation.progress",
                "payload": {"investigation_id": "progress-1"},
            },
        )

        results = await WorkspaceMemory(store, images).search(
            "floodplain",
            current_session_id=session.id,
            context=_context(12, 40),
        )

        assert {item.record.kind for item in results} >= {
            "asset",
            "bookmark",
            "investigation",
            "evidence",
        }
        assert all(item.record.session_id == session.id for item in results)
        progress = await WorkspaceMemory(store, images).search(
            "progress-1",
            current_session_id=session.id,
        )
        assert any(
            item.record.id.endswith("progress-1") and item.record.kind == "investigation"
            for item in progress
        )
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_workspace_memory_ranks_timeline_overlapping_bookmarks_higher(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    images = FilesystemImageStore(tmp_path / "images")
    try:
        now = utcnow()
        target_range = TimeRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
        )
        overlapping = EarthBookmark(
            id="overlap",
            name="Riverside survey",
            context=EarthContext(camera=_camera(0), time=target_range),
            created_at=now,
            updated_at=now,
        )
        earlier = EarthBookmark(
            id="earlier",
            name="Riverside survey",
            context=EarthContext(
                camera=_camera(0),
                time=TimeRange(
                    start=datetime(2010, 1, 1, tzinfo=UTC),
                    end=datetime(2011, 1, 1, tzinfo=UTC),
                ),
            ),
            created_at=now,
            updated_at=now,
        )
        session = await store.sessions.create(
            Session(earth_workspace=EarthWorkspaceState(bookmarks=[earlier, overlapping]))
        )
        results = await WorkspaceMemory(store, images).search(
            "Riverside survey",
            context=EarthContext(camera=_camera(170, 80), time=target_range),
        )

        assert [item.record.id for item in results[:2]] == [
            f"bookmark:{session.id}:overlap",
            f"bookmark:{session.id}:earlier",
        ]
        recommendations = RecommendationEngine().recommend(results)
        assert any(item.kind == "timeline_overlap" for item in recommendations)
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_workspace_memory_breaks_score_and_timestamp_ties_by_record_id(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    images = FilesystemImageStore(tmp_path / "images")
    try:
        now = utcnow()
        bookmarks = [
            EarthBookmark(
                id=bookmark_id,
                name="Riverside survey",
                context=_context(0),
                created_at=now,
                updated_at=now,
            )
            for bookmark_id in ("bookmark-z", "bookmark-a")
        ]
        session = await store.sessions.create(
            Session(earth_workspace=EarthWorkspaceState(bookmarks=bookmarks))
        )

        results = await WorkspaceMemory(store, images).search(
            "Riverside survey",
            context=_context(0),
        )

        assert [item.record.id for item in results] == [
            f"bookmark:{session.id}:bookmark-a",
            f"bookmark:{session.id}:bookmark-z",
        ]
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_request_planner_builds_context_for_structured_engine_delivery(tmp_path):
    store = SQLiteSessionStore(str(tmp_path / "platform.sqlite3"))
    await store.open()
    images = FilesystemImageStore(tmp_path / "images")
    settings = Settings(
        _env_file=None,
        intelligence=IntelligenceSettings(context_token_budget=1200),
    )
    capabilities = CapabilityDiscovery(
        settings,
        Registry("provider factory"),
        Registry("tool source"),
        LayerRegistry("earth layer"),
    )
    memory = WorkspaceMemory(store, images)
    planner = RequestPlanner(
        store,
        images,
        EarthContextBuilder(),
        ConversationContextBuilder(),
        memory,
        capabilities,
        RecommendationEngine(),
        PromptAssembler(),
        settings.intelligence,
    )
    try:
        session = await store.sessions.create(Session(title="Current session"))
        context = _context(14)
        plan = await planner.plan(
            session,
            AgentTurnRequest(message="Inspect the selected location", earth_context=context),
            _engine_session(investigation_ids=["prior-investigation"]),
        )

        assert plan.request.earth_context is not None
        assert plan.request.earth_context.camera.position.lng == 14
        assert "Platform workspace context" in plan.request.engine_message
        assert '"earth_context"' not in plan.request.engine_message
        assert plan.engine_supports_earth_context
        assert plan.engine_supports_attachments
        assert not any("structured context" in item for item in plan.request.warnings)
        assert any(
            item.record.id.endswith("prior-investigation") for item in plan.request.retrieved_memory
        )
        saved = await store.sessions.get(session.id)
        assert saved.earth_context_snapshots[-1].camera.position.lng == 14

        asset = ImageAsset(
            id="c" * 32,
            session_id=session.id,
            mime_type="image/png",
            size_bytes=4,
            sha256="d" * 64,
            origin="upload",
            filename="selected-region.png",
        )
        await images.put(asset, b"data", b"thumb")
        image_plan = await planner.plan(
            saved,
            AgentTurnRequest(
                message="Review the attached image",
                asset_ids=[asset.id],
            ),
            _engine_session(),
        )
        assert image_plan.request.vision_context.assets[0].id == asset.id
        assert image_plan.request.attachments_supported_by_engine is True
        assert "data_base64" not in image_plan.request.engine_message
    finally:
        await store.aclose()
