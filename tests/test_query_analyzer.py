import pytest
from src.nlp.query_analyzer import QueryAnalyzer


def test_language_detection():
    # Uzbek Latin
    res_uz = QueryAnalyzer.analyze("Nogironligi bo'lgan shaxslarga qanday imtiyozlar bor?")
    assert res_uz.detected_language == "uz"
    assert res_uz.detected_script == "latin"

    # Uzbek Cyrillic
    res_uz_cyr = QueryAnalyzer.analyze("Ногиронлиги бўлган шахсларга қандай имтиёзлар бор?")
    assert res_uz_cyr.detected_language == "uz"
    assert res_uz_cyr.detected_script == "cyrillic"
    assert "imtiyozlar" in res_uz_cyr.normalized_query

    # Russian
    res_ru = QueryAnalyzer.analyze("Какие льготы предусмотрены для инвалидов 2 группы?")
    assert res_ru.detected_language == "ru"
    assert res_ru.detected_script == "cyrillic"

    # English
    res_en = QueryAnalyzer.analyze("What are the employment rights for persons with disabilities?")
    assert res_en.detected_language == "en"
    assert res_en.detected_script == "latin"


def test_article_and_law_extraction():
    res = QueryAnalyzer.analyze("15-modda O'RQ-641 bo'yicha tibbiy yordam")
    assert res.target_article_number == "15-modda"
    assert res.target_law_number == "O'RQ-641"

    res_ru = QueryAnalyzer.analyze("что говорит статья 42 закона ЗРУ-641?")
    assert res_ru.target_article_number == "42-modda"
    assert res_ru.target_law_number == "O'RQ-641"


def test_disability_types_extraction():
    res_vis = QueryAnalyzer.analyze("ko'zi ojiz fuqarolar uchun qanday qulayliklar bor?")
    assert "visual" in res_vis.extracted_disability_types

    res_phys = QueryAnalyzer.analyze("nogironlar aravachasi va harakatlanish imkoniyati")
    assert "physical" in res_phys.extracted_disability_types


# Uzbek written in Cyrillic the way people type it: no ў/ғ/қ/ҳ, with suffixes ("ногиронман", "боламга").
UZBEK_CYRILLIC_PLAIN = [
    "Мен 2 гурух ногиронман, стажим канча булиши шарт?",
    "Боламга аравача ва протез каердан олинади?",
    "Инсон марказидан ваучер чикди, кандай ишлатаман?",
    "Санаторийга йулланма олиш навбати кандай?",
    "Нафака олиш учун нима килиш керак",
    "Ногиронлик пенсияси канча булади?",
    "Компьютер олиб бериладими ногирон болага?",  # ь in a loanword must not outweigh the Uzbek evidence
]

RUSSIAN_QUESTIONS = [
    "Какая пенсия положена инвалиду первой группы?",
    "Как оформить инвалидность ребенку?",
    "Где получить протез для ребенка?",
    "Какие льготы предусмотрены для инвалидов 2 группы?",
    "Можно ли уволить работника с инвалидностью?",
    "Положена ли коляска бесплатно?",
    "Что делать при отказе в назначении пособия?",
    "Куда обращаться за путевкой в санаторий?",
    "Мой сын инвалид, как получить ваучер",
    "Нужна ли справка МСЭК для получения пенсии",
]


@pytest.mark.parametrize("question", UZBEK_CYRILLIC_PLAIN)
def test_uzbek_cyrillic_without_special_letters_is_uzbek(question):
    assert QueryAnalyzer.detect_language(question) == "uz"


@pytest.mark.parametrize("question", RUSSIAN_QUESTIONS)
def test_russian_questions_stay_russian(question):
    assert QueryAnalyzer.detect_language(question) == "ru"


def test_russian_only_letters_do_not_mark_uzbek_text_as_russian_when_uzbek_evidence_wins():
    # ь and ы are Russian letters, but one loanword is not enough against two Uzbek words
    assert QueryAnalyzer.detect_language("Ногиронлиги бор шахсга компьютер берилади") == "uz"
    # ... and they are what keeps a keyword-free Russian question Russian
    assert QueryAnalyzer.detect_language("Положены ли льготы?") == "ru"


# --- English questions are recognised even without legal vocabulary (the service answers Uzbek only) ---------------------

@pytest.mark.parametrize("question", [
    "Hello, can you help me with my rights?",
    "I want to apply for a pension, what documents do I need?",
    "Please tell me about the benefits that you can get",
    "Where is the nearest office for disabled people?",
])
def test_english_questions_without_legal_keywords_are_detected(question):
    assert QueryAnalyzer.detect_language(question) == "en"


@pytest.mark.parametrize("question", [
    "Nogironligi bo'lgan shaxslarga pensiya qancha to'lanadi?",
    "Ish beruvchi nogironlarni ishga qabul qilishi shartmi?",
    "Telegram bot orqali ariza berish mumkinmi?",
    "TIEK qarori ustidan qayerga shikoyat qilinadi?",
    "Ногирони бўлган шахсларга нафақа қанча тўланади?",
])
def test_uzbek_questions_are_never_taken_for_english(question):
    assert QueryAnalyzer.detect_language(question) == "uz"
