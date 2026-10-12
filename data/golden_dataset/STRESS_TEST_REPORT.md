# O'zbekiston Nogironlik Huquqi RAG Tizimining 200 Savollik Stress Testi Tahliliy Hisoboti

## 1. Qisqa xulosa va asosiy metrikalar

Mazkur tahliliy hisobot O'zbekiston Respublikasi nogironlik huquqi bo'yicha maxsus axborot-qidiruv va generatsiya (RAG) tizimining 200 ta murakkab savoldan iborat stress-test sinovi natijalariga bag'ishlangan. Avvalgi kichik va toza namunaviy to'plamda (Old Golden Set) tizim yuqori natijalar ko'rsatgan bo'lsa-da (Hit@3 98.0%, MRR 0.910), amaliyotdagi real vaziyatlarga asoslangan 200 savollik stress-testi qidiruv va qayta saralash (reranking) zanjiridagi jiddiy tizimli muammolarni ochib berdi. Stress-test natijalariga ko'ra, umumiy Hit@1 ko'rsatkichi 51.2% ga, Hit@3 72.7% ga, Hit@6 79.7% ga, MRR esa 0.623 ga tushdi. Eng katta uzilishlar rus tilidagi so'rovlar (Hit@3 atigi 37.5%, asossiz rad etish 25.0%), katta hajmli moddalar matnining dastlabki 600 belgisida kesib tashlanishi, reranker havzasining 18 ta nomzod bilan sun'iy cheklanishi hamda ko'p bosqichli (multi-hop) savollarda bir nechta huquqiy aktni to'liq qamrab ololmaslikda namoyon bo'ldi. Shunga qaramay, 25 talik gibrid havza qamrovi (Pool@25) 93.6% ni tashkil etishi qidiruv bazasi to'g'ri shakllanganini, ammo reranker va darvoza (gate) qatlamlarida optimallashtirish zarurligini ko'rsatadi.

### 1.1. Asosiy umumiy metrikalar taqqoslovi

