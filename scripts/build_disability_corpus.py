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
from typing import Dict, List, Tuple

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

# An act about social assistance states its procedure (how often, how much, card or voucher, where to apply) in
# general units that never say "nogironlik": keeping only the disability units loses exactly what people ask about.
# Such acts, and acts the Huquq+ editors cite, are kept whole unless they are codes or very long.
MAX_WHOLE_UNITS = 300
_SOCIAL_TITLE = re.compile(
    r"ijtimoiy (himoya|yordam|xizmat|qo'llab|ta'minot|karta|reyestr)|nafaqa|pensiya|parvarish|vaucher|daftar"
    r"|saxovat|kambag'al|muhtoj|imtiyoz|reabilitatsiya|protez|dori vosita|sanatoriy|moddiy yordam|kompensatsiya"
    r"|subsidiya")


def _keep_whole(title: str, units: int, doc_type: str, *, tier: int, cited_posts: int = 0) -> bool:
    if doc_type == "Kodeks" or "kodeks" in title.lower() or units > MAX_WHOLE_UNITS:
        return False
    social = bool(_SOCIAL_TITLE.search(normalize_apostrophes(title).lower()))
    if cited_posts:
        # an editor citation alone may concern one clause of a long general act (railway rules, police law)
        return social or (cited_posts >= 2 and units <= 150)
    return int(tier) == 1 and social


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
            if not seed and include == "disability_articles" and _keep_whole(
                    doc.title, len(doc.units), doc.doc_type, tier=tier):
                include = "all"

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

    # documents added by `cited` (Huquq+ citations) are not in discovered.json - keep them across re-selects
    previous = _load_json(SOURCES / "disability_registry.json", {"documents": []})["documents"]
    have = {r["lex_id"] for r in registry}
    registry.extend(r for r in previous if r.get("source") in ("huquqplus_cited", "domain_review") and r["lex_id"] not in have)

    registry.sort(key=lambda r: (r["tier"], -(r["relevance_title"] * 10 + r["relevance_text"])))
    _save_json(SOURCES / "disability_registry.json", {"generated": date.today().isoformat(), "documents": registry})
    _save_json(SOURCES / "rejected.json", rejected)
    tiers = Counter(r["tier"] for r in registry)
    log.info(f"registry: {len(registry)} documents (tiers {dict(tiers)}), rejected {len(rejected)}")


# --------------------------------------------------------------------------------------------------------------
# Acts that only amend other acts: their text is a list of edits, the amended act carries the law.
_AMENDING_TITLE = re.compile(r"(?:o'zgartish|o'zgartirish|qo'shimcha)\w*\s+(?:va\s+qo'shimcha\w*\s+)?kiritish", re.I)
_QUOTED_TITLE = re.compile(r"[“\"«]([^”\"»]{12,})[”\"»]")


def _lex_id_of(url: str) -> str:
    m = re.search(r"/docs/(-?\d+)", url or "")
    return m.group(1) if m else ""


def _latin_edition(lex: LexClient, parser: LexDocumentParser, doc_id: str) -> str:
    """Latin-Uzbek edition id of a cited Lex.uz id (cited ids may be the Cyrillic or the Russian edition)."""
    raw = str(doc_id).strip()
    if raw.startswith("-"):
        return raw
    if lex.fetch_url(f"https://lex.uz/uz/docs/-{raw}"):          # Cyrillic id N -> Latin edition -N
        return f"-{raw}"
    html = lex.fetch_url(f"https://lex.uz/uz/docs/{raw}")
    if not html:
        return ""
    return _lex_id_of(parser.parse(html, raw).language_links.get("uz_latn", ""))


def _title_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z']{4,}", _norm_title(text)) if w not in ("to'g'risida", "haqida")}


def _amended_act(lex: LexClient, parser: LexDocumentParser, html: str, title: str) -> Tuple[str, str]:
    """
    (lex id, reason) of the single act an amending act changes. Candidates are the acts its text links to on
    Lex.uz; the one whose title the amending act repeats wins. Acts amending "ayrim ..." (several acts) are skipped.
    """
    if re.search(r"\bayrim\b", _norm_title(title)):
        return "", "amends_several_acts"
    m = _QUOTED_TITLE.search(title or "")
    named = _title_words(m.group(1) if m else title)
    body = html.split('id="divCont"', 1)[-1]
    linked = Counter(i for i in re.findall(r'/docs/(-?\d+)', body))
    best, best_score = None, 0.0
    for lex_id, _ in linked.most_common(12):
        cand_html = lex.fetch_document(lex_id)
        if not cand_html:
            continue
        cand = parser.parse(cand_html, lex_id)
        words = _title_words(cand.title)
        score = len(words & named) / max(1, len(words))
        if score > best_score and not _AMENDING_TITLE.search(normalize_apostrophes(cand.title)):
            best, best_score = cand, score
    if best is None or best_score < 0.6:
        return "", "base_act_not_found"
    if best.status == "repealed":
        return "", f"base_act_not_in_force({best.number} {best.repealed_date or 'yangi tahrir'})"
    return best.doc_id, ""


