# MISSION: BUILD A PRODUCTION-GRADE, ULTRA-ACCURATE MULTILINGUAL LEGAL RAG PLATFORM
## (Uzbekistan legislation — disability rights, labor code, social protection)

You are a Principal AI Systems Architect and Senior Full-Stack Engineer. Build a complete,
end-to-end, lightweight, ultra-accurate Legal RAG (Retrieval-Augmented Generation) system for
Uzbekistan legislation. Accuracy and citation-faithfulness are the top priority — this system
will be used by disabled citizens and their families to understand their legal rights, so a
wrong or hallucinated answer is a real-world harm, not just a bug.

This document is written to be handed directly to a coding agent (yourself, or another
instance) as its working specification. Follow it section by section, in the stated build
order (Section 13). Do not skip the guardrail and evaluation sections to "get to the demo
faster" — for a legal-rights product, the guardrails ARE the product.

---

## 0. NON-NEGOTIABLE CONSTRAINTS

- **Hardware target**: Linux VPS, 2 vCPU, 4GB RAM. **Idle RSS footprint must stay under 350MB**
  for the whole application (API process + embedded vector store + embedded FTS index).
- **No local model inference of any kind**: no local transformer models, no local embedding
  models, no local OCR, no local reranker, no Elasticsearch/OpenSearch/Milvus/Qdrant servers.
  All embeddings, generation, reranking-by-LLM, and OCR (if ever needed for scanned amendments)
  MUST be calls to the OpenRouter API (or another external API you explicitly justify).
- **Everything must degrade gracefully**: if OpenRouter is down or rate-limited, the system
  must fail safely (clear error to the user) — never silently fall back to an ungrounded
  answer generated "from memory."
- **Every legal claim shown to a user must be traceable to a specific canonical_id, article
  number, law number, and source URL.** This is the single most important constraint in this
  entire document. Treat it as a hard invariant, not a nice-to-have.

---

## 1. DATA MODEL — Hierarchical Parallel Canonical Entity Model

The original granularity rule is correct and must be kept: **the retrieval unit is the Article
(Modda/Статья) — never split an article across arbitrary character/token counts.** The gap in
the original schema is that real legal citation happens *below* the article (a specific band/
qism/punkt — paragraph/point — inside the article), and articles reference *other* articles and
laws. Both must be modeled explicitly, or the system cannot answer precisely or track amendments.

### 1.1 Hierarchy
```
Law (Qonun/Закон)
 └─ Chapter (Bob/Глава)          [optional — not all laws have chapters]
     └─ Article (Modda/Статья)   ← retrieval unit, embedded as one whole
         └─ Point (Band/Qism/Punkt)  ← structured sub-field, NOT separately embedded,
                                        used only for precise in-answer citation
```

### 1.2 Canonical schema (expanded)
```json
{
  "canonical_id": "law_disability_2020_art_15",
  "schema_version": "1.1",
  "metadata": {
    "law_id": "law_disability_2020",
    "law_title": {
      "uz": "O'zbekiston Respublikasining 'Nogironligi bo'lgan shaxslarning huquqlari to'g'risida'gi Qonuni",
      "ru": "Закон Республики Узбекистан «О правах лиц с инвалидностью»",
      "en": "Law of the Republic of Uzbekistan 'On the Rights of Persons with Disabilities'"
    },
    "law_number": "O'RQ-641",
    "chapter_number": "3-bob",
    "article_number": "15-modda",
    "article_title": {
      "uz": "Nogironligi bo'lgan shaxslarga tibbiy yordam ko'rsatish",
      "ru": "Оказание медицинской помощи лицам с инвалидностью",
      "en": "Provision of medical assistance to persons with disabilities"
    },
    "source_url": "https://lex.uz/docs/5053070",
    "effective_date": "2021-01-16",
    "last_verified_date": "2026-09-01",
    "source_hash": "sha256:...",
    "status": "active",
    "superseded_by": null,
    "supersedes": null,
    "amendment_history": [
      {"amending_law_number": "O'RQ-712", "date": "2023-04-11", "summary_of_change": "..."}
    ],
    "category": "social_protection",
    "disability_types": ["physical", "visual", "hearing", "general"],
    "beneficiary_type": ["individual", "employer", "government_agency"],
    "cross_references": [
      {"ref_type": "implements", "target_canonical_id": "law_labor_code_art_178"},
      {"ref_type": "refers_to", "target_canonical_id": "decree_cm_2019_425"}
    ],
    "embedding_model_version": "bge-m3-2025-11-18"
  },
  "points": [
    {"point_id": "1", "text": {"uz": "...", "ru": "...", "en": "..."}},
    {"point_id": "2", "text": {"uz": "...", "ru": "...", "en": "..."}}
  ],
  "translations": {
    "uz": "Full official article text in Uzbek (Latin script canonical form)...",
    "ru": "Полный официальный текст статьи на русском...",
    "en": "Verified English translation of the article..."
  },
  "translation_provenance": {
    "uz": "official",
    "ru": "official",
    "en": "machine_translated_reviewed"
  }
}
```

