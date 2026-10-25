#!/usr/bin/env python3
"""
Finds units whose Russian text is not a translation of their Uzbek text.

Lex.uz publishes the Uzbek and the Russian edition of an act separately; the importer pairs their points by number.
Where the two editions number an annex differently, point 6 of one annex received point 6 of another annex (seen in
the Regulation on medical and social expertise, VMQ-62). A Russian question is answered from the Russian text, so a
wrong pairing becomes a wrong answer.

The check is cross-lingual: the beginning of both texts is embedded with the production embedding model (bge-m3 is
multilingual) and the two vectors are compared. Translations of each other score high; unrelated texts score low. (The
stored Uzbek vectors are not used: they embed the act's title with the text, which lowers the score of short points.)
Embeddings are kept in eval/cache/{uz,ru}_vectors.npz, so a second run is free.

  python scripts/audit_translations.py                    # report: eval/reports/translation_alignment.json
  python scripts/audit_translations.py --apply            # removes the misaligned Russian texts (Uzbek stays)

A pair is misaligned when its own similarity is below --threshold, or when the Russian text is closer (by more than
--margin) to the Uzbek text of ANOTHER unit of the same act than to its own: that is the signature of the shifted
pairing (in annexes that number several lists 1, 2, 3 ... the importer gave point 7 of one list the Russian point 7 of
another). On 2026-10-25 this flagged 284 of 15,247 pairs; aligned pairs score 0.70-0.95. Removing a correct Russian
text costs little (the answer is then written from the Uzbek text); keeping a wrong one costs a wrong answer.
"""
import argparse
import hashlib
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPEND_SCOPE", "eval")

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.config import settings  # noqa: E402
from src.ingestion.translation_alignment import closer_matches  # noqa: E402

CACHE_DIR = ROOT / "eval" / "cache"
REPORT = ROOT / "eval" / "reports" / "translation_alignment.json"
HEAD = 1500          # characters of each text compared (the first chunk of the Uzbek vector covers the beginning)


def load_units(db_path: Path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    units = {}
    for cid, raw in con.execute("SELECT canonical_id, json_data FROM articles_metadata"):
        tr = json.loads(raw).get("translations") or {}
        if (tr.get("ru") or "").strip() and (tr.get("uz") or "").strip():
            units[cid] = (tr["uz"], tr["ru"])
    con.close()
    return units


def _cache_key(cid: str, text: str) -> str:
    """The id and a hash of the embedded text: after a re-parse changes a unit's text its old vector is not reused."""
    return f"{cid}#{hashlib.sha1(text[:HEAD].encode('utf-8')).hexdigest()[:12]}"


async def embed_cached(units: dict, lang: str) -> dict:
    """{unit id: vector of the first HEAD characters of its `lang` text}, from the cache where the text is unchanged."""
    path = CACHE_DIR / f"{lang}_vectors_v2.npz"
    col = 0 if lang == "uz" else 1
    cached = {}
    if path.exists():
        data = np.load(path, allow_pickle=False)
        cached = dict(zip(data["ids"].tolist(), data["vectors"]))
    keys = {cid: _cache_key(cid, units[cid][col]) for cid in units}
    todo = [cid for cid in units if keys[cid] not in cached]
    if todo:
        client = OpenRouterClient()
        if client.embedding_is_mock:
            raise SystemExit("no OpenRouter key: the check needs the real embedding model")
        t0 = time.time()
        for i in range(0, len(todo), 192):
            part = todo[i:i + 192]
            vecs = await client.get_embeddings([units[c][col][:HEAD] for c in part])
            cached.update({keys[c]: np.asarray(v, dtype=np.float32) for c, v in zip(part, vecs)})
            if (i // 192) % 10 == 0:
                print(f"  {lang}: embedded {min(i + 192, len(todo))}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
                path.parent.mkdir(parents=True, exist_ok=True)
                np.savez(path, ids=np.array(list(cached)), vectors=np.stack(list(cached.values())))
        await client.close()
        np.savez(path, ids=np.array(list(cached)), vectors=np.stack(list(cached.values())))
    return {cid: cached[keys[cid]] for cid in units}


def cosine(a, b) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-dir", default=str(ROOT / settings.STORAGE_DIR))
    ap.add_argument("--threshold", type=float, default=0.55, help="below this similarity the pair is called misaligned")
    ap.add_argument("--margin", type=float, default=0.06, help="how much closer another unit's Uzbek text must be")
    ap.add_argument("--apply", action="store_true", help="remove the Russian text of the misaligned units")
    args = ap.parse_args()
    store_dir = Path(args.store_dir)
    db = store_dir / "legal_rag.db"

    units = load_units(db)
    uz = asyncio.run(embed_cached(units, "uz"))
    ru = asyncio.run(embed_cached(units, "ru"))
    scores = {cid: round(cosine(uz[cid], ru[cid]), 4) for cid in units if cid in uz and cid in ru}
    closer = closer_matches(scores, uz, ru, args.margin)
    low = sorted((s, cid) for cid, s in scores.items() if s < args.threshold or cid in closer)
    hist = np.histogram(list(scores.values()), bins=[0, .3, .4, .5, .55, .6, .65, .7, .8, .9, 1.01])
    report = {
        "units_with_ru": len(units), "scored": len(scores), "threshold": args.threshold,
        "margin": args.margin,
        "histogram": {f"{hist[1][i]:.2f}-{hist[1][i + 1]:.2f}": int(hist[0][i]) for i in range(len(hist[0]))},
        "misaligned": [{"id": cid, "similarity": s, "closer_to": closer.get(cid), "uz": units[cid][0][:160],
                        "ru": units[cid][1][:160]} for s, cid in low],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("units_with_ru", "scored", "threshold", "margin", "histogram")}, indent=1))
    print(f"misaligned: {len(low)} -> {REPORT}")

    if args.apply and low:
        from src.storage.hybrid_store import HybridStore
        store = HybridStore(str(store_dir))
        changed = 0
        for _, cid in low:
            art = store.get_article(cid)
            if art is None or "ru" not in art.translations:
                continue
            art.translations.pop("ru", None)
            art.metadata.article_title.pop("ru", None)     # the Russian title came from the same wrong unit
            store.fts_store.upsert_article(art)          # text only: the Uzbek vector does not change
            changed += 1
        print(f"Russian text removed from {changed} units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
