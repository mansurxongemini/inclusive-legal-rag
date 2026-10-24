# Kalitlarni almashtirish va git tarixini tozalash rejasi (push'dan oldin)

Tayyorlandi: 2026-10-23. **Hech narsa bajarilmagan:** tarix qayta yozilmagan, push qilinmagan, `remote.origin.pushurl=DISABLED` va
`.git/hooks/pre-push` hali yoqilgan. Quyidagi holat `git log -G` / `git merge-base` bilan tekshirilgan (kalit qiymatlari hech qaerda chop etilmagan).

## 1. Holat: nima qayerda

| # | Sir | Qayerda | Push qilinganmi | Xavf |
|---|---|---|---|---|
| 1 | Gateway klient kaliti `hpk_live_…` (`key_0b43ba545ae6b2b8`, klient `cli_76e865458a19a087` — "HuquqPlus Telegram bot (test)", ruxsatlar `ask,feedback,review`, **faol**) | `scripts/eval_3way_sample.py`: commit `13001dc` qo'shgan, `22c9a78` olib tashlagan | **Yo'q** (`origin/feat/editorial-qa-huquqplus` dan 14 commit oldinda) | hali oshkor emas; push qilinsa public repoga chiqadi |
| 2 | Tuzuk JWT (Bearer token) | `scripts/harvest_tuzuk_api.py`: commit `ea3093c` qo'shgan, `9f6273f` olib tashlagan | **Ha, `origin/main` va `origin/feat/editorial-qa-huquqplus` da** (public repo) | **allaqachon oshkor** — tarixni tozalash uni qaytarib ololmaydi |
| 3 | GitHub shaxsiy token (PAT) | `origin` URL ichida (`.git/config`), tarixda emas | — | mashinadagi fayl; sessiya buyruqlari chiqishida maskalandi |
| 4 | `.env` dagi kalitlar: OpenRouter (`EMBEDDING_API_KEY`), Meta (`OPENROUTER_API_KEY`, `plus_META_AI_API_KEY`) | faqat `.env` (gitignore), tarixda **yo'q** | — | Ammo bu ish sessiyasining jurnalida chiqib ketgan: `OPENROUTER_API_KEY` qiymati bir buyruq chiqishida maskalanmay chop etilgan, `EMBEDDING_API_KEY` esa yordamchi agent jurnalida |

Boshqa sirlar qidirildi (`sk-or-v1-`, `sk-…`, `ghp_`/`github_pat_`, `AIza…`, Meta `LLM_<raqam>_…`, `TOKEN/SECRET/API_KEY = "…"`): tarixda topilmadi.

## 2. Tartib

### 2.1. Avval almashtirish (tarixdan tozalashdan MUHIMROQ)

1. **Gateway kaliti** (bot ishlashda qolishi uchun ketma-ketlikka rioya qiling):
   ```bash
   .venv/bin/python scripts/rotate_client_key.py --list                              # cli_76e865458a19a087 ning kalitlari
   .venv/bin/python scripts/rotate_client_key.py --client-id cli_76e865458a19a087    # yangi kalit chiqadi (bir marta ko'rsatiladi)
   # yangi kalitni botning .env dagi RAG_API_KEY ga yozing, botni qayta ishga tushiring, javob kelishini tekshiring
   .venv/bin/python scripts/rotate_client_key.py --client-id cli_76e865458a19a087 --revoke-old   # sizib chiqqan kalit va boshqa eskilari bekor
   ```
   Eslatma: bu klientda 3 ta faol kalit bor (`key_db051…`, `key_69bcb…`, `key_0b43b…`); `--revoke-old` uchalasini ham bekor qiladi —
   bot yangi kalitga o'tganini tekshirmasdan qilmang. Boshqa klient (`cli_fd65d90075fba690`, faolsiz) ning 4 kaliti ham "faol" deb turibdi:
   klient o'chiq bo'lsa ham, ularni `--revoke-old` bilan tozalang.
