"""
Legal-force weights used in fusion and reranking (src/retrieval/hierarchy.py), and the scope rule of the gate.

Measured on the gold set (2026-10-25): the Pension Law (938-XII) weighed 0.68 like a departmental order, and Huquq+
posts weighed up to 1.00 (a post titled after the Constitution), so "who is entitled to a disability pension" was
answered from an allowance regulation and two posts instead of article 15 of the Pension Law.
"""
import pytest

from src.retrieval.hierarchy import StateOrganHierarchy as H
from src.retrieval.jev_ranker import SCOPE_QUESTION


@pytest.mark.parametrize("number,title", [
    ("938-XII", "Fuqarolarning davlat pensiya ta'minoti to'g'risida"),
    ("343-I", "Mehnatni muhofaza qilish to'g'risida"),
    ("258-II", "Fuqarolarning o'zini o'zi boshqarish organlari to'g'risida"),
    ("O'RQ-641", "Nogironligi bo'lgan shaxslarning huquqlari to'g'risida"),
])
def test_laws_of_every_numbering_weigh_as_laws(number, title):
    assert H.evaluate_hierarchy(title, number).tier_level == 2


def test_annex_numbers_are_not_mistaken_for_laws():
    assert H.evaluate_hierarchy("Ilova", "1-ilova").tier_level != 2


def test_commentary_never_outranks_a_statute():
    post = H.calculate_hierarchy_boost("Konstitutsiyamizda nogironligi bo'lgan shaxslar uchun qanday yangiliklar?",
                                       "Huquq+", "inclusive_education", None, source_type="huquqplus")
    law = H.calculate_hierarchy_boost("Fuqarolarning davlat pensiya ta'minoti to'g'risida", "938-XII",
                                      "pensions_and_benefits", "1993-09-03")
    assert post == H.COMMENTARY_WEIGHT < law


def test_every_right_of_the_disability_law_is_in_scope():
    # "What is the facsimile signature of a person with a disability?" (Law 641, art. 29) was refused as out of scope
    assert "facsimile signature" in SCOPE_QUESTION["criteria"]["in_scope"]