**Fixes this makes over the original draft:**
- `points[]` lets the system cite "Article 15, point 3" precisely instead of only "Article 15."
- `status` / `superseded_by` / `supersedes` / `amendment_history` make amendment and repeal
  tracking a first-class, queryable property instead of an afterthought.
- `cross_references[]` turns the corpus into a graph, enabling 1-hop context expansion (Section
  3.4) — legal answers routinely depend on a referenced article in another law.
- `source_hash` + `last_verified_date` enable cheap change-detection during re-ingestion (only
  re-embed and re-review articles whose hash changed).
- `translation_provenance` distinguishes "official government text" from "machine translation
  reviewed by a human" from "machine translation, unreviewed" — critical for an accuracy-first
  system; unreviewed machine translations should be flagged to the user or excluded from `en`
  answers until reviewed.
- `embedding_model_version` lets you detect stale embeddings after an embedding-model upgrade.

---

## 2. INGESTION & VERSIONING PIPELINE

1. **Source**: scrape/fetch from lex.uz (the official legal information portal). Check
   lex.uz's robots.txt and terms of use before automated scraping; prefer an official API or
   bulk-export mechanism if lex.uz offers one, and rate-limit polling regardless (e.g., no more
   than one full crawl per day, incremental diff-checks more often).
2. **Parse** each law into the hierarchy in Section 1.1. Legal HTML on lex.uz is not uniformly
   structured across all laws — write a parser per law-family, not one universal regex, and
   have it fail loudly (not silently drop an article) on unrecognized structure.
3. **Script normalization**: Uzbek is published in both Latin and Cyrillic script. Store the
   canonical `uz` text in **Latin script** (Uzbekistan's official current script), and run every
   scraped Cyrillic Uzbek source through a rule-based Cyrillic→Latin transliterator. This
   transliteration has known ambiguous cases (е, ц, ъ, ў/ъ digraphs, ё→yo, etc.) — special-case
   them explicitly and unit-test against a curated list of known-tricky words; do not rely on a
   naive character map.
4. **Translation QA**: `uz` and `ru` are almost always both "official" (both are used in
   practice for legislation). `en` is very often *not* official — mark it
   `machine_translated_reviewed` or `machine_translated_unreviewed` per `translation_provenance`,
   and route unreviewed translations into a human-review queue before they're servable to users.
5. **Cross-reference extraction**: during ingestion, run a cheap OpenRouter LLM call (or
   deterministic regex for well-formed citations like "15-modda" / "статья 15") over each
   article to extract references to other articles/laws, and populate `cross_references[]`.
   Validate extracted references resolve to a real `canonical_id` before storing.
6. **Amendment diffing**: on each re-crawl, compute `source_hash` per article. If it changed,
   diff old vs. new text, create a new version, set the old version's `status` to `amended` (or
   `repealed`) with `superseded_by` pointing to the new `canonical_id`, and **queue the change
   for human legal review before it goes live** — never auto-publish a legal-text change
   without a review step, given the stakes.
7. **Embedding on ingest**: embed only new/changed articles (checked via `source_hash` and
   `embedding_model_version`), not the whole corpus every run.

---

## 3. RETRIEVAL ARCHITECTURE

### 3.1 Embeddings (external API only)
Use `baai/bge-m3` via the OpenRouter embeddings endpoint as the primary embedding model: it is
explicitly trained for multilingual retrieval, supports an 8,192-token context (long enough for
full articles, unlike 512-token-limited alternatives), and is inexpensive (roughly $0.01 per
million input tokens as of writing — verify current pricing at openrouter.ai before committing
budget). If higher retrieval quality is later needed and budget allows, `google/gemini-embedding-2`
is a fallback (also multilingual, flexible output dimensions 128–3,072, ~$0.20/M tokens).
Always store which model produced each vector (`embedding_model_version`) so you can detect and
re-embed stale vectors after a model upgrade instead of silently mixing embedding spaces.

