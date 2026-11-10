"""
Single source of truth for the disability-rights domain: legal categories, beneficiary groups and the
rules that map official Lex.uz classifier (OKOZ) nodes and wording to them.

Used by ingestion (tagging), query analysis (scope detection) and the public API (filters).
"""
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from src.nlp.transliteration import cyrillic_to_latin, detect_script, normalize_apostrophes


@dataclass(frozen=True)
class Category:
    id: str
    name_uz: str
    name_ru: str
    description_uz: str


CATEGORIES: List[Category] = [
    Category("disability_rights", "Umumiy huquqlar va kafolatlar", "Общие права и гарантии",
             "Nogironligi bo'lgan shaxslarning asosiy huquqlari, kamsitishni taqiqlash, davlat kafolatlari"),
    Category("medical_social_expertise", "Tibbiy-ijtimoiy ekspertiza (TIEK/TMEK)", "Медико-социальная экспертиза",
             "Nogironlikni belgilash, guruhlar, qayta ko'rik, ekspert komissiyalari, shikoyat tartibi"),
    Category("pensions_and_benefits", "Pensiya, nafaqa va to'lovlar", "Пенсии, пособия и выплаты",
             "Nogironlik pensiyasi, nafaqalar, kompensatsiyalar, moddiy yordam"),
    Category("labor_rights", "Mehnat huquqlari va bandlik", "Трудовые права и занятость",
             "Ish o'rinlari kvotasi, qisqartirilgan ish vaqti, ishga joylashtirish, mehnat shartlari"),
    Category("tax_benefits", "Soliq va boj imtiyozlari", "Налоговые и пошлинные льготы",
             "Soliq, davlat boji, to'lovlardan ozod etish va chegirmalar"),
    Category("rehabilitation_prosthetics", "Reabilitatsiya, protez va texnik vositalar", "Реабилитация и технические средства",
             "Reabilitatsiya dasturi, protez-ortopediya buyumlari, aravacha, eshitish apparati"),
    Category("healthcare", "Tibbiy yordam va dori vositalari", "Медицинская помощь и лекарства",
             "Tibbiy xizmatlar, dispanser kuzatuvi, dori-darmon bilan ta'minlash"),
    Category("sanatorium_health", "Sanatoriy-kurort davolanishi", "Санаторно-курортное лечение",
             "Yo'llanmalar, sanatoriyda davolanish va reabilitatsiya"),
    Category("inclusive_education", "Inklyuziv ta'lim", "Инклюзивное образование",
             "Maktabgacha, umumiy o'rta, kasb-hunar va oliy ta'lim, grant kvotalari, maxsus ehtiyojli o'quvchilar"),
    Category("accessibility_infrastructure", "To'siqsiz muhit va qulaylik", "Доступная среда",
             "Binolar, transport infratuzilmasi, axborotdan foydalanish, shaharsozlik talablari"),
    Category("transport_benefits", "Transport imtiyozlari", "Транспортные льготы",
             "Jamoat transporti, havo/temir yo'l, chiptalarda chegirmalar, avtotransport vositalari"),
    Category("housing_rights", "Uy-joy huquqlari", "Жилищные права",
             "Uy-joy olish, ipoteka, kommunal imtiyozlar, moslashtirilgan turar joy"),
    Category("social_services", "Ijtimoiy xizmatlar va muassasalar", "Социальные услуги и учреждения",
             "Ijtimoiy xizmat ko'rsatish, 'Muruvvat' internat uylari, patronaj, parvarish"),
    Category("social_protection_governance", "Ijtimoiy himoya tizimi va organlar", "Система социальной защиты",
             "Ijtimoiy himoya milliy agentligi, yagona reyestr, 'Inson' markazlari, vakolatlar"),
    Category("legal_protection", "Huquqiy himoya va shikoyat", "Правовая защита и обжалование",
             "Sud himoyasi, shikoyat, javobgarlik, huquqbuzarliklar"),
    Category("international_treaty", "Xalqaro shartnomalar", "Международные договоры",
             "BMT Nogironlar huquqlari konvensiyasi va boshqa xalqaro hujjatlar"),
]
CATEGORY_IDS = [c.id for c in CATEGORIES]
CATEGORY_BY_ID: Dict[str, Category] = {c.id: c for c in CATEGORIES}


