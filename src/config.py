from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # OpenRouter API
    OPENROUTER_API_KEY: Optional[str] = Field(default=None)
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1")
    
    # Models
    EMBEDDING_MODEL: str = Field(default="baai/bge-m3")
    EMBEDDING_DIMENSION: int = Field(default=1024)
    GENERATION_MODEL_PRIMARY: str = Field(default="google/gemini-2.5-flash")
    GENERATION_MODEL_FALLBACK: str = Field(default="meta-llama/llama-3.3-70b-instruct")
    RERANK_MODEL: str = Field(default="google/gemini-2.5-flash")

    # Storage paths
    STORAGE_DIR: str = Field(default="./data/store")
    CACHE_DB_PATH: str = Field(default="./data/cache/query_cache.db")
    REVIEW_QUEUE_PATH: str = Field(default="./data/store/review_queue.db")

    # Server settings
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    WORKERS: int = Field(default=1)
    LOG_LEVEL: str = Field(default="INFO")

    # Rate limiting & Security
    RATE_LIMIT_PER_MINUTE: int = Field(default=60)
    CACHE_TTL_SECONDS: int = Field(default=86400)
    MOCK_EXTERNAL_APIS: bool = Field(default=False)

    @property
    def is_mock_mode(self) -> bool:
        return self.MOCK_EXTERNAL_APIS or not bool(self.OPENROUTER_API_KEY)

    def ensure_directories(self) -> None:
        Path(self.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CACHE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.REVIEW_QUEUE_PATH).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
