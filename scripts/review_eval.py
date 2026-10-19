#!/usr/bin/env python3
"""Volontyor-javob review sifatini HAQIQIY LLM bilan o'lchaydi.

`tests/fixtures/review_golden.json` dagi har bir keys uchun review pipeline
(retrieval + LLM + server verdict) ishga tushiriladi va kutilgan verdict bilan
solishtiriladi. Natija: false-approve va false-reject ulushlari.

DIQQAT: testlarda ISHLATILMAYDI (pytest bu skriptni chaqirmaydi). Haqiqiy
OpenRouter kaliti kerak; mock rejimda ishlashdan bosh tortadi.

    OPENROUTER_API_KEY=... .venv/bin/python scripts/review_eval.py [--limit N]
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.app import get_client, get_store  # noqa: E402
from src.config import settings  # noqa: E402
from src.gateway.review import (  # noqa: E402
    build_review_messages,
    call_review_llm,
    decide_verdict,
    format_norms_for_review,
    parse_review_output,
    resolve_review_model,
    retrieve_review_contexts,
)


async def eval_case(case: dict, client, store, model: str, timeout_s: float) -> dict:
    question = case["question"]
    answer = case["answer"]
    contexts = await retrieve_review_contexts(
        question, answer, client, store, settings.REVIEW_TOP_K,
    )
    messages = build_review_messages(question, answer, format_norms_for_review(contexts))
    parsed = None
    for _ in range(2):  # endpoint kabi: parse xatosida 1 marta qayta urinish
        raw = await call_review_llm(messages, client, model, timeout_s)
        try:
            cand = parse_review_output(raw)
            parsed = cand
            if cand.confidence is None and _ == 0:
                messages = messages + [{"role": "user", "content": "'confidence' (0.0-1.0) kaliti yetishmayapti. Faqat to'liq JSON obyektni confidence bilan qayta yozing."}]
                continue
            break
        except Exception:
            messages = messages + [{"role": "user", "content": "Faqat JSON obyekt qaytaring. Hech qanday qo'shimcha matn yozmang."}]
    if parsed is None:
        raise ValueError("review_parse_error")
    if parsed.confidence is None:
        parsed.confidence = 0.0
    verdict = decide_verdict(parsed.scores, parsed.issues, parsed.confidence)
    if not contexts:
        verdict = "needs_admin"
    return {
        "id": case["id"],
        "expected": case["expected_verdict"],
        "verdict": verdict,
        "scores": parsed.scores.model_dump(),
        "issues": [f"{i.type}/{i.severity}" for i in parsed.issues],
        "confidence": parsed.confidence,
        "retrieved": [c.article.canonical_id for c in contexts],
    }


async def main(limit: int, out: str = "") -> int:
    client = get_client()
    if getattr(client, "is_mock", False):
        print("REFUSAL: mock rejimda (OPENROUTER_API_KEY yo'q). Haqiqiy kalit bilan qayta urining.")
        return 2
    store = get_store()
    model = resolve_review_model(client)

    from src.gateway.review import fetch_llm_status
    status = await fetch_llm_status()
    if status.get("error") == "insufficient_credits":
        print(f"REFUSAL: OpenRouter balansi tugagan (qoldiq: {status.get('credits_remaining')}). Avval to'ldiring.")
        return 2

    cases = json.loads(Path("tests/fixtures/review_golden.json").read_text(encoding="utf-8"))
    if limit:
        cases = cases[:limit]

    results = []
    for case in cases:
        try:
            res = await eval_case(case, client, store, model, settings.REVIEW_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 — eval davom etishi kerak
            res = {"id": case["id"], "expected": case["expected_verdict"], "verdict": f"ERROR: {e}"}
        results.append(res)
        extra = f" scores={res.get('scores')} conf={res.get('confidence')} issues={res.get('issues')}" if "scores" in res else ""
        print(f"{res['id']}: expected={res['expected']} got={res['verdict']}{extra}")

    good = [r for r in results if r["expected"] == "approve"]
    bad = [r for r in results if r["expected"] != "approve"]
    false_reject = sum(1 for r in good if r["verdict"] != "approve") / len(good) if good else 0.0
    false_approve = sum(1 for r in bad if r["verdict"] == "approve") / len(bad) if bad else 0.0
    needs_admin_rate = sum(1 for r in results if r["verdict"] == "needs_admin") / len(results) if results else 0.0
    errors = sum(1 for r in results if str(r["verdict"]).startswith("ERROR"))
    print(f"\nN={len(results)}  false_reject={false_reject:.2%}  false_approve={false_approve:.2%}  "
          f"needs_admin={needs_admin_rate:.2%}  errors={errors}")
    by_kind: dict[str, list[int]] = {}
    kinds = {c["id"]: c.get("answer_kind", "?") for c in cases}
    for r in results:
        ok = (r["verdict"] == r["expected"]) or (r["expected"] != "approve" and r["verdict"] in ("reject", "needs_admin"))
        by_kind.setdefault(kinds.get(r["id"], "?"), [0, 0])
        by_kind[kinds.get(r["id"], "?")][0] += int(ok)
        by_kind[kinds.get(r["id"], "?")][1] += 1
    print("Tur bo'yicha to'g'ri natija: " + ", ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(by_kind.items())))
    if out:
        Path(out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Natijalar: {out}")
    # chegaralar: xato tasdiq 0% bo'lishi shart, noto'g'ri rad 20% dan oshmasin
    return 1 if (false_approve > 0 or false_reject > 0.2 or errors) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="", help="natijalarni JSON faylga yozish")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.limit, args.out)))
