"""Business logic: curated answers, legal-basis links, store projection, notification resolution."""

import logging
from typing import Optional

from src.editorial.doc_watch import doc_snapshot, is_doc_link, law_id_of, refresh_doc_link
from src.editorial.store import EditorialStore
from src.schema.canonical import (
    ArticleMetadata,
    ArticleStatus,
    CanonicalArticle,
    CrossReference,
    RefType,
)

logger = logging.getLogger(__name__)

CURATED_LAW_ID = "curated_qa"


def qa_canonical_id(answer_id: int) -> str:
    return f"qa_{answer_id}"


def build_qa_article(answer: dict, links: list) -> CanonicalArticle:
    """Projects a published curated answer into a store CanonicalArticle.

    Text is composed only from the editor-entered question/alt-questions/answer plus the
    titles of linked Lex.uz norms (legal text itself stays in the linked lex articles).
    """
    aid = answer["id"]
    parts = [f"Savol: {answer['question']}"]
    for alt in answer.get("alt_questions") or []:
        if str(alt).strip():
            parts.append(f"Muqobil savol: {alt.strip()}")
    parts.append(f"Huquqshunos javobi:\n{answer['answer_md']}")
    for link in links:
        label = link.get("article_label") or link.get("canonical_id", "")
        parts.append(f"Huquqiy asos: {label} [{link.get('canonical_id', '')}]")
    full_uz = "\n\n".join(parts)
    lang = answer.get("language") or "uz"
    translations = {"uz": full_uz}
    if lang != "uz" and lang:
        translations[lang] = full_uz
    cross_refs = [
        CrossReference(ref_type=RefType.REFERS_TO, target_canonical_id=link["canonical_id"])
        for link in links if link.get("canonical_id")
    ]
    return CanonicalArticle(
        canonical_id=qa_canonical_id(aid),
        schema_version="1.2",
        metadata=ArticleMetadata(
            law_id=CURATED_LAW_ID,
            law_title={"uz": "Huquq+ huquqshunoslari javoblari", "ru": "Ответы юристов Huquq+"},
            law_number="HUQUQPLUS-QA",
            article_number=f"QA-{aid}",
            article_title={"uz": (answer["question"] or "")[:200]},
            source_url=f"/admin#qa/{aid}",
            effective_date=answer.get("updated_at", "")[:10] or "2026-01-01",
            last_verified_date=answer.get("updated_at", "")[:10] or "2026-01-01",
            source_hash="sha256:qa-placeholder",
            status=ArticleStatus.ACTIVE,
            category=answer.get("category") or "general",
            disability_types=["general"],
            beneficiary_type=["individual"],
            cross_references=cross_refs,
            source_type="curated",
        ),
        points=[],
        translations=translations,
    )


def validate_link_target(store, canonical_id: str):
    """Returns (article, error). Linkable only: exists in store, source_type lex, status ACTIVE."""
    article = store.get_article(canonical_id)
    if article is None:
        return None, "not_found"
    source_type = getattr(article.metadata, "source_type", "lex") or "lex"
    if source_type != "lex":
        return None, "not_lex"
    if article.metadata.status != ArticleStatus.ACTIVE:
        return None, "not_active"
    return article, ""


def snapshot_of(article) -> tuple[str, str, str]:
    text = article.get_text("uz") or ""
    return text, article.metadata.source_hash, article.metadata.status.value


def _invalidate_cache() -> None:
    try:
        from src.api.app import get_cache
        get_cache().clear()
    except Exception as e:
        logger.warning(f"Could not clear query cache: {e}")


async def project_answer(store, editorial: EditorialStore, answer: dict) -> None:
    links = editorial.list_links(owner_type="curated", owner_id=str(answer["id"]))
    qa_article = build_qa_article(answer, links)
    qa_article.metadata.source_hash = qa_article.calculate_source_hash()
    await store.index_article(qa_article)


def unproject_answer(store, answer_id: int) -> None:
    try:
        store.delete_article(qa_canonical_id(answer_id))
    except Exception as e:
        logger.warning(f"Could not remove QA projection qa_{answer_id}: {e}")
    _invalidate_cache()


