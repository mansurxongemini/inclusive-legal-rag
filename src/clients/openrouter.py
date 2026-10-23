import asyncio
import hashlib
import json
import logging
import math
import time
from typing import AsyncGenerator, Dict, List, Optional
import httpx
import numpy as np

from src.config import settings
from src.clients.spend import cost_of, is_limit_error, ledger

logger = logging.getLogger(__name__)

# Models that always reason before answering. Their reasoning tokens count against max_tokens: muse-spark-1.3 spends
# ~1,900 reasoning tokens on a three-sentence question and ~3,000 on a legal question with retrieved context, so a
# 2,048-token budget ends the reply before any answer text (an empty answer with finish_reason "stop").
REASONING_MODEL_MARKERS = ("muse", "nemotron", "r1", "deepseek-r1")
REASONING_MODEL_MIN_TOKENS = 8192


def output_token_budget(model: Optional[str], max_tokens: int) -> int:
    """max_tokens for one request: at least REASONING_MODEL_MIN_TOKENS for an always-reasoning model."""
    if any(m in (model or "").lower() for m in REASONING_MODEL_MARKERS):
        return max(max_tokens, REASONING_MODEL_MIN_TOKENS)
    return max_tokens


NO_REASONING = {"enabled": False}          # never mutated
META_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")


def reasoning_fields(base_url: str, reasoning: Optional[Dict]) -> Dict:
    """
    Request fields that control a model's reasoning, from the OpenRouter-style `reasoning` option.
    OpenRouter takes the object as it is. The Meta API rejects `reasoning` (HTTP 400, unknown parameter) and takes
    `reasoning_effort` instead (minimal..max; "off" is not supported, so {"enabled": False} means minimal).
    Other endpoints get no reasoning field.
    """
    if not reasoning:
        return {}
    if "openrouter.ai" in base_url:
        return {"reasoning": reasoning}
    if "meta.ai" in base_url:
        if reasoning.get("enabled") is False:
            return {"reasoning_effort": "minimal"}
        effort = str(reasoning.get("effort") or "").lower()
        if effort in META_REASONING_EFFORTS:
            return {"reasoning_effort": effort}
    return {}


def _error_body(response) -> str:
    """First part of an error response body for the log (never the request, which may hold a user's question)."""
    try:
        return (response.text or "")[:200].replace("\n", " ")
    except Exception:
        return ""


