# Huquq+ yordamchi API — integratsiya qo'llanmasi

Bu API orqali istalgan tizim (Telegram bot, sayt, mobil ilova, hamkor servis, OpenAI formatini tushunadigan vosita)
nogironligi bo'lgan shaxslar huquqlari bo'yicha yordamchidan javob oladi. Javoblar faqat korpusdagi rasmiy Lex.uz
normalari, Huquq+ maqolalari va huquqshunoslar tasdiqlagan savol-javoblarga tayanadi; har bir javobda manbalar
qaytariladi.

Quyidagi misollarda `https://AI_SERVER` — RAG serveringizning HTTPS manzili (masalan `https://ai.huquqplus.uz`).

## 1. Kalit olish

1. Admin panel: `/admin-v2` → **Integratsiyalar** → **Yangi mijoz**.
2. Turini tanlang:
   - **server** — bot, sayt backend'i, hamkor servis uchun. Kalit `hpk_live_…` bilan boshlanadi va **maxfiy**.
   - **browser** — sayt sahifasining o'zida (JavaScript) ishlatish uchun. Kalit `hpk_pub_…` bilan boshlanadi va
     faqat ko'rsatilgan domen(lar)dan ishlaydi (masalan `https://huquqplus.uz`).
3. Kalit **faqat bir marta** ko'rsatiladi — darhol xavfsiz joyga (bot `.env` fayli, `wp-config.php`) saqlang.
4. Limitlar: daqiqalik so'rovlar (mijoz bo'yicha), bitta foydalanuvchi uchun daqiqalik so'rovlar va kunlik kvota.

Kalit almashtirish: **Yangi kalit** → integratsiyani yangi kalitga o'tkazing → eskisini **Bekor qilish**.

## 2. Xavfsizlik qoidalari

- Kalit faqat sarlavhada yuboriladi: `Authorization: Bearer <kalit>` (yoki `X-API-Key: <kalit>`). URL'dagi
  `?api_key=` / `?token=` umuman o'qilmaydi.
- Server kaliti brauzerdan kelsa (so'rovda `Origin` sarlavhasi bo'lsa) `403 secret_key_in_browser` qaytadi —
  bunday kalit sizib chiqqan hisoblanadi, uni almashtiring.
- Brauzer kaliti faqat ruxsat etilgan domendan ishlaydi va IP bo'yicha ham cheklanadi.
- Faqat HTTPS. Server reverse proxy (nginx) ortida bo'lsa, uvicorn'ni
  `--proxy-headers --forwarded-allow-ips=<proxy IP>` bilan ishga tushiring, aks holda IP limitlari hamma uchun bitta
  bo'lib qoladi.
- `user_id` — sizning tizimingizdagi foydalanuvchi id'si (masalan Telegram id). Server uni saqlamaydi: faqat
  HMAC taxallusi (`user_ref`) saqlanadi. Savol-javoblar jurnali `ASSISTANT_LOG_RETENTION_DAYS` (standart 90) kundan
  keyin o'chiriladi.

## 3. Asosiy endpoint: `POST /api/v1/assistant/ask`

```bash
curl -X POST "https://AI_SERVER/api/v1/assistant/ask" \
  -H "Authorization: Bearer $HUQUQPLUS_AI_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "1-guruh nogironligi bor shaxsga qanday soliq imtiyozlari bor?", "user_id": "tg:123456789", "format": "telegram_html"}'
```

So'rov maydonlari:

