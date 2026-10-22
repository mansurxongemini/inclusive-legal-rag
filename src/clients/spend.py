"""
OpenRouter spend ledger and monthly budget guard.

Every OpenRouter response (chat, embeddings, Jev decisions) carries `usage.cost` in USD. The ledger adds it up per day
and kind in a small SQLite file and tells the client in which state the month is:

* ok         - below OPENROUTER_BUDGET_SOFT_RATIO of the monthly budget: everything runs;
* soft       - above it: optional OpenRouter calls (query rewriting, claim check, backup model) are skipped, the free
               generation provider (Meta) does that work instead;
* exhausted  - the monthly budget is used up: embeddings and Jev are skipped too, retrieval degrades to full-text
               search with the RRF order, and nothing more is spent until the month changes.

Evaluation scripts count into their own ledger (SPEND_SCOPE=eval) and are never limited by the service budget.
"""
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from src.config import settings

logger = logging.getLogger(__name__)


class SpendLedger:
    def __init__(self, path: Optional[str] = None, scope: Optional[str] = None):
        self.scope = scope or os.environ.get("SPEND_SCOPE", "service")
        default = Path(settings.STORAGE_DIR) / ("spend.db" if self.scope == "service" else f"spend_{self.scope}.db")
        self.path = Path(path) if path else default
        self._lock = threading.Lock()
        self._month_cache: Optional[float] = None
        self._cache_at = 0.0
        self._init_failed = False
        self._tripped_until = 0.0              # the provider itself refused (key limit / credit used up) until then
        self._trip_reason = ""
        self.provider_remaining: Optional[float] = None      # USD left on the key, when the provider tells (see refresh_provider_limit)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS spend (day TEXT NOT NULL, kind TEXT NOT NULL, "
                             "usd REAL NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, kind))")
        except Exception as e:      # the guard must never take the service down
            self._init_failed = True
            logger.warning(f"Spend ledger unavailable ({e}); the budget guard is off")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def add(self, kind: str, usd: float) -> None:
        if self._init_failed or usd <= 0:
            return
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO spend (day, kind, usd, calls) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(day, kind) DO UPDATE SET usd = usd + excluded.usd, calls = calls + 1",
                    (self._today(), kind, usd))
            if self._month_cache is not None:
                self._month_cache += usd
        except Exception as e:
            logger.warning(f"Spend ledger write failed: {e}")

    def month_total(self) -> float:
        """USD spent in the current UTC month (re-read from the file every 5 s, other processes write to it too)."""
        if self._init_failed:
            return 0.0
        now = time.monotonic()
        if self._month_cache is not None and now - self._cache_at < 5.0:
            return self._month_cache
        try:
            prefix = datetime.now(timezone.utc).strftime("%Y-%m")
            with self._connect() as conn:
                row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM spend WHERE day LIKE ?", (prefix + "%",)).fetchone()
            self._month_cache, self._cache_at = float(row[0]), now
        except Exception:
            self._month_cache = self._month_cache or 0.0
        return self._month_cache

    def by_kind(self) -> Dict[str, float]:
        if self._init_failed:
            return {}
        try:
            prefix = datetime.now(timezone.utc).strftime("%Y-%m")
            with self._connect() as conn:
                return {k: round(v, 5) for k, v in conn.execute(
                    "SELECT kind, SUM(usd) FROM spend WHERE day LIKE ? GROUP BY kind", (prefix + "%",))}
        except Exception:
            return {}

    def trip(self, reason: str, minutes: float = 15.0) -> None:
        """The provider answered 'key limit exceeded' / 'insufficient credit': stop calling it for a while."""
        if time.monotonic() >= self._tripped_until:
            logger.error(f"OpenRouter refused the key ({reason}); its calls are paused for {minutes:.0f} min")
        self._tripped_until = time.monotonic() + minutes * 60
        self._trip_reason = reason

    async def refresh_provider_limit(self, client) -> Optional[float]:
        """Reads the remaining USD of the key from OpenRouter (GET /key, free of charge); None when it has no limit."""
        try:
            http = await client.get_embedding_client()
            r = await http.get(f"{client.embedding_base_url}/key", timeout=15)
            if r.status_code == 200:
                data = r.json().get("data", {})
                remaining = data.get("limit_remaining")
                self.provider_remaining = float(remaining) if remaining is not None else None
        except Exception as e:
            logger.info(f"Could not read the OpenRouter key limit: {e}")
        return self.provider_remaining

    def state(self) -> str:
        if time.monotonic() < self._tripped_until:
            return "exhausted"
        if self.provider_remaining is not None and self.provider_remaining <= 0.01:
            return "exhausted"
        budget = settings.OPENROUTER_MONTHLY_BUDGET_USD
        if budget <= 0 or self.scope != "service":
            return "ok"
        if self.provider_remaining is not None and self.provider_remaining < budget * (1 - settings.OPENROUTER_BUDGET_SOFT_RATIO):
            return "soft"
        total = self.month_total()
        if total >= budget:
            return "exhausted"
        if total >= budget * settings.OPENROUTER_BUDGET_SOFT_RATIO:
            return "soft"
        return "ok"

    def summary(self) -> Dict:
        return {"scope": self.scope, "month_usd": round(self.month_total(), 4),
                "budget_usd": settings.OPENROUTER_MONTHLY_BUDGET_USD, "state": self.state(), "by_kind": self.by_kind(),
                "key_remaining_usd": self.provider_remaining, "paused_because": self._trip_reason or None}


ledger = SpendLedger()


def is_limit_error(status: int, body: str) -> bool:
    """True for the provider's 'this key / account can not spend more' answers (402, or 403 with a limit message)."""
    text = (body or "").lower()
    return status == 402 or (status == 403 and any(w in text for w in ("limit", "credit", "insufficient", "quota")))


def cost_of(usage: Optional[dict]) -> float:
    """USD of one response from its `usage` object (0 when the provider reports none)."""
    try:
        return max(0.0, float((usage or {}).get("cost") or 0.0))
    except (TypeError, ValueError):
        return 0.0
