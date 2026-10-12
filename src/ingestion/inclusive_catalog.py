"""
DEPRECATED - do not use for ingestion.

This hand-written catalog was verified against Lex.uz on 2026-10-11 and found unreliable: most `lex_doc_id`
values do not exist (HTTP 404) or point to another act (111453 is the Criminal Code, not the pension law), and
several act numbers do not match the documents. The verified, regenerable source list is
`data/sources/disability_registry.json` (see `data/sources/REGISTRY.md`), built by
`scripts/build_disability_corpus.py` from the official Lex.uz classifier.
"""
import warnings

warnings.warn(
    "src.ingestion.inclusive_catalog is deprecated and contains unverified document ids; "
    "use scripts/build_disability_corpus.py and data/sources/disability_registry.json instead",
    DeprecationWarning,
    stacklevel=2,
)
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class InclusiveLawSpec:
    law_id: str
    law_title_uz: str
    law_title_ru: str
    law_title_en: str
    law_number: str
    lex_doc_id: Optional[int]
    category: str
    target_disability_types: List[str] = field(default_factory=lambda: ["general"])
    # If only specific articles are relevant from a large code, list them; if empty, ingest all articles
    relevant_articles: Optional[List[str]] = None
    priority: int = 1


INCLUSIVE_LAWS_CATALOG: List[InclusiveLawSpec] = [
    # 1. Core Disability Rights Law
    InclusiveLawSpec(
        law_id="law_disability_2020",
        law_title_uz="O'zbekiston Respublikasining 'Nogironligi bo'lgan shaxslarning huquqlari to'g'risida'gi Qonuni",
        law_title_ru="Закон Республики Узбекистан «О правах лиц с инвалидностью»",
        law_title_en="Law of the Republic of Uzbekistan 'On the Rights of Persons with Disabilities'",
        law_number="O'RQ-641",
        lex_doc_id=5053070,
        category="disability_rights",
        target_disability_types=["group_1", "group_2", "group_3", "childhood_disability", "general", "physical", "visual", "hearing", "intellectual"],
        priority=1,
    ),

    # 2. UN Convention on the Rights of Persons with Disabilities
    InclusiveLawSpec(
        law_id="law_un_crpd_2006",
        law_title_uz="BMTning Nogironlar huquqlari to'g'risidagi Konvensiyasi (O'zbekiston Respublikasi tomonidan ratifikatsiya qilingan)",
        law_title_ru="Конвенция ООН о правах инвалидов (ратифицирована Республикой Узбекистан)",
        law_title_en="UN Convention on the Rights of Persons with Disabilities (ratified by Uzbekistan)",
        law_number="O'RQ-695 / UN CRPD",
        lex_doc_id=5448378,
        category="international_treaty",
        target_disability_types=["general", "physical", "visual", "hearing", "intellectual"],
        priority=1,
    ),

    # 3. Medical-Social Expertise Regulations (TMEK / TIEK)
    InclusiveLawSpec(
        law_id="regulation_tmek_vmq_864",
        law_title_uz="Tibbiy-ijtimoiy ekspertiza xizmati tashkiliy tuzilmasini va faoliyatini tashkil etish chora-tadbirlari to'g'risida (TMEK nizomi)",
        law_title_ru="О мерах по совершенствованию организационной структуры и деятельности медико-социальной экспертной службы",
        law_title_en="On measures to organize medical and social expert service (MSEK Regulations)",
        law_number="VMQ-864",
        lex_doc_id=5796245,
        category="medical_social_expertise",
        target_disability_types=["group_1", "group_2", "group_3", "childhood_disability", "general"],
        priority=1,
    ),

    # 4. Prosthetics and Rehabilitation Equipment Provision
    InclusiveLawSpec(
        law_id="regulation_prosthetics_vmq_257",
        law_title_uz="Muhtoj shaxslarni protez-ortopediya buyumlari va reabilitatsiya qilishning texnik vositalari bilan ta'minlash tartibi to'g'risidagi nizom",
        law_title_ru="Положение о порядке обеспечения нуждающихся лиц протезно-ортопедическими изделиями и техническими средствами реабилитации",
        law_title_en="Regulations on the provision of persons in need with prosthetic-orthopedic products and technical means of rehabilitation",
        law_number="VMQ-257",
        lex_doc_id=5487714,
        category="rehabilitation_prosthetics",
        target_disability_types=["physical", "visual", "hearing", "group_1", "group_2", "general"],
        priority=1,
    ),

    # 5. Sanatorium Treatment and Vouchers
    InclusiveLawSpec(
        law_id="regulation_sanatorium_vmq_631",
        law_title_uz="Aholining ijtimoiy himoyaga muhtoj qatlamlarini sanatoriy-kurortlarda davolanish uchun yo'llanmalar bilan ta'minlash tartibi",
        law_title_ru="Положение о порядке предоставления путевок на санаторно-курортное лечение социально уязвимым слоям населения",
        law_title_en="Regulations on the provision of sanatorium-resort vouchers to socially vulnerable categories of the population",
        law_number="VMQ-631 / VMQ-422",
        lex_doc_id=6149174,
        category="sanatorium_health",
        target_disability_types=["group_1", "group_2", "general", "childhood_disability"],
        priority=2,
    ),

    # 6. Labor Code (O'RQ-798) - Exclusively Articles Relevant to Persons with Disabilities
    InclusiveLawSpec(
        law_id="code_labor_disability",
        law_title_uz="O'zbekiston Respublikasining Mehnat kodeksi (Nogironligi bo'lgan shaxslar mehnati kafolatlari)",
        law_title_ru="Трудовой кодекс Республики Узбекистан (Гарантии труда лиц с инвалидностью)",
        law_title_en="Labor Code of the Republic of Uzbekistan (Disability Labor Rights)",
        law_number="O'RQ-798",
        lex_doc_id=6257288,
        category="labor_rights",
        target_disability_types=["group_1", "group_2", "group_3", "general"],
        relevant_articles=["423", "424", "425", "426", "427", "428", "429", "430", "431"],
        priority=1,
    ),

    # 7. Tax Code - Exclusively Disability Deductions and Exemptions
    InclusiveLawSpec(
        law_id="code_tax_disability",
        law_title_uz="O'zbekiston Respublikasining Soliq kodeksi (Nogironligi bo'lgan shaxslar uchun soliq imtiyozlari)",
        law_title_ru="Налоговый кодекс Республики Узбекистан (Налоговые льготы для лиц с инвалидностью)",
        law_title_en="Tax Code of the Republic of Uzbekistan (Disability Tax Exemptions)",
        law_number="O'RQ-599",
        lex_doc_id=4674902,
        category="tax_benefits",
        target_disability_types=["group_1", "group_2", "childhood_disability", "general"],
        relevant_articles=["378", "380", "421", "436"],
        priority=1,
    ),

    # 8. State Pension Provision Law - Disability Pensions
    InclusiveLawSpec(
        law_id="law_pension_disability",
        law_title_uz="O'zbekiston Respublikasining 'Fuqarolarning davlat pensiya ta'minoti to'g'risida'gi Qonuni (Nogironlik pensiyalari)",
        law_title_ru="Закон Республики Узбекистан «О государственном пенсионном обеспечении граждан» (Пенсии по инвалидности)",
        law_title_en="Law of the Republic of Uzbekistan 'On State Pension Provision of Citizens' (Disability Pensions)",
        law_number="938-XII",
        lex_doc_id=111453,
        category="pensions_and_benefits",
        target_disability_types=["group_1", "group_2", "group_3", "childhood_disability", "general"],
        relevant_articles=["15", "16", "17", "18", "19", "20", "27", "28", "29"],
        priority=1,
    ),

    # 9. Law on Education - Inclusive Education & Quotas
    InclusiveLawSpec(
        law_id="law_education_inclusive",
        law_title_uz="O'zbekiston Respublikasining 'Ta'lim to'g'risida'gi Qonuni (Inklyuziv ta'lim kafolatlari)",
        law_title_ru="Закон Республики Узбекистан «Об образовании» (Инклюзивное образование)",
        law_title_en="Law of the Republic of Uzbekistan 'On Education' (Inclusive Education)",
        law_number="O'RQ-637",
        lex_doc_id=5013007,
        category="inclusive_education",
        target_disability_types=["general", "childhood_disability", "visual", "hearing", "intellectual"],
        relevant_articles=["20", "38", "56"],
        priority=2,
    ),

    # 10. Urban Planning & Accessibility (Barrier-Free Infrastructure)
    InclusiveLawSpec(
        law_id="code_urban_accessibility",
        law_title_uz="O'zbekiston Respublikasining Shaharsozlik kodeksi (To'siqsiz muhit va qulay shaharsozlik infratuzilmasi)",
        law_title_ru="Градостроительный кодекс Республики Узбекистан (Безбарьерная среда и доступная инфраструктура)",
        law_title_en="Urban Planning Code of Uzbekistan (Accessible & Barrier-Free Infrastructure)",
        law_number="O'RQ-676",
        lex_doc_id=5332066,
        category="accessibility_infrastructure",
        target_disability_types=["physical", "visual", "general"],
        relevant_articles=["8", "26", "65"],
        priority=2,
    ),

    # 11. National Agency for Social Protection (IHMA) Decree
    InclusiveLawSpec(
        law_id="decree_ihma_social_protection",
        law_title_uz="O'zbekiston Respublikasi Prezidentining Farmoni: Aholiga ijtimoiy xizmatlar va yordam ko'rsatish tizimini tubdan takomillashtirish chora-tadbirlari to'g'risida",
        law_title_ru="Указ Президента Республики Узбекистан: О мерах по кардинальному совершенствованию системы оказания социальных услуг и помощи населению",
        law_title_en="Decree of the President of Uzbekistan: On Radical Improvement of Social Services and Assistance System",
        law_number="PF-82",
        lex_doc_id=6479708,
        category="social_protection_governance",
        target_disability_types=["general", "group_1", "group_2", "childhood_disability"],
        priority=2,
    ),
]
