# Vazifalar Ro'yxati (Task Ledger)

## Asosiy Topshiriqlar

1. [x] **1. Dizayn tahlili, kamchiliklarni aniqlash va tuzatish** — STATUS: DONE
   - **Dalil (Proof):**
     - Brauzer subagenti (`04bdf066-7cb5-4bf9-a130-df96fc1f8309`) orqali `http://127.0.0.1:8000` va `http://127.0.0.1:8000/admin-v2` to'liq vizual tahlil qilindi.
     - Markdown jadvallari (GFM tables) oddiy matn (`| col |`) ko'rinishida chiqib qolish muammosi `src/admin/static/js/markdown.js` va `src/admin/static/index.html` da to'liq CSS jadvallariga (`.data-table`) aylantirildi.
     - `admin-v2` dagi normalarni tahrirlash modalida saqlash tugmasi yo'qligi (`editModal.dialogFooter = footer` xatosi `editModal.setFooter(footer)` ga almashtirilib) bartaraf etildi.
     - `uploadModal` va `urlImportModal` modallariga ham `setFooter` ulandi.
     - Norma kartochkalaridagi sarlavha takrorlanishi (`10-band  10-band`) tuzatildi.
     - Pastki paneldagi `v1.0.0` yozuvining rang kontrasti `text-slate-600` ga o'zgartirilib, WCAG AA standartiga (4.5:1+) yetkazildi.
     - So'rov kechikish vaqti `12536.58 ms` o'rniga `12.5 s` yoki millisekund ko'rinishida formatlandi.

2. [x] **2. Backend va mexanizm ishlash darajasini tahlil qilish hamda testlash** — STATUS: DONE
   - **Dalil (Proof):**
     - Pytest orqali 64 ta avtomatlashtirilgan test ishga tushirildi va barchasi muvaffaqiyatli o'tdi (`64 passed in 4.75s`).
     - Tizimning umumiy test o'tish vaqti 137 soniyadan 4.75 soniyaga qisqardi.
     - `inclusive_api.py` endpointiga normativ havolalarni kengaytirish (expansion) va bekor qilingan normalarni filtrlash (status filter) integratsiya qilindi.
     - Kechikish vaqti (latency) Reranker subsetini 32 dan 18 tagacha optimallashtirish hisobiga sezilarli kamaytirildi.

3. [x] **3. Huquqiy RAG texnikasini mukammallashtirish, soddalashtirish va ortiqchalarini tozalash** — STATUS: DONE
   - **Dalil (Proof):**
     - Takroriy embedding tarmog'i so'rovi olib tashlandi: Semantik kesh tekshiruvi uchun hisoblangan `query_vector` endi to'g'ridan-to'g'ri `HybridRetriever.retrieve(..., precomputed_query_vector=...)` ga uzatiladi va BGE-M3 ga qayta so'rov yuborilmaydi.
     - Sitata va tinish belgilari orasidagi noo'rin probellar (`...hisoblanadi [1] [2] .` -> `...hisoblanadi [1][2].`) `validator.py` da to'liq tozalanishi ta'minlandi va test bilan tasdiqlandi.
     - Ortiqcha va sun'iy nemischa terminlar ("subsumsiya", "tatbestand") tizim ko'rsatmalaridan tozalab soddalashtirildi, tabiiy o'zbek huquqiy tili tartibiga keltirildi.

4. [x] **4. Kompyuterni o'chirish (Power off computer)** — STATUS: DONE
   - **Dalil (Proof):** `systemctl poweroff` buyrug'i tizimga yuborildi.

5. [x] **5. Nogironlik huquqlari RAG uchun stress-test savollari (Batch B: s101..s200, 100 ta savol)** — STATUS: DONE
   - **Tavsif:** `data/golden_dataset/stress_work/batch_b.json` fayli 100 ta savol (84 ta in-scope, 16 ta out-of-scope) bilan barcha kvotalar va qat'iy qoidalarga asosan yaratildi.
   - **Dalil (Proof):** `data/golden_dataset/stress_work/batch_b.json` fayli yaratildi, har bir savol korpusdagi haqiqiy birliklarga va 3-8 so'zli verbatim iqtiboslarga asoslangan.

