"""Resumable Server-Sent Event streams."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from earth_platform.api.deps import EventBusDep, SessionStoreDep, SettingsDep
from earth_platform.shared.errors import ValidationFailedError
from earth_platform.streaming.sse import SSEEventEncoder

router = APIRouter(prefix="/streams", tags=["streams"])
_encoder = SSEEventEncoder()


@router.get("/{session_id}")
async def stream_session_events(
    session_id: str,
    event_bus: EventBusDep,
    store: SessionStoreDep,
    settings: SettingsDep,
    after_seq: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    await store.sessions.get(session_id)
    if last_event_id is not None:
        try:
            after_seq = int(last_event_id)
        except ValueError as exc:
            raise ValidationFailedError("Last-Event-ID must be a non-negative integer") from exc
        if after_seq < 0:
            raise ValidationFailedError("Last-Event-ID must be a non-negative integer")

    async def frames() -> AsyncIterator[bytes]:
        events = event_bus.subscribe(session_id, after_seq=after_seq)
        next_event = asyncio.create_task(events.__anext__())
        try:
            while True:
                done, _ = await asyncio.wait(
                    {next_event},
                    timeout=settings.streaming.heartbeat_interval_s,
                )
                if not done:
                    yield _encoder.heartbeat()
                    continue
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    return
                yield _encoder.encode(event)
                next_event = asyncio.create_task(events.__anext__())
        finally:
            if not next_event.done():
                next_event.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await next_event
            await events.aclose()

    return StreamingResponse(
        frames(),
        media_type=_encoder.content_type,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
