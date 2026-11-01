from typing import Protocol

from earth_platform.vision.types import PreparedVisionPayload, PrepareVisionRequest


class MultimodalPreparer(Protocol):
    """Builds a provider-neutral payload from stored images and client-supplied metadata."""

    async def prepare(
        self, session_id: str, request: PrepareVisionRequest
    ) -> PreparedVisionPayload: ...
