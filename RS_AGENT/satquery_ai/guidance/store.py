"""Task guidance lookup with an optional lazy vector-store fallback."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from satquery_ai.task_catalog import normalize_task


def _clean(text: str) -> str:
    return " ".join(text.split())


class GuidanceStore:
    """Provide task-specific guidance without eagerly loading embeddings."""

    def __init__(self, index_dir: str | Path, embedding_model: str = "moka-ai/m3e-base",
                 device: str = "cpu", top_k: int = 1, source_file: str | Path | None = None) -> None:
        self.index_dir = Path(index_dir)
        self.embedding_model, self.device = embedding_model, device
        self.top_k = max(1, top_k)
        self.source_file = Path(source_file) if source_file else self._default_source()
        self.guidance_by_task = self._load_guidance(self.source_file)
        self._store = None

    def _default_source(self) -> Path:
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
                entries[normalize_task(match.group(1))] = _clean(block)
        return entries

    @lru_cache(maxsize=64)
    def for_task(self, task_type: str) -> str | None:
        task = normalize_task(task_type)
        return self.guidance_by_task.get(task) or self._search_index(task)

    retrieve = for_task

    @lru_cache(maxsize=128)
    def for_question(self, question: str) -> str | None:
        terms = set(re.findall(r"[a-z0-9]+", question.casefold()))
        if self.guidance_by_task:
            def score(item: tuple[str, str]) -> tuple[int, str]:
                task, guidance = item
                corpus = set(re.findall(r"[a-z0-9]+", f"{task} {guidance}".casefold()))
                return len(terms & corpus), task
            best = max(self.guidance_by_task.items(), key=score)
            if score(best)[0]:
                return best[1]
        return self._search_index(question)

    retrieve_by_query = for_question

    def _search_index(self, query: str) -> str | None:
        if not self.index_dir.exists():
            return None
        if self._store is None:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            from langchain_community.vectorstores import FAISS
            embedder = HuggingFaceEmbeddings(model_name=self.embedding_model, model_kwargs={"device": self.device})
            self._store = FAISS.load_local(str(self.index_dir), embedder, allow_dangerous_deserialization=True)
        results = self._store.similarity_search_with_score(query, k=self.top_k)
        return _clean(min(results, key=lambda item: item[1])[0].page_content) if results else None