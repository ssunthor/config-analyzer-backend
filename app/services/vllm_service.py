import httpx
import asyncio
import json
from typing import Dict, Optional
from app.core.config import settings

async def check_vllm_health() -> bool:
    """
    Quickly checks if the vLLM server is responsive.
    """
    url = f"{settings.VLLM_HOST}/vllm-gemma3-27b/v1/chat/completions"
    payload = {
        "model": settings.MODEL_NAME,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as c:
            response = await c.post(url, json=payload)
            response.raise_for_status()
            return True
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

async def call_vllm_api(payload: Dict, client: Optional[httpx.AsyncClient] = None) -> Dict:
    """
    Generic helper to call the vLLM API with retry logic.
    """
    url = f"{settings.VLLM_HOST}/vllm-gemma3-27b/v1/chat/completions"
    
    async def _make_request(c: httpx.AsyncClient) -> Dict:
        for attempt in range(1, 4):
            try:
                response = await c.post(url, json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 504 and attempt < 3:
                    print(f"Attempt {attempt} failed with 504, retrying...")
                    await asyncio.sleep(2)
                    continue
                raise e
        raise httpx.TimeoutException("All retries failed.")

    if client:
        return await _make_request(client)
    else:
        async with httpx.AsyncClient(timeout=300.0, verify=False) as c:
            return await _make_request(c)

async def stream_vllm_api(payload: Dict):
    """
    Helper to call the vLLM API with streaming enabled.
    Yields content chunks.
    """
    url = f"{settings.VLLM_HOST}/vllm-gemma3-27b/v1/chat/completions"
    payload["stream"] = True

    async with httpx.AsyncClient(timeout=300.0, verify=False) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    line = line[6:]
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                        if "choices" in data and len(data["choices"]) > 0:
                            content = data["choices"][0].get("delta", {}).get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
