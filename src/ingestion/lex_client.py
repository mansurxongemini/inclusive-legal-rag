"""
Polite, cached client for the official Lex.uz portal.

* `fetch_document` - HTML of one document (disk-cached, throttled, retried).
* `okoz_tree` - the official classifier (OKOZ) tree.
* `search_okoz` / `search_title` - paged result lists (ASP.NET postback pagination).

Everything here talks only to https://lex.uz and never executes anything from the pages.
"""
import html as html_lib
import json
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import httpx

logger = logging.getLogger(__name__)

LEX_BASE = "https://lex.uz"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 "
    "InclusiveLegalRAG/1.0 (+disability-rights research; contact: project maintainers)"
)


@dataclass
class SearchHit:
    doc_id: str                 # "-8288607" (Latin Uzbek edition)
    title: str
    kind_line: str              # "Oʻzbekiston Respublikasi Prezidentining qarori, 24.06.2026 yildagi PQ-239-son"
    in_force: bool
    okoz_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OkozNode:
    level: int
    node_id: int
    name: str


def to_lex_spelling(text: str) -> str:
    """Lex.uz stores Latin Uzbek with modifier letters: o'/g' -> oʻ/gʻ (U+02BB), other apostrophes -> ʼ (U+02BC)."""
    t = re.sub(r"([oOgG])['`’‘ʻʼ]", lambda m: m.group(1) + "\u02bb", text)
    return re.sub(r"['`’‘]", "\u02bc", t)


def doc_cache_name(doc_id: str) -> str:
    d = str(doc_id).strip()
    return ("m" + d[1:]) if d.startswith("-") else ("p" + d)


