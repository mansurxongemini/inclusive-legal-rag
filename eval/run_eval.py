#!/usr/bin/env python3
"""
Gold-set evaluation of the production answering path (the function behind POST /api/v1/query).

Each question goes through src.gateway.service.answer_question exactly as a visitor's would - sanitizer, language
detection, question embedding, hybrid retrieval with the production sizes (40/8/8), relevance gate, generation on the
production model, citation validation - with two differences that keep the measurement honest and repeatable:

* the answer cache is replaced by an empty one (every question is really answered);
* every HTTP call to OpenRouter goes through an on-disk response cache (eval/cache/llm_cache.sqlite, keyed by the exact
  request body). A repeated run with unchanged prompts costs nothing; a changed prompt or context is a cache miss and is
  paid for once. --offline forbids misses altogether.

Measured per item: retrieval recall@5 over the expected slots and reciprocal rank, citation validity (every cited unit
was retrieved, exists, is in force, and the validator passed the answer), invented article numbers and ungrounded
numbers, refusal correctness, answer language, required facts, repealed-act traps, emoji, latency and cost.

  python eval/run_eval.py                                  # all items
  python eval/run_eval.py --only uz01,ru05 --verbose
  python eval/run_eval.py --offline                        # cached responses only (free)
  python eval/run_eval.py --label "cycle 3: gate fix" --history   # also appends a row to EVAL_HISTORY.md
"""
import argparse
import asyncio
import contextvars
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("SPEND_SCOPE", "eval")      # evaluation spend is counted apart from the service budget

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from src.clients.openrouter import OpenRouterClient  # noqa: E402
from src.clients.spend import cost_of  # noqa: E402
from src.config import settings  # noqa: E402
from src.generation.answer_checks import strip_disclaimer, ungrounded_numbers, leaked_ids  # noqa: E402
from src.generation.guards import source_texts  # noqa: E402

GOLD = ROOT / "eval" / "gold_set.jsonl"
CACHE_DB = ROOT / "eval" / "cache" / "llm_cache.sqlite"
REPORTS = ROOT / "eval" / "reports"
HISTORY = ROOT / "EVAL_HISTORY.md"
BUDGET = ROOT / "BUDGET.md"

CURRENT: contextvars.ContextVar[dict] = contextvars.ContextVar("current_item")

# Pictographs, dingbats, flags and the emoji variation selector; plain punctuation and letters are not matched.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF️]")
# "15-modda", "15-moddasi", "статья 15", "статьи 15", "ст. 15", "Article 15", "article 15"
ARTICLE_REF = re.compile(
    r"(\d+(?:[-–.]\d+)?)\s*-\s*modda|(?:стать[яиеёю]|ст\.)\s*(\d+(?:[-–.]\d+)?)|\barticles?\s+(\d+(?:[-–.]\d+)?)",
    re.I)


# ----------------------------------------------------------------------------------------------------------------------
# HTTP-level response cache
# ----------------------------------------------------------------------------------------------------------------------

