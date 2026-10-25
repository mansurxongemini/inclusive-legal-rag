"""A vector search must not make LanceDB log a deprecation warning (it printed one per search, 4-6 per question)."""
from src.api.app import get_store


def test_vector_search_logs_no_deprecation_warning(capfd):
    store = get_store()                              # the seeded temporary store of the suite
    hits = store.vector_store.search_vector([0.01] * 1024, top_k=3, language="uz")
    err = capfd.readouterr().err
    assert hits and "disable_scoring_autoprojection" not in err and "_distance" not in err
