#!/usr/bin/env python3
"""
scripts/integrate_argon_dataset.py - Ingest and split legal_intelligence_dataset.json into project assets.
"""
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("argon_ingest")

SRC_PATH = Path("legal_intelligence_dataset.json")
SOURCES_DIR = Path("data/sources")
GOLDEN_DIR = Path("data/golden_dataset")

def main():
    if not SRC_PATH.exists():
        log.error(f"{SRC_PATH} topilmadi!")
        return

    with open(SRC_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    log.info(f"Loaded {SRC_PATH} successfully. Keys: {list(data.keys())}")

    # 1. Ensure directories exist
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Extract and save Blok 1 (Colloquial to Legal mapping)
    blok_1 = data.get("blok_1_xalq_tili_qonun_tili_xaritasi", [])
    lexicon_path = SOURCES_DIR / "query_expansion_lexicon.json"
    with open(lexicon_path, "w", encoding="utf-8") as f:
        json.dump(blok_1, f, ensure_ascii=False, indent=2)
    log.info(f"Blok 1 saqlandi: {lexicon_path} ({len(blok_1)} ta ibora/xarita)")

    # 3. Extract and save Blok 2 (Casuistic benchmark cases)
    blok_2 = data.get("blok_2_kazuistik_vaziyatlar_benchmark", [])
    benchmark_path = GOLDEN_DIR / "casuistic_benchmarks_50.json"
    with open(benchmark_path, "w", encoding="utf-8") as f:
        json.dump(blok_2, f, ensure_ascii=False, indent=2)
    log.info(f"Blok 2 saqlandi: {benchmark_path} ({len(blok_2)} ta murakkab keys)")

    # 4. Extract and save Blok 3 (System prompt and CoT examples)
    blok_3 = data.get("blok_3_tizim_korsatmasi_va_cot_namunalar", {})
    prompt_path = SOURCES_DIR / "argon_cot_system_prompt.json"
    with open(prompt_path, "w", encoding="utf-8") as f:
        json.dump(blok_3, f, ensure_ascii=False, indent=2)
    log.info(f"Blok 3 saqlandi: {prompt_path} (System prompt + {len(blok_3.get('cot_examples', []))} ta CoT namunasi)")

    # 5. Build quick synonym lookup dictionary for search engine
    synonym_map = {}
    for item in blok_1:
        cq = item.get("colloquial_query", "").lower()
        kws = item.get("retrieval_keywords", [])
        legal = item.get("official_legal_term", "")
        if cq:
            synonym_map[cq] = {
                "official_term": legal,
                "keywords": kws
            }
    synonym_lookup_path = SOURCES_DIR / "colloquial_synonym_lookup.json"
    with open(synonym_lookup_path, "w", encoding="utf-8") as f:
        json.dump(synonym_map, f, ensure_ascii=False, indent=2)
    log.info(f"Tezkor qidiruv indeksi yaratildi: {synonym_lookup_path} ({len(synonym_map)} ta kalit)")

if __name__ == "__main__":
    main()