@dataclass(frozen=True)
class DisabilityGroup:
    id: str
    name_uz: str
    patterns: Tuple[str, ...]


# Patterns are matched against lowercase Latin text with ASCII apostrophes.
DISABILITY_GROUPS: List[DisabilityGroup] = [
    DisabilityGroup("group_1", "I guruh nogironligi bo'lgan shaxslar",
                    (r"\bi\s*guruh", r"\b1\s*-?\s*guruh", r"birinchi guruh", r"\bi-guruh")),
    DisabilityGroup("group_2", "II guruh nogironligi bo'lgan shaxslar",
                    (r"\bii\s*guruh", r"\b2\s*-?\s*guruh", r"ikkinchi guruh", r"\bii-guruh")),
    DisabilityGroup("group_3", "III guruh nogironligi bo'lgan shaxslar",
                    (r"\biii\s*guruh", r"\b3\s*-?\s*guruh", r"uchinchi guruh", r"\biii-guruh")),
    DisabilityGroup("childhood_disability", "Nogironligi bo'lgan bolalar (18 yoshgacha)",
                    (r"bolalikdan nogiron", r"nogironligi bo'lgan bol", r"nogiron bol", r"16 yoshgacha", r"18 yoshgacha",
                     r"bolalikdan")),
    DisabilityGroup("visual", "Ko'rish bo'yicha nogironlik",
                    (r"ko'rish bo'yicha", r"ko'zi ojiz", r"ko'rish qobiliyati", r"ko'rish a'zolari", r"\bbrayl", r"zaif ko'ruvchi")),
    DisabilityGroup("hearing", "Eshitish bo'yicha nogironlik",
                    (r"eshitish bo'yicha", r"eshitish qobiliyati", r"karlar\b", r"\bkar\b", r"surdo", r"eshitish apparat")),
    DisabilityGroup("physical", "Tayanch-harakat a'zolari bo'yicha nogironlik",
                    (r"tayanch-harakat", r"harakatlanish", r"nogironlik aravacha", r"kreslo-aravacha", r"\baravacha", r"amputatsiya")),
    DisabilityGroup("intellectual", "Aqliy rivojlanish / ruhiy nogironlik",
                    (r"aqliy rivojlanish", r"aqliy zaif", r"ruhiy kasal", r"ruhiy nogiron", r"psixik", r"autizm", r"daun")),
]

# Official OKOZ classifier node -> category. Only the disability-specific nodes are listed: an act is usually
# indexed under many unrelated nodes (education, tax, transport ...) and those must not decide its category.
OKOZ_CATEGORY_RULES: List[Tuple[str, str]] = [
    ("06.06.17", "medical_social_expertise"),   # Nogironlikni belgilash
    ("14.01.10", "medical_social_expertise"),   # Tibbiy-ijtimoiy ekspertiza
    ("06.06.03", "pensions_and_benefits"),      # Nogironlik pensiyasi
    ("06.07.01.03", "pensions_and_benefits"),   # Nogironligi bo'lgan bolalarga nafaqalar
    ("06.07.02.01", "pensions_and_benefits"),   # Kompensatsiya to'lovlari
    ("06.09.01", "pensions_and_benefits"),      # Imtiyozlar
    ("06.08.04", "rehabilitation_prosthetics"),
    ("14.01.03.05", "rehabilitation_prosthetics"),
    ("06.08.02", "social_services"),
    ("14.01.07", "healthcare"),
    ("05.09.03", "labor_rights"),
    ("06.10", "disability_rights"),
]

