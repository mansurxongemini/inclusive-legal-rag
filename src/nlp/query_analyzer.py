import re
from typing import List, Literal, Optional
from pydantic import BaseModel
from .transliteration import (
    UZBEK_CYRILLIC_COMMON_WORDS,
    cyrillic_to_latin,
    detect_script,
    normalize_apostrophes,
)

SupportedLanguage = Literal["uz", "ru", "en"]


class QueryAnalysis(BaseModel):
    raw_query: str
    detected_language: SupportedLanguage
    detected_script: Literal["cyrillic", "latin", "unknown"]
    normalized_query: str
    target_article_number: Optional[str] = None
    target_law_number: Optional[str] = None
    target_law_id: Optional[str] = None
    extracted_disability_types: List[str] = []



class QueryAnalyzer:
    """Heuristic and regex-based fast multilingual query analyzer."""

    UZBEK_SPECIFIC_CHARS = set("ўғқҳЎҒҚҲ")
    RUSSIAN_SPECIFIC_CHARS = set("ыэёъьЫЭЁЪЬ")

    UZBEK_KEYWORDS = {
        "nogiron", "nogironlik", "huquq", "huquqlari", "qonun", "modda", "qism", "band",
        "ish", "ishga", "ishlash", "mehnat", "ta'lim", "pensiya", "nafaqa", "yordam",
        "imtiyoz", "tibbiy", "sharoit", "parvarish", "ijtimoiy", "bolalar", "himoya",
        "qanday", "bormi", "mumkinmi", "kimlar", "belgilangan", "uchun",
        "jinoyat", "jazo", "jarima", "soliq", "soliqlar", "bojxona", "sud", "sudya",
        "shartnoma", "mulk", "meros", "oila", "nikoh", "aliment", "javobgarlik",
        "ma'muriy", "kodeks", "kodeksi", "kodeksining", "protsess", "da'vo", "shikoyat"
    }

    RUSSIAN_KEYWORDS = {
        "инвалид", "инвалидность", "права", "право", "закон", "статья", "пункт", "часть",
        "работа", "труд", "образование", "пенсия", "пособие", "помощь", "льготы",
        "медицинская", "условия", "социальная", "дети", "защита", "как", "есть", "можно",
        "для", "кто", "установлен", "льгота",
        "преступление", "наказание", "штраф", "налог", "налоги", "таможня", "суд", "судья",
        "договор", "собственность", "наследство", "семья", "брак", "алименты", "ответственность",
        "административный", "кодекс", "кодекса", "процесс", "иск", "жалоба"
    }

    ENGLISH_KEYWORDS = {
        "disability", "disabled", "rights", "right", "law", "article", "section", "point",
        "work", "labor", "education", "pension", "benefit", "help", "privilege",
        "medical", "conditions", "social", "children", "protection", "how", "what", "is",
        "can", "who", "for", "eligible", "employment",
        "crime", "criminal", "punishment", "fine", "tax", "taxes", "customs", "court",
        "contract", "property", "inheritance", "family", "marriage", "alimony", "liability",
        "administrative", "code", "procedure", "claim", "appeal"
    }

    SUPERSCRIPT_MAP = {
        "¹": "-1", "²": "-2", "³": "-3", "⁴": "-4", "⁵": "-5",
        "⁶": "-6", "⁷": "-7", "⁸": "-8", "⁹": "-9", "⁰": "-0",
    }

    @classmethod
    def detect_language(cls, text: str) -> SupportedLanguage:
        normalized = normalize_apostrophes(text).lower()
        words = set(re.findall(r"\b\w+\b", normalized))
        
        # Check Cyrillic vs Latin
        script = detect_script(text)
        
        # Check English words
        en_matches = len(words.intersection(cls.ENGLISH_KEYWORDS))
        ru_matches = len(words.intersection(cls.RUSSIAN_KEYWORDS))
        uz_matches = len(words.intersection(cls.UZBEK_KEYWORDS))

        if any(char in cls.UZBEK_SPECIFIC_CHARS for char in text):
            return "uz"
        
        if script == "cyrillic":
            # Can be Uzbek Cyrillic or Russian. UZBEK_KEYWORDS are Latin, so Cyrillic words must be
            # transliterated before matching (otherwise every Cyrillic query without ў/ғ/қ/ҳ became "ru").
            cyr_words = set(re.findall(r"[а-яёўғқҳ]+", text.lower()))
            latin_words = set(re.findall(r"\w+", normalize_apostrophes(cyrillic_to_latin(" ".join(cyr_words)))))
            uz_cyr_hits = len(cyr_words.intersection(UZBEK_CYRILLIC_COMMON_WORDS)) + len(
                latin_words.intersection(cls.UZBEK_KEYWORDS)
            )
            if uz_cyr_hits > ru_matches:
                return "uz"
            return "ru"
        
        # In Latin script
        if en_matches > uz_matches and en_matches > 0:
            return "en"
        
        return "uz"

    @classmethod
    def extract_article_number(cls, text: str) -> Optional[str]:
        """Extracts article mentions like '15-modda', '18-1-modda', 'статья 18-1', '244-6-modda'."""
        patterns = [
            r"(\d+(?:[-–—\.]\d+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\s*[-–—]?\s*(?:modda|статья|article)",
            r"(?:modda|статья|article)\s*(\d+(?:[-–—\.]\d+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)",
            r"(\d+(?:[-–—\.]\d+|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\s*[-–—]?\s*(?:band|qism|пункт)",
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                raw_num = match.group(1)
                for sup_char, repl in cls.SUPERSCRIPT_MAP.items():
                    raw_num = raw_num.replace(sup_char, repl)
                raw_num = re.sub(r"[\.–—]", "-", raw_num)
                return f"{raw_num}-modda"
        return None

    @classmethod
    def extract_law_number(cls, text: str) -> Optional[str]:
        """Extracts law numbers like 'O'RQ-641', 'ЗРУ-641'."""
        match = re.search(r"(?:O['`’‘ʻʼ]?RQ|ЗРУ|ZRU)[-–—\s]*(\d+)", text, re.IGNORECASE)
        if match:
            return f"O'RQ-{match.group(1)}"
        return None

    # (pattern, law_id) - law_ids are those assigned in data/sources/seeds.json / the corpus builder
    CODE_ACRONYM_PATTERNS = [
        (r"\b(o['`’‘ʻʼ]?rq[-\s]?641|nogironligi bo['`’‘ʻʼ]?lgan shaxslarning huquqlari to['`’‘ʻʼ]?g['`’‘ʻʼ]?risida|"
         r"закон\w* о правах лиц с инвалидностью|law on the rights of persons with disabilities)\b", "law_disability_2020"),
        (r"\b(konvensiya\w*|конвенци\w*|convention|crpd|bmt nogironlar)\b", "crpd_2006"),
        (r"\b(konstitutsiya\w*|конституци\w*|constitution)\b", "constitution_uz"),
        (r"\b(mehnat kodeks\w*|трудов\w* кодекс\w*|labou?r code|\bmk\b|\bтк\b)\b", "labor_code_2022"),
        (r"\b(soliq kodeks\w*|налогов\w* кодекс\w*|tax code|\bsk\b|\bнк\b)\b", "tax_code_2020"),
        (r"\b(uy[- ]?joy kodeks\w*|жилищн\w* кодекс\w*|housing code)\b", "housing_code"),
        (r"\b(shaharsozlik kodeks\w*|градостроительн\w* кодекс\w*|urban planning code)\b", "urban_code_2021"),
        (r"\b(fuqarolik kodeks\w*|гражданск\w* кодекс\w*|civil code|\bfk\b|\bгк\b)\b", "civil_code_1"),
        (r"\b(oila kodeks\w*|семейн\w* кодекс\w*|family code)\b", "family_code"),
        (r"\b(jinoyat kodeks\w*|уголовн\w* кодекс\w*|criminal code|\bjk\b|\bук\b)\b", "criminal_code"),
        (r"\b(mjtk|ma['`’‘ʻʼ]?muriy javobgarlik\w*|коап|административн\w* ответственност\w*)\b", "admin_liability_code"),
        (r"\b(saylov kodeks\w*|избирательн\w* кодекс\w*|election code)\b", "election_code"),
        (r"\b(ta['`’‘ʻʼ]?lim to['`’‘ʻʼ]?g['`’‘ʻʼ]?risidagi qonun\w*|закон\w* об образовании|education law)\b", "education_law_2020"),
    ]

    @classmethod
    def extract_law_id(cls, text: str) -> Optional[str]:
        """Extracts canonical law_id from common acronyms (MJtK, JK, MK, etc.) or full titles."""
        for pattern, law_id in cls.CODE_ACRONYM_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return law_id
        return None

    # Russian / English wording that the Latin-only taxonomy patterns do not cover
    _EXTRA_TYPE_PATTERNS = {
        "visual": [r"слеп", r"слабовидящ", r"зрени", r"\bblind\b", r"visual impairment", r"visually"],
        "hearing": [r"глух", r"слабослышащ", r"слух", r"\bdeaf\b", r"hearing"],
        "physical": [r"коляск", r"опорно-двигательн", r"двигательн", r"wheelchair", r"mobility", r"physical disab"],
        "intellectual": [r"умственн", r"интеллектуальн", r"психическ", r"intellectual", r"mental"],
        "childhood_disability": [r"ребен[ок]+\s+с\s+инвалидн", r"дет\w*\s+с\s+инвалидн", r"инвалид\w*\s+с\s+детства",
                                 r"disabled child", r"children with disab", r"child with disab"],
        "group_1": [r"\b1\s*групп", r"перв\w+\s+групп", r"\bi\s+групп", r"group\s*(?:1|i)\b", r"first group"],
        "group_2": [r"\b2\s*групп", r"втор\w+\s+групп", r"\bii\s+групп", r"group\s*(?:2|ii)\b", r"second group"],
        "group_3": [r"\b3\s*групп", r"трет\w+\s+групп", r"\biii\s+групп", r"group\s*(?:3|iii)\b", r"third group"],
    }

    @classmethod
    def extract_disability_types(cls, text: str) -> List[str]:
        """Beneficiary groups mentioned in the question, in the same vocabulary as the corpus metadata."""
        from src.domain.disability_taxonomy import detect_disability_groups

        found = [g for g in detect_disability_groups(text) if g != "general"]
        lower = text.lower()
        for gid, patterns in cls._EXTRA_TYPE_PATTERNS.items():
            if gid not in found and any(re.search(p, lower) for p in patterns):
                found.append(gid)
        return found if found else ["general"]

    @classmethod
    def analyze(cls, query: str, user_language: Optional[str] = None) -> QueryAnalysis:
        cleaned = query.strip()
        script = detect_script(cleaned)
        
        detected_lang: SupportedLanguage
        if user_language and user_language in ("uz", "ru", "en"):
            detected_lang = user_language  # type: ignore
        else:
            detected_lang = cls.detect_language(cleaned)

        # Normalize query:
        # If detected language is Uzbek and script is Cyrillic, transliterate to Latin
        if detected_lang == "uz" and script == "cyrillic":
            normalized = cyrillic_to_latin(cleaned)
        else:
            normalized = normalize_apostrophes(cleaned)

        art_num = cls.extract_article_number(cleaned)
        law_num = cls.extract_law_number(cleaned)
        law_id = cls.extract_law_id(cleaned)
        disability_types = cls.extract_disability_types(cleaned)

        return QueryAnalysis(
            raw_query=cleaned,
            detected_language=detected_lang,
            detected_script=script,
            normalized_query=normalized,
            target_article_number=art_num,
            target_law_number=law_num,
            target_law_id=law_id,
            extracted_disability_types=disability_types,
        )

