#!/usr/bin/env python3
"""
scripts/analyze_harvested.py - Analyze harvested Q&As from Tuzuk AI, cross-check against registry,
and format clean FAQ cards for the frontend / knowledge base.
"""
import json
import re
from pathlib import Path

REGISTRY_PATH = Path("data/sources/disability_registry.json")
HARVEST_DIRS = [
    Path("data/sources/harvested_tuzuk"),
    Path("data/sources/harvested_benchmark")
]
OUTPUT_FAQ_PATH = Path("data/sources/website_faq_knowledge_base.json")
MISSING_ACTS_PATH = Path("data/sources/discovered_missing_acts.json")

KNOWN_ALIASES = {
    "41329": "-26013",   # Fuqarolar sog'lig'ini saqlash to'g'risida (Cyrillic ID -> Latin canonical)
    "3517334": "-3517337", # Fuqarolik protsessual kodeksi (Cyrillic ID -> Latin canonical)
    "8445749": "-8503049",  # VMQ-505 22.09.2026 (Tuzuk cited element ID -> canonical Lex ID)
    "-8445749": "-8503049",
    "6257291": "-6257288",  # Mehnat kodeksi anchor ID -> canonical doc ID
    "-6257291": "-6257288",
    "5049549": "-5049511",  # O'RQ-641 Cyrillic ID -> Latin canonical doc ID
    "-5049549": "-5049511",
    "5055696": "-5055690",  # O'RQ-642 Cyrillic ID -> Latin canonical doc ID
    "-5055696": "-5055690",
    "180550": "-180552",    # Fuqarolik kodeksi Cyrillic ID -> Latin canonical doc ID
    "-180550": "-180552",
    "2240472": "-2240470",  # O'RQ-353 OIV to'g'risida Cyrillic ID -> Latin canonical doc ID
    "-2240472": "-2240470",
    "2325614": "-2325612",  # VMQ-15 Cyrillic ID -> Latin canonical doc ID
    "-2325614": "-2325612",
    "6684617": "-6684613",  # VMQ-704 Cyrillic ID -> Latin canonical doc ID
    "-6684617": "-6684613",
    "112312": "-112314",    # Pensiya qonuni Cyrillic ID -> Latin canonical doc ID
    "-112312": "-112314",
    "5373753": "-5373771",  # O'RQ-688 Fuqarolik qonuni Cyrillic ID -> Latin canonical doc ID
    "-5373753": "-5373771",
    "2896474": "-112314",   # MDH pensiya bitimi (ruscha matn) -> Milliy Pensiya qonuni
    "-2896474": "-112314",
    "1721067": "-1721063",  # O'RQ-276 Dafn etish to'g'risida Cyrillic ID -> Latin canonical doc ID
    "-1721067": "-1721063",
    "5865497": "-5865484",  # PF-70 Cyrillic ID -> Latin canonical doc ID
    "-5865497": "-5865484",
    "2509996": "-3336169",  # O'RQ-378 (eski tahrir) -> O'RQ-445 (yangi tahrirdagi Murojaatlar to'g'risida Qonun)
    "-2509996": "-3336169",
    "6819217": "-6819215",  # PQ-88 Cyrillic ID -> Latin canonical doc ID
    "-6819217": "-6819215",
    "4674893": "-4674902",  # Soliq kodeksi anchor -> Latin canonical doc ID
    "-4674893": "-4674902",
    "6297082": "-6297080",  # O'RQ-803 Cyrillic ID -> Latin canonical doc ID
    "-6297082": "-6297080",
    "2978666": "-2978664",  # VMQ-191 Cyrillic ID -> Latin canonical doc ID
    "-2978666": "-2978664",
    "1470265": "-1470263",  # VMQ-110 Cyrillic ID -> Latin canonical doc ID
    "-1470265": "-1470263",
    "2876352": "-2876354",  # Bojxona kodeksi Cyrillic ID -> Latin canonical doc ID
    "-2876352": "-2876354",
    "6725094": "-6725077",  # PQ-410 Cyrillic ID -> Latin canonical doc ID
    "-6725094": "-6725077",
    "3765162": "-3765153",  # VMQ-411 Cyrillic ID -> Latin canonical doc ID
    "-3765162": "-3765153",
    "7215999": "-7215989",  # Cyrillic ID -> Latin canonical doc ID
    "5013009": "-5013007",  # Cyrillic ID -> Latin canonical doc ID
    "-5013009": "-5013007",
    "2467539": "-2467536",  # VMQ-269 Cyrillic ID -> Latin canonical doc ID
    "-2467539": "-2467536",
    "6248469": "-6248467",  # PQ-407 Cyrillic ID -> Latin canonical doc ID
    "-6248469": "-6248467",
    "5569701": "-5569689",  # PQ-5216 Cyrillic ID -> Latin canonical doc ID
    "-5569701": "-5569689",
    "7051594": "-7051573",  # O'RQ-939 Cyrillic ID -> Latin canonical doc ID
    "-7051594": "-7051573",
    "3263332": "-3263328",  # VMQ-484 Cyrillic ID -> Latin canonical doc ID
    "-3263332": "-3263328",
    "55599": "-55594",      # Cyrillic ID -> Latin canonical doc ID
    "-55599": "-55594",
    "7027442": "-7027440",  # Cyrillic ID -> Latin canonical doc ID
    "-7027442": "-7027440",
    "1521663": "-1521661",  # O'RQ-226 Cyrillic ID -> Latin canonical doc ID
    "-1521663": "-1521661",
    "7239400": "-7239390",  # O'RQ-1006 Cyrillic ID -> Latin canonical doc ID
    "-7239400": "-7239390",
    "2591898": "-2591903",  # Cyrillic ID -> Latin canonical doc ID
    "-2591898": "-2591903",
    "104723": "-104720",    # Cyrillic ID -> Latin canonical doc ID
    "-104723": "-104720",
    "2414323": "-2414320",  # Cyrillic ID -> Latin canonical doc ID
    "-2414323": "-2414320",
    "57043": "-54458",      # Cyrillic ID -> Latin canonical doc ID
    "-57043": "-54458",
    "1449507": "-1449509",  # Cyrillic ID -> Latin canonical doc ID
    "-1449507": "-1449509",
    "8345471": "-8345381",  # Cyrillic ID -> Latin canonical doc ID
    "-8345471": "-8345381",
    "3034917": "-3034913",  # Cyrillic ID -> Latin canonical doc ID
    "-3034917": "-3034913",
    "170150": "-170143",    # Cyrillic ID -> Latin canonical doc ID
    "-170150": "-170143",
    "6600415": "-6600390",  # Cyrillic ID -> Latin canonical doc ID
    "-6600415": "-6600390",
    "246698": "-246696",    # VMQ-472 Cyrillic ID -> Latin canonical doc ID
    "2627700": "-55594",    # MDH urush nogironlari bitimi -> VMQ-507 milliy qaror
    "-2627700": "-55594",
    "2628006": "-55594",    # MDH urush nogironlari bitimi -> VMQ-507 milliy qaror
    "-2628006": "-55594",
}

