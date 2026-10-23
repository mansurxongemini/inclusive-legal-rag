"""
Disability-rights terminology bridge for lexical (BM25) search.

Citizens say "nogiron", "aravacha", "TMEK", "kvota"; statutes say "nogironligi bo'lgan shaxs",
"reabilitatsiyaning texnik vositalari", "tibbiy-ijtimoiy ekspert komissiyasi", "ish o'rinlarini zaxiralash".
Each entry maps a colloquial or older expression to the vocabulary used by current legislation.

Rules for this dictionary:
  * terminology only - never article numbers or amounts (numbering changes with every new code edition, and a
    wrong number injected into a query silently pulls in the wrong provisions);
  * every right-hand term must be a phrase that occurs in official texts.
"""

import re
from typing import Dict, List, Set


LEGAL_SYNONYM_DICTIONARY: Dict[str, List[str]] = {
    # --- who is covered --------------------------------------------------------------------------------
    "nogiron": ["nogironligi bo'lgan shaxs", "nogironligi bo'lgan shaxslar", "nogironlik"],
    "imkoniyati cheklangan": ["nogironligi bo'lgan shaxs", "nogironlik"],
    "imkoniyatlari cheklangan": ["nogironligi bo'lgan shaxs", "nogironlik"],
    "nogironlik guruh": ["nogironlik guruhi", "tibbiy-ijtimoiy ekspert komissiyasi", "nogironlikni belgilash"],
    "bolalikdan nogiron": ["bolalikdan nogironligi bo'lgan shaxs", "nogironligi bo'lgan bola"],
    "nogiron bola": ["nogironligi bo'lgan bola", "16 yoshgacha bo'lgan nogironligi bo'lgan bola", "bolalikdan nogironlik"],
    "ko'zi ojiz": ["ko'rish bo'yicha nogironligi bo'lgan shaxs", "ko'rish qobiliyati buzilgan"],
    "kar": ["eshitish bo'yicha nogironligi bo'lgan shaxs", "eshitish qobiliyati buzilgan", "surdotarjima"],
    "soqov": ["nutq buzilgan", "eshitish va nutq bo'yicha nogironlik"],
    "aqli zaif": ["aqliy rivojlanish buzilgan shaxs", "ruhiy holati buzilgan shaxs"],

    # --- recognition of disability (TIEK) --------------------------------------------------------------
    "tmek": ["tibbiy-ijtimoiy ekspert komissiyasi", "TIEK", "nogironlikni belgilash"],
    "tiek": ["tibbiy-ijtimoiy ekspert komissiyasi", "nogironlikni belgilash"],
    "vtek": ["tibbiy-ijtimoiy ekspert komissiyasi", "TIEK", "nogironlikni belgilash"],
    "ekspertiza": ["tibbiy-ijtimoiy ekspertiza", "tibbiy-ijtimoiy ekspert komissiyasi"],
    "qayta ko'rik": ["qayta tekshiruv", "nogironlikni qayta ko'rib chiqish", "tibbiy-ijtimoiy ekspertiza"],
    "nogironlik belgilash": ["nogironlikni belgilash", "tibbiy-ijtimoiy ekspertiza", "tibbiy-ijtimoiy ekspert komissiyasi"],
    "nogironlik guvohnoma": ["nogironligi to'g'risidagi ma'lumotnoma", "tibbiy-ijtimoiy ekspertiza xulosasi"],
    "ipr": ["individual reabilitatsiya dasturi", "reabilitatsiya dasturi"],

    # --- money -----------------------------------------------------------------------------------------
    "pensiya": ["nogironlik pensiyasi", "pensiya tayinlash", "pensiya miqdori"],
    "nogironlik pensiya": ["nogironlik pensiyasi", "ijtimoiy pensiya", "eng kam miqdori"],
    "nafaqa": ["ijtimoiy nafaqa", "nogironlik nafaqasi", "bolalikdan nogironligi bo'lgan shaxslarga nafaqa"],
    "parvarish": ["parvarishlash", "qarovchi", "o'zgalar parvarishiga muhtoj", "parvarish nafaqasi"],
    "moddiy yordam": ["ijtimoiy yordam", "yagona ijtimoiy reyestr", "moddiy yordam to'lovi"],
    "kompensatsiya": ["kompensatsiya to'lovlari", "pul kompensatsiyasi"],
    "reyestr": ["Ijtimoiy reyestr", "yagona ijtimoiy reyestr", "ijtimoiy himoya yagona reyestri"],
    "reestr": ["Ijtimoiy reyestr", "yagona ijtimoiy reyestr", "ijtimoiy himoya yagona reyestri"],
    "to'lov": ["to'lovlar", "nafaqa", "kompensatsiya"],

    # --- work ------------------------------------------------------------------------------------------
    "ish o'rni": ["ish o'rinlari", "ish o'rinlarini zaxiralash", "nogironligi bo'lgan shaxslarni ishga joylashtirish"],
    "kvota": ["ish o'rinlari kvotasi", "ish o'rinlarini zaxiralash", "eng kam ish o'rinlari"],
    "ishga olish": ["ishga qabul qilish", "mehnat shartnomasi", "ishga joylashtirish"],
    "ish vaqti": ["ish vaqtining qisqartirilgan davomiyligi", "qisqartirilgan ish vaqti"],
    "mehnat ta'til": ["mehnat ta'tili", "yillik ta'til", "qo'shimcha ta'til"],
    "bandlik": ["aholining bandligi", "ishga joylashtirish", "bandlikka ko'maklashish"],
    "ishsiz": ["ishsiz deb e'tirof etish", "ishsizlik nafaqasi", "bandlik markazi"],
    "ishdan bo'shat": ["mehnat shartnomasini bekor qilish", "ishdan bo'shatish", "kafolatlar"],
    "uyda ishlash": ["uyda ishlash", "masofaviy ishlash", "moslashtirilgan ish sharoitlari"],

    # --- rehabilitation & equipment ---------------------------------------------------------------------
    "aravacha": ["nogironlik aravachasi", "kreslo-aravacha", "reabilitatsiyaning texnik vositalari"],
    "protez": ["protez-ortopediya buyumlari", "protez-ortopediya moslamalari", "reabilitatsiyaning texnik vositalari"],
    "eshitish apparat": ["eshitish apparatlari", "surdotexnika vositalari", "reabilitatsiyaning texnik vositalari"],
    "reabilitatsiya": ["reabilitatsiya dasturi", "tibbiy reabilitatsiya", "ijtimoiy reabilitatsiya"],
    "texnik vosita": ["reabilitatsiyaning texnik vositalari", "protez-ortopediya buyumlari"],
    "sanatoriy": ["sanatoriy-kurort davolanishi", "sanatoriyga yo'llanma", "reabilitatsiya"],
    "yo'llanma": ["sanatoriyga yo'llanma", "bepul yo'llanma", "imtiyozli yo'llanma", "order"],
    "operatsiya": ["jarrohlik amaliyoti", "ixtisoslashtirilgan tibbiy yordam", "imtiyozli yo'llanma", "order"],
    "aperatsiya": ["jarrohlik amaliyoti", "operatsiya", "ixtisoslashtirilgan tibbiy yordam", "imtiyozli yo'llanma", "order"],
    "jarroh": ["jarrohlik amaliyoti", "operatsiya", "ixtisoslashtirilgan tibbiy yordam", "imtiyozli yo'llanma"],
    "order": ["imtiyozli yo'llanma", "tibbiy yordam olish huquqini beruvchi order", "ixtisoslashtirilgan tibbiy yordam"],
    "davolan": ["tibbiy yordam", "ixtisoslashtirilgan tibbiy yordam", "statsionar davolanish", "imtiyozli yo'llanma"],
    "shifoxona": ["tibbiyot muassasasi", "statsionar davolanish", "ixtisoslashtirilgan tibbiy yordam"],
    "kasalxona": ["tibbiyot muassasasi", "statsionar davolanish", "ixtisoslashtirilgan tibbiy yordam"],

    # --- access ----------------------------------------------------------------------------------------
    "pandus": ["to'siqsiz muhit", "qulay muhit", "nogironligi bo'lgan shaxslar uchun qulaylik"],
    "lift": ["to'siqsiz muhit", "binolarning qulayligi"],
    "to'siqsiz": ["to'siqsiz muhit", "qulay muhit yaratish", "obyektlar va xizmatlarning qulayligi"],
    "imo-ishora": ["surdotarjima", "imo-ishora tili", "axborotdan foydalanish"],
    "brayl": ["Brayl yozuvi", "axborotdan foydalanish", "ko'rish bo'yicha nogironligi bo'lgan shaxslar"],

    # --- services and benefits --------------------------------------------------------------------------
    "imtiyoz": ["imtiyozlar", "chegirma", "ozod etiladi", "kafolatlar"],
    "chegirma": ["imtiyozli", "chegirma asosida", "imtiyozlar"],
    "transport": ["jamoat transportidan foydalanish", "yo'l haqi", "imtiyozli yo'l chiptalari"],
    "uy-joy": ["uy-joy sharoitlarini yaxshilash", "uy-joy bilan ta'minlash", "kommunal xizmatlar"],
    "soliq": ["soliq imtiyozlari", "soliqdan ozod etish", "soliq to'lovchi"],
    "davlat boji": ["davlat bojidan ozod etish", "sud xarajatlari"],
    "internat": ["ijtimoiy xizmat ko'rsatish muassasalari", "Muruvvat", "Saxovat", "ijtimoiy xizmat"],
    "ijtimoiy xizmat": ["ijtimoiy xizmatlar", "ijtimoiy xizmat ko'rsatish", "uyda ijtimoiy xizmat"],
    "inklyuziv": ["inklyuziv ta'lim", "alohida ta'lim ehtiyojlari", "maxsus ta'lim ehtiyojlari bo'lgan bolalar"],
    "grant": ["davlat granti", "kvota", "qabul kvotasi"],
    "agentlik": ["Ijtimoiy himoya milliy agentligi", "ijtimoiy himoya"],
    "inson markaz": ["'Inson' ijtimoiy xizmatlar markazi", "ijtimoiy xizmatlar markazi"],

    # --- protection of rights ---------------------------------------------------------------------------
    "kamsit": ["kamsitishga yo'l qo'ymaslik", "nogironlik belgisiga ko'ra kamsitish", "teng huquqlilik"],
    "shikoyat": ["shikoyat qilish", "murojaat qilish huquqi", "sudga shikoyat"],
    "vasiy": ["vasiylik", "homiylik", "muomalaga layoqatsiz"],

    # --- Russian ----------------------------------------------------------------------------------------
    "инвалид": ["лицо с инвалидностью", "лица с инвалидностью", "инвалидность"],
    "инвалидност": ["лица с инвалидностью", "группа инвалидности", "признание инвалидом"],
    "втэк": ["медико-социальная экспертиза", "медико-социальная экспертная комиссия"],
    "мсэк": ["медико-социальная экспертиза", "медико-социальная экспертная комиссия"],
    "пенсия по инвалидности": ["пенсия по инвалидности", "социальная пенсия"],
    "пособие": ["социальное пособие", "пособие по инвалидности"],
    "коляска": ["кресло-коляска", "технические средства реабилитации", "протезно-ортопедические изделия"],
    "льгот": ["льготы", "скидка", "освобождается"],
    "квота": ["квота рабочих мест", "бронирование рабочих мест", "трудоустройство"],
    "реабилитац": ["реабилитация", "индивидуальная программа реабилитации", "технические средства реабилитации"],
    "доступн": ["доступная среда", "безбарьерная среда"],
    "санатори": ["санаторно-курортное лечение", "путевка"],
}


class LegalSynonymExpander:
    """Expands citizen queries with statutory terminology for BM25 and hybrid search."""

    @classmethod
    def expand_terms(cls, query: str, max_terms: int = 5) -> List[str]:
        """
        Returns up to `max_terms` official terms for expressions found in the query.
        Entries are matched as word prefixes ("nogiron" matches "nogironlar") so short keys such as "kar" do not
        fire inside unrelated words ("karta", "tekshiruv").
        """
        q_lower = query.lower()
        expanded: List[str] = []
        seen: Set[str] = set()

        for key, synonyms in LEGAL_SYNONYM_DICTIONARY.items():
            if not re.search(r"(?<!\w)" + re.escape(key), q_lower):
                continue
            if len(key) <= 3 and not re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", q_lower):
                continue
            for syn in synonyms:
                if syn.lower() not in q_lower and syn not in seen:
                    seen.add(syn)
                    expanded.append(syn)
                    if len(expanded) >= max_terms:
                        return expanded

        return expanded

    @classmethod
    def build_enriched_search_query(cls, query: str) -> str:
        """The original text plus statutory terminology."""
        expansion = cls.expand_terms(query)
        if not expansion:
            return query
        return f"{query} {' '.join(expansion)}"
