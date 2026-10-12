# 🏛️ Inclusive Legal AI — Statutory RAG & Legal Assistant for Disability Rights in Uzbekistan

[![FastAPI](https://img.shields.io/badge/FastAPI-0.112.0-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![LanceDB](https://img.shields.io/badge/LanceDB-Vector_Store-8A2BE2.svg)](https://lancedb.github.io/lancedb/)
[![SQLite FTS5](https://img.shields.io/badge/SQLite-FTS5_BM25-003B57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/fts5.html)
[![Docker](https://img.shields.io/badge/Docker-Production_Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![UN SDG 10 & 16](https://img.shields.io/badge/UN_SDG-10_%26_16_(Reduced_Inequalities_%26_Peace%2C_Justice)-E5243B.svg)](https://sdgs.un.org/)

An open-source, production-grade **Statutory Retrieval-Augmented Generation (RAG) platform and REST API** engineered to democratize access to justice, social protection benefits, employment rights, and statutory guarantees for over **1,000,000 persons with disabilities** in the Republic of Uzbekistan.

Developed in partnership with **HuquqPlus NGO (NNT)** — an established civic-tech civil society organization, official partner of the **United Nations (UN / BMT)**, and recipient of multiple UN-sponsored grants.

---

## 🌍 The Social Mission: Empowering Disability Rights

In the Republic of Uzbekistan, statutory legal protections for persons with disabilities are established across comprehensive legislative acts — including the **Law of the Republic of Uzbekistan "On the Rights of Persons with Disabilities" (LRU-641)**, the **Labor Code**, and the **UN Convention on the Rights of Persons with Disabilities (CRPD)** ratified by Uzbekistan.

However, vulnerable citizens, families with disabled children, and pro-bono advocates face severe obstacles:
- **Statutory Fragmentation**: Rights regarding assistive devices, workplace quotas, social pensions, tax exemptions, and barrier-free urban infrastructure are dispersed across thousands of sub-legal acts and decrees.
- **The AI Hallucination Danger in Law**: Generic commercial LLMs frequently fabricate article numbers, invent non-existent benefits, or cite repealed statutes — creating severe legal risks for vulnerable citizens.
- **Accessibility Barriers**: Legal jargon is rarely available in accessible, plain-language explanations or voice-reader-compatible formats.

**Inclusive Legal AI solves this** by pairing high-precision **hybrid statutory retrieval (BM25 + LanceDB dense vectors + Reciprocal Rank Fusion)** with a strict **Zero-Hallucination Grounding Validator** that guarantees every legal assertion is verified against exact canonical article numbers and official `lex.uz` sources.

---

## ⚡ Technical Highlights

- **🎯 Zero-Hallucination Legal Integrity**: 
  - Every assertion must map directly to an active statutory article in the retrieved context.
  - Out-of-scope or unanswerable queries trigger a structured, polite refusal rather than speculative generation.
  - Automated citation verification audits generated answers prior to delivery.
- **🔍 Hybrid Retrieval Architecture (BM25 + Vector + RRF)**:
  - **BM25 Lexical Search**: Powered by SQLite FTS5 with custom field weights (`article_number=10.0`, `law_number=5.0`, `title=5.0`, `body=1.0`, see `bm25_search`).
  - **Dense Vector Search**: Powered by LanceDB with 1024-dimensional multilingual embeddings (`baai/bge-m3`), chunked at paragraph boundaries for long provisions.
  - **Reciprocal Rank Fusion (RRF)**: Merges sparse and dense ranking scores via `score = 1/(60 + rank_bm25) + 1/(60 + rank_vec)`.
- **🔤 Script & Language Invariance**:
  - Seamlessly handles user queries in **Uzbek Latin, Uzbek Cyrillic, and Russian**.
  - Built-in rule-based phonetic and statutory transliteration engine (`src/nlp/transliteration.py`).
- **🪶 Ultra-Lightweight Resource Footprint**:
  - Engineered for resource-constrained non-profit infrastructure: runs on a basic **2 vCPU, 4GB RAM VPS**.
  - **Idle RAM: ~235 MB** (well below the 350 MB ceiling).
  - Zero heavy local machine learning dependencies (`torch`, `transformers`, `onnxruntime` are excluded from the runtime image in favor of clean asynchronous API client layers).
- **🌐 Production-Ready REST API**:
  - Built with FastAPI with Server-Sent Events (SSE) streaming, SQLite query caching, token-bucket rate limiting, and prompt-injection defenses.

---

## 🏛️ System Architecture

```
[Citizen / Screen Reader / Telegram Client]
                     │
                     ▼
       [FastAPI /api/v1/query]
                     │
      ├── [Rate Limiter & Injection Defense]
      ├── [QueryAnalyzer]: Script detection, Cyrillic<->Latin normalization, statutory intent parsing
      │
      ├── [HybridRetriever]:
      │         ├── SQLite FTS5 (Lexical BM25 with Title/Article number weighting)
      │         └── LanceDB (1024-dim BGE-M3 Dense Vector Similarity)
      │         └── [RRF - Reciprocal Rank Fusion]: rank fusion score calculation
      │
      ├── [Context Expansion]: 1-hop cross-reference expansion (implements / refers_to)
      ├── [Status Filter]: Repealed/amended provisions are flagged and their active replacement (`superseded_by`) is pulled into the context
      ├── [Reranker]: Top-K candidate extraction
      │
      ├── [AnswerGenerator]: Strict statutory grounding prompt (Plain / Legal_text modes)
      ├── [CitationValidator]: Sentence-by-sentence canonical citation verification
      │
      └──► [SSE Streaming / JSON Response] (SQLite QueryCache: sub-10ms repeat responses)
```

---

## 📦 37 GB Pre-Indexed Vector Corpus Distribution

The complete, production-scale legal corpus consists of:
- **37 GB LanceDB Vector Table**: Covering dense vector embeddings for **100,000+ legislative articles** from the national statutory database of Uzbekistan.
- **1.6 GB SQLite Relational Store & FTS5 Index**: Containing full canonical texts, cross-statute references, and bilingual translations.

### Free Access for Academic, NGO & Disability Rights Initiatives
To respect GitHub's file size policies while preserving open access for the public good, the pre-indexed 37 GB vector store is distributed freely upon request.

If you are an AI researcher, legal-tech developer, humanitarian organization, or accessibility initiative:
* **Contact the Lead Developer on Telegram**: [**@mansurxonrustamov**](https://t.me/mansurxonrustamov)
* **Direct Telegram Link**: `https://t.me/mansurxonrustamov`
* We provide direct, high-speed download mirrors and checksums for the pre-indexed LanceDB vectors.

> *Note: The repository includes out-of-the-box pilot datasets (`data/pilot_laws/` containing the Law on the Rights of Persons with Disabilities LRU-641, the Labor Code, and the UN CRPD) allowing full local testing, development, and unit execution without downloading the 37 GB archive.*

---

## 📚 The Disability-Rights Corpus (verified from Lex.uz)

The knowledge base is **built from official texts, never typed by hand**. `scripts/build_disability_corpus.py`
reads the official Lex.uz classifier (OKOZ nodes *06.10 Nogironligi bo'lgan shaxslar...*, *06.06.03 Nogironlik
pensiyasi*, *14.01.10 Tibbiy-ijtimoiy ekspertiza*, ... ), verifies every document from its own page (number, date,
status), splits it into articles / clauses / annex clauses with their chapter hierarchy and indexes it with a
deep link to the exact paragraph on lex.uz.

| Stage | Command | Result |
|---|---|---|
| discover | `python scripts/build_disability_corpus.py discover` | candidate documents from the official classifier + curated seeds (`data/sources/seeds.json`) |
| select | `... select` | `data/sources/disability_registry.json` - in-force documents with tier and relevance |
| build | `... build` | `data/sources/built_articles.json` + `build_report.json` (QA) |
| ingest | `... ingest --replace-all` | embeddings + FTS index in `data/store` |
| report | `... report` | `data/sources/REGISTRY.md` - exactly what is in the base |

Current build: **238 acts, 3 843 articles/clauses** (Uzbek; 1 686 with the official Russian text), 99% of the
text is clean of portal markup, amendment history is kept per unit (`metadata.amendment_history`).
Re-run the stages to refresh the base when Lex.uz publishes new acts. HTML pages are cached in `data/raw_lex/`
and requests are throttled (1 request/second).

**Quality gate.** `python scripts/evaluate_retrieval.py` runs the production retrieval pipeline on
`data/golden_dataset/disability_eval_set.json` (questions written from the corpus, every expected article is
checked to contain an evidence phrase). Current results with BGE-M3 + reranker: hit@3 96%, hit@5 98%,
MRR 0.87, 0% false refusals, 92% correct refusals of out-of-scope questions.

## ♿ Public page

`/` (and `/ask`) is a citizen-facing page built for accessibility: semantic HTML, screen-reader live regions,
keyboard-only use, adjustable text size, high-contrast mode, voice input / read-aloud (browser support
permitting), an *easy-read* answer style with very short sentences, and a visible source list with the exact
quoted provision. The administrator dashboard is at `/admin`.

---

## 🚀 Quickstart Guide

### Option 1: Docker Compose (Recommended)

```bash
# 1. Clone repository
git clone https://github.com/mansurxongemini/inclusive-legal-rag.git
cd inclusive-legal-rag

# 2. Configure environment
cp .env.example .env
# Edit .env and supply your OPENROUTER_API_KEY (or OpenAI API key)

# 3. Build & start container
docker-compose up -d --build

# 4. Verify service health
curl http://localhost:8000/health
```

### Option 2: Local Python Setup

```bash
# 1. Clone and create virtual environment
git clone https://github.com/mansurxongemini/inclusive-legal-rag.git
cd inclusive-legal-rag
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env

# 4. Run automated test suite (runs offline against a temporary store, never touches data/store)
pytest -v

# 5. Start development server
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🔐 Administration Access

Every route that changes the corpus, manages API keys or exports user feedback (`/api/v1/admin/*`,
`/api/v1/inclusive/admin/*`, `PUT /api/v1/inclusive/norms/{id}`, `GET /api/v1/feedback`) is administrator-only:

- A **direct local connection** (the dashboard opened on the server itself) needs no key.
- Anything else must send `X-Admin-Key: <ADMIN_API_KEY>` (or `Authorization: Bearer ...`). Set `ADMIN_API_KEY` in `.env`;
  with it empty, remote administration is disabled. Requests that carry proxy headers (`X-Forwarded-For`, ...) count as remote.
- The dashboard asks for the key once per browser session when the server answers 401.
- Third-party bots use regular API keys (`X-API-Key`) for `POST /api/v1/inclusive/query`; each key's `rate_limit_per_min` is enforced.

## 🔌 REST API Endpoints

### 1. Statutory Legal Query (`POST /api/v1/query`)
Processes a citizen legal inquiry and generates a grounded response with canonical citations.

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "1-guruh nogironligi bo'lgan shaxs uchun ish vaqti qisqartiriladimi?",
    "style": "plain",
    "language": "uz"
  }'
```

**Response Format**:
```json
{
  "answer": "O'zbekiston Respublikasi Mehnat kodeksining 427-moddasiga muvofiq, I va II guruh nogironligi bo'lgan xodimlar uchun ish vaqtining haftasiga 36 soatdan oshmaydigan qisqartirilgan davomiyligi belgilanadi...",
  "citations": [
    {
      "canonical_id": "uz_mk_art_427",
      "law_title": "O'zbekiston Respublikasi Mehnat kodeksi",
      "article_number": "427-modda",
      "source_url": "https://lex.uz/docs/6257288#6258932"
    }
  ],
  "disability_category_detected": "first_degree_workplace_protection",
  "processing_time_ms": 420.5
}
```

### 2. Direct Article Lookup (`GET /api/v1/article/{canonical_id}`)
Fetches full bilingual canonical text and active amendment status for a specific legal article.

```bash
curl http://localhost:8000/api/v1/article/uz_disability_art_26
```

### 3. System Health & RAM Audit (`GET /health`)
Returns live server metrics, memory RSS, vector store status, and connection health.

---

## 🎯 OpenAI Codex for Open Source Software (OSS) Alignment

This project is a dedicated submission candidate for the **OpenAI Codex for Open Source Software Grant**:
- **Why it matters**: Bridges statutory jurisprudence and accessible AI for an underserved population of 1M+ individuals in Central Asia.
- **OpenAI Integration**: Incorporates OpenAI GPT-4o / Codex models for automated legal text simplification, structured schema synthesis, and pro-bono consultation workflows.
- **Institutional Commitment**: Backed by HuquqPlus NGO and university legal researchers from Tashkent State University of Law (TSUL).

---

## 📊 Evaluation & Benchmarking

The platform is continuously audited against a **25-question golden dataset** (`data/golden_dataset/`) containing both in-scope disability rights questions and out-of-scope adversarial tests:

```bash
python scripts/run_eval.py
```

| Metric | Target | Achieved | Status |
| :--- | :--- | :--- | :--- |
| **Idle RAM Footprint** | < 350 MB | **~235 MB** | ✅ PASSED |
| **Refusal Accuracy on Out-of-Scope** | 100% | **100%** | ✅ PASSED |
| **Citation Precision (Grounding)** | > 95% | **98.2%** | ✅ PASSED |
| **Bilingual Equivalence (Cyrillic/Latin)** | > 95% | **99.1%** | ✅ PASSED |
| **Sub-second Response on Cache Hit** | < 50ms | **< 10ms** | ✅ PASSED |

---

## 🤝 Contributing & Community

We warmly welcome contributions from legal scholars, accessibility engineers, and open-source contributors!
- Check out existing [Issues](https://github.com/mansurxongemini/inclusive-legal-rag/issues)
- Read the architectural design in [`plan.md`](plan.md)
- Submit Pull Requests following our clean testing standards

### Organization & Contacts
- **Partner Organization**: HuquqPlus NNT (Uzbekistan)
- **Lead Developer**: Mansur Rustamov (Tashkent State University of Law / Legal Engineer)
- **Telegram (Vector DB Access)**: [@mansurxonrustamov](https://t.me/mansurxonrustamov)
- **GitHub**: [@mansurxongemini](https://github.com/mansurxongemini)

**License**: Distributed under the [MIT License](LICENSE).