### 3.2 Storage: embedded, serverless vector + full-text store
Given the 350MB idle-RAM budget, do **not** run a separate vector-database server (a minimal
Milvus deployment alone baselines over 1GB before storing a single vector). Use an **embedded**
store instead:
- **LanceDB** (Rust core, Python/JS bindings, disk-native, zero server process, built-in hybrid
  vector + full-text + SQL-style filtering) is the recommended default — it directly supports
  the hybrid search pattern in 3.3 without a second search engine.
- **sqlite-vec** is a valid lighter-weight alternative if you want everything in one SQLite file
  alongside your relational metadata (articles, cross-references, amendment history).
Either way: single file(s) on disk, no daemon, versionable, trivially backed up with `rsync`/
`cp`. For a corpus of a few thousand articles at 1024 dimensions, expect tens of MB of vector
data — well inside budget.

### 3.3 Hybrid retrieval (never vector-only for legal text)
Legal questions frequently hinge on an exact term or article number ("15-modda nima deydi?"),
which pure semantic search can miss. Retrieve with **both**:
1. Full-text/BM25-style match against the query's detected language field, and
2. Vector similarity against the `bge-m3` embedding,

then merge with **Reciprocal Rank Fusion (RRF)**, not a naive score average (scores from BM25
and cosine similarity are not on comparable scales).

### 3.4 Query understanding, script handling, and cross-reference expansion
1. **Language + script detection**: cheap heuristic first (Cyrillic vs. Latin character ranges,
   plus common Russian/English stopwords), falling back to a small OpenRouter LLM call only for
   genuinely ambiguous or code-switched queries.
2. **Normalize** the query the same way ingested text is normalized (Cyrillic→Latin for Uzbek)
   so matching is script-invariant.
3. Retrieve top-K (e.g., K=20) via hybrid search (3.3).
4. **Expand 1-hop** via `cross_references[]`: if a top hit references another article that's
   likely needed to answer completely (e.g., an "implements"/"refers_to" edge), pull it in too,
   capped at a small fixed number of extra articles to control token cost.
5. **Filter/flag by status**: if a top hit is `amended` or `repealed`, swap in (or add alongside,
   clearly labeled) its `superseded_by` version — never present a superseded article as current
   law without saying so.
6. **Rerank** the expanded candidate set down to top-N (e.g., N=5) with a single cheap OpenRouter
   LLM call structured as a scoring/ranking task (an actual dedicated reranker API is not
   required if budget is tight — an LLM asked to score relevance 0–10 per candidate works well
   at this corpus size).

---

## 4. GENERATION & ANTI-HALLUCINATION GUARDRAILS

This is the most important section. The generation-stage system prompt (for the OpenRouter call
that drafts the user-facing answer) must enforce, verbatim:

1. Answer **only** using the retrieved article text passed in context. Never supplement from
   general/background knowledge about Uzbek law, even if you believe you know the answer.
2. Every factual or legal claim in the answer must carry an inline citation naming the exact
   `article_number` (and `point_id` when applicable), `law_number`, and be traceable to a
   `canonical_id` / `source_url`.
3. If the retrieved articles do not clearly answer the question, say so explicitly — do not
   fill the gap with a plausible-sounding but unsupported answer. A correct "I couldn't find a
   specific provision covering this — here's the closest related article, or consult [relevant
   ministry/legal aid body]" beats a fluent wrong answer.
4. If any cited article's `status` is `amended` or `repealed`, the answer must say so and point
   to the current version.
5. Never invent an article number, law number, date, or URL. If uncertain which exact number
   applies, cite the `canonical_id` you actually retrieved, not one you're inferring.
6. End every substantive answer with a short, plain disclaimer: this is informational and not a
   substitute for advice from a qualified lawyer or the relevant government body (e.g., the
   Ministry of Employment and Labor Relations, or Nazorat/social protection agencies).

**Post-generation validation pass**: before returning the answer, run an automated check (regex/
parse, optionally backed by a second cheap LLM call) confirming every claim-bearing sentence has
a citation resolving to a `canonical_id` actually in the retrieved set. If a sentence fails this
check, strip it or regenerate rather than serving it uncited.

