"""
HuquqPlus (WordPress) REST API mijozi va tozalash moduli.
https://huquqplus.uz/wp-json/wp/v2/posts va categories bilan ishlaydi.
Faqat yangi mustaqil fayl: mavjud fayllarga bog'liqlik yo'q.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "HuquqPlus-RAG/1.0"
ALLOWED_HOST = "huquqplus.uz"
SECTION_MATERIALS = "materials"
SECTION_QA = "qa"

# Root kategoriya IDlari (huquqplus.uz WordPress)
ROOT_CATEGORY_MATERIALS = 20  # "Huquqiy maqolalar"
ROOT_CATEGORY_QA = 23         # "Savol va javob"
EXCLUDED_CATEGORIES = {1, 41} # 1: Yangiliklar, 41: Huquqshunoslar (Uzbek ids)
ROOT_SLUGS_MATERIALS = {"materials"}
ROOT_SLUGS_QA = {"faq"}
CONTENT_PAGE_SIZE = 20          # posts with full content per request


@dataclass
class LexRef:
    url: str
    doc_id: str              # Lex.uz hujjat id, belgisi bilan: "-5852486" yoki "5852486"
    element_id: Optional[str]  # URL #anchor: "-5853923" yoki None
    lang: Optional[str]      # url yo'lidagi "uz"/"ru"/"oz", bo'lmasa None
    anchor_text: str


@dataclass
class HuquqPlusPost:
    wp_id: int
    lang: str                # "uz" | "ru"
    title: str               # HTML entity'lardan tozalangan
    url: str                 # post link
    published: str           # ISO, API "date"
    modified: str            # ISO, API "modified"
    category_ids: List[int]
    category_names: List[str]
    section: str             # "materials" (20 daraxti) | "qa" (23 daraxti)
    excerpt: str             # tozalangan matn
    text: str                # tozalangan toza matn: paragraflar "\n\n" bilan, sarlavhalar alohida qator, ro'yxat bandlari "- " bilan
    lex_refs: List[LexRef]
    other_links: List[str]   # lex.uz bo'lmagan tashqi havolalar (reklama/ad_click, ichki huquqplus.uz/lawyers havolalarisiz)
    content_hash: str        # "sha256:" + sha256(title + "\n" + text)


def clean_html(html_str: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    HTML matnini tozalaydi va havolalarni ajratadi.
    Qaytaradi: (toza matn, [(href, anchor_text)])
    """
    if not html_str or not isinstance(html_str, str):
        return "", []

    soup = BeautifulSoup(html_str, "html.parser")

    # 1. Keraksiz teglar: script, style, noscript
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    # 2. Reyting bloklari: kk-star-ratings va uning bolalari
    for tag in soup.find_all(class_=re.compile(r"kk-star-ratings|kksr-", re.I)):
        tag.decompose()

    # 3. Ulashish (sharer) tugmalari
    for tag in soup.find_all(class_=re.compile(r"\b(share|sharer|sharedaddy|social-share|post-share|entry-share)\b", re.I)):
        tag.decompose()
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if any(sh in href for sh in ["facebook.com/sharer", "sharer.php", "twitter.com/intent/tweet", "twitter.com/share"]):
            a.decompose()

    # 4. Reklama bloklari va ad_click havolalari
    for tag in soup.find_all(class_=re.compile(r"\b(wp-ad-wrap|adBlock|ad-block)\b", re.I)):
        tag.decompose()
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "ad_click" in href:
            a.decompose()

    # 5. Tozalangan DOM dan havolalarni olish
    links: List[Tuple[str, str]] = []
    for a in soup.find_all("a"):
        href = a.get("href", "").strip()
        if href:
            anchor_text = html_lib.unescape(a.get_text().strip())
            links.append((href, anchor_text))

    # 6. Ro'yxat bandlarini '- ' bilan belgilash
    for li in soup.find_all("li"):
        li_text = li.get_text().strip()
        if li_text:
            li.insert_before("\n- ")
            li.insert_after("\n")
        li.unwrap()

    # 7. Sarlavhalarni alohida qatorga ajratish
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        h.insert_before("\n\n")
        h.insert_after("\n\n")
        h.unwrap()

    # 8. Paragraflarni ajratish
    for p in soup.find_all("p"):
        p.insert_before("\n\n")
        p.insert_after("\n\n")
        p.unwrap()

    # 9. Qator uzilishlari
    for br in soup.find_all("br"):
        br.replace_with("\n")

    for bq in soup.find_all("blockquote"):
        bq.insert_before("\n\n")
        bq.insert_after("\n\n")
        bq.unwrap()

    for tr in soup.find_all("tr"):
        tr.insert_after("\n")

    raw_text = soup.get_text()
    decoded = html_lib.unescape(raw_text)

    # Qatorlar bo'yicha probellarni tozalash
    lines = []
    for line in decoded.splitlines():
        cleaned_line = re.sub(r"[ \t\xa0]+", " ", line).strip()
        lines.append(cleaned_line)

    joined = "\n".join(lines)
    # Ketma-ket 3 yoki undan ko'p bo'sh qatorlarni \n\n ga yig'ish
    final_text = re.sub(r"\n{3,}", "\n\n", joined).strip()
    # Ro'yxat bandlari orasidagi ortiqcha bo'sh qatorlarni ixchamlashtirish
    final_text = re.sub(r"(\n- [^\n]+)\n+(?=- )", r"\1\n", final_text)

    return final_text, links


