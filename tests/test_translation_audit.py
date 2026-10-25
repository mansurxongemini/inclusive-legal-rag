"""The translation audit (scripts/audit_translations.py): a Russian text that is the translation of another unit of the same act is flagged."""
import numpy as np

from src.ingestion.translation_alignment import closer_matches


def test_a_shifted_russian_text_is_flagged_and_an_aligned_one_is_not():
    a, b, c = np.eye(3, dtype=np.float32)
    uz = {"vmq_1_2024_a1_p_7": a, "vmq_1_2024_a1_p_7_2": b, "vmq_1_2024_a1_p_8": c}
    ru = {"vmq_1_2024_a1_p_7": a * 0.9 + b * 0.1,       # its own translation
          "vmq_1_2024_a1_p_7_2": a,                     # the Russian point 7 of the other list
          "vmq_1_2024_a1_p_8": c}
    scores = {k: float(uz[k] @ ru[k] / np.linalg.norm(ru[k])) for k in uz}
    flagged = closer_matches(scores, uz, ru, margin=0.06)
    assert set(flagged) == {"vmq_1_2024_a1_p_7_2"} and flagged["vmq_1_2024_a1_p_7_2"][0] == "vmq_1_2024_a1_p_7"


def test_units_of_different_acts_are_never_compared():
    a, b = np.eye(2, dtype=np.float32)
    uz = {"vmq_1_2024_p_1": a, "vmq_2_2024_p_1": b}
    ru = {"vmq_1_2024_p_1": b * 0.6 + a * 0.4, "vmq_2_2024_p_1": b}
    scores = {k: float(uz[k] @ ru[k] / np.linalg.norm(ru[k])) for k in uz}
    assert closer_matches(scores, uz, ru, margin=0.06) == {}


def test_russian_points_glued_to_the_previous_one_are_moved_to_their_own_units():
    # review 2026-10-25: Russian point 44 of VMQ-62 annex 9 held 46-48; the Uzbek edition had them as units
    from src.ingestion.translation_alignment import split_russian_overflow
    units = {
        "vmq_62_2022_a9_p_44": ("44. To'rt daraja.", "44. Четыре степени.\n46. Критерий I группы.\n47. Критерий II группы."),
        "vmq_62_2022_a9_p_46": ("46. I guruh mezoni.", ""),
        "vmq_62_2022_a9_p_47": ("47. II guruh mezoni.", ""),
        "vmq_62_2022_a9_p_48": ("48. III guruh mezoni.", "48. Критерий III группы."),
    }
    assert split_russian_overflow(units) == {
        "vmq_62_2022_a9_p_44": "44. Четыре степени.",
        "vmq_62_2022_a9_p_46": "46. Критерий I группы.",
        "vmq_62_2022_a9_p_47": "47. Критерий II группы.",
    }


def test_a_sub_list_inside_a_point_is_left_alone():
    from src.ingestion.translation_alignment import split_russian_overflow
    units = {"x_p_5": ("5. Ro'yxat: 1. bir 2. ikki", "5. Перечень:\n1. один\n2. два"), "x_p_6": ("6. Keyingi.", "6. Следующий.")}
    assert split_russian_overflow(units) == {}
