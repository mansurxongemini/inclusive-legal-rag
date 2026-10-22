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
    # Embeddings may live on another endpoint than the LLM (e.g. LLM on Meta AI, embeddings on OpenRouter).
    # Empty = use OPENROUTER_BASE_URL / OPENROUTER_API_KEY.
    EMBEDDING_BASE_URL: str = Field(default="")
    EMBEDDING_API_KEY: Optional[str] = Field(default=None)
    
    # Models
    EMBEDDING_MODEL: str = Field(default="baai/bge-m3")
    EMBEDDING_DIMENSION: int = Field(default=1024)
    GENERATION_MODEL_PRIMARY: str = Field(default="google/gemini-2.5-flash")
    GENERATION_MODEL_FALLBACK: str = Field(default="meta-llama/llama-3.3-70b-instruct")
    # Must be a dedicated rerank model served by OpenRouter's /rerank endpoint (a chat model is rejected there).
    RERANK_MODEL: str = Field(default="cohere/rerank-v3.5")
    RERANK_PROVIDER: str = Field(default="jev")                     # "jev" (Cohere used as fallback), "cohere", or "rrf"/"none" (no model reranking)
    CURATED_MIN_JEV_SCORE: float = Field(default=0.05)              # Jev score a curated/Huquq+ item needs to be moved ahead of statutory norms
    RERANK_PICK_MIN: float = Field(default=0.05)                    # a unit Jev scored at least this is its pick and stays ahead of rule-added legal bases
    # Jev (reranking + scope/answerability gate) runs on OpenRouter only. Empty = EMBEDDING_* then OPENROUTER_*.
    JEV_BASE_URL: str = Field(default="")
    JEV_API_KEY: Optional[str] = Field(default=None)
    JEV_MODEL: str = Field(default="typesafe/jev-1.13")
    JEV_RERANK_UNITS: int = Field(default=30)                       # candidates sent to Jev
    JEV_RERANK_CHARS: int = Field(default=1500)                     # characters of each unit shown to Jev
    PASSAGE_FOCUS: bool = Field(default=True)                       # long units: show Jev/LLM the matched chunk, not only the head
    JEV_TIMEOUT_S: float = Field(default=20.0)
    # Light LLM calls (query rewriting and translation, history condensing) run on a fast non-reasoning model over
    # OpenRouter instead of the always-reasoning generation model: ~1 s instead of 7-10 s. Empty model = off.
    UTILITY_MODEL: str = Field(default="anthropic/claude-haiku-5.5")
    UTILITY_BASE_URL: str = Field(default="")                       # empty = EMBEDDING_BASE_URL, then OPENROUTER_BASE_URL
    UTILITY_API_KEY: Optional[str] = Field(default=None)            # empty = EMBEDDING_API_KEY, then OPENROUTER_API_KEY
    UTILITY_TIMEOUT_S: float = Field(default=8.0)
    # Tried on the utility endpoint when every generation model failed, so that a Meta outage is not an answer outage.
    GENERATION_MODEL_BACKUP: str = Field(default="anthropic/claude-sonnet-5.5")   # empty = no backup
    GENERATION_BACKUP_TIMEOUT_S: float = Field(default=60.0)
    LLM_PROVIDER_ORDER: str = Field(default="deepinfra")            # comma-separated OpenRouter provider slugs tried first; "" = OpenRouter default routing
    LLM_PROVIDER_QUANTIZATIONS: str = Field(default="fp8,fp16,bf16,fp32,unknown")  # allowed quantizations (excludes fp4/int4); "" = no filter
    GENERATION_REASONING_EFFORT: str = Field(default="none")        # "", "none", "low", "high" or "max"; "" = model default, "none" = reasoning off
    SUPPORT_CHECK_ENABLED: bool = Field(default=False)              # off until reviewed and measured (scripts/faithfulness_eval.py)
    SUPPORT_CHECK_MODEL: str = Field(default="")                    # "" = GENERATION_MODEL_PRIMARY
    SUPPORT_CHECK_TIMEOUT_S: float = Field(default=15.0)
    # Volunteer-answer review (POST /api/v1/assistant/review, TASKS.md 14.1-14.2)
    REVIEW_MODEL: str = Field(default="")                           # "" = GENERATION_MODEL_PRIMARY
    REVIEW_TIMEOUT_S: float = Field(default=60.0)
    REVIEW_MIN_SCORE: int = Field(default=3)                        # every score must be >= this for approve
    REVIEW_MIN_CONFIDENCE: float = Field(default=0.5)
    REVIEW_TOP_K: int = Field(default=6)                            # retrieved norms given to the reviewer LLM
    REVIEW_RUBRIC_VERSION: str = Field(default="1.0")
    REVIEW_MAX_QUESTION_CHARS: int = Field(default=6000)
    REVIEW_MAX_ANSWER_CHARS: int = Field(default=16000)
    # /health budget for a SERVING process: idle is ~175 MB (tests/test_memory_budget.py keeps it < 350),
    # retrieval warms LanceDB/FTS caches to a ~300-550 MB plateau (measured 2026-10-18), not a leak.
    MEMORY_BUDGET_MB: float = Field(default=700.0)

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
    # Uzbek questions are also searched through an LLM rewrite in standard Latin (fixes Cyrillic/misspelled chat input)
    QUERY_NORMALIZE_UZ: bool = Field(default=True)
    GATE_JEV_MIN_IN_SCOPE: float = Field(default=0.3)               # refuse when P(in_scope) is below this ...
    GATE_JEV_ANSWERABLE_CEILING: float = Field(default=0.8)         # ... and P(answerable) is below this (calibrated: OOS max 0.62, in-scope >= 0.9)
    GATE_JEV_MIN_ANSWERABLE: float = Field(default=0.0)             # refuse any question whose P(answerable) is below this (0 = off)

    # Rate limiting & Security
    RATE_LIMIT_PER_MINUTE: int = Field(default=60)
    # Shared secret for remote administration (X-Admin-Key / Bearer). Direct loopback access needs no key.
    ADMIN_API_KEY: Optional[str] = Field(default=None)
    # A direct local connection may administer without the key (the dashboard on the server itself). Switch it off
    # behind a reverse proxy that does not forward X-Forwarded-For / X-Real-IP: every visitor then looks local.
    ADMIN_LOOPBACK_ENABLED: bool = Field(default=True)
    CACHE_TTL_SECONDS: int = Field(default=86400)
    MOCK_EXTERNAL_APIS: bool = Field(default=False)
    # Editorial module: a published curated answer with a fresh open notification is suspended from search.
    EDITORIAL_SUSPEND_ON_CHANGE: bool = Field(default=True)
    # huquqplus.uz WordPress plugin -> POST /api/v1/webhooks/huquqplus (HMAC); empty disables the endpoint.
    HUQUQPLUS_WEBHOOK_SECRET: str = Field(default="")
    HUQUQPLUS_SYNC_INTERVAL_MIN: int = Field(default=60)
    HUQUQPLUS_SYNC_ENABLED: bool = Field(default=True)
    # Assistant API (src/gateway): HMAC secret that turns client user ids into pseudonyms; empty = a random secret
    # kept in STORAGE_DIR/.integration_hash_secret
    INTEGRATION_HASH_SECRET: str = Field(default="")
    # Assistant log retention period in days (answers, turns, feedback)
    ASSISTANT_LOG_RETENTION_DAYS: int = Field(default=90)

    @property
    def is_mock_mode(self) -> bool:
        return self.MOCK_EXTERNAL_APIS or not bool(self.OPENROUTER_API_KEY)

    def ensure_directories(self) -> None:
        Path(self.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CACHE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.REVIEW_QUEUE_PATH).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
