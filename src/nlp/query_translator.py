import collections
import json
import logging
import re
from typing import List, Optional, Tuple, Union

from src.clients.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 512
MAX_SUBQUESTIONS = 4
MAX_SUBQUESTION_CHARS = 300


class QueryTranslator:
    """In-memory cached translator for legal queries to Uzbek (Latin script)."""

    _cache: collections.OrderedDict[Tuple[str, str], Union[str, List[str]]] = collections.OrderedDict()

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

        is_reasoning = any(k in getattr(client, "primary_model", "") for k in ("nemotron", "r1"))
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
        is_reasoning = any(k in getattr(client, "primary_model", "") for k in ("nemotron", "r1"))
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

    @classmethod
    async def legal_subquestions(
        cls, query: str, client: OpenRouterClient, terms: Optional[List[str]] = None,
    ) -> Optional[List[str]]:
        """
        Turns a long chat message that tells a story ("I applied to the social registry, got an SMS that it was
        refused, the Inson centre gave no answer, what should I do?") into up to MAX_SUBQUESTIONS short legal
        questions in standard Uzbek Latin ("Ijtimoiy reyestrga kiritish rad etilsa qayerga shikoyat qilinadi?").
        The story's words match the norms poorly and its several issues crowd each other out, while each short
        question finds its own norms. `terms` are the words the legislation itself uses for expressions of the
        message (see LegalSynonymExpander): a model does not know that an everyday "yordamchi" is the statutes'
        "hamrohlik qiluvchi shaxs", and a question written with the everyday word finds nothing.
        Returns None in mock mode, on error, or when no usable question comes back.
        """
        if getattr(client, "is_mock", False) or not query or not query.strip():
            return None
        cache_key = ("uz-subq", query)
        if cache_key in cls._cache:
            cls._cache.move_to_end(cache_key)
            return list(cls._cache[cache_key])

        system_prompt = (
            "The user's message is a question to a legal assistant on the rights of persons with disabilities and "
            "their families in Uzbekistan. It may be long and colloquial, in Cyrillic or Latin, with dialect or "
            "Karakalpak words and typos, and may tell a story. Work out what the user needs to know from the "
            f"legislation and write 1 to {MAX_SUBQUESTIONS} short, self-contained legal questions in standard Uzbek, "
            "LATIN script only, with the terminology of Uzbek legislation on Lex.uz, so that each can be searched on "
            "its own. Cover every distinct legal issue the user faces now, e.g. the right or benefit asked about and "
            "its conditions, the grounds on which it is refused, and where and how a refusal can be appealed; leave "
            "out steps the user has already taken (how to apply, when the application was made and refused). One "
            "issue per question, at most 12 words; each question names the benefit, register, document or procedure "
            "it is about, not the office the user visited. Use the names the current legislation uses, e.g. \"Ijtimoiy reyestr\" "
            "(not \"Ijtimoiy himoya yagona reyestri\" or \"reestr\"), \"tibbiy-ijtimoiy ekspert komissiyasi\" (not VTEK, "
            "TMEK), \"nogironligi bo'lgan shaxs\", \"'Inson' ijtimoiy xizmatlar markazi\", \"davlat xizmatlari markazi\". "
            "Do not add facts and do not answer. "
            "Example: 'Салом мен 2 гурух ногиронман ВТЭК гурухимни олиб ташлади пенсиям тухтади нима килай' -> "
            "[\"Tibbiy-ijtimoiy ekspert komissiyasining qarori ustidan qayerga shikoyat qilinadi?\", "
            "\"Qayta ko'rikda nogironlik guruhi qanday asoslarda olib tashlanadi?\", "
            "\"Nogironlik bekor qilinganda nogironlik pensiyasini to'lash to'xtatiladimi?\"]. "
            "Output ONLY a JSON array of strings."
        )
        user_message = query
        if terms:
            user_message += (
                "\n\n[Terms the legislation itself uses for words of this message; use them in the questions when "
                "they fit, and do not copy the everyday word instead: " + "; ".join(terms) + "]"
            )
        try:
            raw = await client.chat_completion(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                temperature=0.0,
                max_tokens=1500,
                min_chars=2,
                reasoning={"enabled": False},
                light=True,
            )
            questions = _parse_subquestions(raw or "")
            if not questions:
                return None
            cls._cache[cache_key] = questions
            cls._cache.move_to_end(cache_key)
            if len(cls._cache) > MAX_CACHE_SIZE:
                cls._cache.popitem(last=False)
            return list(questions)
        except Exception as e:
            logger.warning(f"Legal sub-question rewrite failed: {e}")
            return None


def _parse_subquestions(raw: str) -> List[str]:
    """The JSON array of the reply, keeping short Latin-script questions only (at most MAX_SUBQUESTIONS, no repeats)."""
    m = re.search(r"\[.*\]", raw, re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        return []
    questions: List[str] = []
    for item in items if isinstance(items, list) else []:
        q = " ".join(str(item).split())
        if (
            len(q) < 10 or len(q) > MAX_SUBQUESTION_CHARS
            or any("Ѐ" <= ch <= "ӿ" for ch in q)
            or q.lower() in {x.lower() for x in questions}
        ):
            continue
        questions.append(q)
    return questions[:MAX_SUBQUESTIONS]
