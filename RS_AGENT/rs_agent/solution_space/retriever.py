"""Lightweight task-aware retrieval for the Solution Space.

The shipped guidance corpus has one authoritative instruction per task. Loading a
sentence-transformer and searching FAISS for that fixed mapping adds latency without
improving recall, so the normal path is an in-memory lookup. The legacy index is kept
as a lazy fallback for custom corpora.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from rs_agent.task_types import normalize_task_type


def _clean_content(content: str) -> str:
    return " ".join(content.split())


class SolutionRetriever:
    """Retrieve solution guidance without eagerly loading embedding models."""

    def __init__(
        self, index_dir: str | Path, embedding_model: str = "moka-ai/m3e-base",
        device: str = "cpu", top_k: int = 1, source_file: str | Path | None = None,
    ) -> None:
        self.index_dir = Path(index_dir)
        self.embedding_model, self.device = embedding_model, device
        self.top_k = max(1, top_k)
        self.source_file = Path(source_file) if source_file else self._default_source_file()
        self.guidance_by_task = self._load_guidance(self.source_file)
        self._store = None

    def _default_source_file(self) -> Path:
        filename = "guidance_rschatgpt.txt" if "rschatgpt" in self.index_dir.name.lower() else "guidance.txt"
        return self.index_dir.parents[1] / "solutions" / filename

    @staticmethod
    def _load_guidance(source_file: Path) -> dict[str, str]:
        if not source_file.exists():
            return {}
        entries: dict[str, str] = {}
        for block in re.split(r"\n\s*\n", source_file.read_text(encoding="utf-8")):
            match = re.search(r"\[\s*['\"]?([^\]'\"]+)['\"]?\s*\]", block)
            if match:
                entries[normalize_task_type(match.group(1))] = _clean_content(block)
        return entries

    @lru_cache(maxsize=64)
    def retrieve(self, task_type: str) -> str | None:
        """Return exact guidance for a classified task in O(1)."""
        task = normalize_task_type(task_type)
        return self.guidance_by_task.get(task) or self._retrieve_faiss(task)

    @lru_cache(maxsize=128)
    def retrieve_by_query(self, query: str) -> str | None:
        """Use cheap lexical ranking for the raw-query ablation path."""
        query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
        if self.guidance_by_task:
            def score(item: tuple[str, str]) -> tuple[int, str]:
                task, guidance = item
                terms = set(re.findall(r"[a-z0-9]+", f"{task} {guidance}".casefold()))
                return len(query_terms & terms), task

            best = max(self.guidance_by_task.items(), key=score)
            if score(best)[0]:
                return best[1]
        return self._retrieve_faiss(query)

    def _retrieve_faiss(self, query: str) -> str | None:
        """Lazy compatibility fallback for externally supplied guidance indexes."""
        if not self.index_dir.exists():
            return None
        if self._store is None:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            from langchain_community.vectorstores import FAISS
            embedder = HuggingFaceEmbeddings(
                model_name=self.embedding_model, model_kwargs={"device": self.device}
            )
            self._store = FAISS.load_local(
                str(self.index_dir), embedder, allow_dangerous_deserialization=True
            )
        results = self._store.similarity_search_with_score(query, k=self.top_k)
        # FAISS returns L2 distance: lower values are better.
        return _clean_content(min(results, key=lambda item: item[1])[0].page_content) if results else None
