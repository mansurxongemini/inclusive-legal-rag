# Pilotdan ommaviy ishga tushirishgacha reja

Tayyorlandi: 2026-10-23. Holat: ishlaydigan, o'lchangan **pilot**. Ommaviy ishga tushirish uchun quyidagi bandlar kerak.
Har bandda: nima uchun, nima qilinadi, kim, qancha vaqt, qachon "bajarildi" deymiz.

## 0. Hozirgi holat (o'lchangan)

| Ko'rsatkich | Natija |
|---|---|
| To'g'ri modda 1-o'rinda / birinchi 6 tada (kodlanmagan 55 savol) | 62% / 80% |
| Javob to'g'riligi (dev, 59 savol; baholovchi: boshqa AI) | 91–98% |
| Mavzudan tashqari savolni rad etish / to'g'ri savolni noto'g'ri rad etish | 95–100% / 1–7% |
| Javobga qonunda yo'q shart qo'shilishi | 2–6% |
| Xotira, javob vaqti | ~230 MB, retrieval ~3 s, to'liq javob ~6–10 s |
| Rejim | tejamkor (Jev o'chiq; Jev bilan 1-o'rin ~81%) |

## 1. Muddatli qarorlar (hammasidan avval)

### 1.1. Javob modeli 2026-10-30 dan keyin (rahbar + siz)
Meta krediti shu kuni tugaydi; ikkala kalit tugasa tizim faqat "manbalar matni" rejimida qoladi.
Variantlar (oyiga 30 000 savol, ~40% kesh):
| Variant | Taxminiy narx | Izoh |
|---|---|---|
| Meta pullik tarif | Meta narxini aniqlash kerak | hozirgi sifat saqlanadi |
| OpenRouter, Claude Haiku 5.5 | ~$0.0009/javob → ~$16/oy | $15 chegarasidan biroz yuqori |
| OpenRouter, arzon "flash" model (Qwen/DeepSeek/GLM, ~$0.0003/javob) | ~$6/oy | **o'zbekcha huquqiy sifati o'lchanmagan** |
Qadamlar: (a) Meta narxini so'rash; (b) hisobni to'ldirib 2–3 arzon modelni dev to'plamda sinash (`scripts/stress_eval.py --only @…dev_split.json`,
bir model ~$0.05–0.1); (c) tanlov mezoni: to'g'ri javob ≥ 90%, "ortiqcha shart" ≤ 3%, narx ≤ $15/oy.
Muddat: 2 kun (pul va rahbar qarori bo'lsa). **Bajarildi:** 30-oktabrgacha generatsiya provayderi tanlangan va `.env` da.

### 1.2. Pul (OpenRouter)
Hozir $0.44. Embedding deyarli bepul (~$0.000001/savol), Jev $0.0006/savol. Jevni qaytarish +19 punkt aniqlik beradi.
Qaror: $10–15 to'ldirish (Jev ~25 000 savolga yetadi) yoki tejamkor rejimda qolish.

## 2. Yuristlar tekshirgan sinov to'plami (eng muhim sifat qadami)

**Muammo:** barcha hozirgi baholar AI tomonidan yozilgan savollar va AI baholovchi bilan. Yuridik mahsulotda bu yetarli emas.
**Qilinadi:**
1. 100 ta haqiqiy savol (Huquq+ bot jurnali, volontyorlar savollari; shaxsiy ma'lumotlar olib tashlangan), 8–10 soha, kirill/ruscha ham.
2. Yurist har biriga to'g'ri moddani va "to'g'ri javob" tezisini yozadi (`data/golden_dataset/` formatida, `expected_ids`).
3. Tizim javoblarini yurist ko'r holda baholaydi: to'g'ri / qisman / xato + sabab turi (ortiqcha shart, noto'g'ri modda, eskirgan norma, rad etish xatosi).
4. Xato turlari bo'yicha 1–2 haftalik tuzatish, qayta o'lchash. Bu to'plam **hech qachon sozlash uchun ishlatilmaydi**.
Kim: 1–2 yurist, ~3 kun. **Bajarildi:** yurist bahosida "to'g'ri" ≥ 90%, "xato" ≤ 3%, natijalar hisobotda.

## 3. Serverga joylash va ishonchlilik

Hali tekshirilmagan: Docker build, systemd, nginx, haqiqiy yuklama, monitoring.
1. VPS (2 vCPU / 4 GB) da `docker compose up` yoki systemd; `.env` (ADMIN_API_KEY majburiy, `ADMIN_LOOPBACK_ENABLED` o'chiq), HTTPS (Caddy/nginx), nginx `X-Forwarded-For` uzatsin.
2. `scripts/backup.sh --keep 14` ni kunlik cron/timer bilan; haftada bir `restore_store.py` ni sinov nusxada tekshirish.
3. Yuklama sinovi: 20 parallel foydalanuvchi, p95 < 20 s, xotira < 700 MB, Meta/OpenRouter 429 holatlari.
4. Monitoring: `/health` ni tashqi tekshiruv (UptimeRobot kabi), log yig'ish (hozir INFO loglar o'chiq: `LOG_LEVEL` qo'llanmaydi — tuzatish kerak), xato ogohlantirish (Telegram).
5. CI (GitHub Actions): `pytest`, `gitleaks`, Docker build; `requirements.txt` ni versiyaga qotirish.
Muddat: 2–3 kun. **Bajarildi:** 24 soatlik uzluksiz ishlash, 20 foydalanuvchi sinovi, zaxiradan tiklash isbotlangan.

## 4. Ma'lumotlar yangiligi

1. Lex.uz bilan haftalik sinxronlash: `scripts/build_disability_corpus.py refresh` ni timer bilan ishga tushirish, o'zgarish hisoboti; yangilangandan keyin javob keshini tozalash (`ANSWER_VERSION` ni oshirish).
2. Bekor qilingan/o'zgargan normalarni belgilash (hozir barcha 28 111 birlik "active"): `status` va `superseded_by` ni to'ldirish.
3. Reestrdagi 11 ta yuklanmagan akt (VMQ-269 vasiylik va b.) + Qoraqalpog'iston qonuni + Huquq+ keltirgan ~21 hujjat.
Muddat: 3–4 kun. **Bajarildi:** avtomatik yangilanish hisoboti, status maydoni to'lgan, yangi aktlar sinovdan o'tgan.

## 5. Sifatni oshirish (2-bandning natijalariga qarab)

- Jevni qaytarish yoki Meta/boshqa ranker oynasini kengaytirish (hozir 30×1200).
- Xato yozilgan kirill savollar uchun tuzatuvchi qadam; bir necha modda kerak bo'lgan savollar (sub-savollar eshigini sozlash).
- "Ortiqcha shart" xatosi: promptda "faqat matndagini qayta ayt", gap darajasidagi iqtibos tekshiruvi (da'vo-tekshiruv o'lchandi: foyda bermadi, shuning uchun boshqa yo'l).
- Chegara mavzulardagi noto'g'ri rad etish (7%): scope savolini yuristlar bilan aniqlash.
Muddat: 1–2 hafta.

## 6. Hali tekshirilmagan funksiyalar

Admin panel (hujjat qo'shish, Huquq+ paneli), "volontyor javobini AI bilan tekshirish" (`REVIEW_MODEL`, `review_eval.py` hech ishlatilmagan),
Telegram bot ↔ API to'liq oqimi, `/assistant` va OpenAI-mos endpointlar. Har biri uchun qisqa qabul sinovi + natija jadvali.
Foydalanish qulayligi: haqiqiy ekran o'quvchi (NVDA/TalkBack) bilan nogironligi bo'lgan foydalanuvchilar sinovi (ko'rish, eshitish bo'yicha), telefon.
Muddat: 3–4 kun. **Bajarildi:** har funksiya uchun "ishlaydi / ishlamaydi" ro'yxati.

## 7. Xavfsizlik va maxfiylik (yakunlash)

- Tuzuk tokeni: yangilanishini kuzatish. Ochiq tarixdagi eski qiymat endi foydasiz bo'lishi kerak.
- GitHub secret scanning yoqilgan (siz qildingiz) — ogohlantirishlarni kuzatish. Kalitlarni har 6 oyda almashtirish jadvali.
- Maxfiylik: savollar 24 soat keshda, fikr-mulohaza saqlanadi. Foydalanuvchiga ko'rinadigan siyosat matni va saqlash muddatini rahbar/yurist bilan tasdiqlash.
- Yuridik ogohlantirish matnini (disclaimer) yurist tasdiqlasin.

## 8. Pilot (2–4 hafta) va keyin qaror

1. 10–20 ta volontyor/yurist 2 hafta davomida real savollarda foydalanadi; har javobda "foydali/foydasiz" tugmasi (mavjud).
2. Haftalik hisobot: foydalanuvchilar soni, rad etish ulushi, salbiy baholar, yuristlar topgan xatolar, narx.
3. **Ommaviy ishga tushirish qarori** (go): yurist bahosida to'g'ri ≥ 90% (2-band), serverda uzluksiz ishlash (3-band), provayder tanlangan va narx ≤ $15/oy (1-band), asosiy funksiyalar sinalgan (6-band), maxfiylik matni tasdiqlangan.

## Vaqt jadvali (taxminiy, kalendar hafta)

| Hafta | Ish |
|---|---|
| 1 (23–30 okt) | 1.1 va 1.2 qarorlar, provayder sinovi; 3-band (server) boshlanadi; 4-band (yangi aktlar) |
| 2 | 2-band: yuristlar to'plami yozadi va baholaydi; 6-band sinovlari; CI, monitoring |
| 3 | 5-band: xato turlari bo'yicha tuzatish; qayta o'lchash; 4-band avtomatik yangilash |
| 4–5 | Pilot (volontyorlar), haftalik hisobotlar |
| 6 | Go / no-go qarori |

## Sizdan va rahbardan kerak bo'ladigan narsalar

1. Meta narxi va 30-oktabrdan keyingi provayder bo'yicha qaror; OpenRouter uchun $10–15.
2. 1–2 yurist (~3 kun) va 10–20 pilot foydalanuvchi.
3. Server (VPS) kirish huquqi va domen.
4. Maxfiylik siyosati va ogohlantirish matnini tasdiqlovchi shaxs.
