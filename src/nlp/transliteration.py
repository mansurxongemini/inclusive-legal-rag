import re
from typing import Literal

# Apostrophe variants
APOSTROPHES = "’‘`ʻʼ''"
APOSTROPHE_PATTERN = re.compile(f"[{re.escape(APOSTROPHES)}]")

VOWELS_CYRILLIC = "аеёиоуўэюяАЕЁИОУЎЭЮЯ"
VOWELS_LATIN = "aeiouo'AEIOUO'"

# Special word dictionary for high-precision transliteration
SPECIAL_WORDS = {
    "сентябрь": "sentabr",
    "октябрь": "oktabr",
    "ноябрь": "noyabr",
    "декабрь": "dekabr",
    "январь": "yanvar",
    "февраль": "fevral",
    "апрель": "aprel",
    "июль": "iyul",
    "июнь": "iyun",
    "рубль": "rubl",
    "автомобиль": "avtomobil",
    "контроль": "kontrol",
    "роль": "rol",
    "цирк": "tsirk",
    "цех": "tsex",
    "конституция": "konstitutsiya",
    "инвалид": "nogiron",
    "инвалидлик": "nogironlik",
}


def normalize_apostrophes(text: str) -> str:
    """Standardizes all apostrophe variants to a single standard ASCII apostrophe `'`."""
    return APOSTROPHE_PATTERN.sub("'", text)


def detect_script(text: str) -> Literal["cyrillic", "latin", "unknown"]:
    """Detects whether text is primarily Cyrillic or Latin script."""
    cyrillic_count = len(re.findall(r"[\u0400-\u04FF]", text))
    latin_count = len(re.findall(r"[a-zA-Z]", text))
    
    if cyrillic_count == 0 and latin_count == 0:
        return "unknown"
    if cyrillic_count > latin_count:
        return "cyrillic"
    return "latin"


def cyrillic_to_latin(text: str) -> str:
    """
    High-accuracy rule-based Cyrillic to Latin transliterator for Uzbek.
    Properly handles contextual letters:
    - Е/е: 'ye' at start of word, after vowel, or after soft/hard sign; 'e' after consonant
    - Ё/ё -> Yo/yo
    - Ю/ю -> Yu/yu
    - Я/я -> Ya/ya
    - Ц/ц -> Ts/ts
    - Ч/ч -> Ch/ch
    - Ш/ш -> Sh/sh
    - Щ/щ -> Sh/sh
    - Ў/ў -> O'/o'
    - Ғ/ғ -> G'/g'
    - Ъ/ъ -> ' (tutuq belgisi)
    - Ь/ь -> omitted or apostrophe depending on context
    """
    if not text:
        return ""

    # Check for known special words. Split on whitespace runs but keep them, so line breaks survive
    # (numbered case questions are separated by newlines and are decomposed on them).
    words = re.split(r"(\s+)", text)
    processed_words = []

    for word in words:
        if not word or word.isspace():
            processed_words.append(word)
            continue
        clean_word = word.strip(".,!?:;\"'()[]{}«»")
        lower_clean = clean_word.lower()
        if lower_clean in SPECIAL_WORDS:
            replacement = SPECIAL_WORDS[lower_clean]
            if clean_word.isupper():
                replacement = replacement.upper()
            elif clean_word[0].isupper():
                replacement = replacement.capitalize()
            # replace in word
            word = word.replace(clean_word, replacement)
        processed_words.append(word)

    text = "".join(processed_words)

    result = []
    length = len(text)
    
    i = 0
    while i < length:
        ch = text[i]
        prev_ch = text[i - 1] if i > 0 else ""
        next_ch = text[i + 1] if i + 1 < length else ""
        
        # Check two-character digraphs or special cases
        # 1. Е / е handling
        if ch in ("е", "Е"):
            is_start_of_word = (i == 0) or (not prev_ch.isalnum() and prev_ch not in "'-")
            is_after_vowel_or_sign = prev_ch in VOWELS_CYRILLIC or prev_ch in "ъьЪЬ"
            
            if is_start_of_word or is_after_vowel_or_sign:
                if ch == "Е":
                    # Check next character capitalization
                    result.append("YE" if next_ch.isupper() else "Ye")
                else:
                    result.append("ye")
            else:
                result.append("E" if ch.isupper() else "e")
            i += 1
            continue

        # 2. Ё / ё
        if ch == "ё":
            result.append("yo")
            i += 1
            continue
        if ch == "Ё":
            result.append("YO" if next_ch.isupper() else "Yo")
            i += 1
            continue

        # 3. Ю / ю
        if ch == "ю":
            result.append("yu")
            i += 1
            continue
        if ch == "Ю":
            result.append("YU" if next_ch.isupper() else "Yu")
            i += 1
            continue

        # 4. Я / я
        if ch == "я":
            result.append("ya")
            i += 1
            continue
        if ch == "Я":
            result.append("YA" if next_ch.isupper() else "Ya")
            i += 1
            continue

        # 5. Ц / ц
        if ch == "ц":
            result.append("ts")
            i += 1
            continue
        if ch == "Ц":
            result.append("TS" if next_ch.isupper() else "Ts")
            i += 1
            continue

        # 6. Ч / ч
        if ch == "ч":
            result.append("ch")
            i += 1
            continue
        if ch == "Ч":
            result.append("CH" if next_ch.isupper() else "Ch")
            i += 1
            continue

        # 7. Ш / ш
        if ch == "ш":
            result.append("sh")
            i += 1
            continue
        if ch == "Ш":
            result.append("SH" if next_ch.isupper() else "Sh")
            i += 1
            continue

        # 8. Щ / щ
        if ch == "щ":
            result.append("sh")
            i += 1
            continue
        if ch == "Щ":
            result.append("SH" if next_ch.isupper() else "Sh")
            i += 1
            continue

        # 9. Ў / ў (Uzbek O')
        if ch == "ў":
            result.append("o'")
            i += 1
            continue
        if ch == "Ў":
            result.append("O'")
            i += 1
            continue

        # 10. Ғ / ғ (Uzbek G')
        if ch == "ғ":
            result.append("g'")
            i += 1
            continue
        if ch == "Ғ":
            result.append("G'")
            i += 1
            continue

        # 11. Ъ / ъ (tutuq belgisi)
        if ch in ("ъ", "Ъ"):
            # Avoid duplicate apostrophe if preceded by o' or g' (ў / ғ)
            if prev_ch in ("ў", "Ў", "ғ", "Ғ") or (result and result[-1].endswith("'")):
                i += 1
                continue
            result.append("'")
            i += 1
            continue

        # 12. Ь / ь (soft sign, usually dropped in Uzbek Latin)
        if ch in ("ь", "Ь"):
            # If followed by a vowel like е, it will have been treated, else drop
            i += 1
            continue

        # 13. Regular Cyrillic mappings
        char_map = {
            "а": "a", "А": "A",
            "б": "b", "Б": "B",
            "в": "v", "В": "V",
            "г": "g", "Г": "G",
            "д": "d", "Д": "D",
            "ж": "j", "Ж": "J",
            "з": "z", "З": "Z",
            "и": "i", "И": "I",
            "й": "y", "Й": "Y",
            "к": "k", "К": "K",
            "л": "l", "Л": "L",
            "м": "m", "М": "M",
            "н": "n", "Н": "N",
            "о": "o", "О": "O",
            "п": "p", "П": "P",
            "р": "r", "Р": "R",
            "с": "s", "С": "S",
            "т": "t", "Т": "T",
            "у": "u", "У": "U",
            "ф": "f", "Ф": "F",
            "х": "x", "Х": "X",
            "ҳ": "h", "Ҳ": "H",
            "қ": "q", "Қ": "Q",
            "э": "e", "Э": "E",
        }

        if ch in char_map:
            result.append(char_map[ch])
        else:
            result.append(ch)
        i += 1

    latin_text = "".join(result)
    latin_text = re.sub(r"'+", "'", latin_text)
    return normalize_apostrophes(latin_text)


