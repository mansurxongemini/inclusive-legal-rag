import asyncio
import hashlib
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional
import httpx
import numpy as np

from src.config import settings
from src.clients.spend import cost_of, is_limit_error, ledger

logger = logging.getLogger(__name__)

# Models that always reason before answering. Their reasoning tokens count against max_tokens: such a model can spend
# thousands of tokens on a legal question with retrieved context, so a 2,048-token budget ends the reply before any
# answer text (an empty answer with finish_reason "stop").
REASONING_MODEL_MARKERS = ("nemotron", "r1", "deepseek-r1")
REASONING_MODEL_MIN_TOKENS = 8192


def output_token_budget(model: Optional[str], max_tokens: int) -> int:
    """max_tokens for one request: at least REASONING_MODEL_MIN_TOKENS for an always-reasoning model."""
    if any(m in (model or "").lower() for m in REASONING_MODEL_MARKERS):
        return max(max_tokens, REASONING_MODEL_MIN_TOKENS)
    return max_tokens


NO_REASONING = {"enabled": False}          # never mutated


def reasoning_fields(base_url: str, reasoning: Optional[Dict]) -> Dict:
    """Request fields that control a model's reasoning: OpenRouter takes the `reasoning` object as it is (a model that
    cannot reason ignores it). Another endpoint gets no reasoning field."""
    if not reasoning or "openrouter.ai" not in base_url:
        return {}
    return {"reasoning": reasoning}


def _error_body(response) -> str:
    """First part of an error response body for the log (never the request, which may hold a user's question)."""
    try:
        return (response.text or "")[:200].replace("\n", " ")
    except Exception:
        return ""


