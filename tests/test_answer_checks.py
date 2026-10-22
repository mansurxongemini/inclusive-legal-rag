from src.generation.answer_checks import (
    banned_phrases, check_answer, leaked_ids, numbers_in, script_ok, uncited_ratio, ungrounded_numbers,
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
