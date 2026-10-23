#!/usr/bin/env python3
"""
scripts/harvest_tuzuk_api.py - Lightweight background API client for Tuzuk AI.
Runs with near-zero CPU/GPU footprint, streaming responses directly from Tuzuk's API.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "https://api.tuzuk.ai/api/v1"
QUERY_BANK_PATH = Path("data/sources/tuzuk_query_bank.json")
HARVEST_DIR = Path("data/sources/harvested_tuzuk")

def get_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    }

def create_conversation(headers: dict, title: str = "Huquqiy Tadqiqot") -> str:
    url = f"{BASE_URL}/chat-conversation/create"
    data = json.dumps({"title": title}).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["conversationUUID"]

def ask_question_stream(headers: dict, conv_uuid: str, question: str) -> str:
    url = f"{BASE_URL}/ai/agentic/ask-with-stream"
    payload = {
        "conversation_id": conv_uuid,
        "question": question,
        "memory": False,
        "use_cache": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=data, method="POST")
    
    deltas = []
    with urllib.request.urlopen(req, timeout=90) as resp:
        for line in resp:
            line_str = line.decode("utf-8", errors="ignore").strip()
            if not line_str.startswith("data:"):
                continue
            data_str = line_str[5:].strip()
            if not data_str:
                continue
            try:
                ev = json.loads(data_str)
                ev_type = ev.get("type")
                if ev_type == "answer_delta":
                    deltas.append(ev.get("delta", ""))
                elif ev_type == "completed":
                    break
            except json.JSONDecodeError:
                pass
    return "".join(deltas).strip()

def extract_laws_mentioned(text: str) -> list:
    patterns = [
        r"O‘zbekiston Respublikasi[^\n\.\,\;]+(?:Kodeksi|Qonuni|Farmoni|Qarori|buyrug‘i|nizomi)",
        r"(?:Mehnat|Soliq|Uy-joy|Fuqarolik|Ma’muriy|Jinoyat|Oila)\s+kodeksi[^\n\.\,\;]*",
        r"Vazirlar Mahkamasining[^\n\.\,\;]+qarori",
        r"Prezidentning[^\n\.\,\;]+(?:Farmoni|qarori)",
        r"PF-\d+[^\n\.\,\;]*",
        r"PQ-\d+[^\n\.\,\;]*",
        r"VMQ-\d+[^\n\.\,\;]*",
    ]
    results = []
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        for m in matches:
            clean = m.strip("()[]\"' ,;.")
            if clean and clean not in results and len(clean) > 8:
                results.append(clean)
    return results[:5]

def process_batch(start_idx: int, count: int, batch_num: int, token: str, input_file: Path, out_dir: Path, auto_ingest: bool = False):
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_file = out_dir / f"batch_{batch_num:02d}.json"
    
    with open(input_file, "r", encoding="utf-8") as f:
        query_bank = json.load(f)
    
    target_questions = query_bank[start_idx : start_idx + count]
    print(f"[*] Partiya {batch_num} boshlanmoqda: {input_file.name} dan index {start_idx}..{start_idx + len(target_questions)} ({len(target_questions)} ta savol)")
    
    headers = get_headers(token)
    batch_results = []
    
    for i, item in enumerate(target_questions):
        qid = item.get("id", start_idx + i + 1)
        q_text = item.get("question")
        category = item.get("category_name") or item.get("category", "")
        print(f"\n[{i+1}/{len(target_questions)}] Savol #{qid} ({category[:30]}): {q_text[:70]}...")
        
        try:
            conv_uuid = create_conversation(headers, title=f"Q{qid}: {q_text[:30]}")
            t0 = time.time()
            answer = ask_question_stream(headers, conv_uuid, q_text)
            elapsed = time.time() - t0
            print(f"    -> Javob olindi ({elapsed:.1f} soniya, {len(answer)} belgi)")
            
            # Extract sources
            lex_matches = re.findall(r"https?://(?:www\.)?lex\.uz/docs/(-?\d+)", answer)
            unique_sources = list(dict.fromkeys([f"https://lex.uz/docs/{m}" for m in lex_matches]))
            laws = extract_laws_mentioned(answer)
            
            entry = {
                "id": qid,
                "category": category,
                "question": q_text,
                "answer": answer,
                "cited_sources": unique_sources,
                "laws_mentioned": laws,
                "metadata": {
                    "difficulty": item.get("difficulty", "murakkab"),
                    "key_legal_acts": item.get("key_legal_acts", []),
                    "complexity_reason": item.get("complexity_reason", "")
                }
            }
            batch_results.append(entry)
            time.sleep(2)  # respectful pause between questions
        except Exception as e:
            print(f"    [!] Xatolik: {e}")
            time.sleep(5)
    
    with open(batch_file, "w", encoding="utf-8") as f:
        json.dump(batch_results, f, ensure_ascii=False, indent=2)
    print(f"\n[+] Partiya {batch_num} saqlandi: {batch_file} ({len(batch_results)} ta savol-javob)")
    
    if auto_ingest:
        print("\n[*] Avtomatik tahlil va integratsiya ishga tushirilmoqda...")
        subprocess.run([sys.executable, "scripts/analyze_harvested.py"], check=False)
        
        missing_file = Path("data/sources/discovered_missing_acts.json")
        if missing_file.exists():
            try:
                with open(missing_file, "r", encoding="utf-8") as mf:
                    missing = json.load(mf)
                for lex_id in missing:
                    clean_id = str(lex_id).strip()
                    if clean_id:
                        print(f"[+] Yangi topilgan hujjat yuklab olinmoqda: {clean_id}...")
                        res = subprocess.run([sys.executable, "scripts/build_disability_corpus.py", "add", "--lex-id", clean_id, "--include", "all"], check=False)
                        if res.returncode == 0:
                            subprocess.run([sys.executable, "scripts/append_act_to_corpus.py", clean_id], check=False)
                        else:
                            print(f"[!] Hujjat {clean_id} yuklab olinmadi, o'tkazib yuborildi.")
            except Exception as e:
                print(f"[!] Avto-ingest xatoligi: {e}")

    return batch_file

def main():
    parser = argparse.ArgumentParser(description="Tuzuk AI lightweight API harvester")
    parser.add_argument("--input-file", type=str, default="data/golden_dataset/uzbekistan_nogironlik_huquqi_200_savol_benchmark.json", help="Path to input questions JSON")
    parser.add_argument("--out-dir", type=str, default="data/sources/harvested_benchmark", help="Output directory")
    parser.add_argument("--start-idx", type=int, default=0, help="Start index in query bank (0-based)")
    parser.add_argument("--count", type=int, default=5, help="Number of questions to process per batch")
    parser.add_argument("--batch-num", type=int, default=1, help="Batch number for saving")
    parser.add_argument("--total-batches", type=int, default=1, help="Total batches to process sequentially")
    parser.add_argument("--auto-ingest", action="store_true", help="Auto ingest missing acts after batch")
    parser.add_argument("--token", type=str, default="", help="Bearer token (prefer the TUZUK_BEARER_TOKEN environment variable)")
    args = parser.parse_args()
    
    token = os.environ.get("TUZUK_BEARER_TOKEN") or args.token
    if not token:
        sys.exit("Tuzuk AI token is required: set TUZUK_BEARER_TOKEN (never commit it) or pass --token.")
    input_path = Path(args.input_file)
    out_dir = Path(args.out_dir)
    
    curr_idx = args.start_idx
    for b in range(args.total_batches):
        batch_n = args.batch_num + b
        process_batch(curr_idx, args.count, batch_n, token, input_path, out_dir, args.auto_ingest)
        curr_idx += args.count
        if b < args.total_batches - 1:
            print("[*] Partiyalar oralig'ida 5 soniya tanaffus...")
            time.sleep(5)

if __name__ == "__main__":
    main()
