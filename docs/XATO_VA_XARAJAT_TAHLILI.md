# Bot qayerda xato qiladi, pul qayerga ketadi va qanday qilib "arzon + kuchli" bo'ladi

*Tahlil sanasi: 2026-10-12. Bu hisobot faqat tahlil — loyiha kodiga hech qanday o'zgartirish kiritilmagan.*

---

## 0. Qisqa xulosa (1 daqiqada)

1. **Bitta savolga javob o'rtacha $0.0052 turadi** (11 ta real so'rovda OpenRouter hisobidan o'lchandi). Pulning **57% i reranker**ga (Cohere rerank-4-pro), **31% i javob yozish**ga, **12% i ruscha/inglizcha savolni tarjima qilish**ga ketyapti. Embedding (vektor) xarajati deyarli nol.
2. **Eng katta behuda sarf — tarjima qadami.** Bitta gapni tarjima qilish uchun "o'ylaydigan" (reasoning) model 2000 tokengacha o'ylab, **bo'sh javob** qaytaryapti, pul esa baribir olinadi. Natijada ru/en savolda tarjima javobning o'zidan qimmat ($0.0017 vs $0.0016) va ~13 soniya kechikish qo'shadi.
3. **Bir xil model uchun narx 5–10 barobar farq qilyapti**, chunki OpenRouter har safar boshqa provayderni tanlaydi (ba'zilari modelni fp4 ga siqib ishlatadi — sifat xavfi). Keshdan (prompt caching) foydalanish 0%.
4. **Xatolar endi asosan javob yozish bosqichida:** 172 ta savoldan 21 tasi to'liq to'g'ri emas — 9 tasida kerakli modda topilmagan, 12 tasida modda topilgan, lekin javob muhim shartni tushirib qoldirgan, umumiy yozilgan yoki boshqa hujjatdagi raqamni olgan. Eng zaif joylar: **xalqona so'zli savollar** (top-3 da topish 62.5%), **ikki hujjatni talab qiladigan savollar**, **sohaga yaqin, lekin bazada yo'q savollar**.
5. **Yirik huquqiy AI'lar ham xato qiladi:** Stanford tadqiqotida Lexis+ AI 17%, Westlaw AI 33% holatda gallyutsinatsiya qilgan. Ular sifatni **o'z korpusi + iqtibos tekshiruvi + vazifaga qarab model tanlash** bilan, xarajatni esa **kesh, model kaskadi/marshrutlash, kontekstni qisqartirish** bilan boshqaradi.
6. **Taxminiy salohiyat:** tavsiyalar bajarilsa, bir savol narxi **$0.0052 → ~$0.0015–0.0025** ga tushishi, ru/en kechikishi ~13 soniyaga qisqarishi va sifat (top-3) 88% dan 92%+ ga chiqishi mumkin. Bu **baho**, har bir qadam stress-test bilan o'lchanishi shart.

---

## 1. Ma'lumot qayerdan olindi

| Manba | Nima o'lchandi |
|---|---|
| 200 savolli stress-test (`data/golden_dataset/stress_eval_200.json`) — 2 marta: tuzatishdan oldin va keyin | qidiruv sifati (hit@k, MRR), rad etishlar, LLM-hakam bahosi, kechikish |
| Eski golden to'plam (63 savol) | regressiya |
| 11 ta real so'rov, har bir API chaqiruvi yozib olindi | token soni, reasoning tokenlari, **OpenRouter qo'ygan haqiqiy narx**, kechikish |
| OpenRouter narx ro'yxati (model va provayderlar bo'yicha) | provayderlar orasidagi narx farqi, kesh narxi |
| Ochiq manbalar (oxirida ro'yxat) | yirik huquqiy AI'lar va xarajat kamaytirish usullari |

Muhim ogohlantirish: LLM-hakam bahosi kichik guruhlarda ±15% tebranadi (bir xil kontekstda qayta baholanganda ruscha "to'g'ri" 100% → 81%). Shuning uchun asosiy xulosalar qidiruv metrikalari va haqiqiy hisob-kitob raqamlariga tayanadi.

---

## 2. Bot qayerda va nima sababdan xato qiladi

### 2.1. Xato zanjiri: savol → javob

```
Savol → [tushunish/tarjima] → [qidiruv: BM25 + vektor] → [reranker] → [filtr (gate)] → [javob yozish] → [iqtibos tekshiruvi]
           12% pul, 13 s        deyarli bepul              57% pul      bepul           31% pul           bepul
```

Tuzatishlardan keyingi holat (172 ta bazadagi savol):

| Natija | Soni | Ulushi |
|---|---|---|
| To'liq to'g'ri (hakam) | 151 | 87.8% |
| Kerakli modda **topilmagan** → javob yomon | 9 | 5.2% |
| Modda **topilgan**, lekin javob to'liq emas yoki xato | 12 | 7.0% |
| Asossiz rad etish | 0 | 0% |

Demak, endi **xatolarning ko'pi javob yozish bosqichida**: qidiruv o'z ishini 92% holatda bajaryapti (kerakli modda 6 ta kontekst ichida).

### 2.2. Qidiruv (retrieval) xatolari — nima sababdan

| Muammo | Raqam | Sabab |
|---|---|---|
| **Xalqona so'zlar** ("to'shakka mixlangan", "tekin yotoqxona") | top-3: 62.5%, hovuzda: 75% | Qonun matnida bunday so'zlar yo'q. BM25 so'zma-so'z qidiradi, vektor qidiruv esa yordam bergan bilan uni yetarli darajada qoplay olmayapti. Sinonim lug'ati faqat BM25 uchun ishlaydi va kichik. |
| **Ikki hujjatni talab qiladigan savollar** | barcha kerakli moddalar kontekstda: 53.8% | Savol qismlarga qoidaga asoslanib (regex) bo'linadi va faqat BM25 uchun. Har bir qism uchun kamida bitta modda kontekstga tushishi kafolatlanmagan. |
| **Vaziyatli va noto'g'ri asosga qurilgan savollar** | top-1: 36–60% | Uzun hikoya ichida huquqiy savol yashirin qoladi. Hikoya so'rov sifatida to'g'ridan-to'g'ri qidiruvga beriladi, avval "huquqiy savolga aylantirilmaydi". |
| ~~Reranker faqat 18 ta nomzodni va 600 belgini ko'rardi~~ | **tuzatildi**: top-3 72.7% → 88.4% | — |
| ~~Ruscha savol o'zbekcha moddani topa olmasdi~~ | **tuzatildi**: ruscha top-3 37.5% → 93.8% | — |

### 2.3. Javob yozish (generatsiya) xatolari — nima sababdan

12 ta "modda topilgan, lekin javob yomon" holatda hakam bergan teglar: *shart tushib qolgan* (6), *gallyutsinatsiya* (4, ulardan bir qismi hakam xatosi ekani qo'lda tasdiqlangan), *juda umumiy* (3), *raqam yo'q yoki noto'g'ri* (4).

Asosiy sabablar:

1. **Javoblar juda uzun va asosiy fikr ko'milib qoladi.** Javobning median uzunligi **2 477 belgi** (maksimal 6 119). Prompt "avval asosiy javob, keyin shartlar" deydi. Lekin modelga 6 ta to'liq modda (har biri 7 000 belgigacha) beriladi, u esa hammasini qayta hikoya qiladi. Natijada savolning aynan javobi (masalan, "faqat PTPK rad eta oladi" — s045, s148) tushib qoladi.
2. **Kontekstda "shovqin" ko'p.** Kerakli moddadan tashqari 5 ta yarim-tegishli modda ham yuboriladi. Model ba'zan boshqa hujjatdagi sana yoki raqamni oladi. Masalan, s005 da kutilgan 2027-yil o'rniga boshqa qarordagi 2025-yil sanasi olingan.
3. **"Eng yangi hujjat ustun" qoidasi xato qo'llaniladi.** Prompt "eng yangi aktga tayan" deydi, lekin aktlar har doim bir masalani tartibga solmaydi. Model turli masalalarga oid normalarni "ziddiyat" deb qabul qilib, noto'g'ri tanlashi mumkin.
4. **Kontekstda bor ma'lumotni "yo'q" deyish** (s059, s151). Model uzun matnda kerakli joyni topa olmay, xavfsiz tomonga — "hujjatlarda ko'rsatilmagan" deb — o'tadi.
5. **Ortiqcha shart qo'shish.** Masalan, s075 da kontekstda yo'q "I va II guruh" sharti qo'shilgan. Validator faqat iqtibos ID'larini tekshiradi; javobdagi **raqam, sana va shartlar** kontekstda borligini tekshirmaydi.

### 2.4. Sohadan tashqari (OOS) savollar

| Ko'rsatkich | Oldin | Keyin |
|---|---|---|
| Filtr to'xtatdi (barcha OOS) | 42.9% | 32.1% |
| Filtr to'xtatdi (sohaga yaqin huquqiy savollar) | 25% | 8.3% |
| Yakuniy javob to'g'ri (model o'zi rad etdi/yo'naltirdi) | 92.9% | 92.9% |

**Sabab:** filtr reranker balli ≥ 0.70 ga qaraydi. Sohaga yaqin savol (masalan, oddiy homiladorlik ta'tili) ham yuqori ball oladi (0.94), chunki Mehnat kodeksining tegishli moddalari korpusda bor. Ballar aralash: chegarani ko'tarsak, to'g'ri savollar ham rad etiladi. Hozir xavfsizlikni amalda **javob yozuvchi model** ta'minlayapti — bu qimmat (to'liq generatsiya puli to'lanadi) va ishonchsiz (28 tadan 2 tasida baribir javob berilgan).

**Strategik masala:** maqsad "istalgan murakkab savolga javob" bo'lsa, korpusda hozir faqat nogironlikka oid 238 ta akt (3 843 birlik) bor. Kodekslardan faqat nogironlikka oid moddalar olingan: Mehnat kodeksidan 50 ta, Soliq kodeksidan 16 ta, Oila kodeksidan 3 ta modda. Shuning uchun bot bunday savollarga yo halol rad etadi, yo qisman javob beradi. Masalan, s187 da model homiladorlik ta'tili moddasiga havolani topgan, lekin ta'tilning o'zi haqidagi 404-modda korpusda yo'q.

### 2.5. Infratuzilma xatolari (ko'rinmaydi, lekin sifat va pulga ta'sir qiladi)

| Muammo | Dalil | Ta'siri |
|---|---|---|
| **Reasoning model "o'ylashga" barcha tokenni sarflaydi** | tarjimada 7 chaqiruvdan 3 tasida 2000/2000 token reasoning, javob bo'sh | pul to'lanadi, 1 s kutib qayta urinadi, keyin zaxira modelga (Llama-3.3-70B, o'zbek tilida zaifroq) o'tadi |
| **Provayder ruleti** | bir xil model, narx 1k token uchun $0.0001–$0.0005 (5×); ro'yxatda 30+ provayder, ba'zilari **fp4** | narx va sifat har so'rovda tasodifiy; javob sifatining tebranishiga hissa qo'shishi mumkin |
| **Prompt keshi ishlamaydi** | barcha 17 chaqiruvda `cached_tokens = 0` | doimiy tizim prompti (~1 000 token) har safar to'liq narxda (kesh narxi 50× arzon) |
| **Kechikish** | o'zbekcha median 11.2 s, ru/en 16–18 s | generatsiya ~9 s, reranker ~1.7 s, tarjima ~13 s (bo'sh javoblar sababli) |
| **Inclusive endpoint'da semantik kesh yo'q** | `/query` da bor, `/inclusive/query` da faqat aynan bir xil matn keshi | qayta-qayta beriladigan savollar (FAQ) har safar to'liq narxda |

---

## 3. Pul qayerga ketyapti (o'lchangan)

11 ta real so'rov (7 o'zbekcha, 3 ruscha, 1 inglizcha), production yo'li, OpenRouter qo'ygan haqiqiy narx:

| Qadam | Model | Bir so'rovga | Ulush | Izoh |
|---|---|---|---|---|
| Reranker | cohere/rerank-4-pro | **$0.00295** | **57%** | 1 "search unit" = $0.0025 (100 hujjatgacha); 100 dan ortiq bo'lak bo'lsa 2 unit = $0.005. 20 ta hujjat yuborilsa ham to'liq 1 unit to'lanadi. |
| Javob yozish | deepseek-v4.1-flash | **$0.00163** | 31% | kirish median 4 736 token, chiqish median 1 433 token, chiqishning **34% i reasoning** |
| Tarjima (faqat ru/en) | deepseek-v4.1-flash (+Llama zaxira) | **$0.00172** ru/en savolga | 12% (umumiy) | 7 chaqiruvdan 3 tasi bo'sh; jami 52 s |
| Embedding | baai/bge-m3 | $0.000001 | ~0% | — |
| **Jami** | | **$0.0052** | 100% | |

**Miqyosda (hozirgi narx bilan):**

| Kuniga savol | Oyiga xarajat |
|---|---|
| 1 000 | ≈ $156 |
| 10 000 | ≈ $1 560 |
| 100 000 | ≈ $15 600 |

### Nega shunchalik qimmat — ildiz sabablar

1. **Reranker har bir savolda, eng qimmat versiyada ishlaydi.** Oson savolda ham (BM25 va vektor qidiruv bir xil moddani 1-o'ringa qo'ygan bo'lsa ham) $0.0025 to'lanadi.
2. **Modelga keragidan ko'p matn beriladi.** 6 ta modda × 7 000 belgigacha. Reranker allaqachon har bir moddaning **qaysi bo'lagi** savolga mos ekanini biladi, lekin modelga butun modda yuboriladi.
3. **Reasoning hamma joyda "high" darajada.** Tarjima kabi oddiy ishda ham. Model `low` darajani qo'llab-quvvatlaydi, lekin u ishlatilmayapti.
4. **Provayder tanlanmagan.** Ro'yxat narxi kirish uchun $0.30/1M, rasmiy DeepSeek provayderida $0.15/1M (2× arzon) va kesh bor. Hozir har safar tasodifiy provayder tanlanadi.
5. **Javob uzun** (median ~2 500 belgi). Chiqish tokeni kirishdan 4× qimmat ($1.20 vs $0.30 / 1M).
6. **Qayta urinishlar** (bo'sh javob → yana urinish → zaxira model) yashirin ikki-uch barobar xarajat.

---

## 4. Yirik huquqiy AI'lar qanday ishlaydi

### 4.1. Sifat: ular ham mukammal emas

- **Stanford tadqiqoti (Magesh va boshq., 2024/2025)** — 200 dan ortiq oldindan ro'yxatga olingan huquqiy savolda: **Lexis+ AI 17%, Westlaw AI-Assisted Research 33%** holatda gallyutsinatsiya qilgan (umumiy GPT-4 — 43%). Aniq javoblar ulushi: Lexis+ AI 65%, Westlaw 42%. Xulosa: "gallyutsinatsiyasiz" degan reklama oshirib yuborilgan. RAG xatoni kamaytiradi, lekin yo'q qilmaydi.
- **Thomson Reuters CoCounsel / Westlaw** — o'z yopiq korpusi ustida RAG; javobda har bir da'vo **bosiladigan iqtibos** bilan beriladi; KeyCite iqtiboslar eskirgan-eskirmaganini tekshiradi; "Deep Research Verify" har bir huquqiy da'voni manba qo'llab-quvvatlashini tekshiradi. Murakkab ishlarda "inson nazoratda" (human-in-the-loop) — tizim muhim qarorlarda to'xtab, foydalanuvchidan so'raydi.
- **Harvey** — 2025-yildan **ko'p modelli arxitektura**: har bir vazifa uchun o'z benchmarki (BigLaw Bench) bo'yicha eng yaxshi model avtomatik tanlanadi (masalan, bir model hujjat tuzishda kuchli, boshqasi sudga tayyorgarlikda). O'z maxsus huquqiy modelidan voz kechgan: umumiy frontier modellar uni benchmarkda ortda qoldirgan.

**Bizga saboq:** (1) o'z mustaqil o'lchovingiz bo'lmasa, sifat haqida gapirib bo'lmaydi — bizda bu bor (200 savol), uni kengaytirish kerak; (2) iqtibosni tekshirish yetarli emas, **da'vo ↔ manba** mosligini tekshirish kerak; (3) bitta model hamma ish uchun eng yaxshisi emas.

### 4.2. Xarajat: isbotlangan usullar

| Usul | Mohiyati | Manbadagi natija |
|---|---|---|
| **Model kaskadi** (FrugalGPT) | Avval arzon model; javob ishonchsiz bo'lsa qimmatiga o'tiladi | eng yaxshi model sifatida **98% gacha arzon** (eng yaxshi holat; o'rtacha kamroq) |
| **Marshrutlash** (RouteLLM) | Savol murakkabligiga qarab kuchli yoki arzon model tanlanadi | GPT-4 sifatining 95% ida **35–85% arzon** (benchmarkka qarab) |
| **Prompt keshi** | Doimiy qism (tizim prompti, hujjat) keshlanadi | xarajat **90% gacha**, kechikish 2× gacha kamayadi (Anthropic) |
| **Semantik kesh** | Ma'nosi o'xshash savolga oldingi javob qaytariladi | ilmiy tadqiqotlarda so'rovlarning **45–69%** i keshdan; to'g'ri javob aniqligi ~97% |
| **Contextual Retrieval** | Har bir bo'lakka hujjat kontekstidan qisqa izoh qo'shib indekslash | topilmay qolish **49% kam**, reranker bilan **67% kam** (Anthropic) |
| **Reranker → kam kontekst** | Faqat eng mos bo'laklar modelga beriladi | kam token = arzon va tez, model chalg'imaydi |
| **Batch narx** | Real vaqt talab qilmaydigan ishlar (baholash, FAQ oldindan tayyorlash) | OpenRouter'da DeepSeek `:batch` ~**60% arzon** |

---

## 5. Bu loyiha uchun tavsiyalar (ta'sir/kuch nisbati bo'yicha)

Har bir qadamdan keyin `scripts/stress_eval.py` qayta ishga tushiriladi: **sifat pasaymasa va narx tushsa — qabul**. Narx ham metrika sifatida o'lchanishi kerak (so'rov boshiga $).

### A. Tez yutuqlar (1–3 kun, kod o'zgarishi kichik)

| # | Nima qilish | Kutilgan ta'sir (baho) | Xavf |
|---|---|---|---|
| A1 | **Tarjimada reasoning'ni o'chirish** (yoki `low`), javob limiti ~200 token; yoki tarjimani reasoningsiz arzon modelga berish | tarjima narxi ~$0.0017 → ~$0.0001; ru/en kechikishi **~13 s ga qisqaradi**; bo'sh javoblar yo'qoladi | deyarli yo'q |
| A2 | **Provayderni belgilash**: rasmiy DeepSeek yoki DeepInfra (fp8+), fp4 provayderlarni chiqarib tashlash; `sort: price` faqat ruxsat etilganlar ichida | generatsiya **~2× arzon**; narx va sifat barqaror; prompt keshi ishlay boshlaydi | provayder ishlamay qolsa — zaxira ro'yxat kerak |
| A3 | **Reranker'ni har doim ≤100 bo'lakda ushlash** (2 unit to'lamaslik) va `rerank-4-fast` ($0.002) ni stress-testda sinash | reranker **−20…−35%** | fast versiya sifati o'lchanishi shart |
| A4 | **Javob uchun reasoning darajasi `low`**, oddiy rejimda javob uzunligini cheklash (~150–250 so'z, "Batafsil" tugmasi bilan) | chiqish tokeni **−40…−60%**; javob aniqroq, asosiy fikr birinchi | murakkab savollarda sifat — stress-test bilan tekshirish |
| A5 | **Semantik keshni inclusive endpoint'ga ham ulash** (kod `/query` da tayyor) | takroriy savollarda xarajat 0 va javob <100 ms; real ulush trafikka bog'liq (adabiyotda 20–45%) | o'xshashlik chegarasi juda past bo'lsa noto'g'ri javob — 0.93 dan boshlash |

### B. O'rta muddat (1–2 hafta)

| # | Nima qilish | Nima uchun |
|---|---|---|
| B1 | **Bitta arzon "savolni tushunish" qadami** (reasoningsiz): savolni o'zbekcha huquqiy tilga qayta yozadi, kerak bo'lsa tarjima qiladi, sub-savollarga bo'ladi, "soha ichida/tashqarisida" deb belgilaydi | Bir chaqiruv uchta muammoni yopadi: **xalqona so'zlar** (62.5%), **multi-hop** (53.8%) va **OOS filtr**. Tarjima chaqiruvining o'rnini egallaydi, shuning uchun qo'shimcha xarajat deyarli yo'q. |
| B2 | **Modelga butun modda emas, reranker tanlagan eng mos bo'laklarni berish** (+ modda sarlavhasi, akt nomi va sanasi); past balli kontekstlarni tashlab yuborish | Kirish tokeni **−40…−60%**, model chalg'imaydi (s005 kabi boshqa hujjatdan raqam olish kamayadi) |
| B3 | **Reranker'ni shartli ishlatish:** BM25 va vektor qidiruv bir xil moddani aniq farq bilan 1-o'ringa qo'ysa, rerank o'tkazib yuboriladi; aks holda ishlatiladi | Reranker — eng katta xarajat (57%). Uning ulushini kamaytirishning yagona yo'li — kamroq chaqirish. Qancha savolda o'tkazib yuborish mumkinligi stress-testda o'lchanadi. |
| B4 | **Javobdagi raqam/sana/foizlarni deterministik tekshirish:** javobdagi har bir raqam iqtibos qilingan modda matnida bo'lishi shart, bo'lmasa javob qayta yoziladi yoki belgilanadi | Bepul (LLM chaqiruvisiz). "Ortiqcha shart" va "boshqa hujjat raqami" xatolarini ushlaydi. Thomson Reuters'ning "har bir da'voni manba bilan tekshirish" g'oyasining arzon versiyasi. |
| B5 | **Model marshrutlash:** oddiy (bitta fakt, raqam) savollar → arzon model; vaziyatli, multi-hop, taqqoslash → kuchliroq model yoki reasoning `high` | Stress-testda qaysi turdagi savolda qaysi model yetarli ekani ko'rinadi (RouteLLM/Harvey yondashuvi) |
| B6 | **FAQ javoblarini oldindan tayyorlash** (eng ko'p beriladigan 200–500 savol, `:batch` narxida, huquqshunos tekshiruvi bilan) | Eng ko'p trafik eng arzon va eng ishonchli bo'ladi |

### C. "Top" darajaga chiqish uchun strategik ishlar

| # | Nima qilish | Nima uchun |
|---|---|---|
| C1 | **Korpusni kengaytirish** (faqat Lex.uz'dan, mavjud `build_disability_corpus.py` tamoyili bilan): Mehnat, Soliq, Oila, Fuqarolik kodekslari, pensiya va ijtimoiy ta'minot qonunchiligi to'liq | "Istalgan murakkab savol" sohaga yaqin savollarni ham o'z ichiga oladi; hozir ular rad etiladi yoki qisman javob beriladi |
| C2 | **Contextual Retrieval:** har bir birlikka indekslashda akt nomi, bob, maqsadi haqida 1–2 gaplik kontekst qo'shish (bir martalik xarajat, `:batch` + kesh bilan arzon) | Topilmay qolish ~49% kam (Anthropic). Ayniqsa VMQ ilovalaridagi "N-band" kabi kontekstsiz bo'laklar uchun foydali |
| C3 | **Murakkab savollar uchun agentli qidiruv:** sub-savol → qidiruv → yetishmayotgan narsani aniqlash → yana qidiruv → sintez; faqat B1 "murakkab" deb belgilagan savollar uchun | Multi-hop va vaziyatli savollar uchun; oddiy savollar arzon yo'ldan ketadi (kaskad) |
| C4 | **Baholash tizimini professional darajaga chiqarish:** 200 savolni huquqshunoslar (HuquqPlus) bilan 500+ ga yetkazish; hakam = kuchliroq model + 2 marta baholash; har oy tasodifiy 50 javobni inson tekshiradi; `/feedback` ma'lumotlarini yangi test savollariga aylantirish | Stanford tadqiqoti ko'rsatdiki, mustaqil o'lchovsiz "gallyutsinatsiyasiz" degan da'vo ishonchsiz. Har bir o'zgarish = sifat + narx o'lchovi. |
| C5 | **Ochiq sifat hisoboti** (hit@k, to'g'ri javob %, rad etish %, so'rov narxi) | Ishonch va grantlar uchun; xalqaro hamkorlar (BMT) uchun kuchli dalil |

### D. Taxminiy natija (barcha A + B bajarilsa)

| Ko'rsatkich | Hozir | Maqsad (baho) | Hisob |
|---|---|---|---|
| Bir savol narxi (keshsiz) | $0.0052 | **~$0.0020–0.0025** | reranker ~$0.0015 (fast + shartli) + generatsiya ~$0.0006 (provayder 2×, kontekst −50%, chiqish −40%) + tushunish qadami ~$0.0001 |
| Bir savol narxi (kesh 30% bilan) | — | **~$0.0015** | kesh urilgan savollar ~0 |
| Oyiga 1 000 savol/kun | ≈ $156 | **≈ $45–75** | |
| ru/en kechikishi (median) | 16–18 s | **~8–10 s** | tarjimadagi bo'sh javoblar yo'qoladi, chiqish qisqaradi |
| Top-3 da topish | 88.4% | **92%+** | B1 (xalqona so'zlar, multi-hop) |
| Hakam bo'yicha to'g'ri javob | 87.8% | **92%+** | B2 + B4 |
| Sohaga yaqin OOS'ni to'g'ri ushlash | filtr 8%, model 92.9% | **filtr 70%+** | B1 tasnifi; arzonroq (generatsiyasiz rad etish) |

> Bu raqamlar **baho**. Ular o'lchangan narx va tokenlardan hisoblangan, lekin har bir tavsiya stress-test bilan tasdiqlanmaguncha natija emas.

---

## 6. Tavsiya etiladigan tartib

1. **A1 → A2 → A4** (bir kunda; eng katta behuda sarfni yopadi) → stress-test.
2. **A3 + A5** → stress-test (reranker modeli tanlovi).
3. **B1 + B2** (sifat va narx bir vaqtda yaxshilanadi) → stress-test.
4. **B4, B3, B5, B6**.
5. **C1–C5** — "top" mahsulot uchun strategik reja.

---

## Manbalar

- Magesh va boshq., *Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools* — [Stanford PDF](https://nlp.stanford.edu/~manning/papers/Magesh-Hallucination%E2%80%90Free-2025.pdf); qisqacha: [Stanford HAI](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)
- Thomson Reuters CoCounsel: [AI-Assisted Research](https://thomsonreuters.com/en-us/help/cocounsel/skills/ai-assisted-research), [Next generation CoCounsel Legal](https://legal.thomsonreuters.com/blog/the-next-generation-of-cocounsel-legal-is-here/), [Seven shifts](https://legal.thomsonreuters.com/blog/westlaw-cocounsel-legal-seven-shifts-shaping-modern-legal-work/)
- Harvey: [Expanding Harvey's Model Offerings](https://www.harvey.ai/blog/expanding-harveys-model-offerings); [Sacra tahlili](https://sacra.com/research/harvey-at-75m-arr/)
- Anthropic: [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- FrugalGPT: [arXiv 2305.05176](https://arxiv.org/abs/2305.05176)
- RouteLLM: [LMSYS blog](https://lmsys.org/blog/2024-07-01-routellm/)
- Semantik kesh: [GPT Semantic Cache, arXiv 2411.05276](https://arxiv.org/abs/2411.05276); [Braziliya EdTech tadqiqoti](https://sol.sbc.org.br/index.php/sbrc_estendido/article/view/35896)
- OpenRouter: [Provider routing](https://openrouter.ai/docs/features/provider-routing), [Reasoning tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens), [rerank-4-fast](https://openrouter.ai/models/cohere/rerank-4-fast)
- Cohere rerank "search unit" ta'rifi: [Azure hujjati](https://learn.microsoft.com/en-us/azure/ai-studio/how-to/deploy-models-cohere-rerank)
- Ichki ma'lumotlar: `data/golden_dataset/STRESS_TEST_REPORT.md`, `data/golden_dataset/stress_report.json`, `data/golden_dataset/stress_work/report_baseline.json`

---

## 7. Bajarildi: A1, A2, A4 (2026-10-12)

**Nima o'zgardi (kod):**
- **A1 — tarjima:** reasoning o'chirildi (`reasoning: {enabled: false}`), limit 300 token, faqat lotin yozuvi (`src/nlp/query_translator.py`); reranker'ga tarjimaning normallashtirilgan shakli beriladi (`src/retrieval/pipeline.py`).
- **A2 — provayder:** `LLM_PROVIDER_ORDER=deepinfra` (fp8, eng arzon barqaror provayder), `LLM_PROVIDER_QUANTIZATIONS=fp8,fp16,bf16,fp32,unknown` (fp4/int4 chiqarib tashlandi), zaxira provayderlarga ruxsat bor (`src/config.py`, `src/clients/openrouter.py`). Rasmiy DeepSeek provayderi bu akkaunt uchun yopiq (mintaqaviy cheklov) — tekshirildi.
- **A4 — javob:** oddiy rejimda "avval 1–2 gapda aniq javob, keyin faqat tegishli shartlar, ≤220 so'z" (`src/generation/prompts.py`); reasoning sozlamasi `GENERATION_REASONING_EFFORT` (`src/generation/generator.py`).
- Testlar: 132 passed (yangi: provayder sozlamalari, reasoning, tarjimon parametrlari, prompt).

**Muhim topilma — `low` emas, `none`:** `effort: low` kutilganidek ishlamadi — DeepInfra'da reasoning *ko'paydi* (median 522 → 1 047 token) va javob sekinlashdi. Reasoning'ni butunlay o'chirish (`none`) sifatni ham, narxni ham yaxshiladi, shuning uchun standart qiymat **`none`**. Qaytarish kerak bo'lsa: `.env` da `GENERATION_REASONING_EFFORT=low` (yoki `""` — model standarti).

**Baholash usuli tuzatildi:** hakam endi faqat kutilgan moddani emas, javob iqtibos qilgan barcha moddalarni ham ko'radi (aks holda boshqa topilgan normaga to'g'ri tayangan javob "gallyutsinatsiya" deb belgilanardi). Barcha variantlar **bir xil hakam** bilan qayta baholandi (`scripts/stress_eval.py --rejudge`), shuning uchun quyidagi raqamlar bir-biri bilan solishtiriladi (avvalgi bo'limlardagi hakam raqamlari bilan emas).

### Narx (11 ta real savol, OpenRouter hisobi)

| | Oldin | A1+A2+A4 (`low`) | A1+A2+A4 (**`none`**) |
|---|---|---|---|
| **Jami, bir savol** | $0.00521 | $0.00408 | **$0.00324 (−38%)** |
| Reranker | $0.00295 | $0.00295 | $0.00295 (endi xarajatning ~91%) |
| Javob yozish (bir chaqiruv) | $0.00163 | $0.00111 | **$0.00027 (−83%)** |
| Tarjima (ru/en savol) | $0.00172 | $0.00004 | **$0.00004 (−97%)** |
| Chiqish tokeni (median) | 1 433 | 1 527 | **524** |
| Reasoning tokeni (median) | 522 | 1 047 | **0** |
| Javob yozish vaqti (median) | 9.4 s | 13.8 s | **5.1 s** |
| Tarjima vaqti (ru/en) | 13.1 s | 1.8 s | **1.6 s** |
| Bo'sh javoblar | 3 | 0 | **0** |

### Sifat (200 savol, bir xil hakam)

| | Oldin (P0 dan keyin) | `low` | **`none`** |
|---|---|---|---|
| Top-3 da topish | 88.4% | 88.4% | 88.4% |
| Hakam: to'g'ri | 85.5% | 86.0% | **87.8%** |
| Hakam: noto'g'ri | 3.5% | 6.4% | **3.5%** |
| "Gallyutsinatsiya" teglari | 38 | 24 | **22** |
| To'liq javob vaqti (median) | 12.2 s | 14.6 s | **8.1 s** |
| Javob uzunligi (median) | 2 410 belgi | 1 230 | 1 475 |
| OOS: yakuniy javob to'g'ri | 92.9% | 85.7% | 89.3% ⚠️ |

**Qolgan kamchiliklar (`none` bilan):**
- Sohaga yaqin 2 ta OOS savolga (s091 homiladorlik ta'tili, s093 soliq) rad etish o'rniga javob berildi (oldin to'g'ri rad etilgan) — reasoning'siz model chegarani kamroq "o'ylaydi". Yechim: B1 (savolni tushunish qadamida soha tasnifi).
- 1 ta ruscha savolga o'zbekcha javob berildi (s142), 1 ta javobda iqtibos yo'q (s183, validator ushladi).
- Endi asosiy xarajat — **reranker (~91%)**. Keyingi qadam: A3 (`rerank-4-fast`, ≤100 bo'lak) va B3 (shartli rerank).

**Hisob (1 000 savol/kun):** oldin ≈ $156/oy → hozir ≈ **$97/oy**. Reranker optimallashtirilsa (A3+B3) ≈ $50–60/oy bo'lishi kutiladi (baho).

---

## 8. Jev'ga o'tish (2026-10-12)

**Nima o'zgardi (kod):**
- `src/retrieval/jev_ranker.py` (yangi): TypeSafe **Jev** (`typesafe/jev-1.13`, OpenRouter `/api/alpha/decisions`) bilan ikki qaror:
  - **rank** — 30 ta nomzod (har biri 1 500 belgi) ichidan "qaysi biri savolga eng aniq javob beradi" (listwise) + "javob umuman bormi" (`answerable`), bitta chaqiruvda;
  - **scope** — savol nogironlik huquqi doirasidami (`in_scope / other_law / not_legal / manipulation`), qidiruv bilan parallel.
- `src/retrieval/reranker.py`: Jev asosiy reranker; Jev ishlamasa yoki kutilmagan javob qaytarsa — **Cohere avtomatik zaxira**.
- `src/retrieval/relevance_gate.py` + `pipeline.py`: yangi filtr — `P(in_scope) < 0.3` **va** `P(answerable) < 0.8` bo'lsa rad etiladi (Jev yo'li); Cohere zaxirasida eski filtr ishlaydi.
- `src/clients/openrouter.py`: `decide()`; **xavfli joy tuzatildi** — oldin Jev API xato bersa jimgina *soxta (mock) qaror* qaytarilardi, endi `None` qaytadi va zaxira ishlaydi.
- Sozlamalar: `RERANK_PROVIDER=jev`, `JEV_*`, `GATE_JEV_*` (`src/config.py`, `.env.example`). Cohere'ga qaytish: `RERANK_PROVIDER=cohere`.
- Testlar: 138 passed (yangi: Jev rank/scope tahlili, reranker Jev yo'li va Cohere zaxirasi, filtr qoidalari, mock qaytarmaslik).

**Filtr chegaralari qanday tanlandi:** 200 savolda faqat-qidiruv o'lchovi (filtr o'chiq holda) — begona savollarda `answerable` maksimal 0.62, Jev "doiradan tashqari" degan to'g'ri savollarda esa ≥ 0.90. `in_scope<0.3` va `answerable` chegarasi 0.7–0.9 oralig'ida bo'lsa natija bir xil (28/28 ushlanadi, 0 noto'g'ri rad); o'rtasi — **0.8** tanlandi. Chegaralar shu to'plamda tanlangani uchun yangi savollarda qayta tekshirilishi kerak.

### Natijalar (200 savol)

| | Cohere + A1A2A4 | **Jev** |
|---|---|---|
| Top-1 da topish | 62.2% | **77.9%** |
| Top-3 da topish | 88.4% | **92.4%** |
| Top-6 (kontekstda) | 92.4% | **95.3%** |
| MRR | 0.755 | **0.857** |
| Begona savollarni filtr to'xtatdi | 32.1% (9/28) | **100% (28/28)** |
| Begona savollar — yakuniy javob to'g'ri | 89.3% | **100%** |
| To'g'ri savolni asossiz rad etish | 0% | **0%** |
| Hakam: to'g'ri javob (2 marta baholash o'rtachasi) | 86.9% | **86.9%** (o'zgarmadi) |

**Hakam shovqini haqida:** bir xil javoblarni bir xil hakam ikkinchi marta baholaganda 172 tadan 14–15 verdikt (~9%) o'zgardi (v5: 83.7% → 90.1%). Shuning uchun javob sifati ikki baholash o'rtachasi bilan solishtirildi. Xulosa: Jev qidiruv va filtrni sezilarli yaxshiladi, javob sifati (hakam bo'yicha) o'zgarmadi.

**Eski 63 savollik to'plam:** OOS to'g'ri rad etish 84.6% → **100%**, top-1 80% → 82%, top-3 98% → 94% (3 ta savol 2→4-o'ringa tushdi — Jev boshqa, mavzuga mos moddalarni (o'sha farmonning asosiy bandi, ta'rif moddasi) oldinga qo'ydi; ehtimol yorliq tor, tasdiqlanmagan), qidiruv vaqti 3.8 s → **1.9 s**.

### Narx va tezlik (11 ta real savol, OpenRouter hisobi)

| | Eng boshida | A1+A2+A4 | **+ Jev** |
|---|---|---|---|
| **Jami, bir savol** | $0.00521 | $0.00324 | **$0.00085** |
| Reranker | $0.00295 (Cohere) | $0.00295 | **$0.00050** (Jev, 2 chaqiruv: rank + scope) |
| Javob yozish | $0.00163 | $0.00027 | $0.00037 |
| Tarjima (ru/en) | $0.00172 | $0.00004 | $0.00004 |
| Reranker vaqti (median) | 1.7 s | 1.4 s | **0.6 s** |
| Oyiga (1 000 savol/kun) | ≈ $156 | ≈ $97 | **≈ $26** |

Begona savol endi javob yozilmasdan rad etiladi (s187: 2.8 s, generatsiya puli yo'q).

### Xavflar va keyingi qadamlar
- Jev — erta kirish bosqichidagi model, OpenRouter'da "alpha" endpoint: o'zgarishi yoki to'xtashi mumkin. Cohere zaxirasi shu sababli saqlangan; Jev'ning ishlamay qolish holatlarini monitoring qilish kerak (`signals.rerank_provider`).
- Jev har bir nomzodning faqat 1 500 belgisini ko'radi; uzun moddalarda javob undan keyin bo'lsa ko'rmaydi (hozircha natijaga ta'sir qilmadi, lekin kuzatish kerak).
- Qolgan sifat ishlari: ko'p hujjatli savollar (barcha kerakli moddalar kontekstda 89%), xalqona so'zlar, javobga ortiqcha tafsilot qo'shish (hakamning asosiy shikoyati) — B1, B2, B4.
