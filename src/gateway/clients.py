"""
Integration clients: the bots, websites and services that call the assistant API.

Every client has its own keys, scopes and limits. Only the SHA-256 of a key is stored and a key is shown once, when
it is issued. A "server" key is a secret for backends (Telegram bot, site backend, partner service); a "browser" key
is publishable, works only from the exact origins listed for its client and has stricter limits.

End users are known to the API only as an HMAC of the client's own user id (`user_ref`), so the logs never hold a
Telegram id, phone number or e-mail.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from src.config import settings
from src.storage.sqlite_utils import connect as _sqlite_connect

KIND_SERVER = "server"
KIND_BROWSER = "browser"
KINDS = (KIND_SERVER, KIND_BROWSER)
SCOPES = ("ask", "feedback")
SECRET_PREFIX = "hpk_live_"
PUBLIC_PREFIX = "hpk_pub_"
MAX_KEY_LENGTH = 128
_LAST_USED_RESOLUTION_S = 60          # last_used_at is written at most once a minute per key


@dataclass
class Client:
    client_id: str
    name: str
    kind: str
    scopes: List[str]
    allowed_origins: List[str]
    rate_per_min: int
    user_rate_per_min: int
    daily_quota: int                   # 0 = unlimited
    is_active: bool
    created_at: float
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KeyInfo:
    key_id: str
    client_id: str
    prefix: str
    created_at: float
    last_used_at: Optional[float] = None
    revoked_at: Optional[float] = None
    expires_at: Optional[float] = None

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > time.time())

    def to_dict(self) -> dict:
        return {**asdict(self), "is_usable": self.is_usable}


def normalize_origin(origin: str) -> str:
    """'https://Huquqplus.uz/' -> 'https://huquqplus.uz'. Raises ValueError for anything but an http(s) origin."""
    parts = urlsplit((origin or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an origin: {origin!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError(f"an origin has no path, query or credentials: {origin!r}")
    host = parts.hostname.lower()
    if parts.scheme == "http" and host not in ("localhost", "127.0.0.1"):
        raise ValueError(f"browser keys need https origins (http only for localhost): {origin!r}")
    default_port = 443 if parts.scheme == "https" else 80
    port = f":{parts.port}" if parts.port and parts.port != default_port else ""
    return f"{parts.scheme}://{host}{port}"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _now_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class ClientStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or (Path(settings.STORAGE_DIR) / "integrations.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        conn = _sqlite_connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    allowed_origins TEXT NOT NULL,
                    rate_per_min INTEGER NOT NULL,
                    user_rate_per_min INTEGER NOT NULL,
                    daily_quota INTEGER NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS client_keys (
                    key_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                    key_hash TEXT NOT NULL UNIQUE,
                    prefix TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_used_at REAL,
                    revoked_at REAL,
                    expires_at REAL
                );
                CREATE INDEX IF NOT EXISTS ix_client_keys_client ON client_keys(client_id);
                CREATE TABLE IF NOT EXISTS usage_daily (
                    client_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    refusals INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0,
                    rejected INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (client_id, day)
                );
            """)

    # -- clients -----------------------------------------------------------------------------------------
    @staticmethod
    def _validate(kind: str, scopes: List[str], origins: List[str], rate: int, user_rate: int, quota: int) -> List[str]:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        bad = [s for s in scopes if s not in SCOPES]
        if bad or not scopes:
            raise ValueError(f"scopes must be a non-empty subset of {SCOPES}")
        normalized = sorted({normalize_origin(o) for o in origins})
        if kind == KIND_BROWSER and not normalized:
            raise ValueError("a browser client needs at least one allowed origin")
        if kind == KIND_SERVER and normalized:
            raise ValueError("a server client is not used from browsers: leave allowed_origins empty")
        for name, value, top in (("rate_per_min", rate, 10000), ("user_rate_per_min", user_rate, 1000)):
            if not 1 <= value <= top:
                raise ValueError(f"{name} must be between 1 and {top}")
        if quota < 0:
            raise ValueError("daily_quota must be >= 0 (0 = unlimited)")
        return normalized

    def create_client(self, name: str, *, kind: str = KIND_SERVER, scopes: Optional[List[str]] = None,
                      allowed_origins: Optional[List[str]] = None, rate_per_min: int = 120,
                      user_rate_per_min: int = 10, daily_quota: int = 0, note: str = "") -> Client:
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise ValueError("name must be 1-120 characters")
        scopes = list(scopes or ["ask", "feedback"])
        origins = self._validate(kind, scopes, allowed_origins or [], rate_per_min, user_rate_per_min, daily_quota)
        client = Client(
            client_id=f"cli_{secrets.token_hex(8)}", name=name, kind=kind, scopes=scopes, allowed_origins=origins,
            rate_per_min=rate_per_min, user_rate_per_min=user_rate_per_min, daily_quota=daily_quota,
            is_active=True, created_at=time.time(), note=(note or "")[:500],
        )
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (client.client_id, client.name, client.kind, json.dumps(client.scopes),
                 json.dumps(client.allowed_origins), client.rate_per_min, client.user_rate_per_min,
                 client.daily_quota, client.created_at, client.note),
            )
        return client

    @staticmethod
    def _row_to_client(r) -> Client:
        return Client(client_id=r[0], name=r[1], kind=r[2], scopes=json.loads(r[3]), allowed_origins=json.loads(r[4]),
                      rate_per_min=r[5], user_rate_per_min=r[6], daily_quota=r[7], is_active=bool(r[8]),
                      created_at=r[9], note=r[10])

    def get_client(self, client_id: str) -> Optional[Client]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        return self._row_to_client(r) if r else None

    def list_clients(self) -> List[Client]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM clients ORDER BY created_at DESC").fetchall()
        return [self._row_to_client(r) for r in rows]

    def update_client(self, client_id: str, **changes) -> Client:
        current = self.get_client(client_id)
        if current is None:
            raise KeyError(client_id)
        allowed = {"name", "scopes", "allowed_origins", "rate_per_min", "user_rate_per_min", "daily_quota",
                   "is_active", "note"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot change {sorted(unknown)}")
        merged = {**current.to_dict(), **{k: v for k, v in changes.items() if v is not None}}
        name = (merged["name"] or "").strip()
        if not name or len(name) > 120:
            raise ValueError("name must be 1-120 characters")
        origins = self._validate(current.kind, list(merged["scopes"]), list(merged["allowed_origins"]),
                                 int(merged["rate_per_min"]), int(merged["user_rate_per_min"]),
                                 int(merged["daily_quota"]))
        with self._conn() as conn:
            conn.execute("""
                UPDATE clients SET name = ?, scopes = ?, allowed_origins = ?, rate_per_min = ?, user_rate_per_min = ?,
                                   daily_quota = ?, is_active = ?, note = ?
                WHERE client_id = ?
            """, (name, json.dumps(list(merged["scopes"])), json.dumps(origins), int(merged["rate_per_min"]),
                  int(merged["user_rate_per_min"]), int(merged["daily_quota"]), 1 if merged["is_active"] else 0,
                  str(merged["note"] or "")[:500], client_id))
        return self.get_client(client_id)

    # -- keys --------------------------------------------------------------------------------------------
    def issue_key(self, client_id: str, *, expires_at: Optional[float] = None) -> Tuple[str, KeyInfo]:
        """Returns (raw key, info). The raw key is not stored anywhere and cannot be shown again."""
        client = self.get_client(client_id)
        if client is None:
            raise KeyError(client_id)
        if expires_at is not None and expires_at <= time.time():
            raise ValueError("expires_at must be in the future")
        prefix = SECRET_PREFIX if client.kind == KIND_SERVER else PUBLIC_PREFIX
        raw = prefix + secrets.token_urlsafe(32)
        info = KeyInfo(key_id=f"key_{secrets.token_hex(8)}", client_id=client_id,
                       prefix=f"{raw[:len(prefix) + 4]}…{raw[-4:]}", created_at=time.time(), expires_at=expires_at)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO client_keys (key_id, client_id, key_hash, prefix, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (info.key_id, client_id, hash_key(raw), info.prefix, info.created_at, expires_at),
            )
        return raw, info

    def revoke_key(self, key_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("UPDATE client_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
                               (time.time(), key_id))
            return cur.rowcount > 0

    def list_keys(self, client_id: str) -> List[KeyInfo]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key_id, client_id, prefix, created_at, last_used_at, revoked_at, expires_at "
                "FROM client_keys WHERE client_id = ? ORDER BY created_at DESC", (client_id,)).fetchall()
        return [KeyInfo(*r) for r in rows]

    def resolve_key(self, raw_key: str) -> Optional[Tuple[Client, KeyInfo]]:
        """The active client and usable key behind a raw key, or None (unknown, revoked, expired, inactive)."""
        if not raw_key or len(raw_key) > MAX_KEY_LENGTH or not raw_key.startswith((SECRET_PREFIX, PUBLIC_PREFIX)):
            return None
        with self._conn() as conn:
            r = conn.execute(
                "SELECT key_id, client_id, prefix, created_at, last_used_at, revoked_at, expires_at "
                "FROM client_keys WHERE key_hash = ?", (hash_key(raw_key),)).fetchone()
            if not r:
                return None
            info = KeyInfo(*r)
            if not info.is_usable:
                return None
            now = time.time()
            if info.last_used_at is None or now - info.last_used_at >= _LAST_USED_RESOLUTION_S:
                conn.execute("UPDATE client_keys SET last_used_at = ? WHERE key_id = ?", (now, info.key_id))
                info.last_used_at = now
        client = self.get_client(info.client_id)
        if client is None or not client.is_active:
            return None
        # a key must match its client's kind (a publishable key never unlocks a server client)
        expected = SECRET_PREFIX if client.kind == KIND_SERVER else PUBLIC_PREFIX
        if not raw_key.startswith(expected):
            return None
        return client, info

    # -- usage -------------------------------------------------------------------------------------------
    def take_daily_request(self, client: Client) -> bool:
        """Counts one request for today; False (and nothing counted) when the client's daily quota is used up."""
        day = _now_day()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT requests FROM usage_daily WHERE client_id = ? AND day = ?",
                               (client.client_id, day)).fetchone()
            used = row[0] if row else 0
            if client.daily_quota and used >= client.daily_quota:
                conn.execute("""
                    INSERT INTO usage_daily (client_id, day, rejected) VALUES (?, ?, 1)
                    ON CONFLICT(client_id, day) DO UPDATE SET rejected = rejected + 1
                """, (client.client_id, day))
                return False
            conn.execute("""
                INSERT INTO usage_daily (client_id, day, requests) VALUES (?, ?, 1)
                ON CONFLICT(client_id, day) DO UPDATE SET requests = requests + 1
            """, (client.client_id, day))
            return True

    def record_outcome(self, client_id: str, *, refusal: bool = False, error: bool = False) -> None:
        if not (refusal or error):
            return
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO usage_daily (client_id, day, refusals, errors) VALUES (?, ?, ?, ?)
                ON CONFLICT(client_id, day) DO UPDATE SET refusals = refusals + excluded.refusals,
                                                          errors = errors + excluded.errors
            """, (client_id, _now_day(), int(refusal), int(error)))

    def record_rejected(self, client_id: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO usage_daily (client_id, day, rejected) VALUES (?, ?, 1)
                ON CONFLICT(client_id, day) DO UPDATE SET rejected = rejected + 1
            """, (client_id, _now_day()))

    def usage(self, client_id: str, days: int = 30) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT day, requests, refusals, errors, rejected FROM usage_daily WHERE client_id = ? "
                "ORDER BY day DESC LIMIT ?", (client_id, max(1, min(days, 366)))).fetchall()
        return [{"day": r[0], "requests": r[1], "refusals": r[2], "errors": r[3], "rejected": r[4]} for r in rows]

    def usage_today(self, client_id: str) -> int:
        with self._conn() as conn:
            r = conn.execute("SELECT requests FROM usage_daily WHERE client_id = ? AND day = ?",
                             (client_id, _now_day())).fetchone()
        return r[0] if r else 0


