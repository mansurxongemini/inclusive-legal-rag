"""
HuquqPlus (WordPress) REST API mijozi uchun tarmoqsiz testlar.
Barcha testlar faqat fixture va soxta get_json bilan ishlaydi.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pytest

from src.ingestion.huquqplus_client import (
    HuquqPlusClient,
    HuquqPlusPost,
    LexRef,
    clean_html,
    diff_index,
    parse_lex_ref,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "huquqplus"


@pytest.fixture
def categories_fixture() -> List[dict]:
    with open(FIXTURES_DIR / "categories.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def post_2966_fixture() -> dict:
    with open(FIXTURES_DIR / "post_2966_uz.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def posts_page_uz_fixture() -> List[dict]:
    with open(FIXTURES_DIR / "posts_page_uz.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def posts_page_ru_fixture() -> List[dict]:
    with open(FIXTURES_DIR / "posts_page_ru.json", "r", encoding="utf-8") as f:
        return json.load(f)


# =====================================================================
# 1. Kategoriya daraxti (20/23 kirdi, 1/41 kirmadi)
# =====================================================================

def test_allowed_category_tree(categories_fixture: List[dict]):
    cats_dict = {int(c["id"]): c for c in categories_fixture}
    client = HuquqPlusClient(min_interval_s=0.0)

    allowed = client.allowed_category_ids(cats_dict)

    # 20 ("Huquqiy maqolalar") va uning bolalari materials bo'lishi kerak
    assert 20 in allowed
    assert allowed[20] == "materials"
    # 48 ("Tibbiy xizmatlar va reabilitasiya"), 43, 44, 45, 54, 57 bolalari
    for cid in [48, 43, 44, 45, 54, 57]:
        assert cid in allowed, f"Category {cid} should be allowed"
        assert allowed[cid] == "materials", f"Category {cid} should be materials"

    # 23 ("Savol va javob") va uning bolalari qa bo'lishi kerak
    assert 23 in allowed
    assert allowed[23] == "qa"
    # 231, 232, 233, 237 bolalari
    for cid in [231, 232, 233, 237]:
        assert cid in allowed, f"QA Category {cid} should be allowed"
        assert allowed[cid] == "qa", f"QA Category {cid} should be qa"

    # 1 ("Yangiliklar") kirmasligi kerak
    assert 1 not in allowed

    # 41 ("Huquqshunoslar") va uning bolalari kirmasligi kerak
    assert 41 not in allowed
    for cid in [65, 67, 187, 247, 248]:
        assert cid not in allowed, f"Lawyer category {cid} must not be allowed"

    # Boshqa muallif/root kategoriyalar ham kirmasligi kerak
    for cid in [170, 63, 171, 97, 86]:
        assert cid not in allowed


# =====================================================================
# 2. post_2966 tozalash (reyting/reklama yo'q, other_links, lex_refs)
# =====================================================================

def test_post_2966_cleaning_and_lex_refs(post_2966_fixture: dict, categories_fixture: List[dict]):
    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return categories_fixture, {"X-WP-TotalPages": "1"}
        if "/posts/2966" in parsed.path:
            return post_2966_fixture, {}
        raise ValueError(f"Kutilmagan URL: {url}")

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0)
    post = client.fetch_post(2966, lang="uz")

    assert post is not None
    assert post.wp_id == 2966
    assert post.lang == "uz"
    assert post.title == "Kattalarda nogironlik holatini belgilash tartibi qanday?"
    assert post.section == "materials"
    assert post.category_ids == [48, 65]
    assert "Tibbiy xizmatlar va reabilitasiya" in post.category_names

    # Matn tozalanishi: kk-star-ratings reyting matnlari yo'q
    assert "3/5" not in post.text
    assert "votes" not in post.text
    assert "3/5" not in post.excerpt

    # Reklama yo'q: ad_click matnda ham, havolalarda ham yo'q
    assert "ad_click" not in post.text
    for link in post.other_links:
        assert "ad_click" not in link

    # my.gov.uz tashqi havolalar (other_links) ichida bor
    assert any("my.gov.uz" in link for link in post.other_links)
    assert "https://my.gov.uz/uz" in post.other_links

    # Huquqshunoslar ichki havolalari (huquqplus.uz/lawyers) other_links da bo'lmasligi kerak
    for link in post.other_links:
        assert "huquqplus.uz" not in link
        assert "lawyers" not in link

    # Lex.uz havolalari to'g'ri parse qilingan
    assert len(post.lex_refs) == 3
    ref_5852486 = next((r for r in post.lex_refs if r.doc_id == "-5852486"), None)
    assert ref_5852486 is not None
    assert ref_5852486.element_id == "-5853923"
    assert ref_5852486.lang == "ru"
    assert ref_5852486.url == "https://lex.uz/ru/docs/-5852486#-5853923"

    ref_7021644 = next((r for r in post.lex_refs if r.doc_id == "-7021644"), None)
    assert ref_7021644 is not None
    assert ref_7021644.element_id is None
    assert ref_7021644.lang == "uz"

    ref_7730821 = next((r for r in post.lex_refs if r.doc_id == "-7730821"), None)
    assert ref_7730821 is not None
    assert ref_7730821.element_id is None
    assert ref_7730821.lang == "uz"

    # content_hash tekshiruvi
    assert post.content_hash.startswith("sha256:")
    assert len(post.content_hash) == 71  # "sha256:" (7) + 64 hex


# =====================================================================
# 3. parse_lex_ref turli URL shakllari va lex bo'lmagan URL -> None
# =====================================================================

def test_parse_lex_ref_variants():
    # Rus tili va anchor
    r1 = parse_lex_ref("https://lex.uz/ru/docs/-5852486#-5853923", "Havola matni")
    assert r1 is not None
    assert r1.doc_id == "-5852486"
    assert r1.element_id == "-5853923"
    assert r1.lang == "ru"
    assert r1.anchor_text == "Havola matni"

    # O'zbek tili, anchorsiz
    r2 = parse_lex_ref("https://lex.uz/uz/docs/-7021644")
    assert r2 is not None
    assert r2.doc_id == "-7021644"
    assert r2.element_id is None
    assert r2.lang == "uz"

    # O'zbek tili (kirill/oz)
    r3 = parse_lex_ref("https://lex.uz/oz/docs/-12345")
    assert r3 is not None
    assert r3.doc_id == "-12345"
    assert r3.element_id is None
    assert r3.lang == "oz"

    # Tilsiz va musbat son
    r4 = parse_lex_ref("https://lex.uz/docs/5852486")
    assert r4 is not None
    assert r4.doc_id == "5852486"
    assert r4.element_id is None
    assert r4.lang is None

    # www.lex.uz va query param (?ONDATE=...)
    r5 = parse_lex_ref("https://www.lex.uz/docs/5852486?ONDATE=2020-01-01")
    assert r5 is not None
    assert r5.doc_id == "5852486"
    assert r5.element_id is None
    assert r5.lang is None

    # Trailing slash va anchor
    r6 = parse_lex_ref("https://lex.uz/ru/docs/-5852486/#-5853923")
    assert r6 is not None
    assert r6.doc_id == "-5852486"
    assert r6.element_id == "-5853923"
    assert r6.lang == "ru"

    # HTTP protokoli
    r7 = parse_lex_ref("http://lex.uz/docs/12345")
    assert r7 is not None
    assert r7.doc_id == "12345"

    # Lex bo'lmagan URL lar -> None
    assert parse_lex_ref("https://my.gov.uz/uz") is None
    assert parse_lex_ref("https://huquqplus.uz/materials/2966") is None
    assert parse_lex_ref("https://google.com/search?q=lex") is None
    assert parse_lex_ref("https://notlex.uz/docs/123") is None

    # Hujjat ID si bo'lmagan lex havolalar -> None
    assert parse_lex_ref("https://lex.uz/") is None
    assert parse_lex_ref("https://lex.uz/search") is None
    assert parse_lex_ref("https://lex.uz/docs/") is None
    assert parse_lex_ref("") is None


# =====================================================================
# 4. diff_index
# =====================================================================

def test_diff_index():
    previous = {
        101: "2026-01-01T10:00:00",
        102: "2026-01-01T10:00:00",
        103: "2026-01-01T10:00:00",
    }
    current = {
        102: "2026-01-02T12:00:00",  # O'zgardi
        103: "2026-01-01T10:00:00",  # O'zgarmadi
        104: "2026-01-03T08:00:00",  # Yangi qo'shildi
        105: "2026-01-03T09:00:00",  # Yangi qo'shildi
    }

    added, changed, removed = diff_index(previous, current)

    assert added == [104, 105]
    assert changed == [102]
    assert removed == [101]

    # Bo'sh lug'atlar bilan
    assert diff_index({}, current) == ([102, 103, 104, 105], [], [])
    assert diff_index(previous, {}) == ([], [], [101, 102, 103])
    assert diff_index(previous, previous) == ([], [], [])


# =====================================================================
# 5. Pagination (soxta 3 sahifa)
# =====================================================================

def test_pagination_three_pages():
    requested_pages = []

    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return [{"id": 20, "name": "Huquqiy maqolalar", "parent": 0, "slug": "materials"}], {"X-WP-TotalPages": "1"}

        if parsed.path.endswith("/posts"):
            query = urllib.parse.parse_qs(parsed.query)
            page = int(query.get("page", ["1"])[0])
            requested_pages.append(page)
            if page == 1:
                return [
                    {"id": 1, "modified": "2026-01-01", "categories": [20]},
                    {"id": 2, "modified": "2026-01-01", "categories": [20]},
                ], {"X-WP-TotalPages": "3", "X-WP-Total": "6"}
            elif page == 2:
                return [
                    {"id": 3, "modified": "2026-01-02", "categories": [20]},
                    {"id": 4, "modified": "2026-01-02", "categories": [20]},
                ], {"X-WP-TotalPages": "3", "X-WP-Total": "6"}
            elif page == 3:
                return [
                    {"id": 5, "modified": "2026-01-03", "categories": [20]},
                    {"id": 6, "modified": "2026-01-03", "categories": [20]},
                ], {"X-WP-TotalPages": "3", "X-WP-Total": "6"}
            else:
                return [], {"X-WP-TotalPages": "3"}
        raise ValueError(f"Unexpected url: {url}")

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0)
    index = client.list_post_index()

    assert requested_pages == [1, 2, 3]
    assert len(index) == 6
    assert index[1] == "2026-01-01"
    assert index[6] == "2026-01-03"


# =====================================================================
# 6. Boshqa host rad etilishi
# =====================================================================

def test_other_host_rejected():
    # Konstruktorda ruxsat etilmagan base_url
    with pytest.raises(ValueError, match="huquqplus.uz"):
        HuquqPlusClient(base_url="https://evil.com")

    with pytest.raises(ValueError, match="huquqplus.uz"):
        HuquqPlusClient(base_url="https://not-huquqplus.uz")

    # default_get_json orqali ruxsat etilmagan URL
    client = HuquqPlusClient(min_interval_s=0.0)
    with pytest.raises(ValueError, match="huquqplus.uz"):
        client._default_get_json("https://evil.com/wp-json/wp/v2/posts")


# =====================================================================
# 7. 404 -> None
# =====================================================================

def test_fetch_post_404_returns_none(categories_fixture: List[dict]):
    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return categories_fixture, {"X-WP-TotalPages": "1"}
        req = httpx.Request("GET", url)
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("Post topilmadi", request=req, response=resp)

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0)
    res = client.fetch_post(999999)
    assert res is None


# =====================================================================
# 8. Retry va exponential backoff
# =====================================================================

def test_retry_on_server_error(categories_fixture: List[dict]):
    call_count = 0

    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            req = httpx.Request("GET", url)
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("Server error", request=req, response=resp)
        return categories_fixture, {"X-WP-TotalPages": "1"}

    client = HuquqPlusClient(
        get_json=mock_get_json,
        min_interval_s=0.001,
        max_retries=3,
    )

    cats = client.fetch_categories()
    assert len(cats) > 0
    # 2 marta muvaffaqiyatsiz, 3-sida muvaffaqiyatli
    assert call_count == 3


def test_retry_exhausted_raises():
    call_count = 0

    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        nonlocal call_count
        call_count += 1
        req = httpx.Request("GET", url)
        resp = httpx.Response(503, request=req)
        raise httpx.HTTPStatusError("Service unavailable", request=req, response=resp)

    client = HuquqPlusClient(
        get_json=mock_get_json,
        min_interval_s=0.001,
        max_retries=2,
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_categories()

    # Dastlabki urinish + 2 ta qayta urinish = 3 ta chaqiruv
    assert call_count == 3


# =====================================================================
# 9. list_post_index kategoriyalarni filtrlashi (posts_page_uz fixture)
# =====================================================================

def test_list_post_index_filters_categories(
    categories_fixture: List[dict],
    posts_page_uz_fixture: List[dict]
):
    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return categories_fixture, {"X-WP-TotalPages": "1"}
        if parsed.path.endswith("/posts"):
            return posts_page_uz_fixture, {"X-WP-TotalPages": "1"}
        raise ValueError(f"Unexpected url: {url}")

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0)
    index = client.list_post_index("uz")

    # 11157 - 1-kategoriya ("Yangiliklar"), kirmasligi shart
    assert 11157 not in index
    # 11145 (20 daraxti), 2966 (48), 11068 (20, 45), 11032 (57) kirishi shart
    assert 11145 in index
    assert 2966 in index
    assert 11068 in index
    assert 11032 in index


# =====================================================================
# 10. fetch_posts rus tili sahifasi (posts_page_ru fixture)
# =====================================================================

def test_fetch_posts_russian(
    categories_fixture: List[dict],
    posts_page_ru_fixture: List[dict]
):
    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return categories_fixture, {"X-WP-TotalPages": "1"}
        if parsed.path.endswith("/posts"):
            return posts_page_ru_fixture, {"X-WP-TotalPages": "1"}
        raise ValueError(f"Unexpected url: {url}")

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0)
    posts = client.fetch_posts(lang="ru")

    post_ids = [p.wp_id for p in posts]
    # 11178 yangiliklar post (cat 9, link /ru/news/), kirmasligi shart
    assert 11178 not in post_ids
    # Ruxsat etilgan maqolalar mavjud
    assert 11176 in post_ids
    assert 9686 in post_ids
    assert 11123 in post_ids
    assert 11110 in post_ids

    for p in posts:
        assert p.lang == "ru"
        assert p.section == "materials"


# =====================================================================
# 11. fetch_posts ids va modified_after parametrlari
# =====================================================================

def test_fetch_posts_with_ids_and_modified_after(
    categories_fixture: List[dict],
    post_2966_fixture: dict
):
    captured_urls = []

    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        captured_urls.append(url)
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return categories_fixture, {"X-WP-TotalPages": "1"}
        return [post_2966_fixture], {"X-WP-TotalPages": "1"}

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0)

    # Bo'sh ids so'rovsiz bo'sh ro'yxat qaytaradi
    empty_res = client.fetch_posts(ids=[])
    assert empty_res == []

    # Muayyan id va modified_after bilan chaqirish
    posts = client.fetch_posts(ids=[2966], modified_after="2026-09-01T00:00:00")
    assert len(posts) == 1
    assert posts[0].wp_id == 2966

    last_url = captured_urls[-1]
    assert "include=2966" in last_url
    assert "modified_after=2026-09-01T00%3A00%3A00" in last_url or "modified_after=2026-09-01T00:00:00" in last_url


# =====================================================================
# 12. clean_html funksiyasi maxsus holatlari
# =====================================================================

def test_clean_html_structure():
    html_sample = """
    <h2>Sarlavha 1</h2>
    <p>Birinchi paragraf &#8216;iqtibos&#8217; &amp; &quot;matn&quot;.</p>
    <div class="kk-star-ratings">
        <div class="kksr-legend">3/5 - (2 votes)</div>
    </div>
    <div class="wp-ad-wrap">
        <a href="https://huquqplus.uz/?ad_click=101">Reklama havolasi</a>
    </div>
    <div class="social-share">
        <a href="https://www.facebook.com/sharer/sharer.php?u=foo">Facebook share</a>
    </div>
    <ul>
        <li>Band bir</li>
        <li>Band ikki</li>
    </ul>
    <p></p>
    <p>&nbsp;</p>
    <p>Oxirgi <a href="https://lex.uz/docs/5852486">qonun havolasi</a>.</p>
    """

    text, links = clean_html(html_sample)

    # HTML entitylar tozalangan
    assert "‘iqtibos’ & \"matn\"" in text
    # Reyting va reklama bloklari yo'q
    assert "3/5" not in text
    assert "votes" not in text
    assert "Reklama" not in text
    assert "Facebook share" not in text

    # Ro'yxat bandlari '- ' bilan boshlanadi
    assert "- Band bir" in text
    assert "- Band ikki" in text

    # Havolalar
    assert len(links) == 1
    assert links[0] == ("https://lex.uz/docs/5852486", "qonun havolasi")

    # Bo'sh matn
    empty_text, empty_links = clean_html("")
    assert empty_text == ""
    assert empty_links == []


def test_russian_posts_use_the_russian_category_tree():
    """WPML gives Russian categories their own ids (materials = 19, faq = 22 instead of 20 / 23)."""
    fixtures = Path(__file__).parent / "fixtures" / "huquqplus"
    cats_ru = json.loads((fixtures / "categories_ru.json").read_text(encoding="utf-8"))
    posts_ru = json.loads((fixtures / "posts_page_ru.json").read_text(encoding="utf-8"))

    def get_json(url):
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        assert query.get("lang") == ["ru"], url
        if parsed.path.endswith("/categories"):
            return cats_ru, {"X-WP-TotalPages": "1"}
        return posts_ru, {"X-WP-TotalPages": "1"}

    client = HuquqPlusClient(get_json=get_json, min_interval_s=0.0)
    allowed = client.allowed_category_ids({c["id"]: c for c in cats_ru})
    by_slug = {c["slug"]: c["id"] for c in cats_ru if c["parent"] == 0}
    assert allowed[by_slug["materials"]] == "materials" and allowed[by_slug["faq"]] == "qa"
    assert by_slug["news"] not in allowed and by_slug["lawyers"] not in allowed

    posts = client.fetch_posts(lang="ru")
    expected = [p for p in posts_ru if "/news/" not in p["link"]]
    assert len(posts) == len(expected) > 0
    assert all(p.lang == "ru" and "/news/" not in p.url for p in posts)


def test_extra_posts_admit_a_listed_news_explainer_only(categories_fixture: List[dict], posts_page_ru_fixture: List[dict]):
    def mock_get_json(url: str) -> Tuple[Any, Dict[str, str]]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.path.endswith("/categories"):
            return categories_fixture, {"X-WP-TotalPages": "1"}
        return posts_page_ru_fixture, {"X-WP-TotalPages": "1"}

    client = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0, extra_posts={"ru": [11178]})
    news = next(p for p in client.fetch_posts(lang="ru") if p.wp_id == 11178)
    assert news.section == "materials"
    assert 11178 in client.list_post_index(lang="ru")
    # the allowlist is per language: the same id listed for uz does not admit the ru news post
    uz_only = HuquqPlusClient(get_json=mock_get_json, min_interval_s=0.0, extra_posts={"uz": [11178]})
    assert 11178 not in [p.wp_id for p in uz_only.fetch_posts(lang="ru")]


def test_load_extra_posts_reads_lang_ids(tmp_path):
    from src.ingestion.huquqplus_client import load_extra_posts
    f = tmp_path / "extra.json"
    f.write_text('{"posts": [{"lang": "uz", "wp_id": 606}, {"lang": "ru", "wp_id": "8161"}, {"lang": "uz"}]}')
    assert load_extra_posts(f) == {"uz": {606}, "ru": {8161}}
    assert load_extra_posts(tmp_path / "missing.json") == {}
