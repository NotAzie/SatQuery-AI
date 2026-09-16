"""The orchestration brain.

Responsibilities, in order:

1. Ingest images and attach modality.
2. Ask the router which capability to run.
3. Execute that capability, letting tools call each other through a shared
   cache so nothing is computed twice.
4. Assemble the answer and a step-by-step execution trace.

The orchestrator owns all the timing and all the trace assembly, so tools stay
focused on vision and never have to think about response shape.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .backends.base import VisionSuite
from .backends.hf_practical import PracticalVisionFactory
from .backends.rsvlm import RSVLMVision
from .backends.geochat import GeoChatVision
from .config import Settings, get_settings
from .errors import (
    QueryError,
    ResourceNotConfiguredError,
    SatQueryError,
    ToolExecutionError,
)
from .imaging import LoadedImage, apply_modality, load_image_from_bytes, load_image_from_path
from .registry import ModelRegistry
from .schemas import (
    BackendKind,
    CapabilityInfo,
    Intent,
    Modality,
    QueryPlan,
    QueryResponse,
    StepStatus,
    ToolName,
    ToolResult,
    TraceStep,
    utc_now_iso,
)
from .router import QueryRouter
from .tools import INTENT_TO_TOOL, ResultCache, Tool, ToolContext, build_tools

logger = logging.getLogger("satquery.orchestrator")

CAPABILITY_DOCS: Dict[ToolName, Tuple[Intent, str, int]] = {
    ToolName.CAPTION: (
        Intent.CAPTION,
        "Detailed remote-sensing description fusing captioning, scene classification, "
        "modality, and spatial layout.",
        1,
    ),
    ToolName.VQA: (
        Intent.VQA,
        "Open visual question answering, with an independent CLIP cross-check on yes/no "
        "presence questions.",
        1,
    ),
    ToolName.SCENE: (
        Intent.SCENE_CLASSIFICATION,
        "Zero-shot scene and land-use classification over a remote-sensing taxonomy, with "
        "quadrant voting for mixed scenes.",
        1,
    ),
    ToolName.GROUNDING: (
        Intent.GROUNDING,
        "Localises a named target using multi-scale CLIP window scoring against a contrast "
        "set, returning ranked regions.",
        1,
    ),
    ToolName.COUNTING: (
        Intent.COUNTING,
        "Estimates instance counts from grounded regions and a VQA numeric answer, reporting "
        "the disagreement between them.",
        1,
    ),
    ToolName.CHANGE: (
        Intent.CHANGE_DETECTION,
        "Bi-temporal change detection fusing radiometric differencing with CLIP semantic "
        "patch drift across two epochs.",
        2,
    ),
    ToolName.MODALITY: (
        Intent.MODALITY_ANALYSIS,
        "Determines optical versus SAR acquisition from pixel statistics, corroborated by a "
        "CLIP probe.",
        1,
    ),
    ToolName.EO_INSPECTION: (Intent.EO_INSPECTION, "Inspects EO raster metadata without inventing unavailable geospatial fields.", 1),
    ToolName.RASTER_STATISTICS: (Intent.RASTER_STATISTICS, "Computes valid-pixel statistics for an EO raster.", 1),
    ToolName.SPECTRAL_INDEX: (Intent.SPECTRAL_INDEX, "Calculates a registered spectral index from resolved bands.", 1),
}


class SatQueryEngine:
    """Top-level entry point. One instance per process."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.registry = ModelRegistry(self.settings)
        self.router = QueryRouter(self.settings)
        self.tools = build_tools()
        self.cache = ResultCache(self.settings.cache_size)
        self._practical = PracticalVisionFactory(self.registry, self.settings)
        self._rsvlm: Optional[RSVLMVision] = None

    # -- Vision assembly ---------------------------------------------------

    def vision_suite(self) -> VisionSuite:
        """Build the capability bundle for this request.

        Backends are constructed here but models are still not loaded; the
        first actual forward pass triggers the download or the disk read.
        """
        status = self.registry.status()
        practical_ok = bool(status["practical"]["available"])
        strong_ok = bool(status["rsvlm"]["available"])

        embedder = self._practical.embedder() if practical_ok else None
        captioner = self._practical.captioner() if practical_ok else None
        answerer = self._practical.answerer() if practical_ok else None

        strong = None
        if strong_ok:
            if self._rsvlm is None:
                self._rsvlm = (
                    GeoChatVision(self.settings)
                    if self.settings.rsvlm_kind == "geochat"
                    else RSVLMVision(self.registry, self.settings)
                )
            strong = self._rsvlm

        if embedder is None and strong is None:
            raise ResourceNotConfiguredError(
                "SatQuery has no vision backend available, so it cannot answer questions "
                "about imagery. It will not guess from the query text alone.",
                remediation=[
                    "Install the practical stack: pip install torch transformers",
                    "The default models download on first use: "
                    f"{self.settings.caption_model}, {self.settings.vqa_model}, "
                    f"{self.settings.clip_model}",
                    "Or point SATQUERY_RSVLM_PATH at a remote-sensing VLM checkpoint and set "
                    "SATQUERY_RSVLM_ENABLED=true.",
                    "See .env.example for the full list of settings.",
                ],
                context={"backends": status},
            )

        return VisionSuite(
            embedder=embedder, captioner=captioner, answerer=answerer, strong=strong
        )

    # -- Ingestion ---------------------------------------------------------

    def ingest(
        self,
        *,
        uploads: Optional[Sequence[Tuple[str, bytes]]] = None,
        image_paths: Optional[Sequence[str]] = None,
        modality_hint: Optional[Modality] = None,
    ) -> List[LoadedImage]:
        """Load every supplied image and attach its modality."""
        images: List[LoadedImage] = []

        for filename, payload in uploads or []:
            images.append(
                load_image_from_bytes(payload, filename, self.settings, source="upload")
            )
        for path in image_paths or []:
            images.append(load_image_from_path(path, self.settings))

        if len(images) > 8:
            raise QueryError(
                f"{len(images)} images were supplied; the limit is 8 per request.",
                remediation=["Send fewer images, or split the analysis across requests."],
            )

        return [apply_modality(image, modality_hint) for image in images]

    # -- Execution ---------------------------------------------------------

    def answer(
        self,
        query: str,
        *,
        uploads: Optional[Sequence[Tuple[str, bytes]]] = None,
        image_paths: Optional[Sequence[str]] = None,
        modality_hint: Optional[Modality] = None,
        force_tool: Optional[ToolName] = None,
        include_trace: bool = True,
    ) -> QueryResponse:
        request_id = f"sq-{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        trace: List[TraceStep] = []
        warnings: List[str] = []

        # 1. Ingest -------------------------------------------------------
        step_started = time.perf_counter()
        images = self.ingest(
            uploads=uploads, image_paths=image_paths, modality_hint=modality_hint
        )
        if not images:
            raise QueryError(
                "No image was supplied, and SatQuery answers questions about imagery rather "
                "than from general knowledge.",
                remediation=[
                    "Attach at least one image file to the request.",
                    "Or pass image_paths if the file is already on the server.",
                ],
            )
        trace.append(
            TraceStep(
                step="ingest",
                kind="io",
                status=StepStatus.OK,
                latency_ms=_elapsed(step_started),
                detail=(
                    f"{len(images)} image(s) decoded and normalised: "
                    + ", ".join(
                        f"{image.filename} {image.width}x{image.height} "
                        f"{image.modality.value}"
                        for image in images
                    )
                ),
            )
        )
        for image in images:
            if image.was_resized:
                warnings.append(
                    f"{image.filename} was downsampled from "
                    f"{image.original_size[0]}x{image.original_size[1]} to "
                    f"{image.width}x{image.height} to fit SATQUERY_MAX_IMAGE_PX."
                )

        # 2. Route --------------------------------------------------------
        step_started = time.perf_counter()
        plan = self.router.route(query, image_count=len(images), force_tool=force_tool)
        route_latency = _elapsed(step_started)

        # 3. Backends -----------------------------------------------------
        step_started = time.perf_counter()
        scientific = plan.intent in {
            Intent.EO_INSPECTION,
            Intent.RASTER_STATISTICS,
            Intent.SPECTRAL_INDEX,
        }
        vision = VisionSuite(None, None, None, None) if scientific else self.vision_suite()
        trace.append(
            TraceStep(
                step="backend_selection",
                kind="setup",
                status=StepStatus.OK,
                latency_ms=_elapsed(step_started),
                backend=vision.active_kind.value,
                detail=_describe_backends(vision),
            )
        )
        trace.append(
            TraceStep(
                step="intent_router",
                kind="reasoning",
                status=StepStatus.OK,
                latency_ms=route_latency,
                backend=plan.router,
                detail=(
                    f"{plan.intent.value} (confidence {plan.confidence:.2f}) - {plan.rationale}"
                    + (f" Target: '{plan.target}'." if plan.target else "")
                ),
            )
        )

        # 4. Execute ------------------------------------------------------
        context = ToolContext(
            query=query,
            images=images,
            settings=self.settings,
            vision=vision,
            cache=self.cache,
            target=plan.target,
            warnings=warnings,
        )
        results: List[ToolResult] = []
        executed: List[ToolName] = []

        def invoke(tool_name: ToolName, arguments: Dict[str, Any]) -> ToolResult:
            """Nested tool invocation, traced like any top-level step."""
            return self._execute_tool(
                tool_name,
                context,
                arguments,
                trace=trace,
                executed=executed,
                nested=True,
            )

        context.invoke = invoke

        primary_step = plan.steps[0]
        primary_result = self._execute_tool(
            primary_step.tool,
            context,
            dict(primary_step.arguments),
            trace=trace,
            executed=executed,
            nested=False,
        )
        results.append(primary_result)

        # 5. Compose ------------------------------------------------------
        step_started = time.perf_counter()
        answer = self._compose_answer(plan, primary_result, context)
        trace.append(
            TraceStep(
                step="answer_composer",
                kind="reasoning",
                status=StepStatus.OK,
                latency_ms=_elapsed(step_started),
                detail=f"{len(answer)} characters assembled from tool output.",
            )
        )

        total_latency = _elapsed(started)
        return QueryResponse(
            request_id=request_id,
            timestamp_utc=utc_now_iso(),
            query=query,
            answer=answer,
            intent=plan.intent,
            # Nested helpers finish before the tool that called them, so raw
            # execution order would report a caption request as scene-first.
            # The capability that answered the question leads.
            tools_used=_unique([primary_step.tool, *executed]),
            backend=primary_result.backend,
            confidence=primary_result.confidence,
            images=[image.to_ref() for image in images],
            results=results,
            plan=plan,
            trace=trace if include_trace else [],
            latency_ms=total_latency,
            warnings=list(context.warnings),
        )

    # -- Tool execution ----------------------------------------------------

    def _execute_tool(
        self,
        tool_name: ToolName,
        context: ToolContext,
        arguments: Dict[str, Any],
        *,
        trace: List[TraceStep],
        executed: List[ToolName],
        nested: bool,
    ) -> ToolResult:
        tool: Optional[Tool] = self.tools.get(tool_name)
        if tool is None:
            raise ToolExecutionError(
                tool_name.value, f"No implementation is registered for {tool_name.value}."
            )

        step_started = time.perf_counter()
        scoped = ToolContext(
            query=context.query,
            images=context.images,
            settings=context.settings,
            vision=context.vision,
            cache=context.cache,
            target=arguments.get("target", context.target),
            arguments=dict(arguments),
            warnings=context.warnings,
            invoke=context.invoke,
        )

        try:
            tool.validate(scoped)
            result = tool.run(scoped)
        except SatQueryError as exc:
            trace.append(
                TraceStep(
                    step=f"tool.{tool_name.value}",
                    kind="vision",
                    status=StepStatus.FAILED,
                    latency_ms=_elapsed(step_started),
                    detail=exc.message,
                    error=exc.code,
                )
            )
            raise
        except Exception as exc:  # unexpected tool fault
            trace.append(
                TraceStep(
                    step=f"tool.{tool_name.value}",
                    kind="vision",
                    status=StepStatus.FAILED,
                    latency_ms=_elapsed(step_started),
                    detail=str(exc),
                    error=exc.__class__.__name__,
                )
            )
            raise ToolExecutionError(
                tool_name.value,
                f"{tool_name.value} failed: {exc}",
                remediation=[
                    "Check the server log for the full traceback.",
                    "If this is a memory error, lower SATQUERY_MAX_IMAGE_PX or "
                    "SATQUERY_BATCH_SIZE.",
                ],
            ) from exc

        executed.append(tool_name)
        trace.append(
            TraceStep(
                step=f"tool.{tool_name.value}" + (" (nested)" if nested else ""),
                kind="vision",
                status=StepStatus.OK,
                latency_ms=_elapsed(step_started),
                backend=result.backend.value,
                model=result.model,
                detail=_truncate(result.summary, 220),
            )
        )
        return result

    # -- Answer composition ------------------------------------------------

    @staticmethod
    def _compose_answer(
        plan: QueryPlan, result: ToolResult, context: ToolContext
    ) -> str:
        """Turn the tool output into the user-facing answer.

        Everything here is assembled from values the tools actually computed.
        No sentence in the answer exists that is not backed by a measurement.
        """
        parts: List[str] = [result.summary.strip()]

        if plan.intent is Intent.CHANGE_DETECTION and len(context.images) < 2:
            parts.append(
                "Only one image was supplied, so this is a single-epoch reading rather than a "
                "comparison."
            )

        if context.warnings:
            parts.append("Notes: " + " ".join(context.warnings))

        return "\n\n".join(part for part in parts if part)

    # -- Introspection -----------------------------------------------------

    def capabilities(self) -> List[CapabilityInfo]:
        status = self.registry.status()
        practical_ok = bool(status["practical"]["available"])
        strong_ok = bool(status["rsvlm"]["available"])
        practical_ready = bool(status["practical"].get("ready"))
        strong_ready = bool(status["rsvlm"].get("ready"))

        infos: List[CapabilityInfo] = []
        for tool_name, (intent, description, required) in CAPABILITY_DOCS.items():
            if tool_name in {ToolName.EO_INSPECTION, ToolName.RASTER_STATISTICS, ToolName.SPECTRAL_INDEX}:
                infos.append(
                    CapabilityInfo(
                        tool=tool_name,
                        intent=intent,
                        description=description,
                        requires_images=required,
                        backend_preference=[BackendKind.NONE],
                        available=True,
                    )
                )
                continue
            # Grounding, scene, and counting are CLIP-shaped: a generative-only
            # strong backend cannot stand in for an embedder.
            needs_embedder = tool_name in {
                ToolName.SCENE,
                ToolName.GROUNDING,
                ToolName.COUNTING,
            }
            if needs_embedder:
                available = practical_ready and status["practical"].get("loaded", []).count("clip") > 0
                reason = None if available else "CLIP is not warmed and ready; run `python -m satquery warmup`."
                preference = [BackendKind.PRACTICAL]
            elif tool_name is ToolName.MODALITY:
                available = practical_ready and status["practical"].get("loaded", []).count("clip") > 0
                reason = None if available else "The practical CLIP backend is not warmed and ready."
                preference = [BackendKind.PRACTICAL]
            else:
                available = strong_ready or practical_ready
                reason = None if available else "A required vision backend is not warmed and ready."
                preference = (
                    [BackendKind.RSVLM, BackendKind.PRACTICAL]
                    if strong_ok
                    else [BackendKind.PRACTICAL]
                )

            infos.append(
                CapabilityInfo(
                    tool=tool_name,
                    intent=intent,
                    description=description,
                    requires_images=required,
                    backend_preference=preference,
                    available=available,
                    unavailable_reason=reason,
                )
            )
        return infos

    def health(self) -> Dict[str, Any]:
        from .registry import probe_dependencies

        status = self.registry.status()
        dependencies = probe_dependencies()
        ready = bool(status["practical"].get("ready") or status["rsvlm"].get("ready"))

        actions: List[str] = []
        if not dependencies.get("torch", {}).get("installed"):
            actions.append(
                "pip install torch  (use the CUDA wheel matching your driver for GPU inference)"
            )
        if not dependencies.get("transformers", {}).get("installed"):
            actions.append("pip install transformers")
        if status["practical"]["available"] and not status["practical"].get("ready"):
            actions.append("Run `python -m satquery warmup` to load and verify the practical models.")
        if ready and not status["rsvlm"]["available"]:
            actions.append(
                "Optional: set SATQUERY_RSVLM_PATH and SATQUERY_RSVLM_ENABLED=true to enable "
                "the stronger remote-sensing VLM path."
            )
        if not status["planner_llm"]["available"]:
            actions.append(
                "Optional: set OPENAI_API_KEY to enable LLM planning for ambiguous queries. "
                "Rule-based routing works without it."
            )

        return {
            "status": "ready" if ready else "degraded",
            "device": status["device"],
            "backends": status,
            "dependencies": dependencies,
            "ready": ready,
            "setup_actions": actions,
            "cache": self.cache.stats(),
        }

    def warmup(self) -> Dict[str, Any]:
        """Force model loading now rather than on the first user request."""
        loaded: List[str] = []
        errors: Dict[str, str] = {}
        started = time.perf_counter()

        status = self.registry.status()
        if status["practical"]["available"]:
            for name, loader in (
                ("clip", self.registry.clip),
                ("captioner", self.registry.captioner),
                ("vqa", self.registry.vqa),
            ):
                try:
                    loader()
                    loaded.append(name)
                except SatQueryError as exc:
                    errors[name] = exc.message
                except Exception as exc:
                    errors[name] = str(exc)
        if status["rsvlm"]["available"]:
            try:
                self.registry.rsvlm()
                loaded.append("rsvlm")
            except SatQueryError as exc:
                errors["rsvlm"] = exc.message
            except Exception as exc:
                errors["rsvlm"] = str(exc)

        final_status = self.registry.status()

        return {
            "loaded": loaded,
            "errors": errors,
            "ready": bool(
                final_status["practical"].get("ready")
                or final_status["rsvlm"].get("ready")
            ),
            "device": self.registry.resolve_device(),
            "elapsed_s": round(time.perf_counter() - started, 2),
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _unique(items: Sequence[ToolName]) -> List[ToolName]:
    seen: List[ToolName] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _truncate(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "\u2026"


def _describe_backends(vision: VisionSuite) -> str:
    described = vision.describe()
    active = described["active"]
    if vision.has_strong:
        return (
            f"Strong remote-sensing VLM active ({described['strong']}); CLIP "
            f"{'available' if vision.has_embedder else 'unavailable'} for grounding and "
            f"classification. Mode: {active}."
        )
    return (
        f"Practical path active - captioner {described['captioner']}, answerer "
        f"{described['answerer']}, embedder {described['embedder']}. Mode: {active}."
    )
