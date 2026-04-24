import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    VLLM_HOST: str = "http://10.250.133.8:8080"
    MODEL_NAME: str = "google/gemma-3-27b-it"
    CONCURRENT_REQUESTS: int = 5
    CHUNK_SIZE: int = 100000
    PORT: int = 8010
    HOST: str = "0.0.0.0"
    VERIFY_SSL: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = "allow"

settings = Settings()