| Metrika | Old Golden Set | Stress Test 200 | Farq | Izoh |
| :--- | :---: | :---: | :---: | :--- |
| **Savollar soni (N)** | 50 | 200 | +150 | 172 ta soha ichidagi (in-scope), 28 ta sohadan tashqari (out-of-scope) |
| **Hit@1** | 84.0% | **51.2%** | -32.8% | Birinchi o'rinda to'g'ri normaning chiqish ehtimoli keskin pasaygan |
| **Hit@3** | **98.0%** | **72.7%** | -25.3% | Top-3 kontekstda kutilgan barcha normalarning topilishi |
| **Hit@6** (eski to'plamda hit@5) | 100.0% | **79.7%** | -20.3% | LLM generatsiyasiga uzatiladigan 6 ta kontekst qamrovi |
| **Pool@25** (eski to'plamda pool@30) | 100.0% | **93.6%** | -6.4% | Gibrid qidiruv (BM25 + Dense) dastlabki 25 talik havzasi qamrovi |
| **MRR (Mean Reciprocal Rank)** | **0.910** | **0.623** | -0.287 | To'g'ri javob pozitsiyasi o'rtacha 1-o'rindan 2-3-o'rinlarga surilgan |
| **False Refusal Rate (In-scope)**| 0.0% | **4.1%** | +4.1% | Kerakli norma bazada bo'la turib, asossiz rad etilgan so'rovlar |
| **Judge Correct (Baholash)** | o'lchanmagan | **77.9%** | - | LLM hakamining to'liq to'g'ri deb topgan javoblari ulushi |
| **Judge Partial** | o'lchanmagan | **7.6%** | - | Javob qisman to'g'ri, lekin muhim shartlar tushirib qoldirilgan |
| **Judge Wrong** | o'lchanmagan | **12.8%** | - | Noto'g'ri javob yoki asossiz rad javobi |
| **OOS Gate Refusal (Chetdagi savollar)**| - | **42.9%** | - | Chetdagi savollarni darvoza (gate) orqali to'xtatish ulushi |
| **OOS Judge Correct** | - | **92.9%** | - | Sohadan tashqari savollarning to'g'ri rad etilishi (prompt himoyasi bilan) |

---

### 1.2. Tillar bo'yicha metrikalar

| Til | N | Hit@1 (%) | Hit@3 (%) | Hit@6 (%) | Pool@25 (%) | MRR | False Refusal (%) | Judge Correct (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **O'zbekcha (uz)** | 171 | 53.9 | 76.6 | 84.4 | 95.5 | 0.657 | 1.9 | 80.5 |
| **Ruscha (ru)** | 22 | 25.0 | **37.5** | **37.5** | 75.0 | **0.312** | **25.0** | **50.0** |
| **Inglizcha (en)** | 7 | 50.0 | 50.0 | 50.0 | 100.0 | 0.500 | 0.0 | 100.0 |

---

### 1.3. Murakkablik toifalari bo'yicha metrikalar (By Difficulty)

| Murakkablik toifasi | N | Hit@1 (%) | Hit@3 (%) | Hit@6 (%) | Pool@25 (%) | MRR | False Refusal (%) | Judge Correct (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **cyrillic_uz** (O'zbekcha kirill) | 16 | 68.8 | 93.8 | 100.0 | 100.0 | 0.818 | 0.0 | 93.8 |
| **exception_condition** (Istisnolar) | 16 | 68.8 | 87.5 | 100.0 | 100.0 | 0.794 | 0.0 | 87.5 |
| **numeric_detail** (Raqamli muddatlar) | 16 | 68.8 | 81.2 | 81.2 | 100.0 | 0.740 | 0.0 | 87.5 |
| **comparison** (Qiyoslash) | 13 | 53.8 | 84.6 | 84.6 | 100.0 | 0.667 | 0.0 | 92.3 |
| **multi_hop** (Ko'p bosqichli) | 26 | 50.0 | 76.9 | 88.5 | 100.0 | 0.651 | 0.0 | 65.4 |
| **false_premise** (Noto'g'ri taxmin) | 15 | 53.3 | 73.3 | 86.7 | 93.3 | 0.663 | 6.7 | 80.0 |
| **situational** (Hayotiy keyslar) | 22 | 45.5 | 68.2 | 81.8 | 95.5 | 0.590 | 0.0 | 86.4 |
| **noisy** (Xato va qisqartmalar) | 16 | 37.5 | 68.8 | 75.0 | 93.8 | 0.516 | 6.2 | 68.8 |
| **lexical_gap** (Xalqona/norasmiy til) | 16 | 43.8 | 56.2 | 56.2 | 75.0 | 0.490 | 6.2 | 75.0 |
| **russian** (Ruscha so'rovlar) | 16 | 25.0 | **37.5** | **37.5** | 75.0 | **0.312** | **25.0** | **50.0** |
| **out_of_scope_far** (Mutlaqo chetdagi) | 8 | - | - | - | - | - | (Gate: 75%) | 100.0 |
| **out_of_scope_near** (Yaqin huquqiy) | 12 | - | - | - | - | - | (Gate: 25%) | 83.3 |
| **adversarial** (G'arazli/jailbreak) | 8 | - | - | - | - | - | (Gate: 37.5%) | 100.0 |

---

### 1.4. Sohalar bo'yicha metrikalar (By Domain)

| Huquqiy soha | N | Hit@1 (%) | Hit@3 (%) | Hit@6 (%) | MRR | Judge Correct (%) | Asosiy zaiflik |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **healthcare** | 10 | 100.0 | 100.0 | 100.0 | 1.000 | 90.0 | Eng barqaror soha |
| **labor_rights** | 12 | 58.3 | 91.7 | 91.7 | 0.736 | 91.7 | Katta moddalar tahriri |
| **medical_social_expertise**| 12 | 58.3 | 75.0 | 83.3 | 0.688 | 91.7 | Nizomlarning uzunligi |
| **legal_protection** | 9 | 66.7 | 77.8 | 77.8 | 0.722 | 77.8 | Top-18 cheklovi |
| **accessibility_infrastructure**| 9 | 44.4 | 66.7 | 77.8 | 0.574 | 77.8 | 600 belgi cheklovi |
| **inclusive_education** | 11 | 45.5 | 72.7 | 81.8 | 0.579 | 90.9 | Maxsus ta'lim atamalari |
| **cross_domain** | 15 | 40.0 | 73.3 | 93.3 | 0.606 | 60.0 | Ko'p aktli integratsiya |
| **transport_benefits** | 9 | 44.4 | 77.8 | 88.9 | 0.615 | 66.7 | Imtiyoz shartlarining tushib qolishi |
| **rehabilitation_prosthetics** | 11 | 54.5 | 81.8 | 81.8 | 0.652 | 63.6 | Yangi qarorlar (VMQ-253) |
| **disability_rights** | 12 | 33.3 | 75.0 | 83.3 | 0.517 | 83.3 | Umumiy qonun normalari |
| **pensions_and_benefits** | 12 | 41.7 | 58.3 | 75.0 | 0.542 | 91.7 | Staj va foiz hisoblari |
| **social_services** | 12 | 50.0 | 58.3 | 66.7 | 0.562 | 66.7 | Xizmat ko'rsatish standartlari |
| **social_protection_governance**| 9 | 55.6 | 55.6 | 55.6 | 0.556 | 77.8 | Agentlik vakolatlari |
| **sanatorium_health** | 4 | 75.0 | 75.0 | 75.0 | 0.750 | 75.0 | Hamrohlik yo'llanmalari |
| **international_treaty** | 8 | 50.0 | 62.5 | 62.5 | 0.562 | 62.5 | BMT Konvensiyasi 2-moddasi |
| **tax_benefits** | 8 | 37.5 | 62.5 | 75.0 | 0.504 | 75.0 | Soliq imtiyozlari chegaralari |
| **out_of_scope** | 28 | - | - | - | - | 92.9 | Darvoza sizishi (near-domain) |

---

## 2. Zaif joylar tahlili

Stress-test natijalarini batafsil o'rganish tizimda 6 ta asosiy zaif nuqta mavjudligini ko'rsatdi:

### 2.1. Rus tili va kross-lingval tafovut (Russian Cross-lingual Gap)
- **Muammo va raqamlar:** Rus tilidagi so'rovlar bo'yicha Hit@3 atigi 37.5%, asossiz rad etishlar (false refusals) esa 25.0% ni tashkil etdi. MRR ko'rsatkichi 0.312 ga tushib ketdi (o'zbek tilida 0.657).
- **Ildiz sababi:** Korpusdagi 3,843 ta birlikdan faqat 1,686 tasida Lex.uz ning rasmiy ruscha matni mavjud. Ruscha so'rov berilganda BM25 leksik qidiruvi o'zbek tilidagi qonun matnlari bilan mos tusha olmaydi; zich vektorli qidiruv (BGE-M3 dense) esa bir o'zi kutilgan hujjatni dastlabki o'rinlarga olib chiqa olmaydi. 9 ta ruscha xatolikdan 7 tasida maqsadli hujjatning Lex.uz da rasmiy ruscha varianti mavjud bo'lmagan.
- **Misollar:**
  - `s086`: IIV xodimining kasalligi bo'yicha komissiya xulosasi haqidagi ruscha so'rov darvoza tomonidan rad etildi (normada ruscha matn yo'q).
  - `s142`: I va II guruh nogironlarini ishga olgan tadbirkorlar uchun subsidiya muddatiga doir ruscha savol bo'yicha 2025-yilgi VMQ-405 qarorining ruscha matni bo'lmagani sababli norma havzaga kirmadi.
  - `s168`: IIV muassasalariga biriktirish sharti bo'yicha ruscha savol darvoza tomonidan asossiz rad etildi.

### 2.2. Rerankerda matnning 600-belgida kesilishi ([:600] Truncation Defect)
- **Muammo va raqamlar:** Reranker moduli (`src/retrieval/reranker.py`, 70-qator) har bir hujjat matnidan faqat `[:600]` belgini olib baholaydi. Korpusdagi barcha huquqiy birliklarning 38% qismi 600 belgidan uzunroq. 24 ta in-scope yo'qotishning 16 tasida kutilgan javob dalili aynan 600-belgidan keyin joylashgan.
- **Oqibati:** Hatto gibrid qidiruv havzasida 1-o'rinda turgan eng aniq hujjatlar ham (pool_rank = 1) reranker tomonidan past baholanib, yakuniy 6 talik kontekstdan butunlay tushirib qoldirildi.
- **Misollar:**
  - `s038`: Havzada 1-o'rindagi hujjat (dalil 600-belgidan keyinda) reranker tomonidan tushirib yuborildi.
  - `s119`: Havzada 1-o'rinda kelgan nafaqa muddati normasi 600 belgili qirqish tufayli kontekstga kirmadi va model ma'lumot topilmadi deb javob berdi.
  - `s121`: Havzada 1-o'rinda turgan qoida reranker past ball bergani sababli relevance gate tomonidan asossiz rad etildi.
  - `s155`: BMT Konvensiyasining 2-moddasidagi "Universal dizayn" ta'rifi moddaning oxirida (600-belgidan ancha narida) bo'lgani uchun havzada 1-o'rinda turgan bo'lsa-da, reranker uni tanimadi.

### 2.3. Reranker nomzodlar havzasining sun'iy cheklanishi (Top-18 Subset Cap)
- **Muammo va raqamlar:** `src/retrieval/reranker.py` faylining 67-qatorida `subset_size = min(len(article_contexts), max(top_n * 3, 16))` formulasi qo'llangan bo'lib, `top_n = 6` bo'lganda maksimal 18 ta nomzod olinadi. Gibrid qidiruv 25 ta nomzod qaytaradi, biroq 19 dan 25 gacha bo'lgan nomzodlar rerankerga umuman uzatilmaydi.
- **Ildiz sababi:** 24 ta in-scope yo'qotishning 10 tasida kutilgan birlik dastlabki gibrid havzada mavjud bo'lgan, ammo uning o'rni 19 yoki undan yuqori (pool_rank >= 19) bo'lgani uchun cross-encoder uni ko'rmasdan tashlab yuborgan.
- **Misollar:**
  - `s013`: Kutilgan norma havzada 19-o'rinda bo'lib, reranker chegarasidan tashqarida qolib ketdi.
  - `s019`: Shovqinli so'rovda to'g'ri hujjat havzada 23-o'rinni egalladi va rerankerga yetib bormadi.
  - `s075`: Hayotiy keys savolida kutilgan akt havzada 25-o'rinda bo'lib, baholanmadi.
  - `s163`: Vaucher mablag'i bo'yicha muhim norma havzada 23-o'rinda qolib, tushib qoldi.

### 2.4. Sohadan tashqari savollarni ajratish zaifligi (Relevance Gate Leakage)
- **Muammo va raqamlar:** Relevance gate moduli sohadan tashqari (out-of-scope) savollarning umumiy 42.9% qismini to'xtata oldi. Xususan, soha chegarasiga yaqin huquqiy savollarda (near-domain: aliment, jinoyat, yo'l harakati, soliq) ushbu ko'rsatkich atigi 25.0% ni tashkil etdi.
- **Ijobiy tomoni va xavflar:** Tizim promptidagi qat'iy ko'rsatmalar ("korpusda yo'q ma'lumotni to'qima") tufayli LLM hakamining o'zi OOS so'rovlarning 92.9% qismini muvaffaqiyatli qaytardi. Biroq, 2 ta holatda tizim korpusdan tashqari umumiy qonunchilik normalarini topib, ularga noto'g'ri javob berib qo'ydi.
- **Misollar:**
  - `s187`: Mehnat kodeksidagi umumiy homiladorlik ta'tili haqidagi savolni darvoza o'tkazib yubordi va model sohadan tashqari javob qaytardi.
  - `s188`: Yakka tartibdagi tadbirkorning umumiy chakana savdo solig'i stavkasi bo'yicha sohadan tashqari javob shakllantirildi.

### 2.5. Ko'p bosqichli (Multi-hop) qidiruv va sintez qiyinchiliklari
- **Muammo va raqamlar:** Bir nechta qonun yoki qaror birlashmasini talab qiluvchi savollarda (multi_hop toifasi) Judge Correct ko'rsatkichi 65.4% ga tushdi, Judge Partial esa 23.1% ni tashkil etdi.
- **Ildiz sababi:** Qidiruv bitta kalit so'z orqali amalga oshirilganda, savolning birinchi qismiga oid hujjat (masalan, BMT Konvensiyasi) yuqori ball oladi, ikkinchi qismiga oid milliy qaror esa quyi o'rinlarga tushib qoladi yoki umuman kirmaydi. Natijada generatsiya modeli to'liq bo'lmagan (partial) javob qaytaradi.
- **Misollar:**
  - `s172`: Uy-joy maydoni normasi bo'yicha milliy qonun va maxsus nizom talab qilinganda, normalardan biri 4-o'ringa surilib qoldi.
  - `s175`: BMT Konvensiyasi va O'zbekiston Qonuni sintezi so'ralganda, Konvensiya topildi, ammo milliy qonunning 5-moddasi kontekstdan tushib qoldi.
  - `s179`: Urush nogironlari uchun transport imtiyozi topildi, biroq sanatoriyga qabul qilish sharti bo'yicha ikkinchi hujjat kontekstga kirmadi.

### 2.6. Leksik va terminologik bo'shliqlar (Lexical Gap & Noisy Queries)
- **Muammo va raqamlar:** Foydalanuvchilar rasmiy qonun atamalari o'rniga xalqona iboralarni ("to'shakka mixlangan", "tekinga beriladimi", "o'g'rilik jazosi") yoki orfografik xatolarni ishlatganda Hit@3 ko'rsatkichi 56.2% gacha tushdi.
- **Ildiz sababi:** BM25 leksik qidiruvi bunday iboralarni rasmiy yuridik leksika ("harakatlanish imkoniyati cheklangan", "bepul ta'minlanadi") bilan bog'lay olmaydi. Agar zich qidiruv ham kuchsiz bo'lsa, birlik havzaga kirmay qoladi.
- **Misollar:**
  - `s001`: "To'shakka mixlanib qolgan" iborasi VMQ-62 nizomidagi "o'zgalar parvarishiga muhtoj" normasi bilan to'g'ridan-to'g'ri moslashmadi.
  - `s058`: Imtiyozli qabul shartlari bo'yicha norasmiy iboralar sababli hujjat havzaga kirmadi.
  - `s069`: Maxsus komissiya ko'rigi bo'yicha so'zlashuv tili sababli qidiruv natijasiz bo'ldi.

---

## 3. Har bir muvaffaqiyatsiz savol katalogi

Quyidagi jadvalda stress-testdagi barcha muvaffaqiyatsiz holatlar to'liq jamlangan. Bunga quyidagi mezonlarga tushgan har bir holat kiritilgan:
1. Soha ichidagi (in-scope) savollarda: `rank == null` yoki `rank > 3`, yoxud `refused_by_gate == true`, yoxud `judge.verdict != "correct"`.
2. Sohadan tashqari (out-of-scope) savollarda: `judge.verdict != "correct"` bo'lgan barcha holatlar.

Ildiz sabablar faqat belgilangan 11 ta rasmiy toifaga ajratilgan:
`rerank_subset`, `rerank_truncation`, `crosslingual`, `lexical_gap_retrieval`, `not_in_pool`, `gate_false_refusal`, `gate_miss_oos`, `multi_hop_partial`, `generation_hallucination`, `generation_incomplete`, `label_or_judge_doubt`.

| ID | Turi (Difficulty) | Nima bo'ldi (qisqacha tavsif) | Ildiz sabab |
| :--- | :--- | :--- | :--- |
| **s001** | lexical_gap | Xalqona ibora sababli kutilgan norma havzaga kirmadi (rank=null, pool_rank=null) | `lexical_gap_retrieval` |
| **s005** | multi_hop | Ko'p bosqichli savolda ikkinchi norma yakuniy kontekstdan tushib qoldi, hakam xato deb topdi | `multi_hop_partial` |
| **s009** | numeric_detail | Havzada 12-o'rindagi norma qayta baholashda 4-o'ringa surildi (rank=4) | `rerank_truncation` |
| **s013** | numeric_detail | Kutilgan norma havzada 19-o'rinda bo'lib, rerankerning top-18 chegarasidan tashqarida qoldi | `rerank_subset` |
| **s018** | noisy | Havzada 2-o'rindagi norma 600 belgili qirqish sababli 4-o'ringa surildi (rank=4) | `rerank_truncation` |
| **s019** | noisy | Kutilgan norma havzada 23-o'rinda bo'lib, top-18 reranker doirasiga kirmadi | `rerank_subset` |
| **s020** | exception_condition | Havzada 11-o'rinda bo'lgan norma qayta baholashda 4-o'ringa tushib qoldi | `rerank_truncation` |
| **s023** | comparison | Qiyosiy norma havzada 25-o'rinda qolib, top-18 ga kirmadi; hakam qisman to'g'ri dedi | `rerank_subset` |
| **s029** | false_premise | Tizim to'g'ri javob berdi, lekin hakam formatni tushunmay unparsed deb xato baholadi | `label_or_judge_doubt` |
| **s031** | cyrillic_uz | Havzada 6-o'rindagi norma 600 belgili qirqish tufayli kontekstga kirmadi | `rerank_truncation` |
| **s038** | noisy | Havzada 1-o'rindagi norma dalili 600-belgidan keyin bo'lgani sababli rerankerda tushirildi | `rerank_truncation` |
| **s043** | russian | Ruscha so'rov, qonunning rasmiy ruscha matni yo'q, havzada 21-o'rinda qolib ketdi | `crosslingual` |
| **s045** | situational | Havzada 6-o'rindagi norma reranker baholashida 5-o'ringa surilib qoldi | `rerank_truncation` |
| **s055** | exception_condition | Norma topildi, biroq generatsiya jarayonida shartlardan biri tushirib qoldirildi | `generation_incomplete` |
| **s058** | lexical_gap | Terminologik bo'shliq tufayli kutilgan modda dastlabki havzaga kira olmadi | `lexical_gap_retrieval` |
| **s059** | exception_condition | Kontekstda norma bo'lishiga qaramay model ma'lumot yo'q deb asossiz rad javobi berdi | `generation_incomplete` |
| **s060** | situational | Vaziyatli savolda javob to'liq berilmadi, muhim shart qisqartirildi | `generation_incomplete` |
| **s065** | situational | Kerakli normani gibrid qidiruv dastlabki 25 talik havzaga olib kela olmadi | `not_in_pool` |
| **s066** | situational | Kontekst topildi (rank=2), ammo model shartlarni to'liq bayon etmadi (judge: partial) | `generation_incomplete` |
| **s069** | lexical_gap | Norasmiy til tufayli hujjat havzaga kirmadi va tizim asossiz rad javobini berdi | `lexical_gap_retrieval` |
| **s072** | noisy | Shovqinli so'rov sababli kutilgan akt dastlabki 25 talik havzaga kirmadi | `not_in_pool` |
| **s075** | situational | Kutilgan norma havzada 25-o'rinda bo'lib, reranker ko'rigiga yetib bormadi | `rerank_subset` |
| **s079** | numeric_detail | Raqamli dalil 600 belgidan narida joylashgani sababli norma 4-o'ringa tushib qoldi | `rerank_truncation` |
| **s080** | multi_hop | Ko'p bosqichli savolda ikkinchi kutilgan norma yakuniy kontekstdan tushib qoldi | `multi_hop_partial` |
| **s084** | numeric_detail | Havzada 10-o'rindagi norma qayta baholashda 5-o'ringa surildi (rank=5) | `rerank_truncation` |
| **s086** | russian | Ruscha so'rov, normada ruscha matn yo'q, darvoza asossiz rad etdi | `crosslingual` |
| **s087** | noisy | Havzada 2-o'rindagi norma 600 belgili qirqish sababli yakuniy kontekstdan tushib qoldi | `rerank_truncation` |
| **s102** | situational | Havzada 2-o'rinda turgan norma reranker baholashida 5-o'ringa tushib ketdi | `rerank_truncation` |
| **s103** | lexical_gap | Norma 1-o'rinda topildi, javob to'g'ri; hakam JSON'i 600 token limitida kesilib `unparsed` bo'ldi | `label_or_judge_doubt` |
| **s108** | noisy | Havzada 12-o'rindagi norma 600 belgili qirqish tufayli kontekstga kirmadi | `rerank_truncation` |
| **s109** | comparison | Qiyosiy tahlilda taqqoslash shartlarining bir qismi generatsiyada to'liq yoritilmadi | `generation_incomplete` |
| **s110** | numeric_detail | Havzada 5-o'rindagi norma reranker tomonidan kesilib, yakuniy 6 talikka kirmadi | `rerank_truncation` |
| **s114** | cyrillic_uz | Model to'g'ri javob bergan, lekin hakam javobni unparsed qilib xato baholagan | `label_or_judge_doubt` |
| **s115** | russian | Ruscha savol, qonunda rasmiy ruscha matn mavjud emas, darvoza asossiz rad etdi | `crosslingual` |
| **s118** | situational | Kutilgan norma havzada 24-o'rinda qolib, top-18 reranker doirasiga kirmadi | `rerank_subset` |
| **s119** | numeric_detail | Havzada 1-o'rindagi norma dalili 600-belgidan keyin bo'lgani uchun rerankerda tushirildi | `rerank_truncation` |
| **s120** | numeric_detail | Havzada 2-o'rinda bo'lgan norma rerankerda 6-o'ringa surilib, top-3 ga kirmadi | `rerank_truncation` |
| **s121** | noisy | Havzada 1-o'rindagi norma dalili 600 belgidan keyinligi sababli darvoza rad etdi | `rerank_truncation` |
| **s131** | noisy | Kutilgan norma havzada 22-o'rinda bo'lib, reranker ko'rigiga yetib bormadi | `rerank_subset` |
| **s133** | russian | Ruscha savol, tegishli qarorning ruscha tarjimasi yo'qligi sababli havzaga kirmadi | `crosslingual` |
| **s140** | situational | Havzada 7-o'rindagi norma 600 belgili qirqish oqibatida yakuniy kontekstga kirmadi | `rerank_truncation` |
| **s142** | russian | Ruscha so'rov, 2025-yilgi qarorning ruscha matni yo'q, havzaga umuman tushmadi | `crosslingual` |
| **s147** | situational | Havzada 3-o'rinda bo'lgan norma rerankerda 5-o'ringa surilib ketdi | `rerank_truncation` |
| **s148** | noisy | Xizmatning bepul yoki pullik ekani haqidagi aniq shart generatsiyada ochiqlanmadi | `generation_incomplete` |
| **s151** | lexical_gap | Havzada 4-o'rindagi Konvensiya moddasi dalili 600 belgidan keyinligi sababli tushirildi | `rerank_truncation` |
| **s155** | noisy | Havzada 1-o'rindagi universal dizayn ta'rifi 600 belgidan keyinligi sababli tushirildi | `rerank_truncation` |
| **s156** | false_premise | Ratifikatsiya to'g'risidagi qonun preambulasi gibrid qidiruv havzasiga kirmadi | `not_in_pool` |
| **s159** | lexical_gap | Kutilgan aniq punkt o'rniga boshqa tutash moddalar olindi, kutilgan birlik havzada yo'q | `not_in_pool` |
| **s162** | russian | Ruscha so'rov, 253-qarorning ruscha matni yo'qligi sababli havzaga tushmadi | `crosslingual` |
| **s163** | noisy | Kutilgan norma havzada 23-o'rinda qoldi; lekin javobdagi "ijobiy farqning 20 foizi rag'batlantirish" qoidasi korpusda bor (PQ-88 2-band, VMQ-253 6-band, VMQ-897) — hakam/yorliq to'liq emas | `rerank_subset` + `label_or_judge_doubt` |
| **s165** | comparison | Qiyosiy normalar havzada 14-o'rinda bo'lib, 600 belgili qirqish tufayli tushirildi | `rerank_truncation` |
| **s168** | russian | Ruscha savol, IIV qoidalarining ruscha matni yo'qligi sababli havzaga kirmadi | `crosslingual` |
| **s172** | multi_hop | Ko'p bosqichli savolda ikkala zarur normadan biri rerankerda 4-o'ringa surildi | `multi_hop_partial` |
| **s174** | multi_hop | BMT Konvensiyasi va milliy qonun sintezida ikkinchi norma 4-o'ringa tushib qoldi | `multi_hop_partial` |
| **s175** | multi_hop | Konvensiya moddasi topildi, lekin O'zbekiston qonunidagi 5-modda kontekstdan tushib qoldi | `multi_hop_partial` |
| **s177** | multi_hop | Ikkala imtiyoz topildi, biroq bir vaqtda foydalanish mumkinligi generatsiyada tushirildi | `generation_incomplete` |
| **s179** | multi_hop | Transport bo'yicha norma olindi, ammo sanatoriyga qabul qilish normasi topilmadi | `multi_hop_partial` |
| **s181** | multi_hop | Imtiyoz topildi, lekin uni amalga oshirish tartibi va shartlari to'liq bayon etilmadi | `multi_hop_partial` |
| **s182** | multi_hop | Nazorat organi topildi, biroq javobgarlik oqibatlari normasi 4-o'ringa surilib qoldi | `multi_hop_partial` |
| **s184** | multi_hop | Model xalq deputatlari kengashini ko'rsatdi, hakam vakillik organi iborasi bo'yicha shubha qildi | `label_or_judge_doubt` |
| **s187** | out_of_scope_near | Homiladorlik ta'tili bo'yicha chetdagi savolni darvoza o'tkazdi va javob berildi | `gate_miss_oos` |
| **s188** | out_of_scope_near | YaTT savdo solig'i bo'yicha chetdagi savolni darvoza o'tkazdi va javob berildi | `gate_miss_oos` |

*(Katalogdagi jami muvaffaqiyatsiz satrlar soni: **61 ta**).*

---

## 4. Tizimni kuchaytirish choralari (P0 / P1 / P2)

Stress-test natijalarida aniqlangan kamchiliklarni bartaraf etish uchun ustuvorliklar kesimida aniq texnik yechimlar ishlab chiqildi.

### 4.1. Shoshilinch tuzatishlar (P0 - Critical Priority)

#### P0-1: Reranker nomzodlar havzasini to'liq qamrab olish (Subset Expansion)
- **Fayl va funksiya:** `src/retrieval/reranker.py`, `Reranker.rerank()` (~67-qator).
- **Qilinadigan o'zgarish:**
  Hozirgi cheklovchi kod:
  ```python
  subset_size = min(len(article_contexts), max(top_n * 3, 16))
  ```
  quyidagiga o'zgartiriladi:
  ```python
  subset_size = len(article_contexts)  # Gibrid havzadagi barcha 25 (yoki 30) ta nomzod to'liq baholanadi
  ```
- **Kutilayotgan samara:** Gibrid qidiruvda topilgan, biroq 19..25 o'rinlarda qolib ketgan barcha birliklar cross-encoder tomonidan baholanadi. Quyidagi 8 ta to'g'ridan-to'g'ri muvaffaqiyatsizlik bartaraf etiladi: `s013`, `s019`, `s023`, `s075`, `s118`, `s131`, `s163`, `s043`.
- **Xavf va resurs sarfi:** Reranking kechikishi oshadi (aniq qiymat o'lchanmagan — Cohere rerank API'ga 18 o'rniga ~31 hujjat yuboriladi; narx so'rov bo'yicha hisoblanadi). Bu generatsiya vaqtiga (8-12 sekund) nisbatan sezilarsiz darajada kam qo'shimcha yuklama hisoblanadi.

#### P0-2: Katta hajmli matnlarni darchalar bo'yicha qayta baholash (Passage-level Window Reranking)
- **Fayl va funksiya:** `src/retrieval/reranker.py`, `Reranker.rerank()` (~70-qator).
- **Qilinadigan o'zgarish:**
  Hozirgi 600 belgili qattiq qirqish:
  ```python
  ctx.article.get_text(language)[:600]
  ```
  o'rniga, har bir hujjat matnini 500 belgili oyna (100 belgi qoplanish/overlap bilan) ko'rinishida darchalarga ajratish va har bir darcha uchun cross-encoder bahosini hisoblab, eng yuqori bahoni (`max(window_scores)`) butun hujjat bali sifatida qabul qilish:
  ```python
  # Har bir uzun matn uchun sliding window baholash
  windows = split_into_windows(full_text, window_size=500, overlap=100)
  window_scores = [cross_encoder.score(query, w) for w in windows]
  best_score = max(window_scores)
  ```
- **Kutilayotgan samara:** Dalili 600-belgidan keyin joylashgan 16 ta in-scope yo'qotish va havzada 1-o'rinda bo'lib ham tushib qolgan birliklar to'liq qaytariladi. Ta'sir ko'rsatadigan ID-lar: `s009`, `s018`, `s020`, `s031`, `s038`, `s045`, `s079`, `s084`, `s087`, `s102`, `s108`, `s110`, `s119`, `s120`, `s121`, `s140`, `s147`, `s151`, `s155`, `s165` (jami 20 ta holat).
- **Xavf va resurs sarfi:** Cross-encoder inferensiya hajmi 2 barobarga ortadi (kechikish o'lchanmagan; hujjatlar soni oynalar soniga ko'payadi — Cohere'ning uzun hujjatlarni o'zi bo'laklash imkoniyati ham sinab ko'rilsin: `[:600]` o'rniga `[:4000]`). Matnning ma'no yaxlitligi saqlanadi.

#### P0-3: Rus va inglizcha so'rovlarni o'zbek tiliga tarjima qilib gibrid izlash (Query-side Translation & Dual RRF)
- **Fayl va funksiya:** `src/nlp/query_analyzer.py` (`QueryAnalyzer.analyze`) va `src/retrieval/hybrid_retriever.py` (`HybridRetriever.retrieve`).
- **Qilinadigan o'zgarish:**
  *Qat'iy qoida:* Lex.uz qonunchilik korpusi matnlariga sun'iy tarjima qo'shilmaydi (qonun faqat rasmiy manbadan olinadi). O'zgarish faqat foydalanuvchi so'rovi bosqichida amalga oshiriladi:
  1. So'rov tili rus yoki ingliz deb aniqlanganda, u o'zbek tiliga tezkor model yoki lug'at yordamida tarjima qilinadi.
  2. Bir vaqtning o'zida ikkita parallel qidiruv yuritiladi:
     - Asl tildagi so'rov bo'yicha ruscha/inglizcha mavjud matnlarda BM25 + Dense;
     - Tarjima qilingan so'rov bo'yicha o'zbekcha asosiy korpusda BM25 + Dense.
  3. Har ikkala qidiruv natijalari RRF (Reciprocal Rank Fusion) orqali birlashtiriladi.
- **Kutilayotgan samara:** Ruscha so'rovlarda Hit@3 ko'rsatkichi 37.5% dan kamida 75-80% ga ko'tariladi, soxta rad etishlar 25% dan 3% gacha pasayadi. Ta'sir qiluvchi ID-lar: `s043`, `s086`, `s115`, `s133`, `s142`, `s162`, `s168` (kutilgan ta'sir; qayta o'lchov bilan tasdiqlanishi kerak).
- **Xavf va resurs sarfi:** So'rovni tarjima qilish uchun kichik lokal model yoki tezkor API chaqiruvi talab etiladi (kechikish o'lchanmagan; natijani so'rov keshida saqlash mumkin).

---

### 4.2. Muhim yaxshilanishlar (P1 - High Priority)

#### P1-1: Ko'p bosqichli so'rovlarni dekompozitsiya qilish (Multi-hop Query Decomposition)
- **Fayl va funksiya:** `src/nlp/query_decomposer.py` (`LegalQueryDecomposer.decompose` — mavjud, qoidaga asoslangan, hozir faqat BM25 uchun ishlatiladi: `hybrid_retriever.py` ~96-qator) va `src/retrieval/pipeline.py`. Taklif: sub-so'rovlarni dense qidiruvga ham berish va har bir sub-so'rovdan kamida 1 ta birlik yakuniy kontekstda qolishini kafolatlash.
- **Qilinadigan o'zgarish:** Agar so'rov murakkab (bir nechta subyekt yoki shartni birlashtiruvchi) deb belgilansa, u 2 ta sodda sub-so'rovga ajratiladi (masalan: "avtomobilni moslashtirish qaysi jamg'armadan" va "qoplash miqdori qancha"). Har bir sub-so'rov bo'yicha top-3 nomzod olinib, yakuniy 6 talik kontekstga kiritiladi.
- **Kutilayotgan samara:** Multi-hop so'rovlarda ikkala huquqiy aktning kontekstga kirishi kafolatlanadi. Ta'sir: `s005`, `s080`, `s172`, `s174`, `s175`, `s179`, `s181`, `s182`.
- **Xavf va resurs sarfi:** Ko'p bosqichli so'rovlar uchun qo'shimcha rejalashtirish qadami (latency +150 ms).

#### P1-2: Sohadan tashqari savollar uchun darvozani kalibrlash (Near-domain Gate Calibration)
- **Fayl va funksiya:** `src/retrieval/relevance_gate.py`, `RelevanceGate.assess()`.
- **Qilinadigan o'zgarish:**
  Relevance gate tekshiruviga nogironlik va ijtimoiy himoya sohasiga mansublikni tekshiruvchi leksik/mavzuiy filtr qo'shiladi. Agar so'rovda umumiy huquq sohalari (ajrashish, aliment, haydovchilik guvohnomasidan mahrum qilish, umumiy homiladorlik ta'tili, ko'chmas mulk oldi-sotdi boji) aniqlansa va unda nogironlik faktori bo'lmasa, darvoza LLM generatsiyasiga o'tkazmasdan to'xtatadi.
- **Kutilayotgan samara:** Near-domain sohadan tashqari savollarni to'xtatish darajasi 25% dan 75-80% gacha oshadi. `s187` va `s188` kabi noto'g'ri javob berish holatlari butunlay yo'qoladi.
- **Xavf va resurs sarfi:** Noto'g'ri pozitivlar (soha ichidagi savollarni noto'g'ri to'xtatib qo'yish) xavfini oldini olish uchun chegara qiymatlarini ehtiyotkorlik bilan kalibrlash zarur.

#### P1-3: Xalqona va norasmiy iboralar uchun sinonimik kengaytirish (Synonym & Colloquial Expansion)
- **Fayl va funksiya:** `src/nlp/legal_synonyms.py` (`LEGAL_SYNONYM_DICTIONARY`, `LegalSynonymExpander` — mavjud, `LegalQueryDecomposer` orqali faqat BM25 so'roviga qo'shiladi).
- **Qilinadigan o'zgarish:** Xalqona iboralar ("to'shakka mixlangan", "tekin yotoqxona", "soxta nogiron") uchun qonunchilikdagi rasmiy ekvivalentlar ("harakatlanish imkoniyati cheklangan", "ijtimoiy turar joy", "asossiz nogironlik belgilash") ro'yxati kengaytiriladi va BM25 so'roviga kiritiladi.
- **Kutilayotgan samara:** `s001`, `s058`, `s069` kabi leksik tafovut tufayli yuzaga kelgan qidiruv yo'qotishlari bartaraf etiladi.

---

### 4.3. Monitoring va profilaktika (P2 - Medium Priority)

#### P2-1: 200 savollik stress-testini avtomatlashtirilgan regressiya darvozasi sifatida joriy etish
- **Fayl va infratuzilma:** `scripts/stress_eval.py` (tayyor) + `data/golden_dataset/stress_eval_200.json`; `tests/test_evaluation_regression.py` dagi grounding testini shu to'plamga ham qo'llash.
- **Qilinadigan o'zgarish:** Ushbu 200 ta savoldan iborat to'plam har bir yangi korpus indeksi yoki kod relizidan oldin avtomatik ishga tushiriladigan majburiy sifat nazorati (Regression Gate) etib belgilanadi.
- **Kutilayotgan samara:** Yangi kiritilgan o'zgarishlar mavjud metrikalarni pasaytirmasligi oldindan kafolatlanadi.

---

## 5. Keyingi o'lchov rejasi va maqsadli ko'rsatkichlar (Targets)

Taklif etilgan P0 va P1 choralari amalga oshirilgandan so'ng 200 savollik to'plam qayta sinovdan o'tkaziladi. Erishilishi lozim bo'lgan maqsadli ko'rsatkichlar:

| Metrika | Joriy holat (Baseline) | Maqsadli ko'rsatkich (Target) | Asosiy yutuq omili |
| :--- | :---: | :---: | :--- |
| **Umumiy Hit@1** | 51.2% | **>= 70.0%** | Reranker oynasi (sliding window) va to'liq havza tahlili |
| **Umumiy Hit@3** | 72.7% | **>= 88.0%** | 600 belgili qirqish va Top-18 cheklovi bartaraf etilishi |
| **Umumiy Hit@6** | 79.7% | **>= 93.0%** | Barcha potentsial nomzodlarning yakuniy kontekstga yetishi |
| **MRR** | 0.623 | **>= 0.780** | Dalillar matn boshida bo'lmagan hujjatlar o'rnining ko'tarilishi |
| **Rus tili Hit@3** | 37.5% | **>= 75.0%** | So'rovni tarjima qilish va parallel o'zbekcha qidiruv (Dual RRF) |
| **Rus tili False Refusal** | 25.0% | **<= 5.0%** | Kross-lingval bo'shliqning bartaraf etilishi |
| **OOS Gate Refusal (Near-domain)**| 25.0% | **>= 75.0%** | Domenlararo chegara filtrining kalibratsiyasi |
| **Judge Correct (Soha ichida)** | 77.9% | **>= 90.0%** | Ko'p bosqichli sintez va to'liq kontekst uzatilishi |
| **Asossiz rad etishlar (Umumiy)**| 4.1% | **<= 1.5%** | Reranker ballari va darvoza chegaralarining uyg'unlashishi |

---

## 6. Nazoratchi (Claude) tekshiruvi — hisobotdan foydalanishdan oldin o'qing

Quyidagilar korpus va kod bo'yicha qo'lda tekshirildi:

- **Hakam (LLM-judge) ba'zan xato qiladi, shuning uchun `judge_wrong` = 12.8% real holatdan biroz yuqori.**
  - `s163`: javobdagi 20% rag'batlantirish qoidasi korpusda mavjud (PQ-88 2-band, VMQ-253 6-band, VMQ-897 4-ilova 40-band); kutilgan javob (`note`) faqat bitta normani hisobga olgan.
  - `s184`: Qonunning 14-moddasi "mahalliy davlat hokimiyati vakillik organlari" deydi — bu xalq deputatlari Kengashlari; javob to'g'ri.
  - `s062`, `s068`, `s143`: `hallucination` tegi noto'g'ri — hakam faqat kutilgan moddani ko'rgan, javob esa boshqa topilgan normalarga to'g'ri tayangan; verdikt baribir `correct`.
  - `s103`: hakam javobi 600 token limitida kesilgan (`unparsed`); xom javob `correct`. Skriptda hakam limiti 2000 tokenga oshirildi.
- **Root-cause raqamlari skript bilan tasdiqlandi:** 24 ta "havzada bor, kontekstda yo'q" holatdan 10 tasi `pool_rank >= 19` (reranker subset), 16 tasida dalil 600-belgidan keyin (6 tasida ikkala sabab ham bor); korpusdagi birliklarning 38% i 600 belgidan uzun.
- **LLM bo'sh javoblari:** ishga tushirish logidagi 156 ta ogohlantirish asosan hakam chaqiruvlaridan (max_tokens=600). 16 ta haqiqiy generatsiya chaqiruvi bilan alohida sinovda bo'sh javob 0 ta. Production'da muammo deb hisoblanmaydi, lekin `src/clients/openrouter.py` dagi `finish_reason`ni logga yozish foydali.
- **Yorliq sifati:** 200 savolning hammasi validatordan o'tgan (id korpusda bor, `evidence` so'zma-so'z topiladi). Gemini yozgan 2 ta xato yorliq tuzatildi: `s035` (mavjud bo'lmagan id), `s088` (337-moddada "50 foiz" cheklovi yo'q — 1 foiz/har foiz qoidasi).

---

## 7. P0 tuzatishlardan keyingi natijalar (2026-10-12)

Amalga oshirilgan o'zgarishlar:
1. **Reranker barcha nomzodlarni ko'radi** — `src/retrieval/reranker.py`: 18 ta o'rniga 40 tagacha birlik (`MAX_RERANK_UNITS`), API'dan barcha hujjatlar uchun ball olinadi.
2. **Uzun moddalar bo'laklab baholanadi** — `split_windows()`: 700 belgili, 150 belgi ustma-ust tushadigan oynalar (birlik uchun 8 tagacha, so'rov uchun jami 100 hujjat); birlik bali = eng yaxshi oyna bali. `[:600]` kesish olib tashlandi.
3. **ru/en savollar o'zbekchaga tarjima qilinadi** — `src/nlp/query_translator.py` (LRU kesh, 512) + `src/retrieval/pipeline.py`: asl tildagi va tarjima qilingan so'rov bo'yicha ikki qidiruv, `merge_candidates()` bilan RRF birlashtirish; reranker so'rovi = asl savol + tarjima. Korpus matni tarjima qilinmaydi. Tarjima birinchi qidiruv bilan parallel ishlaydi.
4. Yordamchi: `OpenRouterClient.chat_completion(min_chars=...)` — qisqa tarjimalar "bo'sh javob" deb rad etilmasligi uchun (standart 30 o'zgarmagan).

Testlar: `pytest` — 127 passed (4 ta yangi test: oynalar, 18-dan keyingi va 600-belgidan keyingi matnni ko'rish, `merge_candidates`, tarjimon).

### 200 savol: oldin → keyin

| Ko'rsatkich | Oldin | Keyin |
|---|---|---|
| Hit@1 | 51.2% | **63.4%** |
| Hit@3 | 72.7% | **88.4%** |
| Hit@6 | 79.7% | **92.4%** |
| MRR | 0.623 | **0.760** |
| Pool@25 | 93.6% | 95.9% |
| Asossiz rad etish (in-scope) | 4.1% | **0.0%** |
| Hakam: to'g'ri | 77.9% | **87.8%** |
| Hakam: noto'g'ri | 12.8% | **5.2%** |
| Ruscha Hit@3 | 37.5% | **93.8%** |
| Ruscha hakam: to'g'ri | 50.0% | 100% (qayta o'lchovda 81%) |
| OOS: darvoza rad etdi | 42.9% | 32.1% ⚠️ |
| OOS: yakuniy javob to'g'ri (hakam) | 92.9% | 92.9% |
| O'rtacha kechikish (to'liq javob) | 11.8 s | 15.6 s ⚠️ |

Eski golden to'plam (63 savol) tuzatishdan keyin: hit@3 98% (o'zgarmadi), hit@1 84% → 80%, MRR 0.912 → 0.894, OOS to'g'ri rad etish 92.3% → 84.6%.

### Qolgan muammolar va kuzatuvlar
- **Darvoza sohaga yaqin savollarni ushlay olmaydi.** Oyna bo'yicha eng yaxshi ball olinishi rerank ballarini oshirdi. Kalibrlash (222 in-scope + 21 OOS) ko'rsatdiki, ballar kesishadi: masalan `s187` (oddiy homiladorlik ta'tili) 0.94 oladi, chunki Mehnat kodeksi korpusda bor. Chegarani 0.80 ga ko'tarish 6 ta OOS ni to'xtatadi, lekin 5 ta to'g'ri savolni ham rad etadi — shuning uchun `GATE_MIN_RERANK_SCORE=0.70` o'zgartirilmadi. Yechim — ballga emas, LLM-asosidagi "kontekst savolga javob beradimi" tekshiruviga (P1-2) o'tish.
- **Kechikish:** ru/en savollarga tarjima (~3 s) va ikkinchi qidiruv qo'shildi; ilgari tez rad etilgan ruscha savollarga endi to'liq javob yoziladi, shuning uchun ru median 6.7 s → 16-18 s. O'zbekcha median 9.5 → 11.2 s (ko'proq rerank hujjati). Asosiy vaqt — javob generatsiyasi.
- **Qidiruvda yomonlashgan 3 savol:** `s045` (rank 5 → yo'q), `s048` (1 → 4), `s175` (3 → yo'q); bunga qarshi 27 savol top-3 ga kirdi.
- **Hakam shovqini:** bir xil kontekstda qayta ishga tushirilganda kichik guruhlarda (n≈16) hakam ko'rsatkichi ±15% tebranadi (ruscha 100% → 81%). Qaror qabul qilishda retrieval metrikalari (hit@k, MRR) ishonchliroq.
- **Hali qilinmagan:** P1-1 (multi-hop: hit@3 92%, lekin barcha kerakli moddalar kontekstda faqat 53.8% holatda; oldin 50%), P1-2 (OOS darvozasi), P1-3 (xalqona sinonimlar: lexical_gap hit@3 hali 62.5%).
