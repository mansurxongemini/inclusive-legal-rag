# Huquq+ RAG Webhook (WordPress plagini)

huquqplus.uz'da maqola **nashr qilinganda, tahrirlanganda, nashrdan olinganda yoki o'chirilganda** AI yordamchi
bazasi (RAG) shu zahoti yangilanishi uchun.

## Qanday ishlaydi

1. Muharrir maqolani saqlaydi. Plagin faqat qisqa xabar tayyorlaydi:
   `{"event": "upsert" | "delete", "post_id": 2966, "lang": "uz", ...}`.
   Xabarda maqola matni **bo'lmaydi**.
2. Xabar WP-Cron orqali fonda yuboriladi. Shuning uchun RAG serveri sekin ishlasa yoki o'chiq bo'lsa ham,
   maqolani saqlash sekinlashmaydi. Yetib bormagan xabar 2, 4, 8 va 16 daqiqadan keyin qayta yuboriladi.
3. RAG serveri imzoni tekshiradi. Keyin maqolani `https://huquqplus.uz/wp-json/wp/v2/posts/<id>` dan **o'zi**
   oladi va bazada yangilaydi yoki o'chiradi.
4. Xabar umuman yetib bormasa, RAG serveri har soatda saytni o'zi tekshiradi. Bu zaxira sinxronlash.

Xavfsizlik:
- Har xabar `HMAC-SHA256` bilan imzolanadi.
- Server 5 daqiqadan eski xabarni va qayta yuborilgan (bir xil `event_id`) xabarni qabul qilmaydi.
- Kalit faqat `wp-config.php` da saqlanadi, ma'lumotlar bazasida emas.
- Kalit begona qo'lga tushsa ham, u orqali bazaga matn kiritib bo'lmaydi. Server matnni faqat
  huquqplus.uz'ning o'zidan oladi.

## O'rnatish

1. Kalit yarating (kamida 32 belgi):
   ```bash
   openssl rand -hex 32
   ```
2. **RAG serverida** `.env` fayliga yozing va serverni qayta ishga tushiring:
   ```
   HUQUQPLUS_WEBHOOK_SECRET=<yaratilgan kalit>
   ```
3. **WordPress serverida** `wp-config.php` ga `/* That's all, stop editing! */` qatoridan **oldin** qo'shing:
   ```php
   define('HUQUQPLUS_RAG_WEBHOOK_URL', 'https://<rag-server-manzili>/api/v1/webhooks/huquqplus');
   define('HUQUQPLUS_RAG_WEBHOOK_SECRET', '<o\'sha kalit>');
   ```
4. `huquqplus-rag-webhook` papkasini `wp-content/plugins/` ga yuklang (yoki zip qilib *Plaginlar → Yangi qo'shish →
   Yuklash* orqali o'rnating) va faollashtiring.
5. *Asboblar → Huquq+ RAG Webhook* sahifasida **"Sinov xabarini yuborish"** tugmasini bosing. Natija
   jadvalda `OK` bo'lishi kerak.

RAG serveri internetdan **HTTPS** orqali ochiq bo'lishi kerak. WordPress serveri unga so'rov yubora olishi shart.

## Muammolar

| Jadvaldagi natija | Sababi |
|---|---|
| `Xato -1` | `wp-config.php` da URL yoki kalit yo'q |
| `Xato 0: cURL error ...` | RAG serveriga ulanib bo'lmadi (manzil, DNS, firewall, SSL) |
| `Xato 401` | Kalitlar mos emas yoki serverlardagi soat 5 daqiqadan ko'proq farq qiladi (NTP'ni tekshiring) |
| `Xato 503` | RAG serverida `HUQUQPLUS_WEBHOOK_SECRET` o'rnatilmagan |

Saytda doimiy cron bo'lmasa (`DISABLE_WP_CRON`), xabarlar tizim cron'i ishga tushganda yuboriladi.
Bunday holatda tizim cron'ini har daqiqada ishga tushiring:
`* * * * * curl -s https://huquqplus.uz/wp-cron.php >/dev/null`.
