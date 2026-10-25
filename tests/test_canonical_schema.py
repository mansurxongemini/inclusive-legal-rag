import json
from pathlib import Path
from src.schema.canonical import CanonicalArticle, ArticleStatus


def test_canonical_schema_validation():
    pilot_file = Path("tests/fixtures/synthetic_pilot.json")
    assert pilot_file.exists(), "Pilot file must exist"

    with open(pilot_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data) >= 8, "Expected at least 8 pilot articles"

    articles = [CanonicalArticle.model_validate(item) for item in data]
    assert len(articles) == len(data)

    # Check active vs repealed
    active_articles = [a for a in articles if a.metadata.status == ArticleStatus.ACTIVE]
    repealed_articles = [a for a in articles if a.metadata.status == ArticleStatus.REPEALED]

    assert len(active_articles) >= 7
    assert len(repealed_articles) >= 1
    assert repealed_articles[0].metadata.superseded_by == "synthetic_law_art_15"

    # Check multilingual translations and helper methods
    art15 = next(a for a in articles if a.canonical_id == "synthetic_law_art_15")
    assert "tibbiy yordam" in art15.get_text("uz").lower()
    assert "медицинская помощь" in art15.get_text("ru").lower()
    assert "medical care" in art15.get_text("en").lower()

    # Check FTS document generation
    fts_doc = art15.to_fts_document("uz")
    assert "15-modda" in fts_doc
    assert "TEST-641" in fts_doc
