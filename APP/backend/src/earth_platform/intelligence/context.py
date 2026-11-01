from math import ceil

from earth_platform.engine.models import EngineAgentSession
from earth_platform.intelligence.models import ContextMessage, ConversationContext


def estimate_tokens(text: str) -> int:
    """Conservative provider-neutral estimate; no tokenizer is implied."""
    return ceil(len(text.encode("utf-8")) / 4)


class ConversationContextBuilder:
    def build(
        self,
        transcript: EngineAgentSession,
        *,
        history_limit: int,
        token_budget: int,
    ) -> ConversationContext:
        eligible = [
            ContextMessage(role=message.role, content=message.content)
            for message in transcript.messages
            if message.role in {"user", "assistant", "tool"}
        ]
        source = eligible[-history_limit:] if history_limit else []
        limited_message_count = len(eligible) - len(source)

        budget = max(0, token_budget)
        recent: list[ContextMessage] = []
        used = 0
        for message in reversed(source):
            message_tokens = estimate_tokens(message.content) + 2
            if used + message_tokens > budget:
                break
            recent.append(message)
            used += message_tokens
        recent.reverse()

        retained_start = len(source) - len(recent)
        older = source[:retained_start]
        summary_parts: list[str] = []
        for message in older:
            excerpt = message.content.strip().replace("\n", " ")
            if len(excerpt) > 160:
                excerpt = excerpt[:157].rstrip() + "..."
            if excerpt:
                summary_parts.append(f"{message.role}: {excerpt}")

        summary: str | None = None
        if summary_parts:
            summary = "Earlier transcript excerpts: " + " | ".join(summary_parts)
            summary_tokens = estimate_tokens(summary) + 2
            if summary_tokens <= budget - used:
                used += summary_tokens
            else:
                summary = None

        return ConversationContext(
            messages=recent,
            compressed_summary=summary,
            omitted_message_count=limited_message_count + (len(older) if summary is None else 0),
            estimated_tokens=used,
        )
