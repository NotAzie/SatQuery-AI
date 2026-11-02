import asyncio

import pytest

from earth_platform.settings.models import VisionSettings
from earth_platform.vision.filesystem import FilesystemImageIngestor, FilesystemImageStore
from earth_platform.vision.types import GeoReference, ImageAsset


class _ImageStore:
    def __init__(self) -> None:
        self.assets: list[ImageAsset] = []

    async def put(self, asset: ImageAsset, _data: bytes, _thumbnail: bytes) -> None:
        self.assets.append(asset)


@pytest.mark.asyncio
async def test_image_ingestion_bounds_concurrent_buffering(tmp_path, monkeypatch):
    settings = VisionSettings(store_path=tmp_path, max_concurrent_ingests=2)
    store = _ImageStore()
    ingestor = FilesystemImageIngestor(store, settings)
    entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    maximum_active = 0

    def inspect_image(
        _raw: bytes,
        _declared_mime_type: str | None,
        _allowed_mime_types: list[str],
    ) -> tuple[str, int, int, bytes]:
        return "image/png", 1, 1, b"thumbnail"

    monkeypatch.setattr("earth_platform.vision.filesystem._inspect_image", inspect_image)

    async def image_data():
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        if active == settings.max_concurrent_ingests:
            entered.set()
        try:
            await release.wait()
            yield b"image"
        finally:
            active -= 1

    uploads = [
        asyncio.create_task(ingestor.ingest(image_data(), origin="upload"))
        for _ in range(3)
    ]
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert maximum_active == settings.max_concurrent_ingests
    finally:
        release.set()

    await asyncio.gather(*uploads)
    assert maximum_active == 2
    assert len(store.assets) == 3


@pytest.mark.asyncio
async def test_concurrent_asset_metadata_updates_preserve_independent_fields(tmp_path):
    store = FilesystemImageStore(tmp_path)
    asset = ImageAsset(
        id="a" * 32,
        mime_type="image/png",
        size_bytes=1,
        sha256="0" * 64,
        origin="upload",
        filename="original.png",
    )
    await store.put(asset, b"image", b"thumbnail")
    georef = GeoReference(center={"lng": 12.5, "lat": 48.1})

    await asyncio.gather(
        store.update(asset.id, filename="renamed.png", update_filename=True),
        store.update(asset.id, georef=georef, update_georef=True),
    )

    saved = await store.get_asset(asset.id)
    assert saved.filename == "renamed.png"
    assert saved.georef == georef
