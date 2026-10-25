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
