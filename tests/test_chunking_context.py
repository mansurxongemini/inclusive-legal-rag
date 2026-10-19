import pytest
from src.schema.canonical import CanonicalArticle, ArticleMetadata
from src.storage.chunking import _header, build_chunks, has_context_header, _cap_context_line


def _make_article(
    canonical_id: str = "test_law_art_1",
    law_title: str = "O'zbekiston Respublikasining Qonuni",
    law_number: str = "O'RQ-100",
    article_number: str = "1-modda",
    article_title: str = "Asosiy tushunchalar",
    chapter_number: str = None,
    annex_title: str = None,
    text_uz: str = "Ushbu modda qonunning asosiy tushunchalarini belgilaydi.",
    text_ru: str = "Настоящая статья определяет основные понятия закона.",
) -> CanonicalArticle:
    return CanonicalArticle(
        canonical_id=canonical_id,
        metadata=ArticleMetadata(
            law_id="test_law",
            law_title={"uz": law_title, "ru": "Закон Республики Узбекистан"},
            law_number=law_number,
            article_number=article_number,
            article_title={"uz": article_title, "ru": "Основные понятия"},
            chapter_number=chapter_number,
            annex_title=annex_title,
            source_url="https://lex.uz/docs/100",
            effective_date="2021-01-01",
            last_verified_date="2021-01-01",
            source_hash="sha256:dummy",
            category="social_protection",
        ),
        translations={"uz": text_uz, "ru": text_ru},
    )


def test_header_without_context_is_byte_identical():
    """Units without chapter_number or annex_title must produce byte-identical chunks."""
    art = _make_article(chapter_number=None, annex_title=None)
    assert not has_context_header(art)

    expected_head = "O'zbekiston Respublikasining Qonuni | 1-modda. Asosiy tushunchalar"
    head = _header(art, "uz")
    assert head == expected_head

    chunks = build_chunks(art, "uz")
    assert len(chunks) == 1
    assert chunks[0] == f"{expected_head}\n{art.translations['uz']}"


def test_header_with_chapter_and_annex():
    """Header appends chapter_number and annex_title when present."""
    art = _make_article(
        chapter_number="1-bob. Umumiy qoidalar",
        annex_title="Davlat xizmatlari ko'rsatish reglamenti",
    )
    assert has_context_header(art)

    head = _header(art, "uz")
    lines = head.split("\n")
    assert len(lines) == 3
    assert lines[0] == "O'zbekiston Respublikasining Qonuni | 1-modda. Asosiy tushunchalar"
    assert lines[1] == "1-bob. Umumiy qoidalar"
    assert lines[2] == "Davlat xizmatlari ko'rsatish reglamenti"

    # Multilingual behavior: Uzbek context strings are used in Russian chunks as well
    head_ru = _header(art, "ru")
    lines_ru = head_ru.split("\n")
    assert len(lines_ru) == 3
    assert lines_ru[0] == "Закон Республики Узбекистан | 1-modda. Основные понятия"
    assert lines_ru[1] == "1-bob. Umumiy qoidalar"
    assert lines_ru[2] == "Davlat xizmatlari ko'rsatish reglamenti"


def test_header_dedup_annex_contained_in_chapter():
    """Annex line is skipped if it is already contained in the chapter text."""
    art = _make_article(
        chapter_number="Davlat xizmatlari reglamenti — 1-bob. Umumiy qoidalar",
        annex_title="Davlat xizmatlari reglamenti",
    )
    assert has_context_header(art)

    head = _header(art, "uz")
    lines = head.split("\n")
    assert len(lines) == 2
    assert lines[1] == "Davlat xizmatlari reglamenti — 1-bob. Umumiy qoidalar"


def test_header_dedup_contained_in_law_title():
    """Lines contained in law title are skipped."""
    art = _make_article(
        law_title="Tibbiy xizmat ko'rsatish to'g'risidagi Nizom",
        chapter_number="1-bob. Umumiy qoidalar",
        annex_title="Tibbiy xizmat ko'rsatish to'g'risidagi Nizom",
    )
    assert has_context_header(art)

    head = _header(art, "uz")
    lines = head.split("\n")
    assert len(lines) == 2
    assert lines[1] == "1-bob. Umumiy qoidalar"
    # Annex was identical to law_title, so it was dropped
    assert "Nizom" not in lines[1]


def test_capping_word_boundary_and_ellipsis():
    """Capping cuts at word boundary <= 240 chars and appends ellipsis."""
    # Under limit
    short_text = "Qisqa bob sarlavhasi"
    assert _cap_context_line(short_text) == short_text

    # Exactly 240 chars
    exact_text = "x" * 240
    assert _cap_context_line(exact_text) == exact_text

    # Over 240 chars with spaces
    words = ["so'z" for _ in range(70)]  # each is 4 chars + space = 5 * 70 = 350 chars
    long_text = " ".join(words)
    capped = _cap_context_line(long_text)
    assert len(capped) <= 241  # 240 + '…' or word boundary + '…'
    assert capped.endswith("…")
    assert not capped[:-1].endswith(" ")

    # Single long word with no spaces
    no_space = "a" * 300
    capped_no_space = _cap_context_line(no_space)
    assert capped_no_space == "a" * 240 + "…"


def test_has_context_header_cases():
    """Tests various combinations of empty/non-empty context fields."""
    art_none = _make_article()
    assert not has_context_header(art_none)

    art_empty_str = _make_article(chapter_number="  ", annex_title="")
    assert not has_context_header(art_empty_str)

    art_chap = _make_article(chapter_number="1-bob")
    assert has_context_header(art_chap)

    art_annex = _make_article(annex_title="1-ilova")
    assert has_context_header(art_annex)

    assert not has_context_header(None)
