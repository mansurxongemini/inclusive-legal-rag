import collections
import logging
from typing import Optional, Tuple

from src.clients.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 512


class QueryTranslator:
    """In-memory cached translator for legal queries to Uzbek (Latin script)."""

    _cache: collections.OrderedDict[Tuple[str, str], str] = collections.OrderedDict()

    @classmethod
    async def to_uzbek(
        cls,
        query: str,
        source_language: str,
        client: OpenRouterClient,
    ) -> Optional[str]:
        """
        Translates Russian or English legal question into Uzbek (Latin script).
        Returns None if source_language is 'uz', if client is mock, or on any error.
        """
        if source_language == "uz" or getattr(client, "is_mock", False):
            return None

        if not query or not query.strip():
            return None

        cache_key = (source_language, query)
        if cache_key in cls._cache:
            cls._cache.move_to_end(cache_key)
            return cls._cache[cache_key]

        system_prompt = (
            "Translate the user's legal question into Uzbek (Latin script) using the terminology "
            "of Uzbek legislation on Lex.uz (examples: \"nogironligi bo'lgan shaxs\", "
            "\"tibbiy-ijtimoiy ekspert komissiyasi (TIEK)\", \"nafaqa\", \"pensiya\", "
            "\"reabilitatsiya texnik vositalari\"); keep numbers, names and abbreviations; "
            "the output must be in Uzbek LATIN script only, never Cyrillic; "
            "output ONLY the translated question, no quotes or explanations."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]

        is_reasoning = any(k in getattr(client, "primary_model", "") for k in ("muse", "nemotron", "r1"))
        max_toks = 1500 if is_reasoning else 300
        try:
            raw = await client.chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=max_toks,
                min_chars=2,  # short questions translate to short text; the default stub filter would reject them
                reasoning={"enabled": False},
                light=True,
            )
            if not raw:
                return None

            translated = raw.strip().strip('"\'`«»').strip()
            if not translated or len(translated) > 3 * len(query) + 200:
                return None

            cls._cache[cache_key] = translated
            cls._cache.move_to_end(cache_key)
            if len(cls._cache) > MAX_CACHE_SIZE:
                cls._cache.popitem(last=False)

            return translated
        except Exception as e:
            logger.warning(f"Query translation to Uzbek failed: {e}")
            return None

    @classmethod
    async def normalize_uzbek(cls, query: str, client: OpenRouterClient) -> Optional[str]:
        """
        Rewrites an Uzbek question as chat users type it (Cyrillic, colloquial, misspelled: "озик овкат ккийим
        вавчир") into standard Uzbek Latin with the words the legislation uses ("oziq-ovqat, kiyim-kechak, vaucher"):
        transliteration alone keeps the typos, so neither the lexical nor the dense search finds the act.
        Returns None in mock mode, on error, or when the rewrite is not a plausible restatement.
        """
        if getattr(client, "is_mock", False) or not query or not query.strip():
            return None
        cache_key = ("uz-norm", query)
        if cache_key in cls._cache:
            cls._cache.move_to_end(cache_key)
            return cls._cache[cache_key]

        system_prompt = (
            "Rewrite the user's question in correct standard Uzbek, LATIN script only: fix spelling and typos, "
            "remove conversational greetings (e.g. 'Salom', 'Assalomu alaykum'), transliterate Cyrillic correctly "
            "(o', g', q, h, sh, ch), and use the terminology of Uzbek legislation on Lex.uz (examples: \"oziq-ovqat\", "
            "\"kiyim-kechak\", \"vaucher\", \"bank plastik kartasi\", \"Ijtimoiy himoya yagona reyestri\", "
            "\"II guruh nogironligi bo'lgan shaxs\", \"nafaqa\", \"pensiya\", \"aperatsiya/operatsiya\" -> "
            "\"jarrohlik amaliyoti (operatsiya), bepul ixtisoslashtirilgan tibbiy yordam va imtiyozli yo'llanma (order)\"). "
            "Write common abbreviations out in full as the legislation does, keeping the abbreviation in brackets: "
            "OTM -> oliy ta'lim muassasasi (tashkiloti), TIEK/TMEK/VTEK -> tibbiy-ijtimoiy ekspert komissiyasi, "
            "FHDYO -> fuqarolik holati dalolatnomalarini yozish organi, DXM -> davlat xizmatlari markazi. "
            "Keep the meaning and every sub-question; do not add facts and do not answer. "
            "Output ONLY the rewritten question, no quotes or explanations."
        )
        is_reasoning = any(k in getattr(client, "primary_model", "") for k in ("muse", "nemotron", "r1"))
        max_toks = 1500 if is_reasoning else 300
        try:
            raw = await client.chat_completion(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": query}],
                temperature=0.0,
                max_tokens=max_toks,
                min_chars=2,
                reasoning={"enabled": False},
                light=True,
            )
            rewritten = (raw or "").strip().strip('"\'`«»').strip()
            if not rewritten or len(rewritten) > 2 * len(query) + 100 or any("Ѐ" <= ch <= "ӿ" for ch in rewritten):
                return None
            cls._cache[cache_key] = rewritten
            cls._cache.move_to_end(cache_key)
            if len(cls._cache) > MAX_CACHE_SIZE:
                cls._cache.popitem(last=False)
            return rewritten
        except Exception as e:
            logger.warning(f"Uzbek query normalization failed: {e}")
            return None
