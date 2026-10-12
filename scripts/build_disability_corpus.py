#!/usr/bin/env python3
"""
Builds the disability-rights corpus from the official Lex.uz portal.

Stages (each one is re-runnable; HTML is cached in data/raw_lex):

  discover   official OKOZ classifier nodes + title searches  -> data/sources/discovered.json
  select     fetch + parse candidates, score relevance, tier   -> data/sources/disability_registry.json
  build      registry -> canonical articles + quality report   -> data/sources/build_report.json (+ .md)
  ingest     embed and write the built articles into the store (needs OPENROUTER_API_KEY unless mock)
  report     data/sources/REGISTRY.md - the generated list of what the corpus contains

Typical run:
  python scripts/build_disability_corpus.py discover
  python scripts/build_disability_corpus.py select
  python scripts/build_disability_corpus.py build
  python scripts/build_disability_corpus.py ingest --store-dir data/store
"""
import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domain.disability_taxonomy import disability_relevance  # noqa: E402
from src.ingestion.corpus_builder import CorpusBuilder, SourceSpec  # noqa: E402
from src.ingestion.lex_client import LexClient  # noqa: E402
from src.ingestion.lex_structured import LexDocumentParser  # noqa: E402
from src.nlp.transliteration import normalize_apostrophes  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("corpus")

SOURCES = ROOT / "data" / "sources"
RAW = ROOT / "data" / "raw_lex"

# Official OKOZ classifier nodes about disability / its social protection (ids verified against the live tree)
DISABILITY_OKOZ_NODES: Dict[int, str] = {
    6533: "06.10.00.00",   # Nogironligi bo'lgan shaxslar va fuqarolarning boshqa toifalarining ijtimoiy himoyasi
    6492: "06.06.03.00",   # Nogironlik pensiyasi
    8792: "06.06.17.00",   # Nogironlikni belgilash
    6510: "06.07.01.03",   # Nogironligi bo'lgan bolalarga nafaqalar
    6519: "06.07.02.01",   # Nogironligi bo'lgan shaxslarga kompensatsiya to'lovlari
    6530: "06.09.01.00",   # Nogironligi bo'lgan shaxslar uchun imtiyozlar
    6457: "05.09.03.00",   # Nogironligi bo'lgan shaxslar mehnati
    6524: "06.08.02.00",   # Davlat muassasalarida ijtimoiy xizmat ko'rsatish
    6526: "06.08.04.00",   # Reabilitatsiya
    7385: "14.01.07.00",   # Keksa yoshdagi va nogironligi bo'lgan shaxslarga tibbiy yordam
    7396: "14.01.10.00",   # Tibbiy-ijtimoiy ekspertiza
    7379: "14.01.03.05",   # Protez-ortopediya yordami
    23502: "06.07.07.00",  # Ijtimoiy himoya yagona reyestri
}
CORE_NODES = {6533, 6492, 8792, 6530, 6457, 7396, 6510, 6519}


def _norm_title(t: str) -> str:
    t = normalize_apostrophes(t or "").lower()
    return re.sub(r"[\s\u201c\u201d\u00ab\u00bb\"]+", " ", t).strip(" .,")


def _title_matches(title: str, expected: str) -> bool:
    t, e = _norm_title(title), _norm_title(expected)
    return t == e or bool(re.match(re.escape(e) + r"(?:\s|$|,)", t) and len(t) <= len(e) + 25)


