"""
huquqplus.uz maqolalarini RAG do'koni bilan sinxronlash moduli.
- Holat bazasi: huquqplus.db (hp_posts, sync_runs)
- Maqolalarni bo'laklash (<= 3500 belgi) va CanonicalArticle yaratish
- Lex.uz havolalarini resolve qilish va editorial legal_links boshqaruvi
- full_sync(), process_queue(), suspend_post(), unsuspend_post()
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.domain.disability_taxonomy import classify_category
from src.editorial import service as svc
from src.editorial.doc_watch import doc_link_id, doc_snapshot, is_doc_link, law_id_of, law_label, refresh_doc_link
from src.editorial.store import EditorialStore
from src.ingestion.huquqplus_client import HuquqPlusClient, HuquqPlusPost, LexRef, diff_index, lex_element_id
from src.integrations.huquqplus_webhook import WebhookQueue
from src.schema.canonical import (
    ArticleMetadata,
    ArticleStatus,
    CanonicalArticle,
    CrossReference,
    RefType,
)
from src.storage.hybrid_store import HybridStore
from src.storage.sqlite_utils import connect as _sqlite_connect

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_queue_lock = asyncio.Lock()          # webhook background task and scheduler must not process the same events twice

# a run that never finished (process killed mid-sync) must not block every later sync
STALE_RUN_AFTER_S = 2 * 3600
# a listing that suddenly lacks most known posts is treated as an API/category problem, not as mass deletion
MAX_REMOVAL_SHARE = 0.5
MIN_POSTS_FOR_REMOVAL_GUARD = 5
LEX_INDEX_TTL_S = 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_huquqplus_db_path() -> Path:
    p = Path(settings.STORAGE_DIR) / "huquqplus.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def init_huquqplus_db(db_path: Optional[Path] = None) -> None:
    path = db_path or get_huquqplus_db_path()
    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hp_posts (
                wp_id INTEGER NOT NULL,
                lang TEXT NOT NULL,
                modified TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                section TEXT NOT NULL,
                status TEXT NOT NULL, -- 'active' | 'suspended' | 'deleted'
                unit_ids TEXT NOT NULL, -- JSON list of canonical_ids
                lex_refs TEXT NOT NULL, -- JSON list
                unresolved_refs TEXT NOT NULL, -- JSON list
                synced_at TEXT NOT NULL,
                PRIMARY KEY(wp_id, lang)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hp_posts_status ON hp_posts(status)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL, -- 'full' | 'queue' | 'manual'
                started_at TEXT NOT NULL,
                finished_at TEXT,
                added INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                removed INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT ''
            )
        """)


def split_post_into_chunks(post_title: str, text: str, max_chars: int = 3500) -> List[Tuple[str, str]]:
    """
    Matnni sarlavhalar va paragraflar bo'yicha <= max_chars (3500) belgili bo'limlarga ajratadi.
    Qaytaradi: [(section_title, chunk_text), ...]
    """
    if not text or not text.strip():
        return [(post_title, text or "")]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [(post_title, text)]

    chunks: List[Tuple[str, str]] = []
    current_paras: List[str] = []
    current_len = 0
    current_title = post_title

    def flush():
        nonlocal current_paras, current_len
        if current_paras:
            body = "\n\n".join(current_paras)
            chunks.append((current_title, body))
            current_paras = []
            current_len = 0

    for p in paragraphs:
        p_len = len(p)
        # Agar paragraf qo'shilsa limitdan oshsa, oldingi bo'limni yakunlaymiz
        if current_len + p_len + (2 if current_paras else 0) > max_chars and current_paras:
            flush()
            # Yangi bo'lim uchun sarlavha: agar joriy paragraf sarlavhaga o'xshasa
            if len(p) < 150 and not p.endswith(".") and "\n" not in p:
                current_title = p
            else:
                current_title = post_title

        # Agar bitta paragrafning o'zi max_chars dan katta bo'lsa
        if p_len > max_chars:
            flush()
            lines = p.split("\n")
            sub_lines: List[str] = []
            sub_len = 0
            for l in lines:
                if sub_len + len(l) + 1 > max_chars and sub_lines:
                    chunks.append((current_title, "\n".join(sub_lines)))
                    sub_lines = []
                    sub_len = 0
                sub_lines.append(l)
                sub_len += len(l) + 1
            if sub_lines:
                chunks.append((current_title, "\n".join(sub_lines)))
            continue

        if not current_paras:
            if len(p) < 150 and not p.endswith(".") and "\n" not in p:
                current_title = p

        current_paras.append(p)
        current_len += p_len + (2 if len(current_paras) > 1 else 0)

    flush()
    return chunks or [(post_title, text)]