def load_registry():
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    registry_lex_ids = set()
    registry_numbers = set()
    for doc in data.get("documents", []):
        lid = str(doc.get("lex_id", "")).strip()
        if lid:
            registry_lex_ids.add(lid)
            registry_lex_ids.add(lid.lstrip("-"))
            registry_lex_ids.add(f"-{lid.lstrip('-')}")
        num = doc.get("number", "").strip().upper()
        if num:
            registry_numbers.add(num)
    return data, registry_lex_ids, registry_numbers

def extract_lex_ids(text_or_urls):
    found = set()
    if isinstance(text_or_urls, list):
        for item in text_or_urls:
            found.update(extract_lex_ids(item))
        return found
    
    matches = re.findall(r"lex\.uz/docs/(-?\d+)", str(text_or_urls))
    for m in matches:
        found.add(m)
    return found

def extract_doc_numbers(text):
    patterns = [
        r"(?:O['’‘`]?RQ|PF|PQ|VMQ|Qaror|Qonun)[-\s]?\d+",
        r"Vazirlar Mahkamasining\s+(?:\d{4}-yil\s+\d+-[a-z]+dagi\s+)?(\d+)-son\s+qarori",
        r"Prezidentning\s+(?:\d{4}-yil\s+\d+-[a-z]+dagi\s+)?(?:PQ-|PF-)?(\d+)-son",
    ]
    results = set()
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        for m in matches:
            if isinstance(m, str) and len(m) > 1:
                results.add(m.strip())
    return results

