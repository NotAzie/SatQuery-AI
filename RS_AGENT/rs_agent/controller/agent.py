"""Central controller for SatQuery AI."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Literal

from langchain import hub
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain.tools import Tool
from langchain_core.agents import AgentAction
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from rs_agent.controller.prompts import TASK_TYPE_PROMPT, TASK_TYPE_PROMPT_RSCHATGPT, TASK_TYPES, TASK_TYPES_RSCHATGPT
from rs_agent.solution_space.retriever import SolutionRetriever
from rs_agent.task_types import match_task_type
from rs_agent.toolkit.registry import TASK_TO_TOOL, TASK_TO_TOOL_RSCHATGPT

AgentMode = Literal["full", "baseline", "task_inference_only", "solution_retrieval_only"]
ToolkitType = Literal["rsagent", "rschatgpt"]


class SatQueryAI:
    """Efficient LLM controller retaining the original RS-Agent public workflow."""

    def __init__(self, llm: BaseChatModel, tools: list[Tool], solution_retriever: SolutionRetriever | None = None,
                 mode: AgentMode = "full", toolkit: ToolkitType = "rsagent", verbose: bool = False) -> None:
        self.llm, self.tools, self.solution_retriever = llm, tools, solution_retriever
        self.mode, self.toolkit, self.verbose = mode, toolkit, verbose
        self.task_type_prompt = TASK_TYPE_PROMPT if toolkit == "rsagent" else TASK_TYPE_PROMPT_RSCHATGPT
        self.task_types = TASK_TYPES if toolkit == "rsagent" else TASK_TYPES_RSCHATGPT
        self.task_to_tool = TASK_TO_TOOL if toolkit == "rsagent" else TASK_TO_TOOL_RSCHATGPT
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._task_cache: OrderedDict[str, str] = OrderedDict()
        self._executors: dict[tuple[str, ...], AgentExecutor] = {}
        self._prompt = None

    @classmethod
    def from_config(cls, config: dict[str, Any], tools: list[Tool] | None = None,
                    toolkit: ToolkitType = "rsagent") -> "SatQueryAI":
        from rs_agent.config import resolve_path
        from rs_agent.toolkit.registry import get_stub_tools

        llm_cfg, agent_cfg = config["llm"], config.get("agent", {})
        mode: AgentMode = agent_cfg.get("mode", "full")
        llm_kwargs: dict[str, Any] = {"model": llm_cfg["model"], "temperature": llm_cfg.get("temperature", 0)}
        if llm_cfg.get("api_key"):
            llm_kwargs["api_key"] = llm_cfg["api_key"]
        if llm_cfg.get("api_base"):
            llm_kwargs["base_url"] = llm_cfg["api_base"]
        if not llm_kwargs.get("api_key"):
            raise ValueError("No LLM API key is set. Copy .env.example to .env and configure your provider key.")

        retriever = None
        if mode in ("full", "solution_retrieval_only"):
            sol_cfg = config["solution_space"]
            source = "data/solutions/guidance_rschatgpt.txt" if toolkit == "rschatgpt" else sol_cfg["source_file"]
            index = "data/indices/solution_db_rschatgpt" if toolkit == "rschatgpt" else sol_cfg["index_dir"]
            retriever = SolutionRetriever(
                index_dir=resolve_path(index), source_file=resolve_path(source),
                embedding_model=config["embedding"]["model"], device=config["embedding"]["device"],
                top_k=sol_cfg.get("top_k", 1),
            )
        return cls(ChatOpenAI(**llm_kwargs), tools or get_stub_tools(toolkit), retriever, mode, toolkit, agent_cfg.get("verbose", False))

    def infer_task_type(self, question: str) -> str:
        """Classify once per distinct question and accept only known task labels."""
        cached = self._task_cache.get(question)
        if cached:
            self._task_cache.move_to_end(question)
            return cached
        response = self.llm.invoke(self.task_type_prompt.format(question=question))
        task = match_task_type(str(response.content), self.task_types)
        if not task:
            return str(response.content).strip()
        self._task_cache[question] = task
        if len(self._task_cache) > 256:
            self._task_cache.popitem(last=False)
        return task

    def retrieve_guidance(self, question: str, predicted_task_type: str | None) -> str | None:
        if not self.solution_retriever:
            return None
        if self.mode == "solution_retrieval_only":
            return self.solution_retriever.retrieve_by_query(question)
        return self.solution_retriever.retrieve(predicted_task_type) if self.mode == "full" and predicted_task_type else None

    def build_input(self, question: str, image_path: str, guidance: str | None, predicted_task_type: str | None) -> str:
        base = f"{question} The image path is {image_path}."
        if self.mode == "task_inference_only" and predicted_task_type:
            return f"{base} Task type: {predicted_task_type}."
        return f"{base} Guidance: {guidance}" if guidance else base

    def _executor_for(self, tools: list[Tool]) -> AgentExecutor:
        key = tuple(tool.name for tool in tools)
        if key not in self._executors:
            # Hub access happens only for genuinely ambiguous fallback requests.
            self._prompt = self._prompt or hub.pull("hwchase17/structured-chat-agent")
            agent = create_structured_chat_agent(self.llm, tools, self._prompt)
            self._executors[key] = AgentExecutor(agent=agent, tools=tools, verbose=self.verbose,
                                                 return_intermediate_steps=True)
        return self._executors[key]

    def _direct_tool_result(self, tool_name: str, question: str, image_path: str) -> dict[str, Any] | None:
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            return None
        tool_input = question if tool_name == "knowledge_search" else image_path
        result = tool.invoke(tool_input)
        return {"output": result, "intermediate_steps": [(AgentAction(tool=tool_name, tool_input=tool_input,
                log="Deterministic task-to-tool route."), result)]}

    def run(self, question: str, image_path: str) -> dict[str, Any]:
        """Execute the workflow, using direct single-tool routes when unambiguous."""
        predicted = None if self.mode == "baseline" else self.infer_task_type(question) if self.mode != "solution_retrieval_only" else None
        guidance = self.retrieve_guidance(question, predicted) if self.mode in ("full", "solution_retrieval_only") else None
        known_tool = self.task_to_tool.get(predicted or "")
        # All shipped task templates specify exactly one tool. Avoid a second LLM call.
        direct = self._direct_tool_result(known_tool, question, image_path) if known_tool and self.mode != "baseline" else None
        if direct is None:
            selected = [self._tools_by_name[known_tool]] if known_tool in self._tools_by_name else self.tools
            direct = self._executor_for(selected).invoke({"input": self.build_input(question, image_path, guidance, predicted)})
        return {"predicted_task_type": predicted, "guidance": guidance, "output": direct.get("output"),
                "intermediate_steps": direct.get("intermediate_steps", [])}


# Backward-compatible import for existing integrations.
RSAgent = SatQueryAI
