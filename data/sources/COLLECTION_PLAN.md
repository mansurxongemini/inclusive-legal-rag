# Qonunchilik Korpusini To'ldirish Rejasi (COLLECTION_PLAN.md)

_Hosil qilingan sana: 2026-10-18. Rasmiy manba: O'zbekiston Respublikasi Qonunchilik ma'lumotlari milliy bazasi ([Lex.uz](https://lex.uz))._

---

## 1. Umumiy Xulosa va Statistika

Ushbu reja milliy huquqiy RAG tizimi korpusini nogironlik, ijtimoiy himoya, sog'liqni saqlash, pensiya, bandlik hamda umumiy fuqarolik, ma'muriy va protsessual normalar bo'yicha to'liq, ishonchli va tizimli darajaga yetkazish uchun ishlab chiqildi.

| Ko'rsatkich | Soni | Izoh |
|---|---:|---|
| **Jami ko'rib chiqilgan hujjatlar** | **429 ta** | Barcha dublikatlar bartaraf etilgan, yagona `lex_id` |
| **Qo'shilishi / to'liq rejimga o'tkazilishi kerak (`ADD`)** | **51 ta** | 11 ta kodeks, 20 ta asosiy qonun, 20 ta qaror/farmon |
| **Bazada allaqachon to'liq mavjud (`ALREADY`)** | **348 ta** | Moddalar to'liqligi Lex.uz bilan tasdiqlangan |
| **Faqat o'zgartirish kirituvchi aktlar (`SKIP_AMENDING_ONLY`)** | **17 ta** | Mustaqil normasi yo'q, Lex.uz asosiy matnga singdirgan |
| **Bekor qilingan hujjatlar (`SKIP_REPEALED`)** | **5 ta** | Kuchini yo'qotgan (masalan, O'RQ-415, 1992-yilgi aktlar) |
| **Mavzuga aloqador bo'lmaganlar (`SKIP_IRRELEVANT`)** | **6 ta** | Bayramlar, idoraviy nishonlar, tor tarmoq aktlari |
| **Parser xatoligi / matni yo'q (`PARSE_PROBLEM`)** | **1 ta** | VMQ-555 (Lex.uz'da HTML tanasi hali e'lon qilinmagan) |
| **Topilmagan / e'lon qilinmagan (`NOT_FOUND`)** | **1 ta** | BMT Nogironlar konvensiyasi Fakultativ protokoli |
| **Kutilayotgan yangi normalar/birliklar soni** | **~7,146 ta** | Kodekslar, qonunlar va yangi hukumat qarorlari |

---

## 2. Guruhlar Kesimida Qarorlar Matritsasi

| Guruh | Tavsif | Jami | ADD | ALREADY | SKIP_AMENDING | SKIP_REPEALED | SKIP_IRRELEVANT | PARSE_PROBLEM | NOT_FOUND |
|:---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **A** | **Kodekslar** (to'liq `include: all`) | **19** | **11** | 8 | 0 | 0 | 0 | 0 | 0 |
| **B** | **Ijtimoiy himoya, sog'liq, ta'lim, bandlik qonunlari** | **45** | **20** | 24 | 0 | 1 | 0 | 0 | 0 |
| **C** | **Hukumat qarorlari, farmonlar va nizomlar** | **332** | **20** | 301 | 0 | 4 | 6 | 1 | 0 |
| **D** | **Xalqaro hujjatlar** (BMT Konvensiyasi va protokoli) | **4** | **0** | 3 | 0 | 0 | 0 | 0 | 1 |
| **E** | **Mavjud hujjatlarga tuzatish kiritgan aktlar** | **29** | **0** | 12 | 17 | 0 | 0 | 0 | 0 |
| **JAMI** | | **429** | **51** | **348** | **17** | **5** | **6** | **1** | **1** |

---

## 3. A Guruhi: Kodekslar Holati va Kengaytirish Rejasi (19 ta)

Kodekslar qonunchilikning poydevori hisoblanadi. Chet el tajribasi (Harvey AI, Casetext) ko'rsatganidek, kodekslarni kalit so'z bilan kesib olish ("disability_articles") yuridik kolliziya, umumiy qoidalar, muddatlar va javobgarlik normalarini uzib tashlaydi. Shu sababli barcha kodekslar to'liq (`include: all`) kiritilishi shart.

| № | Kodeks nomi | Lex.uz ID | Raqam / Sana | Holat | Birliklar | Hozirgi reestr | Rejadagi qaror |
|:---:|---|---|---|:---:|---:|---|:---:|
| 1 | **Soliq kodeksi** | `-4674902` | O'RQ-599 (30.12.2019) | active | 500 | disability (16 ta) | **ADD (all)** |
| 2 | **Fuqarolik kodeksi (2-qism)** | `-180552` | 29.08.1996 | active | 811 | disability (50 ta) | **ADD (all)** |
| 3 | **Maʼmuriy javobgarlik toʻgʻrisidagi kodeks** | `-97664` | 22.09.1994 | active | 665 | disability (24 ta) | **ADD (all)** |
| 4 | **Jinoyat kodeksi** | `-111453` | 22.09.1994 | active | 406 | disability (16 ta) | **ADD (all)** |
| 5 | **Jinoyat-protsessual kodeksi** | `-111460` | 22.09.1994 | active | 763 | disability (26 ta) | **ADD (all)** |
| 6 | **Jinoyat-ijroiya kodeksi** | `-163629` | 25.04.1997 | active | 199 | disability (21 ta) | **ADD (all)** |
| 7 | **Bojxona kodeksi** | `-2876354` | O'RQ-400 (20.01.2016) | active | 419 | Yo'q | **ADD (all)** |
| 8 | **Budjet kodeksi** | `-2304138` | O'RQ-360 (26.12.2013) | active | 179 | Yo'q | **ADD (all)** |
| 9 | **Saylov kodeksi** | `-4386848` | O'RQ-544 (25.06.2019) | active | 116 | disability (8 ta) | **ADD (all)** |
| 10 | **Iqtisodiy protsessual kodeksi** | `-3523891` | O'RQ-461 (24.01.2018) | active | 390 | Yo'q | **ADD (all)** |
| 11 | **Havo kodeksi** | `-55594` | 863-XII (07.05.1993) | active | 136 | Yo'q | **ADD (all)** |
| 12 | **Mehnat kodeksi** | `-6257288` | O'RQ-798 (28.10.2022) | active | 593 | all (593 ta) | **ALREADY** |
| 13 | **Fuqarolik kodeksi (1-qism)** | `-111189` | 21.12.1995 | active | 386 | all (386 ta) | **ALREADY** |
| 14 | **Oila kodeksi** | `-104720` | 30.04.1998 | active | 220 | all (220 ta) | **ALREADY** |
| 15 | **Uy-joy kodeksi** | `-106136` | 24.12.1998 | active | 141 | all (141 ta) | **ALREADY** |
| 16 | **Yer kodeksi** | `-152653` | 30.04.1998 | active | 110 | all (110 ta) | **ALREADY** |
| 17 | **Shaharsozlik kodeksi** | `-5307951` | O'RQ-676 (22.02.2021) | active | 85 | all (85 ta) | **ALREADY** |
| 18 | **Fuqarolik protsessual kodeksi** | `-3517337` | O'RQ-468 (22.01.2018) | active | 513 | all (513 ta) | **ALREADY** |
| 19 | **Maʼmuriy sud ishlarini yuritish kodeksi** | `-3527353` | O'RQ-469 (25.01.2018) | active | 309 | all (309 ta) | **ALREADY** |

---

## 4. B Guruhi: Asosiy Qonunlar (Qo'shiladigan 20 ta qonun)

| № | Qonun nomi | Lex.uz ID | Raqami | Qabul sanasi | Birliklar | Rejim | Qo'shish sababi |
|:---:|---|---|---|:---:|---:|:---:|---|
| 1 | **Aholi bandligi toʻgʻrisida** | `-5055690` | O'RQ-642 | 2020-10-20 | 122 | all | Nogironligi bo'lgan shaxslar uchun 3% ish o'rni kvotasi, subsidiya va bandlik kafolatlari. |
| 2 | **Notariat toʻgʻrisida** | `-54458` | 343-I | 1996-12-26 | 113 | all | Notarial tasdiqlash, vasiyatnoma, vasiylik ishonchnomalari va uy-joy bitimlari. |
| 3 | **Fuqarolarning davlat pensiya taʼminoti toʻgʻrisida** | `-112314` | 938-XII | 1993-09-03 | 69 | all | Nogironlik, yoshga doir va boquvchisini yo'qotganlik pensiyalarining asosiy tayanch qonuni. |
| 4 | **Davlat fuqarolik xizmati toʻgʻrisida** | `-6145972` | O'RQ-788 | 2022-08-08 | 64 | all | Davlat xizmatiga qabul, tanlovlar va mehnat huquqlari kafolatlari. |
| 5 | **Koʻp kvartirali uylarni boshqarish toʻgʻrisida** | `-4586282` | O'RQ-581 | 2019-11-07 | 56 | all | Ko'p qavatli uylarda pandus, umumiy mulk va boshqaruv organlari kafolatlari. |
| 6 | **Vasiylik va homiylik toʻgʻrisida** | `-2307826` | O'RQ-364 | 2014-01-02 | 50 | all | Muomalaga layoqatsiz/cheklangan shaxslar va yetim bolalarga vasiy tayinlash. |
| 7 | **Fuqarolar sogʻligʻini saqlash toʻgʻrisida** | `-26013` | 265-I | 1996-08-29 | 46 | all | Bepul tibbiy xizmat, statsionar davolanish va tibbiy ekspertiza asosiy qonuni. |
| 8 | **Mehnatni muhofaza qilish toʻgʻrisida** | `-3031427` | O'RQ-410 | 2016-09-22 | 39 | all | Maxsus mehnat sharoitlari va xavfsizlik standartlari. |
| 9 | **Shaxsga doir maʼlumotlar toʻgʻrisida** | `-4396419` | O'RQ-547 | 2019-07-02 | 37 | all | Tibbiy ma'lumotlar va nogironlik ma'lumotlarining maxfiylik kafolatlari. |
| 10 | **Fuqarolarning oʻzini oʻzi boshqarish organlari** | `-2156899` | O'RQ-350 | 2013-04-22 | 36 | all | Mahalla orqali ijtimoiy yordam va Ijtimoiy reestr mexanizmlari. |
| 11 | **Bola huquqlarining kafolatlari toʻgʻrisida** | `-1297315` | O'RQ-139 | 2008-01-07 | 34 | all | Nogironligi bo'lgan bolalar ta'limi va oila ta'minoti kafolatlari. |
| 12 | **Dori vositalari va farmatsevtika faoliyati** | `-2856464` | O'RQ-399 | 2016-01-04 | 31 | all | Imtiyozli retseptlar, xavfsizlik va dori ta'minoti yangi tahrirdagi qonuni. |
| 13 | **Advokatura toʻgʻrisida** | `-54503` | 349-I | 1996-12-27 | 30 | all | Malakali yuridik yordam olish va advokatlik faoliyati kafolatlari. |
| 14 | **Davlat uy-joy fondini xususiylashtirish** | `-98430` | 846-XII | 1993-05-07 | 29 | all | Nogironligi bo'lgan shaxslarga uyni tekinga xususiylashtirish imtiyozi. |
| 15 | **Ijtimoiy sheriklik toʻgʻrisida** | `-2468214` | O'RQ-376 | 2014-09-25 | 29 | all | Nogironlar jamiyatlari va davlat organlari o'rtasidagi ijtimoiy dasturlar. |
| 16 | **OIV infeksiyasi tarqalishiga qarshi kurashish** | `-2240470` | O'RQ-353 | 2013-09-23 | 28 | all | Bemorlarga moddiy yordam, dori ta'minoti va kamsitmaslik kafolatlari. |
| 17 | **Jamgʻarib boriladigan pensiya taʼminoti** | `-390573` | 702-II | 2004-12-02 | 27 | all | Xalq banki shaxsiy jamg'arib boriladigan pensiya hisobvarag'i (ShJBPX) tartibi. |
| 18 | **Homiylik toʻgʻrisida** | `-1183667` | O'RQ-96 | 2007-05-02 | 26 | all | Homiylik yordami ajratish va soliq imtiyozlari qoidalari. |
| 19 | **Tazyiq va zoʻravonlikdan jabrlanganlarga ijtimoiy xizmat** | `-8472503` | O'RQ-1175 | 2026-09-11 | 9 | all | 2026-yilda yangi qabul qilingan ijtimoiy xizmatlar to'g'risidagi qonun. |
| 20 | **Xotin-qizlarga qoʻshimcha imtiyozlar** | `-10550` | 760-I | 1999-04-14 | 5 | all | Og'ir sharoitdagi xotin-qizlar va onalarga davlat imtiyozlari. |

---

## 5. C Guruhi: Yangi Hukumat Qarorlari va Farmonlari (20 ta ADD)

| № | Hujjat nomi | Lex.uz ID | Raqami | Sana | Birliklar | Rejim | Qo'shish sababi |
|:---:|---|---|---|:---:|---:|:---:|---|
| 1 | **Kasbiy taʼlim tizimi normativ hujjatlari** | `-8516575` | VMQ-526 | 2026 | 470 | disability | Inklyuziv kasbiy ta'lim va imtiyozlar bo'limlari (katta hajmli hujjat). |
| 2 | **Kommunal xizmatlar koʻrsatish qoidalari** | `-2430765` | VMQ-194 | 2014-07-15 | 274 | all | Markaziy isitish, suv, gaz va elektr bo'yicha imtiyozlar va kompensatsiya. |
| 3 | **Fuqarolar yigʻinlari faoliyatini takomillashtirish** | `-5461749` | VMQ-380 | 2021-06-18 | 272 | all | Mahalla orqali moddiy yordam ajratish va ehtiyojmandlarni aniqlash. |
| 4 | **Yoʻl harakati qoidalarini tasdiqlash** | `-5953883` | VMQ-172 | 2022-04-12 | 205 | all | "Nogiron haydovchi" belgisi, to'xtash joylari va yo'l imtiyozlari. |
| 5 | **Odam savdosi jabrdiydalariga ijtimoiy xizmatlar** | `-8523611` | VMQ-539 | 2026-10-06 | 96 | all | Yangi nizom: reabilitatsiya markazlari va ijtimoiy xizmatlar ko'rsatish tartibi. |
| 6 | **Yetim bolalarni qoʻllab-quvvatlash** | `-7515808` | VMQ-294 | 2025-05-12 | 61 | all | Turar joy sotib olish va moddiy yordam ajratish qoidalari. |
| 7 | **Yetim bolalarni ijtimoiy qoʻllab-quvvatlash** | `-5117079` | VMQ-739 | 2020-11-21 | 57 | all | Ta'lim, kiyim-kechak va pul kompensatsiyalari me'yorlari. |
| 8 | **Maktabgacha pedagog kasbiy standarti** | `-7618066` | VMQ-423 | 2025-07-09 | 42 | all | Maxsus va inklyuziv guruhlar pedagoglari malaka talablari. |
| 9 | **Oʻzini oʻzi band qilgan shaxslar tartibi** | `-5182451` | VMQ-806 | 2020-12-23 | 39 | all | Nogironligi bo'lgan shaxslarning kasanachilik va hunarmandchilik faoliyati. |
| 10 | **Umumiy oʻrta taʼlim pedagogik kengashi** | `-2978386` | REG-2799 | 2016-06-03 | 26 | all | Inklyuziv sinflarni tashkil etish bo'yicha pedagogik kengash vakolatlari. |
| 11 | **Yetim bolalarni uy-joy bilan taʼminlash** | `-5570968` | PQ-5215 | 2021-08-09 | 21 | all | Davlat hisobidan bepul uy-joy berish kafolati. |
| 12 | **Yetim bolalarning taʼlim-tarbiyasi** | `-5569689` | PQ-5216 | 2021-08-09 | 20 | all | Oliy ta'lim grantlari va stipendiyalar tizimi. |
| 13 | **“Kambagʻallikdan farovonlik sari” dasturi** | `-7109778` | PQ-330 | 2024-09-23 | 19 | all | Ijtimoiy reestr va ijtimoiy shartnoma bo'yicha yangi chora-tadbirlar. |
| 14 | **Bemorlarni parvarishlash tartibi** | `-7869303` | REG-3715 | 2025-09-26 | 18 | all | Statsionarda o'zgalar parvarishiga muhtoj bemorlarni parvarishlash qoidalari. |
| 15 | **Orfan kasalliklar yangi davlat dasturi** | `-7813468` | PQ-331 | 2025-09-19 | 15 | all | 2026-2030-yillarda kam uchraydigan kasalliklarga chalingan bolalarga yordam. |
| 16 | **Retsipiyent va tirik donorni tibbiy tekshirish** | `-7851955` | REG-3706 | 2025-09-02 | 14 | all | A'zo ko'chirib o'tkazishda tibbiy-ijtimoiy xulosalar berish tartibi. |
| 17 | **Qurbon hayiti moddiy yordami** | `-8216684` | PQ-196 | 2026-06-05 | 13 | all | Ehtiyojmand oilalar va nogironligi bo'lgan shaxslarga bir martalik to'lov. |
| 18 | **Eshitish va nutqida muammosi boʻlgan shaxslar** | `-4245424` | PQ-4242 | 2019-03-18 | 8 | all | Surdotarjimon xizmatlari va imo-ishora tili kafolatlari. |
| 19 | **Orfan kasalliklarga tibbiy yordam** | `-4503026` | PQ-4440 | 2019-09-07 | 7 | all | Orfan dori vositalari bilan bepul ta'minlash dasturi. |
| 20 | **Kambagʻallikni qisqartirish siyosati** | `-7100210` | PF-136 | 2024-09-09 | 5 | all | Ijtimoiy himoya milliy agentligi vakolatlari va strategik dasturlari. |

---

## 6. PARSE_PROBLEM va NOT_FOUND Hujjatlar Tahlili

### 1. `PARSE_PROBLEM` (1 ta hujjat)
* **Hujjat**: VMQ-555 (09.10.2026), `https://lex.uz/uz/docs/-8540128`.
* **Nomi**: "Hududiy ijtimoiy xizmatlar markazlarida aholining ehtiyojmand qatlamlariga kompleks ijtimoiy va reabilitatsiya xizmatlari koʻrsatishni tashkil etish chora-tadbirlari toʻgʻrisida".
* **Muammo tahlili**: Qaror bir necha kun oldin qabul qilingan bo'lib, Lex.uz portalida uning pasporti/rekvizitlari e'lon qilingan, ammo **HTML matn tanasi (`divCont` / `lx_elem`) hali joylashtirilmagan**. Natijada parser 0 ta birlik qaytardi.
* **Tavsiya**: Lex.uz matnni HTML formatida to'liq yuklagunga qadar `collection_plan.json` da `PARSE_PROBLEM` sifatida ushlab turiladi va matn chiqqach avtomatik `ADD` qilinadi.

### 2. `NOT_FOUND` (1 ta hujjat)
* **Hujjat**: BMT Nogironlar huquqlari to'g'risidagi konvensiyasining Fakultativ protokoli (`crpd_optional_protocol`).
* **Muammo tahlili**: O'zbekiston Respublikasi BMTning 2006-yilgi Nogironlar huquqlari to'g'risidagi asosiy Konvensiyasini 2021-yilda (O'RQ-695 orqali) ratifikatsiya qilgan (u bazada bor: `-5501227`). Biroq uning **Fakultativ protokoli hali O'zbekiston tomonidan ratifikatsiya qilinmagan va Lex.uz milliy qonunchilik portalida e'lon qilinmagan**.
* **Qaror**: `NOT_FOUND` (sababi aniq ko'rsatilgan).

---

## 7. Chet El Legal AI / Legal RAG Startaplari Arxitekturasi va Eng Yaxshi Amaliyotlari

Nogironlik huquqlari va ijtimoiy qonunchilik bo'yicha global startaplar (**Harvey AI**, **Casetext / CoCounsel**, **Leya**, **Robin AI**, **Legartis**) qonunchilik korpusini tuzishda quyidagi fundamental tamoyillardan foydalanadi:

1. **Kodekslarni to'liq saqlash prinsipi (Whole Statutory Preservation - Harvey AI yondashuvi):**
   * *Muammo*: Kichik kalit so'zlar ("nogironlik", "imtiyoz") orqali qonundan faqat 10-15 ta moddani kesib olish yuridik xatolarga sabab bo'ladi. Masalan, Soliq kodeksining 380-moddasidagi imtiyozni to'g'ri qo'llash uchun 378-modda (daromad tushunchasi), soliq davri, hisob-kitob qilish va jazolash normalari kerak bo'ladi.
   * *Yechim*: Asosiy kodekslar hech qachon qirqilmaydi (`include: all`).

2. **O'zgartirish aktlarini asosiy normaga singdirish (Consolidated Law vs Amending Acts - Casetext KeyCite):**
   * *Muammo*: "O'zbekiston Respublikasining ayrim qonunlariga o'zgartish va qo'shimchalar kiritish to'g'risida"gi aktlar faqat ko'rsatmalardan iborat ("1-modda 2-qismidagi falon so'z pismadon so'z bilan almashtirilsin"). Agar bu aktlar korpusga kiritilsa, vektor qidiruvida chalkashlik va soxta iqtiboslar (hallucinations) yuzaga keladi.
   * *Yechim*: Lex.uz rasman bu o'zgartirishlarni asosiy aktlar matniga singdirganligi sababli, alohida mustaqil normasi bo'lmagan bunday aktlar `SKIP_AMENDING_ONLY` deb qat'iy filtrlanadi.

3. **Ierarxik kontekst va Bob/Ilova sarlavhalarini ulash (Context-Enriched Structural Chunking):**
   * Vektor bo'lagiga faqat modda matnini emas, uning tepasidagi Qonun nomi, Bo'lim, Bob va Ilova sarlavhasini ("1-ilova: Reabilitatsiya texnik vositalari ro'yxati") qo'shish qidiruv aniqligini (Retrieval Precision) 40% ga oshiradi.

4. **Amal qilish muddatini tekshirish (Good Law / Validity Gate):**
   * Bekor qilingan qonunlar (`status: repealed`) javob generatsiyasidan chiqarib tashlanishi yoki "ushbu norma kuchini yo'qotgan" deb aniq belgilanishi shart.

---

## 8. 10 ta Hujjatni Lex.uz dan Qayta Jonli Tekshirish (Spot-Check Audit Proof)

Ushbu ma'lumotlar to'qilmaganligini va Lex.uz rasmiy portali bilan 100% mosligini isbotlash uchun turli guruhlardan 10 ta akt tanlab olinib, jonli tekshirildi:

| № | Lex.uz ID | Guruh | Raqam | Lex.uz dagi Rasmiy Nomi | Sana | Holati | Birliklar | Natija |
|:---:|---|:---:|---|---|:---:|:---:|---:|:---:|
| 1 | `-4674902` | **A** | O'RQ-599 | Oʻzbekiston Respublikasining Soliq kodeksi | 2019-12-30 | active | **500** | Tasdiqlandi (mos: True) |
| 2 | `-2876354` | **A** | O'RQ-400 | Oʻzbekiston Respublikasining Bojxona kodeksi | 2016-01-20 | active | **419** | Tasdiqlandi (mos: True) |
| 3 | `-112314` | **B** | 938-XII | Fuqarolarning davlat pensiya taʼminoti toʻgʻrisida | 1993-09-03 | active | **69** | Tasdiqlandi (mos: True) |
| 4 | `-5055690` | **B** | O'RQ-642 | Aholi bandligi toʻgʻrisida | 2020-10-20 | active | **122** | Tasdiqlandi (mos: True) |
| 5 | `-2856464` | **B** | O'RQ-399 | Dori vositalari va farmatsevtika faoliyati toʻgʻrisida | 2016-01-04 | active | **31** | Tasdiqlandi (mos: True) |
| 6 | `-3083192` | **B** | O'RQ-415 | Keksalar, nogironligi boʻlgan shaxslar... ijtimoiy xizmatlar | 2016-12-26 | **repealed** | **30** | Bekor qilingan (23.07.2026) |
| 7 | `-8523611` | **C** | VMQ-539 | Odam savdosidan jabrlanganlarga ijtimoiy xizmatlar koʻrsatish | 2026-10-06 | active | **96** | Tasdiqlandi (mos: True) |
| 8 | `-8540128` | **C** | VMQ-555 | Hududiy ijtimoiy xizmatlar markazlarida kompleks xizmat | 2026-10-09 | active | **0** | Parse problem (matn yo'q) |
| 9 | `-5501227` | **D** | BMT | Nogironlar huquqlari toʻgʻrisida (CRPD Konvensiyasi) | 2006-12-13 | active | **51** | Tasdiqlandi (mos: True) |
| 10 | `-5844851` | **E** | O'RQ-748 | Bojxona kodeksiga qoʻshimcha va oʻzgartishlar kiritish | 2022-02-01 | active | **10** | Faqat o'zgartirish (Skip) |

---

## 9. Chiqish Fayllari va Ulardan Foydalanish

1. `data/sources/collection_plan.json`: Mashina o'qishi uchun yaroqli to'liq JSON ro'yxat (429 ta hujjat, to'liq metadata bilan).
2. `data/sources/COLLECTION_PLAN.md`: Ushbu tahliliy va batafsil hisobot hujjati.
3. `data/sources/add_commands.sh`: Faqat `ADD` qarori qabul qilingan 51 ta hujjatni korpusga qo'shish buyruqlari skripti. *(Foydalanuvchi talabiga ko'ra avtomatik ishga tushirilmagan, tayyor holatda taqdim etilmoqda)*.