class OpenRouterClient:
    """Client for OpenRouter API with retry, fallback models, and offline deterministic mock support."""

    EMBEDDING_BATCH = 48  # inputs per /embeddings request

    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.base_url = settings.OPENROUTER_BASE_URL.rstrip("/")
        self.primary_model = settings.GENERATION_MODEL_PRIMARY
        self.fallback_model = settings.GENERATION_MODEL_FALLBACK
        self.embedding_model = settings.EMBEDDING_MODEL
        self.embedding_base_url = self._api_root(settings.EMBEDDING_BASE_URL or settings.OPENROUTER_BASE_URL)
        self.embedding_api_key = settings.EMBEDDING_API_KEY or settings.OPENROUTER_API_KEY
        self.jev_base_url = self._api_root(
            settings.JEV_BASE_URL or settings.EMBEDDING_BASE_URL or settings.OPENROUTER_BASE_URL)
        self.jev_api_key = settings.JEV_API_KEY or settings.EMBEDDING_API_KEY or settings.OPENROUTER_API_KEY
        self.utility_base_url = self._api_root(
            settings.UTILITY_BASE_URL or settings.EMBEDDING_BASE_URL or settings.OPENROUTER_BASE_URL)
        self.utility_api_key = settings.UTILITY_API_KEY or settings.EMBEDDING_API_KEY or settings.OPENROUTER_API_KEY
        self.is_mock = settings.is_mock_mode
        self._plus_api_key = settings.PLUS_META_AI_API_KEY if settings.PLUS_META_AI_API_KEY != self.api_key else None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._embedding_http_client: Optional[httpx.AsyncClient] = None
        self._jev_http_client: Optional[httpx.AsyncClient] = None
        self._utility_http_client: Optional[httpx.AsyncClient] = None
        self._utility_failures = 0                    # consecutive failures of the utility endpoint
        self._utility_open_until = 0.0                # circuit breaker: utility calls are skipped until then

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
        return settings.MOCK_EXTERNAL_APIS or not bool(self.embedding_api_key)

    async def get_jev_client(self) -> httpx.AsyncClient:
        """HTTP client for Jev decisions (its own key, see JEV_API_KEY)."""
        if self.jev_api_key == self.api_key:
            return await self.get_client()
        if self.jev_api_key == self.embedding_api_key:
            return await self.get_embedding_client()
        if self._jev_http_client is None or self._jev_http_client.is_closed:
            self._jev_http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                headers={
                    "Authorization": f"Bearer {self.jev_api_key or ''}",
                    "HTTP-Referer": "https://legal-rag.uz",
                    "X-Title": "Uzbekistan Legal RAG",
                }
            )
        return self._jev_http_client

    async def get_embedding_client(self) -> httpx.AsyncClient:
        """HTTP client for the embedding endpoint (its own key and base URL, see EMBEDDING_BASE_URL)."""
        if self.embedding_base_url == self.base_url and self.embedding_api_key == self.api_key:
            return await self.get_client()
        if self._embedding_http_client is None or self._embedding_http_client.is_closed:
            self._embedding_http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                headers={
                    "Authorization": f"Bearer {self.embedding_api_key or ''}",
                    "HTTP-Referer": "https://legal-rag.uz",
                    "X-Title": "Uzbekistan Legal RAG",
                }
            )
        return self._embedding_http_client

    @property
    def utility_enabled(self) -> bool:
        """Light calls and the generation backup can run on the utility endpoint."""
        return (not self.is_mock) and bool(self.utility_api_key) and bool(
            settings.UTILITY_MODEL or settings.GENERATION_MODEL_BACKUP)

    async def get_utility_client(self) -> httpx.AsyncClient:
        """HTTP client for the utility endpoint (OpenRouter by default, see UTILITY_BASE_URL)."""
        if self.utility_base_url == self.base_url and self.utility_api_key == self.api_key:
            return await self.get_client()
        if self.utility_base_url == self.embedding_base_url and self.utility_api_key == self.embedding_api_key:
            return await self.get_embedding_client()
        if self._utility_http_client is None or self._utility_http_client.is_closed:
            self._utility_http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.utility_api_key or ''}",
                    "HTTP-Referer": "https://legal-rag.uz",
                    "X-Title": "Uzbekistan Legal RAG",
                }
            )
        return self._utility_http_client

    async def utility_chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 300,
        min_chars: int = 2,
        timeout: Optional[float] = None,
        response_format: Optional[Dict] = None,
        breaker: bool = True,
        reasoning: Optional[Dict] = NO_REASONING,
    ) -> Optional[str]:
        """
        One non-reasoning completion on the utility endpoint. Returns None on any failure (the caller falls back to
        the generation model). After 3 failures in a row the endpoint is skipped for 60 s instead of making every
        request wait for its timeout (breaker=False: evaluation judges neither trip nor honour the breaker).
        reasoning=None leaves the model's own default (some models, e.g. Claude Sonnet, cannot run without reasoning).
        """
        target = model or settings.UTILITY_MODEL
        if not target or not self.utility_enabled or (breaker and time.monotonic() < self._utility_open_until):
            return None
        if ledger.state() != "ok":      # budget guard: the free generation provider does the light work instead
            return None
        payload: Dict = {"model": target, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        payload.update(reasoning_fields(self.utility_base_url, reasoning))
        if response_format is not None:
            payload["response_format"] = response_format
        try:
            client = await self.get_utility_client()
            response = await client.post(f"{self.utility_base_url}/chat/completions", json=payload,
                                         timeout=timeout or settings.UTILITY_TIMEOUT_S)
            if response.status_code == 200:
                body = response.json()
                ledger.add("utility", cost_of(body.get("usage")))
                content = (body.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if len(content) >= min_chars and content:
                    self._utility_failures = 0
                    return content
                logger.warning(f"Utility model {target} returned an empty reply")
            else:
                logger.warning(f"Utility model {target} failed with HTTP {response.status_code}: {_error_body(response)}")
                if is_limit_error(response.status_code, response.text):
                    ledger.trip("light model: " + _error_body(response)[:80])
        except Exception as e:
            logger.warning(f"Utility model {target} call failed: {type(e).__name__}: {e}")
        if not breaker:
            return None
        self._utility_failures += 1
        if self._utility_failures >= 3:
            self._utility_open_until = time.monotonic() + 60.0
            self._utility_failures = 0
            logger.error("Utility endpoint failed 3 times in a row; skipping it for 60 s")
        return None

    def _rotate_main_key(self) -> bool:
        """The generation provider answered 402 (billing / limit used up): switch to the second key, once."""
        if not self._plus_api_key or self.api_key == self._plus_api_key:
            return False
        logger.warning("Generation provider answered HTTP 402; switching to the second API key")
        self.api_key = self._plus_api_key
        old, self._http_client = self._http_client, None      # get_client() builds a new one with the new key
        if old is not None and not old.is_closed:
            try:
                asyncio.get_running_loop().create_task(old.aclose())
            except RuntimeError:
                pass
        return True

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
        if self._embedding_http_client and not self._embedding_http_client.is_closed:
            await self._embedding_http_client.aclose()
        if self._jev_http_client and not self._jev_http_client.is_closed:
            await self._jev_http_client.aclose()
        if self._utility_http_client and not self._utility_http_client.is_closed:
            await self._utility_http_client.aclose()

    def provider_preferences(self) -> Optional[Dict]:
        """Builds OpenRouter provider routing and quantization preferences from settings."""
        if "openrouter.ai" not in self.base_url:
            return None
        order = [x.strip() for x in (settings.LLM_PROVIDER_ORDER or "").split(",") if x.strip()]
        quantizations = [x.strip() for x in (settings.LLM_PROVIDER_QUANTIZATIONS or "").split(",") if x.strip()]
        if not order and not quantizations:
            return None
        prefs: Dict = {}
        if order:
            prefs["order"] = order
        prefs["allow_fallbacks"] = True
        if quantizations:
            prefs["quantizations"] = quantizations
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
        client = await self.get_embedding_client()

        max_retries = 5
        delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await client.post(
                    f"{self.embedding_base_url}/embeddings",
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
    ) -> str:
        """
        Non-streaming generation with automatic fallback. Replies not longer than min_chars count as stubs.

        light=True marks a cheap helper call (query rewriting, translation, history condensing): it goes to the fast
        non-reasoning utility model first and only falls back to the generation model, with minimal reasoning.
        When every generation model fails, GENERATION_MODEL_BACKUP (on the utility endpoint) answers instead.
        """
        if self.is_mock:
            return self._mock_grounded_response(messages)

        if light:
            text = await self.utility_chat(messages, model=model, temperature=temperature, max_tokens=max_tokens,
                                           min_chars=min_chars, response_format=response_format)
            if text:
                return text
            reasoning = reasoning or {"enabled": False}

        models_to_try: List[str] = []
        for name in (model or self.primary_model, self.fallback_model):
            if name and name not in models_to_try:
                models_to_try.append(name)
        prefs = self.provider_preferences()

        for cur_model in models_to_try:
            for attempt in range(2):
                try:
                    client = await self.get_client()
                    payload: Dict = {
                        "model": cur_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": output_token_budget(cur_model, max_tokens),
                    }
                    if prefs is not None and "openrouter.ai" in self.base_url:
                        payload["provider"] = prefs
                    payload.update(reasoning_fields(self.base_url, reasoning))
                    if response_format is not None:
                        payload["response_format"] = response_format
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                    )
                    if response.status_code == 200:
                        res_json = response.json()
                        choice = res_json.get("choices", [{}])[0]
                        msg = choice.get("message", {})
                        content = msg.get("content")
                        if content and len(content.strip()) > min_chars:
                            return content.strip()
                        # If reasoning took all tokens or content is empty
                        logger.warning(f"Model {cur_model} returned empty or stub content ({repr(content)[:50]}). Triggering fallback...")
                    else:
                        logger.warning(f"Chat completion model {cur_model} failed with HTTP {response.status_code}: "
                                       f"{_error_body(response)}")
                        if response.status_code == 402 and self._rotate_main_key():
                            continue       # same model, second key
                        if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                            break          # the same request would be rejected again: next model
                except Exception as e:
                    logger.warning(f"Chat completion model {cur_model} attempt {attempt+1} error: {e}")
                if attempt == 0:
                    await asyncio.sleep(1.0)

        backup = settings.GENERATION_MODEL_BACKUP
        if backup and backup not in models_to_try and not light:
            text = await self.utility_chat(messages, model=backup, temperature=temperature, max_tokens=max_tokens,
                                            min_chars=min_chars, timeout=settings.GENERATION_BACKUP_TIMEOUT_S,
                                            response_format=response_format)
            if text:
                logger.warning(f"Generation models failed; answered by the backup model {backup}")
                return text

        raise RuntimeError("All configured LLM models failed on OpenRouter. Please try again later.")

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        reasoning: Optional[Dict] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming response with SSE chunk yielding."""
        if self.is_mock:
            full_resp = self._mock_grounded_response(messages)
            words = full_resp.split(" ")
            for w in words:
                yield w + " "
                await asyncio.sleep(0.01)
            return

        names: List[str] = []
        for name in (model or self.primary_model, self.fallback_model):
            if name and name not in names:
                names.append(name)
        # (model, on the utility endpoint): the backup model is tried last, on the other provider
        targets = [(name, False) for name in names]
        backup = settings.GENERATION_MODEL_BACKUP
        if backup and backup not in names and self.utility_enabled and time.monotonic() >= self._utility_open_until:
            targets.append((backup, True))

        last_error: Optional[str] = None
        position = 0
        while position < len(targets):
            target_model, on_utility = targets[position]
            position += 1
            emitted = False
            base_url = self.utility_base_url if on_utility else self.base_url
            try:
                client = await (self.get_utility_client() if on_utility else self.get_client())
                payload: Dict = {
                    "model": target_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": output_token_budget(target_model, max_tokens),
                    "stream": True,
                }
                prefs = None if on_utility else self.provider_preferences()
                if prefs is not None and "openrouter.ai" in base_url:
                    payload["provider"] = prefs
                payload.update(reasoning_fields(base_url, {"enabled": False} if on_utility else reasoning))
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        last_error = f"HTTP {response.status_code}"
                        body = ""
                        try:
                            body = (await response.aread()).decode("utf-8", "replace")[:200].replace("\n", " ")
                        except Exception:
                            pass
                        logger.warning(f"Streaming model {target_model} failed with {last_error}: {body}")
                        if response.status_code == 402 and not on_utility and self._rotate_main_key():
                            targets.insert(position, (target_model, on_utility))      # same model again, second key
                        continue

                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0]["delta"].get("content", "")
                            except Exception:
                                continue
                            if delta:
                                emitted = True
                                yield delta
                    if emitted:
                        return
                    # A stream that ends without answer text (reasoning used the whole budget) is a failure, not an
                    # empty answer: try the next model, or let the caller show its error message.
                    last_error = "empty stream"
                    logger.warning(f"Streaming model {target_model} returned no answer text")
                    continue
            except Exception as e:
                last_error = type(e).__name__
                logger.error(f"Streaming error with model {target_model}: {e}")
                if emitted:
                    # Tokens already reached the caller: switching models would splice two answers together.
                    raise RuntimeError("LLM stream was interrupted.") from e

        # Never emit error text as if it were the answer; the caller turns this into a structured error event.
        raise RuntimeError(f"All configured LLM models failed to stream ({last_error}).")

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

        if not self.jev_api_key or "openrouter.ai" not in self.jev_base_url:
            return None
        if ledger.state() == "exhausted":
            return None

        client = await self.get_jev_client()
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