# Wording rules, strongest first. Applied to the document title (weight 3) and the unit text (weight 1).
_KEYWORD_RULES: List[Tuple[str, str]] = [
    (r"tibbiy-ijtimoiy ekspert|\btiek\b|\btmek\b|nogironlikni belgilash|nogironlik guruh", "medical_social_expertise"),
    (r"konvensiya|xalqaro shartnoma", "international_treaty"),
    (r"protez|ortopedi|texnik vosita|reabilitatsiya|aravacha|eshitish apparat", "rehabilitation_prosthetics"),
    (r"sanatoriy|kurort|yo'llanma", "sanatorium_health"),
    (r"to'siqsiz|to'siqlarsiz|qulay muhit|pandus|infratuzilma|shaharsozlik|axborotdan foydalan", "accessibility_infrastructure"),
    (r"inklyuziv|ta'lim|maktab|universitet|grant|talaba|o'quvchi", "inclusive_education"),
    (r"soliq|davlat boji|bojxona|boj\b", "tax_benefits"),
    (r"transport|chipta|yo'l haqi|avtomobil|havo yo'l|temir yo'l", "transport_benefits"),
    (r"uy-joy|turar joy|kvartira|ipoteka|kommunal", "housing_rights"),
    (r"mehnat|ish o'rni|ish o'rinlari|bandlik|ishga joylash|ish vaqti|kvota", "labor_rights"),
    (r"pensiya|nafaqa|kompensatsiya|moddiy yordam|ijtimoiy to'lov", "pensions_and_benefits"),
    (r"ijtimoiy xizmat|internat|muruvvat|saxovat|patronaj|parvarish", "social_services"),
    (r"ijtimoiy himoya milliy agentligi|yagona reyestr|inson markaz|ijtimoiy himoya", "social_protection_governance"),
    (r"sud\b|shikoyat|javobgarlik|jinoyat|ma'muriy huquqbuzarlik", "legal_protection"),
    (r"tibbiy yordam|dori\b|dori vosita|dori-darmon|davolanish|tibbiy xizmat|sog'liqni saqlash|sog'lig'ini saqlash|tibbiyot muassasa", "healthcare"),
]

DISABILITY_TERMS = re.compile(
    r"nogiron|imkoniyati cheklangan|imkoniyatlari cheklangan|nogironlik|tibbiy-ijtimoiy ekspert|\btiek\b|\btmek\b|"
    r"reabilitatsiya|to'siqsiz|to'siqlarsiz|alohida ta'lim ehtiyoj|ehtiyojli bol|протез|инвалид|ногирон",
    re.IGNORECASE,
)


def to_search_latin(text: str) -> str:
    """Lowercase, ASCII-apostrophe Latin form used by all rule matching."""
    t = normalize_apostrophes(text or "")
    if detect_script(t) == "cyrillic":
        t = cyrillic_to_latin(t)
    return t.lower()


def disability_relevance(text: str) -> int:
    """Number of distinct disability-related term hits (0 = not about disability)."""
    t = to_search_latin(text)
    return len({m.group(0).lower() for m in DISABILITY_TERMS.finditer(t)}) + (
        3 if DISABILITY_TERMS.search(t) and len(DISABILITY_TERMS.findall(t)) >= 3 else 0
    )


def detect_disability_groups(text: str) -> List[str]:
    t = to_search_latin(text)
    found = [g.id for g in DISABILITY_GROUPS if any(re.search(p, t) for p in g.patterns)]
    return found or ["general"]


def classify_category(
    title: str = "",
    okoz: Iterable[str] = (),
    text: str = "",
    default: str = "disability_rights",
    min_score: float = 0.0,
) -> str:
    """
    Best category for a title (+ optional text and OKOZ nodes).

    A title hit is worth 6 points, a body hit 1 point (at most 5), an OKOZ node 0.75. With `min_score` a weak
    guess falls back to `default`, which is how a unit inherits the category of its act unless its own heading
    or body clearly says otherwise.
    """
    scores: Dict[str, float] = {}
    title_l = to_search_latin(title)
    body_l = to_search_latin(text[:4000])
    for pattern, cat in _KEYWORD_RULES:
        n_title = len(re.findall(pattern, title_l))
        n_body = len(re.findall(pattern, body_l))
        if n_title or n_body:
            scores[cat] = scores.get(cat, 0.0) + (6.0 if n_title else 0.0) + min(n_body, 5)
    for node in okoz:
        code = (node or "").split(" ", 1)[0]
        for prefix, cat in OKOZ_CATEGORY_RULES:
            if code.startswith(prefix):
                scores[cat] = scores.get(cat, 0.0) + 0.75
                break
    if not scores:
        return default
    cat, best = max(scores.items(), key=lambda kv: kv[1])
    return cat if best >= min_score else default
