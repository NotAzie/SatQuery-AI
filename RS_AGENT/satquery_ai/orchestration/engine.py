"""The SatQuery AI query engine: understand, enrich, route, and answer."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Literal

from langchain import hub
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.tools import Tool
from langchain_core.agents import AgentAction
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from satquery_ai.guidance import GuidanceStore
from satquery_ai.orchestration.prompts import TASK_LABELS, TASK_UNDERSTANDING_PROMPT
from satquery_ai.task_catalog import match_task
from satquery_ai.tools import TASK_TO_CAPABILITY, get_capabilities

ExecutionMode = Literal["full", "baseline", "task_inference_only", "solution_retrieval_only"]


class SatQueryEngine:
    """Coordinate question understanding, guidance, capability routing, and response."""

    def __init__(self, llm: BaseChatModel, capabilities: list[Tool], guidance: GuidanceStore | None = None,
                 mode: ExecutionMode = "full", verbose: bool = False) -> None:
        self.llm, self.capabilities, self.guidance = llm, capabilities, guidance
        self.mode, self.verbose = mode, verbose
        self._capabilities_by_name = {capability.name: capability for capability in capabilities}
        self._understanding_cache: OrderedDict[str, str] = OrderedDict()
        self._fallback_engines: dict[tuple[str, ...], AgentExecutor] = {}
        self._fallback_prompt = None

    @classmethod
    def from_config(cls, config: dict[str, Any], capabilities: list[Tool] | None = None) -> "SatQueryEngine":
        from satquery_ai.configuration import resolve_path

        llm_config, runtime_config = config["llm"], config.get("agent", {})
        llm_kwargs: dict[str, Any] = {"model": llm_config["model"], "temperature": llm_config.get("temperature", 0)}
        if llm_config.get("api_key"):
            llm_kwargs["api_key"] = llm_config["api_key"]
        if llm_config.get("api_base"):
            llm_kwargs["base_url"] = llm_config["api_base"]
        if not llm_kwargs.get("api_key"):
            raise ValueError("No LLM API key is set. Configure the provider key before starting SatQuery AI.")

        guidance = None
        if runtime_config.get("mode", "full") in ("full", "solution_retrieval_only"):
            guidance_config = config["solution_space"]
            guidance = GuidanceStore(
                index_dir=resolve_path(guidance_config["index_dir"]),
                source_file=resolve_path(guidance_config["source_file"]),
                embedding_model=config["embedding"]["model"],
                device=config["embedding"]["device"],
                top_k=guidance_config.get("top_k", 1),
            )
        return cls(
            ChatOpenAI(**llm_kwargs), capabilities or get_capabilities(), guidance,
            runtime_config.get("mode", "full"), runtime_config.get("verbose", False),
        )

    def understand(self, question: str) -> str:
        cached = self._understanding_cache.get(question)
        if cached:
            self._understanding_cache.move_to_end(question)
            return cached
        response = self.llm.invoke(TASK_UNDERSTANDING_PROMPT.format(question=question))
        task = match_task(str(response.content), TASK_LABELS) or str(response.content).strip()
        self._understanding_cache[question] = task
        if len(self._understanding_cache) > 256:
            self._understanding_cache.popitem(last=False)
        return task

    def _guidance_for(self, question: str, task: str | None) -> str | None:
        if not self.guidance:
            return None
        if self.mode == "solution_retrieval_only":
            return self.guidance.for_question(question)
        return self.guidance.for_task(task) if self.mode == "full" and task else None

    def _fallback_for(self, capabilities: list[Tool]) -> AgentExecutor:
        key = tuple(capability.name for capability in capabilities)
        if key not in self._fallback_engines:
            self._fallback_prompt = self._fallback_prompt or hub.pull("hwchase17/structured-chat-agent")
            agent = create_structured_chat_agent(self.llm, capabilities, self._fallback_prompt)
            self._fallback_engines[key] = AgentExecutor(
                agent=agent, tools=capabilities, verbose=self.verbose, return_intermediate_steps=True,
            )
        return self._fallback_engines[key]

    def run(self, question: str, image_path: str) -> dict[str, Any]:
        """Run one query through understanding, guidance, routing, and answer generation."""
        task = None if self.mode == "baseline" else self.understand(question) if self.mode != "solution_retrieval_only" else None
        guidance = self._guidance_for(question, task) if self.mode in ("full", "solution_retrieval_only") else None
        capability_name = TASK_TO_CAPABILITY.get(task or "")
        capability = self._capabilities_by_name.get(capability_name or "")
        if capability and self.mode != "baseline":
            if capability.name == "knowledge_search":
                tool_input = question
            elif capability.name in {"visual_question_answering", "grounding"}:
                tool_input = f"{image_path}\nQuestion: {question}"
            else:
                tool_input = image_path
            output = capability.invoke(tool_input)
            result = {"output": output, "intermediate_steps": [(AgentAction(
                tool=capability.name, tool_input=tool_input, log="SatQuery capability route.",
            ), output)]}
        else:
            selected = [capability] if capability else self.capabilities
            base = f"{question} The image path is {image_path}."
            if self.mode == "task_inference_only" and task:
                base = f"{base} Task type: {task}."
            elif guidance:
                base = f"{base} Guidance: {guidance}"
            result = self._fallback_for(selected).invoke({"input": base})
        return {"predicted_task_type": task, "guidance": guidance, "output": result.get("output"),
                "intermediate_steps": result.get("intermediate_steps", [])}