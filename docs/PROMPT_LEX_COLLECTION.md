# Agent uchun prompt: RAG bazasi uchun Lex.uz hujjatlarini yig'ish

Quyidagi matnni agentga (`mdo` / `gdo` yoki boshqa) to'liq bering. Ishchi papka: loyiha ildizi.

---

## VAZIFA

Sen "Inclusive Legal AI" loyihasi (O'zbekiston qonunchiligi bo'yicha RAG, nogironligi bo'lgan shaxslar huquqlari va ular bilan bog'liq hayotiy sohalar) uchun **rasmiy Lex.uz'dan** kerakli hujjatlarni bittalab topib, tekshirib, ro'yxatga olasan. Bu bosqichda hujjatlar **bazaga yuklanmaydi** (embedding yo'q). Natija: tekshirilgan nomzodlar ro'yxati + qo'shishga tayyor buyruqlar.

## QATTIQ QOIDALAR

1. **Manba faqat Lex.uz** (`https://lex.uz/...`). norma.uz, gazeta.uz, Telegram, Wikipedia yoki boshqa saytdan hujjat matni yoki raqam olinmaydi. Boshqa sayt faqat "qanday hujjat bor?" degan fikr uchun ishlatilishi mumkin, lekin har bir hujjat Lex.uz'da topilib tasdiqlanishi shart.
2. **Hech narsa to'qima.** `lex_id`, raqam, sana, nom faqat Lex.uz sahifasidan olingan bo'lsin. Topolmagan hujjatni "topilmadi" deb yoz, taxmin qilma.
3. **Bekor qilingan (kuchini yo'qotgan) hujjatlarni qo'shma.** Sahifa holati "amal qiladi" bo'lishi shart. Bekor qilingan bo'lsa, o'rniga kelgan hujjatni top.
4. **OpenRouter/embedding/LLM chaqirma**, `ingest`, `refresh --apply`, `add` buyruqlarini ishga tushirma. `data/store`, `.env` va jonli bazaga tegma. Hech narsani commit qilma.
5. Lex.uz'ga **sekin** murojaat qil (so'rovlar orasida kamida 1 soniya, mavjud `LexClient(min_delay=...)` ishlat). Bir vaqtda ko'p so'rov yuborma. Kesh `data/raw_lex` ishlatiladi.
6. Mavjud kod va fayllarni o'zgartirma. Faqat pastdagi chiqish fayllarini yoz. `TASKS.md` ga tegma.

## BOSHLASHDAN OLDIN O'QI

- `scripts/build_disability_corpus.py` (buyruqlar: `discover`, `select`, `cited`, `widen`, `domain`, `add`, `refresh`, `report`) va `src/ingestion/lex_client.py`, `src/ingestion/lex_structured.py`.
- `data/sources/disability_registry.json`: bazada **allaqachon bor** 387 akt (`lex_id`, `law_id`, `number`, `include`). Takrorlama.
- `data/sources/discovered.json`, `domain_candidates.json`, `seeds.json`: oldin topilgan nomzodlar.
- `data/sources/REGISTRY.md` (yoki `report` buyrug'i): hozirgi tarkib.

## NIMA YIG'ILADI (ustuvorlik tartibida)

**A. Kodekslar (to'liq, `include: all`)**: Soliq kodeksi (O'RQ-599, hozir faqat 16 modda bor), Fuqarolik kodeksi 2-qism (hozir 50), Ma'muriy javobgarlik, Jinoyat, Jinoyat-protsessual, Jinoyat-ijroiya, Bojxona, Budjet, Shaharsozlik (to'liqligini tekshir), Saylov. Mehnat, Fuqarolik 1-qism, Oila, Uy-joy, Yer kodekslari bazada bor: to'liqligini tekshir (moddalar soni Lex.uz'dagidan kam bo'lmasin).

**B. Ijtimoiy himoya va sog'liq qonunlari**: aholini ijtimoiy muhofaza qilish, pensiya ta'minoti, ijtimoiy xizmatlar, nogironligi bo'lgan shaxslar huquqlari (O'RQ-641 bazada bor), keksalar, oila va bolalar, sog'liqni saqlash, majburiy tibbiy sug'urta, dori vositalari, ta'lim to'g'risidagi qonun, inklyuziv ta'lim, bandlik, kvotalar, murojaatlar, bepul yuridik yordam, advokatura, davlat xizmatlari, ma'muriy tartib-taomillar.

**C. Hukumat qarorlari va farmonlari**: nogironlik guruhini belgilash (VTEK/MSEK) tartibi, reabilitatsiya texnik vositalari, nafaqa va kompensatsiyalar, kommunal va transport imtiyozlari, ijtimoiy reestr, ijtimoiy xizmatlar standartlari, ish o'rinlari kvotasi, ta'lim imtiyozlari. Faqat hozirda amal qiladiganlari.