def parse_lex_ref(url: str, anchor_text: str = "") -> Optional[LexRef]:
    """
    Faqat lex.uz / www.lex.uz havolalarini parse qiladi.
    /docs/<id>, /uz/docs/<id>, /ru/docs/<id>, /oz/docs/<id>, ?ONDATE=..., #anchor shakllarini qo'llab-quvvatlaydi.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception:
        return None

    host = parsed.netloc.split(":")[0].lower()
    if host not in ("lex.uz", "www.lex.uz"):
        return None

    match = re.match(r"^/(?:(uz|ru|oz)/)?docs/(-?\d+)(?:/|$)", parsed.path)
    if not match:
        return None

    lang = match.group(1)
    doc_id = match.group(2)
    element_id = parsed.fragment if parsed.fragment else None

    return LexRef(
        url=url.strip(),
        doc_id=doc_id,
        element_id=element_id,
        lang=lang,
        anchor_text=anchor_text.strip() if anchor_text else "",
    )


def diff_index(
    previous: Dict[int, str],
    current: Dict[int, str]
) -> Tuple[List[int], List[int], List[int]]:
    """
    Indekslar orasidagi farqni hisoblaydi: (added, changed, removed).
    O'zgarish modified qiymatiga qarab aniqlanadi, barcha ro'yxatlar tartiblangan.
    """
    added = [wp_id for wp_id in current if wp_id not in previous]
    changed = [
        wp_id for wp_id in current
        if wp_id in previous and current[wp_id] != previous[wp_id]
    ]
    removed = [wp_id for wp_id in previous if wp_id not in current]
    return sorted(added), sorted(changed), sorted(removed)


class HuquqPlusClient:
    """
    huquqplus.uz WordPress REST API mijozi.
    """
    def __init__(
        self,
        base_url: str = "https://huquqplus.uz",
        get_json: Optional[Callable[[str], Tuple[Any, Dict[str, str]]]] = None,
        min_interval_s: float = 0.5,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        parsed_base = urllib.parse.urlsplit(self.base_url)
        if parsed_base.netloc.lower() != ALLOWED_HOST:
            raise ValueError(f"FAQAT https://{ALLOWED_HOST} hostiga ruxsat berilgan, berildi: {self.base_url}")

        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self.max_retries = max_retries
        self._get_json = get_json or self._default_get_json
        self._last_request_time: float = 0.0
        # WPML gives every language its own category ids (uz "materials" = 20, ru "materials" = 19), so the tree
        # and the allowed set are kept per language
        self._categories_by_lang: Dict[str, Dict[int, dict]] = {}
        self._allowed_by_lang: Dict[str, Dict[int, str]] = {}

    def _default_get_json(self, url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc.lower() != ALLOWED_HOST:
            raise ValueError(f"FAQAT https://{ALLOWED_HOST} hostiga ruxsat berilgan, berildi: {url}")

        with httpx.Client(timeout=self.timeout, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json(), dict(resp.headers)

    def _request_json(self, url: str) -> Tuple[Any, Dict[str, str]]:
        # Rate limit
        if self.min_interval_s > 0 and self._last_request_time > 0:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)
        self._last_request_time = time.monotonic()

        # Retry loop for 429 / 5xx
        for attempt in range(self.max_retries + 1):
            try:
                return self._get_json(url)
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code is None:
                    status_code = getattr(exc, "status_code", getattr(exc, "code", None))

                if status_code == 404 or "404" in str(exc):
                    raise

                is_retryable = False
                if status_code in (429, 500, 502, 503, 504):
                    is_retryable = True
                elif isinstance(exc, (httpx.TransportError, httpx.TimeoutException, OSError)):
                    is_retryable = True
                elif any(err_code in str(exc) for err_code in ("429", "500", "502", "503", "504")):
                    is_retryable = True

                if is_retryable and attempt < self.max_retries:
                    backoff = max(0.01, self.min_interval_s) * (2 ** attempt)
                    logger.warning(
                        "So'rov xatosi (%s), %d/%d urinish, %s soniyadan so'ng qayta uriniladi: %s",
                        exc, attempt + 1, self.max_retries, backoff, url
                    )
                    time.sleep(backoff)
                    continue
                raise

    @staticmethod
    def _extract_total_pages(headers: Dict[str, str]) -> Optional[int]:
        if not headers:
            return None
        for k, v in headers.items():
            if k.lower() == "x-wp-totalpages":
                try:
                    return int(v)
                except (ValueError, TypeError):
                    pass
        return None

    def fetch_categories(self, lang: Optional[str] = None) -> Dict[int, dict]:
        """Kategoriyalar daraxtini olib keladi."""
        page = 1
        categories_dict: Dict[int, dict] = {}
        while True:
            params: Dict[str, Any] = {"per_page": 100, "page": page}
            if lang:
                params["lang"] = lang
            url = f"{self.base_url}/wp-json/wp/v2/categories?{urllib.parse.urlencode(params)}"
            data, headers = self._request_json(url)
            if not data or not isinstance(data, list):
                break
            for item in data:
                if isinstance(item, dict) and "id" in item:
                    categories_dict[int(item["id"])] = item

            total_pages = self._extract_total_pages(headers)
            if total_pages is not None:
                if page >= total_pages:
                    break
            else:
                if len(data) < 100:
                    break
            page += 1

        key = lang or "uz"
        self._categories_by_lang[key] = categories_dict
        self._allowed_by_lang[key] = self.allowed_category_ids(categories_dict)
        return categories_dict

    def allowed_category_ids(self, categories: Dict[int, dict]) -> Dict[int, str]:
        """
        Kategoriya daraxtini parent bo'yicha rekursiv hisoblaydi.
        20 va uning avlodlari -> "materials"
        23 va uning avlodlari -> "qa"
        1 ("Yangiliklar"), 41 ("Huquqshunoslar") va boshqalar kiritilmaydi.
        """
        def find_section(cat_id: int) -> Optional[str]:
            # walk up to the root; the root's slug is the same in every language ("materials", "faq")
            curr_id, visited = cat_id, set()
            while curr_id in categories and curr_id not in visited:
                visited.add(curr_id)
                parent_id = int(categories[curr_id].get("parent", 0) or 0)
                if not parent_id or parent_id not in categories:
                    break
                curr_id = parent_id
            root = categories.get(curr_id, {})
            slug = str(root.get("slug", "")).lower()
            if slug in ROOT_SLUGS_MATERIALS:
                return SECTION_MATERIALS
            if slug in ROOT_SLUGS_QA:
                return SECTION_QA
            if not slug:   # minimal payloads without slugs: fall back to the Uzbek root ids
                return {ROOT_CATEGORY_MATERIALS: SECTION_MATERIALS, ROOT_CATEGORY_QA: SECTION_QA}.get(curr_id)
            return None

        allowed: Dict[int, str] = {}
        for cid in categories:
            sec = find_section(cid)
            if sec:
                allowed[cid] = sec
        return allowed

    def _ensure_categories(self, lang: str = "uz") -> Dict[int, str]:
        key = "ru" if lang == "ru" else "uz"
        if key not in self._categories_by_lang:
            self.fetch_categories(key if key != "uz" else None)
        return self._allowed_by_lang.get(key, {})

    def _parse_post(self, post_dict: dict, lang: str = "uz") -> Optional[HuquqPlusPost]:
        wp_id = int(post_dict.get("id", 0))
        post_link = post_dict.get("link", "")
        post_lang = "ru" if (lang == "ru" or "/ru/" in post_link) else "uz"

        cat_ids: List[int] = [int(c) for c in post_dict.get("categories", [])]
        allowed_cats = self._allowed_by_lang.get(post_lang, {})
        categories = self._categories_by_lang.get(post_lang, {})

        section: Optional[str] = None
        for cid in cat_ids:
            if cid in allowed_cats:
                section = allowed_cats[cid]
                break

        if section is None:
            if "/news/" in post_link or (post_lang == "uz" and any(cid in EXCLUDED_CATEGORIES for cid in cat_ids)):
                return None
            if "/materials/" in post_link:
                section = SECTION_MATERIALS
            elif "/faq/" in post_link or "/savol-javob/" in post_link:
                section = SECTION_QA
            else:
                return None

        # Sarlavha
        raw_title = post_dict.get("title", {}).get("rendered", "") if isinstance(post_dict.get("title"), dict) else str(post_dict.get("title", ""))
        title = html_lib.unescape(BeautifulSoup(raw_title, "html.parser").get_text()).strip()

        # Matn va havolalar
        raw_content = post_dict.get("content", {}).get("rendered", "") if isinstance(post_dict.get("content"), dict) else str(post_dict.get("content", ""))
        text, extracted_links = clean_html(raw_content)

        # Excerpt
        raw_excerpt = post_dict.get("excerpt", {}).get("rendered", "") if isinstance(post_dict.get("excerpt"), dict) else str(post_dict.get("excerpt", ""))
        excerpt, _ = clean_html(raw_excerpt)

        # Havolalarni ajratish
        lex_refs: List[LexRef] = []
        other_links: List[str] = []
        for href, anchor_text in extracted_links:
            ref = parse_lex_ref(href, anchor_text)
            if ref is not None:
                lex_refs.append(ref)
            else:
                if "ad_click" in href:
                    continue
                try:
                    p_url = urllib.parse.urlsplit(href)
                except Exception:
                    continue
                netloc = p_url.netloc.lower()
                if not netloc or ALLOWED_HOST in netloc:
                    continue
                if "/lawyers/" in p_url.path or "lawyers" in netloc:
                    continue
                if href not in other_links:
                    other_links.append(href)

        # Kategoriya nomlari
        cat_names: List[str] = []
        if categories:
            for cid in cat_ids:
                if cid in categories:
                    name = html_lib.unescape(categories[cid].get("name", "")).strip()
                    if name:
                        cat_names.append(name)

        content_hash = "sha256:" + hashlib.sha256(f"{title}\n{text}".encode("utf-8")).hexdigest()

        return HuquqPlusPost(
            wp_id=wp_id,
            lang=post_lang,
            title=title,
            url=post_link,
            published=post_dict.get("date", ""),
            modified=post_dict.get("modified", ""),
            category_ids=cat_ids,
            category_names=cat_names,
            section=section,
            excerpt=excerpt,
            text=text,
            lex_refs=lex_refs,
            other_links=other_links,
            content_hash=content_hash,
        )

    def list_post_index(self, lang: str = "uz") -> Dict[int, str]:
        """
        wp_id -> modified lug'atini qaytaradi.
        Faqat ruxsat etilgan kategoriyalarga tegishli postlar (_fields=id,modified,categories).
        """
        allowed_cats = self._ensure_categories(lang)
        index: Dict[int, str] = {}
        page = 1
        while True:
            params = {
                "per_page": 100,
                "page": page,
                "_fields": "id,modified,categories",
            }
            if lang == "ru":
                params["lang"] = "ru"
            url = f"{self.base_url}/wp-json/wp/v2/posts?{urllib.parse.urlencode(params)}"
            data, headers = self._request_json(url)
            if not data or not isinstance(data, list):
                break

            for item in data:
                if not isinstance(item, dict):
                    continue
                wp_id = item.get("id")
                modified = item.get("modified", "")
                cats = [int(c) for c in item.get("categories", [])]
                if any(cid in allowed_cats for cid in cats):
                    index[int(wp_id)] = str(modified)

            total_pages = self._extract_total_pages(headers)
            if total_pages is not None:
                if page >= total_pages:
                    break
            else:
                if len(data) < 100:
                    break
            page += 1

        return index

    def fetch_posts(
        self,
        lang: str = "uz",
        modified_after: Optional[str] = None,
        ids: Optional[List[int]] = None,
    ) -> List[HuquqPlusPost]:
        """
        Postlarni to'liq olib keladi va HuquqPlusPost obyektlariga aylantiradi.
        """
        self._ensure_categories(lang)
        if ids is not None and len(ids) == 0:
            return []

        posts: List[HuquqPlusPost] = []

        if ids is not None:
            # full posts with content are ~40 KB each: 100 per request timed out against the live site
            for i in range(0, len(ids), CONTENT_PAGE_SIZE):
                chunk = ids[i:i + CONTENT_PAGE_SIZE]
                params: Dict[str, Any] = {
                    "per_page": len(chunk),
                    "include": ",".join(str(cid) for cid in chunk),
                }
                if lang == "ru":
                    params["lang"] = "ru"
                if modified_after:
                    params["modified_after"] = modified_after
                url = f"{self.base_url}/wp-json/wp/v2/posts?{urllib.parse.urlencode(params)}"
                data, _ = self._request_json(url)
                if data and isinstance(data, list):
                    for item in data:
                        parsed = self._parse_post(item, lang)
                        if parsed is not None:
                            posts.append(parsed)
            return posts

        page = 1
        while True:
            params = {
                "per_page": CONTENT_PAGE_SIZE,
                "page": page,
            }
            if lang == "ru":
                params["lang"] = "ru"
            if modified_after:
                params["modified_after"] = modified_after
            url = f"{self.base_url}/wp-json/wp/v2/posts?{urllib.parse.urlencode(params)}"
            data, headers = self._request_json(url)
            if not data or not isinstance(data, list):
                break

            for item in data:
                if isinstance(item, dict):
                    parsed = self._parse_post(item, lang)
                    if parsed is not None:
                        posts.append(parsed)

            total_pages = self._extract_total_pages(headers)
            if total_pages is not None:
                if page >= total_pages:
                    break
            else:
                if len(data) < CONTENT_PAGE_SIZE:
                    break
            page += 1

        return posts

    def fetch_post(self, wp_id: int, lang: str = "uz") -> Optional[HuquqPlusPost]:
        """
        Alohida postni ID bo'yicha olib keladi. 404 yoki ruxsat etilmagan kategoriyada bo'lsa None qaytaradi.
        """
        params = {}
        if lang == "ru":
            params["lang"] = "ru"
        url = f"{self.base_url}/wp-json/wp/v2/posts/{wp_id}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        try:
            data, _ = self._request_json(url)
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code is None:
                status_code = getattr(exc, "status_code", getattr(exc, "code", None))
            if status_code == 404 or "404" in str(exc):
                return None
            raise

        if not data or not isinstance(data, dict):
            return None
        if data.get("data", {}).get("status") == 404 or data.get("code") in ("rest_post_invalid_id", "rest_forbidden", "rest_no_route"):
            return None

        self._ensure_categories(lang)
        return self._parse_post(data, lang)