class _LexIndex:
    def __init__(self):
        self.element_to_canonical: Dict[str, str] = {}
        self.doc_to_law_id: Dict[str, str] = {}
        self.built_at: float = 0.0


_cached_lex_index: Optional[_LexIndex] = None


def reset_lex_index_cache() -> None:
    global _cached_lex_index
    _cached_lex_index = None


def _index_ids(target: Dict[str, str], ids: List[str], value: str) -> None:
    """Lex.uz serves the Latin and Cyrillic Uzbek editions as -N / N, so both spellings map to the same value."""
    for raw in ids:
        clean = str(raw or "").lstrip("#").strip().lstrip("-")
        if clean:
            target.setdefault(clean, value)
            target.setdefault("-" + clean, value)


def get_lex_index(store: HybridStore) -> _LexIndex:
    """Cached for LEX_INDEX_TTL_S: the Lex.uz corpus is refreshed by a separate process."""
    import time as _time
    global _cached_lex_index
    if _cached_lex_index is not None and _time.monotonic() - _cached_lex_index.built_at < LEX_INDEX_TTL_S:
        return _cached_lex_index

    idx = _LexIndex()
    idx.built_at = _time.monotonic()
    for rec in store.fts_store.iter_link_metadata():
        if (rec.get("source_type") or "lex") != "lex":
            continue
        # document ids of the Uzbek edition (source_url) and of the Russian edition, which has its own ids
        m = re.search(r"/docs/(-?\d+)", rec.get("source_url") or "")
        doc_ids = [m.group(1)] if m else []
        if rec.get("ru_document_id"):
            doc_ids.append(rec["ru_document_id"])
        _index_ids(idx.doc_to_law_id, doc_ids, rec.get("law_id"))
        # every element of the unit (inner paragraphs and points included), in both editions
        element_ids = list(rec.get("source_element_ids") or [])
        if rec.get("source_element_id"):
            element_ids.append(rec["source_element_id"])
        element_ids += list(rec.get("ru_element_ids") or [])
        _index_ids(idx.element_to_canonical, element_ids, rec["canonical_id"])

    _cached_lex_index = idx
    return idx


def _add_watch_link(store: HybridStore, editorial: EditorialStore, owner_id: str, link_id: str) -> bool:
    """Creates a legal link for a unit id or a whole-act id (law:<law_id>) with the current snapshot."""
    if is_doc_link(link_id):
        law_id = law_id_of(link_id)
        snap = doc_snapshot(store, law_id)
        if snap is None:
            return False
        link = editorial.add_link(owner_type="huquqplus", owner_id=owner_id, canonical_id=link_id, law_id=law_id,
                           article_label=f"{law_label(store, law_id)} (butun hujjat)",
                           snapshot_text=snap[0], snapshot_hash=snap[1], snapshot_status=snap[2])
        refresh_doc_link(store, editorial, link)
        return True
    lex_art = store.get_article(link_id)
    if lex_art is None:
        return False
    text, h, st = svc.snapshot_of(lex_art)
    editorial.add_link(owner_type="huquqplus", owner_id=owner_id, canonical_id=link_id,
                       law_id=lex_art.metadata.law_id,
                       article_label=f"{lex_art.metadata.law_number} {lex_art.metadata.article_number}".strip(),
                       snapshot_text=text, snapshot_hash=h, snapshot_status=st)
    return True


def _watch_link_ids(resolved_cids: List[str], unresolved: List[Dict[str, Any]]) -> List[str]:
    """Unit links for anchored references, whole-act links for references to acts that are in the corpus."""
    doc_links = {doc_link_id(u["law_id"]) for u in unresolved if u.get("law_id")}
    return sorted(set(resolved_cids) | doc_links)


def resolve_lex_ref(store: HybridStore, ref: LexRef) -> Optional[str]:
    """
    LexRef dan canonical_id ni topadi (element_id orqali).
    Element id bo'lmasa yoki topilmasa None qaytaradi.
    """
    idx = get_lex_index(store)
    if not ref.element_id:
        return None
    clean = lex_element_id(str(ref.element_id))      # also links stored before fragments were normalised
    # An anchor that belongs to no unit (act title, chapter/appendix heading, or an article left out of a general
    # code) stays a document-level reference. Guessing "the next unit" is unsafe: amendments give new elements
    # higher ids than their neighbours, and partially included codes skip articles - a wrong link is worse than none.
    return idx.element_to_canonical.get(clean)


