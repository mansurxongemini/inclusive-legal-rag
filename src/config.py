import os
from typing import List

from dotenv import dotenv_values
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

    # OpenRouter: ONE key and ONE endpoint serve every call (chat, embeddings, reranking, Jev). Meta AI was only a test provider.
    OPENROUTER_API_KEY: Optional[str] = Field(default=None)
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1")

    # Models
    EMBEDDING_MODEL: str = Field(default="qwen/qwen3-embedding-8b")
    EMBEDDING_DIMENSION: int = Field(default=1024)
    # For models with adjustable output size (qwen3-embedding: 4096 natively): sent as "dimensions" when > 0. bge-m3 ignores it.
    EMBEDDING_REQUEST_DIMENSIONS: int = Field(default=1024)
    # qwen3-embedding-8b at 1024 dimensions since 2026-10-25 (docs/EMBEDDING_COMPARISON.md: whole-path MRR 0.921 -> 0.971
    # over bge-m3, same price). Changing it means re-embedding the whole store: scripts/reembed_context.py --all.
    # Instruction put before QUESTIONS only (documents are embedded as they are): qwen3-embedding recommends
    # "Instruct: ...\nQuery: <question>", but on the gold set it lowered dense recall@5 (0.836 -> 0.764), so it is empty.
    EMBEDDING_QUERY_INSTRUCTION: str = Field(default="")
    # THE chat model: generation, query rewriting, translation, ranking, claim check, review and judging all use it
    # (one model keeps the cost predictable; OpenRouter itself falls back between the providers of that model).
    # DeepSeek V4 Flash 0731: 1M context, about $0.04-0.06 per million input and $0.13-0.18 per million output tokens
    # (OpenRouter's list, 2026-10-24), many providers; it supports `reasoning` and `response_format`.
    GENERATION_MODEL_PRIMARY: str = Field(default="deepseek/deepseek-v4-flash-0731")
    # Must be a dedicated rerank model served by OpenRouter's /rerank endpoint (a chat model is rejected there).
    RERANK_MODEL: str = Field(default="cohere/rerank-v3.5")
    RERANK_PROVIDER: str = Field(default="jev")                     # "jev" (Cohere used as fallback), "cohere", or "rrf"/"none" (no model reranking)
    CURATED_MIN_JEV_SCORE: float = Field(default=0.05)              # Jev score a curated/Huquq+ item needs to be moved ahead of statutory norms
    RERANK_PICK_MIN: float = Field(default=0.05)                    # a unit Jev scored at least this is its pick and stays ahead of rule-added legal bases
    # Jev (reranking + scope/answerability gate), same key and endpoint.
    JEV_MODEL: str = Field(default="typesafe/jev-1.13")
    JEV_RERANK_UNITS: int = Field(default=30)                       # candidates sent to Jev
    JEV_RERANK_UNITS_PER_SUBQUESTION: int = Field(default=5)        # ... plus this many for each legal sub-question of a long question
    JEV_RERANK_CHARS: int = Field(default=1500)                     # characters of each unit shown to Jev
    # Jev is the better ranker (dev split: hit@1 81% vs 70%) but costs about $0.0006 per question on top of the chat model.
    # False = never call it: the chat model ranks the candidates and checks the scope (LLM_RANK_FALLBACK).
    JEV_ENABLED: bool = Field(default=False)
    LLM_RANK_FALLBACK: bool = Field(default=True)
    LLM_RANK_UNITS: int = Field(default=30)                         # candidates shown to the fallback ranker (20 x 700: hit@1 51%, 30 x 1200: 70%)
    LLM_RANK_CHARS: int = Field(default=1200)                       # characters of each unit shown to it
    JEV_TIMEOUT_S: float = Field(default=20.0)
    # Monthly OpenRouter budget (every paid call: chat, embeddings, Jev). Above SOFT_RATIO /health warns (answers unchanged);
    # at 100% nothing is called and a new question gets "temporarily unavailable" (HTTP 503) until the month changes.
    # $0.0009 per new question: $15 covers about 16 600 a month. 0 = no guard.
    OPENROUTER_MONTHLY_BUDGET_USD: float = Field(default=15.0)
    # OpenRouter is paused (no call at all: new questions get "temporarily unavailable") when this switch is on, or when the
    # balance read from the provider every 15 minutes is at or below the reserve.
    OPENROUTER_PAUSED: bool = Field(default=False)
    OPENROUTER_RESERVE_USD: float = Field(default=0.05)
    OPENROUTER_BUDGET_SOFT_RATIO: float = Field(default=0.8)
    # Which of the ~25 OpenRouter providers of the chat model serve it. Their prices differ up to 10x (2026-10-25:
    # $0.042-0.44 per M input, $0.13-1.32 output). Baidu first (fp8, $0.044/$0.133: 12 gold questions cost 31% less than on
    # DeepInfra, $0.0009 vs $0.0013 each, same answers, median answer 13 s vs 26 s that day), DeepInfra (fp8, $0.06/$0.18) next;
    # a fallback never goes above the price cap or below fp8 ("unknown" admitted Reka, Phala, Cloudflare at up to 10x).
    LLM_PROVIDER_ORDER: str = Field(default="baidu,deepinfra")      # comma-separated OpenRouter provider slugs tried first; "" = OpenRouter default routing
    LLM_PROVIDER_QUANTIZATIONS: str = Field(default="fp8,fp16,bf16,fp32")  # allowed quantizations (excludes fp4/int4/unknown); "" = no filter
    LLM_PROVIDER_MAX_PRICE_PROMPT: float = Field(default=0.10)      # USD per million input tokens a provider may charge; 0 = no cap
    LLM_PROVIDER_MAX_PRICE_COMPLETION: float = Field(default=0.30)  # USD per million output tokens; 0 = no cap
    GENERATION_REASONING_EFFORT: str = Field(default="none")        # "", "none", "low", "high" or "max"; "" = model default, "none" = reasoning off
    # Deterministic guards on every answer (script of the question, forbidden wording, numbers absent from the sources):
    # one repair regeneration, then warnings (src/generation/guards.py)
    ANSWER_GUARDS_ENABLED: bool = Field(default=True)
    ANSWER_REPAIR_TIMEOUT_S: float = Field(default=90.0)
    SUPPORT_CHECK_ENABLED: bool = Field(default=False)              # off until reviewed and measured (scripts/faithfulness_eval.py)
    SUPPORT_CHECK_MODEL: str = Field(default="")                    # "" = the chat model at minimal reasoning
    SUPPORT_CHECK_TIMEOUT_S: float = Field(default=25.0)
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

    # Server settings
    HOST: str = Field(default="0.0.0.0")
    LOG_LEVEL: str = Field(default="INFO")

    # Retrieval confidence gate (see src/retrieval/relevance_gate.py). Calibrate with scripts/evaluate_retrieval.py.
    GATE_ENABLED: bool = Field(default=True)
    GATE_MIN_RERANK_SCORE: float = Field(default=0.70)
    GATE_MIN_VECTOR_SCORE: float = Field(default=0.82)
    GATE_MIN_LEXICAL_COVERAGE: float = Field(default=0.5)
    GATE_JEV_SCOPE_ENABLED: bool = Field(default=True)
    # Uzbek questions are also searched through an LLM rewrite in standard Latin (fixes Cyrillic/misspelled chat input)
    QUERY_NORMALIZE_UZ: bool = Field(default=True)
    # A question of at least this many words (a story with several issues) is also searched through up to 4 short
    # legal sub-questions written by the LLM; each one gets its own share of the candidates and its own Jev pick. 0 = off
    QUERY_SUBQUESTIONS_MIN_WORDS: int = Field(default=25)
    # The only languages that get vector rows and are searched by vector (comma list; empty = the default, uz). The other texts
    # (Russian, English) stay in the store and are shown to the model and the user, but are never embedded: Russian and English
    # questions are translated to Uzbek and searched there. Measured on 22 Russian questions (2 runs each) hit@6 77% with the Russian
    # texts searched, 82% without their vectors, 86% without vectors and full-text rows; Uzbek questions did not get worse
    # (dev split hit@6 91% -> 92-94%).
    VECTOR_LANGUAGES: str = Field(default="uz")
    # Languages whose texts are not searched by full text (comma list): their rows are skipped
    FTS_EXCLUDE_LANGUAGES: str = Field(default="ru")
    VECTOR_KEEP_VERSIONS_HOURS: int = Field(default=6)  # old versions of the vector table are pruned daily, keeping this many hours
    FTS_CHUNK_MIN_CHARS: int = Field(default=6000)    # a unit longer than this also gets one full-text row per chunk (0 = off)
    LIST_LEADERS: int = Field(default=2)               # units in the top N of any single list are lifted to LEADER_ANCHOR_POSITION in the pool (0 = off)
    LEADER_ANCHOR_POSITION: int = Field(default=12)
    # A high P(answerable) does not excuse a low scope: the Traffic/Criminal codes in the corpus answer their questions (0.89-0.96) just
    # like the Convention questions that Jev misjudges. The chat model's scope judge is decisive (0.0 for out-of-scope questions).
    # When the model ranker fails (a provider error) the scope judgement already made is kept: at or above this value the
    # question is answered from the fused order instead of being refused by the lexical gate (which refuses ru/en questions
    # whose words are not in the Uzbek units: gold item en06 was refused that way).
    GATE_SCOPE_RESCUE: float = Field(default=0.8)
    GATE_JEV_MIN_IN_SCOPE: float = Field(default=0.2)               # refuse when P(in_scope) is below this (calibrated on the stress set and the held-out set: 100% / 95% of the out-of-scope questions, 1-4% of the in-scope ones)

    # Rate limiting & Security
    RATE_LIMIT_PER_MINUTE: int = Field(default=60)
    PUBLIC_BROWSE_RATE_PER_MINUTE: int = Field(default=30)   # per address: the public norm / document browsing endpoints
    FEEDBACK_RATE_PER_MINUTE: int = Field(default=6)         # per address: submissions of the public feedback form
    # Shared secret for remote administration (X-Admin-Key / Bearer). Direct loopback access needs no key.
    ADMIN_API_KEY: Optional[str] = Field(default=None)
    # A direct local connection may administer without the key (the dashboard on the server itself). Switch it off
    # behind a reverse proxy that does not forward X-Forwarded-For / X-Real-IP: every visitor then looks local.
    # None = on when no ADMIN_API_KEY is configured (a developer's machine), off when one is (a deployment: the key
    # is then the only way in). Set it explicitly to override.
    ADMIN_LOOPBACK_ENABLED: Optional[bool] = Field(default=None)
    # Reverse proxies in front of the app that append to X-Forwarded-For (0 = none: the header is ignored).
    TRUSTED_PROXIES: int = Field(default=0)
    MAX_PUBLIC_BODY_BYTES: int = Field(default=262144)       # 0 = no limit; applies to the public question endpoints
    ANSWER_TIMEOUT_S: float = Field(default=100.0)           # whole generation step of one request; then the matching norms are shown
    # Retrieval of one request (question embedding, translation, scope, ranking). A provider that hangs - neither an answer
    # nor an error - held a request for minutes; past these deadlines the question is searched by full-text search only.
    QUERY_EMBED_TIMEOUT_S: float = Field(default=10.0)
    RETRIEVAL_TIMEOUT_S: float = Field(default=30.0)
    PUBLIC_DAILY_GENERATIONS: int = Field(default=3000)      # answers generated per day (cache hits are free); 0 = no cap
    CACHE_TTL_SECONDS: int = Field(default=86400)
    MOCK_EXTERNAL_APIS: bool = Field(default=False)
    # Editorial module: a published curated answer with a fresh open notification is suspended from search.
    EDITORIAL_SUSPEND_ON_CHANGE: bool = Field(default=True)
    # huquqplus.uz WordPress plugin -> POST /api/v1/webhooks/huquqplus (HMAC); empty disables the endpoint.
    HUQUQPLUS_WEBHOOK_SECRET: str = Field(default="")
    HUQUQPLUS_SYNC_INTERVAL_MIN: int = Field(default=60)
    HUQUQPLUS_SYNC_ENABLED: bool = Field(default=True)
    # Languages of Huquq+ that are synchronized (comma list). Uzbek only: the Russian version of a post says what the Uzbek one
    # says, and a unit without Uzbek text has no vector and no full-text row, so it could never be found.
    HUQUQPLUS_LANGUAGES: str = Field(default="uz")
    # Assistant API (src/gateway): HMAC secret that turns client user ids into pseudonyms; empty = a random secret
    # kept in STORAGE_DIR/.integration_hash_secret
    INTEGRATION_HASH_SECRET: str = Field(default="")
    # Assistant log retention period in days (answers, turns, feedback)
    ASSISTANT_LOG_RETENTION_DAYS: int = Field(default=90)

    @property
    def admin_loopback_enabled(self) -> bool:
        if self.ADMIN_LOOPBACK_ENABLED is not None:
            return self.ADMIN_LOOPBACK_ENABLED
        return not bool(self.ADMIN_API_KEY)

    @property
    def vector_language_list(self) -> list[str]:
        """VECTOR_LANGUAGES as a list; an empty setting means the default (Uzbek), not "embed nothing"."""
        languages = [l.strip().lower() for l in self.VECTOR_LANGUAGES.split(",") if l.strip()]
        return languages or ["uz"]

    @property
    def huquqplus_language_list(self) -> list[str]:
        """HUQUQPLUS_LANGUAGES as a list; an empty setting means the default (Uzbek)."""
        languages = [l.strip().lower() for l in self.HUQUQPLUS_LANGUAGES.split(",") if l.strip()]
        return languages or ["uz"]

    @property
    def is_mock_mode(self) -> bool:
        return self.MOCK_EXTERNAL_APIS or not bool(self.OPENROUTER_API_KEY)

    def ensure_directories(self) -> None:
        Path(self.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.CACHE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()

# Settings that earlier versions read and this one does not (one OpenRouter key and endpoint serve every call; experiments that
# were measured and dropped). Settings has
# extra="ignore", so they would be dropped without a word: a key of another provider left in OPENROUTER_API_KEY would
# then be sent to OpenRouter. The application lists the ones it finds at start-up.
REMOVED_SETTINGS = (
    # experiments that were measured and not adopted, switches that only had an "off" branch (their code is gone)
    "FTS_STOPWORDS", "FTS_STEM_PREFIX", "FTS_STEM_EXTRA_WEIGHT", "VECTOR_DEDUP_QUERIES", "VECTOR_WINDOW_FACTOR",
    "GATE_JEV_ANSWERABLE_CEILING", "GATE_JEV_MIN_ANSWERABLE", "LLM_SCOPE_SCALE", "RETRIEVAL_THREADS", "PASSAGE_FOCUS",
    "REVIEW_QUEUE_PATH",
    # the Meta test provider and its side endpoints
    "PLUS_META_AI_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "JEV_BASE_URL", "JEV_API_KEY",
    "UTILITY_MODEL", "UTILITY_BASE_URL", "UTILITY_API_KEY", "UTILITY_TIMEOUT_S",
    "GENERATION_MODEL_BACKUP", "GENERATION_BACKUP_TIMEOUT_S", "GENERATION_MODEL_FALLBACK", "WORKERS",
)


def removed_settings_in_use(env_file: str = ".env") -> List[str]:
    """Names of REMOVED_SETTINGS that have a value in the environment or in the env file."""
    values = {**dotenv_values(env_file), **os.environ}
    return sorted(name for name in REMOVED_SETTINGS if (values.get(name) or "").strip())
