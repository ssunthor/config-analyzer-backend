from fastapi import APIRouter
from app.api.v1.endpoints import analysis, translation, health, chat, fetch

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(analysis.router, prefix="/configs", tags=["analysis"])
api_router.include_router(translation.router, prefix="/configs", tags=["translation"])
api_router.include_router(fetch.router, prefix="/fetch", tags=["fetch"])
api_router.include_router(chat.router, tags=["chat"])