6. [x] **6. Nogironlik huquqlari RAG uchun stress-test savollari (Batch A: s001..s100, 100 ta savol)** — STATUS: DONE
   - **Tavsif:** `data/golden_dataset/stress_work/batch_a.json` fayli 100 ta savol (88 ta in-scope, 12 ta out-of-scope) bilan barcha kvotalar va qat'iy qoidalarga asosan yaratildi.
   - **Dalil (Proof):** `data/golden_dataset/stress_work/batch_a.json` fayli yaratildi (100 ta element, s001..s100), har bir savol korpusdagi tegishli birliklarga va 3-8 so'zli verbatim iqtiboslarga to'liq asoslangan.
7. [x] **7. Retrieval tizimini uchta tuzatish orqali yaxshilash** — STATUS: DONE
   - **Tavsif:**
     - 1+2. `src/retrieval/reranker.py`: `split_windows` sliding-window funksiyasi, `MAX_RERANK_UNITS=40`, `MAX_RERANK_DOCS=100`, barcha oynalar bo'yicha baholash va unitlar bo'yicha max relevance fuzioni.
     - 3. `src/nlp/query_translator.py`: `QueryTranslator` klassi (512 hajmli OrderedDict LRU kesh, OpenRouter chat_completion orqali ru/en so'rovlarini leksik jihatdan to'g'ri o'zbek tiliga tarjima qilish).
     - 4. `src/retrieval/pipeline.py`: `retrieve_contexts` da ru/en so'rovlar uchun dual retrieval va mutatsiyasiz `merge_candidates` funksiyasi.
     - 5. `tests/test_retrieval.py`: `test_split_windows`, `test_reranker_scores_beyond_18_and_sees_text_after_char_600`, `test_merge_candidates`, `test_query_translator_to_uzbek_mock_and_uz` testlari to'liq qo'shildi.

8. [x] **8. OpenRouter narx/sifat optimizatsiyalari (provider routing, quantization, reasoning nazorati, sodda rejim prompti)** — STATUS: DONE
   - **Dalil (Proof):**
     - 1) `src/config.py` va `.env.example`: `LLM_PROVIDER_ORDER`, `LLM_PROVIDER_QUANTIZATIONS`, `GENERATION_REASONING_EFFORT` sozlamalari pydantic Field va bir qatorli izohlar bilan qo'shildi.
     - 2) `src/clients/openrouter.py`: `provider_preferences(self)` metodi qo'shildi; `chat_completion` va `chat_completion_stream` ga `reasoning` parametri va json request'ga "provider" va "reasoning" maydonlari integratsiya qilindi.
     - 3) `src/nlp/query_translator.py`: `chat_completion` chaqiruviga `reasoning={"enabled": False}`, `max_tokens=300` berildi, tizim promptiga faqat lotin yozuvi talabi qo'shildi.
     - 4) `src/retrieval/pipeline.py`: rerank so'rovi uchun `uz_analysis.normalized_query` kiritildi.
     - 5) `src/generation/generator.py`: `generate_answer` (birlamchi va fallback) va `generate_answer_stream` ga `reasoning` parametri ulandi.
     - 6) `src/generation/prompts.py`: oddiy til rejimi (plain mode) matni 220 so'z chegarasi va yangi talablar bilan yangilandi.
     - 7) `tests/test_retrieval.py` va `tests/test_generation.py`: `NonMockClient` imzosi yangilandi, 4 ta yangi test (`test_query_translator_passes_reasoning_and_max_tokens`, `test_build_system_prompt_plain_word_limit`, `test_openrouter_provider_preferences`, `test_chat_completion_sends_provider_and_reasoning`) kiritildi.


