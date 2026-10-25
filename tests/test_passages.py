"""
Long units: the vector store remembers which chunk matched, and Jev and the LLM read the unit's beginning plus
the matched part instead of only its first characters.
"""
from types import SimpleNamespace

import pytest

from src.config import settings
from src.generation.prompts import format_context_for_llm
from src.retrieval.hybrid_retriever import ScoredArticle
from src.retrieval.passages import focus_chunks, focused_text
from src.retrieval.pipeline import merge_candidates
from src.retrieval.reranker import Reranker, RetrievedArticleContext
from src.schema.canonical import CanonicalArticle
from src.storage.chunking import MAX_CHUNKS_PER_ARTICLE, build_chunks, chunk_layout
from src.storage.vector_store import VectorStore

TOPICS = ["pensiya", "nafaqa", "transport", "maktab", "soliq", "protez", "sanatoriy", "dori", "imtiyoz", "kvota",
          "notarius", "bank", "ijara", "mehnat", "kafolat", "shikoyat", "reabilitatsiya", "tibbiy", "ekspertiza",
          "guvohnoma", "subsidiya", "kredit", "grant", "stipendiya", "kommunal", "vasiylik", "aliment", "jarima",
          "litsenziya", "bojxona"]
TARGET = "kunduzgi parvarish xizmatini ko'rsatuvchi tadbirkorlar soliqlardan ozod etiladi"
FILLER = "Ushbu band bo'yicha tegishli tartib belgilanadi va vakolatli organ tomonidan qo'llaniladi. " * 3


def _article(n_paras: int = 30, target_at: int = 22, ru: bool = False) -> CanonicalArticle:
    def paras(lang):
        out = []
        for i in range(n_paras):
            word = TOPICS[i % len(TOPICS)]
            if lang == "ru":
                text = f"{i + 1}. Пункт о {word}. " + "Настоящий порядок применяется уполномоченным органом. " * 4
            else:
                text = f"{i + 1}. {word.capitalize()} masalasi. {FILLER}"
            if i == target_at:
                text += (" Дневной уход освобождается от налогов." if lang == "ru" else f" {TARGET}.")
            out.append(text)
        return "\n".join(out)

    translations = {"uz": paras("uz")}
    if ru:
        translations["ru"] = paras("ru")
    return CanonicalArticle(
        canonical_id="tax_test_art_483",
        metadata={
            "law_id": "tax_test", "law_title": {"uz": "Soliq kodeksi"}, "law_number": "O'RQ-599",
            "article_number": "483-modda", "article_title": {"uz": "Vaqtinchalik soliq imtiyozlari"},
            "source_url": "https://lex.uz/docs/1", "effective_date": "2020-01-01",
            "last_verified_date": "2026-10-01", "source_hash": "sha256:x", "category": "tax_benefits",
        },
        translations=translations,
    )


# --- chunk layout ----------------------------------------------------------------------------------------------------

def test_layout_covers_the_whole_text_and_only_the_cap_is_embedded():
    art = _article(n_paras=30 * MAX_CHUNKS_PER_ARTICLE, target_at=110)
    layout = chunk_layout(art, "uz")
    assert len(layout.texts) > MAX_CHUNKS_PER_ARTICLE
    assert build_chunks(art, "uz") == layout.texts[:MAX_CHUNKS_PER_ARTICLE]
    # spans are contiguous, cover every paragraph, and each chunk holds its own paragraphs
    assert layout.spans[0][0] == 0 and layout.spans[-1][1] == len(layout.paragraphs)
    assert all(a[1] == b[0] for a, b in zip(layout.spans, layout.spans[1:]))
    assert all(p in t for t, (s, e) in zip(layout.texts, layout.spans) for p in layout.paragraphs[s:e])


# --- vector store ------------------------------------------------------------------------------------------------------

def _rec(cid, vec, idx=None):
    r = {"canonical_id": cid, "vector": vec, "language": "uz", "status": "active", "category": "c",
         "disability_types": "[]", "embedding_model_version": "v"}
    if idx is not None:
        r["chunk_index"] = idx
    return r


def _vec(hot: int):
    v = [0.01] * settings.EMBEDDING_DIMENSION
    v[hot] = 1.0
    return v


def test_vector_store_returns_the_best_chunk_of_an_article(tmp_path):
    store = VectorStore(str(tmp_path))
    store.upsert_vectors([_rec("a_art_1", _vec(0), 0), _rec("a_art_1", _vec(1), 1), _rec("b_art_1", _vec(2), 0)])
    hits = store.search_vector(_vec(1), top_k=5)
    assert hits[0]["canonical_id"] == "a_art_1" and hits[0]["chunk_index"] == 1