def cmd_cited(args) -> None:
    """
    Lex.uz acts cited by Huquq+ articles but missing from the corpus -> registry candidates.

    Reads data/sources/huquqplus_cited_missing.json, folds Cyrillic/Russian ids onto the Latin edition, replaces an
    amending act by the act it amends, skips data/sources/cited_exclusions.json and scores each act like `select`
    does. Writes data/sources/huquqplus_cited_selection.json; with --apply also appends the accepted acts to the
    registry (source "huquqplus_cited"), after which `build` and `refresh --law-ids=...` bring them into the store.
    """
    cited = _load_json(SOURCES / "huquqplus_cited_missing.json", None)
    if not cited:
        sys.exit("data/sources/huquqplus_cited_missing.json not found")
    reg = _load_json(SOURCES / "disability_registry.json", {"documents": []})
    in_registry = {d["lex_id"] for d in reg["documents"]}
    excluded = _load_json(SOURCES / "cited_exclusions.json", {}).get("exclusions", {})
    parser = LexDocumentParser()

    candidates: Dict[str, dict] = {}
    unresolved: List[dict] = []
    with LexClient(cache_dir=str(RAW), min_delay=args.delay) as lex:
        for c in cited["documents"]:
            latin = _latin_edition(lex, parser, c["doc_id"])
            if not latin:
                unresolved.append({"doc_id": c["doc_id"], "reason": "no_latin_edition"})
                continue
            rec = candidates.setdefault(latin, {"lex_id": latin, "cited_ids": [], "posts": 0, "citations": 0})
            rec["cited_ids"].append(c["doc_id"])
            rec["posts"] += c.get("posts", 0)
            rec["citations"] += c.get("citations", 0)

        added: List[dict] = []
        rejected: List[dict] = []
        present: List[dict] = []
        queue = list(candidates.values())
        seen = set()
        while queue:
            c = queue.pop(0)
            lex_id = c["lex_id"]
            if lex_id in seen:
                continue
            seen.add(lex_id)
            if lex_id in in_registry:
                present.append(c)
                continue
            if lex_id in excluded:
                rejected.append({**c, "reason": "excluded", "note": excluded[lex_id]})
                continue
            html = lex.fetch_document(lex_id)
            if html is None:
                rejected.append({**c, "reason": "not_available"})
                continue
            doc = parser.parse(html, lex_id)
            title = normalize_apostrophes(doc.title)
            base = {**c, "number": doc.number, "title": doc.title, "doc_type": doc.doc_type}
            if doc.status == "repealed":
                rejected.append({**base, "reason": "repealed", "repealed_date": doc.repealed_date or "yangi tahrir"})
                continue
            if _AMENDING_TITLE.search(title):
                target, why = _amended_act(lex, parser, html, doc.title)
                rejected.append({**base, "reason": "amending_act", "amends": target or why})
                if target:
                    queue.append({"lex_id": target, "cited_ids": c["cited_ids"], "posts": c["posts"],
                                  "citations": c["citations"], "via_amending_act": lex_id})
                continue
            if not doc.units:
                rejected.append({**base, "reason": "no_text(body is not published as HTML)"})
                continue
            rel_title = disability_relevance(doc.title)
            rel_text = disability_relevance("\n".join(u.text for u in doc.units)[:60000])
            dis_units = sum(1 for u in doc.units if disability_relevance(f"{u.title}\n{u.text}") > 0)
            if doc.doc_type == "Kodeks":
                tier, include = 3, "disability_articles"
            elif rel_title >= 1:
                tier, include = 1, "all"
            elif rel_text >= args.min_rel_all and len(doc.units) <= args.max_units_all:
                tier, include = 2, "all"              # a short act largely about disability benefits: keep it whole
            elif _keep_whole(doc.title, len(doc.units), doc.doc_type, tier=2, cited_posts=c["posts"]):
                tier, include = 2, "all"              # cited by the Huquq+ editors: its procedure is what readers ask
            else:
                tier, include = 2, "disability_articles"
            if include == "disability_articles" and not dis_units:
                rejected.append({**base, "reason": f"not_about_disability(rel={rel_text})", "units": len(doc.units)})
                continue
            added.append({
                "lex_id": lex_id, "law_id": "", "number": doc.number, "number_override": "",
                "title": doc.title, "doc_type": doc.doc_type, "adopted": doc.adopted_date,
                "effective": doc.effective_date, "tier": tier, "include": include, "category": None,
                "nodes": [], "relevance_title": rel_title, "relevance_text": rel_text, "units": len(doc.units),
                "verified_at": date.today().isoformat(), "source": "huquqplus_cited",
                "cited_posts": c["posts"], "cited_citations": c["citations"], "cited_ids": c["cited_ids"],
                **({"via_amending_act": c["via_amending_act"]} if c.get("via_amending_act") else {}),
                "_kept_units": len(doc.units) if include == "all" else dis_units,
            })

    _save_json(SOURCES / "huquqplus_cited_selection.json", {
        "generated": date.today().isoformat(), "added": added, "rejected": rejected,
        "already_in_registry": present, "unresolved": unresolved,
    })
    log.info(f"cited: {len(candidates)} distinct acts -> add {len(added)} "
             f"({sum(a['_kept_units'] for a in added)} units), rejected {len(rejected)}, "
             f"already in registry {len(present)}, unresolved {len(unresolved)}")
    for why, n in Counter(r["reason"].split("(")[0] for r in rejected).most_common():
        log.info(f"  rejected {why}: {n}")
    if args.apply and added:
        reg["documents"].extend({k: v for k, v in a.items() if not k.startswith("_")} for a in added)
        _save_json(SOURCES / "disability_registry.json", reg)
        log.info(f"registry: +{len(added)} documents. Next: build, then refresh --law-ids "
                 + ",".join(a["lex_id"] for a in added[:3]) + ",...")


