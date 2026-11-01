"""Validated filesystem-backed image ingestion, metadata, thumbnails and asset storage."""

import asyncio
import hashlib
import io
import re
import uuid
import warnings
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from earth_platform.settings.models import VisionSettings
from earth_platform.shared.errors import NotFoundError, ValidationFailedError
from earth_platform.vision.store import ImageStore
from earth_platform.vision.types import GeoReference, ImageAsset, ImageOrigin

_FORMAT_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
}
_ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
_THUMBNAIL_MAX_SIZE = (480, 480)


class FilesystemImageStore:
    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    def _directory(self, asset_id: str) -> Path:
        if not _ASSET_ID.fullmatch(asset_id):
            raise NotFoundError("Image asset was not found")
        return self._root / asset_id

    async def put(self, asset: ImageAsset, data: bytes, thumbnail: bytes) -> None:
        await asyncio.to_thread(self._put, asset, data, thumbnail)

    def _put(self, asset: ImageAsset, data: bytes, thumbnail: bytes) -> None:
        directory = self._directory(asset.id)
        directory.mkdir(parents=True, exist_ok=False)
        try:
            (directory / "image").write_bytes(data)
            (directory / "thumbnail.png").write_bytes(thumbnail)
            metadata = asset.model_dump_json()
            temporary = directory / "metadata.tmp"
            temporary.write_text(metadata, encoding="utf-8")
            temporary.replace(directory / "metadata.json")
        except Exception:
            for path in directory.iterdir():
                path.unlink()
            directory.rmdir()
            raise

    async def get_asset(self, asset_id: str) -> ImageAsset:
        return await asyncio.to_thread(self._get_asset, asset_id)

    def _get_asset(self, asset_id: str) -> ImageAsset:
        path = self._directory(asset_id) / "metadata.json"
        try:
            return ImageAsset.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NotFoundError(f"Image asset '{asset_id}' was not found") from exc

    async def read(self, asset_id: str) -> bytes:
        return await asyncio.to_thread(self._read, asset_id, "image")

    async def read_thumbnail(self, asset_id: str) -> bytes:
        return await asyncio.to_thread(self._read, asset_id, "thumbnail.png")

    async def stream(self, asset_id: str) -> AsyncIterator[bytes]:
        path = self._directory(asset_id) / "image"
        if not path.is_file():
            raise NotFoundError(f"Image asset '{asset_id}' was not found")
        with path.open("rb") as source:
            while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
                yield chunk

    def _read(self, asset_id: str, filename: str) -> bytes:
        path = self._directory(asset_id) / filename
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise NotFoundError(f"Image asset '{asset_id}' was not found") from exc

    async def list_for_session(self, session_id: str) -> list[ImageAsset]:
        return await asyncio.to_thread(self._list_for_session, session_id)

    async def list_all(self) -> list[ImageAsset]:
        return await asyncio.to_thread(self._list_all)

    def _list_all(self) -> list[ImageAsset]:
        if not self._root.exists():
            return []
        assets = [
            ImageAsset.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self._root.glob("*/metadata.json")
        ]
        return sorted(assets, key=lambda asset: asset.created_at)

    def _list_for_session(self, session_id: str) -> list[ImageAsset]:
        if not self._root.exists():
            return []
        assets: list[ImageAsset] = []
        for metadata_path in self._root.glob("*/metadata.json"):
            asset = ImageAsset.model_validate_json(metadata_path.read_text(encoding="utf-8"))
            if asset.session_id == session_id:
                assets.append(asset)
        return sorted(assets, key=lambda asset: asset.created_at)

    async def update(
        self,
        asset_id: str,
        *,
        filename: str | None = None,
        update_filename: bool = False,
        georef: GeoReference | None = None,
        update_georef: bool = False,
    ) -> ImageAsset:
        return await asyncio.to_thread(
            self._update,
            asset_id,
            filename,
            update_filename,
            georef,
            update_georef,
        )

    def _update(
        self,
        asset_id: str,
        filename: str | None,
        update_filename: bool,
        georef: GeoReference | None,
        update_georef: bool,
    ) -> ImageAsset:
        asset = self._get_asset(asset_id)
        if update_filename:
            asset.filename = _safe_filename(filename) if filename is not None else None
        if update_georef:
            asset.georef = georef
        path = self._directory(asset_id) / "metadata.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(asset.model_dump_json(), encoding="utf-8")
        temporary.replace(path)
        return asset

    async def delete(self, asset_id: str) -> None:
        await asyncio.to_thread(self._delete, asset_id)

    def _delete(self, asset_id: str) -> None:
        directory = self._directory(asset_id)
        if not directory.exists():
            raise NotFoundError(f"Image asset '{asset_id}' was not found")
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()


class FilesystemImageIngestor:
    def __init__(self, store: ImageStore, settings: VisionSettings) -> None:
        self._store = store
        self._settings = settings

    async def ingest(
        self,
        data: AsyncIterable[bytes],
        *,
        origin: ImageOrigin,
        declared_mime_type: str | None = None,
        filename: str | None = None,
        session_id: str | None = None,
        georef: GeoReference | None = None,
    ) -> ImageAsset:
        parts: list[bytes] = []
        size = 0
        async for part in data:
            size += len(part)
            if size > self._settings.max_image_bytes:
                raise ValidationFailedError(
                    f"Image exceeds the {self._settings.max_image_bytes}-byte size limit"
                )
            parts.append(part)
        if not size:
            raise ValidationFailedError("Image upload is empty")
        raw = b"".join(parts)
        mime_type, width, height, thumbnail = await asyncio.to_thread(
            _inspect_image, raw, declared_mime_type, self._settings.allowed_mime_types
        )
        asset = ImageAsset(
            id=uuid.uuid4().hex,
            session_id=session_id,
            mime_type=mime_type,
            size_bytes=size,
            width=width,
            height=height,
            sha256=hashlib.sha256(raw).hexdigest(),
            origin=origin,
            filename=_safe_filename(filename) if filename else None,
            georef=georef,
        )
        await self._store.put(asset, raw, thumbnail)
        return asset


def _inspect_image(
    raw: bytes,
    declared_mime_type: str | None,
    allowed_mime_types: list[str],
) -> tuple[str, int, int, bytes]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(raw))
            image.verify()
            image = Image.open(io.BytesIO(raw))
            width, height = image.size
            image.load()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValidationFailedError("Uploaded data is not a valid supported image") from exc
    mime_type = _FORMAT_MIME.get(image.format or "")
    if not mime_type or mime_type not in allowed_mime_types:
        raise ValidationFailedError("Image format is not allowed")
    if declared_mime_type and declared_mime_type not in {"application/octet-stream", mime_type}:
        raise ValidationFailedError("Declared content type does not match the image data")
    thumbnail_image = ImageOps.exif_transpose(image)
    thumbnail_image.thumbnail(_THUMBNAIL_MAX_SIZE)
    output = io.BytesIO()
    thumbnail_image.convert("RGBA").save(output, format="PNG", optimize=True)
    return mime_type, width, height, output.getvalue()


def _safe_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    safe = "".join(
        character for character in basename if character.isprintable() and character not in "\r\n"
    )
    if not safe or safe in {".", ".."}:
        raise ValidationFailedError("Image filename is invalid")
    return safe[:255]
