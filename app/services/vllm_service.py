import asyncio
import logging
from typing import AsyncGenerator, Dict

from app.core.config import settings
from app.services.llm_interface import vLLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton vLLMClient — built at import time; fails fast if Keycloak is
# not configured (Keycloak-only auth, no static token fallback).
# ---------------------------------------------------------------------------

def _build_client() -> vLLMClient:
    missing = [v for v in ("LLM_AUTH_URL", "LLM_CLIENT_ID", "LLM_CLIENT_SECRET")
               if not getattr(settings, v)]
    if missing:
        raise ValueError(
            f"Keycloak auth is required but these env vars are not set: {', '.join(missing)}"
        )

    logger.info(
        f"Building vLLMClient: endpoint={settings.VLLM_ENDPOINT} model={settings.VLLM_MODEL} "
        f"auth_url={settings.LLM_AUTH_URL} client_id={settings.LLM_CLIENT_ID} "
        f"timeout={settings.LLM_CHAT_TIMEOUT}s ssl_verify={settings.LLM_SSL_VERIFY}"
    )

    llm_config = {
        "model": settings.VLLM_MODEL,
        "api_url": settings.VLLM_ENDPOINT,
        "chat_timeout_seconds": settings.LLM_CHAT_TIMEOUT,
        "num_ctx": settings.LLM_NUM_CTX,
        "ssl_verify": settings.LLM_SSL_VERIFY,
        "enable_thinking": settings.LLM_ENABLE_THINKING,
    }
    auth_cfg = {
        "auth_url": settings.LLM_AUTH_URL,
        "client_id": settings.LLM_CLIENT_ID,
        "client_secret": settings.LLM_CLIENT_SECRET,
    }
    client = vLLMClient(config=llm_config, auth_cfg=auth_cfg)
    logger.info("vLLMClient singleton created successfully")
    return client


_client = _build_client()


# ---------------------------------------------------------------------------
# Async wrappers — preserve the call signatures expected by analysis_service,
# chat_service, and translation_service.
# ---------------------------------------------------------------------------

async def call_vllm_api(payload: Dict) -> Dict:
    """
    Non-streaming LLM call. Runs the sync vLLMClient in a thread executor so
    the event loop is never blocked. Returns a dict shaped like the raw vLLM
    response: {"choices": [{"message": {"role": ..., "content": ...}}]}.
    """
    messages = payload.get("messages", [])
    temperature = payload.get("temperature", 0.2)
    max_tokens = payload.get("max_tokens")
    json_mode = payload.get("response_format", {}).get("type") == "json_object"

    logger.debug(
        f"call_vllm_api: messages={len(messages)} temperature={temperature} "
        f"max_tokens={max_tokens} json_mode={json_mode}"
    )

    loop = asyncio.get_event_loop()
    message = await loop.run_in_executor(
        None,
        lambda: _client.get_chat_completion(
            messages, temperature, json_mode, max_tokens=max_tokens
        ),
    )
    if message is None:
        logger.error("call_vllm_api: vLLM returned no response after all retries")
        raise RuntimeError("vLLM API returned no response after all retries")

    logger.debug(
        f"call_vllm_api: success — role={message.get('role')} "
        f"content_len={len(message.get('content', ''))} chars"
    )
    return {"choices": [{"message": message}]}


async def stream_vllm_api(payload: Dict) -> AsyncGenerator[str, None]:
    """
    Streaming LLM call. Yields raw content chunks (strings) for SSE delivery.
    """
    messages = payload.get("messages", [])
    temperature = payload.get("temperature", 0.2)
    max_tokens = payload.get("max_tokens")

    logger.debug(
        f"stream_vllm_api: messages={len(messages)} temperature={temperature} "
        f"max_tokens={max_tokens}"
    )

    chunk_count = 0
    async for chunk in _client.get_chat_completion_stream(messages, temperature, max_tokens=max_tokens):
        chunk_count += 1
        yield chunk

    logger.debug(f"stream_vllm_api: stream finished — {chunk_count} chunks yielded")


async def check_vllm_health() -> bool:
    """
    Sends a 1-token ping through the authenticated client to verify the
    vLLM endpoint is reachable.
    """
    logger.debug(f"Health check: pinging {settings.VLLM_ENDPOINT}")
    try:
        result = await call_vllm_api({
            "model": settings.VLLM_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        })
        logger.info("Health check: vLLM endpoint is online")
        return result is not None
    except Exception as e:
        logger.warning(f"Health check: vLLM endpoint offline — {e}")
        return False