def _load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------
def cmd_discover(args) -> None:
    seeds = _load_json(SOURCES / "seeds.json", {"seeds": []})["seeds"]
    found: Dict[str, dict] = {}
    previous = _load_json(SOURCES / "discovered.json", {})
    if args.seeds_only and previous:
        found = {d["doc_id"]: d for d in previous.get("documents", [])}
    with LexClient(cache_dir=str(RAW), min_delay=args.delay) as lex:
        tree = {n.node_id: n.name for n in lex.okoz_tree()}
        for node_id, code in ([] if args.seeds_only and previous else DISABILITY_OKOZ_NODES.items()):
            name = tree.get(node_id, "")
            if not name.startswith(code):
                log.warning(f"OKOZ node {node_id} is '{name}', expected code {code} - skipping")
                continue
            hits = lex.search_okoz(node_id)
            log.info(f"OKOZ {code} {name[:60]}: {len(hits)} documents ({sum(h.in_force for h in hits)} in force)")
            for h in hits:
                rec = found.setdefault(h.doc_id, {**h.to_dict(), "nodes": []})
                rec["nodes"].append(node_id)
                rec.pop("okoz_id", None)

        resolved = []
        for seed in seeds:
            if seed.get("lex_id"):
                resolved.append({"seed": seed, "match": {
                    "doc_id": seed["lex_id"], "title": "", "kind_line": "", "in_force": True}, "alternatives": []})
                log.info(f"seed {seed['law_id']}: fixed id {seed['lex_id']} (verified at select)")
                continue
            exact = seed.get("title_equals", "")
            num = seed.get("number_contains", "").lower()
            pick = None
            alternatives: List[str] = []
            for h in lex.iter_search_title(seed["search_title"], max_pages=args.seed_pages):
                if not h.in_force:
                    continue
                if exact and not _title_matches(h.title, exact):
                    continue
                if num and normalize_apostrophes(num) not in normalize_apostrophes(h.kind_line).lower():
                    continue
                if pick is None:
                    pick = h
                    break
                alternatives.append(h.doc_id)
            resolved.append({"seed": seed, "match": pick.to_dict() if pick else None, "alternatives": alternatives})
            log.info(f"seed {seed['law_id']}: {pick.doc_id + ' ' + pick.title[:50] + ' | ' + pick.kind_line[-40:] if pick else 'NOT FOUND'}")

    _save_json(SOURCES / "discovered.json", {
        "generated": date.today().isoformat(),
        "okoz_nodes": DISABILITY_OKOZ_NODES,
        "documents": list(found.values()),
        "seeds": resolved,
    })
    log.info(f"discovered {len(found)} documents via OKOZ, {sum(1 for r in resolved if r['match'])}/{len(resolved)} seeds resolved")


# --------------------------------------------------------------------------------------------------------------
def cmd_select(args) -> None:
    disc = _load_json(SOURCES / "discovered.json", None)
    if not disc:
        sys.exit("run `discover` first")
    parser = LexDocumentParser()
    docs: List[dict] = []
    seeds_by_id: Dict[str, dict] = {}
    for r in disc["seeds"]:
        if r["match"]:
            seeds_by_id[r["match"]["doc_id"]] = r["seed"]
            docs.append({**r["match"], "nodes": [], "seed": r["seed"]})
    docs.extend(d for d in disc["documents"] if d["doc_id"] not in seeds_by_id and d["in_force"])

    registry: List[dict] = []
    rejected: List[dict] = []
    with LexClient(cache_dir=str(RAW), min_delay=args.delay) as lex:
        for i, d in enumerate(docs, 1):
            html = lex.fetch_document(d["doc_id"])
            if html is None:
                rejected.append({"doc_id": d["doc_id"], "title": d["title"], "reason": "not_available"})
                continue
            doc = parser.parse(html, d["doc_id"])
            seed_chk = d.get("seed") or {}
            if seed_chk.get("expect_number") and normalize_apostrophes(doc.number).upper() != normalize_apostrophes(seed_chk["expect_number"]).upper():
                rejected.append({"doc_id": d["doc_id"], "title": doc.title, "reason": f"number_mismatch(got {doc.number!r}, expected {seed_chk['expect_number']!r})"})
                continue
            if seed_chk.get("expect_title_contains") and _norm_title(seed_chk["expect_title_contains"]) not in _norm_title(doc.title):
                rejected.append({"doc_id": d["doc_id"], "title": doc.title, "reason": "title_mismatch"})
                continue
            if doc.status == "repealed":
                rejected.append({"doc_id": d["doc_id"], "title": doc.title, "reason": "repealed"})
                continue
            if not doc.units:
                rejected.append({"doc_id": d["doc_id"], "title": doc.title, "reason": "no_text(body is not published as HTML)"})
                continue
            text = "\n".join(u.text for u in doc.units)
            rel_title = disability_relevance(doc.title)
            rel_text = disability_relevance(text[:60000])
            seed = d.get("seed")
            core_hit = bool(set(d.get("nodes", [])) & CORE_NODES)

            if seed:
                tier, include = int(seed.get("tier", 3)), seed.get("include", "disability_articles")
            elif rel_title >= 1:
                tier, include = 1, "all"
            elif core_hit and rel_text >= 3:
                # indexed under a disability node but about something broader: keep only the disability units
                tier, include = 1, "disability_articles"
            elif rel_text >= 2:
                tier, include = 2, "disability_articles"
            else:
                rejected.append({"doc_id": d["doc_id"], "title": doc.title, "reason": f"not_about_disability(rel={rel_text})"})
                continue

            registry.append({
                "lex_id": d["doc_id"],
                "law_id": seed["law_id"] if seed else "",
                "number": doc.number,
                "number_override": (seed.get("number", "") if seed else ""),
                "title": doc.title,
                "doc_type": doc.doc_type,
                "adopted": doc.adopted_date,
                "effective": doc.effective_date,
                "tier": tier,
                "include": include,
                "category": seed.get("category") if seed else None,
                "nodes": d.get("nodes", []),
                "relevance_title": rel_title,
                "relevance_text": rel_text,
                "units": len(doc.units),
                "verified_at": date.today().isoformat(),
            })
            if i % 25 == 0:
                log.info(f"  {i}/{len(docs)} processed")

    registry.sort(key=lambda r: (r["tier"], -(r["relevance_title"] * 10 + r["relevance_text"])))
    _save_json(SOURCES / "disability_registry.json", {"generated": date.today().isoformat(), "documents": registry})
    _save_json(SOURCES / "rejected.json", rejected)
    tiers = Counter(r["tier"] for r in registry)
    log.info(f"registry: {len(registry)} documents (tiers {dict(tiers)}), rejected {len(rejected)}")


