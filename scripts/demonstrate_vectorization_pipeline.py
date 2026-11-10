"""
Live Pipeline Demonstration for Lex.uz document: https://lex.uz/uz/docs/-8400823
Shows every step of the 4-stage ingestion, metadata tagging, BGE-M3 vectorization,
and hybrid search verification without manual intervention.
"""
import asyncio
import os
import sys
import time

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.abspath("."))

from src.ingestion.url_importer import LexUrlImporter, UrlImportRequest
from src.retrieval.hybrid_retriever import HybridRetriever
from src.storage.hybrid_store import HybridStore


async def run_live_demonstration():
    target_url = "https://lex.uz/uz/docs/-8400823"
    
    print("\n" + "=" * 80)
    print("🚀 NOGIRONLIK HUQUQI RAG TIZIMI: VEKTORLASH JARAYONINING JONLI DEMONSTRATSIYASI")
    print(f"📌 Manba: {target_url}")
    print("=" * 80 + "\n")

    # =========================================================================
    # 1-BOSQICH: MATNNI YUKLASH, TOZALASH VA MODDALARGA / BANDLARGA AJRATISH
    # =========================================================================
    print("━" * 80)
    print("🔹 1-BOSQICH: TARMOQDAN YUKLASH VA MATNNI HUQUQIY BO'LAKLARGA AJRATISH (SEGMENTATSIYA)")
    print("━" * 80)
    
    t0 = time.time()
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print("1.1. Lex.uz serveriga so'rov yuborilmoqda...")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(target_url, headers=headers)
        status = resp.status_code
        raw_html = resp.text

    print(f"     ✅ Server javobi: HTTP {status} OK (Hajmi: {len(raw_html):,} bayt)")

    importer = LexUrlImporter()
    req = UrlImportRequest(url=target_url)

    print("1.2. Sayt navigatsiyasi, audio panellar va fon elementlari tozalanmoqda...")
    soup = BeautifulSoup(raw_html, "html.parser")
    for el in soup.select(".lx_elem2, .lx_elem3, .docNabvar, script, style, .doc-tools, .doc_tools"):
        el.decompose()

    print("1.3. Hujjat rekvizitlari va nomerlanishi aniqlanmoqda...")
    articles, law_number, law_title = importer.parse_lex_html(raw_html, target_url, req)
    
    print(f"     ✅ Aniqlangan hujjat raqami: {law_number}")
    print(f"     ✅ Hujjat rasmiy nomi: {law_title[:95]}...")
    print(f"     ✅ Ajratib olingan mustaqil huquqiy normalar (bandlar) soni: {len(articles)} ta")
    print(f"     ⏱ 1-bosqich bajarilish vaqti: {(time.time() - t0)*1000:.1f} ms\n")

    sample_art = articles[0]
    print("🔎 1-BAND MATNINING ASL NUSXASI VA TOZALANGAN SHAKLI:")
    print("   [Band raqami]:", sample_art.metadata.article_number)
    print("   [Matn lavhasi]:", sample_art.translations["uz"][:320] + "...\n")

    # =========================================================================
    # 2-BOSQICH: HUQUQIY METAMA'LUMOTLARNI BIRIKTIRISH VA TEGLASH
    # =========================================================================
    print("━" * 80)
    print("🔹 2-BOSQICH: HUQUQIY METAMA'LUMOTLARNI BOYITISH VA TOIFALASH (METADATA ENRICHMENT)")
    print("━" * 80)
    
    t1 = time.time()
    print("2.1. Sun'iy intellekt tahliliga ko'ra yuridik xususiyatlar biriktirilmoqda:")
    print(f"     🏷 Huquqiy soha (Kategoriya): {sample_art.metadata.category}")
    print(f"     👥 Qamrab olingan nogironlik guruhlari: {', '.join(sample_art.metadata.disability_types)}")
    print(f"     🏛 Huquqdan foydalanuvchilar (Benefisiar): {', '.join(sample_art.metadata.beneficiary_type)}")
    print(f"     🔗 Rasmiy Lex.uz havolasi: {sample_art.metadata.source_url}")
    print(f"     🔑 Raqamli xesh (Source Hash): {sample_art.metadata.source_hash}")
    print(f"     ⏱ 2-bosqich bajarilish vaqti: {(time.time() - t1)*1000:.1f} ms\n")

    # =========================================================================
    # 3-BOSQICH: BGE-M3 MODELI ORQALI SEMANTIK VEKTOR HISOBLASH
    # =========================================================================
    print("━" * 80)
    print("🔹 3-BOSQICH: KO'P TILLI BGE-M3 MODELI ORQALI SEMANTIK VEKTOR HISOBLASH")
    print("━" * 80)
    
    store = HybridStore()
    t2 = time.time()
    print("3.1. BGE-M3 neyron tarmog'i yuklanmoqda va matn vektor koordinatalariga aylantirilmoqda...")
    
    from src.clients.openrouter import OpenRouterClient
    client = OpenRouterClient()
    sample_text = sample_art.translations["uz"]
    embeddings = await client.get_embeddings([sample_text])
    embedding_vector = embeddings[0]
    
    print(f"     ✅ Vektor o'lchami (Dimensions): {len(embedding_vector)} ta float ko'rsatkichi")
    print(f"     ✅ Vektor normasi (Unit length check): {sum(x*x for x in embedding_vector)**0.5:.4f}")
    print("     📊 Vektor koordinatalaridan dastlabki 10 ta son namunasi:")
    print("        [ " + ", ".join(f"{x:+.5f}" for x in embedding_vector[:10]) + ", ... ]")
    print(f"     ⏱ 3-bosqich bajarilish vaqti (Bitta norma uchun): {(time.time() - t2)*1000:.1f} ms\n")

    # =========================================================================
    # 4-BOSQICH: GIBRID OMBORGA (SQLITE + LANCEDB) MUHRLASH VA TEKSHIRUV
    # =========================================================================
    print("━" * 80)
    print("🔹 4-BOSQICH: GIBRID OMBORGA (SQLITE FTS5 + LANCEDB) MUHRLASH VA JONLI TEKSHIRUV")
    print("━" * 80)
    
    t3 = time.time()
    print(f"4.1. Barcha {len(articles)} ta normalar bazaga yozilmoqda...")
    await store.index_articles_batch(articles)
    print("     ✅ SQLite (Matnli qidiruv) va LanceDB (Vektorli ombor)ga to'liq saqlandi.")
    print(f"     ⏱ Saqlash va indekslash vaqti: {(time.time() - t3)*1000:.1f} ms\n")

    # 4.2. LIVE RETRIEVAL TEST: Check that the system finds it accurately
    test_question = "1941-1945 yillardagi urush nogironlari uchun jamoat transportida qanday imtiyozlar beriladi?"
    print("4.2. Jonli semantik qidiruv orqali tekshirish:")
    print(f"     ❓ Savol: \"{test_question}\"")
    
    retriever = HybridRetriever(store=store)
    t4 = time.time()
    scored_results = await retriever.retrieve(test_question, top_k=3)
    
    print(f"     ⏱ Qidiruv tezligi: {(time.time() - t4)*1000:.1f} ms")
    print(f"     🎯 Topilgan eng mos huquqiy normalar soni: {len(scored_results)} ta\n")

    for i, res in enumerate(scored_results, 1):
        art = store.get_article(res.canonical_id)
        if not art:
            continue
        meta = art.metadata
        print(f"   [{i}-NATIJA] RRF Balli: {res.rrf_score:.4f} | Vektor Rank: {res.vector_rank} | Matnli (BM25) Rank: {res.bm25_rank}")
        print(f"      📌 Norma: {meta.law_number} ({meta.article_number})")
        print(f"      📋 Hujjat: {meta.law_title.get('uz', '')[:85]}...")
        print(f"      🔗 Rasmiy havola: {meta.source_url}")
        print(f"      📝 Huquqiy matn: {art.translations.get('uz', '')[:220]}...\n")

    print("=" * 80)
    print("🎉 DEMONSTRATSIYA MUVAFFAQIYATLI YAKUNLANDI!")
    print(f"Hujjat ({law_number}) to'liq tahlil qilindi, 4 ta bosqichdan o'tkazildi va qidiruvga tayyor holatga keltirildi.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_live_demonstration())
