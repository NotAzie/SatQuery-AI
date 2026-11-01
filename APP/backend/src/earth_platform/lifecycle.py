from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from earth_platform.container import build_container
from earth_platform.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    configure_logging(settings.logging)
    container = build_container(settings)
    try:
        await container.start()
        app.state.container = container
        yield
    finally:
        await container.aclose()