2. **Tuzuk JWT**: Tuzuk tomonda hisobdan chiqib qayta kiring / tokenni bekor qiling (JWT `ea3093c` da public repoda turibdi). Yangisini faqat
   `.env` yoki muhit o'zgaruvchisida saqlang (`scripts/harvest_tuzuk_api.py` hozir uni fayldan olmaydi).
3. **GitHub PAT**: GitHub → Settings → Developer settings → Personal access tokens → eskisini revoke; yangisini `gh auth login` yoki
   credential helper orqali saqlang, `origin` URL ni tokensiz qiling:
   `git remote set-url origin https://github.com/mansurxongemini/inclusive-legal-rag.git`.
4. **Meta va OpenRouter kalitlari**: sessiya jurnalida chiqqani uchun almashtirish tavsiya etiladi (Meta paneli, OpenRouter → Keys).
   Yangisini `.env` ga yozing; kod `PLUS_META_AI_API_KEY` ni avtomatik ishlatadi (HTTP 402 da).

### 2.2. Push qilinmagan 14 commitni tozalash (1-sir)

Commitlar hali hech kimga ko'rinmagan, shuning uchun ularni qayta yozish xavfsiz. Avval zaxira (**bundle ichida kalit bor — repodan tashqarida saqlang, rotatsiyadan keyin o'chiring**):

```bash
git bundle create ~/rag-before-clean.bundle --all
git branch backup/before-clean
```

Tozalash (faqat `origin/feat/editorial-qa-huquqplus..HEAD` oralig'i qayta yoziladi; asos commit `34c65e5` o'zgarmaydi, shuning uchun keyin oddiy `git push` ishlaydi):

```bash
git filter-branch -f --tree-filter \
  'test -f scripts/eval_3way_sample.py && sed -i -E "s/hpk_live_[A-Za-z0-9_-]+/REDACTED/g" scripts/eval_3way_sample.py || true' \
  origin/feat/editorial-qa-huquqplus..HEAD
rm -rf .git/refs/original && git reflog expire --expire=now --all && git gc --prune=now
```

Tekshiruv (ikkalasi ham bo'sh chiqishi kerak):

```bash
git log --all -G'hpk_live_[A-Za-z0-9_-]{20,}' --oneline
git grep -I -E 'hpk_live_[A-Za-z0-9_-]{20,}' $(git rev-list origin/feat/editorial-qa-huquqplus..HEAD) | head -1
```

Muqobil (kamroq xavfli, lekin tarixda "olib tashlash" izi qoladi): `git rebase -i 34c65e5` da `13001dc` ni `edit` qilib faylni tuzatish — bu
muhitda interaktiv rebase ishlamaydi, shuning uchun yuqoridagi `filter-branch` tavsiya etiladi.

### 2.3. Public tarixdagi JWT (2-sir): tarixni qayta yozish kerakmi?

- **Birinchi navbatda JWT ni Tuzuk tomonda bekor qiling** (2.1-bandning 2-qadami). Shundan keyin tarixdagi qiymat foydasiz bo'ladi.
- Tarixni baribir tozalashni xohlasangiz: `origin/main` va ikkala feature branchni **force-push** qilish kerak; bu ochiq **PR #2** ni, barcha klonlarni
  va forklarni buzadi, GitHub'ning `refs/pull/*` keshida eski commitlar qoladi (GitHub Support orqali tozalatiladi). Foyda kam, xarajat katta —
  tavsiya: **qayta yozmang**, faqat rotatsiya + secret scanning.
- Qayta yozish qaroriga kelsangiz: `pip install git-filter-repo`, `replacements.txt` (`<token>==>REDACTED`), `git filter-repo --replace-text replacements.txt`,
  keyin `git push --force-with-lease` (har bir branch uchun), PR #2 ni qayta ochish, hamkorlarga qayta klon qilishni aytish. Buni faqat siz aytganingizda bajaraman.

## 3. Push'dan oldingi tekshiruv ro'yxati

1. [ ] 2.1 dagi 4 ta rotatsiya bajarilgan, bot yangi kalit bilan ishlayapti.
2. [ ] 2.2 tozalash bajarilgan va ikki tekshiruv buyrug'i bo'sh.
3. [ ] `.venv/bin/python -m pytest -q` — hammasi o'tadi (hozir 519 o'tadi, 1 skip).
4. [ ] `git status`: `data/legal_rag.db-shm` / `-wal`, `.env`, `data/store/` staged emas; `.claude/` ni `.gitignore` ga qo'shing (hozir untracked, scratch ma'lumotlar bor).
5. [ ] `git log origin/feat/editorial-qa-huquqplus..HEAD --stat | grep -iE "\.env|\.db$"` — bo'sh.
6. [ ] Push blokini olib tashlash: `git config --unset remote.origin.pushurl && rm .git/hooks/pre-push`.
7. [ ] Oddiy push (force EMAS): `git push origin feat/editorial-qa-huquqplus`.
8. [ ] Push'dan keyin: GitHub → Settings → Code security → **Secret scanning** va **Push protection** ni yoqing (public repo uchun bepul);
   CI ga `gitleaks` qadamini qo'shing (hozir CI yo'q).

