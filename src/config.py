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
    # Must be a dedicated rerank model served by OpenRouter's /rerank endpoint (a chat model is rejected there).
    RERANK_MODEL: str = Field(default="cohere/rerank-v3.5")
    RERANK_PROVIDER: str = Field(default="jev")                     # "jev" (Cohere used as fallback) or "cohere"
    JEV_MODEL: str = Field(default="typesafe/jev-1.13")
    JEV_RERANK_UNITS: int = Field(default=30)                       # candidates sent to Jev
    JEV_RERANK_CHARS: int = Field(default=1500)                     # characters of each unit shown to Jev
    JEV_TIMEOUT_S: float = Field(default=20.0)
    LLM_PROVIDER_ORDER: str = Field(default="deepinfra")            # comma-separated OpenRouter provider slugs tried first; "" = OpenRouter default routing
    LLM_PROVIDER_QUANTIZATIONS: str = Field(default="fp8,fp16,bf16,fp32,unknown")  # allowed quantizations (excludes fp4/int4); "" = no filter
    GENERATION_REASONING_EFFORT: str = Field(default="none")        # "", "none", "low", "high" or "max"; "" = model default, "none" = reasoning off

    # Storage paths
    STORAGE_DIR: str = Field(default="./data/store")
    CACHE_DB_PATH: str = Field(default="./data/cache/query_cache.db")
    REVIEW_QUEUE_PATH: str = Field(default="./data/store/review_queue.db")

    # Server settings
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    WORKERS: int = Field(default=1)
    LOG_LEVEL: str = Field(default="INFO")

    # Retrieval confidence gate (see src/retrieval/relevance_gate.py). Calibrate with scripts/evaluate_retrieval.py.
    GATE_ENABLED: bool = Field(default=True)
    GATE_MIN_RERANK_SCORE: float = Field(default=0.70)
    GATE_MIN_VECTOR_SCORE: float = Field(default=0.82)
    GATE_MIN_LEXICAL_COVERAGE: float = Field(default=0.5)
    GATE_JEV_SCOPE_ENABLED: bool = Field(default=True)
    GATE_JEV_MIN_IN_SCOPE: float = Field(default=0.3)               # refuse when P(in_scope) is below this ...
    GATE_JEV_ANSWERABLE_CEILING: float = Field(default=0.8)         # ... and P(answerable) is below this (calibrated: OOS max 0.62, in-scope >= 0.9)
    GATE_JEV_MIN_ANSWERABLE: float = Field(default=0.0)             # refuse any question whose P(answerable) is below this (0 = off)

    # Rate limiting & Security
    RATE_LIMIT_PER_MINUTE: int = Field(default=60)
    # Shared secret for remote administration (X-Admin-Key / Bearer). Direct loopback access needs no key.
    ADMIN_API_KEY: Optional[str] = Field(default=None)
    CACHE_TTL_SECONDS: int = Field(default=86400)
    MOCK_EXTERNAL_APIS: bool = Field(default=False)
    # Editorial module: a published curated answer with a fresh open notification is suspended from search.
    EDITORIAL_SUSPEND_ON_CHANGE: bool = Field(default=True)
    # huquqplus.uz WordPress plugin -> POST /api/v1/webhooks/huquqplus (HMAC); empty disables the endpoint.
    HUQUQPLUS_WEBHOOK_SECRET: str = Field(default="")
    HUQUQPLUS_SYNC_INTERVAL_MIN: int = Field(default=60)
    HUQUQPLUS_SYNC_ENABLED: bool = Field(default=True)

    @property
    def is_mock_mode(self) -> bool:
        return self.MOCK_EXTERNAL_APIS or not bool(self.OPENROUTER_API_KEY)

    def ensure_directories(self) -> None:
        Path(self.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CACHE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.REVIEW_QUEUE_PATH).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
