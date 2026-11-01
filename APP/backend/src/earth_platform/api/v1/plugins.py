"""Plugin discovery and panel manifests."""

from fastapi import APIRouter

router = APIRouter(prefix="/plugins", tags=["plugins"])