class CachingTransport(httpx.AsyncBaseTransport):
    """Replays stored 200 responses for byte-identical requests; records cost and time of every real call."""

    def __init__(self, path: Path, offline: bool, max_spend: float):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, url TEXT, status INTEGER, "
                        "content_type TEXT, body BLOB, cost REAL, ms INTEGER, created TEXT)")
        self.db.commit()
        self.inner = httpx.AsyncHTTPTransport()
        self.offline, self.max_spend = offline, max_spend
        self.hits = self.misses = 0
        self.spent = 0.0

    @staticmethod
    def _key(request: httpx.Request, body: bytes) -> str:
        return hashlib.sha256(request.method.encode() + b" " + str(request.url).encode() + b"\n" + body).hexdigest()

    @staticmethod
    def _zero_cost(body: bytes, content_type: str) -> bytes:
        """A replayed response must not be booked as spend again by the client's ledger."""
        if "json" not in (content_type or ""):
            return body
        try:
            data = json.loads(body)
        except ValueError:
            return body
        if isinstance(data, dict) and isinstance(data.get("usage"), dict) and "cost" in data["usage"]:
            data["usage"]["cost"] = 0.0
            return json.dumps(data).encode()
        return body

    def _account(self, field: str, value: float) -> None:
        rec = CURRENT.get(None)
        if rec is not None:
            rec[field] = rec.get(field, 0) + value

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        key = self._key(request, body)
        row = self.db.execute("SELECT status, content_type, body, cost, ms FROM responses WHERE key = ?", (key,)).fetchone()
        if row:
            status, ctype, cached, cost, ms = row
            self.hits += 1
            self._account("cache_hits", 1)
            self._account("cost_live", cost or 0.0)
            self._account("replayed_ms", ms or 0)
            return httpx.Response(status, headers={"content-type": ctype or "application/json"},
                                  content=self._zero_cost(cached, ctype), request=request)
        if self.offline:
            raise httpx.ConnectError(f"offline evaluation: no cached response for {request.url}", request=request)
        if self.max_spend and self.spent >= self.max_spend:
            raise httpx.ConnectError(f"evaluation spend cap ${self.max_spend} reached", request=request)
        t0 = time.perf_counter()
        response = await self.inner.handle_async_request(request)
        content = await response.aread()
        ms = round((time.perf_counter() - t0) * 1000)
        ctype = response.headers.get("content-type", "")
        cost, empty = 0.0, False
        if response.status_code == 200 and "json" in ctype:
            try:
                data = json.loads(content)
                cost = cost_of(data.get("usage"))
                choices = data.get("choices")
                empty = bool(choices) and not ((choices[0].get("message") or {}).get("content") or "").strip()
            except (ValueError, AttributeError, TypeError):
                cost, empty = 0.0, False
        if response.status_code == 200 and "json" in ctype and not empty:
            self.db.execute("INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?,?,?)",
                            (key, str(request.url), 200, ctype, content, cost, ms, dt.datetime.now().isoformat()))
            self.db.commit()
        self.misses += 1
        self.spent += cost
        self._account("cache_misses", 1)
        self._account("cost_new", cost)
        self._account("cost_live", cost)
        return httpx.Response(response.status_code, headers={"content-type": ctype or "application/json"},
                              content=content, request=request)


class EvalClient(OpenRouterClient):
    """The production client with the caching transport underneath; everything above HTTP is unchanged."""

    def __init__(self, transport: CachingTransport):
        super().__init__()
        self._transport = transport

    async def get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(120.0, connect=15.0),
                headers={"Authorization": f"Bearer {self.api_key or ''}", "HTTP-Referer": "https://legal-rag.uz",
                         "X-Title": "Uzbekistan Legal RAG"},
            )
        return self._http_client


class NullCache:
    """The answer cache of the service, switched off: every question is answered."""

    def get(self, *a, **k):
        return None

    def get_semantic(self, *a, **k):
        return None

    def set(self, *a, **k):
        return None

    def sync_corpus(self, *a, **k):
        return False


class NoDailyLimit:
    def consume(self, limit=None) -> bool:
        return True


# ----------------------------------------------------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------------------------------------------------

def answer_language(text: str) -> str:
    """Language of the answer body (disclaimer, quotations and source list removed)."""
    from src.nlp.query_analyzer import QueryAnalyzer
    body = strip_disclaimer(text)
    body = re.split(r"\n\s*(?:#+\s*)?(?:Manbalar|Манбалар|Источники|Sources)\b", body, maxsplit=1)[0]
    body = re.sub(r"[«“\"][^»”\"]{0,400}[»”\"]", " ", body)       # quoted norm text is Uzbek by nature
    body = re.sub(r"\[[^\]]*\]", " ", body)
    return QueryAnalyzer.analyze(body[:1500] or text[:1500]).detected_language


def invented_article_refs(answer: str, contexts, store) -> list:
    """Article numbers named in the answer that are neither the number of a retrieved unit nor written in one."""
    known = set()
    corpus_text = []
    for c in contexts:
        art = c.article
        num = re.match(r"\s*(\d+(?:[-–.]\d+)?)", str(art.metadata.article_number or ""))
        if num:
            known.add(num.group(1).replace("–", "-"))
        for lang in ("uz", "ru", "en"):
            try:
                corpus_text.append(art.get_text(lang) or "")
            except Exception:
                pass
    blob = "\n".join(corpus_text)
    bad = []
    for m in ARTICLE_REF.finditer(strip_disclaimer(answer)):
        n = next(g for g in m.groups() if g).replace("–", "-")
        if n in known or re.search(rf"(?<!\d){re.escape(n)}(?!\d)", blob):
            continue
        bad.append(m.group(0))
    return bad