def build_canonical_articles_for_post(
    post: HuquqPlusPost,
    resolved_lex_cids: List[str],
) -> List[CanonicalArticle]:
    """
    HuquqPlusPost dan store bo'laklarini (<= 3500 belgi) yaratadi.
    """
    chunks = split_post_into_chunks(post.title, post.text, max_chars=3500)
    articles: List[CanonicalArticle] = []

    cross_refs = [
        CrossReference(ref_type=RefType.REFERS_TO, target_canonical_id=cid)
        for cid in sorted(set(resolved_lex_cids))
    ]

    eff_date = post.published[:10] if post.published else "2024-01-01"
    mod_date = post.modified[:10] if post.modified else eff_date

    for i, (chunk_title, chunk_body) in enumerate(chunks, start=1):
        cid = f"hp_{post.lang}_{post.wp_id}_{i}"
        cat = classify_category(title=post.title, text=chunk_body, default="general")
        translations = {post.lang: chunk_body}

        art = CanonicalArticle(
            canonical_id=cid,
            schema_version="1.2",
            metadata=ArticleMetadata(
                law_id=f"huquqplus_{post.lang}_{post.wp_id}",
                law_title={post.lang: post.title},
                law_number="Huquq+",
                article_number=f"{i}-qism",
                article_title={post.lang: chunk_title or post.title},
                source_url=post.url,
                published_url=post.url,
                effective_date=eff_date,
                last_verified_date=mod_date,
                source_hash="placeholder",
                status=ArticleStatus.ACTIVE,
                category=cat or "general",
                disability_types=["general"],
                beneficiary_type=["individual"],
                cross_references=cross_refs,
                source_type="huquqplus",
            ),
            points=[],
            translations=translations,
        )
        art.metadata.source_hash = art.calculate_source_hash()
        articles.append(art)

    return articles


