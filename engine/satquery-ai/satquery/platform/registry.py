"""Thread-safe component discovery and trusted installed extensions."""

from __future__ import annotations

import importlib.metadata
import threading
from typing import Any, Callable, Dict, Generic, Iterator, TypeVar

from ..errors import ExtensionError
from .datasets import InMemoryDatasetRegistry

T = TypeVar("T")

ENTRY_POINT_GROUPS = {
    "connectors": "satquery.connectors",
    "tools": "satquery.tools",
    "models": "satquery.models",
    "agents": "satquery.agents",
    "reasoners": "satquery.reasoners",
    "visualizers": "satquery.visualizers",
    "evaluators": "satquery.evaluators",
}


class ComponentRegistry(Generic[T]):
    """Explicit, process-local registry; no imports occur during lookup."""

    def __init__(self) -> None:
        self._components: Dict[str, T] = {}
        self._lock = threading.RLock()

    def register(self, name: str, component: T, *, replace: bool = False) -> None:
        key = name.strip()
        if not key:
            raise ExtensionError("A registered component must have a non-empty name.")
        with self._lock:
            if key in self._components and not replace:
                raise ExtensionError(
                    f"Component {key!r} is already registered.",
                    context={"component": key},
                )
            self._components[key] = component

    def get(self, name: str) -> T:
        with self._lock:
            try:
                return self._components[name]
            except KeyError as exc:
                raise ExtensionError(
                    f"Component {name!r} is not registered.",
                    context={"component": name},
                ) from exc

    def unregister(self, name: str) -> T:
        with self._lock:
            try:
                return self._components.pop(name)
            except KeyError as exc:
                raise ExtensionError(
                    f"Component {name!r} is not registered.",
                    context={"component": name},
                ) from exc

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._components))

    def items(self) -> tuple[tuple[str, T], ...]:
        with self._lock:
            return tuple(self._components.items())

    def __contains__(self, name: object) -> bool:
        with self._lock:
            return name in self._components

    def __len__(self) -> int:
        with self._lock:
            return len(self._components)

    def __iter__(self) -> Iterator[str]:
        return iter(self.names())

    def discover_entry_points(
        self,
        group: str,
        build: Callable[[Any], tuple[str, T]],
    ) -> tuple[str, ...]:
        """Load installed extensions using an explicit, caller-owned builder.

        Entry points execute trusted installed Python code in this process.
        A builder receives the loaded entry-point object and returns its
        registration name and configured component instance.
        """
        try:
            entries = importlib.metadata.entry_points()
            selected = entries.select(group=group)
        except Exception as exc:
            raise ExtensionError(
                f"Could not enumerate entry points for group {group!r}: {exc}",
                context={"entry_point_group": group},
            ) from exc

        discovered: list[str] = []
        for entry_point in sorted(selected, key=lambda item: item.name):
            try:
                loaded = entry_point.load()
                name, component = build(loaded)
                self.register(name, component)
            except ExtensionError:
                raise
            except Exception as exc:
                raise ExtensionError(
                    f"Could not load entry point {entry_point.name!r} "
                    f"from group {group!r}: {exc}",
                    context={
                        "entry_point": entry_point.name,
                        "entry_point_group": group,
                    },
                ) from exc
            discovered.append(name)
        return tuple(discovered)


class PlatformRegistries:
    """Independent registries for current and future component categories."""

    def __init__(self) -> None:
        self.models: ComponentRegistry[Any] = ComponentRegistry()
        self.tools: ComponentRegistry[Any] = ComponentRegistry()
        self.connectors: ComponentRegistry[Any] = ComponentRegistry()
        self.agents: ComponentRegistry[Any] = ComponentRegistry()
        self.reasoners: ComponentRegistry[Any] = ComponentRegistry()
        self.visualizers: ComponentRegistry[Any] = ComponentRegistry()
        self.evaluators: ComponentRegistry[Any] = ComponentRegistry()
        self.datasets = InMemoryDatasetRegistry()

    def registry_for(self, category: str) -> ComponentRegistry[Any]:
        if category not in ENTRY_POINT_GROUPS:
            raise ExtensionError(
                f"Unknown component category {category!r}.",
                context={"category": category},
            )
        return getattr(self, category)

    def discover_entry_points(
        self,
        category: str,
        build: Callable[[Any], tuple[str, Any]],
    ) -> tuple[str, ...]:
        registry = self.registry_for(category)
        return registry.discover_entry_points(ENTRY_POINT_GROUPS[category], build)
