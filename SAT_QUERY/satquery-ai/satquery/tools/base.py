"""Tool abstraction and shared execution context."""

from __future__ import annotations

import abc
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..backends.base import VisionSuite
from ..config import Settings
from ..errors import QueryError
from ..imaging import LoadedImage, image_digest
from ..schemas import BackendKind, Modality, ToolName, ToolResult


class ResultCache:
    """Small LRU cache keyed on (image set, tool, arguments).

    Tools call each other - captioning wants the scene classes, counting wants
    the grounding regions - so within a single request the same work is often
    requested twice. Caching across requests also matters at a demo booth,
    where the same image gets asked three questions in a row.
    """

    def __init__(self, maxsize: int = 128) -> None:
        self.maxsize = max(int(maxsize), 0)
        self._store: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        if self.maxsize == 0:
            return None
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self.hits += 1
                return self._store[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        if self.maxsize == 0:
            return
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self.maxsize:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"size": len(self._store), "hits": self.hits, "misses": self.misses}


@dataclass
class ToolContext:
    """Everything a tool needs to do its job."""

    query: str
    images: List[LoadedImage]
    settings: Settings
    vision: VisionSuite
    cache: ResultCache
    target: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    invoke: Optional[Callable[[ToolName, Dict[str, Any]], ToolResult]] = None

    @property
    def primary(self) -> LoadedImage:
        if not self.images:
            raise QueryError(
                "This capability needs at least one image.",
                remediation=["Attach an image file, or pass image_paths in the request body."],
            )
        return self.images[0]

    @property
    def modality(self) -> Modality:
        return self.primary.modality

    @property
    def modality_name(self) -> str:
        return self.primary.modality.value

    def digest(self) -> str:
        return image_digest(self.images)

    def cache_key(self, tool: ToolName, *parts: Any) -> str:
        pieces = [self.digest(), tool.value, *[str(part) for part in parts]]
        return "|".join(pieces)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def run_tool(self, tool: ToolName, **arguments: Any) -> ToolResult:
        """Invoke a sibling tool through the orchestrator, sharing the cache."""
        if self.invoke is None:
            raise RuntimeError("ToolContext.invoke was not wired by the orchestrator")
        return self.invoke(tool, arguments)


class Tool(abc.ABC):
    """A specialist capability."""

    name: ToolName
    description: str = ""
    min_images: int = 1
    max_images: int = 1

    @abc.abstractmethod
    def run(self, context: ToolContext) -> ToolResult:
        """Execute against real imagery and return a structured result."""

    def validate(self, context: ToolContext) -> None:
        """Check preconditions before any model is touched."""
        count = len(context.images)
        if count < self.min_images:
            noun = "image" if self.min_images == 1 else "images"
            raise QueryError(
                f"{self.name.value} needs at least {self.min_images} {noun}, "
                f"but {count} were supplied.",
                remediation=self._image_remediation(),
                context={"tool": self.name.value, "supplied": count, "required": self.min_images},
            )

    def _image_remediation(self) -> List[str]:
        if self.min_images >= 2:
            return [
                "Upload both epochs in the same request, oldest first.",
                "The two scenes should cover the same footprint and be co-registered.",
            ]
        return ["Attach an image file, or pass image_paths in the request body."]

    # -- helpers for subclasses -------------------------------------------

    @staticmethod
    def timed(started: float) -> float:
        return round((time.perf_counter() - started) * 1000.0, 3)

    def result(
        self,
        *,
        summary: str,
        started: float,
        backend: BackendKind = BackendKind.PRACTICAL,
        model: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        regions: Optional[Sequence[Any]] = None,
        labels: Optional[Sequence[Any]] = None,
        confidence: Optional[float] = None,
        warnings: Optional[Sequence[str]] = None,
        ok: bool = True,
    ) -> ToolResult:
        return ToolResult(
            tool=self.name,
            ok=ok,
            summary=summary,
            latency_ms=self.timed(started),
            backend=backend,
            model=model,
            data=dict(data or {}),
            regions=list(regions or []),
            labels=list(labels or []),
            confidence=confidence,
            warnings=list(warnings or []),
        )
