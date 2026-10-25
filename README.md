# Inclusive Legal AI — Statutory RAG & Legal Assistant for Disability Rights in Uzbekistan

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

## The Social Mission: Empowering Disability Rights

In the Republic of Uzbekistan, statutory legal protections for persons with disabilities are established across comprehensive legislative acts — including the **Law of the Republic of Uzbekistan "On the Rights of Persons with Disabilities" (LRU-641)**, the **Labor Code**, and the **UN Convention on the Rights of Persons with Disabilities (CRPD)** ratified by Uzbekistan.

However, vulnerable citizens, families with disabled children, and pro-bono advocates face severe obstacles:
- **Statutory Fragmentation**: Rights regarding assistive devices, workplace quotas, social pensions, tax exemptions, and barrier-free urban infrastructure are dispersed across thousands of sub-legal acts and decrees.
- **The AI Hallucination Danger in Law**: Generic commercial LLMs frequently fabricate article numbers, invent non-existent benefits, or cite repealed statutes — creating severe legal risks for vulnerable citizens.
- **Accessibility Barriers**: Legal jargon is rarely available in accessible, plain-language explanations or voice-reader-compatible formats.

**Inclusive Legal AI solves this** by pairing high-precision **hybrid statutory retrieval (BM25 + LanceDB dense vectors + Reciprocal Rank Fusion)** with a strict **Zero-Hallucination Grounding Validator** that guarantees every legal assertion is verified against exact canonical article numbers and official `lex.uz` sources.

---

## Technical Highlights

- **Zero-Hallucination Legal Integrity**: 
  - Every assertion must map directly to an active statutory article in the retrieved context.
  - Out-of-scope or unanswerable queries trigger a structured, polite refusal rather than speculative generation.
  - Automated citation verification audits generated answers prior to delivery.
- **Hybrid Retrieval Architecture (BM25 + Vector + RRF)**:
  - **BM25 Lexical Search**: Powered by SQLite FTS5 with custom field weights (`article_number=10.0`, `law_number=5.0`, `title=5.0`, `body=1.0`, see `bm25_search`).
  - **Dense Vector Search**: Powered by LanceDB with 1024-dimensional multilingual embeddings (`qwen/qwen3-embedding-8b`; the store records its model and the service never mixes two), chunked at paragraph boundaries for long provisions.
  - **Reciprocal Rank Fusion (RRF)**: Merges sparse and dense ranking scores via `score = 1/(60 + rank_bm25) + 1/(60 + rank_vec)`.
- **Script & Language Invariance**:
  - Seamlessly handles user queries in **Uzbek (Latin and Cyrillic), Russian and English** and answers in the language of the question.
    The units and every vector are Uzbek: a Russian or English question is searched through an Uzbek translation.
  - Built-in rule-based phonetic and statutory transliteration engine (`src/nlp/transliteration.py`).
- **Ultra-Lightweight Resource Footprint**:
  - Engineered for resource-constrained non-profit infrastructure: runs on a basic **2 vCPU, 4GB RAM VPS**.
  - **Resident memory: ~180-200 MB** while serving (glibc allocator tuned in `src/runtime_tuning.py`; without it a vector search inflated the process to 900+ MB).
  - Zero heavy local machine learning dependencies (`torch`, `transformers`, `onnxruntime` are excluded from the runtime image in favor of clean asynchronous API client layers).
- **Production-Ready REST API**:
  - Built with FastAPI with Server-Sent Events (SSE) streaming, SQLite query caching, token-bucket rate limiting, and prompt-injection defenses.

---

## System Architecture

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
      │         └── LanceDB (1024-dim qwen3-embedding dense vector similarity)
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

## Size of the knowledge base

Measured on 2026-10-25 (`data/store`, built by `scripts/build_disability_corpus.py`):
- **SQLite store with FTS5 index: 305 MB** - 27 530 units of 518 Lex.uz acts (14 963 with the official Russian text) and 324 units of
  113 Huquq+ posts.
- **LanceDB vector table: 148 MB** - 37 464 bge-m3 vectors (1024 numbers each; long units are embedded paragraph by paragraph).

