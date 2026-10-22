import json
import urllib.request
import time

API_KEY = "REDACTED"
BASE_URL = "http://127.0.0.1:8000"

def call_ask(question: str):
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/assistant/ask",
        data=json.dumps({"question": question, "format": "markdown"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        data["elapsed_s"] = round(time.time() - t0, 2)
        return data

def call_review(question: str, answer: str):
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/assistant/review",
        data=json.dumps({"question": question, "answer": answer}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        data["elapsed_s"] = round(time.time() - t0, 2)
        return data

def main():
    with open("data/golden_dataset/gemini_argon_block1_ground_truth.json", "r", encoding="utf-8") as f:
        argon_data = json.load(f)

    with open("data/sources/harvested_benchmark/batch_01.json", "r", encoding="utf-8") as f:
        tuzuk_batch1 = json.load(f)

    # Test Question 1
    q1_argon = argon_data[0]
    q1_tuzuk = tuzuk_batch1[0]
    question_text = q1_tuzuk["question"]

    print("=" * 80)
    print("SAVOL 1:", question_text)
    print("=" * 80)

    # 1. Legal RAG Answer
    print("\n[1] LEGAL RAG (Meta Muse Spark) dan javob olinmoqda...")
    rag_resp = call_ask(question_text)
    print(f"RAG javobi ({rag_resp['elapsed_s']}s):")
    print(rag_resp["answer"][:600], "...\n")
    print("Manbalar soni:", len(rag_resp.get("citations", [])))

    # 2. Review Tuzuk AI Answer
    print("\n[2] TUZUK AI javobi QA AUDIT (/api/v1/assistant/review) orqali tekshirilmoqda...")
    tuzuk_review = call_review(question_text, q1_tuzuk["answer"])
    print(f"Tuzuk AI Audit Natijasi ({tuzuk_review['elapsed_s']}s):")
    print("  Hukm (Verdict):", tuzuk_review.get("verdict"))
    print("  Ishonch (Confidence):", tuzuk_review.get("confidence"))
    print("  Ballar:", tuzuk_review.get("scores"))
    print("  Kamchiliklar:", tuzuk_review.get("issues"))

    # 3. Review Legal RAG Answer
    print("\n[3] LEGAL RAG javobi QA AUDIT (/api/v1/assistant/review) orqali tekshirilmoqda...")
    rag_review = call_review(question_text, rag_resp["answer"])
    print(f"Legal RAG Audit Natijasi ({rag_review['elapsed_s']}s):")
    print("  Hukm (Verdict):", rag_review.get("verdict"))
    print("  Ishonch (Confidence):", rag_review.get("confidence"))
    print("  Ballar:", rag_review.get("scores"))
    print("  Kamchiliklar:", rag_review.get("issues"))

    # Summary
    results = {
        "question_id": 1,
        "question": question_text,
        "gemini_argon_ground_truth": q1_argon,
        "tuzuk_ai": {
            "answer": q1_tuzuk["answer"],
            "review": tuzuk_review
        },
        "legal_rag": {
            "answer": rag_resp["answer"],
            "citations": rag_resp.get("citations", []),
            "review": rag_review
        }
    }
    with open("data/golden_dataset/sample_3way_eval_q1.json", "w", encoding="utf-8") as out:
        json.dump(results, out, indent=2, ensure_ascii=False)
    print("\n[+] Barcha natijalar data/golden_dataset/sample_3way_eval_q1.json ga saqlandi.")

if __name__ == "__main__":
    main()