async def upsert_post(
    post: HuquqPlusPost,
    store: HybridStore,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Bitta HuquqPlusPost ni RAG bazasiga va holat jadvaliga joylaydi.
    force=True re-indexes and re-activates even when the content is unchanged (explicit unsuspend).
    """
    editorial = editorial or EditorialStore()
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    if post.lang not in settings.huquqplus_language_list:        # e.g. the Russian version of a post (HUQUQPLUS_LANGUAGES)
        return {"action": "skipped_language", "wp_id": post.wp_id, "lang": post.lang}

    owner_id = f"{post.lang}:{post.wp_id}"

    # Mavjud holatni tekshirish
    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
        existing = conn.execute(
            "SELECT * FROM hp_posts WHERE wp_id = ? AND lang = ?", (post.wp_id, post.lang)
        ).fetchone()

    # Agar modified o'zgargan lekin content_hash bir xil bo'lsa va status active bo'lsa -> faqat modified yangilanadi, embed QILINMAYDI
    # same content: only the timestamp moves. A suspended post stays suspended until its text really changes.
    if (not force and existing and existing.get("content_hash") == post.content_hash
            and existing.get("status") in ("active", "suspended")):
        with _sqlite_connect(path, timeout=30.0) as conn:
            conn.execute(
                "UPDATE hp_posts SET modified = ?, synced_at = ? WHERE wp_id = ? AND lang = ?",
                (post.modified, _now(), post.wp_id, post.lang),
            )
        return {"action": "modified_only", "wp_id": post.wp_id, "lang": post.lang}

    # Lex havolalarni resolve qilish (index building reads the whole corpus: keep it off the event loop)
    idx = await asyncio.to_thread(get_lex_index, store)
    resolved_lex_cids: List[str] = []
    unresolved_refs: List[Dict[str, Any]] = []

    for ref in post.lex_refs:
        cid = resolve_lex_ref(store, ref)
        if cid:
            resolved_lex_cids.append(cid)
        else:
            law_id = idx.doc_to_law_id.get(ref.doc_id)
            unresolved_refs.append({
                "doc_id": ref.doc_id,
                "law_id": law_id,
                "url": ref.url,
            })

    # Bo'laklarni qurish va indekslash
    articles = build_canonical_articles_for_post(post, resolved_lex_cids)
    await store.index_articles_batch(articles)

    # Eski bo'laklardan yangisida yo'qlarini o'chirish
    new_unit_ids = [a.canonical_id for a in articles]
    old_unit_ids: List[str] = []
    if existing:
        try:
            old_unit_ids = json.loads(existing.get("unit_ids") or "[]")
        except Exception:
            old_unit_ids = []

    for old_id in old_unit_ids:
        if old_id not in new_unit_ids:
            try:
                store.delete_article(old_id)
            except Exception as e:
                logger.warning(f"Ortiqcha bo'lakni o'chirishda xatolik {old_id}: {e}")

    # Editorial legal_links yangilash
    editorial.delete_links_of_owner(owner_type="huquqplus", owner_id=owner_id)
    for link_id in _watch_link_ids(resolved_lex_cids, unresolved_refs):
        _add_watch_link(store, editorial, owner_id, link_id)

    # Shu owner uchun ochiq bildirishnomalarni "article_updated" bilan yopish
    editorial.resolve_open_for_owner(
        owner_type="huquqplus",
        owner_id=owner_id,
        resolution="article_updated",
    )

    # hp_posts ga yozish
    lex_refs_json = json.dumps([
        {"url": r.url, "doc_id": r.doc_id, "element_id": r.element_id, "anchor": r.anchor_text}
        for r in post.lex_refs
    ], ensure_ascii=False)
    unresolved_json = json.dumps(unresolved_refs, ensure_ascii=False)
    units_json = json.dumps(new_unit_ids, ensure_ascii=False)

    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.execute("""
            INSERT INTO hp_posts (
                wp_id, lang, modified, content_hash, title, url, section,
                status, unit_ids, lex_refs, unresolved_refs, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            ON CONFLICT(wp_id, lang) DO UPDATE SET
                modified = excluded.modified,
                content_hash = excluded.content_hash,
                title = excluded.title,
                url = excluded.url,
                section = excluded.section,
                status = 'active',
                unit_ids = excluded.unit_ids,
                lex_refs = excluded.lex_refs,
                unresolved_refs = excluded.unresolved_refs,
                synced_at = excluded.synced_at
        """, (
            post.wp_id, post.lang, post.modified, post.content_hash,
            post.title, post.url, post.section, units_json,
            lex_refs_json, unresolved_json, _now(),
        ))

    svc._invalidate_cache()
    return {
        "action": "indexed",
        "wp_id": post.wp_id,
        "lang": post.lang,
        "units_count": len(new_unit_ids),
        "resolved_links": len(resolved_lex_cids),
    }


def delete_post(
    wp_id: int,
    lang: str,
    store: HybridStore,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> bool:
    """
    Maqola o'chirilganda uning bo'laklarini store'dan va bog'lanishlarini editorial'dan tozalaydi.
    """
    editorial = editorial or EditorialStore()
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    owner_id = f"{lang}:{wp_id}"

    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
        row = conn.execute(
            "SELECT unit_ids FROM hp_posts WHERE wp_id = ? AND lang = ?", (wp_id, lang)
        ).fetchone()
        if not row:
            return False

        try:
            unit_ids = json.loads(row.get("unit_ids") or "[]")
        except Exception:
            unit_ids = []

        conn.execute(
            "UPDATE hp_posts SET status = 'deleted', unit_ids = '[]', synced_at = ? WHERE wp_id = ? AND lang = ?",
            (_now(), wp_id, lang),
        )

    for cid in unit_ids:
        try:
            store.delete_article(cid)
        except Exception as e:
            logger.warning(f"Bo'lakni o'chirishda xatolik {cid}: {e}")

    editorial.delete_links_of_owner(owner_type="huquqplus", owner_id=owner_id)
    svc._invalidate_cache()
    return True


def purge_disallowed_languages(
    store: HybridStore,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> int:
    """
    Removes the posts of a language that is not synchronized (HUQUQPLUS_LANGUAGES) any more: their units leave the store
    (text index, vectors), their Lex.uz links and the answer cache go with them, and the row stays as a 'deleted' record.
    Returns the number of posts removed; nothing is left to remove on the next run.
    """
    editorial = editorial or EditorialStore()
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)
    allowed = settings.huquqplus_language_list
    marks = ",".join("?" for _ in allowed)
    with _sqlite_connect(path, timeout=30.0) as conn:
        rows = conn.execute(
            f"SELECT wp_id, lang FROM hp_posts WHERE status != 'deleted' AND lang NOT IN ({marks})", allowed,
        ).fetchall()
    removed = 0
    for wp_id, lang in rows:
        if delete_post(int(wp_id), lang, store, editorial, db_path=path):
            removed += 1
    if removed:
        logger.info(f"Huquq+: {removed} posts of languages other than {allowed} removed")
    return removed


def suspend_post(owner_id: str, store: Optional[HybridStore] = None, db_path: Optional[Path] = None) -> bool:
    """
    Maqolani RAG'dan vaqtincha oladi (status = 'suspended').
    """
    if store is None:
        from src.api.app import get_store
        store = get_store()

    parts = owner_id.split(":", 1)
    if len(parts) != 2:
        return False
    lang, wp_id_str = parts
    try:
        wp_id = int(wp_id_str)
    except ValueError:
        return False

    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
        row = conn.execute(
            "SELECT unit_ids FROM hp_posts WHERE wp_id = ? AND lang = ?", (wp_id, lang)
        ).fetchone()
        if not row:
            return False

        try:
            unit_ids = json.loads(row.get("unit_ids") or "[]")
        except Exception:
            unit_ids = []

        conn.execute(
            "UPDATE hp_posts SET status = 'suspended', synced_at = ? WHERE wp_id = ? AND lang = ?",
            (_now(), wp_id, lang),
        )

    for cid in unit_ids:
        try:
            store.delete_article(cid)
        except Exception as e:
            logger.warning(f"Suspend qilishda bo'lakni o'chirish xatosi {cid}: {e}")

    svc._invalidate_cache()
    return True


async def unsuspend_post(
    owner_id: str,
    client: Optional[HuquqPlusClient] = None,
    store: Optional[HybridStore] = None,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> bool:
    """
    Vaqtincha olingan maqolani qayta tiklaydi.
    """
    if store is None:
        from src.api.app import get_store
        store = get_store()
    editorial = editorial or EditorialStore()

    parts = owner_id.split(":", 1)
    if len(parts) != 2:
        return False
    lang, wp_id_str = parts
    try:
        wp_id = int(wp_id_str)
    except ValueError:
        return False

    hp_client = client or HuquqPlusClient()
    post = await asyncio.to_thread(hp_client.fetch_post, wp_id, lang=lang)
    if not post:
        return False

    res = await upsert_post(post, store, editorial, db_path=db_path, force=True)
    return res.get("action") == "indexed"


async def full_sync(
    client: Optional[HuquqPlusClient] = None,
    store: Optional[HybridStore] = None,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    HUQUQPLUS_LANGUAGES (odatda faqat uz) uchun to'liq sinxronlash:
    list_post_index -> hp_posts bilan diff_index -> fetch_posts -> upsert / delete.
    Bir vaqtda faqat bitta sync bajariladi.
    """
    if _sync_lock.locked():
        logger.warning("full_sync allaqachon bajarilmoqda (lock band).")
        return {"status": "skipped", "reason": "already_running"}

    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    # sync_runs dagi tugallanmagan yozuv tekshiruvi
    with _sqlite_connect(path, timeout=30.0) as conn:
        for run_id_, started in conn.execute(
                "SELECT id, started_at FROM sync_runs WHERE finished_at IS NULL").fetchall():
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
            except ValueError:
                age = STALE_RUN_AFTER_S + 1
            if age > STALE_RUN_AFTER_S:
                conn.execute("UPDATE sync_runs SET finished_at = ?, errors = errors + 1, message = ? WHERE id = ?",
                             (_now(), "abandoned (process stopped mid-run)", run_id_))
        running = conn.execute(
            "SELECT id FROM sync_runs WHERE finished_at IS NULL"
        ).fetchone()
        if running:
            logger.warning(f"Tugallanmagan sync_run mavjud: {running[0]}")
            return {"status": "skipped", "reason": "sync_in_progress", "run_id": running[0]}

        cur = conn.execute(
            "INSERT INTO sync_runs (kind, started_at) VALUES ('full', ?)", (_now(),)
        )
        run_id = cur.lastrowid

    async with _sync_lock:
        _now()
        hp_client = client or HuquqPlusClient()
        if store is None:
            from src.api.app import get_store
            store = get_store()
        editorial = editorial or EditorialStore()

        total_added = 0
        total_updated = 0
        total_removed = 0
        total_errors = 0
        error_messages: List[str] = []

        try:
            total_removed += await asyncio.to_thread(purge_disallowed_languages, store, editorial, path)
            for lang in settings.huquqplus_language_list:
                # 1. Hozirgi saytdagi indeks
                try:
                    current_index = await asyncio.to_thread(hp_client.list_post_index, lang=lang)
                except Exception as exc:
                    logger.error(f"Post indeksini olishda xatolik ({lang}): {exc}")
                    total_errors += 1
                    error_messages.append(f"{lang}_index_error: {exc}")
                    continue

                # 2. Bazadagi avvalgi indeks
                with _sqlite_connect(path, timeout=30.0) as conn:
                    conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
                    rows = conn.execute(
                        "SELECT wp_id, modified FROM hp_posts WHERE lang = ? AND status != 'deleted'",
                        (lang,),
                    ).fetchall()
                    previous_index = {int(r["wp_id"]): str(r["modified"]) for r in rows}

                # 3. Diff hisoblash
                added_ids, changed_ids, removed_ids = diff_index(previous_index, current_index)
                if (len(previous_index) >= MIN_POSTS_FOR_REMOVAL_GUARD
                        and len(removed_ids) > MAX_REMOVAL_SHARE * len(previous_index)):
                    # renamed category / API hiccup: deleting most of the articles must be a human decision
                    logger.error(f"{lang}: {len(removed_ids)}/{len(previous_index)} posts missing from the listing - "
                                 f"removal skipped")
                    total_errors += 1
                    error_messages.append(f"{lang}_mass_removal_blocked: {len(removed_ids)}/{len(previous_index)}")
                    removed_ids = []

                # 4. Yangi va o'zgargan postlarni fetch qilish
                fetch_ids = added_ids + changed_ids
                if fetch_ids:
                    posts = await asyncio.to_thread(hp_client.fetch_posts, lang=lang, ids=fetch_ids)
                    for post in posts:
                        try:
                            res = await upsert_post(post, store, editorial, db_path=path)
                            if res.get("action") == "indexed":
                                if post.wp_id in added_ids:
                                    total_added += 1
                                else:
                                    total_updated += 1
                            elif res.get("action") == "modified_only":
                                total_updated += 1
                        except Exception as exc:
                            logger.error(f"Postni upsert qilishda xatolik ({post.wp_id}, {lang}): {exc}")
                            total_errors += 1
                            error_messages.append(f"upsert_error_{post.wp_id}: {exc}")

                # 5. Yo'qolgan postlarni o'chirish
                for wp_id in removed_ids:
                    try:
                        deleted = delete_post(wp_id, lang, store, editorial, db_path=path)
                        if deleted:
                            total_removed += 1
                    except Exception as exc:
                        logger.error(f"Postni o'chirishda xatolik ({wp_id}, {lang}): {exc}")
                        total_errors += 1
                        error_messages.append(f"delete_error_{wp_id}: {exc}")

            try:
                relinked = await asyncio.to_thread(relink_posts, store, editorial, path)
                if relinked["changed_posts"]:
                    logger.info(f"Huquq+ relink: {relinked}")
            except Exception as exc:
                logger.error(f"Huquq+ relink xatosi: {exc}")
                total_errors += 1
                error_messages.append(f"relink_error: {exc}")

            finished_at = _now()
            msg = "; ".join(error_messages) if error_messages else "Sinxronlash muvaffaqiyatli yakunlandi"

            with _sqlite_connect(path, timeout=30.0) as conn:
                conn.execute("""
                    UPDATE sync_runs SET
                        finished_at = ?,
                        added = ?,
                        updated = ?,
                        removed = ?,
                        errors = ?,
                        message = ?
                    WHERE id = ?
                """, (finished_at, total_added, total_updated, total_removed, total_errors, msg[:500], run_id))

            return {
                "status": "success" if total_errors == 0 else "partial_success",
                "run_id": run_id,
                "added": total_added,
                "updated": total_updated,
                "removed": total_removed,
                "errors": total_errors,
                "message": msg,
            }
        except BaseException as exc:
            finished_at = _now()
            with _sqlite_connect(path, timeout=30.0) as conn:
                conn.execute("""
                    UPDATE sync_runs SET
                        finished_at = ?,
                        errors = errors + 1,
                        message = ?
                    WHERE id = ?
                """, (finished_at, str(exc)[:500], run_id))
            raise


async def process_queue(
    limit: int = 50,
    client: Optional[HuquqPlusClient] = None,
    store: Optional[HybridStore] = None,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    WebhookQueue dagi navbatni qayta ishlaydi. One worker at a time: the webhook's background task and the
    scheduler would otherwise fetch and index the same pending events concurrently.
    """
    async with _queue_lock:
        return await _process_queue_unlocked(limit, client, store, editorial, db_path)


async def _process_queue_unlocked(
    limit: int,
    client: Optional[HuquqPlusClient],
    store: Optional[HybridStore],
    editorial: Optional[EditorialStore],
    db_path: Optional[Path],
) -> Dict[str, Any]:
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    queue = WebhookQueue(str(path))
    events = queue.pending(limit=limit)
    if not events:
        return {"processed": 0, "errors": 0}

    hp_client = client or HuquqPlusClient()
    if store is None:
        from src.api.app import get_store
        store = get_store()
    editorial = editorial or EditorialStore()

    processed = 0
    errors = 0

    for item in events:
        row_id = item["id"]
        event = item["event"]
        post_id = item["post_id"]
        lang = item.get("lang") or "uz"

        try:
            if event == "delete":
                delete_post(post_id, lang, store, editorial, db_path=path)
                queue.mark_done(row_id)
                processed += 1
            elif event == "upsert" and lang not in settings.huquqplus_language_list:
                queue.mark_done(row_id)          # a language that is not synchronized: nothing to fetch
                processed += 1
            elif event == "upsert":
                post = await asyncio.to_thread(hp_client.fetch_post, post_id, lang=lang)
                if post is None:
                    delete_post(post_id, lang, store, editorial, db_path=path)
                else:
                    await upsert_post(post, store, editorial, db_path=path)
                queue.mark_done(row_id)
                processed += 1
            else:
                queue.mark_done(row_id)
                processed += 1
        except Exception as exc:
            logger.error(f"Webhook hodisasini ishlashda xatolik (id={row_id}): {exc}")
            queue.mark_failed(row_id, str(exc))
            errors += 1

    return {"processed": processed, "errors": errors}


async def resync_post(
    wp_id: int,
    lang: str,
    client: Optional[HuquqPlusClient] = None,
    store: Optional[HybridStore] = None,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Bitta postni majburiy qayta sinxronlaydi.
    """
    hp_client = client or HuquqPlusClient()
    if store is None:
        from src.api.app import get_store
        store = get_store()
    editorial = editorial or EditorialStore()
    path = db_path or get_huquqplus_db_path()

    post = await asyncio.to_thread(hp_client.fetch_post, wp_id, lang=lang)
    if not post:
        delete_post(wp_id, lang, store, editorial, db_path=path)
        return {"status": "deleted", "wp_id": wp_id, "lang": lang}

    res = await upsert_post(post, store, editorial, db_path=path)
    return {"status": "synced", **res}


def relink_posts(
    store: HybridStore,
    editorial: Optional[EditorialStore] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, int]:
    """
    Re-resolves the stored Lex.uz references of every synced article against the current corpus, without
    re-fetching or re-embedding: after a Lex.uz refresh/rebuild a reference may start (or stop) resolving.
    Existing links keep their snapshots, so a pending norm change is still reported by the watcher.
    """
    editorial = editorial or EditorialStore()
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)
    idx = get_lex_index(store)
    changed_posts = added_links = removed_links = 0

    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
        rows = conn.execute("SELECT * FROM hp_posts WHERE status IN ('active', 'suspended')").fetchall()

    for row in rows:
        owner_id = f"{row['lang']}:{row['wp_id']}"
        refs = json.loads(row.get("lex_refs") or "[]")
        resolved: List[str] = []
        unresolved: List[Dict[str, Any]] = []
        for r in refs:
            ref = LexRef(url=r.get("url", ""), doc_id=str(r.get("doc_id", "")), element_id=r.get("element_id"),
                         lang=None, anchor_text=r.get("anchor", ""))
            cid = resolve_lex_ref(store, ref)
            if cid:
                resolved.append(cid)
            else:
                unresolved.append({"doc_id": ref.doc_id, "law_id": idx.doc_to_law_id.get(ref.doc_id), "url": ref.url})
        wanted = _watch_link_ids(resolved, unresolved)
        current = {l["canonical_id"] for l in editorial.list_links(owner_type="huquqplus", owner_id=owner_id)}
        if set(wanted) == current and json.dumps(unresolved, ensure_ascii=False) == (row.get("unresolved_refs") or "[]"):
            continue
        changed_posts += 1

        for cid in current - set(wanted):
            editorial.remove_link(owner_type="huquqplus", owner_id=owner_id, canonical_id=cid)
            removed_links += 1
        for link_id in set(wanted) - current:
            if _add_watch_link(store, editorial, owner_id, link_id):
                added_links += 1

        cross_refs = [CrossReference(ref_type=RefType.REFERS_TO, target_canonical_id=c)
                      for c in sorted(set(resolved))]
        for unit_id in json.loads(row.get("unit_ids") or "[]"):
            art = store.get_article(unit_id)
            if art is None:
                continue
            art.metadata.cross_references = cross_refs
            store.fts_store.upsert_article(art)      # metadata only: the text and its embedding are unchanged
        with _sqlite_connect(path, timeout=30.0) as conn:
            conn.execute("UPDATE hp_posts SET unresolved_refs = ? WHERE wp_id = ? AND lang = ?",
                         (json.dumps(unresolved, ensure_ascii=False), row["wp_id"], row["lang"]))

    if changed_posts:
        svc._invalidate_cache()
    return {"checked_posts": len(rows), "changed_posts": changed_posts,
            "added_links": added_links, "removed_links": removed_links}


def get_sync_status(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Admin status uchun umumiy statistika.
    """
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    queue = WebhookQueue(str(path))
    queue_stats = queue.stats()

    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}

        # Postlar soni til / status bo'yicha
        posts_summary = conn.execute("""
            SELECT lang, section, status, COUNT(*) as cnt
            FROM hp_posts
            GROUP BY lang, section, status
        """).fetchall()

        # Oxirgi sync_runs
        last_runs = conn.execute("""
            SELECT * FROM sync_runs ORDER BY id DESC LIMIT 5
        """).fetchall()

        # Unresolved havolalar soni
        all_posts = conn.execute("SELECT unresolved_refs FROM hp_posts WHERE status = 'active'").fetchall()
        unresolved_count = doc_level_count = missing_doc_count = 0
        for r in all_posts:
            try:
                refs = json.loads(r.get("unresolved_refs") or "[]")
            except Exception:
                continue
            unresolved_count += len(refs)
            doc_level = sum(1 for x in refs if x.get("law_id"))       # act is in the corpus: watched as a whole
            doc_level_count += doc_level
            missing_doc_count += len(refs) - doc_level                 # act is not in the corpus at all

        total_active = conn.execute("SELECT COUNT(*) FROM hp_posts WHERE status = 'active'").fetchone()["COUNT(*)"]

    return {
        "posts_summary": posts_summary,
        "total_active_posts": total_active,
        "unresolved_refs_count": unresolved_count,
        "doc_level_refs_count": doc_level_count,
        "missing_doc_refs_count": missing_doc_count,
        "queue_stats": queue_stats,
        "last_runs": last_runs,
    }


def list_synced_posts(
    lang: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Admin ro'yxati uchun postlarni qidirish va filtrlash.
    """
    path = db_path or get_huquqplus_db_path()
    init_huquqplus_db(path)

    clauses: List[str] = []
    params: List[Any] = []

    if lang and lang != "all":
        clauses.append("lang = ?")
        params.append(lang)
    if status and status != "all":
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("(title LIKE ? OR url LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _sqlite_connect(path, timeout=30.0) as conn:
        conn.row_factory = lambda c, r: {d[0]: r[i] for i, d in enumerate(c.description)}
        total = conn.execute(f"SELECT COUNT(*) as cnt FROM hp_posts {where}", params).fetchone()["cnt"]

        rows = conn.execute(
            f"SELECT * FROM hp_posts {where} ORDER BY modified DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()

        posts = []
        for r in rows:
            unit_ids = []
            lex_refs = []
            unresolved = []
            try:
                unit_ids = json.loads(r.get("unit_ids") or "[]")
            except Exception:
                pass
            try:
                lex_refs = json.loads(r.get("lex_refs") or "[]")
            except Exception:
                pass
            try:
                unresolved = json.loads(r.get("unresolved_refs") or "[]")
            except Exception:
                pass

            posts.append({
                "wp_id": r["wp_id"],
                "lang": r["lang"],
                "title": r["title"],
                "url": r["url"],
                "section": r["section"],
                "status": r["status"],
                "modified": r["modified"],
                "synced_at": r["synced_at"],
                "units_count": len(unit_ids),
                "resolved_links_count": len(lex_refs) - len(unresolved),
                "unresolved_links": unresolved,
                "lex_refs": lex_refs,
            })

        return posts, total
