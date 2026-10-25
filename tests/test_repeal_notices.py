"""
Repeal notices (src/retrieval/repeal_notices.py): a question about an act the corpus repealed gets the repeal clause as
its first context. Gold items uz17/en17 lost the clause (it was the 8th of 8 contexts) when the corpus grew, and the
answers described the repealed resolution 257 as current law.
"""
import pytest

from src.retrieval.repeal_notices import build_index, matching_acts

ROWS = [
    ("vmq_769_2021_p_5", "5. Vazirlar Mahkamasining “Nogironligi bo'lgan shaxslar ishlari bo'yicha idoralararo kengash "
                         "faoliyatini tashkil etish to'g'risida” 2021-yil 29-apreldagi 257-son qarori o'z kuchini "
                         "yo'qotgan deb hisoblansin."),
    ("vmq_405_2025_p_7", "7. Vazirlar Mahkamasining “Nogironligi bo'lgan shaxslarning bandligiga ko'maklashishni "
                         "rag'batlantirish chora-tadbirlari to'g'risida” 2022-yil 20-apreldagi 203-son qarorining 1 va "
                         "2-bandlari hamda unga 1-ilova o'z kuchini yo'qotgan deb hisoblansin."),
    ("vmq_741_2024_a1_p_2", "2. Vazirlar Mahkamasining 2022-yil 8-fevraldagi 62-son qarori bilan tasdiqlangan "
                            "Nizomning 25-bandi o'z kuchini yo'qotgan deb hisoblansin."),
    ("law_disability_2020_art_46", "Quyidagilar o'z kuchini yo'qotgan deb topilsin:\n1) O'zbekiston Respublikasining "
                                   "1991-yil 18-noyabrda qabul qilingan “O'zbekiston Respublikasida nogironlarni "
                                   "ijtimoiy himoya qilish to'g'risida”gi 422-XII-sonli Qonuni (Axborotnomasi, 1992-yil, "
                                   "№ 2, 78-modda);"),
    ("vmq_62_2022_a13_p_7", "7. Vazirlar Mahkamasining “Hukumatning ayrim qarorlariga o'zgartirish va qo'shimchalar "
                            "kiritish, shuningdek ba'zilarini o'z kuchini yo'qotgan deb hisoblash to'g'risida” 2016-yil "
                            "5-fevraldagi 31-son qarorida: a) 2-band quyidagi tahrirda bayon etilsin"),
]
INDEX = build_index(ROWS)


@pytest.mark.parametrize("question,expected", [
    ("Vazirlar Mahkamasining 2021-yil 29-apreldagi 257-son qaroriga ko'ra kengash qanday ishlaydi?", ["vmq_769_2021_p_5"]),
    ("How does the council work under Cabinet of Ministers Resolution No. 257 of 29 April 2021?", ["vmq_769_2021_p_5"]),
    ("Что предусматривают пункты 1 и 2 постановления Кабинета Министров № 203 от 20 апреля 2022 года?", ["vmq_405_2025_p_7"]),
    ("1991-yilgi 422-XII qonunga ko'ra qanday imtiyozlar bor?", ["law_disability_2020_art_46"]),
])
def test_a_named_repealed_act_finds_its_repeal_clause(question, expected):
    assert [a.canonical_id for a in matching_acts(question, INDEX)] == expected


@pytest.mark.parametrize("question", [
    "Vazirlar Mahkamasining 2022-yil 8-fevraldagi 62-son qarori bo'yicha TIEK qachon ko'rik o'tkazadi?",  # only point 25 repealed
    "Как работает постановление Кабинета Министров № 203 от 20 апреля 2022 года?",                      # points 1-2 only
    "VMQ-257 qarori nima haqida?",                                                                      # no year: not the same act for sure
    "Prezidentning 2021-yil 257-son farmoni nima deydi?",                                                # another type of act
    "Vazirlar Mahkamasining 2016-yil 31-son qarori nima deydi?",                                         # amended, not repealed
])
def test_no_notice_without_a_strict_match(question):
    assert matching_acts(question, INDEX) == []