# --------------------------------------------------------------------------------------------------------------
def _specs(max_tier: int) -> List[SourceSpec]:
    reg = _load_json(SOURCES / "disability_registry.json", None)
    if not reg:
        sys.exit("run `select` first")
    return [SourceSpec.from_dict({**d, "number": d.get("number_override", ""), "title_hint": d.get("title", "")})
            for d in reg["documents"] if d.get("tier", 3) <= max_tier]


def cmd_build(args) -> None:
    specs = _specs(args.max_tier)
    builder = CorpusBuilder(LexClient(cache_dir=str(RAW), min_delay=args.delay))
    all_articles = []
    reports = []
    for i, spec in enumerate(specs, 1):
        doc, ru_doc = builder.load(spec, with_russian=not args.no_russian)
        if doc is None:
            reports.append({"lex_id": spec.lex_id, "error": "not_available"})
            continue
        arts, rep = builder.to_articles(doc, spec, ru_doc)
        all_articles.extend(arts)
        reports.append(rep.to_dict())
        log.info(f"[{i}/{len(specs)}] {rep.number or '-':14s} {rep.law_id:34s} units={rep.units_kept:4d}/{rep.units_parsed:<4d} "
                 f"ru={rep.ru_aligned:<4d} {'WARN ' + ','.join(rep.warnings)[:70] if rep.warnings else ''}")
    builder.client.close()

    out = SOURCES / "built_articles.json"
    _save_json(out, [a.model_dump(mode="json") for a in all_articles])
    cats = Counter(a.metadata.category for a in all_articles)
    report = {
        "generated": date.today().isoformat(),
        "documents": reports,
        "articles": len(all_articles),
        "by_category": dict(cats),
        "by_status": dict(Counter(a.metadata.status.value for a in all_articles)),
        "with_russian": sum(1 for a in all_articles if a.translations.get("ru")),
    }
    _save_json(SOURCES / "build_report.json", report)
    log.info(f"built {len(all_articles)} articles from {len(specs)} documents -> {out}")


# --------------------------------------------------------------------------------------------------------------
async def _ingest(args) -> None:
    from src.clients.openrouter import OpenRouterClient
    from src.schema.canonical import CanonicalArticle
    from src.storage.hybrid_store import HybridStore

    items = _load_json(SOURCES / "built_articles.json", None)
    if not items:
        sys.exit("run `build` first")
    articles = [CanonicalArticle.model_validate(i) for i in items]
    store = HybridStore(args.store_dir)
    client = OpenRouterClient()
    if client.is_mock and not args.allow_mock:
        sys.exit("OPENROUTER_API_KEY is not configured (mock mode). Pass --allow-mock to index with fake vectors.")

    if args.replace_all:
        removed = store.clear_all_articles()
        log.info(f"cleared {removed} existing articles (feedback and API keys are kept)")
    elif args.replace_laws:
        law_ids = sorted({a.metadata.law_id for a in articles})
        removed = store.delete_laws(law_ids)
        log.info(f"removed {removed} stale articles of {len(law_ids)} laws before re-indexing")

    if args.metadata_only:
        # refresh text/metadata and the full-text index; embeddings are left as they are
        for art in articles:
            store.fts_store.upsert_article(art)
        log.info(f"refreshed metadata of {len(articles)} articles (no re-embedding)")
        await client.close()
        return

    done = await store.index_articles_batch(articles, client=client, batch_size=args.batch_size)
    log.info(f"indexed {done} articles into {args.store_dir}; store now holds {store.count()} articles")
    await client.close()


