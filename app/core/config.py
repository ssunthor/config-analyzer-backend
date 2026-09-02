import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # vLLM endpoint config
    VLLM_ENDPOINT: str = "https://aif-llm-gemma4-31b.aif.gt-t.net/v1/chat/completions"
    VLLM_MODEL: str = "google/gemma-4-31B-it"

    # Keycloak auth (required — no static token fallback)
    LLM_AUTH_URL: str = ""
    LLM_CLIENT_ID: str = ""
    LLM_CLIENT_SECRET: str = ""

    # LLM runtime settings
    LLM_CHAT_TIMEOUT: int = 300
    LLM_NUM_CTX: int = 131072
    LLM_SSL_VERIFY: bool = False
    LLM_ENABLE_THINKING: bool = False

    CONCURRENT_REQUESTS: int = 5
    CHUNK_SIZE: int = 0  # analysis chunk chars; 0 = derive from LLM_NUM_CTX
    PORT: int = 8010
    HOST: str = "0.0.0.0"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "allow"

settings = Settings()
