import pytest
from src.ingestion.universal_engine import (
    DocumentSpec,
    IngestionState,
    UniversalAutonomousEngine,
    UniversalParser,
)
from src.schema.canonical import TranslationProvenanceType


def test_universal_parser_regulation_clauses():
    sample_html = """
    <div id="divCont">
        <div class="lx_elem2">Buttons</div>
        <div class="COMMENT">Comment</div>
        <div>1. Birinchi band matni bu yerda joylashgan.</div>
        <div>Ushbu bandning davomi quyidagicha davom etadi.</div>
        <div>2. Ikkinchi band matni fuqarolarning huquqlari haqida.</div>
        <div>3. Uchinchi band matni esa majburiyatlar haqida.</div>
    </div>
    """
    spec = DocumentSpec(
        slug="test_reg_1",
        category="regulations",
        doc_number="1-sonli Qaror",
        title_uz="Sinov Nizomi",
        effective_date="2024-01-01",
        url_uz="https://lex.uz/docs/1111",
        parser_type="regulation_clause",
    )

    articles = UniversalParser.parse_regulation_clauses(sample_html, spec)
    assert len(articles) == 3
    assert articles[0].canonical_id == "test_reg_1_art_1"
    assert articles[0].metadata.article_number == "1-band"
    assert "Birinchi band matni" in articles[0].translations["uz"]
    assert "davomi quyidagicha" in articles[0].translations["uz"]
    assert articles[1].canonical_id == "test_reg_1_art_2"
    assert articles[2].canonical_id == "test_reg_1_art_3"


def test_universal_parser_statutory_articles():
    sample_html = """
    <div id="divCont">
        <div>Modda 1. Qonunning asosiy maqsadi</div>
        <div>Ushbu Qonun barcha fuqarolarning huquqlarini kafolatlaydi.</div>
        <div>Modda 2. Qonunchilik hujjatlari</div>
        <div>Ushbu sohadagi qonunchilik Konstitutsiya va ushbu Qonundan iborat.</div>
    </div>
    """
    spec = DocumentSpec(
        slug="test_law_1",
        category="laws",
        doc_number="O'RQ-999",
        title_uz="Sinov Qonuni",
        effective_date="2024-01-01",
        url_uz="https://lex.uz/docs/2222",
        parser_type="statutory_article",
    )

    articles = UniversalParser.parse_statutory_articles(sample_html, spec)
    assert len(articles) == 2
    assert articles[0].canonical_id == "test_law_1_art_1"
    assert articles[0].metadata.article_title["uz"] == "Qonunning asosiy maqsadi"
    assert "kafolatlaydi" in articles[0].translations["uz"]


def test_ingestion_state_model():
    state = IngestionState()
    assert state.total_articles == 0
    assert len(state.completed_slugs) == 0

    state.completed_slugs["vmq_172"] = {
        "title": "YHQ",
        "category": "regulations",
        "count": 186,
    }
    state.total_articles = 186

    dumped = state.model_dump()
    loaded = IngestionState.model_validate(dumped)
    assert "vmq_172" in loaded.completed_slugs
    assert loaded.completed_slugs["vmq_172"]["count"] == 186
