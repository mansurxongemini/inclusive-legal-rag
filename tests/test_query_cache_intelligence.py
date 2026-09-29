import pytest
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
