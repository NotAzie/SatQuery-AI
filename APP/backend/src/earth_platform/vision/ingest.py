from collections.abc import AsyncIterable
from typing import Protocol

from earth_platform.vision.types import GeoReference, ImageAsset, ImageOrigin


class ImageIngestor(Protocol):
    """Validates (size, mime sniffing, count limits from settings), normalises and stores an
    incoming image. All entry points — file picker, drag & drop, clipboard paste, screen and
    Earth captures — converge here; only ``origin`` differs."""

    async def ingest(
        self,
        data: AsyncIterable[bytes],
        *,
        origin: ImageOrigin,
        declared_mime_type: str | None = None,
        filename: str | None = None,
        session_id: str | None = None,
        georef: GeoReference | None = None,
    ) -> ImageAsset: ...