## 4. Nega bunday bo'ldi / qayta takrorlanmasligi uchun

- Kalit skriptga qattiq yozilgan edi; endi `GATEWAY_API_KEY` muhit o'zgaruvchisidan olinadi (faqat shu skript o'qiydi, `.env.example` da yo'q).
- Bu ish davomida agentlarga `.env` ni `cat`/`grep` qilishni taqiqlash va kalit nomlarini faqat maskalangan ko'rsatish qoidasi kerak
  (bir marta maskalash xato ketib, Meta kaliti jurnalga tushdi).

## 5. Bajarilgan (2026-10-23)

- Sizib chiqqan gateway kaliti (`key_0b43ba545ae6b2b8`) bekor qilindi; botning o'z kaliti (`.env` dagi `RAG_API_KEY`, `key_db051…`) boshqa kalit edi va
  ishlashda qoladi (tekshirildi: eskisi "qabul qilinmaydi", botniki "valid"). Shu sabab bot kaliti almashtirilmadi.
- Push qilinmagan 15 commit zaxira (`~/rag-before-clean.bundle`, repodan tashqarida, ichida eski kalit bor — kalit bekor qilingani uchun xavfi kam,
  baribir tekshiruvdan keyin o'chiring) olingach, alohida klonda `filter-branch` bilan tozalandi va qaytarildi. Natija: `feat/editorial-qa-huquqplus`,
  `main`, `feat/official-lexuz-disability-corpus` va ularning `origin/*` nusxalarida kalit **0** commitda; oxirgi daraxt (tree) avvalgisi bilan bir xil;
  asos commit `34c65e5` o'zgarmagan, shuning uchun keyin oddiy `git push` yetadi.
- `origin` URL tokensiz qilindi (eski GitHub PAT `.git/config` dan ketdi); yangi token hech qayerda saqlanmadi. Push bloki (`pushurl=DISABLED`, `pre-push`) hali yoqilgan.
- `.claude/` `.gitignore` ga qo'shildi.

**Qolgan:** (1) Tuzuk JWT va eski GitHub PAT ni o'zingiz bekor qiling; (2) `claude/busy-snyder-a00c9a` filiali (boshqa sessiyaning to'xtatilgan worktree'si)
hali eski commitlarni ushlab turibdi — ichidagi ishlar allaqachon asosiy filialda; sessiyani arxivlagach
`git worktree remove --force .claude/worktrees/busy-snyder-a00c9a && git branch -D claude/busy-snyder-a00c9a` bilan o'chiring (hech qachon `git push --all` qilmang);
(3) push'ni faqat siz buyurganingizda, tokenni vaqtincha muhit o'zgaruvchisi orqali berib bajaraman.