def cmd_widen(args) -> None:
    """
    Applies the keep-whole rule (_keep_whole) to documents already in the registry: an act that is cut to its
    disability units but is cited by Huquq+ or is a tier-1 social-assistance act becomes include "all". Seeded acts
    keep their curated setting. With --apply writes the registry; then `build` and `refresh --law-ids=...`.
    """
    reg = _load_json(SOURCES / "disability_registry.json", None)
    if not reg:
        sys.exit("run `select` first")
    changed = []
    for d in reg["documents"]:
        if d.get("include") != "disability_articles" or d.get("law_id"):
            continue
        if _keep_whole(d.get("title", ""), int(d.get("units") or 0), d.get("doc_type", ""),
                       tier=d.get("tier", 3), cited_posts=int(d.get("cited_posts") or 0)):
            changed.append(d)
    for d in changed:
        log.info(f"  all <- {d.get('number') or d['lex_id']:14s} units={d.get('units'):>4} "
                 f"{'cited' if d.get('source') == 'huquqplus_cited' else 'tier' + str(d.get('tier'))}  {d['title'][:80]}")
    log.info(f"widen: {len(changed)} documents, up to {sum(int(d.get('units') or 0) for d in changed)} units")
    if args.apply and changed:
        for d in changed:
            d["include"] = "all"
            d["widened_at"] = date.today().isoformat()
        _save_json(SOURCES / "disability_registry.json", reg)
        log.info("registry updated. Next: build, then refresh --law-ids=" + ",".join(d["lex_id"] for d in changed))