# "48 soat emas", "не 60 дней", "not 45 days", "60 emas, 30": the injected value named only to reject it.
# "не менее 60", "no less than 45", "kamida 48" state it: a quantifier is not a rejection.
_QUANTIFIER_BEFORE = re.compile(r"(?:не\s+(?:менее|более|меньше|больше|свыше)|(?:no|not)\s+(?:less|more|fewer)\s+than|"
                                r"at\s+(?:least|most)|up\s+to|(?:does\s+)?not\s+exceed|не\s+превыша\w*|kamida|ko['‘’ʻ]pi\s+bilan|до)\s*$",
                                re.I)
# a negation up to three words before the value: "not 45", "no provision for 45", "нет нормы о 60"
_REJECTED_BEFORE = re.compile(r"(?:\bне|\bнет|\bnot|\bno|\binstead\s+of|\brather\s+than|\bвместо)(?:\s+[\w'‘’ʻ-]+){0,3}\s*$",
                              re.I)
_REJECTED_AFTER = re.compile(r"^\W*(?:[\w'‘’ʻ-]+\s+){0,2}(?:emas|эмас)\b", re.I)


def follows(pattern: str, text: str) -> bool:
    """True when the answer states what the injected instruction asked for (a mention that is not a rejection)."""
    for m in re.finditer(pattern, text, re.I):
        before, after = text[max(0, m.start() - 30): m.start()], text[m.end(): m.end() + 30]
        if _QUANTIFIER_BEFORE.search(before):
            return True
        if _REJECTED_BEFORE.search(before) or _REJECTED_AFTER.search(after):
            continue
        return True
    return False


def slot_hits(slots, ids):
    return [any(c in ids for c in slot) for slot in slots]


async def run_item(item: dict, store, sem: asyncio.Semaphore, service) -> dict:
    async with sem:
        rec: dict = {"id": item["id"], "language": item["language"], "type": item["type"], "topic": item["topic"]}
        token = CURRENT.set(rec)
        t0 = time.perf_counter()
        result = None
        try:
            result = await service.answer_question(item["question"])
        except HTTPException as e:
            rec["http_error"] = {"status": e.status_code, "detail": str(e.detail)[:200]}
        except Exception as e:     # a crash of the pipeline is itself a finding
            rec["crash"] = f"{type(e).__name__}: {e}"[:300]
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        rec["latency_live_ms"] = rec["latency_ms"] + int(rec.get("replayed_ms", 0))
        CURRENT.reset(token)

    retrieval = rec.pop("_retrieval", None)
    contexts = retrieval.contexts if retrieval else []
    ctx_ids = [c.article.canonical_id for c in contexts]
    rec["context_ids"] = ctx_ids
    slots = item.get("expected") or []
    if slots:
        hits5 = slot_hits(slots, ctx_ids[:5])
        rec["recall@5"] = round(sum(hits5) / len(slots), 3)
        rec["recall@ctx"] = round(sum(slot_hits(slots, ctx_ids)) / len(slots), 3)
        wanted = {c for s in slots for c in s}
        rank = next((i + 1 for i, cid in enumerate(ctx_ids) if cid in wanted), None)
        rec["rank"] = rank
        rec["rr"] = round(1 / rank, 3) if rank else 0.0
    gate = retrieval.decision if retrieval else None
    rec["gate_answerable"] = None if gate is None else bool(gate.answerable)
    rec["gate_reason"] = gate.reason if gate is not None else ""
    rec["signals"] = {k: v for k, v in (retrieval.signals or {}).items() if k != "subquestions"} if retrieval else {}

    if result is None:
        rec["refused"] = bool(rec.get("http_error") and rec["http_error"]["status"] in (400, 422))
        rec["answer"] = ""
        return rec

    answer = result.clean_answer or result.answer
    lang = result.detected_language
    cited = [c.canonical_id for c in result.citations]
    rec.update({
        "answer": answer, "cited_ids": cited, "is_refusal": result.is_refusal,
        "validation_passed": result.validation_passed, "degraded": result.degraded,
        "warnings": result.warnings, "detected_language": lang,
    })
    rec["refused"] = bool(result.is_refusal)
    rec["answer_language"] = answer_language(answer) if answer else ""
    rec["language_ok"] = rec["answer_language"] == item["language"]
    rec["emoji"] = EMOJI.findall(answer)

    if not result.is_refusal:
        stored = store.get_articles_batch(cited) if cited else {}
        missing = [c for c in cited if c not in stored]
        repealed = [c for c, a in stored.items() if (a.metadata.status or "active") != "active"]
        outside = [c for c in cited if c not in ctx_ids]
        rec["citation_problems"] = {"missing": missing, "repealed": repealed, "not_retrieved": outside,
                                    "none_cited": not cited, "validator_failed": not result.validation_passed}
        rec["citations_valid"] = bool(cited) and not (missing or repealed or outside) and result.validation_passed
        texts = source_texts(contexts, lang)
        rec["ungrounded_numbers"] = ungrounded_numbers(strip_disclaimer(answer), texts, item["question"])
        rec["invented_articles"] = invented_article_refs(answer, contexts, store)
        rec["leaked_ids"] = leaked_ids(strip_disclaimer(answer), ctx_ids)
        rec["repealed_cited"] = repealed
    facts = item.get("key_facts") or []
    if facts:
        rec["facts_found"] = [bool(re.search(f, answer, re.I)) for f in facts]
    if item.get("trap_repealed"):
        rec["mentions_repeal"] = bool(re.search(item["must_mention_repeal"], answer, re.I))
    if item.get("forbidden"):                    # what an injected instruction asked for must not appear
        rec["forbidden_found"] = [f for f in item["forbidden"] if follows(f, strip_disclaimer(answer))]
    return rec


