from fastapi import APIRouter
from app.services.vllm_service import check_vllm_health

router = APIRouter()

@router.get("/health")
async def health_check():
    """
    Health check endpoint for the Config Analyzer API.
    Also verifies connection to the upstream vLLM inference server.
    """
    is_healthy = await check_vllm_health()
    if is_healthy:
        return {"status": "ok", "ai_server": "online"}
    return {"status": "ok", "ai_server": "offline"}
