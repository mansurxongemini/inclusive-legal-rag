# Serverga joylash: Telegram bot turgan server

Bu qo'llanma `debian` serveri (2 yadro Xeon E5-2670, 3.8 GB RAM, 48 GB disk, Docker, bot + celery + MariaDB + Redis) uchun
yozilgan. RAG servisi o'sha Docker tarmog'ida ishlaydi: bot unga `http://legal-rag-api:8000` orqali murojaat qiladi, hech qanday
port internetga ochilmaydi.

## 1. Sig'adimi

| Resurs | RAG ishlatadi | Serverda bor |
|---|---|---|
| RAM | bo'sh turganda ~80 MB, ishlaganda ~330 MB (konteyner chegarasi 800 MB) | 2.1 GB bo'sh |
| Disk | imij 241 MB + baza ~490 MB + zaxira (har biri ~490 MB, 7 ta = 3.4 GB) | 34 GB bo'sh |
| CPU | bitta savolga ~0.5 yadro-soniya (asosan to'liq matnli qidiruv); qolgan ~20 soniya modelni kutish | 2 yadro, yuklama 0.00 |
| Tarmoq | `openrouter.ai` ga chiquvchi HTTPS; kiruvchi port kerak emas | bor |

**Protsessor haqida muhim narsa.** E5-2670 faqat AVX biladi, AVX2 yo'q. Oldingi vektor bazasi (LanceDB) bunday protsessorda
`import` paytidayoq "Illegal instruction" bilan qulardi. U olib tashlandi: vektorlar SQLite da, qidiruv numpy da. Butun server
Sandy Bridge protsessorini emulyatsiya qilib ishga tushirildi va savolga javob berdi (QEMU `-cpu SandyBridge`).

Konteyner `oom_score_adj: 500` bilan ishlaydi: xotira tugab qolsa yadro birinchi navbatda RAG ni to'xtatadi, MariaDB ni emas.
Protsessor ustuvorligi bot va bazadan past (`cpu_shares: 256`): server band bo'lsa RAG sekinlashadi, bot va baza emas.

## 2. Nimalarni serverga ko'chirish kerak

Dasturchi kompyuteridan (git push qilinmaydi, to'g'ridan-to'g'ri nusxa):

```bash
rsync -a --exclude .git --exclude .venv --exclude data --exclude eval --exclude '*.core' ./ bot@SERVER:~/legal-rag/
rsync -a data/store/ bot@SERVER:~/legal-rag/data/store/          # 490 MB: qonunlar, vektorlar, tahririyat bazasi
rsync -a --exclude built_articles.json data/sources/ bot@SERVER:~/legal-rag/data/sources/
```

`data/store` ni ko'chirmasdan ishga tushirmang: bo'sh bazada servis faqat bitta namunaviy qonun bilan boshlanadi.

## 3. Ishga tushirish (serverda)

```bash
cd ~/legal-rag
cp .env.example .env
nano .env        # OPENROUTER_API_KEY, ADMIN_API_KEY (openssl rand -hex 32), TRUSTED_PROXIES=0
mkdir -p data/cache data/backups
sudo chown -R 1001:1001 data/store data/cache data/sources data/backups     # konteyner foydalanuvchisi 1001
sudo docker network ls | grep huquqplusbot                                  # botning tarmog'i: odatda huquqplusbot_default
ss -ltn | grep ':8000 '                                                     # 8000 band bo'lmasligi kerak (aks holda RAG_PORT=8010 .env ga)
sudo docker compose -f docker-compose.yml -f docker-compose.bot.yml up -d --build
```

Tarmoq nomi boshqacha bo'lsa `.env` ga `BOT_NETWORK=<nom>` qo'shing. Tekshirish:

```bash
curl http://127.0.0.1:8000/health                      # {"status":"healthy",...}
sudo docker compose ps                                 # legal-rag-api: Up (healthy)
sudo docker stats --no-stream legal-rag-api            # xotira ~80-330 MB
```

`/health/details` (admin kaliti bilan) da `articles_indexed` 29 418 va `embedding.mismatch` bo'sh bo'lishi kerak.

## 4. Botni ulash

1. Admin panelga SSH tunnel orqali kiring: `ssh -L 8000:127.0.0.1:8000 bot@SERVER`, brauzerda `http://localhost:8000/admin`
   (`ADMIN_API_KEY` so'raladi).
2. **Integratsiyalar -> Yangi mijoz**, turi **server**. `hpk_live_...` kaliti bir marta ko'rsatiladi: botning `.env` fayliga yozing.
3. Bot (va celery worker) `.env` fayliga: `HUQUQPLUS_AI_URL=http://legal-rag-api:8000` va `HUQUQPLUS_AI_KEY=hpk_live_...`.
4. Bot `POST /api/v1/assistant/ask` ni chaqiradi (tayyor aiogram namunasi: `integrations/api/README.md`, 4-bo'lim). Muhim:
   - so'rov kutish vaqti kamida 90 soniya (javob odatda ~20, ba'zan ~40 soniya),
   - kutish paytida "yozmoqda" holatini ko'rsatib turing,
   - `503` kelsa foydalanuvchiga "birozdan so'ng qayta urinib ko'ring" deng (model vaqtincha ishlamayapti yoki oylik limit tugagan:
     servis modelsiz javob yozmaydi).

Bot konteynerlari `huquqplusbot_default` tarmog'ida, shuning uchun alohida sozlash kerak emas.

## 5. Zaxira nusxa va yangilash

Kunlik zaxira (root crontab: `sudo crontab -e`):

```
0 3 * * * docker exec legal-rag-api python scripts/backup_store.py --dest /app/data/backups --keep 7
```

Nusxa `~/legal-rag/data/backups/` da, har bir nusxa tekshiriladi (integrity_check, vektorlar soni). Tiklash: servisni to'xtating,
`python scripts/restore_store.py data/backups/<nusxa>`.

Yangi versiya: kodni yuqoridagi `rsync` bilan yangilang, so'ng `sudo docker compose -f docker-compose.yml -f docker-compose.bot.yml up -d --build`.
`data/` papkasi tegilmaydi. Lex.uz dan yangilash admin paneldagi **Lex.uz'dan yangilash** tugmasi orqali.

## 6. Nima uchun ishlamay qolishi mumkin

| Belgi | Sabab | Nima qilish |
|---|---|---|
| Bot `503` oladi | OpenRouter hisobi/oylik limit tugagan yoki kalit rad etilgan | `/health/details`: `openrouter_budget`; kalitni to'ldiring yoki `OPENROUTER_MONTHLY_BUDGET_USD` ni oshiring (har yangi savol ~$0.0009) |
| Konteyner qayta ishga tushyapti | xotira 800 MB dan oshdi | `sudo docker logs legal-rag-api`, `docker inspect ... OOMKilled` |
| `unable to open database file` | `data/` egasi 1001 emas | `sudo chown -R 1001:1001 data/...` |
| Bot servisni topolmaydi | boshqa tarmoq nomi | `BOT_NETWORK` ni `docker network ls` dagi nomga qo'ying |
| Javoblar kam manba beradi | bazaga noto'g'ri nusxa (bo'sh `data/store`) | bazani qayta ko'chiring, 3-bo'limdagi tekshiruvni takrorlang |

Server 269 kun uzluksiz ishlagan: yadro va paketlarni yangilash (`apt upgrade`, qayta yoqish) tavsiya etiladi, lekin RAG buni talab qilmaydi.
