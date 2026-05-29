"""Chat endpoint — RAG + tool-calling agent."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_chat_agent, invalidate_chat_cache
from backend.schemas import ChatRequest, ChatResponse
from backend.agents.chat import ChatAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    agent: ChatAgent = Depends(get_chat_agent),
) -> ChatResponse:
    try:
        answer = agent.chat(body.message, start_date=body.start, end_date=body.end)
    except Exception as e:
        logger.exception("Chat agent error.")
        raise HTTPException(500, f"Chat agent error: {e}") from e
    return ChatResponse(answer=answer)


@router.post("/reset")
def reset() -> dict:
    """Drop the cached agent so the next chat starts a fresh session and rebuilds the RAG index."""
    invalidate_chat_cache()
    return {"ok": True}
