from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from earth_platform.shared.errors import PlatformError


async def _platform_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PlatformError)
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(PlatformError, _platform_error_handler)