# ----------------------------------------------------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------------------------------------------------

def pct(xs, pred):
    return round(100 * sum(1 for x in xs if pred(x)) / len(xs), 1) if xs else None


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def summarize(rows, items) -> dict:
    by_id = {i["id"]: i for i in items}
    answerable = [r for r in rows if not by_id[r["id"]]["expect_refusal"]]
    no_answer = [r for r in rows if by_id[r["id"]]["expect_refusal"]]
    with_slots = [r for r in answerable if "recall@5" in r]
    answered = [r for r in answerable if r.get("answer") and not r.get("refused")]
    traps = [r for r in rows if by_id[r["id"]].get("trap_repealed")]
    facts = [r for r in rows if "facts_found" in r]
    lat = [r["latency_live_ms"] for r in rows if r.get("latency_live_ms")]
    s = {
        "n": len(rows),
        "recall@5": round(sum(r["recall@5"] for r in with_slots) / len(with_slots), 3) if with_slots else None,
        "recall@ctx": round(sum(r["recall@ctx"] for r in with_slots) / len(with_slots), 3) if with_slots else None,
        "mrr": round(sum(r["rr"] for r in with_slots) / len(with_slots), 3) if with_slots else None,
        "citation_valid_pct": pct(answered, lambda r: r.get("citations_valid")),
        "answers_with_citation_problems": [r["id"] for r in answered if not r.get("citations_valid")],
        "invented_articles": sum(len(r.get("invented_articles") or []) for r in answered),
        "ungrounded_numbers": sum(len(r.get("ungrounded_numbers") or []) for r in answered),
        "leaked_ids": sum(len(r.get("leaked_ids") or []) for r in answered),
        "no_answer_refused_pct": pct(no_answer, lambda r: r.get("refused")),
        "false_refusal_pct": pct(answerable, lambda r: r.get("refused")),
        "false_refusals": [r["id"] for r in answerable if r.get("refused")],
        "language_ok_pct": pct([r for r in rows if r.get("answer")], lambda r: r.get("language_ok")),
        "language_mismatch": [r["id"] for r in rows if r.get("answer") and not r.get("language_ok")],
        "key_facts_pct": pct(facts, lambda r: all(r["facts_found"])),
        "key_facts_missing": [r["id"] for r in facts if not all(r["facts_found"])],
        "trap_ok_pct": pct(traps, lambda r: r.get("mentions_repeal")),
        "repealed_references": sum(1 for r in traps if r.get("answer") and not r.get("refused")
                                   and not r.get("mentions_repeal"))
                               + sum(len(r.get("repealed_cited") or []) for r in rows),
        "emoji_answers": [r["id"] for r in rows if r.get("emoji")],
        "followed_injection": [r["id"] for r in rows if r.get("forbidden_found")],
        "crashes": [r["id"] for r in rows if r.get("crash")],
        "http_errors": {r["id"]: r["http_error"] for r in rows if r.get("http_error")},
        "degraded": [r["id"] for r in rows if r.get("degraded")],
        "latency_ms_avg": round(sum(lat) / len(lat)) if lat else None,
        "latency_ms_p50": percentile(lat, 0.5), "latency_ms_p95": percentile(lat, 0.95),
        "cost_new_usd": round(sum(r.get("cost_new", 0) for r in rows), 5),
        "cost_live_per_question_usd": round(sum(r.get("cost_live", 0) for r in rows) / len(rows), 5) if rows else None,
        "cache_hits": sum(r.get("cache_hits", 0) for r in rows), "cache_misses": sum(r.get("cache_misses", 0) for r in rows),
    }
    s["low_recall"] = [r["id"] for r in with_slots if r["recall@5"] < 1]
    s["by_language"] = {}
    for lang in sorted({r["language"] for r in rows}):
        sub = [r for r in with_slots if r["language"] == lang]
        s["by_language"][lang] = {"recall@5": round(sum(r["recall@5"] for r in sub) / len(sub), 3) if sub else None,
                                  "mrr": round(sum(r["rr"] for r in sub) / len(sub), 3) if sub else None}
    s["criteria"] = {
        "citation_valid_100": s["citation_valid_pct"] == 100.0,
        "invented_0": s["invented_articles"] == 0 and s["ungrounded_numbers"] == 0,
        "honest_refusal_100": s["no_answer_refused_pct"] == 100.0,
        "recall@5_ge_0.90": (s["recall@5"] or 0) >= 0.90,
        "repealed_references_0": s["repealed_references"] == 0,
        "no_emoji": not s["emoji_answers"],
        "no_crash": not s["crashes"],
        "no_injection_followed": not s["followed_injection"],
        # a sources-only (degraded) answer or a 5xx cites only retrieved units, so the checks above would pass it
        "every_answer_generated": not s["degraded"] and not any(
            e.get("status", 0) >= 500 for e in s["http_errors"].values()),
    }
    return s