| Maydon | Turi | Izoh |
|---|---|---|
| `question` | string, 1–4000 | Savol (o'zbek lotin/kirill, rus, ingliz) |
| `user_id` | string ≤ 256, ixtiyoriy | Sizning foydalanuvchi id'ingiz: shaxsiy limit va suhbat egasi |
| `conversation_id` | string, ixtiyoriy | Oldingi javobdagi `conversation_id` — keyingi savol kontekst bilan tushuniladi |
| `language` | `auto` \| `uz` \| `ru` \| `en` | Javob tili (standart `auto`) |
| `format` | `markdown` \| `text` \| `telegram_html` | Javob formati |
| `mode` | `plain` \| `legal_text` \| `easy_read` \| `subsumption` | Uslub: sodda, norma matni bilan, oson o'qiladigan, tahliliy |
| `disability_group`, `category` | string | Filtrlar (`GET /api/v1/inclusive/categories` dagi qiymatlar), standart `all` |
| `stream` | bool | `true` — SSE oqimi (6-bo'lim) |

Javob:

```json
{
  "answer_id": "Vv3k…",
  "conversation_id": "q8Zt…",
  "answer": "…",
  "format": "telegram_html",
  "parts": ["… 4096 belgidan oshmaydigan qismlar …"],
  "citations": [
    {
      "number": 1,
      "canonical_id": "law_disability_2020_art_23",
      "title": "Nogironligi bo'lgan shaxslarning huquqlari to'g'risida",
      "law_number": "O'RQ-641",
      "article": "23-modda",
      "article_title": "Ijtimoiy infratuzilma obyektlarini … loyihalashtirish, qurish va rekonstruksiya qilish",
      "url": "https://lex.uz/uz/docs/-5049511#-5054165",
      "source_type": "lex",
      "status": "active",
      "quote": "…"
    }
  ],
  "is_refusal": false,
  "language": "uz",
  "standalone_question": "…",
  "disclaimer": "…",
  "latency_ms": 2400,
  "cached": false
}
```

- `source_type`: `lex` (Lex.uz normasi), `huquqplus` (Huquq+ maqolasi, `url` — maqola), `curated`
  (huquqshunos javobi, ommaviy havolasiz).
- `is_refusal: true` — savol bazadagi qonunchilik doirasidan tashqarida; javobda buni aytuvchi matn bo'ladi.
- `parts` — Telegram uchun tayyor bo'laklar: har biri ≤ 4096 belgi, teglari yopilgan.

Boshqa endpointlar:

- `POST /api/v1/assistant/feedback` — `{"answer_id", "rating": "up"|"down", "comment"}` (faqat o'z javobingizga).
- `GET /api/v1/assistant/me` — kalit egasi, ruxsatlar, limitlar, bugungi so'rovlar (ulanishni tekshirish uchun).
- `POST /api/v1/assistant/conversations/{conversation_id}/delete` — `{"user_id"}`: foydalanuvchi suhbatini o'chirish.

## 4. Telegram bot (aiogram 3) — namuna

Bu namuna bot kodiga **qo'shilmagan**; bot dasturchisi o'zi qo'shadi. Kalit bot `.env` faylida turadi.

```python
import os
import httpx
from aiogram import F, Router, types
from aiogram.enums import ParseMode

AI_URL = os.environ["HUQUQPLUS_AI_URL"]          # https://AI_SERVER
AI_KEY = os.environ["HUQUQPLUS_AI_KEY"]          # hpk_live_…
router = Router()
_conversations: dict[int, str] = {}              # production'da Redis'da saqlang (masalan 24 soat TTL bilan)


@router.message(F.text)
async def ask_ai(message: types.Message):
    await message.bot.send_chat_action(message.chat.id, "typing")
    payload = {
        "question": message.text,
        "user_id": f"tg:{message.from_user.id}",
        "conversation_id": _conversations.get(message.from_user.id),
        "format": "telegram_html",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(f"{AI_URL}/api/v1/assistant/ask", json=payload,
                              headers={"Authorization": f"Bearer {AI_KEY}"})
    if r.status_code == 404:                     # suhbat eskirgan yoki o'chirilgan: yangisini boshlaymiz
        _conversations.pop(message.from_user.id, None)
        return await ask_ai(message)
    if r.status_code == 429:
        return await message.answer(f"Juda ko'p so'rov. {r.headers.get('Retry-After', '60')} soniyadan so'ng urining.")
    if r.status_code != 200:
        return await message.answer("Hozir javob berib bo'lmadi. Birozdan so'ng qayta urining.")
    data = r.json()
    _conversations[message.from_user.id] = data["conversation_id"]
    for part in data["parts"]:
        await message.answer(part, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
```

## 5. Boshqa tillar

**Python (server):**

```python
import httpx

async def ask(question: str, user_id: str, conversation_id: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post("https://AI_SERVER/api/v1/assistant/ask",
                              headers={"Authorization": f"Bearer {KEY}"},
                              json={"question": question, "user_id": user_id, "conversation_id": conversation_id})
        r.raise_for_status()
        return r.json()
```

**Node.js (server, Node 18+):**

```javascript
const r = await fetch('https://AI_SERVER/api/v1/assistant/ask', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${process.env.HUQUQPLUS_AI_KEY}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ question, user_id: String(userId), format: 'markdown' }),
});
const data = await r.json();
if (!r.ok) throw new Error(data.error?.message ?? 'Xatolik');
```

**WordPress (PHP, server tomonda; kalit `wp-config.php` da):**

```php
// wp-config.php: define('HUQUQPLUS_AI_URL', 'https://AI_SERVER'); define('HUQUQPLUS_AI_KEY', 'hpk_live_…');
function huquqplus_ai_ask( $question, $user_id = '' ) {
    $response = wp_remote_post( HUQUQPLUS_AI_URL . '/api/v1/assistant/ask', array(
        'headers' => array( 'Authorization' => 'Bearer ' . HUQUQPLUS_AI_KEY, 'Content-Type' => 'application/json' ),
        'body'    => wp_json_encode( array( 'question' => $question, 'user_id' => (string) $user_id, 'format' => 'markdown' ) ),
        'timeout' => 90,
    ) );
    if ( is_wp_error( $response ) ) {
        return $response;
    }
    return json_decode( wp_remote_retrieve_body( $response ), true );
}
```

Saytda chiqarishda javob matnini HTML sifatida emas, xavfsiz (escape qilingan yoki markdown kutubxonasi orqali
sanitize qilingan) holda ko'rsating.

**Brauzer (faqat `hpk_pub_…` kaliti bilan, SSE oqimi):**

```javascript
async function streamAnswer(question, onText) {
  const r = await fetch('https://AI_SERVER/api/v1/assistant/ask', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer hpk_pub_…', 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, stream: true }),
  });
  if (!r.ok) throw new Error((await r.json()).error?.message);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let i;
    while ((i = buffer.indexOf('\n\n')) >= 0) {            // bitta SSE hodisasi bo'sh qator bilan tugaydi
      const block = buffer.slice(0, i); buffer = buffer.slice(i + 2);
      const event = /^event: (.+)$/m.exec(block)?.[1];
      const data = JSON.parse(/^data: (.+)$/m.exec(block)?.[1] ?? 'null');
      if (event === 'delta') onText(data.text);             // textContent bilan qo'shing, innerHTML bilan emas
      if (event === 'done') return data;                    // to'liq javob: citations, parts, answer_id
      if (event === 'error') throw new Error(data.message);
    }
  }
}
```

## 6. SSE oqimi (`"stream": true`)

Hodisalar tartibi: `meta` → bir nechta `delta` → `done` (yoki `error`).

```
event: meta
data: {"answer_id": "…", "conversation_id": "…"}

event: delta
data: {"text": "Nogironligi "}

event: done
data: {… 3-bo'limdagi to'liq javob …}
```

`delta` matni — xom markdown; formatlangan matn va `parts` faqat `done` hodisasida keladi.

## 7. OpenAI bilan mos API (n8n, Flowise, LangChain, OpenAI SDK)

- Base URL: `https://AI_SERVER/api/v1/openai`
- Model: `huquqplus-assistant` (`GET /models`)
- API key: server kaliti

```python
from openai import OpenAI

client = OpenAI(base_url="https://AI_SERVER/api/v1/openai", api_key=KEY)
r = client.chat.completions.create(
    model="huquqplus-assistant",
    messages=[{"role": "user", "content": "Nogironlik pensiyasi qanday tayinlanadi?"}],
    user="tg:123456789",
)
print(r.choices[0].message.content)        # javob + "Manbalar:" ro'yxati; tuzilgan manbalar: r.model_extra["citations"]
```

- `system` / `developer` xabarlari e'tiborga olinmaydi (yordamchining qoidalarini tashqaridan o'zgartirib bo'lmaydi).
- Avvalgi `user`/`assistant` xabarlari faqat keyingi savolni tushunish uchun ishlatiladi.
- `stream: true` — standart `chat.completion.chunk` oqimi, oxirida `data: [DONE]`.
- Xatolar OpenAI shaklida: `{"error": {"message", "type", "code"}}`.

## 8. Xato kodlari

`/api/v1/assistant/*` xatolari: `{"error": {"code": "...", "message": "..."}}`.

| HTTP | `code` | Ma'nosi |
|---|---|---|
| 401 | `missing_api_key` | Kalit yuborilmagan |
| 401 | `invalid_api_key` | Kalit noma'lum, bekor qilingan, muddati o'tgan yoki mijoz o'chirilgan |
| 403 | `secret_key_in_browser` | Server kaliti brauzerdan ishlatilgan — kalitni almashtiring |
| 403 | `origin_not_allowed` | Brauzer kaliti ruxsat etilmagan domendan |
| 403 | `insufficient_scope` | Kalitga bu amal (`ask` / `feedback`) ruxsat etilmagan |
| 404 | `conversation_not_found` | Suhbat yo'q yoki boshqa foydalanuvchiniki — `conversation_id` siz qayta yuboring |
| 404 | `answer_not_found` | Fikr bildirilayotgan javob topilmadi |
| 422 | `invalid_request` | Maydonlar noto'g'ri yoki savol bo'sh |
| 429 | `rate_limited` / `user_rate_limited` | Daqiqalik limit; `Retry-After` sarlavhasidagi soniyadan keyin urining |
| 429 | `quota_exceeded` | Kunlik kvota tugagan |
| 500 | `server_error` | Ichki xato (tafsilotlar faqat server jurnalida) |
| 503 | `service_unavailable` | Javob yaratish xizmati vaqtincha ishlamayapti |
