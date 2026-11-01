from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from earth_platform.api.deps import EngineDep
from earth_platform.engine import EngineHealth

router = APIRouter(tags=["health"])


class Readiness(BaseModel):
    status: Literal["ready", "degraded"]
    engine: EngineHealth


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=Readiness)
async def readiness(engine: EngineDep) -> Readiness:
    health = await engine.health()
    return Readiness(status="ready" if health.status == "ok" else "degraded", engine=health)
