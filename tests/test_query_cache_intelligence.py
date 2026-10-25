import numpy as np
from src.api.cache import QueryCache


def test_canonical_punctuation_invariance(tmp_path):
    db_file = tmp_path / "test_cache.db"
    cache = QueryCache(str(db_file))

    q1 = "Ish beruvchi korxona shtatini qisqartirayotganda kimlarni birinchi navbatda ishda qoldirishi shart?"
    q2 = "Ish beruvchi korxona shtatini qisqartirayotganda kimlarni birinchi navbatda ishda qoldirishi shart."
    q3 = "  Ish beruvchi   korxona   shtatini qisqartirayotganda kimlarni birinchi navbatda ishda qoldirishi shart?! \n"

    dummy_data = {
        "answer": "Shtat qisqarganda xodimlar afzallik huquqi bo'yicha qoldiriladi. " * 10,
        "citations": [],
    }

    # Store with question mark
    cache.set(q1, "uz", "plain", dummy_data)

    # Must hit with period!
    res2 = cache.get(q2, "uz", "plain")
    assert res2 is not None, "Cache should hit despite replacing question mark with period!"
    assert res2["answer"] == dummy_data["answer"]

    # Must hit with extra whitespace and exclamation marks!
    res3 = cache.get(q3, "uz", "plain")
    assert res3 is not None, "Cache should hit despite whitespace and punctuation differences!"


def test_cyrillic_latin_cache_invariance(tmp_path):
    db_file = tmp_path / "test_cache.db"
    cache = QueryCache(str(db_file))

    q_latin = "Nogironlar uchun qanday tibbiy imtiyozlar belgilangan?"
    q_cyrillic = "Ногиронлар учун қандай тиббий имтиёзлар белгиланган?"

    dummy_data = {
        "answer": "Nogironligi bo'lgan shaxslar bepul tibbiy yordam olish huquqiga ega. " * 8,
        "citations": [],
    }

    cache.set(q_latin, "uz", "plain", dummy_data)

    # Must hit with Cyrillic!
    res_cyr = cache.get(q_cyrillic, "uz", "plain")
    assert res_cyr is not None, "Cache should hit across Cyrillic and Latin scripts!"


def test_semantic_vector_cache(tmp_path):
    db_file = tmp_path / "test_cache.db"
    cache = QueryCache(str(db_file))

    vec1 = np.random.randn(1024).tolist()
    # Create a vector with 98% cosine similarity
    v_arr = np.array(vec1, dtype=np.float32)
    noise = np.random.randn(1024) * 0.05
    vec2 = (v_arr + noise).tolist()

    dummy_data = {
        "answer": "Mehnat kodeksining 167-moddasiga ko'ra malakasi yuqoriroq xodimlar qoldiriladi. " * 8,
        "citations": [],
    }

    cache.set("Savol birinchi variant", "uz", "plain", dummy_data, vector=vec1)

    # Semantic get with vec2 (similarity > 0.96)
    sem_hit = cache.get_semantic(vec2, "uz", "plain", threshold=0.95)
    assert sem_hit is not None, "Semantic cache should hit on 98% vector similarity!"
    assert sem_hit.get("cache_type") == "semantic"
    assert sem_hit.get("semantic_similarity", 0) >= 0.95


def test_ram_cache_evicts_the_least_recently_used_and_never_serves_a_replaced_answer(tmp_path, monkeypatch):
    """A full RAM cache used to refuse new entries and to keep the old answer of a key that was set again."""
    monkeypatch.setattr(QueryCache, "RAM_MAX_ITEMS", 3)
    cache = QueryCache(str(tmp_path / "ram.db"))
    body = "Javob matni. " * 40

    def put(n, prefix=""):
        cache.set(f"savol {n}", "uz", "plain", {"answer": f"{prefix}{n} {body}"})

    def key(n):
        return cache._make_key(f"savol {n}", "uz", "plain")

    for n in range(3):
        put(n)
    cache.get("savol 0", "uz", "plain")              # 0 is now the most recently used, 1 the least
    put(3)
    assert len(cache._ram_cache) == 3
    assert key(1) not in cache._ram_cache and key(0) in cache._ram_cache and key(3) in cache._ram_cache
    assert cache.get("savol 1", "uz", "plain")["cache_type"] == "exact_disk"      # evicted from RAM, still on disk

    put(0, prefix="YANGI ")                          # the same key again while RAM is full
    assert cache.get("savol 0", "uz", "plain")["answer"].startswith("YANGI ")


def test_semantic_cache_returns_the_most_similar_answer_not_the_newest(tmp_path):
    cache = QueryCache(str(tmp_path / "semantic.db"))
    body = "Javob matni. " * 40
    base = np.zeros(8, dtype=np.float32)
    base[0] = 1.0
    near = base.copy()
    near[1] = 0.1                                    # cosine ~0.995 with the query
    nearer = base.copy()
    nearer[1] = 0.02                                 # cosine ~0.9998 with the query, stored FIRST (older)

    cache.set("eng yaqin savol", "uz:latn", "plain", {"answer": f"YAQIN {body}"}, vector=nearer.tolist())
    cache.set("yangiroq savol", "uz:latn", "plain", {"answer": f"YANGI {body}"}, vector=near.tolist())

    hit = cache.get_semantic(base.tolist(), "uz:latn", "plain", threshold=0.95)
    assert hit["answer"].startswith("YAQIN") and hit["semantic_similarity"] > 0.999
    assert cache.get_semantic(base.tolist(), "uz:latn", "plain", threshold=0.95,
                              accept=lambda d: not d["answer"].startswith("YAQIN"))["answer"].startswith("YANGI")
    assert cache.get_semantic(base.tolist(), "uz:cyrl", "plain", threshold=0.95) is None      # another script: no hit


def test_expired_entries_are_purged_from_disk_and_ram(tmp_path, monkeypatch):
    cache = QueryCache(str(tmp_path / "purge.db"))
    body = "Javob matni. " * 40
    cache.set("eskirgan savol", "uz:latn", "plain", {"answer": f"ESKI {body}"})
    monkeypatch.setattr(cache, "ttl", 3600)
    cache.set("yangi savol", "uz:latn", "plain", {"answer": f"YANGI {body}"})
    with cache._get_conn() as conn:                  # make the first one two hours old
        conn.execute("UPDATE query_cache SET created_at = created_at - 7200 WHERE canonical_query = 'eskirgan savol'")
    cache._ram_cache[cache._make_key("eskirgan savol", "uz:latn", "plain")] = (cache._ram_cache[cache._make_key("eskirgan savol", "uz:latn", "plain")][0] - 7200, {"answer": "ESKI"})

    assert cache.purge_expired() == 1
    with cache._get_conn() as conn:
        assert conn.execute("SELECT count(*) FROM query_cache").fetchone()[0] == 1
    assert cache.get("eskirgan savol", "uz:latn", "plain") is None
    assert cache.get("yangi savol", "uz:latn", "plain")["answer"].startswith("YANGI")
