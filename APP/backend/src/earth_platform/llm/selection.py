from typing import Protocol

from pydantic import BaseModel

from earth_platform.llm.types import ModelRef


class ModelRequirements(BaseModel):
    vision: bool = False
    tool_calling: bool = False
    reasoning: bool = False
    local_only: bool = False
    min_context_tokens: int | None = None


class ModelSelector(Protocol):
    """Chooses a model satisfying a run's requirements (e.g. an image is attached, so a
    vision-capable model is needed), honouring the user's preference when compatible."""

    async def select(
        self, requirements: ModelRequirements, preferred: ModelRef | None = None
    ) -> ModelRef: ...
