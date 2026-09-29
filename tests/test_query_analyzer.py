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
