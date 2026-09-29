import pytest
from src.ingestion.lex_parser import parse_law_text_file, extract_cross_references_from_text
from src.ingestion.review_queue import ReviewQueue, ReviewQueueItem
from src.ingestion.amendment_diff import check_and_apply_amendment
from src.storage.hybrid_store import HybridStore
from src.schema.canonical import CanonicalArticle


def test_lex_parser_from_text():
    sample_text = """
    O'ZBEKISTON RESPUBLIKASINING QONUNI O'RQ-999
    
    1-modda. Qonunning maqsadi
    Ushbu Qonunning maqsadi fuqarolarning ijtimoiy huquqlarini himoya qilishdan iborat.
    1. Davlat fuqarolarga ijtimoiy kafolatlarni ta'minlaydi.
    2. Mazkur norma 15-modda talablariga muvofiq amalga oshiriladi.

    2-modda. Qonunchilik hujjatlari
    Ijtimoiy himoya to'g'risidagi qonunchilik ushbu Qonun va boshqa hujjatlardan iborat.
    """

    articles = parse_law_text_file(sample_text, "sample_law.txt")
    assert len(articles) == 2
    art1 = articles[0]
    assert art1.metadata.article_number == "1-modda"
    assert "fuqarolarning ijtimoiy huquqlarini" in art1.translations["uz"]
    assert len(art1.points) == 2
    assert art1.points[0].point_id == "1"

    # Cross reference check
    refs = [r.target_canonical_id for r in art1.metadata.cross_references]
    assert "art_15" in refs


def test_review_queue_operations(tmp_path):
    queue = ReviewQueue(str(tmp_path / "test_review_queue.db"))

    item = ReviewQueueItem(
        canonical_id="law_test_art_1",
        change_type="amended_article",
        diff_summary="- eski tahrir\n+ yangi tahrir",
        proposed_json="{}",
        status="pending"
    )
    item_id = queue.enqueue(item)
    assert item_id is not None

    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0].canonical_id == "law_test_art_1"

    # Approve
    queue.set_status(item_id, "approved")
    assert len(queue.list_pending()) == 0


def test_amendment_detection(tmp_path):
    store = HybridStore(str(tmp_path / "amend_store"))
    queue = ReviewQueue(str(tmp_path / "amend_queue.db"))

    # Initial article
    sample = """
    10-modda. Boshlang'ich matn
    Ushbu modda dastlabki tahrirda qabul qilingan.
    """
    arts = parse_law_text_file(sample, "test_amend.txt")
    art = arts[0]
    store.fts_store.upsert_article(art)

    # Modified article with same canonical_id
    modified_sample = """
    10-modda. O'zgartirilgan matn
    Ushbu modda yangi tahrirda butunlay o'zgartirildi.
    """
    mod_arts = parse_law_text_file(modified_sample, "test_amend.txt")
    mod_art = mod_arts[0]

    has_changed, diff = check_and_apply_amendment(mod_art, store, queue)
    assert has_changed is True
    assert "yangi tahrirda" in diff

    # Ensure it was placed into review queue
    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0].canonical_id == mod_art.canonical_id
