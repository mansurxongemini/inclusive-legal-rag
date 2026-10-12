from src.generation.prompts import build_system_prompt, format_context_for_llm


def test_plain_mode_asks_for_conditions_and_deadlines_from_the_context_only():
    prompt = build_system_prompt(language="uz", mode="plain")
    assert "ODDIY TIL REJIMI" in prompt
    assert "kimlarga" in prompt            # who qualifies
    assert "muddatlarni" in prompt          # deadlines ...
    assert "agar kontekstda bo'lsa" in prompt   # ... only when the context states them


def test_easy_read_mode_limits_sentence_length():
    prompt = build_system_prompt(language="uz", mode="easy_read")
    assert "OSON O'QISH REJIMI" in prompt
    assert "15 so'z" in prompt


def test_analysis_mode_is_structured():
    prompt = build_system_prompt(language="uz", mode="subsumption")
    assert "TAHLIL REJIMI" in prompt
    assert "Huquqiy asos" in prompt
    assert "Amaliy xulosa" in prompt


def test_context_block_carries_provenance_and_no_duplicate_points():
    import json
    from pathlib import Path
    from src.retrieval.reranker import RetrievedArticleContext
    from src.schema.canonical import CanonicalArticle

    data = json.loads(Path("data/pilot_laws/law_disability_2020.json").read_text(encoding="utf-8"))
    art = CanonicalArticle.model_validate(next(d for d in data if d["canonical_id"].endswith("_art_31")))
    block = format_context_for_llm([RetrievedArticleContext(article=art, final_score=1.0, source_tag="primary")], "uz")
    assert "Canonical ID: [law_disability_2020_art_31]" in block
    assert "O'RQ-641" in block and "2020-10-15" in block      # act number and adoption date
    assert "lex.uz" in block                                    # deep link to the official text
    assert block.count("yigirma kalendar kun") == 1             # body appears exactly once
