import pytest

from src.generation.answer_checks import (
    banned_phrases, check_answer, leaked_ids, number_words, numbers_in, script_ok, uncited_ratio, ungrounded_numbers,
)

CONTEXT = ["Nogironligi bo'lgan shaxsga 1 500 000 so'm miqdorida bir martalik yordam beriladi. Ariza 30 kun ichida ko'riladi."]


def test_script_follows_the_question():
    assert script_ok("Кундузги парвариш хизмати солиқдан озодми?", "Кундузги парвариш хизмати учун имтиёз бор [1].")
    assert not script_ok("Кундузги парвариш хизmati солиқдан озодми?", "Kunduzgi parvarish xizmati uchun imtiyoz bor [1].")
    assert script_ok("Kunduzgi parvarish soliqdan ozodmi?", "Ha, imtiyoz bor [1].")
    assert not script_ok("Kunduzgi parvarish soliqdan ozodmi?", "Да, льгота предусмотрена [1].")
    assert script_ok("Какой размер пособия?", "Размер пособия составляет сумму [1].", language="ru")
    assert script_ok("What is the benefit?", "The benefit is paid [1].", language="en")
    assert script_ok("12345", "Javob")                      # no letters in the question: nothing to match


def test_internal_ids_must_not_reach_the_user():
    assert leaked_ids("Qonun [1] va vmq_62_2022_a9_p_16 bo'yicha", []) == ["vmq_62_2022_a9_p_16"]
    assert leaked_ids("Qonun [1] bo'yicha", ["vmq_62_2022_a9_p_16"]) == []
    assert leaked_ids("snake_case_word_here", []) == []      # no digit: not an id


def test_forbidden_wording_is_found_in_every_apostrophe_style():
    assert banned_phrases("Kontekstda bunday ma'lumot yo‘q") == ["kontekstda"]
    assert banned_phrases("В предоставленном контексте нет ответа")
    assert banned_phrases("Javob 30 kun ichida beriladi [1].") == []


def test_numbers_are_compared_with_the_sources():
    assert numbers_in("1 500 000 so'm, 30 kun, 2025-yil, 5 ta") == ["1500000", "30", "2025"]
    assert ungrounded_numbers("Yordam 1 500 000 so'm, ariza 30 kun ichida [1].", CONTEXT) == []
    assert ungrounded_numbers("Yordam 1,5 mln so'm [1].", CONTEXT) == []                  # same figure, other wording
    assert ungrounded_numbers("Ariza 60 kun ichida ko'riladi [1].", CONTEXT) == ["60"]     # invented deadline
    assert ungrounded_numbers("Menda 60 yosh", CONTEXT, question="Men 60 yoshdaman") == []   # the user's own figure
    assert ungrounded_numbers("1. Ariza bering.\n2. Hujjat yig'ing.", CONTEXT) == []         # list numbering


def test_uncited_sentences_are_counted():
    cited = "Nogironligi bo'lgan shaxs bir martalik yordam oladi [1]. Ariza o'ttiz kun ichida ko'riladi [2]."
    assert uncited_ratio(cited) == 0.0
    half = "Nogironligi bo'lgan shaxs bir martalik yordam oladi [1]. Ariza o'ttiz kun ichida ko'rib chiqiladi."
    assert uncited_ratio(half) == 0.5
    assert uncited_ratio("## Javob\nQisqa.") == 0.0


def test_check_answer_bundles_everything():
    r = check_answer("Yordam qancha?", "Yordam 2 000 000 so'm [1].", CONTEXT, language="uz")
    assert r["script_ok"] and r["ungrounded_numbers"] == ["2000000"]
    assert r["leaked_ids"] == [] and r["banned_phrases"] == []


# --- numbers written in words ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("o'n to'rt kalendar kungacha", ["14"]),
    ("haftasiga o'ttiz olti soatdan", ["36"]),
    ("ikki yuz ellik ming so'm", ["250000"]),
    ("ўн тўрт кунгача", ["14"]),
    ("тридцать шесть часов", ["36"]),
    ("до шестнадцати лет", ["16"]),
    ("nogironlar uchun uch foiz", ["3"]),          # "uchun" is not "uch"
    ("семья с детьми", []),                         # "семья" is not "семь"
])
def test_number_words_are_read(text, expected):
    assert number_words(text) == expected


def test_a_number_the_source_writes_in_words_is_grounded():
    # gold set en14: "up to 14 calendar days" from Labour Code art. 402 ("o'n to'rt kalendar kungacha")
    source = ["ish haqi saqlanmagan holda davomiyligi o'n to'rt kalendar kungacha bo'lgan ta'til beriladi"]
    assert ungrounded_numbers("Up to 14 calendar days of unpaid leave [1].", source) == []
    assert ungrounded_numbers("Up to 15 calendar days of unpaid leave [1].", source) == ["15"]


def test_hours_and_minutes_quoted_as_a_decimal_are_grounded():
    # gold set en20: "7.5 hours" from Labour Code art. 427 ("yetti soatu o'ttiz daqiqadan")
    source = ["besh kunlik ish haftasida — yetti soatu o'ttiz daqiqadan ortib ketmasligi kerak"]
    assert ungrounded_numbers("Up to 7.5 hours a day [1].", source) == []
    assert ungrounded_numbers("Up to 7.25 hours a day [1].", source) == ["725"]
    assert ungrounded_numbers("Не более 7,5 часа [1].", ["не более 7 часов 30 минут"]) == []


# --- found by the review of 2026-10-25: ordinary words must not ground an invented number --------------------------
@pytest.mark.parametrize("text,expected", [
    ("zarar yuz berganda", []),                                   # "yuz bermoq" = to occur
    ("Стороны договора", []), ("две стороны договора", ["2"]), ("семьи и дети", []), ("однако", []),
    ("o'n besh, yigirma kun", ["15", "20"]), ("ikki-uch kun", ["2", "3"]),
    ("от трехсот до трехсот шестидесяти часов", ["300", "360"]), ("четырехсот восьмидесяти часов", ["480"]),
    ("штраф пятьсот тысяч сумов", ["500000"]), ("yuz foiz", ["100"]), ("ikki yuz ellik ming so'm", ["250000"]),
])
def test_number_words_are_exact(text, expected):
    assert number_words(text) == expected


def test_a_word_that_only_looks_like_a_number_grounds_nothing():
    assert ungrounded_numbers("Bunday holda 100 foiz miqdorida tovon to'lanadi.", ["Agar zarar yuz bergan bo'lsa."]) == ["100"]
    assert ungrounded_numbers("Обязательные работы от 42 до 80 часов.",
                              ["обязательные работы от двухсот сорока до четырехсот восьмидесяти часов"]) == ["42", "80"]