def cmd_domain(args) -> None:
    """
    Life-domain acts (appeals, administrative procedure, legal aid, consumer rights, social protection of related
    groups...) that never say "nogironlik" but decide everyday cases. Reads data/sources/domain_candidates.json
    (each act read and verified from Lex.uz) and data/sources/domain_overrides.json (curator decisions:
    "skip" / "partial", each with a reason); with --apply appends the accepted acts to the registry
    (source "domain_review"), then `build` and `refresh --law-ids=...`.
    """
    cands = _load_json(SOURCES / "domain_candidates.json", None)
    if not cands:
        sys.exit("data/sources/domain_candidates.json not found")
    over = _load_json(SOURCES / "domain_overrides.json", {"skip": {}, "partial": {}})
    reg = _load_json(SOURCES / "disability_registry.json", {"documents": []})
    have = {d["lex_id"] for d in reg["documents"]}
    added = []
    for c in cands["candidates"]:
        lex_id = c["lex_id"]
        if c.get("decision") != "include" or lex_id in have or lex_id in over.get("skip", {}):
            continue
        if c.get("status") != "active" or not c.get("units"):
            continue
        include = "disability_articles" if lex_id in over.get("partial", {}) else "all"
        added.append({
            "lex_id": lex_id, "law_id": "", "number": c.get("number", ""), "number_override": "",
            "title": c["title"], "doc_type": c.get("doc_type", ""), "adopted": c.get("adopted"), "effective": None,
            "tier": 2, "include": include, "category": None, "nodes": [], "relevance_title": 0, "relevance_text": 0,
            "units": int(c["units"]), "verified_at": date.today().isoformat(), "source": "domain_review",
            "domain": c.get("domain", ""), "domain_reason": c.get("reason", ""),
        })
        have.add(lex_id)
    for a in added:
        log.info(f"  + {a['number'] or a['lex_id']:12s} {a['include']:20s} units={a['units']:>4} {a['title'][:80]}")
    log.info(f"domain: {len(added)} acts, up to {sum(a['units'] for a in added)} units "
             f"(skipped by curator: {len(over.get('skip', {}))}, partial: {len(over.get('partial', {}))})")
    if args.apply and added:
        reg["documents"].extend(added)
        _save_json(SOURCES / "disability_registry.json", reg)
        log.info("registry updated. Next: build, then refresh --law-ids=" + ",".join(a["lex_id"] for a in added))


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

    try:
        from src.editorial.store import EditorialStore
        from src.editorial.watch import check_legal_links
        res = check_legal_links(store, EditorialStore(str(Path(args.store_dir) / "editorial.db")))
        log.info(f"editorial watch after ingest: {res}")
    except Exception as e:
        log.warning(f"check_legal_links after ingest failed: {e}")


def cmd_ingest(args) -> None:
    asyncio.run(_ingest(args))