The built store is not in git (`data/store` is ignored). Build it from Lex.uz with the commands below (the HTML is fetched once and
cached), or ask the maintainer for a copy: Telegram [@mansurxonrustamov](https://t.me/mansurxonrustamov).
The repository ships `data/pilot_laws/` (the Law on the rights of persons with disabilities O'RQ-641, selected Labour Code articles and
the UN CRPD): the server seeds O'RQ-641 into an empty store on its first start, and the test suite runs on it offline.

---

## The Disability-Rights Corpus (verified from Lex.uz)

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

Current build: **518 Lex.uz acts, 27 530 articles/clauses** (Uzbek; 14 963 with the official Russian text) plus **113 Huquq+ posts (324 units)**
= 27 854 units, 37 464 embedded chunks. Units longer than 6 000 characters are also indexed chunk by chunk, so a paragraph deep inside a
code article (the Tax Code day-care exemption, art. 483) is found. Amendment history is kept per unit (`metadata.amendment_history`).
Re-run the stages to refresh the base when Lex.uz publishes new acts. HTML pages are cached in `data/raw_lex/`
and requests are throttled (1 request/second).

**Quality gate.** `python eval/run_eval.py` answers the 76 questions of `eval/gold_set.jsonl` (Uzbek, Russian, English; every
expected unit was read in the store) through the production path and measures retrieval, citations, refusals, answer language,
numbers, repealed-act traps, latency and cost; results are in "Evaluation & Benchmarking" below.

## Public page

`/` (and `/ask`) is a citizen-facing page built for accessibility: semantic HTML, screen-reader live regions,
keyboard-only use, adjustable text size, high-contrast mode, voice input / read-aloud (browser support
permitting), an *easy-read* answer style with very short sentences, and a visible source list with the exact
quoted provision. The administrator dashboard is at `/admin`.

---

## Quickstart Guide

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

# 2. Install dependencies (the exact tested versions are in requirements.lock)
pip install -r requirements-dev.txt -c requirements.lock

# 3. Set environment variables (OPENROUTER_API_KEY; without it everything runs offline with placeholder answers)
cp .env.example .env

# 4. Run automated test suite (runs offline against a temporary store, never touches data/store)
pytest -v

# 5. Build the knowledge base in data/store (needs the key: the units are embedded with qwen3-embedding-8b)
#    one act, about a minute - the Law on the rights of persons with disabilities:
python scripts/build_disability_corpus.py refresh --law-ids law_disability_2020 --store-dir data/store
#    or the whole registry (518 acts; Lex.uz is read at 1 request/second, so the first build takes hours):
python scripts/build_disability_corpus.py build
python scripts/build_disability_corpus.py ingest --replace-all --store-dir data/store
#    (with no step 5 the server seeds O'RQ-641 from data/pilot_laws on its first start)

# 6. Start development server, then check it
.venv/bin/python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
curl http://localhost:8000/health
```

Checked on 2026-10-25 in a fresh clone (Python 3.13): steps 1-6 work as written; one act ingests in about a minute and the server
answers with a cited article.

---

## Administration Access

Every route that changes the corpus, manages the partners' API keys or exports user feedback (`/api/v1/admin/*`,
`GET /api/v1/articles`, `GET /api/v1/feedback`) is administrator-only:

- A **direct local connection** (the dashboard opened on the server itself) needs no key **while `ADMIN_API_KEY` is empty**; as soon as a key is configured the loopback shortcut is off by default (`ADMIN_LOOPBACK_ENABLED` overrides).
- Anything else must send `X-Admin-Key: <ADMIN_API_KEY>` (or `Authorization: Bearer ...`). Set `ADMIN_API_KEY` in `.env`;
  with it empty, remote administration is disabled. Requests that carry proxy headers (`X-Forwarded-For`, ...) count as remote,
  and so do local requests driven by another web page (foreign `Host`, `Origin` or `Sec-Fetch-Site: cross-site`).
- **Behind a reverse proxy** that does not forward `X-Forwarded-For` / `X-Real-IP` (nginx does not by default) every visitor
  looks like a direct local connection. Set `ADMIN_LOOPBACK_ENABLED=false` there: the key is then the only way in.
- The dashboard asks for the key once per browser session when the server answers 401.
- Third-party bots and partner sites use the assistant API (`POST /api/v1/assistant/ask`, `Authorization: Bearer hpk_...`); keys are issued on the dashboard's Integratsiyalar page and carry their own limits (see `integrations/api/README.md`).

## REST API Endpoints

### 1. Statutory Legal Query (`POST /api/v1/query`)
Processes a citizen legal inquiry and generates a grounded response with canonical citations.

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "question": "1-guruh nogironligi bo'lgan shaxs uchun ish vaqti qisqartiriladimi?",
  "language": "uz",
  "mode": "plain"
}
JSON
```

| Field | Required | Values |
| :--- | :--- | :--- |
| `question` | yes | 1-4000 characters |
| `language` | no | `auto` (default: detected from the question), `uz`, `ru`, `en`; the answer is written in this language |
| `mode` | no | `plain` (default), `legal_text`, `easy_read`, `subsumption` |
| `disability_group` | no | `all` (default) or an id from `GET /api/v1/inclusive/categories` |
| `category` | no | `all` (default) or an id from `GET /api/v1/inclusive/categories` |
| `conversation_id` | no | optional trace id echoed back in the response |

Add `?stream=true` for a Server-Sent Events stream of tokens. Bots and partner sites call `POST /api/v1/assistant/ask`
with a key instead; it runs the same pipeline.

**Response Format** (abridged):
```json
{
  "answer": "Qisqartirilgan ish vaqti haftasiga 36 soatdan oshmaydi [1]...",
  "clean_answer": "...",
  "telegram_formatted": "...",
  "citations": [
    {
      "index": 1,
      "canonical_id": "uz_mk_art_427",
      "law_title": "O'zbekiston Respublikasi Mehnat kodeksi",
      "article_number": "427-modda",
      "source_url": "https://lex.uz/docs/6257288#6258932",
      "quote_snippet": "..."
    }
  ],
  "detected_language": "uz",
  "detected_script": "latn",
  "mode": "plain",
  "is_refusal": false,
  "validation_passed": true,
  "status_warnings": [],
  "cached": false,
  "cache_type": null,
  "semantic_similarity": null,
  "retrieval_confidence": 0.93
}
```
(Each citation also carries `law_number`, `article_title`, `status`, `source_type`, `normative_tier`, `normative_rank` and `confidence`.)

### 2. Direct Article Lookup (`GET /api/v1/article/{canonical_id}`)
Fetches full bilingual canonical text and active amendment status for a specific legal article.

```bash
curl http://localhost:8000/api/v1/article/uz_disability_art_26
```

### 3. System Health & RAM Audit (`GET /health`)
Returns live server metrics, memory RSS, vector store status, and connection health.

---

## OpenAI Codex for Open Source Software (OSS) Alignment

This project is a dedicated submission candidate for the **OpenAI Codex for Open Source Software Grant**:
- **Why it matters**: Bridges statutory jurisprudence and accessible AI for an underserved population of 1M+ individuals in Central Asia.
- **Providers**: one OpenRouter key and endpoint serve every call: the chat model (`GENERATION_MODEL_PRIMARY`: answers, translation, ranking, review), embeddings (`qwen/qwen3-embedding-8b`) and, optionally, the Jev reranker/scope gate. See `docs/OPERATIONS.md` for cost, the budget guard, degradation order, backup and the evaluation commands.
- **Institutional Commitment**: Backed by HuquqPlus NGO and university legal researchers from Tashkent State University of Law (TSUL).

---

## Evaluation & Benchmarking

**Gold set, production model** (`deepseek/deepseek-v4-flash-0731`, bge-m3), 2026-10-25, `python eval/run_eval.py`; every run is a row of
`EVAL_HISTORY.md`, the server-side checks are `python eval/check_server.py`:

| Measure | Result |
| :--- | :--- |
| Questions | 76 (26 uz, 25 ru, 25 en): short, complex, multi-article, repealed-act traps, out-of-corpus, misspelled / mixed language |
| Expected units in the top 5 contexts (recall@5) / MRR | **0.92 / 0.86** |
| Answers whose every citation was retrieved, exists, is in force and passed the validator | **100%** |
| Invented article numbers / numbers absent from the sources | **0 / 0** |
| Out-of-corpus questions refused / answerable questions refused | **100% / 0%** |
| Answer in the language of the question; required facts present | **100% / 100%** |
| Repealed acts presented as valid | **0** |
| Latency (full answer, uncached) median / p95 | **~16 s / ~32 s** |
| Model cost per uncached question | **~$0.0015** |
| Idle memory of the server; growth over 300 questions | **~180 MB; +1-5 MB** |

The figures below are older measurements on other sets and another (test) generator, kept for history.

Measured on 2026-10-23 (commands and cost notes in `docs/OPERATIONS.md`). Retrieval = the production pipeline (BM25 + vectors + RRF + Jev);
the judge was `muse-spark-1.2` and the generator `muse-spark-1.3` (a test provider that is gone: re-measure on the production model, see `docs/OPERATIONS.md`).

| Set | Questions | What is measured | Result |
| :--- | :--- | :--- | :--- |
| Stress set (`data/golden_dataset/stress_eval_200.json`, used while tuning) | 172 in-scope + 23 out-of-scope | expected unit first / in top 3 / in top 6 | **70% / 84% / 88%** (pool of 25: 92%) |
| Same set | out-of-scope | refused by the scope gate / in-scope refused wrongly | **100% / 0.6%** |
| Held-out set (`heldout_v1.json`, never tuned on) | 55 in-scope + 37 out-of-scope | expected unit first / top 3 / top 6 | **62% / 67% / 80%** |
| Held-out set | out-of-scope | refused / in-scope refused wrongly | **95% / 3.6%** |
| End to end, stress dev split (59 questions) | answers judged against the provision | correct / partial / wrong | **91% / 4% / 6%** (3 answers added a condition the provision does not state) |
| Deterministic answer checks (same 59 answers) | script of the question, leaked ids, forbidden wording, numbers absent from the sources | failures | **0% / 0% / 0% / 1.7%** |
| Latency | retrieval only / full answer | median | **3.3 s / 5.9 s** |
| Resident memory while serving | | | **~180-200 MB** |

The held-out figures are the honest ones: the stress set was used to tune the system and its labels were revised along the way, the
held-out questions were written from units no other set uses. Known weak classes: a paragraph reachable only through words the question
inflects differently (Cyrillic questions with typos), questions that need several units at once, and answers that add a plausible but
unstated condition.


---

## Contributing & Community

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
