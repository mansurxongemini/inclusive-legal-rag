import pytest
from pathlib import Path

from src.ingestion.url_importer import LexUrlImporter, UrlImportRequest


def test_url_importer_html_parsing():
    sample_html = """
    <html>
      <head><title>O‘RQ-888-сон 20.05.2024. Imtiyozlar to'g'risida</title></head>
      <body>
        <div class="document">
          <div class="lx_elem2"><button>Audioni tinglash</button></div>
          <div class="lx_elem"><div id="-1">1-modda. Soliq imtiyozlari</div></div>
          <div>1-guruh va 2-guruh nogironligi bo'lgan shaxslar daromad solig'idan ozod etiladi.</div>
          <div class="lx_elem"><div id="-2">2-modda. Maxsus kvotalar</div></div>
          <div>Ish beruvchilar uchun 3 foizli maxsus ish o'rinlari kvotasi belgilanadi.</div>
        </div>
      </body>
    </html>
    """
    importer = LexUrlImporter()
    req = UrlImportRequest(url="https://lex.uz/uz/docs/-888")
    articles, law_num, title = importer.parse_lex_html(sample_html, "https://lex.uz/uz/docs/-888", req)

    assert len(articles) == 2
    assert "888" in law_num
    assert articles[0].metadata.article_number == "1-modda"
    assert articles[1].metadata.article_number == "2-modda"
    assert articles[0].metadata.source_url == "https://lex.uz/uz/docs/-888"




def test_document_inspector_with_table():
    from src.ingestion.document_inspector import DocumentInspector

    sample_html = """
    <html>
      <head><title>VMQ-777-сон 01.01.2025. Reja to'g'risida</title></head>
      <body>
        <div class="document">
          <p>1. Quyidagi tadbirlar rejasi tasdiqlansin:</p>
          <table>
            <tr><th>Bosqich</th><th>Mas'ul organ</th><th>Muddati</th></tr>
            <tr><td>1-bosqich</td><td>Ijtimoiy agentlik</td><td>Doimiy</td></tr>
            <tr><td>2-bosqich</td><td>Transport vazirligi</td><td>Har oyda</td></tr>
          </table>
        </div>
      </body>
    </html>
    """
    inspector = DocumentInspector()
    report = inspector.inspect_html(sample_html, "https://lex.uz/uz/docs/-777")
    assert report.success is True
    assert report.tables_count == 1
    table_unit = [u for u in report.units if u.is_table][0]
    assert "Bosqich" in table_unit.markdown_table
    assert "Ijtimoiy agentlik" in table_unit.exact_bge_prompt
    assert "Semantik qatorlar" in table_unit.exact_bge_prompt


@pytest.mark.asyncio
async def test_url_importer_differential_logic(tmp_path, monkeypatch):
    import httpx
    from src.storage.hybrid_store import HybridStore

    # Use isolated test store in tmp_path
    test_store = HybridStore(storage_dir=str(tmp_path / "storage"))
    importer = LexUrlImporter(store=test_store, qonunlar_dir=str(tmp_path / "qonunlar"))

    doc_v1 = """
    <html>
      <head><title>O‘RQ-999-сон 01.01.2025. Sinov qonuni</title></head>
      <body>
        <div class="document">
          <p>1-modda. Asosiy qoida</p>
          <p>Nogironligi bo'lgan shaxslarga barcha imtiyozlar kafolatlanadi.</p>
          <p>2-modda. Ish o'rni kvotasi</p>
          <p>Kompaniyalar uchun kamida 3 foiz ish o'rni zaxiralanadi.</p>
        </div>
      </body>
    </html>
    """.strip().encode("utf-8")

    class MockResp:
        def __init__(self, content, headers=None):
            self.status_code = 200
            self.content = content
            self.text = content.decode("utf-8")
            self.headers = headers or {"content-disposition": "attachment;filename=\"O‘RQ-999 01.01.2025.doc\""}

    # Mock httpx.AsyncClient.get
    async def mock_get(self, url, headers=None):
        return MockResp(doc_v1)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    # 1-RUN: Brand new document
    req = UrlImportRequest(url="https://lex.uz/uz/docs/-999")
    res1 = await importer.import_from_url(req)
    assert res1.status == "new"
    assert res1.articles_imported == 2
    assert res1.articles_new == 2

    # 2-RUN: Exact same document (Unchanged)
    res2 = await importer.import_from_url(req)
    assert res2.status == "unchanged"
    assert res2.articles_imported == 0
    assert res2.articles_unchanged == 2

    # 3-RUN: Amended document (modifying 2-modda from 3% to 4%)
    doc_v2 = """
    <html>
      <head><title>O‘RQ-999-сон 01.01.2025. Sinov qonuni</title></head>
      <body>
        <div class="document">
          <p>1-modda. Asosiy qoida</p>
          <p>Nogironligi bo'lgan shaxslarga barcha imtiyozlar kafolatlanadi.</p>
          <p>2-modda. Ish o'rni kvotasi</p>
          <p>Kompaniyalar uchun kamida 4 foiz ish o'rni zaxiralanadi (yangilandi).</p>
        </div>
      </body>
    </html>
    """.strip().encode("utf-8")

    async def mock_get_v2(self, url, headers=None):
        return MockResp(doc_v2)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get_v2)

    res3 = await importer.import_from_url(req)
    assert res3.status == "amended"
    assert res3.articles_imported == 1  # Only 2-modda re-indexed!
    assert res3.articles_updated == 1
    assert res3.articles_unchanged == 1  # 1-modda saved without re-embedding!

    # Clean up test doc file from data/qonunlar
    test_doc = Path("data/qonunlar/o_rq_999.doc")
    if test_doc.exists():
        test_doc.unlink()

