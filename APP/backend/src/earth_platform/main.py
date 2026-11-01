from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from earth_platform import __version__
from earth_platform.api import health
from earth_platform.api.errors import install_error_handlers
from earth_platform.api.v1 import router as v1_router
from earth_platform.lifecycle import lifespan
from earth_platform.settings import Settings, load_settings
from earth_platform.shared.constants import API_PREFIX


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(v1_router, prefix=API_PREFIX)
    return app
