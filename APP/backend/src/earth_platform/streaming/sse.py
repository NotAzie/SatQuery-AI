"""Server-Sent Events framing for the versioned agent event contract."""

import json

from earth_platform.agent.events import AgentEvent
from earth_platform.streaming.messages import ControlMessage


class SSEEventEncoder:
    content_type = "text/event-stream"

    def encode(self, item: AgentEvent | ControlMessage) -> bytes:
        payload = json.dumps(item.model_dump(mode="json"), separators=(",", ":"))
        fields = [f"data: {payload}"]
        seq = getattr(item, "seq", None)
        if seq is not None:
            fields.insert(0, f"id: {seq}")
        return ("\n".join(fields) + "\n\n").encode("utf-8")

    def heartbeat(self) -> bytes:
        return b": keep-alive\n\n"
