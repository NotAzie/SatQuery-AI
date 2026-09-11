"""Lazy bridge between SatQuery AI and the bundled DualRAG knowledge space."""

from __future__ import annotations

from typing import Protocol


class KnowledgeQueryEngine(Protocol):
    def query(self, query: str, *args: object, **kwargs: object) -> str: ...


_engine: KnowledgeQueryEngine | None = None


def configure_knowledge_space(engine: KnowledgeQueryEngine) -> None:
    """Attach an initialized ``dualrag.lightrag.LightRAG`` instance once at startup."""
    global _engine
    _engine = engine


def knowledge_search(query: str) -> str:
    """Query the configured DualRAG instance through the existing tool interface."""
    if _engine is None:
        return (
            "Knowledge Space is not initialized. Configure the bundled DualRAG "
            "instance with configure_knowledge_space(...) before knowledge queries."
        )
    return str(_engine.query(query))