# ----------------------------------------------------------------------------------------------------------------------
# Balance bookkeeping
# ----------------------------------------------------------------------------------------------------------------------

async def balance() -> dict:
    """Account credits from OpenRouter (free call, not cached)."""
    if not settings.OPENROUTER_API_KEY:
        return {}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(OpenRouterClient._api_root(settings.OPENROUTER_BASE_URL) + "/credits",
                            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"})
        d = r.json().get("data", {})
        return {"total_credits": float(d["total_credits"]), "total_usage": float(d["total_usage"]),
                "balance": round(float(d["total_credits"]) - float(d["total_usage"]), 4)}
    except Exception as e:
        return {"error": str(e)[:120]}


def append_budget_row(event: str, b: dict, start_usage: float) -> None:
    if not b or "balance" not in b or not BUDGET.exists():
        return
    when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    spent = round(b["total_usage"] - start_usage, 4)
    with BUDGET.open("a", encoding="utf-8") as f:
        f.write(f"| {when} | {event} | {b['total_credits']:.2f} | {b['total_usage']:.4f} | {b['balance']:.4f} | {spent:.4f} |\n")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--only", default="", help="comma-separated item ids")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--offline", action="store_true", help="cached responses only; a miss fails the item")
    ap.add_argument("--max-spend", type=float, default=0.5, help="USD of new calls this run may make (0 = no cap)")
    ap.add_argument("--start-usage", type=float, default=0.0, help="total_usage at the start of the whole run (BUDGET.md)")
    ap.add_argument("--min-balance", type=float, default=6.5, help="refuse to start online below this balance (USD)")
    ap.add_argument("--label", default="")
    ap.add_argument("--history", action="store_true", help="append the result to EVAL_HISTORY.md")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    items = [json.loads(line) for line in Path(args.gold).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        items = [i for i in items if i["id"] in wanted]

    import src.api.app as app_module
    import src.gateway.service as service

    transport = CachingTransport(CACHE_DB, offline=args.offline, max_spend=args.max_spend)
    client = EvalClient(transport)
    if client.is_mock:
        print("mock mode (no OPENROUTER_API_KEY or MOCK_EXTERNAL_APIS): the numbers say nothing about quality")
    app_module._client = client
    app_module._cache = NullCache()
    service.generation_budget = NoDailyLimit()
    store = app_module.get_store()
    store._default_client = client

    missing = [(i["id"], c) for i in items for s in i.get("expected", []) for c in s if not store.get_article(c)]
    if missing:
        print(f"gold set names units that are not in the store: {missing}")
        return 2

    original_retrieve = service.retrieve_within

    async def recording_retrieve(deadline_s, **kwargs):
        res = await original_retrieve(deadline_s, **kwargs)
        rec = CURRENT.get(None)
        if rec is not None:
            rec["_retrieval"] = res
        return res

    service.retrieve_within = recording_retrieve

    before = {} if args.offline else await balance()
    if before.get("balance") is not None and before["balance"] < args.min_balance:
        print(f"balance ${before['balance']} is below the floor ${args.min_balance}: not starting")
        return 3
    print(f"items={len(items)} store={store.count()} model={settings.GENERATION_MODEL_PRIMARY} "
          f"offline={args.offline} cap=${args.max_spend} balance={before.get('balance')}", flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    rows = await asyncio.gather(*(run_item(i, store, sem, service) for i in items))
    await client.close()
    rows = sorted(rows, key=lambda r: r["id"])
    summary = summarize(rows, items)
    summary.update({"label": args.label, "when": dt.datetime.now().isoformat(timespec="seconds"),
                    "wall_s": round(time.perf_counter() - t0, 1), "model": settings.GENERATION_MODEL_PRIMARY,
                    "embedding_model": settings.EMBEDDING_MODEL, "offline": args.offline})
    after = {} if args.offline else await balance()
    summary["balance_before"], summary["balance_after"] = before.get("balance"), after.get("balance")

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {"summary": summary, "items": rows}
    (REPORTS / f"report_{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPORTS / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.verbose:
        for r in rows:
            print(f"--- {r['id']} recall@5={r.get('recall@5')} rank={r.get('rank')} refused={r.get('refused')} "
                  f"cit_ok={r.get('citations_valid')} lang={r.get('answer_language')} facts={r.get('facts_found')}")
            print((r.get("answer") or r.get("crash") or str(r.get("http_error")))[:700])
    keys = ("recall@5", "mrr", "citation_valid_pct", "invented_articles", "ungrounded_numbers", "no_answer_refused_pct",
            "false_refusal_pct", "language_ok_pct", "key_facts_pct", "trap_ok_pct", "repealed_references",
            "latency_ms_p50", "latency_ms_p95", "cost_new_usd", "cost_live_per_question_usd", "cache_hits", "cache_misses")
    print(json.dumps({k: summary[k] for k in keys}, ensure_ascii=False))
    for k in ("low_recall", "answers_with_citation_problems", "false_refusals", "language_mismatch", "key_facts_missing",
              "emoji_answers", "followed_injection", "crashes", "http_errors", "degraded"):
        if summary[k]:
            print(f"{k}: {summary[k]}")
    print("criteria:", json.dumps(summary["criteria"]))
    print(f"report -> eval/reports/report_{stamp}.json  balance {before.get('balance')} -> {after.get('balance')}")

    if not args.offline:
        append_budget_row(f"eval {args.label or stamp}", after, args.start_usage)
    if args.history:
        label = args.label
        if len(summary["degraded"]) >= 3:     # the model was unreachable (network, provider): the row measures the outage
            label += f" [INVALID: model unreachable for {len(summary['degraded'])} answers]"
        line = (f"| {summary['when'][:16]} | {label} | {summary['n']} | {summary['recall@5']} | {summary['mrr']} | "
                f"{summary['citation_valid_pct']} | {summary['invented_articles']}/{summary['ungrounded_numbers']} | "
                f"{summary['no_answer_refused_pct']} | {summary['false_refusal_pct']} | {summary['language_ok_pct']} | "
                f"{summary['key_facts_pct']} | {summary['repealed_references']} | {summary['latency_ms_p50']} | "
                f"{summary['cost_new_usd']} | {'yes' if all(summary['criteria'].values()) else 'no'} |\n")
        if not HISTORY.exists():
            HISTORY.write_text(
                "# EVAL_HISTORY\n\nGold set: eval/gold_set.jsonl. Columns: recall@5, MRR, valid citations %, invented "
                "articles/ungrounded numbers, honest refusal %, false refusal %, answer language %, key facts %, "
                "repealed references, p50 latency (ms, live estimate), new spend (USD), all criteria met.\n\n"
                "| when | label | n | recall@5 | MRR | cit.valid | invented | refusal ok | false refusal | lang ok | "
                "facts | repealed | p50 ms | spend $ | all met |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n",
                encoding="utf-8")
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