**Response modes**: support both (a) a plain-language summary mode and (b) a verbatim-legal-text
mode showing the exact statutory wording — users vary in whether they want simplified guidance
or the exact legal text to quote to an official.

---

## 5. API DESIGN

- `POST /api/v1/query` — body: `{ "question": str, "language": "auto"|"uz"|"ru"|"en",
  "mode": "plain"|"legal_text", "conversation_id": str|null }` → returns the answer, an array of
  citations (`canonical_id`, article/law numbers, `source_url`, `status`), and a confidence/
  refusal flag.
- `GET /api/v1/article/{canonical_id}` — fetch one canonical entity directly (all three
  languages, full metadata) — useful for "show me the full text of the article you cited."
- `GET /health` — liveness/readiness check (checks OpenRouter reachability + local store openable).
- `POST /api/v1/feedback` — lets a user or reviewer flag a wrong/unclear answer, feeding the
  human-review queue (Section 2) and the eval set (Section 7).
- Stream the generation response (Server-Sent Events or chunked) so users see progressive output
  rather than waiting on the full generation + validation pass; keep citations attached at the
  end once validation completes.

---

## 6. MULTILINGUAL, SCRIPT & ACCESSIBILITY REQUIREMENTS

This system exists specifically to serve people with disabilities — accessibility is a
functional requirement, not a nice-to-have:
- Detect and respond in the user's language/script automatically, but let them explicitly
  request a different response language.
- Plain-language mode should avoid dense legal jargon and nested clauses; keep sentences short.
- Output formatting should be screen-reader-friendly: avoid heavy nested markdown, ASCII tables,
  or symbol clutter that a text-to-speech engine reads awkwardly aloud.
- Support filtering/prioritizing by `disability_types` when a user states their disability type,
  so retrieval can prefer articles most relevant to them without hiding others.
- Never require a specific script (Latin or Cyrillic) from the user — accept both transparently.

---

## 7. EVALUATION & QA (must exist before public launch)

- Build a **golden dataset** of 100–300 real user-style questions, each with the legal-expert-
  verified correct `canonical_id`(s) and an approved reference answer, covering disability
  rights, labor code, and social protection, in all three languages.
- Automated metrics run on every change to prompts, models, or the corpus:
  - **Citation precision/recall** — does the system cite the correct canonical_id(s)?
  - **Faithfulness** — does every claim trace to retrieved text (LLM-as-judge or the validation
    pass from Section 4)?
  - **Correct refusal rate** — does it appropriately decline out-of-scope questions instead of
    hallucinating?
  - **Latency and cost per query.**
- Treat this suite as a **regression gate**: run it after every ingestion update and before
  deploying any prompt/model change; block deployment on a faithfulness or citation-precision
  drop.

---

## 8. SECURITY, RELIABILITY & COST CONTROL

- **Prompt-injection defense**: scraped legal text is generally trusted, but treat any ingested
  or user-submitted text as untrusted input to the LLM call — never let retrieved article text
  or user queries override the system-level grounding rules in Section 4.
- **Rate limiting** per IP/session on `/api/v1/query` to control cost and abuse.
- **Fallback chain across OpenRouter models**: define a primary generation model plus 1–2
  fallbacks (pick current top instruction-following models available on OpenRouter at build
  time — exact model IDs change often enough that hardcoding one here would go stale). Wrap
  every OpenRouter call in retry-with-exponential-backoff and a circuit breaker; on total
  failure, return a clear "service temporarily unavailable" — never a silently ungrounded answer.
- **Caching**: cache repeated/common queries (a simple on-disk SQLite or LRU cache is enough at
  this scale — no Redis needed) to cut both cost and latency.
- **Secrets**: OpenRouter API key via environment variable / secrets manager, never committed or
  logged.
- **Privacy**: if users disclose personal details (a specific disability, employment situation)
  in free-text queries, avoid retaining that in long-term logs beyond what's needed for the
  feedback/review queue, and document this in a short privacy notice.

---

## 9. DEPLOYMENT & RESOURCE BUDGET

Target breakdown to stay under the 350MB idle budget on a 2 vCPU / 4GB VPS:

