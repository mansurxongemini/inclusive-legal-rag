from src.ingestion.lex_parser import parse_law_text_file


def test_lex_parser_from_text():
    sample_text = """
    O'ZBEKISTON RESPUBLIKASINING QONUNI O'RQ-999
    
    1-modda. Qonunning maqsadi
    Ushbu Qonunning maqsadi fuqarolarning ijtimoiy huquqlarini himoya qilishdan iborat.
    1. Davlat fuqarolarga ijtimoiy kafolatlarni ta'minlaydi.
    2. Mazkur norma 15-modda talablariga muvofiq amalga oshiriladi.

    2-modda. Qonunchilik hujjatlari
    Ijtimoiy himoya to'g'risidagi qonunchilik ushbu Qonun va boshqa hujjatlardan iborat.
    """

    articles = parse_law_text_file(sample_text, "sample_law.txt")
    assert len(articles) == 2
    art1 = articles[0]
    assert art1.metadata.article_number == "1-modda"
    assert "fuqarolarning ijtimoiy huquqlarini" in art1.translations["uz"]
    assert len(art1.points) == 2
    assert art1.points[0].point_id == "1"

    # Cross reference check
    refs = [r.target_canonical_id for r in art1.metadata.cross_references]
    assert "art_15" in refs