**D. Xalqaro**: BMT Nogironlar huquqlari konvensiyasi va Fakultativ protokoli (Lex.uz'da e'lon qilingan nusxasi).

**E. Mavjud hujjatlarga tuzatish kiritgan aktlar**: bazadagi muhim aktlar (kodekslar, O'RQ-641 va h.k.) uchun Lex.uz'dagi "o'zgartirishlar/bog'liq hujjatlar" bo'limidan ularni o'zgartirgan aktlarni top, lekin faqat ularning o'zida mustaqil norma bo'lsa qo'sh (faqat "o'zgartirish kiritish" haqidagi aktlar kerak emas; qarang `_AMENDING_TITLE` `src/api/routes/corpus_admin.py` da).

## QANDAY ISHLASH KERAK

1. Avval bazadagi registrni o'qib, nimalar borligini aniqla. Har bir nomzod uchun takror bor-yo'qligini `lex_id` va `number` bo'yicha tekshir.
2. Nomzodlarni Lex.uz'dan topish yo'llari: (a) lex.uz "Kodekslar" va "Qonunlar" bo'limlari; (b) OKOZ klassifikatori tugunlari; (c) sarlavha/raqam bo'yicha qidiruv; (d) aktning "bog'liq hujjatlar" bo'limi; (e) `python scripts/build_disability_corpus.py cited` (Huquq+ maqolalari tayangan, bazada yo'q aktlar; tarmoqqa faqat Lex.uz'ga so'rov yuboradi, kredit sarflamaydi, ishga tushirishdan oldin kodni o'qib buni tasdiqla).
3. **Har bir hujjatni bittalab tekshir** (mavjud `LexClient` + `LexDocumentParser` bilan): `lex_id`, rasmiy nomi, raqami (O'RQ-…/PF-…/PQ-…/VMQ-…), qabul qilingan sana, holati (amal qiladi/bekor), birliklar (modda/band) soni, parser xatosi yoki bo'sh natija. Parser 0 ta birlik qaytarsa yoki birliklar soni shubhali kam bo'lsa (masalan, hammasi bitta "preambula" ichida), buni alohida belgilab, sababini yoz.
4. Har bir hujjat uchun bitta qaror: `ADD` (qo'shish kerak), `ALREADY` (bazada bor), `SKIP_REPEALED`, `SKIP_AMENDING_ONLY`, `SKIP_IRRELEVANT`, `NOT_FOUND`, `PARSE_PROBLEM`. Har bir `SKIP`/`PROBLEM` uchun bir qator sabab.
5. Har bir `ADD` uchun `include` ni tanla: kodekslar va qonunlar uchun `all`; ko'p mavzuli katta qarorlar uchun faqat tegishli bo'lim kerak bo'lsa `disability_articles`.
6. Qamrov bo'shliqlarini tekshir: `data/golden_dataset/stress_eval_200.json` dagi `expected_ids` va `note` lardan qaysi aktlar bazada yo'qligini chiqar (coverage gaps) va ularni ham nomzodga qo'sh.

## CHIQISH FAYLLARI (faqat shular)

1. `data/sources/collection_plan.json`: ro'yxat, har bir element: `lex_id`, `url`, `number`, `title`, `doc_type`, `adopted`, `status`, `units`, `group` (A/B/C/D/E), `decision`, `include`, `reason`, `verified_at`.
2. `data/sources/COLLECTION_PLAN.md`: odam o'qishi uchun qisqa hisobot: guruhlar bo'yicha jadval, jami nechta `ADD`, kutilayotgan birliklar soni, `PARSE_PROBLEM` ro'yxati, topilmaganlar.
3. `data/sources/add_commands.sh`: faqat `ADD` hujjatlar uchun, har biri alohida qatorda: `python scripts/build_disability_corpus.py add --lex-id=<id> --include=<all|disability_articles>`. **Ishga tushirma**, faqat yoz.

## TUGATISH MEZONI

- Har bir A guruhi kodeksi va B/C/D ro'yxati uchun qaror bor, hech biri taxminga asoslanmagan.
- `collection_plan.json` yaroqli JSON, `lex_id` lar takrorlanmaydi, bazadagi registr bilan to'qnashmaydi.
- Sen to'qimagansan: tanlab 10 ta yozuvni qayta tekshir (Lex.uz'dan qaytadan o'qib) va natijasini hisobotga yoz.

## HISOBOT FORMATI (oxirida, qisqa)

Nechta hujjat ko'rib chiqilgan, nechtasi `ADD`/`ALREADY`/`SKIP`/`PROBLEM`, taxminiy qo'shiladigan birliklar soni, yaratilgan fayllar, noaniq qolgan qarorlar va nima uchun.
