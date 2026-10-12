"""
O'zbekiston Respublikasi Qonunchilik Hujjatlari va Davlat Organlari Yuridik Iyerarxiyasi.
Asos: O'zbekiston Respublikasining 2021-yil 20-apreldagi "Normativ-huquqiy hujjatlar to'g'risida"gi
O'RQ-682-son Qonuni (6, 7, 8, 9, 10, 11, 12, 18-moddalar) hamda ma'muriy islohotlar (PF-269, PF-14).
"""

import re
from typing import Dict, Optional, Tuple
from pydantic import BaseModel


class LegalHierarchyScore(BaseModel):
    tier_level: int          # 1 (oliy) dan 8 (quyi) gacha
    tier_name: str           # Bosqich nomi
    hierarchy_weight: float  # 0.50 dan 1.00 gacha
    organ_type: str          # Organ toifasi
    is_presidential_agency: bool = False


class StateOrganHierarchy:
    """
    O'zbekiston Respublikasidagi barcha qonunchilik hujjatlari va davlat organlarining
    to'liq yuridik iyerarxiya matritsasi.
    """

    # 1. Prezident huzuridagi / bevosita bo'ysunuvchi Milliy Agentliklar va mustaqil organlar
    # (Maqomi va vakolatlari vazirlik darajasidan yuqori yoki teng, qarorlari barcha vazirliklar uchun umummajburiy)
    PRESIDENTIAL_AGENCIES = [
        "ijtimoiy himoya milliy agentligi",
        "ijtimoiy himoya",
        "национальное агентство социальной защиты",
        "korrupsiyaga qarshi kurashish agentligi",
        "agentligi korrupsiyaga qarshi",
        "агентство по противодействию коррупции",
        "davlat xizmatini rivojlantirish agentligi",
        "argos",
        "агентство развития государственной службы",
        "strategik islohotlar agentligi",
        "агентство стратегических реформ",
        "hisob palatasi",
        "счетная палата",
        "markaziy bank",
        "центральный банк",
        "bosh prokuratura",
        "генеральная прокуратура",
        "davlat xavfsizlik xizmati",
        "dxx",
        "сгб",
        "konstitutsiyaviy sud",
        "oliy sud",
    ]

    # 2. Vazirliklar va ularga tenglashtirilgan davlat qo'mitalari (Hukumat tarkibidagi oliy ijro organlari)
    MINISTRIES_AND_STATE_COMMITTEES = [
        "adliya vazirligi", "юстиции",
        "iqtisodiyot va moliya vazirligi", "экономики и финансов",
        "kambag'allikni qisqartirish va bandlik vazirligi", "занятости и сокращения бедности",
        "ichki ishlar vazirligi", "мвд", "внутренних дел",
        "sog'liqni saqlash vazirligi", "минздрав", "здравоохранения",
        "favqulodda vaziyatlar vazirligi", "мчс", "чрезвычайных ситуаций",
        "tashqi ishlar vazirligi", "мид", "иностранных дел",
        "mudofaa vazirligi", "минобороны", "обороны",
        "maktabgacha va maktab ta'limi vazirligi", "дошкольного и школьного образования",
        "oliy ta'lim, fan va innovatsiyalar vazirligi", "высшего образования",
        "energetika vazirligi", "энергетики",
        "tog'-kon sanoati va geologiya vazirligi", "горнодобывающей промышленности и геологии",
        "suv xo'jaligi vazirligi", "водного хозяйства",
        "qishloq xo'jaligi vazirligi", "сельского хозяйства",
        "qurilish va uy-joy kommunal xo'jaligi vazirligi", "строительства и жкх",
        "transport vazirligi", "транспорта",
        "ekologiya, atrof-muhitni muhofaza qilish va iqlim o'zgarishi vazirligi", "экологии",
        "raqamli texnologiyalar vazirligi", "цифровых технологий",
        "madaniyat vazirligi", "культуры",
        "yoshlar siyosati va sport vazirligi", "спорта",
        "soliq qo'mitasi", "налоговый комитет",
        "bojxona qo'mitasi", "таможенный комитет",
        "raqobatni rivojlantirish va iste'molchilar huquqlarini himoya qilish qo'mitasi", "комитет по конкуренции",
        "statistika agentligi", "агентство статистики",
        "oila va xotin-qizlar qo'mitasi", "комитет семьи и женщин",
    ]

    # 3. Hujjat turi bo'yicha aniqlash shablonlari
    CONSTITUTION_PATTERNS = [
        r"\bkonstitutsiy\w*\b", r"\bконституци\w*\b"
    ]
    CODE_PATTERNS = [
        r"\bkodeks\b", r"\bкодекс\b", r"\bkodeksi\b", r"\bкодекса\b"
    ]
    LAW_PATTERNS = [
        r"\bo['`’‘ʻʼ]?rq\s*[-–—]?\s*\d+", r"\bзру\s*[-–—]?\s*\d+",
        r"\bqonun\b", r"\bзакон\b", r"\bqonuni\b", r"\bзакона\b"
    ]
    PARLIAMENT_PATTERNS = [
        r"\boliy majlis\b", r"\bсенат\b", r"\bqonunchilik palatasi\b", r"\bзаконодательн\w* палат\w*\b"
    ]
    PRESIDENTIAL_PATTERNS = [
        r"\bpf\s*[-–—]?\s*\d+", r"\bуп\s*[-–—]?\s*\d+",
        r"\bpq\s*[-–—]?\s*\d+", r"\bпп\s*[-–—]?\s*\d+",
        r"\bprezident farmoni\b", r"\bуказ президента\b",
        r"\bprezident qarori\b", r"\bпостановление президента\b",
        r"\bprezident farmoyishi\b", r"\bраспоряжение президента\b"
    ]
    CABINET_PATTERNS = [
        r"\bvmq\s*[-–—]?\s*\d+", r"\bпкм\s*[-–—]?\s*\d+",
        r"\bvazirlar mahkamasi\b", r"\bкабинет министров\b",
        r"\bhukumat qarori\b", r"\bпостановление кабинета министров\b"
    ]
    LOCAL_PATTERNS = [
        r"\bhokim\b", r"\bhokimi\b", r"\bhokimligi\b", r"\bхоким\b", r"\bхокимият\b",
        r"\bxalq deputatlari\b", r"\bкенгаш\b", r"\bкенес\b"
    ]

    @classmethod
    def evaluate_hierarchy(
        cls,
        law_title: str,
        law_number: str = "",
        category: str = "",
        promulgation_date: Optional[str] = None
    ) -> LegalHierarchyScore:
        """
        Normativ-huquqiy hujjatning to'liq yuridik kuch darajasini (1-8) hisoblab beradi.
        """
        combined = f"{law_number} {law_title} {category}".lower()

        # 1-daraja: O'zbekiston Respublikasi Konstitutsiyasi (Oliy yuridik kuch)
        if any(re.search(pat, combined) for pat in cls.CONSTITUTION_PATTERNS):
            return LegalHierarchyScore(
                tier_level=1,
                tier_name="Konstitutsiya (Oliy yuridik kuch)",
                hierarchy_weight=1.00,
                organ_type="Davlat va xalq irodasi",
                is_presidential_agency=False
            )

        # 2-daraja: Kodekslar, Konstitutsiyaviy qonunlar va O'zbekiston Respublikasi Qonunlari
        if any(re.search(pat, combined) for pat in cls.CODE_PATTERNS):
            return LegalHierarchyScore(
                tier_level=2,
                tier_name="Kodeks (Tarmoqning asosiy qonuni)",
                hierarchy_weight=0.96,
                organ_type="Oliy Majlis",
                is_presidential_agency=False
            )

        if any(re.search(pat, combined) for pat in cls.LAW_PATTERNS):
            return LegalHierarchyScore(
                tier_level=2,
                tier_name="Qonun (O'RQ / Qonunchilik hujjati)",
                hierarchy_weight=0.94,
                organ_type="Oliy Majlis",
                is_presidential_agency=False
            )

        # 3-daraja: O'zbekiston Respublikasi Prezidentining Farmon va Qarorlari
        if any(re.search(pat, combined) for pat in cls.PRESIDENTIAL_PATTERNS) or "prezident" in combined:
            is_decree = bool(re.search(r"\b(pf|уп|farmon|указ)\b", combined))
            weight = 0.90 if is_decree else 0.88
            name = "Prezident Farmoni (PF)" if is_decree else "Prezident Qarori (PQ)"
            return LegalHierarchyScore(
                tier_level=3,
                tier_name=name,
                hierarchy_weight=weight,
                organ_type="O'zbekiston Respublikasi Prezidenti",
                is_presidential_agency=False
            )

        # 4-daraja: Prezident huzuridagi / bevosita bo'ysunuvchi Milliy Agentliklar
        for agency in cls.PRESIDENTIAL_AGENCIES:
            if agency in combined:
                return LegalHierarchyScore(
                    tier_level=4,
                    tier_name=f"Prezident huzuridagi Milliy Agentlik / Organ ({agency.title()})",
                    hierarchy_weight=0.84,
                    organ_type="Prezident huzuridagi davlat organi",
                    is_presidential_agency=True
                )

        # 5-daraja: O'zbekiston Respublikasi Vazirlar Mahkamasi (VMQ / Hukumat qarorlari)
        if any(re.search(pat, combined) for pat in cls.CABINET_PATTERNS) or "vazirlar mahkamasi" in combined:
            return LegalHierarchyScore(
                tier_level=5,
                tier_name="Vazirlar Mahkamasi Qarori (VMQ)",
                hierarchy_weight=0.80,
                organ_type="O'zbekiston Respublikasi Hukumati",
                is_presidential_agency=False
            )

        # 6-daraja: Vazirliklar va Davlat qo'mitalari buyruqlari / qarorlari
        for ministry in cls.MINISTRIES_AND_STATE_COMMITTEES:
            if ministry in combined:
                return LegalHierarchyScore(
                    tier_level=6,
                    tier_name=f"Vazirlik / Davlat qo'mitasi hujjati ({ministry.title()})",
                    hierarchy_weight=0.74,
                    organ_type="Vazirlik yoki Davlat qo'mitasi",
                    is_presidential_agency=False
                )

        # 7-daraja: Mahalliy davlat hokimiyati organlari (Hokimliklar va kengashlar)
        if any(re.search(pat, combined) for pat in cls.LOCAL_PATTERNS):
            return LegalHierarchyScore(
                tier_level=8,
                tier_name="Mahalliy davlat hokimiyati hujjati (Hokim qarori / Kengash)",
                hierarchy_weight=0.55,
                organ_type="Mahalliy davlat hokimiyati",
                is_presidential_agency=False
            )

        # 7-daraja: Boshqa idoraviy normativ hujjatlar (inspeksiya, qo'mita, markaz buyruqlari)
        return LegalHierarchyScore(
            tier_level=7,
            tier_name="Idoraviy normativ-huquqiy hujjat",
            hierarchy_weight=0.68,
            organ_type="Idoraviy organ",
            is_presidential_agency=False
        )

    @classmethod
    def calculate_hierarchy_boost(
        cls,
        law_title: str,
        law_number: str = "",
        category: str = "",
        promulgation_date: Optional[str] = None
    ) -> float:
        """
        Qidiruv va qayta saralashda (RRF/Rerank) yuridik kuch bo'yicha beriladigan mutanosib koeffitsiyent.
        Konstitutsiya va Kodekslar eng yuqori bonus oladi, past darajali idoraviy hujjatlar esa
        faqat maxsus mavzulariga mos kelgandagina tanlanadi.
        """
        score = cls.evaluate_hierarchy(law_title, law_number, category, promulgation_date)
        boost = score.hierarchy_weight

        # Agar qabul qilingan sana ma'lum bo'lsa, O'RQ-682 ning 18-moddasi 2-qismiga ko'ra
        # yangiroq hujjatga kichik qo'shimcha afzallik (0.00-0.03) beriladi
        if promulgation_date:
            try:
                # 2024-yil 0.03, 2020-yil 0.015 va h.k.
                year_match = re.search(r"\b(19\d{2}|20\d{2})\b", promulgation_date)
                if year_match:
                    year = int(year_match.group(1))
                    if year >= 2023:
                        boost += 0.03
                    elif year >= 2018:
                        boost += 0.015
            except Exception:
                pass

        return round(boost, 4)
