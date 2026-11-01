"""Provider-neutral assembly of persisted image bytes and typed vision metadata."""

import base64

from earth_platform.shared.errors import NotFoundError, ValidationFailedError
from earth_platform.vision.store import ImageStore
from earth_platform.vision.types import (
    ImageAsset,
    PreparedVisionAsset,
    PreparedVisionPayload,
    PrepareVisionRequest,
    VisionContext,
)


class StoredImagePreparer:
    def __init__(self, store: ImageStore, max_images: int, max_bytes: int) -> None:
        self._store = store
        self._max_images = max_images
        self._max_bytes = max_bytes

    async def prepare(
        self, session_id: str, request: PrepareVisionRequest
    ) -> PreparedVisionPayload:
        if len(request.asset_ids) > self._max_images:
            raise ValidationFailedError(f"A message may contain at most {self._max_images} images")
        if len(set(request.asset_ids)) != len(request.asset_ids):
            raise ValidationFailedError("An image asset may only be attached once")
        assets = [await self._session_asset(session_id, asset_id) for asset_id in request.asset_ids]
        total_bytes = sum(asset.size_bytes for asset in assets)
        if total_bytes > self._max_bytes:
            raise ValidationFailedError(
                f"Attached images exceed the {self._max_bytes}-byte message size limit"
            )
        attached_ids = set(request.asset_ids)
        if any(capture.asset_id not in attached_ids for capture in request.context.earth_captures):
            raise ValidationFailedError("Earth capture metadata must reference an attached image")

        context = VisionContext(
            assets=assets,
            earth_captures=request.context.earth_captures,
            georeference=request.context.georeference,
            metadata=request.context.metadata,
        )
        prepared_assets = [
            PreparedVisionAsset(
                asset=asset,
                data_base64=base64.b64encode(await self._store.read(asset.id)).decode("ascii"),
            )
            for asset in assets
        ]
        return PreparedVisionPayload(context=context, assets=prepared_assets)

    async def _session_asset(self, session_id: str, asset_id: str) -> ImageAsset:
        asset = await self._store.get_asset(asset_id)
        if asset.session_id != session_id:
            raise NotFoundError(f"Image asset '{asset_id}' was not found in this session")
        return asset