def _existing_state(store, law_id: str) -> Dict[str, Tuple[str, str]]:
    """canonical_id -> (source_hash, status) for one law_id (reads the metadata columns, not full JSON)."""
    with store.fts_store._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT canonical_id, source_hash, status FROM articles_metadata
            WHERE json_extract(json_data, '$.metadata.law_id') = ?
        """, (law_id,))
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def cmd_refresh(args) -> None:
    """Re-downloads registry documents and upserts only changed/new units (mockable network layer)."""
    from src.clients.openrouter import OpenRouterClient
    from src.storage.hybrid_store import HybridStore

    reg = _load_json(SOURCES / "disability_registry.json", None)
    if not reg:
        sys.exit("run `select` first")
    docs = reg["documents"]
    wanted = None
    if getattr(args, "law_ids", None):
        wanted = {s.strip() for s in args.law_ids.split(",") if s.strip()}
        docs = [d for d in docs if d.get("law_id") in wanted or d.get("lex_id") in wanted]
    if getattr(args, "limit", None):
        docs = docs[: args.limit]

    store = HybridStore(args.store_dir)
    client = OpenRouterClient()
    if client.is_mock and not args.allow_mock:
        sys.exit("OPENROUTER_API_KEY is not configured (mock mode). Pass --allow-mock to refresh with fake vectors.")

    builder = CorpusBuilder(LexClient(cache_dir=str(RAW), min_delay=args.delay))
    per_doc = []
    to_index = []
    removed_total = 0
    for d in docs:
        spec = SourceSpec.from_dict({**d, "number": d.get("number_override", ""), "title_hint": d.get("title", "")})
        try:
            # force: the HTML cache holds the text as it was at build time; refresh must see today's wording
            doc, ru_doc = builder.load(spec, with_russian=True, force=True)
        except Exception as e:                      # network/HTTP failure: keep the stored text untouched
            per_doc.append({"lex_id": d.get("lex_id"), "law_id": d.get("law_id"), "error": f"fetch_failed: {e}"})
            continue
        if doc is None:
            per_doc.append({"lex_id": d.get("lex_id"), "law_id": d.get("law_id"), "error": "not_available"})
            continue
        arts, rep = builder.to_articles(doc, spec, ru_doc)
        law_id = arts[0].metadata.law_id if arts else (d.get("law_id") or "")
        existing = _existing_state(store, law_id) if law_id else {}
        if not arts:
            # an empty parse (layout change, error page) must never wipe a law from the knowledge base
            per_doc.append({"lex_id": d.get("lex_id"), "law_id": law_id, "error": "no_units_parsed"})
            continue
        new_ids = set()
        changed = 0
        for a in arts:
            new_ids.add(a.canonical_id)
            # status is compared too: a repealed act keeps its wording, so its hash does not change
            if existing.get(a.canonical_id) != (a.metadata.source_hash, a.metadata.status.value):
                to_index.append(a)
                changed += 1
        missing = [cid for cid in existing if cid not in new_ids]
        if existing and len(missing) > max(5, len(existing) // 2) and not args.allow_mass_removal:
            # renumbered edition or a parser problem - a human decides (re-run with --allow-mass-removal)
            to_index = [a for a in to_index if a.metadata.law_id != law_id]
            per_doc.append({"lex_id": d.get("lex_id"), "law_id": law_id, "error": "mass_removal_blocked",
                            "units": len(arts), "would_remove": len(missing), "existing": len(existing)})
            log.warning(f"{law_id}: {len(missing)}/{len(existing)} units would disappear - skipped, review manually")
            continue
        for cid in missing:
            store.delete_article(cid)
        removed_total += len(missing)
        if doc.status == "repealed":
            log.info(f"{law_id or d.get('lex_id')}: document repealed on Lex.uz — {len(arts)} units marked")
        per_doc.append({
            "lex_id": d.get("lex_id"), "law_id": law_id, "units": len(arts),
            "changed_or_new": changed, "removed": len(missing),
            "repealed": doc.status == "repealed",
        })
    builder.client.close()

    indexed = 0
    if to_index:
        async def _run():
            return await store.index_articles_batch(to_index, client=client, batch_size=args.batch_size)
        indexed = asyncio.run(_run())
    await_close = getattr(client, "close", None)
    if callable(await_close):
        try:
            asyncio.run(client.close())
        except Exception:
            pass

    report = {
        "generated": date.today().isoformat(),
        "checked_documents": len(docs),
        "changed_or_new_units": len(to_index),
        "indexed": indexed,
        "removed_units": removed_total,
        "documents": per_doc,
    }
    _save_json(SOURCES / "refresh_report.json", report)
    log.info(f"refresh: {len(docs)} docs, {len(to_index)} changed/new indexed, {removed_total} removed -> {SOURCES / 'refresh_report.json'}")

    try:
        from src.editorial.doc_watch import rebaseline_widened
        from src.editorial.store import EditorialStore
        from src.editorial.watch import check_legal_links
        editorial = EditorialStore(str(Path(args.store_dir) / "editorial.db"))
        # acts widened by `widen` gained units only because the selection changed: re-base their links once
        widened = {d["lex_id"] for d in docs if d.get("widened_at") and not d.get("widened_rebased_at")}
        widened_laws = {p["law_id"] for p in per_doc if p.get("lex_id") in widened and p.get("law_id") and not p.get("error")}
        if widened_laws:
            log.info(f"re-based {rebaseline_widened(store, editorial, widened_laws)} whole-act links of widened acts")
            for d in docs:
                if d["lex_id"] in widened:
                    d["widened_rebased_at"] = date.today().isoformat()
            _save_json(SOURCES / "disability_registry.json", reg)
        res = check_legal_links(store, editorial)
        log.info(f"editorial watch after refresh: {res}")
    except Exception as e:
        log.warning(f"check_legal_links after refresh failed: {e}")


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
    for name, fn in (("discover", cmd_discover), ("select", cmd_select), ("cited", cmd_cited), ("widen", cmd_widen), ("domain", cmd_domain), ("build", cmd_build), ("ingest", cmd_ingest), ("report", cmd_report), ("reindex-fts", cmd_reindex_fts), ("refresh", cmd_refresh)):
        p = sub.add_parser(name)
        p.add_argument("--delay", type=float, default=1.0, help="seconds between Lex.uz requests")
        p.add_argument("--seed-pages", type=int, default=15, help="max result pages scanned per curated seed")
        p.add_argument("--seeds-only", action="store_true", help="discover: re-resolve seeds, keep earlier OKOZ results")
        p.set_defaults(func=fn)
    sub.choices["cited"].add_argument("--apply", action="store_true", help="append the accepted acts to the registry")
    sub.choices["cited"].add_argument("--max-units-all", type=int, default=150,
                                      help="largest act without 'nogironlik' in its title that is kept whole")
    sub.choices["cited"].add_argument("--min-rel-all", type=int, default=6,
                                      help="disability relevance of the text needed to keep such an act whole")
    sub.choices["widen"].add_argument("--apply", action="store_true", help="write include=all into the registry")
    sub.choices["domain"].add_argument("--apply", action="store_true", help="append the accepted acts to the registry")
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
    ref = sub.choices["refresh"]
    ref.add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    ref.add_argument("--batch-size", type=int, default=15)
    ref.add_argument("--allow-mock", action="store_true")
    ref.add_argument("--limit", type=int, default=None, help="refresh at most N registry documents")
    ref.add_argument("--law-ids", default=None, help="comma-separated law_id/lex_id filter")
    ref.add_argument("--allow-mass-removal", action="store_true",
                     help="apply a refresh even when more than half of a document's units disappeared")
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