@pytest.mark.asyncio
async def test_the_repeal_clause_becomes_the_first_context(monkeypatch):
    from types import SimpleNamespace

    from src.api.app import get_store
    from src.nlp.query_analyzer import QueryAnalyzer
    from src.retrieval import pipeline

    store = get_store()
    clause = store.get_article("law_disability_2020_art_49")       # stands in for a repeal clause of the seed corpus
    monkeypatch.setattr(pipeline, "repeal_notices", lambda question, st: [clause])
    client = SimpleNamespace(is_mock=True)
    res = await pipeline.retrieve_contexts(
        analysis=QueryAnalyzer.analyze("Nogironligi bo'lgan shaxslarga ijtimoiy yordam qanday ko'rsatiladi?"),
        store=store, client=client, top_k=10, max_extra=2, rerank_top_n=5, use_vector=False, use_llm=False,
        apply_gate=False)
    ids = [c.article.canonical_id for c in res.contexts]
    assert ids[0] == "law_disability_2020_art_49" and ids.count("law_disability_2020_art_49") == 1
    assert res.signals["repeal_notices"] == ["law_disability_2020_art_49"]


# --- found by the review of 2026-10-25 -------------------------------------------------------------------------------
AMENDING = [
    ("vmq_741_2024_a1_p_2", "2. Vazirlar Mahkamasining 2022-yil 8-fevraldagi 62-son qarorida: a) 2-bandning ikkinchi "
                            "xatboshisi quyidagi tahrirda bayon etilsin: Vrach-ekspertlar 6 — 8 nafar; g) 5-ilova o'z "
                            "kuchini yo'qotgan deb hisoblansin."),
    ("reg_1060_2001_p_4", "4. Mazkur buyruq kuchga kirishi bilan Sog'liqni saqlash vazirligining 1994-yil 28-iyuldagi "
                          "350-sonli buyrug'i o'z kuchini yo'qotgan deb hisoblansin."),
]
INDEX2 = build_index(AMENDING)


def test_an_amending_act_marks_only_the_item_that_lost_force():
    acts = INDEX2["62"]
    assert len(acts) == 1 and acts[0].points == frozenset({"ilova:5"})
    # point 2 was amended, not repealed; point 30 is not mentioned at all
    for q in ("Vazirlar Mahkamasining 2022-yil 8-fevraldagi 62-son qarori bilan tasdiqlangan Nizomning 2-bandi nima deydi?",
              "Vazirlar Mahkamasining 2022-yil 8-fevraldagi 62-son qarorining 30-bandi amaldami?"):
        assert matching_acts(q, INDEX2) == []
    assert [a.canonical_id for a in matching_acts(
        "Vazirlar Mahkamasining 2022-yil 62-son qaroriga 5-ilova amaldami?", INDEX2)] == ["vmq_741_2024_a1_p_2"]


def test_the_type_the_question_names_must_be_the_type_of_the_repealed_act():
    # a ministry order (type unknown in the index) is not the Cabinet resolution the question names
    assert matching_acts("Vazirlar Mahkamasining 1994-yil 350-son qarori amaldami?", INDEX2) == []
    # a question that names no type cannot be matched safely
    assert matching_acts("2021-yil 29-apreldagi 257-son hujjat amaldami?", INDEX) == []


@pytest.mark.parametrize("question", [
    "Vazirlar Mahkamasining 2021-yil 29-apreldagi 257-sonli qarori amaldami?",
    "Вазирлар Маҳкамасининг 2021 йил 29 апрелдаги 257-сон қарори амалдами?",
])
def test_common_spellings_of_the_act_number_and_type_are_understood(question):
    assert [a.canonical_id for a in matching_acts(question, INDEX)] == ["vmq_769_2021_p_5"]


def test_the_year_is_read_however_long_the_title_is():
    long_title = "“" + "juda uzun nom " * 30 + "”"
    idx = build_index([("x_p_1", f"1. Vazirlar Mahkamasining 2019-yil 3-maydagi {long_title} 391-son qarori o'z kuchini "
                                 "yo'qotgan deb hisoblansin.")])
    assert idx["391"][0].year == "2019"


def test_the_index_is_rebuilt_after_a_write(tmp_path):
    from src.retrieval.repeal_notices import _store_index
    from src.schema.canonical import CanonicalArticle
    from src.storage.hybrid_store import HybridStore

    store = HybridStore(str(tmp_path / "store"))
    assert _store_index(store) == {}
    store.fts_store.upsert_article(CanonicalArticle(
        canonical_id="vmq_769_2021_p_5",
        metadata={"law_id": "vmq_769_2021", "law_title": {"uz": "Qaror"}, "law_number": "VMQ-769", "article_number": "5-band",
                  "article_title": {"uz": "Band"}, "source_url": "https://lex.uz/docs/-1", "effective_date": "2021-01-01",
                  "last_verified_date": "2026-10-01", "source_hash": "sha256:x", "category": "disability_rights"},
        translations={"uz": ROWS[0][1]}))
    assert "257" in _store_index(store)