# -- end-user pseudonyms ----------------------------------------------------------------------------------
_hash_secret_cache: Optional[bytes] = None


def _hash_secret() -> bytes:
    """INTEGRATION_HASH_SECRET, else a random secret created once in STORAGE_DIR (readable only by the owner)."""
    global _hash_secret_cache
    if _hash_secret_cache is None:
        configured = getattr(settings, "INTEGRATION_HASH_SECRET", "") or ""
        if configured:
            _hash_secret_cache = configured.encode("utf-8")
        else:
            path = Path(settings.STORAGE_DIR) / ".integration_hash_secret"
            if not path.exists():
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_hex(32))
            _hash_secret_cache = path.read_text().strip().encode("utf-8")
    return _hash_secret_cache


def user_ref(client_id: str, user_id: Optional[str]) -> Optional[str]:
    """Stable pseudonym of a client's end user; the raw id (e.g. a Telegram id) is never stored."""
    if user_id is None or str(user_id).strip() == "":
        return None
    msg = f"{client_id}:{str(user_id).strip()[:256]}".encode("utf-8")
    return "u_" + hmac.new(_hash_secret(), msg, hashlib.sha256).hexdigest()[:32]


_store: Optional[ClientStore] = None


def get_client_store() -> ClientStore:
    global _store
    if _store is None:
        _store = ClientStore()
    return _store
