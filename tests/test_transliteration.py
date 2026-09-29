import pytest
from src.nlp.transliteration import (
    cyrillic_to_latin,
    detect_script,
    normalize_apostrophes,
)


def test_detect_script():
    assert detect_script("Ногиронлар ҳуқуқлари") == "cyrillic"
    assert detect_script("Nogironlar huquqlari") == "latin"
    assert detect_script("12345 6789") == "unknown"


def test_uzbek_vowels_and_e_rule():
    # Word initial: e -> ye
    assert cyrillic_to_latin("ердам").lower().startswith("ye")
    assert cyrillic_to_latin("Ер").startswith("Ye")
    # After vowel: e -> ye
    assert cyrillic_to_latin("беэътибор") == "bee'tibor"
    # After consonant: e -> e
    assert cyrillic_to_latin("келди") == "keldi"
    assert cyrillic_to_latin("меҳнат") == "mehnat"
    assert cyrillic_to_latin("бер") == "ber"


def test_special_letters():
    # Yo, Yu, Ya
    assert cyrillic_to_latin("ёрдам") == "yordam"
    assert cyrillic_to_latin("юридик") == "yuridik"
    assert cyrillic_to_latin("янги") == "yangi"
    
    # O' and G'
    assert cyrillic_to_latin("ўзбекистон") == "o'zbekiston"
    assert cyrillic_to_latin("Ўзбекистон") == "O'zbekiston"
    assert cyrillic_to_latin("ғамхўрлик") == "g'amxo'rlik"
    assert cyrillic_to_latin("Ғалаба") == "G'alaba"

    # Sh, Ch
    assert cyrillic_to_latin("шахс") == "shaxs"
    assert cyrillic_to_latin("чора") == "chora"


def test_tutuq_belgisi_and_ts():
    # ъ -> '
    assert cyrillic_to_latin("эълон") == "e'lon"
    assert cyrillic_to_latin("масъулият") == "mas'uliyat"
    assert cyrillic_to_latin("мўътабар") == "mo'tabar"

    # ts
    assert cyrillic_to_latin("конституция") == "konstitutsiya"
    assert cyrillic_to_latin("цирк") == "tsirk"


def test_special_words_curated():
    assert cyrillic_to_latin("январь") == "yanvar"
    assert cyrillic_to_latin("сентябрь") == "sentabr"
    assert cyrillic_to_latin("декабрь") == "dekabr"
    assert cyrillic_to_latin("автомобиль") == "avtomobil"


def test_apostrophe_normalization():
    variations = ["o`zbekiston", "o‘zbekiston", "oʻzbekiston", "o’zbekiston", "o'zbekiston"]
    for var in variations:
        assert normalize_apostrophes(var) == "o'zbekiston"
