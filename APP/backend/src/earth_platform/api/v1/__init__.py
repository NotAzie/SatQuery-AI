from fastapi import APIRouter

from earth_platform.api.v1 import (
    chat,
    earth,
    intelligence,
    monitoring,
    plugins,
    projects,
    sessions,
    streams,
    vision,
)

router = APIRouter()
for module in (
    chat,
    sessions,
    projects,
    vision,
    earth,
    plugins,
    streams,
    intelligence,
    monitoring,
):
    router.include_router(module.router)
