import re
from typing import List, Literal, Optional
from pydantic import BaseModel
from .transliteration import (
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

    DISABILITY_KEYWORD_MAP = {
        "visual": ["ko'rish", "ko'zi ojiz", "ko'z", "слеп", "зрен", "глаз", "blind", "visual"],
        "hearing": ["eshitish", "kar", "eshitmaydigan", "глух", "слух", "deaf", "hearing"],
        "physical": ["jismoniy", "harakat", "aravacha", "tayanch", "физическ", "коляск", "двигательн", "physical", "wheelchair", "mobility"],
        "intellectual": ["aqliy", "psixik", "ruhiy", "умственн", "психическ", "mental", "intellectual"],
        "children": ["bola", "bolalar", "bolalikdan", "дет", "ребенок", "с детства", "child", "children"],
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
            # Can be Uzbek Cyrillic or Russian
            if uz_matches > ru_matches:
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

    CODE_ACRONYM_PATTERNS = [
        # Match multi-word / longer specific codes first
        (r"\b(jpk|жпк|упк|jinoyat[- ]?protsessual|уголовно[- ]?процессуальн\w*)\b", "jpk_code"),
        (r"\b(jik|жик|уик|jinoyat[- ]?ijroiya|уголовно[- ]?исполнительн\w*)\b", "jik_code"),
        (r"\b(jk|жк|ук|jinoyat kodeks\w*|уголовн\w* кодекс\w*)\b", "jinoyat_code"),
        (r"\b(mjtk|мжтк|коао|ma['`’‘ʻʼ]?muriy javobgarlik|административн\w* ответственност\w*)\b", "mjtk_code"),
        (r"\b(msiytk|мсийтк|коас|ma['`’‘ʻʼ]?muriy sud ishlar\w*|административн\w* судопроизводств\w*)\b", "msiytk_code"),
        (r"\b(mk|мк|тк|mehnat kodeks\w*|трудов\w* кодекс\w*)\b", "mehnat_code"),
        (r"\b(sk|ск|нк|soliq kodeks\w*|налогов\w* кодекс\w*)\b", "soliq_code"),
        (r"\b(fpk|фпк|гпк|fuqarolik protsessual|гражданско[- ]?процессуальн\w*)\b", "fpk_code"),
        (r"\b(ipk|ипк|эпк|iqtisodiy protsessual|экономическ\w* процессуальн\w*)\b", "ipk_code"),
        (r"\b(fk|фк|гк|fuqarolik kodeks\w*|гражданск\w* кодекс\w*)\b", "fuqarolik_code"),
        (r"\b(oila kodeks\w*|семейн\w* кодекс\w*)\b", "oila_code"),
        (r"\b(bojxona kodeks\w*|таможенн\w* кодекс\w*)\b", "bojxona_code"),
        (r"\b(uy[- ]?joy kodeks\w*|жилищн\w* кодекс\w*)\b", "uy_joy_code"),
        (r"\b(yer kodeks\w*|земельн\w* кодекс\w*)\b", "yer_code"),
        (r"\b(shaharsozlik kodeks\w*|градостроительн\w* кодекс\w*)\b", "shaharsozlik_code"),
        (r"\b(byudjet kodeks\w*|бюджетн\w* кодекс\w*)\b", "byudjet_code"),
        (r"\b(saylov kodeks\w*|избирательн\w* кодекс\w*)\b", "saylov_code"),
        (r"\b(havo kodeks\w*|воздушн\w* кодекс\w*)\b", "havo_code"),
    ]

    @classmethod
    def extract_law_id(cls, text: str) -> Optional[str]:
        """Extracts canonical law_id from common acronyms (MJtK, JK, MK, etc.) or full titles."""
        for pattern, law_id in cls.CODE_ACRONYM_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return law_id
        return None

    @classmethod
    def extract_disability_types(cls, text: str) -> List[str]:
        lower = text.lower()
        matched = []
        for dis_type, keywords in cls.DISABILITY_KEYWORD_MAP.items():
            for kw in keywords:
                if kw in lower:
                    matched.append(dis_type)
                    break
        return matched if matched else ["general"]

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

