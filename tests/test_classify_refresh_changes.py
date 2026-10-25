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