def normalize_uzbek_query(query: str) -> str:
    """Normalizes query text: converts Cyrillic Uzbek to Latin and unifies apostrophes."""
    normalized = normalize_apostrophes(query.strip())
    if detect_script(normalized) == "cyrillic":
        # Check if query is Russian or Uzbek Cyrillic:
        # If it has specific Uzbek letters (ў, ғ, ҳ, қ) or Uzbek words, it's definitely Uzbek Cyrillic.
        # Even if Russian query, transliteration only occurs if script is detected as Cyrillic and language is uz.
        normalized = cyrillic_to_latin(normalized)
    return normalized


UZBEK_CYRILLIC_SPECIFIC_CHARS = set("ўғқҳЎҒҚҲ")
UZBEK_CYRILLIC_COMMON_WORDS = {
    "тўғрисида", "билан", "учун", "ҳам", "бўйича", "ҳуқуқи", "модда", "бандида",
    "орқали", "эса", "асосан", "белгиланган", "амалга", "ошириш", "давлат", "хизмати",
    "берилган", "керак", "йўқ", "бўлган", "шахс", "фуқаро", "республикаси", "вазирлиги",
    "қарори", "фармони", "тўғрисидаги", "мувофиқ", "киритиш", "чора", "тадбирлари",
    "ўзбекистон", "бекор", "қилиш", "бошқа", "ҳар", "бир", "шунингдек", "олинган",
    "вазифалари", "тасдиқлаш", "мажбуриятлари", "ҳужжат", "иловага", "банд", "қисми",
    "тартиби", "бошлаб", "ходимларининг", "ҳақи", "йилнинг", "асосида", "назарда"
}
RUSSIAN_LEGAL_MARKERS = {
    "статья", "пункт", "настоящий", "закон", "указ", "постановление",
    "республики", "узбекистан", "соответствии", "целях", "утвердить",
    "внести", "изменения", "граждан", "деятельности", "обеспечения",
    "правительства", "министерства", "года", "принять", "часть",
    "кодекс", "регулирует", "отношения", "связанные", "ними", "общественные"
}


def is_genuine_russian(text: str) -> bool:
    """
    Determines if a Cyrillic text is genuine Russian vs Uzbek written in Cyrillic.
    Lex.uz serves Uzbek legal acts in Cyrillic, which must not be mistakenly classified
    or indexed as Russian translations.
    """
    if not text or not text.strip():
        return False
    if any(c in UZBEK_CYRILLIC_SPECIFIC_CHARS for c in text):
        return False
    words = set(re.findall(r"\b[а-яёА-ЯЁўғқҳЎҒҚҲ]+\b", text.lower()))
    if len(words.intersection(UZBEK_CYRILLIC_COMMON_WORDS)) >= 1:
        return False
    ru_hits = len(words.intersection(RUSSIAN_LEGAL_MARKERS))
    return ru_hits >= 1
