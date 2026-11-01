"""FastAPI surface for SatQuery AI."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from .config import Settings, get_settings
from .errors import QueryError, SatQueryError
from .orchestrator import SatQueryEngine
from .schemas import (
    CapabilityInfo,
    ErrorResponse,
    HealthResponse,
    Modality,
    QueryRequest,
    QueryResponse,
    ToolName,
    utc_now_iso,
)
from .ui import DASHBOARD_HTML

logger = logging.getLogger("satquery.api")

_engine: Optional[SatQueryEngine] = None


def get_engine() -> SatQueryEngine:
    """Process-wide engine singleton.

    Built once so the model registry, and therefore every loaded checkpoint,
    survives across requests.
    """
    global _engine
    if _engine is None:
        _engine = SatQueryEngine(get_settings())
    return _engine


def set_engine(engine: Optional[SatQueryEngine]) -> None:
    """Inject an engine. Used by tests and embedding applications."""
    global _engine
    _engine = engine


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    resolved = settings or get_settings()

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        description=(
            "An interactive vision-language assistant for multimodal remote sensing image "
            "analysis through text queries. Ask a natural question about a satellite or "
            "aerial image; SatQuery routes it to a specialist vision capability, runs real "
            "analysis on the pixels, and returns the answer with an execution trace.\n\n"
            f"Problem statement {resolved.problem_statement}. Built by {resolved.owner}."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    if resolved.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    # -- Error handling ----------------------------------------------------

    @app.exception_handler(SatQueryError)
    async def satquery_error_handler(request: Request, exc: SatQueryError) -> JSONResponse:
        """Every failure explains itself and says what to do next."""
        logger.info("%s on %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=exc.code,
                detail=exc.message,
                remediation=exc.remediation,
                context=exc.context,
            ).model_dump(mode="json"),
        )

    # -- Routes ------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(content=DASHBOARD_HTML)

    @app.get("/api/v1/health", response_model=HealthResponse, summary="Readiness and setup state")
    async def health() -> HealthResponse:
        engine = get_engine()
        report = engine.health()
        return HealthResponse(
            status=report["status"],
            app=resolved.app_name,
            version=resolved.app_version,
            owner=resolved.owner,
            problem_statement=resolved.problem_statement,
            timestamp_utc=utc_now_iso(),
            device=report["device"],
            backends=report["backends"],
            dependencies=report["dependencies"],
            ready=report["ready"],
            setup_actions=report["setup_actions"],
        )

    @app.get(
        "/api/v1/capabilities",
        response_model=List[CapabilityInfo],
        summary="What SatQuery can do right now",
    )
    async def capabilities() -> List[CapabilityInfo]:
        return get_engine().capabilities()

    @app.get("/api/v1/config", summary="Effective configuration, with secrets redacted")
    async def config() -> JSONResponse:
        return JSONResponse(resolved.describe())

    @app.post("/api/v1/warmup", summary="Load models now instead of on first query")
    async def warmup() -> JSONResponse:
        return JSONResponse(get_engine().warmup())

    @app.post(
        "/api/v1/query",
        response_model=QueryResponse,
        summary="Ask a question about uploaded imagery",
    )
    async def query_multipart(
        query: str = Form(..., description="Natural-language question about the image."),
        files: List[UploadFile] = File(
            default=[], description="One image, or two for change detection."
        ),
        image_paths: Optional[str] = Form(
            None, description="Comma-separated server-side paths, as an alternative to uploads."
        ),
        modality_hint: Optional[str] = Form(
            None, description="OPTICAL or SAR. Overrides the pixel heuristic."
        ),
        force_tool: Optional[str] = Form(
            None, description="Pin a capability and bypass routing."
        ),
        include_trace: bool = Form(True),
    ) -> QueryResponse:
        engine = get_engine()

        uploads = []
        for upload in files or []:
            if not upload or not upload.filename:
                continue
            payload = await upload.read()
            await upload.close()
            uploads.append((upload.filename, payload))

        paths = [
            piece.strip()
            for piece in (image_paths or "").replace(";", ",").split(",")
            if piece.strip()
        ]

        return engine.answer(
            query,
            uploads=uploads,
            image_paths=paths,
            modality_hint=_parse_modality(modality_hint),
            force_tool=_parse_tool(force_tool),
            include_trace=include_trace,
        )

    @app.post(
        "/api/v1/query/json",
        response_model=QueryResponse,
        summary="Ask a question about imagery already on the server",
    )
    async def query_json(body: QueryRequest) -> QueryResponse:
        engine = get_engine()
        if not body.image_paths:
            raise QueryError(
                "The JSON endpoint needs image_paths; it has no upload channel.",
                remediation=[
                    "Use POST /api/v1/query with multipart form data to upload files.",
                    "Or list server-side paths in image_paths.",
                ],
            )
        return engine.answer(
            body.query,
            image_paths=body.image_paths,
            modality_hint=body.modality_hint,
            force_tool=body.force_tool,
            include_trace=body.include_trace,
        )

    return app


def _parse_modality(raw: Optional[str]) -> Optional[Modality]:
    if not raw or not raw.strip():
        return None
    try:
        return Modality(raw.strip().upper())
    except ValueError as exc:
        raise QueryError(
            f"modality_hint must be OPTICAL or SAR, got {raw!r}.",
            remediation=["Leave it blank to let SatQuery infer modality from the pixels."],
        ) from exc


def _parse_tool(raw: Optional[str]) -> Optional[ToolName]:
    if not raw or not raw.strip():
        return None
    try:
        return ToolName(raw.strip().lower())
    except ValueError as exc:
        valid = ", ".join(item.value for item in ToolName)
        raise QueryError(
            f"force_tool must be one of: {valid}. Got {raw!r}.",
            remediation=["Leave it blank to let the router choose."],
        ) from exc


app = create_app()
