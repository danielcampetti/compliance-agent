"""CRUD endpoints for conversation memory: /conversations/*"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.api.auth import TokenUser, get_current_user
from src.services.conversation import ConversationService

conversation_router = APIRouter(prefix="/conversations", tags=["conversations"])
_svc = ConversationService()


class CreateConversationRequest(BaseModel):
    title: Optional[str] = None


class RenameTitleRequest(BaseModel):
    title: str


@conversation_router.get("")
async def list_conversations(
    current_user: TokenUser = Depends(get_current_user),
) -> dict:
    """List the current user's conversations, newest first."""
    return {"conversations": _svc.list_by_user(current_user.user_id)}


@conversation_router.post("", status_code=201)
async def create_conversation(
    body: Optional[CreateConversationRequest] = None,
    current_user: TokenUser = Depends(get_current_user),
) -> dict:
    """Create a new conversation. Returns new conversation dict."""
    title = (body.title if body and body.title else None) or "Nova conversa"
    return _svc.create(current_user.user_id, title)


@conversation_router.get("/{conv_id}")
async def get_conversation(
    conv_id: int,
    current_user: TokenUser = Depends(get_current_user),
) -> dict:
    """Return conversation metadata + all messages. 404 if not owned by current user."""
    conv = _svc.get_by_id(conv_id, current_user.user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    messages = _svc.get_messages(conv_id, current_user.user_id)
    return {"conversation": conv, "messages": messages}


@conversation_router.delete("/{conv_id}", status_code=204, response_class=Response)
async def delete_conversation(
    conv_id: int,
    current_user: TokenUser = Depends(get_current_user),
) -> Response:
    """Soft-delete a conversation. 404 if not found or not owned by current user."""
    if not _svc.delete(conv_id, current_user.user_id):
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    return Response(status_code=204)


@conversation_router.patch("/{conv_id}/title")
async def rename_conversation(
    conv_id: int,
    body: RenameTitleRequest,
    current_user: TokenUser = Depends(get_current_user),
) -> dict:
    """Rename a conversation. 404 if not found or not owned by current user."""
    if not _svc.update_title(conv_id, current_user.user_id, body.title):
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    return {"ok": True}
