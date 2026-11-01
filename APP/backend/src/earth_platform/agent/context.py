import asyncio
from dataclasses import dataclass, field

from earth_platform.earth.state import EarthContext
from earth_platform.sessions.models import InvestigationContext


@dataclass
class RunContext:
    """Ambient information for one agent run, passed to tool sources."""

    run_id: str
    session_id: str
    conversation_id: str
    investigation: InvestigationContext
    earth: EarthContext | None = None
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
