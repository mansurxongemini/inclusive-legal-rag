#!/usr/bin/env python3
"""
Faithfulness evaluation: har bir yakuniy javobdagi da'vo (claim) o'zi iqtibos
qilgan manba bandi matni bilan tasdiqlanishini O'LCHASH.

Ishlab chiqarish yo'li (gateway/service.py dagi kabi):
  sanitize_user_input -> QueryAnalyzer.analyze -> retrieve_contexts
  (top_k=40, max_extra=8, rerank_top_n=8) -> AnswerGenerator.generate_answer.

Bitta javob uchun BITTA judge chaqiruvi (JSON massiv). Masalan:

  python scripts/faithfulness_eval.py --judge-model meta-llama/llama-3.3-70b-instruct \\
      --model google/gemini-2.5-flash --support-check on --tag bazaviy --limit 20

DIQQAT: skript real API ga murojaat qiladi (pul sarflanadi). Faqat --help ni
tarmoqqa chiqmasdan tekshirish mumkin.
"""
import argparse
import asyncio
import collections
import json
import re
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SPEND_SCOPE", "eval")      # evaluation spend is counted apart and never limited by the service budget

from fastapi import HTTPException  # noqa: E402

from src.api.middleware.security import sanitize_user_input  # noqa: E402
from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.config import settings  # noqa: E402
from src.generation.generator import AnswerGenerator  # noqa: E402
from src.nlp.query_analyzer import QueryAnalyzer  # noqa: E402
from src.retrieval.passages import focused_text  # noqa: E402
from src.retrieval.pipeline import retrieve_contexts  # noqa: E402
from src.storage.hybrid_store import HybridStore  # noqa: E402

JUDGE_PROMPT = """You check whether each claim in a legal assistant's answer is supported by the provision text it cites.
Uzbekistan disability-rights domain. For every claim you get the exact text of the provision(s) it cites.

Return ONLY a JSON array, one object per claim in order:
[{"i": 0, "verdict": "supported|partial|unsupported", "reason": "short reason"}]
- supported: the claim fully and precisely matches the cited provision text.
- partial: the main direction is right, only an unimportant minor detail is missing (legal substance intact).
- unsupported (apply STRICTLY in any of these cases):
  - the provision belongs to another group (e.g. it covers only children, but the claim presents it as a benefit
    for adults; a norm for military personnel applied to civilians);
  - the provision only lists a category or a list (e.g. a disease list) but does NOT state the benefit, payment
    or assistance type from the claim;
  - the claim adds a fact, state body, deadline or requirement absent from the provision text;
  - the cited provision was not found among the sources or is irrelevant to the claim.
No extra explanation or text."""

_CLAIM_ARRAY_RE = re.compile(r"\[\s*\{.*\}\s*\]", re.DOTALL)
_NUM_CITE_RE = re.compile(r"\[(\d+)\]")
_DROPPED_RE = re.compile(r"dropped\s+(\d+)\s*/")


@dataclass
class EvalClaim:
    index: int
    text: str
    markers: list = field(default_factory=list)  # [n] raqamlari
    canonical_ids: list = field(default_factory=list)
    kind: str = "sentence"  # lead | bullet | step | sentence


