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
