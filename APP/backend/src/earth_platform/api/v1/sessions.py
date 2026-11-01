"""Session and conversation lifecycle endpoints."""

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel

from earth_platform.api.deps import SessionStoreDep
from earth_platform.sessions.models import Conversation, Session
from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import EarthWorkspaceState
from earth_platform.shared.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSession(BaseModel):
    title: str | None = None


class CreateConversation(BaseModel):
    title: str | None = None


class UpdateSession(BaseModel):
    title: str | None = None
    archived: bool | None = None
    earth_workspace: EarthWorkspaceState | None = None


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSession, store: SessionStoreDep) -> Session:
    session = Session(title=body.title)
    return await store.sessions.create(session)


@router.get("", response_model=list[Session])
async def list_sessions(
    store: SessionStoreDep,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Session]:
    return await store.sessions.list(include_archived=include_archived, limit=limit)


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: str, store: SessionStoreDep) -> Session:
    return await store.sessions.get(session_id)


@router.patch("/{session_id}", response_model=Session)
async def update_session(
    session_id: str,
    body: UpdateSession,
    store: SessionStoreDep,
) -> Session:
    session = await store.sessions.get(session_id)
    if "title" in body.model_fields_set:
        session.title = body.title
    if "archived" in body.model_fields_set and body.archived is not None:
        session.archived = body.archived
    if "earth_workspace" in body.model_fields_set and body.earth_workspace is not None:
        session.earth_workspace = body.earth_workspace
    session.updated_at = utcnow()
    return await store.sessions.update(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, store: SessionStoreDep) -> Response:
    session = await store.sessions.get(session_id)
    if session.engine_agent_session_id is not None:
        raise ConflictError(
            "This session has an Engine-owned transcript; archive it instead of deleting it "
            "until the Engine Agent API supports session deletion."
        )
    await store.sessions.delete(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}/conversations", response_model=list[Conversation])
async def list_conversations(
    session_id: str,
    store: SessionStoreDep,
) -> list[Conversation]:
    await store.sessions.get(session_id)
    return await store.conversations.list_for_session(session_id)


@router.post(
    "/{session_id}/conversations",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    session_id: str,
    body: CreateConversation,
    store: SessionStoreDep,
) -> Conversation:
    await store.sessions.get(session_id)
    conversation = Conversation(session_id=session_id, title=body.title)
    return await store.conversations.create(conversation)


@router.get("/{session_id}/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    session_id: str,
    conversation_id: str,
    store: SessionStoreDep,
) -> Conversation:
    conversation = await store.conversations.get(conversation_id)
    if conversation.session_id != session_id:
        raise NotFoundError(f"Conversation '{conversation_id}' was not found")
    return conversation