def main():
    _, reg_ids, reg_nums = load_registry()
    print(f"Bazada jami {len(reg_ids)//3} ta hujjat ro'yxatga olingan.")

    harvest_files = []
    for hdir in HARVEST_DIRS:
        if hdir.exists():
            harvest_files.extend(sorted(hdir.glob("*.json")))

    if not harvest_files:
        print("Hozircha yig'ilgan fayllar yo'q.")
        return

    all_qas = []
    seen_questions = set()

    for hf in harvest_files:
        try:
            with open(hf, "r", encoding="utf-8") as f:
                items = json.load(f)
                if isinstance(items, dict):
                    items = [items]
                for item in items:
                    q = item.get("question", "").strip()
                    if q and q not in seen_questions:
                        seen_questions.add(q)
                        all_qas.append(item)
        except Exception as e:
            print(f"Xatolik {hf.name} faylini o'qishda: {e}")

    print(f"Jami yig'ilgan unikal savol-javoblar soni: {len(all_qas)}")

    missing_lex_ids = set()
    verified_citations = []
    faq_items = []

    for item in all_qas:
        q = item.get("question", "")
        ans = item.get("answer", "")
        cited = item.get("cited_sources", [])
        laws = item.get("laws_mentioned", [])

        # Extract lex IDs from cited URLs and answer text
        all_text = f"{ans} " + " ".join(cited) + " " + " ".join(laws)
        lex_ids = extract_lex_ids(all_text)
        
        item_citations = []
        for lid in lex_ids:
            clean_lid = lid.lstrip("-")
            canonical_lid = KNOWN_ALIASES.get(clean_lid, KNOWN_ALIASES.get(lid, lid))
            c_clean = canonical_lid.lstrip("-")
            is_in_registry = (
                lid in reg_ids or clean_lid in reg_ids or f"-{clean_lid}" in reg_ids or
                canonical_lid in reg_ids or c_clean in reg_ids or f"-{c_clean}" in reg_ids
            )
            item_citations.append({
                "lex_id": lid,
                "canonical_lex_id": canonical_lid,
                "in_our_registry": is_in_registry,
                "url": f"https://lex.uz/docs/{lid}"
            })
            if not is_in_registry:
                missing_lex_ids.add(lid)

        faq_items.append({
            "id": len(faq_items) + 1,
            "category": item.get("category", "Umumiy huquqlar"),
            "question": q,
            "answer": ans,
            "citations": item_citations,
            "laws_mentioned": laws
        })

    # Save formatted FAQ
    with open(OUTPUT_FAQ_PATH, "w", encoding="utf-8") as f:
        json.dump(faq_items, f, ensure_ascii=False, indent=2)
    print(f"Formatlangan FAQ bazasi yaratildi: {OUTPUT_FAQ_PATH} ({len(faq_items)} ta)")

    if missing_lex_ids:
        print(f"DIQQAT! Bazamizda yo'q {len(missing_lex_ids)} ta yangi Lex.uz hujjati topildi: {missing_lex_ids}")
        with open(MISSING_ACTS_PATH, "w", encoding="utf-8") as f:
            json.dump(list(missing_lex_ids), f, indent=2)
    else:
        print("Barcha iqtibos qilingan Lex.uz hujjatlari 100% bizning korpusimizda mavjud!")

if __name__ == "__main__":
    main()
