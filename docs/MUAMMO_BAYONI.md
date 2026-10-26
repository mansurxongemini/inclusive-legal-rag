# Muammo bayoni: oddiy odam tilidagi savollarga javob sifati (2026-10-26)

Bu hujjat boshqa mutaxassis yoki agentga topshirish uchun yozilgan: nima ishlaydi, nima ishlamaydi, nimalar sinalgan, nima ochiq qolgan.
Tokenlar, kalitlar va uchinchi tomon javoblari bu yerda yo'q.

## 1. Tizim

"HuquqPlus RAG": nogironligi bo'lgan shaxslar va ularning oilalari uchun O'zbekiston qonunchiligi bo'yicha savol-javob xizmati.
Telegram bot (aiogram) uni `/api/v1/assistant/*` orqali chaqiradi. Repo: `RAG base`, branch `agent/max-quality`.

Javob zanjiri (`src/gateway/service.py::answer_question`):
1. Savolni tozalash va til/yozuvni aniqlash (`QueryAnalyzer`), aniq va semantik kesh.
2. Qidiruv (`src/retrieval/pipeline.py`):
   - BM25 (SQLite FTS5, butun so'z prefikslari, 4 tagacha kichik so'rov) + lug'at (`src/nlp/legal_synonyms.py`, qo'lda yozilgan oddiy so'z -> qonun atamasi);
   - dense qidiruv: `qwen/qwen3-embedding-8b` (1024 o'lcham), SQLite + numpy, `src/storage/vector_store.py`;
   - RRF bilan birlashtirish, 40 nomzod, o'zaro havolalarni kengaytirish, holat filtri;
   - **reranker**: bitta arzon chat modeli 30 ta bo'lakni ko'rib, "qaysi bo'lak savolga eng aniq javob beradi" deb bitta tanlov qiladi (`src/retrieval/jev_ranker.py`, `llm_ranker.py`); oxirgi 8 ta kontekst;
   - qamrov darvozasi: "bu savol nogironlik huquqlari doirasidami" (yolg'on rad shu yerdan chiqadi).
3. Generator: `deepseek/deepseek-v4-flash-0731` (OpenRouter), prompt `src/generation/prompts.py` (oddiy til rejimi, 120-180 so'z), keyin da'volni manbaga qarshi tekshirish (`support_check.py`), manba raqamlari tekshiruvi.
4. Model ishlamasa yoki byudjet tugasa: halol 503 (modelsiz javob yo'q).

Korpus: faqat Lex.uz. 647 hujjatdan ~660 gacha, 30 402 modda (+ Huquq+ tahririyat postlari), 40 342 vektor satri. Qiyin cheklovlar: ishlab chiqarish chat va embedding modeli ruxsatsiz o'zgarmaydi; push yo'q; emoji yo'q;
byudjet cheklovi OpenRouter uchun (hozirgi sinov limiti: umumiy sarf $8, sarf $4.5 atrofida); server 2 vCPU, AVX-only.

## 2. Muammo

Egasi haqiqiy savol berdi: "Men 1-guruh nogironiman, yonimdagi yordamchiga bepul foydalanish huquqi bor" (xato bilan yozilgan, nimadan foydalanish aytilmagan).
Javob faqat "davlat idoralarida navbatsiz xizmat" (PQ-74, 5-band) normasiga tayandi va "ha, bepul foydalanasiz" deb boshlandi.
Raqib xizmat (Tuzuk AI) bir nechta norma keltirdi: shahar transportida bepul yurish (278-I qonun, PQ-266 9-band), poezd/avtobus bepul chipta (VMQ-733), navbatsiz xizmat (PQ-74).
Bizning bazada bularning hammasi **bor edi**, lekin birinchisi nomzod ro'yxatiga (40 ta) ham kirmadi.

Sabab: odam "yordamchi" deydi, qonun "hamrohlik qiluvchi shaxs" deydi. Chat modeli (so'rovni qayta yozish bosqichida) buni bilmaydi ("yordamchi xizmati" deb so'zma-so'z oldi), embedding ham uni yaqinlashtirmadi (kerakli modda dense ro'yxatda 249-o'rinda edi).

## 3. O'lchovlar (qaysi o'lchovga ishonish mumkin)

| To'plam | Ishonchlimi | hit@1 | hit@6 | Izoh |
|---|---|---|---|---|
| `eval/gold_set.jsonl` (76) | yo'q, 16 sikl davomida sozlangan | ~0.96 MRR | 0.97 recall@5 | haqiqatni oshirib ko'rsatadi |
| `data/golden_dataset/stress_eval_200.json` | qisman, sozlangan | 58.7 | 83.1 | |
| `data/golden_dataset/heldout_v1.json` (92, 55 xizmat doirasida) | **ha**, hech sozlanmagan (manifest sha256) | **58.2** | **76.4** | yolg'on rad 10.9% |
| `data/golden_dataset/lay200.json` (200, men yozdim) | raqib javoblari bilan taqqos uchun | - | - | oddiy tildagi savollar |

Raqib bilan taqqoslash (200 savol, 199 javob): raqib o'rtacha 1.7 hujjatga tayanadi (jami 339).
Bizda: 42% ni biz ham keltiramiz, 47% bizning bazada bor-u javobga tushmaydi, 11% bazada yo'q.
Mazmun bo'yicha (arzon model hakam, shovqinli): "to'liq/ko'pchiligi" 60%, "qisman" 35%, "yomon" 3%; 31 savolda faktlar zid (raqamlar, kimga tegishli).
Raqib javobi 2 barobar uzun (3441 va 1710 belgi), hakam uzunga moyil bo'lishi mumkin.

### Tuzuk hujjatlari qaysi bosqichda yo'qolmoqda (171 ta, korpusda bor-u keltirilmagan)
- 44%: 40 nomzodga kirmaydi (qidiruv topmaydi);
- 33%: nomzodda bor, reranker tashlaydi (ba'zilari 3-8-o'rinda);
- 20%: oxirgi kontekstda bor, generator javobda keltirmaydi;
- qamrov chegaralari (hujjat darajasida): barcha nomzodlarda 75.7%, Jev oynasida (30) 67.8%, oxirgi 8 tada 53.5%.

### Embedding va BM25 (161 savol, oddiy savol matni, hujjat darajasida eng yaxshi bo'lak o'rni)
| Birinchi N | dense | BM25 | ikkalasi |
|---|---|---|---|
| 10 | 42% | 27% | 52% |
| 40 | 66% | 47% | 77% |
| 100 | 77% | 61% | 85% |
| 300 | 89% | 77% | 96% |

Xulosa: embedding BM25 dan kuchli, lekin Tuzuk hujjatlarining 34% ini birinchi 40 ga qo'ymaydi.

## 4. Sinalgan va ISHLAMAGAN yo'llar (qayta sinab ko'rishdan oldin o'qing)

| Yo'l | Natija |
|---|---|
| Hamma savolga (8+ so'z) model bilan kichik savollarga ajratish | hit@1/3/6 va MRR 3-5 punktga tushdi |
| Nomzod havzasi 60 + Jev oynasi 45 | stress +5 punkt, **hech sozlanmaganda hit@1 58.2 -> 49.1**: stress'dagi yutuq moslashtirish edi |
| Faqat oyna 30 -> 45 | hech sozlanmagan to'plamda hit@1 63.6 -> 58.2, hit@6 87.3 -> 80.0 |
| Oxirgi kontekstlar 8 -> 12, oxirgi o'rinlar yangi hujjatlarga | kontekstda 53.5 -> 62.5%, lekin javobda keltirish 42 -> 43% |
| Generatorga "har bir alohida normani keltir" qoidasi | keltirish 44%, hakam bali 1.62 -> 1.57 (yaxshilanmadi) |
| Embedding so'rov ko'rsatmasi (Qwen "Instruct:") | yomonlashdi (`docs/EMBEDDING_COMPARISON.md`) |
| Rerankerning dumini RRF tartibida qoldirish | Jev tartibi dumda ham signal beradi, yomonlashdi |
| 19 yangi hujjat (984 modda) qo'shish | hech sozlanmagan to'plam o'zgarmadi, keltirish 41 -> 42% |

Hamma tajribalar kodi qaytarilgan (`DECISIONS.md`, 2026-10-26). Umumiy tamoyil: **nomzod qancha ko'p bo'lsa, hozirgi arzon reranker shuncha ko'p adashadi.**

## 5. Foydali kichik muvaffaqiyatlar (commit `17cfb3a`)
- Lug'atga "yordamchi/hamroh/kuzatuvchi" -> "hamrohlik qiluvchi shaxs"; shu atamalar kichik savollarga ajratish bosqichiga ham beriladi.
- Javobning havolasiz birinchi gapi (masalan "ha, bepul") endi keltirilgan normalarga qarshi tekshiriladi (`support_check.split_claims`), ma'qullanmasa bir marta qayta yoziladi. Egasining savolida "bepul" iborasi yo'qoldi, oxirida aniqlashtiruvchi savol chiqadi.

## 6. Ochiq farazlar (tekshirilmagan)

1. **Reranker modeli zaif bo'g'in.** Kuchliroq model (masalan Claude Haiku 5.5 ~$0.0013 bir chaqiruv, yoki Gemini/GPT mini) kengroq oynani ko'tarishi mumkin. O'lchanmagan.
2. **Embedding.** Boshqa model (voyage-4, nemotron-embed-8b:free, pplx-embed-4b, qwen3-4b) dense ro'yxatda 34% yo'qotishni kamaytirishi mumkin. Korpusni qayta embedding qilish ~$0.1-0.8.
3. **Savolni tushunish (so'rovni qayta yozish)** modeli o'zbek huquqiy atamalarini bilmaydi. Variantlar: korpus ichidan o'rganish (birinchi qidiruvdan keyin atamani topib qayta qidirish, PRF), Huquq+ posttarini (oddiy tilda yozilgan, normalarga bog'langan) lay -> qonun atamasi juftliklari manbai sifatida ishlatish.
4. **Botdagi haqiqiy savollar** (3 yil, 8000+ savol-javob, volontyor javobi va norma havolasi bilan) eng yaxshi sinov to'plami va atama manbai bo'lishi mumkin. Hali olinmagan; shaxsiy ma'lumotdan tozalash shart; repoga qo'shilmaydi.
5. **Raqamlar eskirishi.** Nafaqa miqdorlari bo'yicha zidlik: biz 2023-yilgi PF-196 dan 648 000 so'mni keltirdik, raqib boshqa miqdor yozdi. Qaysi hujjat yangi ekanini tanlash qoidasi yo'q (`status` va `amendment_history` bor, lekin miqdorlar bo'yicha "so'nggi" tanlanmaydi).
6. **Qamrov siyosati.** Yolg'on rad 10.9%: oila/boshqa huquq savollari rad etiladi (`GATE_JEV_MIN_IN_SCOPE=0.2`, `src/retrieval/jev_ranker.py::SCOPE_QUESTION`). Bu mahsulot qarori, texnik xato emas.
7. **Beqarorlik.** Bir savol, ikki yurish: ~10% savolda keltirilgan hujjatlar keskin farq qiladi (provayder, kvantlash, temperatura 0 bo'lsa ham). Keshda birinchi javob qoladi. Oraliq model chaqiruvlarini (qayta yozish, reranker) kalit bo'yicha keshlash tavsiya etiladi.
8. **Provayder cheklovi.** `deepseek` chat chaqiruvlari ko'p HTTP 429 beradi; sinovlarni buzadi, jonli xizmatda ham sekinlashtirishi mumkin. Sinovlarda parallellik 2 dan oshmasin.

## 7. Takrorlash vositalari

- Hech sozlanmagan to'plam (retrieval-only, ~$0.07-0.10): `python scripts/stress_eval.py --dataset data/golden_dataset/heldout_v1.json --retrieval-only --no-judge --profile prod --concurrency 2 [--store-dir <nusxa>]`
- Tuzatishni solishtirish tartibi: bir xil kod, eski va yangi baza/model, **parallellik 2**, logda "429" sonini tekshirish (253 xato bilan buzilgan yurish soxta -18 punkt ko'rsatgan edi).
- Reranker javoblarini bir marta yozib olib, tanlash qoidalarini offlayn (bepul) sinash: `data/lay_eval/capture.py` va `sim.py` (git'da ignore qilingan papka `data/lay_eval/`).
- Zaxira: `python scripts/backup_store.py --dest data/backups`; hujjat qo'shish: `scripts/build_disability_corpus.py add --lex-id=... ` va `refresh --law-ids=...` (minus bilan boshlanuvchi id uchun `--law-ids=` shaklida).
- Hujjat identifikatori: Lex.uz lotin nashri manfiy son, rus nashri musbat; solishtirishda `law_id` bo'yicha moslang.

## 8. Tuzoqlar

- Oltin to'plam va stress to'plamidagi yaxshilanish ishonchsiz: har doim hech sozlanmagan to'plamda tasdiqlang.
- `/tmp` va vaqtinchalik papkalar qayta yoqishda tozalanadi: natijalarni loyiha ichidagi ignore qilingan papkaga yozing.
- Raqib javoblarini repoga qo'shmang (boshqa kompaniya mahsuloti); ularning tokenini hech qaerga yozmang.

## 9. Agentlarga bo'linish uchun taklif (4 ish oqimi)

1. **Embedding:** 3-4 nomzodni alohida vektor bazasi nusxasida sinash (Tuzuk hujjatlari birinchi 40 da ulushi, hech sozlanmagan to'plam).
2. **Savolni tushunish va so'z qidiruvi:** korpusdan atama o'rganish (PRF yoki Huquq+ postlaridan), BM25 so'rov qurilishi; haqiqiy savollar olinsa, undan.
3. **Reranker:** modellarni solishtirish va oyna/kontekst o'lchamini ularning kuchiga moslash; chaqiruvlarni keshlash.
4. **Javob to'liqligi va yangiligi:** bir necha huquqli savollarda to'liq javob, miqdorlar uchun "so'nggi hujjat" qoidasi, qamrov siyosati bo'yicha taklif.

Har oqim uchun muvaffaqiyat mezoni: hech sozlanmagan to'plamda hit@1 va hit@6 pasaymasin, oddiy tildagi savollarda Tuzuk hujjatlarini keltirish ulushi (hozir 42%) va hakam bali oshsin.
