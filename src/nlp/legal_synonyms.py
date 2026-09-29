"""
Uzbekistan Legal Synonym & Terminology Normalization Engine.
Translates colloquial, slang, and citizen terms into formal statutory legal vocabulary
used in the Constitution, Codes, and Laws of the Republic of Uzbekistan.
"""

import re
from typing import Dict, List, Set


LEGAL_SYNONYM_DICTIONARY: Dict[str, List[str]] = {
    # Mehnat va bandlik
    "ishda qoldirish": ["ishda qoldirishning afzallik huquqi", "malakasi", "mehnat unumdorligi", "167-modda"],
    "birinchi navbatda ishda qoldir": ["afzallik huquqi", "malakasi va mehnat unumdorligi", "mehnat kodeksi 167-modda"],
    "kim qoldiriladi": ["ishda qoldirishning afzallik huquqi", "167-modda"],
    "shtat qisqar": ["xodimlar soni yoki shtati qisqarishi", "mehnat shartnomasini bekor qilish", "161-modda", "167-modda", "173-modda"],
    "ishdan hayda": ["mehnat shartnomasini ish beruvchining tashabbusi bilan bekor qilish", "161-modda"],
    "ishdan bo'shat": ["mehnat shartnomasini bekor qilish", "ishdan bo'shatish nafaqasi", "ogohlantirish muddati"],
    "dekret": ["homiladorlik va tug'ish ta'tillari", "bola parvarishlash ta'tili", "homilador ayollar", "404-modda", "405-modda", "408-modda"],
    "dekret puli": ["homiladorlik va tug'ish nafaqasi", "davlat ijtimoiy sug'urtasi", "404-modda"],
    "otpuska": ["mehnat ta'tili", "yillik asosiy ta'til", "ta'til to'lovlari", "216-modda"],
    "bolnichniy": ["vaqtincha mehnatga qobiliyatsizlik nafaqasi", "mehnatga layoqatsizlik varaqasi", "285-modda"],
    "kompensatsiya": ["pulli kompensatsiya", "ishdan bo'shatish nafaqasi", "ogohlantirish muddati", "165-modda", "173-modda"],
    "ogohlantirish puli": ["ogohlantirish muddatini pulli kompensatsiyaga almashtirish", "165-modda"],
    "sinov muddati": ["dastlabki sinov muddati", "sinov davri", "129-modda", "130-modda"],
    "staj": ["mehnat staji", "ish staji", "umumiy ish staji", "maxsus staj"],
    "zarplata": ["mehnatga haq to'lash", "ish haqi", "tarif stavkasi"],

    # Ijtimoiy ta'minot va nogironlik
    "pensiya": ["yoshga doir pensiya", "davlat pensiyalari", "staj", "imtiyozli pensiya"],
    "pensioner": ["yoshga doir pensiya oluvchilar", "imtiyozlar"],
    "nogiron": ["nogironligi bo'lgan shaxs", "nogironlik guruhi", "tibbiy-ijtimoiy ekspertiza", "reabilitatsiya"],
    "nogironlik puli": ["nogironlik pensiyasi", "nogironlik nafaqasi", "ijtimoiy ta'minot"],
    "aravacha": ["reabilitatsiya texnik vositalari", "kreslo-aravacha", "protez-ortopediya"],
    "bolalar nafaqasi": ["kam ta'minlangan oilalarga bolalar nafaqasi", "ijtimoiy himoya", "yagona reyestr"],

    # Oila va fuqarolik
    "aliment": ["voyaga yetmagan bolalarni moddiy ta'minlash", "aliment undirish", "oila kodeksi 96-modda", "JK 122-modda"],
    "ajrashish": ["nikohni bekor qilish", "nikohdan ajratish", "sud tartibida", "oila kodeksi 38-modda"],
    "zags": ["fuqarolik holati dalolatnomalarini yozish organi", "FHDYO"],
    "meros": ["meros qoldiruvchi", "merosxo'rlar", "qonun bo'yicha meros", "vasiyatnoma", "fuqarolik kodeksi"],
    "propiska": ["doimiy yashash joyi", "vaqtincha turgan joyi bo'yicha ro'yxatga olish"],
    "doverennost": ["ishonchnoma", "vakillik", "notarial tasdiqlash"],

    # Yo'l harakati va jarimalar
    "prava": ["haydovchilik guvohnomasi", "transport vositasini boshqarish huquqidan mahrum qilish", "MJtK 128-modda"],
    "haydovchilik guvohnoma": ["transport vositalarini boshqarish huquqi", "haydovchilik guvohnomasi"],
    "radar": ["tezlikni oshirish", "avtomatlashtirilgan foto va video qayd etish", "MJtK 128-3-modda"],
    "shtraf": ["ma'muriy jarima", "jarima to'lash", "50 foiz chegirma", "332-1-modda"],
    "jarima chegirma": ["jarimani 50 foiz to'lash", "332-1-modda"],
    "tonirovka": ["oynalar tusini o'zgartirish", "ruxsatnoma", "tasdiqlangan standartlar"],
    "mast holda haydash": ["mastlik holatida transport vositasini boshqarish", "MJtK 131-modda"],

    # Soliq va tadbirkorlik
    "samozanyatiy": ["o'zini o'zi band qilgan shaxslar", "daromad solig'idan ozod qilish"],
    "yatt": ["yakka tartibdagi tadbirkor", "davlat ro'yxatidan o'tkazish"],
    "nds": ["qo'shilgan qiymat solig'i", "soliq hisoboti"],
    "ijara": ["mol-mulkni ijaraga berish", "ijara shartnomasi", "soliq stavkalari"],

    # Jinoyat va jazo
    "firibgar": ["firibgarlik", "aldash yoki ishonchni suiiste'mol qilish", "JK 168-modda"],
    "pora": ["pora olish", "pora berish", "pora olish-berishda vositachilik", "JK 210-modda", "JK 211-modda"],
    "o'g'rilik": ["o'g'rilik", "o'zganing mol-mulkini yashirin talon-toroj qilish", "JK 169-modda"],
    "sudlanmaganlik": ["sudlanganlik holati", "sudlanganlikni olib tashlash", "sudlanganlikning tugallanishi"],

    # Russian common terms
    "декрет": ["отпуск по беременности и родам", "пособие по беременности и родам", "статья 404"],
    "больничный": ["пособие по временной нетрудоспособности", "листок нетрудоспособности"],
    "сокращение": ["сокращение численности или штата", "преимущественное право оставления на работе", "статья 167"],
    "алименты": ["взыскание алиментов", "содержание несовершеннолетних детей"],
    "права": ["водительское удостоверение", "лишение права управления"],
    "штраф": ["административный штраф", "скидка 50 процентов"],
}


class LegalSynonymExpander:
    """Expands citizen queries with authoritative legal terminology for BM25 and hybrid search."""

    @classmethod
    def expand_terms(cls, query: str, max_terms: int = 5) -> List[str]:
        """
        Finds matching statutory synonyms for expressions found in the query.
        Returns a list of statutory enhancement terms to append to the search query.
        """
        q_lower = query.lower()
        expanded: List[str] = []
        seen: Set[str] = set()

        for key, synonyms in LEGAL_SYNONYM_DICTIONARY.items():
            # Match whole-word or key substring
            if key in q_lower:
                for syn in synonyms:
                    if syn.lower() not in q_lower and syn not in seen:
                        seen.add(syn)
                        expanded.append(syn)
                        if len(expanded) >= max_terms:
                            return expanded

        return expanded

    @classmethod
    def build_enriched_search_query(cls, query: str) -> str:
        """
        Builds an enhanced search query containing the original text plus statutory legal synonyms.
        """
        expansion = cls.expand_terms(query)
        if not expansion:
            return query
        expansion_text = " ".join(expansion)
        return f"{query} {expansion_text}"
