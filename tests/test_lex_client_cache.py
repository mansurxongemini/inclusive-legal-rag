"""A forced fetch (refresh) bypasses the HTML cache unless the page is younger than fresh_within_s (resuming)."""
import os
import time

from src.ingestion.lex_client import LexClient, doc_cache_name


class _Resp:
    status_code = 200
    text = '<div class="lx_elem">yangi</div>'


def _client(tmp_path, fresh_within_s=0.0):
    c = LexClient(cache_dir=str(tmp_path), min_delay=0, fresh_within_s=fresh_within_s)
    c.requests = []
    c._request = lambda method, url, **kw: c.requests.append(url) or _Resp()
    return c


def _cache(tmp_path, doc_id, age_s):
    path = tmp_path / f"{doc_cache_name(doc_id)}.html"
    path.write_text('<div class="lx_elem">eski</div>', encoding="utf-8")
    then = time.time() - age_s
    os.utime(path, (then, then))


def test_a_forced_fetch_goes_to_lex_uz(tmp_path):
    _cache(tmp_path, "-100", age_s=60)
    c = _client(tmp_path)
    assert "yangi" in c.fetch_document("-100", force=True) and len(c.requests) == 1
    assert "yangi" in c.fetch_document("-100") and len(c.requests) == 1          # unforced: the cache


def test_a_resumed_refresh_reuses_pages_it_fetched_recently(tmp_path):
    _cache(tmp_path, "-100", age_s=600)            # fetched 10 minutes ago by the interrupted run
    _cache(tmp_path, "-200", age_s=3 * 86400)      # fetched at build time
    c = _client(tmp_path, fresh_within_s=3600)
    assert "eski" in c.fetch_document("-100", force=True) and c.requests == []
    assert "yangi" in c.fetch_url("https://lex.uz/uz/docs/-200", force=True) and len(c.requests) == 1
