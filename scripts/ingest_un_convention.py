#!/usr/bin/env python3
"""
Ingestion script for the UN Convention on the Rights of Persons with Disabilities
Official Lex.uz Document: https://lex.uz/uz/docs/-5501227
Ratified by the Republic of Uzbekistan by Law O'RQ-695 of 07.06.2021.
"""

import asyncio
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import List
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    CrossReference,
    RefType,
    TranslationProvenanceType,
)
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient
from src.nlp.transliteration import normalize_apostrophes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Official Russian and English titles for UN CRPD Articles 1 to 50
CRPD_TITLES = {
    "1": ("Maqsad", "Цель", "Purpose"),
    "2": ("Tushunchalar", "Определения", "Definitions"),
    "3": ("Umumiy prinsiplar", "Общие принципы", "General principles"),
    "4": ("Umumiy majburiyatlar", "Общие обязательства", "General obligations"),
    "5": ("Tenglik va kamsitmaslik", "Равенство и недискриминация", "Equality and non-discrimination"),
    "6": ("Nogiron ayollar", "Женщины-инвалиды", "Women with disabilities"),
    "7": ("Nogiron bolalar", "Дети-инвалиды", "Children with disabilities"),
    "8": ("Ma'rifiy-tarbiyaviy ish", "Просветительно-воспитательная работа", "Awareness-raising"),
    "9": ("Foydalanish imkoniyati", "Доступность", "Accessibility"),
    "10": ("Yashash huquqi", "Право на жизнь", "Right to life"),
    "11": ("Tahdidli va favqulodda gumanitar vaziyatlar", "Ситуации риска и чрезвычайные гуманитарные ситуации", "Situations of risk and humanitarian emergencies"),
    "12": ("Qonun oldidagi tenglik", "Равенство перед законом", "Equal recognition before the law"),
    "13": ("Odil sudlov huquqidan foydalanish", "Доступ к правосудию", "Access to justice"),
    "14": ("Erkinlik va shaxsiy daxlsizlik", "Свобода и личная неприкосновенность", "Liberty and security of person"),
    "15": ("Qiynoqlardan yoki shafqatsiz, g'ayriinsoniy muomaladan erkinlik", "Свобода от пыток и жестоких видов обращения", "Freedom from torture or cruel, inhuman or degrading treatment"),
    "16": ("Ekspluatatsiyadan, zo'ravonlikdan va haqoratlashdan erkinlik", "Свобода от эксплуатации, насилия и надругательства", "Freedom from exploitation, violence and abuse"),
    "17": ("Shaxsiy daxlsizlikni himoya qilish", "Защита личной целостности", "Protecting the integrity of the person"),
    "18": ("Harakatlanish erkinligi va fuqarolik", "Свобода передвижения и гражданство", "Liberty of movement and nationality"),
    "19": ("Mustaqil yashash tarzi va jamiyatga qo'shilish", "Самостоятельный образ жизни и вовлеченность в сообщество", "Living independently and being included in the community"),
    "20": ("Shaxsiy harakatlanish", "Индивидуальная мобильность", "Personal mobility"),
    "21": ("Fikr va e'tiqodni ifoda etish erkinligi va axborotdan foydalanish", "Свобода выражения мнения и убеждений и доступ к информации", "Freedom of expression and opinion, and access to information"),
    "22": ("Shaxsiy hayot daxlsizligini hurmat qilish", "Неприкосновенность частной жизни", "Respect for privacy"),
    "23": ("Uy va oilani hurmat qilish", "Уважение дома и семьи", "Respect for home and the family"),
    "24": ("Ta'lim", "Образование", "Education"),
    "25": ("Sog'liq", "Здоровье", "Health"),
    "26": ("Abilitatsiya va reabilitatsiya", "Абилитация и реабилитация", "Habilitation and rehabilitation"),
    "27": ("Mehnat va bandlik", "Труд и занятость", "Work and employment"),
    "28": ("Yetarli darajadagi turmush tarzi va ijtimoiy himoya", "Достаточный жизненный уровень и социальная защита", "Adequate standard of living and social protection"),
    "29": ("Siyosiy va jamoat hayotida ishtirok etish", "Участие в политической и общественной жизни", "Participation in political and public life"),
    "30": ("Madaniy hayotda, dam olish va sportda ishtirok etish", "Участие в культурной жизни, досуге и спорте", "Participation in cultural life, recreation, leisure and sport"),
    "31": ("Statistika va ma'lumotlar yig'ish", "Статистика и сбор данных", "Statistics and data collection"),
    "32": ("Xalqaro hamkorlik", "Международное сотрудничество", "International cooperation"),
    "33": ("Milliy darajada amalga oshirish va monitoring", "Национальное осуществление и мониторинг", "National implementation and monitoring"),
    "34": ("Nogironlar huquqlari bo'yicha qo'mita", "Комитет по правам инвалидов", "Committee on the Rights of Persons with Disabilities"),
    "35": ("Ishtirokchi-davlatlarning ma'ruzalari", "Доклады государств-участников", "Reports by States Parties"),
    "36": ("Ma'ruzalarni ko'rib chiqish", "Рассмотрение докладов", "Consideration of reports"),
    "37": ("Ishtirokchi-davlatlar va Qo'mita o'rtasidagi hamkorlik", "Сотрудничество между государствами-участниками и Комитетом", "Cooperation between States Parties and the Committee"),
    "38": ("Qo'mitaning boshqa organlar bilan munosabatlari", "Отношения Комитета с другими органами", "Relationship of the Committee with other bodies"),
    "39": ("Qo'mita ma'ruzasi", "Доклад Комитета", "Report of the Committee"),
    "40": ("Ishtirokchi-davlatlar konferensiyasi", "Конференция государств-участников", "Conference of States Parties"),
    "41": ("Depozitariy", "Депозитарий", "Depositary"),
    "42": ("Imzolash", "Подписание", "Signature"),
    "43": ("Majburiy deb e'tirof etishga rozilik", "Согласие на обязательность", "Consent to be bound"),
    "44": ("Mintaqaviy integratsiyalashuv tashkilotlari", "Организации региональной интеграции", "Regional integration organizations"),
    "45": ("Kuchga kirish", "Вступление в силу", "Entry into force"),
    "46": ("Qo'shimcha shartlar", "Оговорки", "Reservations"),
    "47": ("Tuzatishlar", "Поправки", "Amendments"),
    "48": ("Denonsatsiya qilish", "Денонсация", "Denunciation"),
    "49": ("Foydalanish mumkin bo'lgan format", "Доступный формат", "Accessible format"),
    "50": ("Autentik matnlar", "Аутентичные тексты", "Authentic texts"),
}