def cmd_ingest(args) -> None:
    asyncio.run(_ingest(args))


def cmd_reindex_fts(args) -> None:
    from src.storage.fts_store import SqliteFtsStore
    store = SqliteFtsStore(str(Path(args.store_dir) / "legal_rag.db"))
    log.info(f"re-indexed {store.rebuild_fts_index()} articles in the full-text index")


def cmd_report(args) -> None:
    """Human-readable registry of exactly what is in the corpus (generated, never hand-edited)."""
    reg = _load_json(SOURCES / "disability_registry.json", None)
    rep = _load_json(SOURCES / "build_report.json", None)
    if not reg or not rep:
        sys.exit("run `select` and `build` first")
    by_lex = {d["lex_id"]: d for d in reg["documents"]}
    rows = []
    for d in rep["documents"]:
        if "error" in d:
            continue
        r = by_lex.get(d["lex_id"], {})
        rows.append({**d, "tier": r.get("tier", 3), "include": r.get("include", "all")})
    rows.sort(key=lambda x: (x["tier"], x.get("adopted") or "", x["number"]))

    lines = [
        "# Huquqiy baza reestri (avtomatik hosil qilingan)",
        "",
        f"_Yaratilgan sana: {rep['generated']}. Manba: rasmiy Lex.uz. Qo'lda tahrirlamang - "
        "`python scripts/build_disability_corpus.py report` bilan qayta yaratiladi._",
        "",
        f"- Hujjatlar: **{len(rows)}**, normalar/bandlar: **{rep['articles']}**, rus tilidagi matn bilan: **{rep['with_russian']}**",
        "- Toifalar bo'yicha: " + ", ".join(f"{k} {v}" for k, v in sorted(rep["by_category"].items(), key=lambda kv: -kv[1])),
        "",
        "Daraja: 1 - nogironlik bo'yicha asosiy hujjat, 2 - tegishli umumiy qonun (faqat nogironlikka oid moddalar), "
        "3 - kodeks (faqat nogironlikka oid moddalar).",
        "",
    ]
    names = {1: "1-daraja: asosiy hujjatlar", 2: "2-daraja: tegishli qonunlar", 3: "3-daraja: kodekslar"}
    for tier in (1, 2, 3):
        sub = [r for r in rows if r["tier"] == tier]
        if not sub:
            continue
        lines += [f"## {names[tier]} ({len(sub)})", "", "| Raqam | Sana | Turi | Nomi | Birliklar | RU | Manba |", "|---|---|---|---|---:|---:|---|"]
        for r in sub:
            title = r["title"].replace("|", "/")
            if len(title) > 110:
                title = title[:107] + "..."
            lines.append(
                f"| {r['number'] or '-'} | {r.get('adopted') or ''} | {r['doc_type']} | {title} | {r['units_kept']} | "
                f"{r['ru_aligned'] or ''} | [lex.uz]({r['url']}) |"
            )
        lines.append("")
    out = SOURCES / "REGISTRY.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"wrote {out} ({len(rows)} documents)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("discover", cmd_discover), ("select", cmd_select), ("build", cmd_build), ("ingest", cmd_ingest), ("report", cmd_report), ("reindex-fts", cmd_reindex_fts)):
        p = sub.add_parser(name)
        p.add_argument("--delay", type=float, default=1.0, help="seconds between Lex.uz requests")
        p.add_argument("--seed-pages", type=int, default=15, help="max result pages scanned per curated seed")
        p.add_argument("--seeds-only", action="store_true", help="discover: re-resolve seeds, keep earlier OKOZ results")
        p.set_defaults(func=fn)
    sub.choices["build"].add_argument("--max-tier", type=int, default=3)
    sub.choices["build"].add_argument("--no-russian", action="store_true")
    sub.choices["reindex-fts"].add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    ing = sub.choices["ingest"]
    ing.add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    ing.add_argument("--batch-size", type=int, default=15)
    ing.add_argument("--allow-mock", action="store_true")
    ing.add_argument("--replace-laws", action="store_true", help="delete existing articles of the same law_id first")
    ing.add_argument("--replace-all", action="store_true", help="empty the corpus first (full rebuild)")
    ing.add_argument("--metadata-only", action="store_true", help="update stored text/metadata + FTS without re-embedding")
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
