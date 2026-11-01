"""Frames exchanged on the bidirectional WebSocket, besides ``AgentEvent`` (server -> client).

SSE is server -> client only and carries ``AgentEvent`` plus ``Hello``/``StreamError``; commands
that SSE cannot carry (cancel, camera updates) travel over plain HTTP POSTs instead."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from earth_platform.earth.state import EarthContext
from earth_platform.shared.constants import EVENT_SCHEMA_VERSION


class Subscribe(BaseModel):
    type: Literal["subscribe"] = "subscribe"
    session_id: str
    after_seq: int = 0  # replay everything newer than this, then go live


class Cancel(BaseModel):
    type: Literal["cancel"] = "cancel"
    run_id: str


class UpdateEarthContext(BaseModel):
    type: Literal["earth.context"] = "earth.context"
    context: EarthContext


class Ping(BaseModel):
    type: Literal["ping"] = "ping"


ClientMessage = Annotated[
    Subscribe | Cancel | UpdateEarthContext | Ping, Field(discriminator="type")
]


class Hello(BaseModel):
    type: Literal["hello"] = "hello"
    session_id: str
    latest_seq: int
    schema_version: int = EVENT_SCHEMA_VERSION


class Pong(BaseModel):
    type: Literal["pong"] = "pong"


class StreamError(BaseModel):
    type: Literal["stream.error"] = "stream.error"
    code: str
    message: str


ControlMessage = Annotated[Hello | Pong | StreamError, Field(discriminator="type")]