| Component | Est. idle RAM |
|---|---|
| Python/Uvicorn runtime + FastAPI app (1–2 workers) | ~80–120MB |
| Embedded vector+FTS store (LanceDB/sqlite-vec) for a few thousand articles at 1024-dim | ~50–100MB |
| OS + misc process overhead | ~50–80MB |
| **Total idle** | **~200–300MB**, leaving headroom under the 350MB ceiling for request bursts |

- **Containerize** with a multi-stage Docker build for a small image; run as a single container
  under systemd (or Docker's own restart policy).
- **Reverse proxy**: Caddy (simplest automatic TLS) or Nginx in front of Uvicorn.
- **Scheduler**: a systemd timer or APScheduler job for periodic re-ingestion/change-detection
  (Section 2), decoupled from the request-serving process so a slow crawl never blocks queries.
- **Backups**: the entire knowledge base is just files on disk (LanceDB/sqlite-vec + relational
  metadata) — back up with a scheduled `rsync`/`cp` to remote storage; no special DB-dump tooling
  needed.
- **Monitoring**: structured JSON logs plus the `/health` endpoint are sufficient at this scale;
  avoid running a full Prometheus/Grafana stack on the same box — it would itself blow the RAM
  budget. Ship logs/metrics to an external service if deeper observability is needed later.

---

## 10. RECOMMENDED TECH STACK

- **Backend**: Python 3.12, FastAPI + Uvicorn (1–2 workers to match 2 vCPUs).
- **Vector + FTS store**: LanceDB (preferred — native hybrid vector/full-text/SQL filtering) or
  sqlite-vec.
- **HTTP client**: `httpx` with retry/backoff for all OpenRouter calls.
- **Ingestion**: `httpx`/`BeautifulSoup` (or a per-law-family parser) for lex.uz, `APScheduler`
  or a systemd timer for scheduling.
- **Testing**: `pytest` for unit/integration tests, plus the golden-dataset eval harness (Section 7).
- **Containerization**: Docker (multi-stage build), `docker-compose` for local dev only.

---

## 11. BUILD ORDER (phased milestones)

0. Repo scaffold, config/secrets management, CI skeleton.
1. Canonical schema (Section 1) + a small hand-seeded pilot dataset (the disability rights law
   only) to validate the model before automating ingestion.
2. Embedding + storage layer (LanceDB) + a bare retrieval test harness (no generation yet).
3. Hybrid retrieval (BM25 + vector, RRF) + cross-reference expansion + status/amendment filtering.
4. Generation layer with the grounding system prompt (Section 4) + citation-validation pass.
5. API (Section 5) + response formatting for plain-language/legal-text modes and accessibility.
6. Evaluation harness + golden dataset (Section 7) — do this *before* wide ingestion, so every
   subsequent step is measured.
7. Full ingestion automation for labor code + social protection laws (scraper, change-detection,
   human-review queue).
8. Deployment hardening (Docker, systemd, reverse proxy, backups) + load-test on the actual
   2 vCPU/4GB target to confirm the resource budget in Section 9.
9. Security pass: rate limiting, prompt-injection test cases, secrets audit.
10. Launch checklist: golden-set pass rate, resource budget confirmed, disclaimer text reviewed,
    human-review queue staffed, feedback loop wired up.

---

## 11.1. Lightweight Admin UI
- Provide a minimal, clean single-page web dashboard (served directly by FastAPI at `/admin` using lightweight Tailwind/HTML/JS, no heavy frontend frameworks).
- Features: view indexed articles, inspect parallel UZ/RU/EN translations, search by canonical_id, upload new law files (.txt/.md), and delete obsolete articles.
## 12. ACCEPTANCE CRITERIA CHECKLIST

- [ ] Idle RAM measured under 350MB on the actual target VPS spec (not just estimated).
- [ ] No local model weights loaded anywhere in the process (verify via dependency audit).
- [ ] Every answer in the golden dataset carries correct, resolvable citations.
- [ ] Amended/repealed articles are never presented as current without a flag.
- [ ] System correctly refuses (rather than hallucinates) on out-of-corpus questions in the
      golden set.
- [ ] Uzbek Cyrillic and Latin script inputs both retrieve correctly.
- [ ] OpenRouter outage is handled with a clear user-facing error, never a silent fallback to
      an ungrounded answer.
- [ ] Plain-language and legal-text response modes both pass expert review.
- [ ] Backup/restore of the knowledge base tested end-to-end.

