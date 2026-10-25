"""scripts/classify_refresh_changes.py: a re-split act is a re-parse, an act with a new sentence is an amendment."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "classify_refresh_changes", Path(__file__).resolve().parents[1] / "scripts" / "classify_refresh_changes.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_resplit_points_are_structural_and_new_text_is_content():
    before = {"vmq_62_2022": mod.sentences("44. To'rt daraja. 46. Birinchi guruh mezoni. 47. Ikkinchi guruh mezoni.")}
    after_split = {"vmq_62_2022": mod.sentences("44. To'rt daraja.") | mod.sentences("46. Birinchi guruh mezoni.")
                   | mod.sentences("47. Ikkinchi guruh mezoni.")}
    after_amended = {"vmq_62_2022": after_split["vmq_62_2022"] | mod.sentences("48. Chernobil qatnashchilari.")}
    rows = [(1, "document_amended", "law:vmq_62_2022"), (2, "norm_amended", "vmq_62_2022_a9_p_44")]
    assert mod.classify(before, after_split, rows)["structural"] == [1, 2]
    content = mod.classify(before, after_amended, rows)["content"]
    assert [c[0] for c in content] == [1, 2] and "chernobil qatnashchilari" in content[0][2][0]



def test_a_removed_sentence_is_a_change_too():
    # review 2026-10-25: a repealed point only removes text; "nothing new" was taken for "nothing changed"
    before = {"act": mod.sentences("1. Nogironligi bo'lgan shaxslar yo'l haqidan ozod qilinadi. 2. Ariza 10 kun ichida ko'riladi.")}
    after = {"act": mod.sentences("2. Ariza 10 kun ichida ko'riladi.")}
    result = mod.classify(before, after, [(1, "document_amended", "law:act")])
    assert result["structural"] == [] and result["content"][0][0] == 1


def test_a_post_that_cannot_be_affected_by_the_amendment_is_recognised():
    before = {"law_x_art_28": ("Sud ishlarini yuritishda jinoyat, fuqarolik ishlari bo'yicha surdotarjimon beriladi.", "28-modda"),
              "law_x_art_29": ("Faksimile imzo ishlatiladi.", "29-modda")}
    after = {**before, "law_x_art_28": ("Sud ishlarini yuritishda konstitutsiyaviy, jinoyat, fuqarolik ishlari bo'yicha "
                                        "surdotarjimon beriladi.", "28-modda")}
    changes = mod.changed_units(before, after)
    assert list(changes) == ["law_x_art_28"]
    assert not mod.mentions("Nogironligi bo'lgan shaxs faksimile imzodan foydalanishi mumkin (29-modda).", changes)
    assert mod.mentions("Qonunning 28-moddasiga ko'ra sudda surdotarjimon beriladi.", changes)       # names the unit
    assert mod.mentions("Sud ishlarini yuritishda jinoyat, fuqarolik ishlari bo'yicha surdotarjimon beriladi.", changes)
    assert not mod.mentions("Qonunning 128-moddasi boshqa narsa haqida.", changes)                    # 128 is not 28


def test_a_post_that_restates_the_old_rule_in_its_own_words_stays_open():
    # VMQ-405 point 29: the deadline moved from the 16th to the 26th; a post said "16-sanasiga qadar" in its own sentence
    before = {"vmq_405_a1_p_29": ("29. Xizmat ko'rsatilgan oydan keyingi oyning 16-sanasiga qadar subsidiya uchun murojaat qiladi.", "29-band")}
    after = {"vmq_405_a1_p_29": ("29. Xizmat ko'rsatilgan oydan keyingi oyning 26-sanasiga qadar subsidiya uchun murojaat qiladi.", "29-band")}
    changes = mod.changed_units(before, after)
    assert mod.mentions("Ish beruvchi subsidiyani olish uchun oyning 16-sanasiga qadar ariza beradi.", changes)
    assert not mod.mentions("Ish beruvchi subsidiya olish uchun ariza beradi.", changes)
