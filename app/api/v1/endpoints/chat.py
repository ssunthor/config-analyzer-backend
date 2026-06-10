import logging

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse
from app.services import chat_service
from typing import Dict

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/chat/stream")
async def chat_stream(
    message: str = Body(..., embed=True),
    context: Dict = Body(default={}, embed=True)
):
    """
    Endpoint for streaming AI chat responses.
    """
    logger.debug(f"POST /chat/stream: message_len={len(message)} context_keys={list(context.keys())}")
    return StreamingResponse(
        chat_service.stream_chat_response(message, context),
        media_type="text/event-stream"
    )