def split_eval_claims(final_answer: str) -> list:
    """Yakuniy (tozalangan, [n] belgili) javobni da'volarga ajratadi. Iqtibossiz qatorlar o'tkazib yuboriladi."""
    claims: list = []
    if not final_answer or not final_answer.strip():
        return claims
    first_seen = False
    for line_no, line in enumerate(final_answer.split("\n")):
        stripped = line.strip()
        if not stripped:
            continue
        markers = [int(m) for m in _NUM_CITE_RE.findall(line)]
        is_bullet = bool(re.match(r"^\s*[-*•]\s+", line))
        is_step = bool(re.match(r"^\s*\d+\.\s+", line))
        if is_bullet or is_step:
            first_seen = True
            if markers:
                claims.append(EvalClaim(len(claims), stripped, markers, [], "bullet" if is_bullet else "step"))
            continue
        if stripped.startswith("#") or (
            stripped.startswith("**") and stripped.endswith("**")
        ) or (stripped.endswith(":") and len(stripped) < 80):
            if not markers:
                continue
        if not markers:
            first_seen = True
            continue
        is_lead = not first_seen
        first_seen = True
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", stripped) if s.strip()]
        added = False
        for sent in sentences:
            sent_markers = [int(m) for m in _NUM_CITE_RE.findall(sent)]
            if sent_markers:
                claims.append(EvalClaim(len(claims), sent, sent_markers, [], "lead" if is_lead else "sentence"))
                added = True
        if not added:
            claims.append(EvalClaim(len(claims), stripped, markers, [], "lead" if is_lead else "sentence"))
    return claims


def _judge_json(text: str):
    m = _CLAIM_ARRAY_RE.search(text or "")
    if not m:
        return None
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return items if isinstance(items, list) else None


