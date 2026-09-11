"""Optional knowledge-query connection for SatQuery AI."""

from __future__ import annotations

from typing import Protocol


class KnowledgeEngine(Protocol):
    def query(self, query: str, *args: object, **kwargs: object) -> str: ...


_engine: KnowledgeEngine | None = None


def configure_knowledge(engine: KnowledgeEngine) -> None:
    """Attach an initialized knowledge engine to the application."""
    global _engine
    _engine = engine


def search_knowledge(query: str) -> str:
    """Search the configured knowledge engine through the tool boundary."""
    if _engine is None:
        return "Knowledge service is not initialized. Configure it before knowledge queries."
    return str(_engine.query(query))