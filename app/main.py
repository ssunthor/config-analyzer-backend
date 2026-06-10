import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Quiet down noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Config Analyzer Backend starting up ===")
    logger.info(f"  VLLM_ENDPOINT    : {settings.VLLM_ENDPOINT}")
    logger.info(f"  VLLM_MODEL       : {settings.VLLM_MODEL}")
    logger.info(f"  LLM_AUTH_URL     : {settings.LLM_AUTH_URL}")
    logger.info(f"  LLM_CLIENT_ID    : {settings.LLM_CLIENT_ID}")
    logger.info(f"  LLM_CLIENT_SECRET: {'***' if settings.LLM_CLIENT_SECRET else '(not set)'}")
    logger.info(f"  LLM_CHAT_TIMEOUT : {settings.LLM_CHAT_TIMEOUT}s")
    logger.info(f"  LLM_NUM_CTX      : {settings.LLM_NUM_CTX}")
    logger.info(f"  LLM_SSL_VERIFY   : {settings.LLM_SSL_VERIFY}")
    logger.info(f"  LLM_ENABLE_THINK : {settings.LLM_ENABLE_THINKING}")
    yield
    logger.info("=== Config Analyzer Backend shutting down ===")


app = FastAPI(
    lifespan=lifespan,
    title="Halo Dashboard - Config Analyzer Backend",
    description="API for analyzing firewall, router, and switch configurations.",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/v1")
