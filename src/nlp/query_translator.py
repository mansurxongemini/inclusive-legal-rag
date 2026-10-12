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

        try:
            raw = await client.chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=300,
                min_chars=2,  # short questions translate to short text; the default stub filter would reject them
                reasoning={"enabled": False},
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