def test_merge_keeps_the_chunk_of_the_strongest_vector_hit():
    a = ScoredArticle(canonical_id="x", rrf_score=0.1, vector_score=0.6, vector_chunk=("uz", 2))
    b = ScoredArticle(canonical_id="x", rrf_score=0.1, vector_score=0.8, vector_chunk=("ru", 5))
    c = ScoredArticle(canonical_id="x", rrf_score=0.1, bm25_score=3.0)
    assert merge_candidates([[a], [b], [c]], limit=5)[0].vector_chunk == ("ru", 5)


# --- choosing the part of a long unit --------------------------------------------------------------------------------

def _target_chunk(art, lang="uz"):
    layout = chunk_layout(art, lang)
    marker = TARGET if lang == "uz" else "Дневной уход"
    return next(i for i, (s, e) in enumerate(layout.spans) if any(marker in p for p in layout.paragraphs[s:e]))


def test_vector_hit_decides_its_language_and_words_decide_the_other():
    art = _article(ru=True)
    focus = focus_chunks(art, "kunduzgi parvarish soliq imtiyozi", ("uz", "ru"), vector_chunk=("ru", 1))
    assert focus["ru"] == 1                          # the vector hit, even if the words point elsewhere
    assert focus["uz"] == _target_chunk(art)         # no uz hit: the chunk sharing the rare query words


def test_cyrillic_uzbek_question_finds_the_latin_paragraph():
    art = _article()
    assert focus_chunks(art, "Кундузги парвариш хизмати солиқдан озодми?", ("uz",))["uz"] == _target_chunk(art)


def test_short_units_have_no_focus_and_are_shown_whole():
    art = _article(n_paras=2, target_at=1)
    assert focus_chunks(art, "kunduzgi parvarish", ("uz",)) == {}
    assert focused_text(art, "uz", {}, 7000) == art.get_text("uz")


def test_long_unit_shows_its_beginning_and_the_matched_part():
    art = _article()
    text = art.get_text("uz")
    assert TARGET not in text[:settings.JEV_RERANK_CHARS]           # the old cut never reached it

    head_only = focused_text(art, "uz", {}, 1500)
    assert head_only.startswith(text[:200]) and head_only.endswith("[...]") and TARGET not in head_only

    focus = focus_chunks(art, "kunduzgi parvarish xizmati soliqdan ozodmi", ("uz",))
    view = focused_text(art, "uz", focus, 1500)
    assert view.startswith("1. Pensiya masalasi")          # what the unit is about
    assert TARGET in view and "[...]" in view
    assert len(view) <= 1500 + 3 * len("\n[...]")


# --- the readers: Jev and the LLM --------------------------------------------------------------------------------------

def _ctx(art, query):
    return RetrievedArticleContext(article=art, final_score=1.0, source_tag="primary",
                                   focus=focus_chunks(art, query, ("uz",)))


@pytest.mark.asyncio
async def test_jev_reads_the_matched_part_of_a_long_unit():
    from src.retrieval.jev_ranker import JevRanker

    seen = {}

    class StubClient:
        async def decide(self, state, questions, model=None, timeout=None):
            seen["state"] = state
            return None

    await JevRanker(client=StubClient()).rank("kunduzgi parvarish soliq", [_ctx(_article(), "kunduzgi parvarish soliq")])
    assert TARGET in seen["state"]


def test_llm_context_contains_the_matched_part_of_a_long_unit():
    art = _article(n_paras=60, target_at=50)
    block = format_context_for_llm([_ctx(art, "kunduzgi parvarish soliqdan ozod")], language="uz")
    assert TARGET in block and "[...matn qisqartirildi]" in block


@pytest.mark.asyncio
async def test_reranker_attaches_the_focus_to_each_context():
    art = _article(ru=True)
    store = SimpleNamespace(get_articles_batch=lambda ids: {art.canonical_id: art})
    cand = ScoredArticle(canonical_id=art.canonical_id, rrf_score=0.5, vector_score=0.7, vector_chunk=("ru", 2))
    out = await Reranker(client=SimpleNamespace()).rerank(
        query="kunduzgi parvarish", language="ru", candidates=[cand], store=store, top_n=5, use_model=False)
    assert out[0].focus == {"ru": 2, "uz": _target_chunk(art)}
