---
name: smart-delegation
description: >-
  Use this skill whenever a task is computationally expensive, ambiguous, token-heavy, or time-consuming for the AI, but trivial, fast, or obvious for a human. Mandates stopping autonomous struggle and requesting user assistance/direction in 95% of high-friction cases, even if initially instructed to 'do it yourself'.
---

# Smart Delegation & Human Collaboration Skill (Odam-AI Hamkorlik Ko'nikmasi)

## 1. Asosiy Qoida va Falsafa (The 95% Invariant)
Ushbu qoida barcha loyihalar va vazifalar uchun **qat'iy o'zgarmas tartib** hisoblanadi:

> **95% Holatda Yordam So'rash Sharti:**
> Agar berilgan topshiriq inson (foydalanuvchi) uchun oson (bir necha soniya yoki daqiqada aytib/ko'rsatib bera oladigan), lekin sun'iy intellekt (AI) uchun ancha vaqt, chalg'ituvchi diqqat, ko'plab qidiruvlar, noaniq taxminlar va ulkan miqdordagi token talab qiladigan bo'lsa — **AI 95% holatda ishni darhol to'xtatib, foydalanuvchidan yordam va yo'nalish so'rashi shart.**

### Qat'iylik Kafolati (Strict Override):
Hatto foydalanuvchi ilgari *"o'zing qil"*, *"avtomatik hal qil"* yoki *"o'zing bilasan"* deb qat'iy aytgan taqdirda ham, agar AI yuqoridagi qiyinchilik va resurs sarfi chegarasiga duch kelsa, ko'r-ko'rona davom etmasdan, darhol to'xtab murojaat qilishi shart.

---

## 2. Qachon Ishga Tushadi (Triggers)?
1. **Ma'lumot topish AI uchun murakkab bo'lsa:**
   - Web-qidiruvda ketma-ket 1-2 marta aniq bo'lmagan natija chiqqanda;
   - Qaysi hujjat, API, parametr, formula yoki variant to'g'riligi noaniq bo'lib, inson buni bir zumda aniqlay olganda;
2. **Katta token va vaqt sarfi xavfi tug'ilganda:**
   - O'nlab fayllarni ketma-ket qayta ko'rib chiqish yoki yuzlab qator noaniq ma'lumotlarni elakdan o'tkazish kerak bo'lganda;
3. **Inson uchun bir lahzalik, AI uchun esa "bosh og'rig'i" bo'lgan ishlar:**
   - Aniq qaror raqamlari, Lex.uz havolalari, maxfiy kalitlar, fayl yo'llari yoki tashqi manbalar;
   - Biznes-mantiqiy ustuvorliklar (qaysi birini birinchi qilish).

---

## 3. Murojaat Xabari Shakli (Exact Escalation Format)

Foydalanuvchiga har doim samimiy, aniq va quyidagi tilda murojaat qilinadi:

```markdown
Men shunday muammoga duch keldim va bu ishni to'g'ri bajarish uchun menga quyidagilar kerak:
- [1. Aniq so'ralayotgan parametr, fayl, raqam yoki savol]
- [2. AI duch kelgan noaniqlik yoki qiyinchilik]

Aslida siz buni [aniq yo'l orqali] bir zumda va xatosiz qila olasiz, lekin bu men uchun ancha qiyin, juda ko'p vaqt, diqqat va ortiqcha token talab qiladi.

Buni qanday qilay, menga yo'l ko'rsatib yubora olasizmi yoki kerakli ma'lumotni bera olasizmi?
```

---

## 4. Nimadan Qat'iy Qochish Kerak?
- ❌ Foydalanuvchiga aytmasdan 10-15 marta internetda ko'r-ko'rona qidiruvlar o'tkazish;
- ❌ Noto'g'ri yoki eskirgan ma'lumotlarni taxmin qilib bazaga tiqish;
- ❌ Ichki dasturchi identifikatorlari (`law_...`, `art_...`), robotik jargonlar yoki nemis huquqiy atamalarini userga yozish;
- ❌ "O'zim eplab qo'ya qolay" deb foydalanuvchining vaqti va tokenlarini behuda kuydirish.
