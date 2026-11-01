"""Session-scoped image upload, metadata, thumbnails and provider-neutral preparation."""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from earth_platform.api.deps import ContainerDep, SessionStoreDep
from earth_platform.container import Container
from earth_platform.shared.errors import NotFoundError, ValidationFailedError
from earth_platform.vision.types import (
    GeoReference,
    ImageAsset,
    ImageOrigin,
    PreparedVisionPayload,
    PrepareVisionRequest,
    UpdateImageAssetRequest,
)

router = APIRouter(prefix="/vision", tags=["vision"])
_ORIGINS = {"upload", "drag_drop", "clipboard", "screen_capture", "earth_capture"}


async def _upload_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(1024 * 1024):
        yield chunk


def _parse_georef(raw: str | None) -> GeoReference | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("georeference must be an object")
        return GeoReference.model_validate(value)
    except (ValueError, ValidationError) as exc:
        raise ValidationFailedError("Georeference metadata is invalid") from exc


async def _session_asset(
    session_id: str,
    asset_id: str,
    container: Container,
) -> ImageAsset:
    asset = await container.image_store.get_asset(asset_id)
    if asset.session_id != session_id:
        raise NotFoundError(f"Image asset '{asset_id}' was not found in this session")
    return asset


@router.post("/sessions/{session_id}/assets", response_model=ImageAsset, status_code=201)
async def upload_image(
    session_id: str,
    container: ContainerDep,
    sessions: SessionStoreDep,
    upload: Annotated[UploadFile, File()],
    origin: Annotated[ImageOrigin, Form()] = "upload",
    georef: Annotated[str | None, Form()] = None,
) -> ImageAsset:
    await sessions.sessions.get(session_id)
    if origin not in _ORIGINS:
        raise ValidationFailedError(f"Unsupported image origin '{origin}'")
    return await container.image_ingestor.ingest(
        _upload_chunks(upload),
        origin=origin,
        declared_mime_type=upload.content_type,
        filename=upload.filename,
        session_id=session_id,
        georef=_parse_georef(georef),
    )


@router.get("/sessions/{session_id}/assets", response_model=list[ImageAsset])
async def list_assets(
    session_id: str,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> list[ImageAsset]:
    await sessions.sessions.get(session_id)
    return await container.image_store.list_for_session(session_id)


@router.get("/sessions/{session_id}/assets/{asset_id}", response_model=ImageAsset)
async def get_asset(
    session_id: str,
    asset_id: str,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> ImageAsset:
    await sessions.sessions.get(session_id)
    return await _session_asset(session_id, asset_id, container)


@router.get("/sessions/{session_id}/assets/{asset_id}/content")
async def get_asset_content(
    session_id: str,
    asset_id: str,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> StreamingResponse:
    await sessions.sessions.get(session_id)
    asset = await _session_asset(session_id, asset_id, container)
    return StreamingResponse(
        container.image_store.stream(asset_id),
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/sessions/{session_id}/assets/{asset_id}/thumbnail")
async def get_asset_thumbnail(
    session_id: str,
    asset_id: str,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> Response:
    await sessions.sessions.get(session_id)
    await _session_asset(session_id, asset_id, container)
    return Response(
        await container.image_store.read_thumbnail(asset_id),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.patch(
    "/sessions/{session_id}/assets/{asset_id}",
    response_model=ImageAsset,
)
async def update_asset(
    session_id: str,
    asset_id: str,
    body: UpdateImageAssetRequest,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> ImageAsset:
    await sessions.sessions.get(session_id)
    await _session_asset(session_id, asset_id, container)
    if not body.model_fields_set:
        raise ValidationFailedError("At least one image metadata field must be provided")
    return await container.image_store.update(
        asset_id,
        filename=body.filename,
        update_filename="filename" in body.model_fields_set,
        georef=body.georef,
        update_georef="georef" in body.model_fields_set,
    )


@router.delete(
    "/sessions/{session_id}/assets/{asset_id}",
    status_code=204,
)
async def delete_asset(
    session_id: str,
    asset_id: str,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> Response:
    await sessions.sessions.get(session_id)
    await _session_asset(session_id, asset_id, container)
    await container.image_store.delete(asset_id)
    return Response(status_code=204)


@router.post(
    "/sessions/{session_id}/prepare",
    response_model=PreparedVisionPayload,
)
async def prepare_images(
    session_id: str,
    body: PrepareVisionRequest,
    container: ContainerDep,
    sessions: SessionStoreDep,
) -> PreparedVisionPayload:
    await sessions.sessions.get(session_id)
    return await container.vision_preparer.prepare(session_id, body)