class OpenRouterClient:
    """
    Client for OpenRouter with retry and an offline deterministic mock. One key and one endpoint serve every call: chat
    (generation, query rewriting, translation, ranking, claim check, review), embeddings, reranking and Jev decisions.
    """

    EMBEDDING_BATCH = 48  # inputs per /embeddings request

    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.base_url = self._api_root(settings.OPENROUTER_BASE_URL)
        self.primary_model = settings.GENERATION_MODEL_PRIMARY
        self.embedding_model = settings.EMBEDDING_MODEL
        self.is_mock = settings.is_mock_mode
        self._http_client: Optional[httpx.AsyncClient] = None

    @staticmethod
    def _api_root(url: str) -> str:
        """Base URL without a trailing endpoint path (".../chat/completions" pasted into the setting by mistake)."""
        url = url.strip().rstrip("/")
        for suffix in ("/chat/completions", "/embeddings"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        return url

    @property
    def embedding_is_mock(self) -> bool:
        return settings.MOCK_EXTERNAL_APIS or not bool(self.api_key)

    async def get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                headers={
                    "Authorization": f"Bearer {self.api_key or ''}",
                    "HTTP-Referer": "https://legal-rag.uz",
                    "X-Title": "Uzbekistan Legal RAG",
                }
            )
        return self._http_client

    async def close(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    @staticmethod
    def _check_budget(optional: bool = False) -> None:
        """
        The budget guard in front of every paid call: once the month's budget (or the key's own limit) is used up, or the
        switch OPENROUTER_PAUSED is on, no call is made at all; an `optional` call (a query rewrite, the claim check, a
        history condensation) is skipped already at the soft limit. Callers treat the RuntimeError as "service unavailable":
        retrieval falls back to full-text search, an answer to a quotation of the matching norms.
        """
        state = ledger.state()
        if state == "exhausted":
            raise RuntimeError("OpenRouter budget used up or paused: no model call is made until it is restored.")
        if optional and state != "ok":
            raise RuntimeError("OpenRouter budget is near its limit: an optional model call is skipped.")

    def provider_preferences(self) -> Optional[Dict]:
        """Builds OpenRouter provider routing and quantization preferences from settings."""
        if "openrouter.ai" not in self.base_url:
            return None
        order = [x.strip() for x in (settings.LLM_PROVIDER_ORDER or "").split(",") if x.strip()]
        quantizations = [x.strip() for x in (settings.LLM_PROVIDER_QUANTIZATIONS or "").split(",") if x.strip()]
        max_price = {k: v for k, v in (("prompt", settings.LLM_PROVIDER_MAX_PRICE_PROMPT),
                                       ("completion", settings.LLM_PROVIDER_MAX_PRICE_COMPLETION)) if v and v > 0}
        if not order and not quantizations and not max_price:
            return None
        prefs: Dict = {}
        if order:
            prefs["order"] = order
        prefs["allow_fallbacks"] = True       # within the quantization and price limits below
        if quantizations:
            prefs["quantizations"] = quantizations
        if max_price:
            prefs["max_price"] = max_price    # USD per million tokens: a fallback never lands on a 3-10x dearer provider
        return prefs

    def _deterministic_mock_embedding(self, text: str, dim: int = 1024) -> List[float]:
        """
        Creates high-quality deterministic pseudo-embeddings for testing without external API.
        Uses SHA-256 token hashing and word-overlap projection into 1024 dimensions.
        """
        vec = np.zeros(dim, dtype=np.float32)
        words = text.lower().split()
        if not words:
            return vec.tolist()

        for word in words:
            # Deterministic bucket
            h = int(hashlib.sha256(word.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % dim
            sign = 1.0 if (h % 2 == 0) else -1.0
            vec[idx] += sign

        # Add overall text hash
        full_h = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
        vec[full_h % dim] += 2.0

        # L2 normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    async def get_embeddings(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """
        Fetches embeddings from OpenRouter or returns deterministic mock embeddings if in mock mode.
        """
        if self.embedding_is_mock:
            return [self._deterministic_mock_embedding(t, settings.EMBEDDING_DIMENSION) for t in texts]

        if len(texts) > self.EMBEDDING_BATCH:
            vectors: List[List[float]] = []
            for i in range(0, len(texts), self.EMBEDDING_BATCH):
                vectors.extend(await self.get_embeddings(texts[i:i + self.EMBEDDING_BATCH], model=model))
            return vectors

        if ledger.state() == "exhausted":
            raise RuntimeError("OpenRouter monthly budget used up: embeddings are paused until the month changes.")
        target_model = model or self.embedding_model
        client = await self.get_client()

        max_retries = 5
        delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json={
                        "model": target_model,
                        "input": texts,
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    ledger.add("embedding", cost_of(data.get("usage")))
                    # OpenRouter format: data: [{"embedding": [...], "index": 0}, ...]
                    return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                elif response.status_code == 429:
                    try:
                        retry_after = float(response.headers.get("Retry-After", delay * 2.0))
                    except ValueError:  # Retry-After may be an HTTP date
                        retry_after = delay * 2.0
                    retry_after = min(max(retry_after, 0.0), 30.0)  # never stall a request for minutes
                    logger.warning(f"OpenRouter 429 Rate Limit. Sleeping {retry_after:.1f}s before retry {attempt+1}/{max_retries}...")
                    await asyncio.sleep(retry_after)
                    continue
                elif response.status_code in (400, 401, 403, 404, 405):
                    if is_limit_error(response.status_code, response.text):
                        ledger.trip("embeddings: " + response.text[:80])
                    logger.warning(f"Embedding endpoint returned non-retryable HTTP {response.status_code}: {response.text[:100]}. Skipping retries.")
                    break
                else:
                    logger.warning(f"OpenRouter embedding error HTTP {response.status_code}: {response.text}")
            except Exception as e:
                logger.warning(f"OpenRouter embedding attempt {attempt+1} failed: {e}")

            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2.0

        # If live API fails, fall back to mock with warning or raise
        logger.error("OpenRouter embedding failed after retries. Degrading gracefully.")
        raise RuntimeError("OpenRouter embedding service is temporarily unavailable.")

    async def rerank_documents(
        self,
        query: str,
        documents: List[str],
        model: Optional[str] = None,
        top_n: Optional[int] = None,
    ) -> List[Dict]:
        """
        Reranks query-document pairs using OpenRouter's official /rerank endpoint.
        Returns list of {"index": int, "relevance_score": float}.
        """
        if not documents:
            return []

        target_model = model or settings.RERANK_MODEL

        if self.is_mock:
            # Deterministic mock scoring based on word overlap
            scores = []
            q_words = set(query.lower().split())
            for idx, doc in enumerate(documents):
                d_words = set(doc.lower().split())
                overlap = len(q_words.intersection(d_words))
                score = min(1.0, 0.5 + (overlap * 0.1))
                scores.append({"index": idx, "relevance_score": score})
            scores.sort(key=lambda x: x["relevance_score"], reverse=True)
            return scores[:top_n] if top_n else scores

        if ledger.state() == "exhausted":
            return []
        client = await self.get_client()
        try:
            response = await client.post(
                f"{self.base_url}/rerank",
                json={
                    "model": target_model,
                    "query": query,
                    "documents": documents,
                    "top_n": top_n or len(documents),
                }
            )
            if response.status_code == 200:
                data = response.json()
                ledger.add("rerank", cost_of(data.get("usage")))
                return data.get("results", [])
            logger.warning(f"OpenRouter /rerank returned HTTP {response.status_code}: {response.text}")
        except Exception as e:
            logger.warning(f"OpenRouter /rerank call failed: {e}")

        # No scores: an invented order would pass for a model's judgement (and clear the relevance gate); the caller
        # falls back to the RRF order.
        return []

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        min_chars: int = 30,
        reasoning: Optional[Dict] = None,
        response_format: Optional[Dict] = None,
        light: bool = False,
        optional: bool = False,
    ) -> str:
        """
        Non-streaming completion on the one chat model (GENERATION_MODEL_PRIMARY; OpenRouter itself falls back between
        providers). Replies not longer than min_chars count as stubs and are asked for once more.

        light=True marks a cheap helper call (query rewriting, translation, history condensing): reasoning is switched off.
        optional=True marks one that may be skipped when the budget runs low (see _check_budget).
        Raises RuntimeError when the call cannot be made or the model does not answer.
        """
        if self.is_mock:
            return self._mock_grounded_response(messages)

        self._check_budget(optional)
        if light:
            reasoning = reasoning or NO_REASONING
        target = model or self.primary_model
        prefs = self.provider_preferences()

        for attempt in range(2):
            try:
                client = await self.get_client()
                payload: Dict = {
                    "model": target,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": output_token_budget(target, max_tokens),
                }
                if prefs is not None:
                    payload["provider"] = prefs
                payload.update(reasoning_fields(self.base_url, reasoning))
                if response_format is not None:
                    payload["response_format"] = response_format
                response = await client.post(f"{self.base_url}/chat/completions", json=payload)
                if response.status_code == 200:
                    res_json = response.json()
                    ledger.add("chat", cost_of(res_json.get("usage")))
                    content = (res_json.get("choices", [{}])[0].get("message", {}) or {}).get("content")
                    if content and len(content.strip()) > min_chars:
                        return content.strip()
                    # If reasoning took all tokens or content is empty
                    logger.warning(f"Model {target} returned empty or stub content ({repr(content)[:50]}).")
                else:
                    logger.warning(f"Chat completion model {target} failed with HTTP {response.status_code}: "
                                   f"{_error_body(response)}")
                    if is_limit_error(response.status_code, response.text):
                        ledger.trip("chat: " + _error_body(response)[:80])
                        raise RuntimeError("OpenRouter refused the key (limit or credit used up).")
                    if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                        break          # the same request would be rejected again
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"Chat completion model {target} attempt {attempt+1} error: {e}")
            if attempt == 0:
                await asyncio.sleep(1.0)

        raise RuntimeError("The LLM did not answer on OpenRouter. Please try again later.")

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        reasoning: Optional[Dict] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming response with SSE chunk yielding. A failure before the first token is tried once more; once a token has
        reached the caller an interruption is an error (a second attempt would splice two answers together).
        """
        if self.is_mock:
            full_resp = self._mock_grounded_response(messages)
            words = full_resp.split(" ")
            for w in words:
                yield w + " "
                await asyncio.sleep(0.01)
            return

        self._check_budget()
        target = model or self.primary_model
        prefs = self.provider_preferences()
        last_error: Optional[str] = None

        for attempt in range(2):
            emitted = False
            try:
                client = await self.get_client()
                payload: Dict = {
                    "model": target,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": output_token_budget(target, max_tokens),
                    "stream": True,
                }
                if "openrouter.ai" in self.base_url:
                    payload["stream_options"] = {"include_usage": True}      # the cost arrives in the last chunk
                if prefs is not None:
                    payload["provider"] = prefs
                payload.update(reasoning_fields(self.base_url, reasoning))
                async with client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as response:
                    if response.status_code != 200:
                        last_error = f"HTTP {response.status_code}"
                        body = ""
                        try:
                            body = (await response.aread()).decode("utf-8", "replace")[:200].replace("\n", " ")
                        except Exception:
                            pass
                        logger.warning(f"Streaming model {target} failed with {last_error}: {body}")
                        if is_limit_error(response.status_code, body):
                            ledger.trip("chat: " + body[:80])
                            raise RuntimeError("OpenRouter refused the key (limit or credit used up).")
                        if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                            break      # the same request would be rejected again
                    else:
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except ValueError:
                                continue
                            if chunk.get("usage"):
                                ledger.add("chat", cost_of(chunk["usage"]))
                            choices = chunk.get("choices") or []
                            delta = ((choices[0].get("delta") or {}).get("content") or "") if choices else ""
                            if delta:
                                emitted = True
                                yield delta
                        if emitted:
                            return
                        # A stream that ends without answer text (reasoning used the whole budget) is a failure, not an
                        # empty answer: asking again would not change it.
                        logger.warning(f"Streaming model {target} returned no answer text")
                        raise RuntimeError("LLM stream returned no answer (empty stream).")
            except RuntimeError:
                raise
            except Exception as e:
                last_error = type(e).__name__
                logger.error(f"Streaming error with model {target}: {e}")
                if emitted:
                    raise RuntimeError("LLM stream was interrupted.") from e
            if attempt == 0:
                await asyncio.sleep(1.0)

        # Never emit error text as if it were the answer; the caller turns this into a structured error event.
        raise RuntimeError(f"The LLM failed to stream ({last_error}).")

    def _mock_grounded_response(self, messages: List[Dict[str, str]]) -> str:
        """Deterministic mock response strictly grounded in context messages for test suites."""
        import re
        from src.nlp.transliteration import cyrillic_to_latin
        from src.nlp.query_analyzer import QueryAnalyzer

        user_content = ""
        for m in messages:
            if m["role"] == "user":
                user_content = m["content"]

        if "Retrieved Legal Context:" in user_content:
            parts = user_content.split("Retrieved Legal Context:")
            pure_query = parts[0].replace("User Question:", "").strip()
            context_text = parts[1].strip()
        else:
            pure_query = user_content.strip()
            context_text = ""

        # Detect language
        analysis = QueryAnalyzer.analyze(pure_query)
        lang = analysis.detected_language

        # Check out-of-scope topics
        out_of_scope_keywords = [
            "kosmik", "raketa", "kriptovalyuta", "mayning", "oy yuzi", "oyda", "xususiylashtirish",
            "штраф", "превышение скорости", "corporate profit tax", "foreign commercial banks",
            "lunar land", "mining"
        ]
        norm_q = cyrillic_to_latin(pure_query).lower()
        if any(kw in norm_q or kw in pure_query.lower() for kw in out_of_scope_keywords):
            if lang == "ru":
                return (
                    "В предоставленных законодательных актах Республики Узбекистан не найдено точной нормы по данному вопросу. "
                    "В целях предотвращения дезинформации рекомендуем обратиться в уполномоченный орган."
                )
            elif lang == "en":
                return (
                    "No specific legal provision covering this question was found in the retrieved legislation of the Republic of Uzbekistan. "
                    "We recommend consulting a competent government authority."
                )
            else:
                return (
                    "Taqdim etilgan O'zbekiston Respublikasi qonunchilik hujjatlarida ushbu savol bo'yicha aniq norma yoki qoida topilmadi. "
                    "Yolg'on yoki tasdiqlanmagan ma'lumot berishning oldini olish maqsadida, vakolatli organga murojaat qilishni tavsiya etamiz."
                )

        # Extract retrieved articles from context
        blocks = re.findall(
            r"Canonical ID: \[([a-z0-9_]+)\]\s*\nLaw: ([^\n]+)\s*\nArticle: ([^\n]+)\s*\nStatus: ([^\n]+)",
            context_text
        )

        if not blocks:
            if lang == "ru":
                return "В законодательстве не найдено применимых норм по вашему вопросу."
            elif lang == "en":
                return "No applicable provisions were found in the retrieved legislation."
            else:
                return "Taqdim etilgan qonunchilik hujjatlarida ushbu savol bo'yicha aniq ma'lumot topilmadi."

        # Selection logic matching query intent
        q_norm = cyrillic_to_latin(pure_query).lower()
        q_words = set(re.findall(r"\w+", q_norm))
        q_nums = set(re.findall(r"\b\d+\b", pure_query))

        num_matched = []
        overlap_matched = []
        for b in blocks:
            cid, law_title, art_title, status = b
            b_norm = cyrillic_to_latin(f"{cid} {law_title} {art_title}").lower()
            b_words = set(re.findall(r"\w+", b_norm))
            b_nums = set(re.findall(r"\b\d+\b", f"{cid} {art_title}"))

            has_num = bool(q_nums.intersection(b_nums))
            overlap = len(q_words.intersection(b_words))

            if has_num:
                num_matched.append(b)
            overlap_matched.append((b, overlap))

        if num_matched:
            selected = num_matched[:3]
        else:
            overlap_matched.sort(key=lambda x: x[1], reverse=True)
            top_ov = overlap_matched[0][1] if overlap_matched else 0
            if top_ov >= 2:
                selected = [overlap_matched[0][0]]
            else:
                selected = [blocks[0]] if blocks else []

        top_cid, top_law, top_art, top_status = selected[0]

        # Check if repealed or amended
        status_note_uz = ""
        status_note_ru = ""
        status_note_en = ""
        if any("REPEALED" in b[3] or "BEKOR QILINGAN" in b[3] for b in selected):
            status_note_uz = " Eslatma: mazkur norma o'z kuchini yo'qotgan va yangi tahrirga almashtirilgan."
            status_note_ru = " Примечание: данная статья утратила силу и заменена новой редакцией."
            status_note_en = " Note: this article is repealed and superseded by an updated provision."

        if len(selected) == 1:
            if lang == "ru":
                return (
                    f"Согласно законодательству Республики Узбекистан [{top_cid}], по {top_art} ({top_law}), "
                    f"установлены соответствующие гарантии, права и порядок применения.{status_note_ru}"
                )
            elif lang == "en":
                return (
                    f"According to the legislation of the Republic of Uzbekistan [{top_cid}], under {top_art} ({top_law}), "
                    f"relevant guarantees, rights, and implementation procedures are established.{status_note_en}"
                )
            else:
                return (
                    f"O'zbekiston Respublikasi qonunchiligiga ko'ra [{top_cid}], {top_art} ({top_law}) bo'yicha "
                    f"fuqarolar uchun tegishli kafolatlar, huquqlar va imtiyozlar belgilangan.{status_note_uz}"
                )

        # Multi-article synthesis
        items_uz = "; ".join(f"{b[2]} ({b[1]}) [{b[0]}]" for b in selected)
        items_ru = "; ".join(f"{b[2]} ({b[1]}) [{b[0]}]" for b in selected)
        items_en = "; ".join(f"{b[2]} ({b[1]}) [{b[0]}]" for b in selected)

        if lang == "ru":
            return (
                f"Согласно законодательству Республики Узбекистан, данный вопрос регулируется комплексом норм: {items_ru}. "
                f"В частности, {top_art} [{top_cid}] и сопутствующие статьи регламентируют права и гарантии субъектов.{status_note_ru}"
            )
        elif lang == "en":
            return (
                f"According to the legislation of the Republic of Uzbekistan, this matter is governed by multiple provisions: {items_en}. "
                f"In particular, {top_art} [{top_cid}] and associated articles establish relevant rights and guarantees.{status_note_en}"
            )
        else:
            return (
                f"O'zbekiston Respublikasi qonunchiligiga muvofiq, ushbu masala bir qator qoidalar bilan tartibga solinadi: {items_uz}. "
                f"Xususan, {top_art} [{top_cid}] va unga yondosh normalar fuqarolarning huquqlari va kafolatlarini belgilaydi.{status_note_uz}"
            )

    async def decide(
        self,
        state: str,
        questions: Dict[str, dict],
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Calls OpenRouter's /api/alpha/decisions endpoint using TypeSafe Jev.
        Returns parsed JSON dict with 'answers' and 'usage', or None on failure.
        Mock mode returns deterministic mock answers and empty usage.
        """
        if self.is_mock:
            return {"answers": self._mock_decision(state, questions), "usage": {}}

        if not self.api_key or "openrouter.ai" not in self.base_url:
            return None
        if ledger.state() == "exhausted":
            return None

        client = await self.get_client()
        url = "https://openrouter.ai/api/alpha/decisions"
        payload = {
            "model": model or settings.JEV_MODEL,
            "state": state,
            "questions": questions,
        }
        req_timeout = timeout if timeout is not None else settings.JEV_TIMEOUT_S

        try:
            response = await client.post(url, json=payload, timeout=req_timeout)
            if response.status_code == 200:
                body = response.json()
                ledger.add("jev", cost_of(body.get("usage")))
                return body
            logger.warning(f"OpenRouter decisions API returned HTTP {response.status_code}: {response.text[:200]}")
            if is_limit_error(response.status_code, response.text):
                ledger.trip("Jev: " + response.text[:80])
            return None
        except Exception as e:
            logger.warning(f"OpenRouter decisions call failed: {e}")
            return None

    async def get_decision(
        self,
        state: str,
        questions: Dict[str, dict],
        model: Optional[str] = None,
    ) -> Dict:
        """
        Calls OpenRouter's /api/alpha/decisions endpoint using TypeSafe Jev.
        Returns answers dict containing probabilities, choice, and score, or {} when decide returns None.
        """
        res = await self.decide(state=state, questions=questions, model=model)
        if res is not None:
            return res.get("answers", {})
        return {}

    def _mock_decision(self, state: str, questions: Dict[str, dict]) -> Dict:
        """Deterministic fallback decision for test suites or offline environments."""
        answers = {}
        state_low = state.lower()

        for q_name, q_spec in questions.items():
            q_type = q_spec.get("type", "choice")
            if q_type == "choice":
                options = q_spec.get("criteria", {}) or q_spec.get("options", {})
                best_choice = list(options.keys())[0] if options else "unknown"
                probs = {k: 0.1 for k in options.keys()}
                for opt in options.keys():
                    if opt in state_low or any(w in state_low for w in opt.split("_")):
                        best_choice = opt
                        break
                probs[best_choice] = 0.8
                answers[q_name] = {
                    "type": "choice",
                    "choice": best_choice,
                    "probabilities": probs,
                    "confidence": 0.85
                }
            elif q_type == "score":
                crit_list = q_spec.get("criteria", ["0", "1", "2"])
                is_practical = any(w in state_low for w in ["imtiyoz", "huquq", "mumkin", "to'lanadi", "ozod"])
                score_val = 1.9 if is_practical else 0.8
                answers[q_name] = {
                    "type": "score",
                    "score": score_val,
                    "legend": {str(i): c for i, c in enumerate(crit_list)},
                    "probabilities": {"2": 0.85, "1": 0.10, "0": 0.05} if is_practical else {"0": 0.7, "1": 0.2, "2": 0.1},
                    "confidence": 0.90
                }
            elif q_type == "noul":
                is_rel = any(w in state_low for w in ["nogiron", "tmek", "imtiyoz", "sud", "qaror"])
                answers[q_name] = {
                    "type": "noul",
                    "noul": 0.92 if is_rel else 0.25
                }
        return answers