async def judge_claims(question, claims, contexts, citations, client, judge_model) -> list | None:
    """BITTA judge chaqiruvi: butun javob uchun JSON massiv. Xato bo'lsa None."""
    by_index = {c.index: c for c in citations}
    ctx_map = {}
    focus_map = {}
    for c in contexts:
        art = getattr(c, "article", None)
        if art is not None and getattr(art, "canonical_id", None):
            ctx_map[art.canonical_id] = art
            focus_map[art.canonical_id] = getattr(c, "focus", None)
    blocks = []
    for cl in claims:
        parts = []
        for n in cl.markers:
            cit = by_index.get(n)
            if cit is None:
                parts.append(f"  - [{n}] (Diqqat: bu belgi javob iqtiboslari orasida YO'Q)")
                continue
            cid = cit.canonical_id
            cl.canonical_ids.append(cid)
            art = ctx_map.get(cid)
            body = ""
            if art is not None and hasattr(art, "get_text"):
                body = focused_text(art, "uz", focus_map.get(cid), 6000)       # the part the answer was given
            if art is None or not body:
                parts.append(f"  - [{n}] canonical_id={cid} (Diqqat: manbalar orasida TOPILMADI)")
            else:
                parts.append(f"  - [{n}] canonical_id={cid}\n    Matn: {body}")
        blocks.append(f"DA'VO #{cl.index} (turi: {cl.kind}):\nDa'vo matni: \"{cl.text}\"\n"
                      f"U iqtibos qilgan bandlar:\n" + "\n".join(parts))
    user = f"SAVOL: {question}\n\nDA'VOLAR:\n" + "\n\n".join(blocks)
    try:       # the judge is another model of the generation provider (the generator must not grade itself)
        raw = await client.chat_completion(
            [{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": user}],
            model=judge_model, temperature=0.0, max_tokens=8000, min_chars=2, reasoning={"effort": "low"},
        )
    except Exception:
        return None
    items = _judge_json(raw)
    if items is None:
        return None
    verdicts = []
    for it in items:
        try:
            v = str(it.get("verdict", "")).strip().lower()
            if v in ("supported", "partial", "unsupported"):
                verdicts.append({"i": int(it["i"]), "verdict": v, "reason": str(it.get("reason", ""))[:300]})
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    if len(verdicts) != len(claims):
        return None
    return verdicts


async def run_item(item, store, client, gen, args, sem, judge_model) -> dict:
    async with sem:
        t0 = time.perf_counter()
        row = {"id": item["id"], "question": item["question"], "out_of_scope": bool(item.get("out_of_scope"))}
        try:
            query = sanitize_user_input(item["question"])
        except HTTPException as e:
            row.update({"outcome": "refused", "refuse_reason": f"sanitizer: {e.detail}",
                        "answer": "", "claims": [], "latency_ms": 0})
            print(f"{item['id']} refused (sanitizer)", flush=True)
            return row
        analysis = QueryAnalyzer.analyze(query)
        lang = analysis.detected_language
        res = await retrieve_contexts(
            analysis=analysis, store=store, client=client,
            top_k=40, max_extra=8, rerank_top_n=8,  # gateway/service.py dagi kabi
        )
        if res.decision is not None and not res.decision.answerable:
            row.update({"outcome": "refused",
                        "refuse_reason": res.decision.reason if res.decision else "",
                        "answer": "", "claims": [], "latency_ms": round((time.perf_counter() - t0) * 1000)})
            print(f"{item['id']} refused (gate)", flush=True)
            return row
        try:
            out = await gen.generate_answer(query=query, contexts=res.contexts, language=lang, mode="plain")
        except Exception as e:
            row.update({"outcome": "error", "refuse_reason": f"generation_error: {e}",
                        "answer": "", "claims": [], "latency_ms": round((time.perf_counter() - t0) * 1000)})
            print(f"{item['id']} generation error: {e}", flush=True)
            return row
        latency_ms = round((time.perf_counter() - t0) * 1000)
        if out.is_refusal:
            row.update({"outcome": "refused", "refuse_reason": "refusal answer",
                        "answer": out.clean_answer or out.answer, "claims": [],
                        "warnings": out.warnings, "latency_ms": latency_ms})
            print(f"{item['id']} refused (answer)", flush=True)
            return row
        final = (out.clean_answer or out.answer or "")
        final = re.split(r"\n\s*---", final, maxsplit=1)[0].strip()
        claims = split_eval_claims(final)
        row.update({"outcome": "answered", "answer": final, "warnings": out.warnings,
                    "latency_ms": latency_ms})
        if not claims:
            row["claims"] = []
            print(f"{item['id']} answered, no cited claims", flush=True)
            return row
        verdicts = await judge_claims(item["question"], claims, res.contexts,
                                      out.citations, client, judge_model)
        if verdicts is None:
            row.update({"outcome": "judge_error", "claims": [
                {"i": c.index, "text": c.text, "kind": c.kind,
                 "markers": c.markers, "canonical_ids": c.canonical_ids} for c in claims]})
            print(f"{item['id']} judge_error", flush=True)
            return row
        vmap = {v["i"]: v for v in verdicts}
        row["claims"] = [{"i": c.index, "text": c.text, "kind": c.kind, "markers": c.markers,
                          "canonical_ids": c.canonical_ids,
                          "verdict": vmap.get(c.index, {}).get("verdict"),
                          "reason": vmap.get(c.index, {}).get("reason", "")} for c in claims]
        n_uns = sum(1 for c in row["claims"] if c["verdict"] == "unsupported")
        print(f"{item['id']} claims={len(claims)} unsupported={n_uns}", flush=True)
        return row


def summarize(rows) -> dict:
    answered = [r for r in rows if r["outcome"] == "answered"]
    refused = sum(1 for r in rows if r["outcome"] == "refused")
    judge_errors = sum(1 for r in rows if r["outcome"] == "judge_error")
    gen_errors = sum(1 for r in rows if r["outcome"] == "error")
    all_claims = [c for r in answered for c in r.get("claims", [])]
    n = len(all_claims)
    cnt = collections.Counter(c.get("verdict") for c in all_claims)
    pct = lambda k: round(100 * cnt.get(k, 0) / n, 1) if n else 0.0  # noqa: E731
    with_uns = sum(1 for r in answered if any(c.get("verdict") == "unsupported" for c in r.get("claims", [])))
    lat = sorted(r["latency_ms"] for r in rows if r.get("latency_ms"))
    dropped = 0
    for r in rows:
        for w in r.get("warnings", []) or []:
            if "support_check" in w:
                m = _DROPPED_RE.search(w)
                if m:
                    dropped += int(m.group(1))
    return {
        "answers": len(answered),
        "refused": refused,
        "judge_errors": judge_errors,
        "generation_errors": gen_errors,
        "claims": n,
        "supported_pct": pct("supported"),
        "partial_pct": pct("partial"),
        "unsupported_pct": pct("unsupported"),
        "answers_with_unsupported_pct": round(100 * with_uns / len(answered), 1) if answered else 0.0,
        "avg_latency_ms": round(sum(lat) / len(lat)) if lat else 0,
        "p90_latency_ms": lat[min(len(lat) - 1, int(-(-90 * len(lat) // 100)) - 1)] if lat else 0,
        "support_check_dropped_total": dropped,
    }


def load_items(dataset, extra_paths) -> list:
    items = json.loads(Path(dataset).read_text(encoding="utf-8"))
    for xp in extra_paths or []:
        more = json.loads(Path(xp).read_text(encoding="utf-8"))
        if isinstance(more, dict):
            more = more.get("items", [])
        items = list(items) + list(more)
    seen, uniq = set(), []
    for it in items:
        if it.get("id") not in seen:
            seen.add(it.get("id"))
            uniq.append(it)
    return [it for it in uniq if not it.get("out_of_scope")]


async def main() -> int:
    ap = argparse.ArgumentParser(description="Faithfulness eval: da'volarning manba bilan tasdiqlanishini o'lchash.")
    ap.add_argument("--dataset", default=str(ROOT / "data" / "golden_dataset" / "practical_eval_set_v2.json"))
    ap.add_argument("--extra", action="append", default=[],
                    help="qo'shimcha JSON ro'yxat; takrorlanishi mumkin")
    ap.add_argument("--store-dir", default=str(ROOT / "data" / "store"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--model", default=None, help="generatsiya modeli (client.primary_model shu ishga almashtiriladi)")
    ap.add_argument("--support-check", choices=["on", "off"], default="off")
    ap.add_argument("--no-support-check", action="store_true", default=False,
                    help="support-check ni o'chirib baholash (--support-check off bilan teng)")
    ap.add_argument("--judge-model", required=True, help="MAJBURIY, generatsiya modelidan farqli bo'lishi shart")
    ap.add_argument("--tag", required=True, help="hisobot nomi: data/golden_dataset/faithfulness_<tag>.json")
    ap.add_argument("--seed-sample", type=int, default=0,
                    help="berilsa, out_of_scope bo'lmagan itemlardan har k-chisini olib N tasini tanlaydi")
    args = ap.parse_args()

    items = load_items(args.dataset, args.extra)
    if args.seed_sample and args.seed_sample < len(items):
        k = max(1, len(items) // args.seed_sample)
        items = items[::k][: args.seed_sample]
    if args.limit:
        items = items[: args.limit]

    store, client = HybridStore(args.store_dir), OpenRouterClient()
    gen_model = args.model or client.primary_model
    if args.judge_model == gen_model:
        print("xato: --judge-model generatsiya modelidan farqli bo'lishi shart", file=sys.stderr)
        return 2
    if args.model:
        client.primary_model = args.model  # faqat shu ishga; settings o'zgarmaydi
    if args.no_support_check:
        args.support_check = "off"
    settings.SUPPORT_CHECK_ENABLED = (args.support_check == "on")  # jarayon ichida
    print(f"items={len(items)} store={store.count()} mock={client.is_mock} "
          f"gen_model={gen_model} support_check={args.support_check} judge={args.judge_model}", flush=True)
    sem = asyncio.Semaphore(args.concurrency)
    gen = AnswerGenerator(client=client)
    rows = await asyncio.gather(*(run_item(i, store, client, gen, args, sem, args.judge_model) for i in items))
    await client.close()
    rows = sorted(rows, key=lambda r: r["id"])
    summary = summarize(rows)
    summary.update({"gen_model": gen_model, "judge_model": args.judge_model,
                    "support_check": args.support_check, "tag": args.tag})
    report = str(ROOT / "data" / "golden_dataset" / f"faithfulness_{args.tag}.json")
    Path(report).write_text(json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), f"\nreport -> {report}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