async def publish_answer(store, editorial: EditorialStore, answer_id: int, *, editor: str = "") -> dict:
    answer = editorial.get_answer(answer_id)
    if not answer:
        raise KeyError("not_found")
    links = editorial.list_links(owner_type="curated", owner_id=str(answer_id))
    if not links:
        raise ValueError("legal_basis_required")
    if editorial.open_notifications_for_owner(owner_type="curated", owner_id=str(answer_id)):
        raise ValueError("open_notifications")
    # Re-validate every link against the current store state.
    for link in links:
        article, err = validate_link_target(store, link["canonical_id"])
        if err:
            raise ValueError(f"link_invalid:{link['canonical_id']}:{err}")
        if article.metadata.source_hash != link.get("snapshot_hash"):
            # the norm changed after the editor last read it (e.g. the answer was unpublished on a change)
            raise ValueError(f"link_stale:{link['canonical_id']}")
    updated = editorial.update_answer(answer_id, {"status": "published"}, editor=editor, action="publish")
    await project_answer(store, editorial, updated)
    _invalidate_cache()
    return updated


def suspend_answer(store, editorial: EditorialStore, answer_id: int, *, action: str = "suspend") -> Optional[dict]:
    answer = editorial.get_answer(answer_id)
    if not answer or answer["status"] != "published":
        return answer
    updated = editorial.update_answer(answer_id, {"status": "needs_review"}, editor="watch", action=action)
    unproject_answer(store, answer_id)
    return updated


def resolve_notification_action(store, editorial: EditorialStore, notif: dict,
                                *, action: str, note: str = "", resolved_by: str = "") -> dict:
    """Implements keep | edited | unpublish | delete for one notification."""
    owner_type, owner_id = notif["owner_type"], notif["owner_id"]
    canonical_id = notif["canonical_id"]

    if action == "delete":
        if owner_type == "huquqplus":
            raise ValueError("Huquq+ maqolasini o'chirish mumkin emas. Saytdan o'chirilganda avtomatik o'chadi.")
        if owner_type == "curated":
            try:
                unproject_answer(store, int(owner_id))
                editorial.delete_answer(int(owner_id), resolved_by=resolved_by)   # also closes its other cards
            except ValueError:
                pass
        else:
            editorial.delete_links_of_owner(owner_type=owner_type, owner_id=owner_id)
        return editorial.resolve_notification(notif["id"], resolution=f"delete:{note}", resolved_by=resolved_by)

    if action == "unpublish":
        if owner_type == "huquqplus":
            from src.integrations.huquqplus_sync import suspend_post
            suspend_post(owner_id, store=store)
        elif owner_type == "curated":
            editorial.update_answer(int(owner_id), {"status": "archived"},
                                    editor=resolved_by, action="unpublish_on_change")
            try:
                unproject_answer(store, int(owner_id))
            except ValueError:
                pass
        # the editor has decided on this change; a later publish re-checks the norm (link_stale)
        editorial.acknowledge_link(owner_type=owner_type, owner_id=owner_id, canonical_id=canonical_id,
                                   marker=notif["new_hash"])
        return editorial.resolve_notification(notif["id"], resolution=f"unpublish:{note}", resolved_by=resolved_by)

    # keep / edited: the editor confirms the answer against the norm's current wording.
    links = editorial.list_links(owner_type=owner_type, owner_id=owner_id)
    link = next((l for l in links if l["canonical_id"] == canonical_id), None)
    if link is not None and is_doc_link(canonical_id):
        snap = doc_snapshot(store, law_id_of(canonical_id))
        if snap is None or snap[2] != "active":
            raise ValueError("Bu hujjat kuchini yo'qotgan yoki bazadan olib tashlangan: \"hali to'g'ri\" deb bo'lmaydi. "
                             "Maqolani WordPress'da yangilang yoki RAG'dan vaqtincha oling.")
        refresh_doc_link(store, editorial, link)
        link = None                                   # handled: skip the single-norm path below
    article = store.get_article(canonical_id) if store and not is_doc_link(canonical_id) else None
    if link is not None:
        if article is None or article.metadata.status != ArticleStatus.ACTIVE:
            # "still correct" cannot rest on a norm that no longer exists or is no longer in force
            if owner_type == "huquqplus":
                raise ValueError(
                    "Bu modda kuchini yo'qotgan yoki bazadan olib tashlangan: maqolani \"hali to'g'ri\" deb bo'lmaydi. "
                    "Maqolani WordPress'da yangilang (keyin \"Saytda yangiladim\") yoki RAG'dan vaqtincha oling."
                )
            raise ValueError(
                "Bu modda kuchini yo'qotgan yoki bazadan olib tashlangan. Javobni tahrirlab, uni huquqiy asosdan "
                "olib tashlang (kerak bo'lsa amaldagi boshqa moddani bog'lang) yoki javobni nashrdan oling."
            )
        text, h, st = snapshot_of(article)
        editorial.refresh_link_snapshot(link["id"], snapshot_text=text, snapshot_hash=h, snapshot_status=st)

    if owner_type == "curated":
        answer = editorial.get_answer(int(owner_id))
        if answer is None:
            raise KeyError("answer_gone")
        if not links:
            raise ValueError("Javobda huquqiy asos qolmadi: kamida bitta Lex.uz moddasini bog'lang.")

    editorial.resolve_open_for_owner_link(owner_type=owner_type, owner_id=owner_id,
                                          canonical_id=canonical_id,
                                          resolution=f"{action}:{note}", resolved_by=resolved_by)

    if owner_type == "curated":
        _republish_if_cleared(store, editorial, int(owner_id), action=f"resolve_{action}", editor=resolved_by)
    return editorial.get_notification(notif["id"])


