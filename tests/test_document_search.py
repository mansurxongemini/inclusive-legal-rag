"""
Document search of the corpus browser (GET /api/v1/inclusive/documents?q=..., the admin panel's "Qonunlar bazasi").

It ran one full-table scan per act (518 on the live store): "641" took 90 s, and the endpoint is public. Now one pass
finds the acts with a matching unit; acts whose number or title holds the query come first.
"""
from src.schema.canonical import CanonicalArticle
from src.storage.fts_store import SqliteFtsStore


def _unit(cid, law_id, number, title, text):
    return CanonicalArticle(
        canonical_id=cid,
        metadata={"law_id": law_id, "law_title": {"uz": title}, "law_number": number, "article_number": "1-modda",
                  "article_title": {"uz": "Modda"}, "source_url": "https://lex.uz/docs/-5641999#-5642000",
                  "effective_date": "2020-01-01", "last_verified_date": "2026-10-01", "source_hash": "sha256:x",
                  "category": "disability_rights"},
        translations={"uz": text},
    )


def _store(tmp_path):
    store = SqliteFtsStore(str(tmp_path / "legal_rag.db"))
    for i in range(30):                                   # many acts: a per-act scan shows up as many statements
        store.upsert_article(_unit(f"act{i}_art_1", f"act{i}", f"VMQ-{i}", f"Qaror {i}", "Oddiy matn."))
    store.upsert_article(_unit("law641_art_29", "law641", "O'RQ-641", "Nogironligi bo'lgan shaxslarning huquqlari",
                               "Nogironligi bo'lgan shaxsning faksimil imzosi."))
    store.upsert_article(_unit("vmq62_p_1", "vmq62", "VMQ-62", "Ekspertiza nizomi", "O'RQ-641 ga muvofiq ko'rik."))
    return store


def test_an_act_is_found_by_the_text_of_its_norm_and_by_its_number(tmp_path):
    store = _store(tmp_path)
    assert [d["law_number"] for d in store.list_documents(search_query="faksimil")] == ["O'RQ-641"]
    # the number itself first, then the act that mentions it in a norm; URLs in the metadata do not match
    assert [d["law_number"] for d in store.list_documents(search_query="641")] == ["O'RQ-641", "VMQ-62"]
    assert store.list_documents(search_query="100%") == []          # LIKE wildcards typed by the user are literal


def test_the_search_is_one_pass_not_one_scan_per_act(tmp_path, monkeypatch):
    store = _store(tmp_path)
    statements = []
    original = store._get_connection

    def traced():
        conn = original()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(store, "_get_connection", traced)
    store.list_documents(search_query="faksimil")
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) <= 2, selects
