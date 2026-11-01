"""Prefixed opaque identifiers. Prefixes make logs and payloads self-describing."""

from typing import NewType
from uuid import uuid4

SessionId = NewType("SessionId", str)
ConversationId = NewType("ConversationId", str)
MessageId = NewType("MessageId", str)
RunId = NewType("RunId", str)
InvocationId = NewType("InvocationId", str)
TaskId = NewType("TaskId", str)
AssetId = NewType("AssetId", str)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