def _republish_if_cleared(store, editorial: EditorialStore, answer_id: int, *, action: str, editor: str) -> None:
    """
    An answer suspended by the watcher (needs_review) goes back online only when every change affecting it has
    been reviewed and all its bases are valid, in-force norms. An answer the editor archived stays archived.
    """
    answer = editorial.get_answer(answer_id)
    if not answer or answer["status"] != "needs_review":
        return
    if editorial.open_notifications_for_owner(owner_type="curated", owner_id=str(answer_id)):
        return
    links = editorial.list_links(owner_type="curated", owner_id=str(answer_id))
    if not links or any(validate_link_target(store, l["canonical_id"])[1] for l in links):
        return
    editorial.update_answer(answer_id, {"status": "published"}, editor=editor, action=action)


async def resolve_notification(store, editorial: EditorialStore, notif: dict,
                               *, action: str, note: str = "", resolved_by: str = "",
                               client=None) -> dict:
    """resolve_notification_action + putting a republished answer back into search."""
    if notif["owner_type"] == "huquqplus" and action == "edited":
        from src.integrations.huquqplus_sync import resync_post
        lang, _, wp_id_str = notif["owner_id"].partition(":")
        res = await resync_post(int(wp_id_str), lang, client=client, store=store, editorial=editorial)
        if res.get("status") == "deleted":
            return editorial.resolve_notification(notif["id"], resolution=f"article_deleted:{note}",
                                                  resolved_by=resolved_by)
        if res.get("action") != "indexed":
            # "I updated it on the site" must not silently act as "still correct" when nothing changed there
            raise ValueError("Saytdagi maqola matni o'zgarmagan. Avval WordPress'da maqolani yangilang "
                             "yoki \"Maqola hali to'g'ri\" ni tanlang.")
        # the re-sync replaced the article's links and closed its open cards (article_updated)
        return editorial.get_notification(notif["id"])

    result = resolve_notification_action(store, editorial, notif, action=action, note=note, resolved_by=resolved_by)
    if notif["owner_type"] == "curated" and action in ("keep", "edited"):
        answer = editorial.get_answer(int(notif["owner_id"]))
        if answer and answer["status"] == "published":
            await project_answer(store, editorial, answer)
            _invalidate_cache()
    return result