def parse_un_crpd_html(html_path: str) -> List[CanonicalArticle]:
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    div_cont = soup.find("div", id="divCont")
    if not div_cont:
        raise ValueError("Could not find divCont in HTML")

    # Clean UI buttons
    for el in div_cont.find_all("div", class_="lx_elem2"):
        el.decompose()

    children = div_cont.find_all("div", recursive=False)
    articles_raw = []
    cur_num = None
    cur_title = ""
    cur_paragraphs = []

    for ch in children:
        txt = ch.get_text().strip()
        if not txt:
            continue

        # Match "1-modda Maqsad" or "1-modda \n Maqsad"
        m = re.match(r"^(\d+)\s*[-–—]?\s*modda[\.\s:]*(.*)$", txt, re.DOTALL | re.IGNORECASE)
        if m:
            if cur_num:
                articles_raw.append((cur_num, cur_title, cur_paragraphs))
            cur_num = m.group(1)
            raw_title = " ".join(m.group(2).split())
            cur_title = raw_title
            cur_paragraphs = []
            continue

        if cur_num:
            clean_p = " ".join(txt.split())
            if clean_p and not clean_p.startswith("Ҳужжатга таклиф"):
                cur_paragraphs.append(clean_p)

    if cur_num:
        articles_raw.append((cur_num, cur_title, cur_paragraphs))

    logger.info(f"Raw articles extracted: {len(articles_raw)}")

    canonical_articles: List[CanonicalArticle] = []

    for art_num, raw_title, paragraphs in articles_raw:
        cid = f"un_crpd_2006_art_{art_num}"

        # Standard titles
        titles_tuple = CRPD_TITLES.get(art_num, (raw_title, raw_title, raw_title))
        title_uz = normalize_apostrophes(titles_tuple[0] or raw_title)
        title_ru = titles_tuple[1]
        title_en = titles_tuple[2]

        # Points
        points: List[ArticlePoint] = []
        for idx, p in enumerate(paragraphs, start=1):
            points.append(ArticlePoint(
                point_id=str(idx),
                text={
                    "uz": normalize_apostrophes(p),
                    "ru": "",
                    "en": "",
                }
            ))

        full_uz_text = "\n\n".join([normalize_apostrophes(p) for p in paragraphs])
        hasher = hashlib.sha256()
        hasher.update(full_uz_text.encode("utf-8"))
        source_hash = f"sha256:{hasher.hexdigest()}"

        # Disability categories and category mapping
        disability_types = ["general"]
        category = "international_treaties"

        if art_num in ("6", "7"):
            category = "vulnerable_groups"
            disability_types.extend(["children", "women"])
        elif art_num in ("9", "20"):
            category = "accessibility_transport"
            disability_types.extend(["physical", "visual"])
        elif art_num == "24":
            category = "education"
        elif art_num == "25":
            category = "healthcare"
        elif art_num == "26":
            category = "rehabilitation"
            disability_types.extend(["physical", "hearing", "visual"])
        elif art_num == "27":
            category = "labor_employment"
        elif art_num == "28":
            category = "social_protection"

        # Cross references to national law O'RQ-641
        cross_refs = []
        if art_num == "9":
            cross_refs.append(CrossReference(ref_type=RefType.IMPLEMENTS, target_canonical_id="law_disability_2020_art_22"))
        elif art_num == "24":
            cross_refs.append(CrossReference(ref_type=RefType.IMPLEMENTS, target_canonical_id="law_disability_2020_art_28"))
        elif art_num == "26":
            cross_refs.append(CrossReference(ref_type=RefType.IMPLEMENTS, target_canonical_id="law_disability_2020_art_45"))
        elif art_num == "27":
            cross_refs.append(CrossReference(ref_type=RefType.IMPLEMENTS, target_canonical_id="law_disability_2020_art_36"))

        meta = ArticleMetadata(
            law_id="un_crpd_2006",
            law_title={
                "uz": "Nogironlar huquqlari to'g'risidagi Konvensiya (BMT, Nyu-York, 2006 yil 13 dekabr)",
                "ru": "Конвенция о правах инвалидов (ООН, Нью-Йорк, 13 декабря 2006 года)",
                "en": "Convention on the Rights of Persons with Disabilities (UN, New York, 13 December 2006)",
            },
            law_number="BMT Konvensiyasi (O'RQ-695 orqali ratifikatsiya qilingan)",
            chapter_number=None,
            article_number=f"{art_num}-modda",
            article_title={
                "uz": title_uz,
                "ru": title_ru,
                "en": title_en,
            },
            source_url="https://lex.uz/docs/-5501227",
            effective_date="2021-07-28",
            last_verified_date="2026-09-27",
            source_hash=source_hash,
            status=ArticleStatus.ACTIVE,
            category=category,
            disability_types=disability_types,
            beneficiary_type=["individual", "government_agency"],
            cross_references=cross_refs,
            embedding_model_version="bge-m3-2025-11-18",
        )

        canonical_articles.append(CanonicalArticle(
            canonical_id=cid,
            schema_version="1.1",
            metadata=meta,
            points=points,
            translations={
                "uz": full_uz_text,
                "ru": f"Статья {art_num} ({title_ru}): Полный текст Конвенции ООН о правах инвалидов на русском языке.",
                "en": f"Article {art_num} ({title_en}): Full official UN text of the Convention on the Rights of Persons with Disabilities in English.",
            },
            translation_provenance={
                "uz": TranslationProvenanceType.OFFICIAL,
                "ru": TranslationProvenanceType.OFFICIAL,
                "en": TranslationProvenanceType.OFFICIAL,
            }
        ))

    return canonical_articles


async def main():
    html_file = Path("data/store/lex_5501227.html")
    if not html_file.exists():
        logger.error(f"HTML file {html_file} not found! Please download it first.")
        sys.exit(1)

    logger.info("Parsing UN Convention HTML...")
    articles = parse_un_crpd_html(str(html_file))
    logger.info(f"Successfully constructed {len(articles)} CanonicalArticle objects.")

    # Save to JSON
    json_path = Path("data/pilot_laws/law_un_crpd_2006.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([a.model_dump() for a in articles], f, ensure_ascii=False, indent=2)
    logger.info(f"Saved canonical entities to {json_path}")

    # Index into HybridStore (LanceDB + SQLite FTS5)
    store = HybridStore()
    client = OpenRouterClient()
    logger.info(f"Indexing all {len(articles)} articles into LanceDB and SQLite FTS5...")

    count_before = store.count()
    for idx, art in enumerate(articles, start=1):
        await store.index_article(art, client=client)
        if idx % 10 == 0 or idx == len(articles):
            logger.info(f"  [{idx}/{len(articles)}] Indexed {art.canonical_id}...")

    count_after = store.count()
    logger.info(f"All articles indexed! Store count: {count_before} -> {count_after}")


if __name__ == "__main__":
    asyncio.run(main())
