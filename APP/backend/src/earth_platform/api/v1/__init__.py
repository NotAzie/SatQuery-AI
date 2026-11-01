from fastapi import APIRouter

from earth_platform.api.v1 import chat, earth, intelligence, plugins, sessions, streams, vision

router = APIRouter()
for module in (chat, sessions, vision, earth, plugins, streams, intelligence):
    router.include_router(module.router)