class LexClient:
    def __init__(
        self,
        cache_dir: str = "data/raw_lex",
        min_delay: float = 1.0,
        timeout: float = 45.0,
        max_retries: int = 3,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_delay = min_delay
        self.max_retries = max_retries
        self._last_request = 0.0
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "uz,ru;q=0.8"},
            follow_redirects=True,
            timeout=timeout,
        )

    # -- plumbing ---------------------------------------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "LexClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self.min_delay - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._http.request(method, url, **kwargs)
                if resp.status_code in (429, 502, 503, 504):
                    time.sleep(2.0 * (attempt + 1))
                    continue
                return resp
            except httpx.HTTPError as e:
                last_exc = e
                time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"Lex.uz request failed: {url} ({last_exc})")

    # -- documents --------------------------------------------------------------------------------------
    def fetch_document(self, doc_id: str, force: bool = False) -> Optional[str]:
        """
        HTML of a document in the Latin-Uzbek edition when it exists (negative id), else the given id.
        Returns None when Lex.uz answers 404 for every variant.
        """
        raw = str(doc_id).strip()
        variants = [raw] if raw.startswith("-") else [f"-{raw}", raw]
        for variant in variants:
            path = self.cache_dir / f"{doc_cache_name(variant)}.html"
            if path.exists() and not force:
                return path.read_text(encoding="utf-8", errors="replace")
            resp = self._request("GET", f"{LEX_BASE}/uz/docs/{variant}")
            if resp.status_code == 200 and "lx_elem" in resp.text:
                path.write_text(resp.text, encoding="utf-8")
                return resp.text
            if resp.status_code not in (200, 404):
                logger.warning(f"Lex.uz {variant}: HTTP {resp.status_code}")
        return None

    def fetch_url(self, url: str, force: bool = False) -> Optional[str]:
        """Fetches a Lex.uz document URL (e.g. a language alternative), cached by its document id."""
        m = re.search(r"/docs/(-?\d+)", url)
        if not m:
            return None
        doc_id = m.group(1)
        path = self.cache_dir / f"{doc_cache_name(doc_id)}.html"
        if path.exists() and not force:
            return path.read_text(encoding="utf-8", errors="replace")
        resp = self._request("GET", f"{LEX_BASE}/uz/docs/{doc_id}")
        if resp.status_code == 200 and "lx_elem" in resp.text:
            path.write_text(resp.text, encoding="utf-8")
            return resp.text
        return None

    # -- classifier -------------------------------------------------------------------------------------
    def okoz_tree(self, force: bool = False) -> List[OkozNode]:
        path = self.cache_dir / "okoz_tree.json"
        if path.exists() and not force:
            return [OkozNode(**n) for n in json.loads(path.read_text(encoding="utf-8"))]
        resp = self._request(
            "GET", f"{LEX_BASE}/uz/ajax_methods_url",
            params={"action": "GetOkozTree", "ucId": "okoz_1"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        nodes: List[OkozNode] = []
        for m in re.finditer(
            r'<div class="stm_item lvl_(\d)" id="okoz_1_(\d+)"><div class="stm_hdr">.*?<label for="[^"]+">([^<]+)</label>',
            resp.text,
        ):
            nodes.append(OkozNode(int(m.group(1)), int(m.group(2)), html_lib.unescape(m.group(3)).strip()))
        if nodes:
            path.write_text(json.dumps([asdict(n) for n in nodes], ensure_ascii=False), encoding="utf-8")
        return nodes

    # -- search -----------------------------------------------------------------------------------------
    @staticmethod
    def _parse_hits(page_html: str, okoz_id: Optional[int] = None) -> List[SearchHit]:
        hits: List[SearchHit] = []
        for row in re.split(r'<tr class="dd-table__main-item">', page_html)[1:]:
            m = re.search(r'class="lx_link\s*" href="/uz/docs/(-?\d+)"[^>]*>([^<]+)</a>', row)
            if not m:
                continue
            kind = re.search(r'badge badge-pill badge-nine">([^<]+)<', row)
            state = re.search(r'status_code_(\w)', row)
            hits.append(SearchHit(
                doc_id=m.group(1),
                title=html_lib.unescape(m.group(2)).strip(),
                kind_line=html_lib.unescape(kind.group(1)).strip() if kind else "",
                in_force=(state.group(1) == "y") if state else True,
                okoz_id=okoz_id,
            ))
        return hits

    def _paged_search(self, query: Dict[str, str], okoz_id: Optional[int], max_pages: int) -> Iterator[SearchHit]:
        url = f"{LEX_BASE}/uz/search/all?" + urllib.parse.urlencode({"lang": "4", **query})
        resp = self._request("GET", url)
        page = 1
        while True:
            hits = self._parse_hits(resp.text, okoz_id)
            if not hits:
                return
            yield from hits
            if page >= max_pages:
                return
            fields = {
                m.group(1): html_lib.unescape(m.group(2))
                for m in re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', resp.text)
            }
            if "ucFoundActsControl$LinkButton1" not in resp.text or "__VIEWSTATE" not in fields:
                return
            # last page: the "next" link is rendered disabled / the list shorter than a full page
            if len(hits) < 20:
                return
            fields["__EVENTTARGET"] = "ucFoundActsControl$LinkButton1"
            fields["__EVENTARGUMENT"] = ""
            resp = self._request("POST", url, data=fields, headers={"Referer": url})
            nxt = re.findall(r'class="lx_link\s*" href="/uz/docs/(-?\d+)"', resp.text)
            if not nxt or nxt[0] == hits[0].doc_id:
                return
            page += 1

    def search_okoz(self, okoz_id: int, max_pages: int = 60) -> List[SearchHit]:
        return list(self._paged_search({"okoz": str(okoz_id)}, okoz_id, max_pages))

    def search_title(self, title: str, max_pages: int = 3) -> List[SearchHit]:
        return list(self._paged_search({"searchtitle": to_lex_spelling(title)}, None, max_pages))

    def iter_search_title(self, title: str, max_pages: int = 15) -> Iterator[SearchHit]:
        """Lazy variant: callers can stop paging as soon as they found the document they need."""
        return self._paged_search({"searchtitle": to_lex_spelling(title)}, None, max_pages)
