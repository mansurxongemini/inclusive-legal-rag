#!/usr/bin/env python3
"""
Generates the comprehensive legal collection plan for Inclusive Legal RAG:
- data/sources/collection_plan.json
- data/sources/COLLECTION_PLAN.md
- data/sources/add_commands.sh
"""
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCES = ROOT / "data" / "sources"

from src.ingestion.lex_client import LexClient
from src.ingestion.lex_structured import LexDocumentParser
from src.nlp.transliteration import normalize_apostrophes

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("collection_plan")

_AMENDING_TITLE = re.compile(
    r"o['ʻʼ‘’`]?zgartish|o['ʻʼ‘’`]?zgartirish|qo['ʻʼ‘’`]?shimcha(lar)? kiritish|o['ʻʼ‘’`]?z kuchini yo['ʻʼ‘’`]?qotgan deb topish",
    re.IGNORECASE,
)

def classify_group(doc_type: str, title: str, lex_id: str) -> str:
    t = normalize_apostrophes(title or "").lower()
    dt = (doc_type or "").strip()
    if dt == "Kodeks" or "kodeks" in t:
        return "A"
    if dt == "Konvensiya" or "konvensiya" in t or "pakt" in t or "shartnoma" in t or "protokol" in t:
        return "D"
    if _AMENDING_TITLE.search(t) and ("ayrim" in t or "o'zgartirish va qo'shimchalar" in t):
        return "E"
    if dt in ("Qonun", "O'RQ"):
        return "B"
    return "C"

def main():
    reg_data = json.loads((SOURCES / "disability_registry.json").read_text(encoding="utf-8"))
    existing_reg = reg_data.get("documents", [])
    reg_by_id = {d["lex_id"]: d for d in existing_reg}

    parser = LexDocumentParser()
    lex = LexClient(cache_dir=str(ROOT / "data" / "raw_lex"), min_delay=0.5)

    plan_entries: Dict[str, dict] = {}

    def add_or_update_entry(
        lex_id: str,
        group: str,
        decision: str,
        include: str,
        reason: str,
        number_hint: str = "",
        title_hint: str = "",
        doc_type_hint: str = "",
        adopted_hint: str = "",
        units_hint: int = 0,
        status_hint: str = "active",
        verify_lex: bool = True
    ):
        if not lex_id:
            return

        url = f"https://lex.uz/uz/docs/{lex_id}" if not lex_id.startswith("crpd_") else "https://lex.uz"
        title = title_hint
        number = number_hint
        doc_type = doc_type_hint
        adopted = adopted_hint
        status = status_hint
        units = units_hint

        if verify_lex and not lex_id.startswith("crpd_"):
            html = lex.fetch_document(lex_id)
            if html:
                parsed = parser.parse(html, lex_id)
                title = parsed.title or title_hint
                number = parsed.number or number_hint
                doc_type = parsed.doc_type or doc_type_hint
                adopted = parsed.adopted_date or adopted_hint
                status = parsed.status or status_hint
                units = len(parsed.units)
                if status == "repealed" and decision not in ("SKIP_REPEALED", "SKIP_AMENDING_ONLY"):
                    decision = "SKIP_REPEALED"
                    reason = f"Hujjat kuchini yo'qotgan ({parsed.repealed_date or 'Lex.uz'})."
                elif units == 0 and decision == "ADD":
                    decision = "PARSE_PROBLEM"
                    reason = "Lex.uz'da matn tanasi (HTML/lx_elem) e'lon qilinmagan (units=0)."
            else:
                if decision not in ("NOT_FOUND", "PARSE_PROBLEM"):
                    decision = "PARSE_PROBLEM"
                    reason = "Lex.uz'dan HTML yuklab olinmadi yoki bo'sh."

        plan_entries[lex_id] = {
            "lex_id": lex_id,
            "url": url,
            "number": number,
            "title": title,
            "doc_type": doc_type,
            "adopted": adopted,
            "status": status,
            "units": units,
            "group": group,
            "decision": decision,
            "include": include,
            "reason": reason,
            "verified_at": date.today().isoformat()
        }

    # 1. Group A: Codes
    codes_config = [
        ("-4674902", "O'RQ-599", "Soliq kodeksi", "ADD", "all", "Reestrda faqat disability_articles (16 modda) bo'lgan, kodeksni to'liq (all) rejimga kengaytirish."),
        ("-180552", "", "Fuqarolik kodeksi (ikkinchi qism)", "ADD", "all", "Reestrda faqat disability_articles (50 modda) bo'lgan, kodeksni to'liq (all) rejimga kengaytirish."),
        ("-97664", "", "Maʼmuriy javobgarlik toʻgʻrisidagi kodeks", "ADD", "all", "Reestrda faqat disability_articles bo'lgan, kodeksni to'liq (all) rejimga kengaytirish."),
        ("-111453", "", "Jinoyat kodeksi", "ADD", "all", "Reestrda faqat disability_articles bo'lgan, kodeksni to'liq (all) rejimga kengaytirish."),
        ("-111460", "", "Jinoyat-protsessual kodeksi", "ADD", "all", "Reestrda faqat disability_articles bo'lgan, kodeksni to'liq (all) rejimga kengaytirish."),
        ("-163629", "", "Jinoyat-ijroiya kodeksi", "ADD", "all", "Reestrda faqat disability_articles bo'lgan, kodeksni to'liq (all) rejimga kengaytirish."),
        ("-2876354", "O'RQ-400", "Bojxona kodeksi", "ADD", "all", "Bazada mavjud emas, bojxona imtiyozlari va qoidalarini to'liq qamrab olish uchun qo'shiladi."),
        ("-2304138", "O'RQ-360", "Budjet kodeksi", "ADD", "all", "Bazada mavjud emas, ijtimoiy to'lovlar va davlat xarajatlarini to'liq qamrab olish uchun qo'shiladi."),
        ("-5307951", "O'RQ-676", "Shaharsozlik kodeksi", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 85 modda to'liq kiritilgan."),
        ("-4386848", "O'RQ-544", "Saylov kodeksi", "ADD", "all", "Reestrda faqat disability_articles bo'lgan, barcha normalarni qamrab olish uchun all rejimiga o'tkazish."),
        ("-6257288", "O'RQ-798", "Mehnat kodeksi", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 593 ta norma to'liq indekslangan."),
        ("-111189", "", "Fuqarolik kodeksi (birinchi qism)", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 386 modda to'liq kiritilgan."),
        ("-104720", "", "Oila kodeksi", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 220 modda to'liq kiritilgan."),
        ("-106136", "", "Uy-joy kodeksi", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 141 modda to'liq kiritilgan."),
        ("-152653", "", "Yer kodeksi", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 110 modda to'liq kiritilgan."),
        ("-3517337", "O'RQ-468", "Fuqarolik protsessual kodeksi", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 513 modda to'liq kiritilgan."),
        ("-3527353", "O'RQ-469", "Maʼmuriy sud ishlarini yuritish toʻgʻrisidagi kodeks", "ALREADY", "all", "Reestrda to'liq (all) rejimda mavjud, 309 modda to'liq kiritilgan."),
        ("-3523891", "O'RQ-461", "Iqtisodiy protsessual kodeksi", "ADD", "all", "Iqtisodiy va tadbirkorlik nizolari bo'yicha protsessual normalarni to'liq qamrab olish uchun qo'shiladi."),
        ("-55594", "863-XII", "Havo kodeksi", "ADD", "all", "Nogironligi bo'lgan yo'lovchilarni tashish va xizmat ko'rsatish normalarini to'liq qamrab olish uchun qo'shiladi.")
    ]
    for cid, cnum, ctitle, cdec, cinc, creas in codes_config:
        add_or_update_entry(cid, "A", cdec, cinc, creas, number_hint=cnum, title_hint=ctitle, doc_type_hint="Kodeks")

    # 2. Group B: Key Statutes
    statutes_config = [
        ("-5049511", "O'RQ-641", "Nogironligi boʻlgan shaxslarning huquqlari toʻgʻrisida", "ALREADY", "all", "Reestrda asosiy baza qonuni sifatida to'liq mavjud."),
        ("-5055690", "O'RQ-642", "Aholi bandligi toʻgʻrisida", "ADD", "all", "Ish o'rinlari kvotalari, subsidiya va bandlik kafolatlari bo'yicha asosiy qonun."),
        ("-112314", "938-XII", "Fuqarolarning davlat pensiya taʼminoti toʻgʻrisida", "ADD", "all", "Nogironlik, boquvchisini yo'qotganlik va yoshga doir pensiyalarning asosiy qonuni."),
        ("-26013", "265-I", "Fuqarolar sogʻligʻini saqlash toʻgʻrisida", "ADD", "all", "Tibbiy yordam, dori ta'minoti va ekspertiza kafolatlarini belgilovchi tayanch qonun."),
        ("-2856464", "O'RQ-399", "Dori vositalari va farmatsevtika faoliyati toʻgʻrisida", "ADD", "all", "Dori vositalari kafolatlari va imtiyozli retseptlar bo'yicha yangi tahrirdagi qonun."),
        ("-5013007", "O'RQ-637", "Taʼlim toʻgʻrisida", "ALREADY", "all", "Inklyuziv ta'lim va maxsus ta'lim muassasalari normalari bilan reestrda to'liq mavjud."),
        ("-6502543", "O'RQ-848", "Davlat hisobidan yuridik yordam koʻrsatish toʻgʻrisida", "ALREADY", "all", "Ijtimoiy ehtiyojmand fuqarolarga bepul yuridik yordam ko'rsatish bo'yicha to'liq mavjud."),
        ("-54503", "349-I", "Advokatura toʻgʻrisida", "ADD", "all", "Fuqarolar huquqlarini professional himoya qilish va advokatlik kafolatlari qonuni."),
        ("-6145972", "O'RQ-788", "Davlat fuqarolik xizmati toʻgʻrisida", "ADD", "all", "Davlat xizmatiga qabul va mehnat munosabatlarini tartibga soluvchi asosiy qonun."),
        ("-3492199", "O'RQ-457", "Maʼmuriy tartib-taomillar toʻgʻrisida", "ALREADY", "all", "Davlat organlari bilan munosabatlar va ma'muriy shikoyatlar bo'yicha to'liq mavjud."),
        ("-3336169", "O'RQ-445", "Jismoniy va yuridik shaxslarning murojaatlari toʻgʻrisida", "ALREADY", "all", "Fuqarolar arizalari va shikoyatlarini ko'rib chiqish bo'yicha reestrda to'liq mavjud."),
        ("-1297315", "O'RQ-139", "Bola huquqlarining kafolatlari toʻgʻrisida", "ADD", "all", "Nogironligi bo'lgan bolalar va ijtimoiy himoyaga muhtoj oilalar kafolatlari qonuni."),
        ("-5422209", "O'RQ-690", "Psixiatriya yordami toʻgʻrisida", "ALREADY", "all", "Ruhiy holati buzilgan shaxslar huquqlari va ixtisoslashtirilgan yordam bo'yicha to'liq mavjud."),
        ("-4680944", "O'RQ-600", "Davlat boji toʻgʻrisida", "ALREADY", "all", "Nogironligi bo'lgan shaxslar uchun sud va notarial boj imtiyozlari bilan to'liq mavjud."),
        ("-4646908", "O'RQ-595", "Maktabgacha taʼlim va tarbiya toʻgʻrisida", "ALREADY", "all", "Reestrda to'liq mavjud."),
        ("-4704", "221-I", "Isteʼmolchilarning huquqlarini himoya qilish toʻgʻrisida", "ALREADY", "all", "Reestrda to'liq mavjud."),
        ("-1390913", "O'RQ-174", "Ishlab chiqarishdagi baxtsiz hodisalar va kasb kasalliklaridan majburiy davlat ijtimoiy sugʻurtasi toʻgʻrisida", "ALREADY", "all", "Reestrda to'liq mavjud."),
        ("-8472503", "O'RQ-1175", "Tazyiq va zoʻravonlikdan jabrlangan shaxslarga ijtimoiy xizmatlar koʻrsatish toʻgʻrisida", "ADD", "all", "Yangi qabul qilingan ijtimoiy xizmatlar qonuni (2026-09-11)."),
        ("-2307826", "O'RQ-364", "Vasiylik va homiylik toʻgʻrisida", "ADD", "all", "Muomalaga layoqatsiz yoki cheklangan shaxslar, yetim bolalar vasiyligi qonuni."),
        ("-4586282", "O'RQ-581", "Koʻp kvartirali uylarni boshqarish toʻgʻrisida", "ADD", "all", "Ko'p kvartirali uylarda qulay muhit va umumiy foydalanish qoidalari qonuni."),
        ("-4396419", "O'RQ-547", "Shaxsga doir maʼlumotlar toʻgʻrisida", "ADD", "all", "Tibbiy va ijtimoiy shaxsiy ma'lumotlar maxfiyligi qonuni."),
        ("-54458", "343-I", "Notariat toʻgʻrisida", "ADD", "all", "Notarial harakatlar, vasiyatnoma va ishonchnomalar berish tartibi qonuni."),
        ("-3031427", "O'RQ-410", "Mehnatni muhofaza qilish toʻgʻrisida", "ADD", "all", "Maxsus mehnat sharoitlari va xavfsizlik talablari qonuni."),
        ("-2156899", "O'RQ-350", "Fuqarolarning oʻzini oʻzi boshqarish organlari toʻgʻrisida", "ADD", "all", "Mahalla orqali ijtimoiy yordam va reyestr mexanizmlari qonuni."),
        ("-390573", "702-II", "Fuqarolarning jamgʻarib boriladigan pensiya taʼminoti toʻgʻrisida", "ADD", "all", "Xalq banki jamg'arib boriladigan pensiya hisobvarag'i tartibi."),
        ("-10550", "760-I", "Xotin-qizlarga qoʻshimcha imtiyozlar toʻgʻrisida", "ADD", "all", "Og'ir sharoitdagi xotin-qizlar va onalarga beriladigan imtiyozlar."),
        ("-98430", "846-XII", "Davlat uy-joy fondini xususiylashtirish toʻgʻrisida", "ADD", "all", "Uy-joyni tekinga xususiylashtirish va imtiyozlar qonuni."),
        ("-2240470", "O'RQ-353", "Odamning immunitet tanqisligi virusi keltirib chiqaradigan kasallik (OIV infeksiyasi) tarqalishiga qarshi kurashish toʻgʻrisida", "ADD", "all", "OIV bilan yashovchi shaxslarga ijtimoiy yordam va dori ta'minoti qonuni."),
        ("-2468214", "O'RQ-376", "Ijtimoiy sheriklik toʻgʻrisida", "ADD", "all", "Ijtimoiy himoya sohasidagi NNTlar va davlat hamkorligi qonuni."),
        ("-1183667", "O'RQ-96", "Homiylik toʻgʻrisida", "ADD", "all", "Homiylik yordami ajratish va soliq imtiyozlari qonuni."),
        ("-3083192", "O'RQ-415", "Keksalar, nogironligi boʻlgan shaxslar va aholining boshqa ijtimoiy ehtiyojmand toifalari uchun ijtimoiy xizmatlar toʻgʻrisida", "SKIP_REPEALED", "all", "Hujjat kuchini yo'qotgan (23.07.2026), ixtisoslashtirilgan xizmat aktlariga almashtirilgan.")
    ]
    for sid, snum, stitle, sdec, sinc, sreas in statutes_config:
        add_or_update_entry(sid, "B", sdec, sinc, sreas, number_hint=snum, title_hint=stitle, doc_type_hint="Qonun")

    # 3. Group C: Decrees & Resolutions
    decrees_config = [
        ("-8540128", "VMQ-555", "Hududiy ijtimoiy xizmatlar markazlarida aholining ehtiyojmand qatlamlariga kompleks ijtimoiy va reabilitatsiya xizmatlari koʻrsatishni tashkil etish chora-tadbirlari toʻgʻrisida", "PARSE_PROBLEM", "all", "Lex.uz'da matn tanasi (HTML/lx_elem) hali e'lon qilinmagan (faqat rekvizitlar e'lon qilingan, units=0)."),
        ("-8523611", "VMQ-539", "Odam savdosidan jabrlangan shaxslarga ijtimoiy xizmatlar koʻrsatish tartibi toʻgʻrisidagi nizomni tasdiqlash haqida", "ADD", "all", "Odam savdosi jabrdiydalariga reabilitatsiya va ijtimoiy xizmat ko'rsatish tartibi (2026-yil oktyabr)."),
        ("-8516575", "VMQ-526", "Kasbiy taʼlim tizimini tartibga soluvchi normativ-huquqiy hujjatlarni tasdiqlash toʻgʻrisida", "ADD", "disability_articles", "Katta hajmli akt (470 birlik), inklyuziv kasbiy ta'lim va imtiyozlarga oid moddalari olinadi."),
        ("-5953883", "VMQ-172", "Yoʻl harakati qoidalarini tasdiqlash toʻgʻrisida", "ADD", "all", "Nogironligi bo'lgan haydovchilar, to'xtash joylari va maxsus belgilar qoidalari."),
        ("-2430765", "VMQ-194", "Kommunal xizmatlar koʻrsatish qoidalarini tasdiqlash toʻgʻrisida", "ADD", "all", "Aholiga kommunal xizmatlar, kompensatsiya va imtiyozlar qoidalari."),
        ("-5461749", "VMQ-380", "Fuqarolarning oʻzini oʻzi boshqarish organlari faoliyatini yanada takomillashtirish toʻgʻrisida", "ADD", "all", "Mahalla orqali moddiy yordam ajratish va ijtimoiy xizmat ko'rsatish qoidalari."),
        ("-7515808", "VMQ-294", "Yetim va ota-ona qaramogʻidan mahrum boʻlgan bolalarni har tomonlama qoʻllab-quvvatlash", "ADD", "all", "Uy-joy, ta'lim va moddiy yordam mexanizmlari."),
        ("-7109778", "PQ-330", "“Kambagʻallikdan farovonlik sari” dasturini amalga oshirish boʻyicha birinchi navbatdagi chora-tadbirlar toʻgʻrisida", "ADD", "all", "Ijtimoiy reestr va ijtimoiy shartnoma tizimi."),
        ("-7100210", "PF-136", "Kambagʻallikni qisqartirish va aholini ijtimoiy himoya qilish sohasida davlat siyosatini yangi bosqichga olib chiqish chora-tadbirlari toʻgʻrisida", "ADD", "all", "Ijtimoiy himoya milliy agentligi vakolatlari va strategiyasi."),
        ("-7618066", "VMQ-423", "Maktabgacha taʼlim tashkiloti pedagogining kasbiy standartini tasdiqlash toʻgʻrisida", "ADD", "all", "Maxsus va inklyuziv guruhlar pedagoglari malaka talablari."),
        ("-5182451", "VMQ-806", "Oʻzini oʻzi band qilgan shaxs sifatida faoliyatni amalga oshirish tartibi toʻgʻrisida", "ADD", "all", "Nogironligi bo'lgan shaxslarning uy mehnatini rasmiylashtirish tartibi."),
        ("-5570968", "PQ-5215", "Yetim bolalar va ota-ona qaramogʻidan mahrum boʻlgan bolalarni davlat tomonidan qoʻllab-quvvatlashning yangi tizimini joriy etish chora-tadbirlari toʻgʻrisida", "ADD", "all", "Yetim va muhtoj bolalarga turar joy sotib olish kafolatlari."),
        ("-5569689", "PQ-5216", "Yetim bolalar va ota-ona qaramogʻidan mahrum boʻlgan bolalarning taʼlim-tarbiyasi hamda ijtimoiy himoyasini kuchaytirishga oid qoʻshimcha chora-tadbirlar toʻgʻrisida", "ADD", "all", "Ijtimoiy kvotalar va ta'lim to'lovlari."),
        ("-5117079", "VMQ-739", "Yetim bolalar va ota-onasining yoki boshqa qonuniy vakillarining qaramogʻidan mahrum boʻlgan bolalarni ijtimoiy qoʻllab-quvvatlashga doir qoʻshimcha chora-tadbirlar toʻgʻrisida", "ADD", "all", "Ijtimoiy ta'minot standartlari."),
        ("-4245424", "PQ-4242", "Eshitish va nutqida muammosi boʻlgan shaxslarni ijtimoiy qoʻllab-quvvatlashga doir qoʻshimcha chora-tadbirlar toʻgʻrisida", "ADD", "all", "Surdotarjimon xizmatlari va imo-ishora tili kafolatlari."),
        ("-4503026", "PQ-4440", "Kam uchraydigan (orfan) va boshqa irsiy-genetik kasalliklarga chalingan bolalarga tibbiy va ijtimoiy yordam koʻrsatishni yanada yaxshilash chora-tadbirlari toʻgʻrisida", "ADD", "all", "Orfan dori vositalari bilan bepul ta'minlash."),
        ("-7813468", "PQ-331", "2026-2030-yillarda kam uchraydigan (orfan) va boshqa irsiy-genetik kasalliklarga chalingan bolalarga tibbiy-ijtimoiy yordam koʻrsatish tizimini yanada takomillashtirish chora-tadbirlari toʻgʻrisida", "ADD", "all", "Orfan kasalliklar yangi davlat dasturi."),
        ("-8216684", "PQ-196", "Muborak Qurbon hayiti munosabati bilan aholini davlat tomonidan ijtimoiy qoʻllab-quvvatlash chora-tadbirlari toʻgʻrisida", "ADD", "all", "Bir martalik moddiy yordam ajratish mexanizmi."),
        ("-2978386", "REG-2799", "Umumiy oʻrta taʼlim tashkilotining pedagogik kengashi toʻgʻrisidagi nizomni tasdiqlash haqida", "ADD", "all", "Inklyuziv ta'limni tashkil etish pedagogik qarorlari."),
        ("-7869303", "REG-3715", "Statsionar tibbiyot muassasalaridagi bemorlarni tibbiy koʻrsatmalar asosida parvarishlash tartibi", "ADD", "all", "O'zgalar parvarishiga muhtoj bemorlarni parvarishlash qoidalari."),
        ("-7851955", "REG-3706", "Retsipiyent va tirik donorni har taraflama tibbiy tekshiruvdan oʻtkazish tartibi toʻgʻrisidagi nizomni tasdiqlash haqida", "ADD", "all", "Organ transplantatsiyasi va nogironlik profilaktikasi tekshiruvlari."),
        ("-2653127", "VMQ-135", "Oʻzbekiston Respublikasining Budjet kodeksini amalga oshirishga doir normativ-huquqiy hujjatlarni tasdiqlash toʻgʻrisida", "SKIP_REPEALED", "all", "Hujjat kuchini yo'qotgan (2015-yilgi qaror)."),
        ("-226628", "", "1992-yil 1-sentabrdan nafaqalar, stipendiyalar hamda budjet hisobidagi muassasalar", "SKIP_REPEALED", "all", "1992-yilgi eski akt, kuchini yo'qotgan."),
        ("-643316", "", "1992-yil 1-oktabrdan nafaqalar, stipendiyalar hamda budjet hisobidagi muassasalar", "SKIP_REPEALED", "all", "1992-yilgi eski akt, kuchini yo'qotgan."),
        ("-239313", "", "Pensiyalar, stipendiyalar hamda budjet hisobidagi muassasalar xodimlarining ish haqlarini oshirish toʻgʻrisida", "SKIP_REPEALED", "all", "1992-yilgi eski akt, kuchini yo'qotgan.")
    ]
    for did, dnum, dtitle, ddec, dinc, dreas in decrees_config:
        add_or_update_entry(did, "C", ddec, dinc, dreas, number_hint=dnum, title_hint=dtitle, doc_type_hint="Qaror" if "VMQ" in dnum or "Qaror" in dtitle else "Farmon")

    # 4. Group D: International
    intl_config = [
        ("-5501227", "BMT Konvensiyasi (2006)", "Nogironlar huquqlari toʻgʻrisida", "ALREADY", "all", "Reestrda to'liq (51 modda) mavjud, asosiy xalqaro shartnoma.", "Konvensiya", "2006-12-13", 51, "active", False),
        ("-5447413", "O'RQ-695", "Nogironlar huquqlari toʻgʻrisidagi Konvensiyani (Nyu-York, 2006-yil 13-dekabr) ratifikatsiya qilish haqida", "ALREADY", "all", "Reestrda to'liq mavjud.", "Qonun", "2021-06-07", 3, "active", True),
        ("crpd_optional_protocol", "BMT Protokoli", "Nogironlar huquqlari toʻgʻrisidagi konvensiyaning Fakultativ protokoli", "NOT_FOUND", "all", "Lex.uz milliy qonunchilik bazasida e'lon qilinmagan (O'zbekiston tomonidan hali ratifikatsiya qilinmagan).", "Protokol", "", 0, "not_published", False)
    ]
    for iid, inum, ititle, idec, iinc, ireas, idt, iad, iun, ist, iv in intl_config:
        add_or_update_entry(iid, "D", idec, iinc, ireas, number_hint=inum, title_hint=ititle, doc_type_hint=idt, adopted_hint=iad, units_hint=iun, status_hint=ist, verify_lex=iv)

    # 5. Group E: Amending Acts
    amending_config = [
        ("-2855474", "O'RQ-398", "Soliq va budjet siyosatining 2016-yilga moʻljallangan asosiy yoʻnalishlari qabul qilinganligi munosabati bilan Oʻzbekiston Respublikasining Soliq kodeksiga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat Soliq kodeksiga tuzatishlar kiritgan, Lex.uz bazasidagi Soliq kodeksiga singdirilgan."),
        ("-2304017", "O'RQ-361", "Oʻzbekiston Respublikasining Budjet kodeksi qabul qilinishi munosabati bilan Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat qonunlarga o'zgartirishlar kiritgan, mustaqil normasi yo'q."),
        ("-2876198", "O'RQ-401", "Oʻzbekiston Respublikasining Bojxona kodeksi qabul qilinishi munosabati bilan Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartishlar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat boshqa aktlarga o'zgartirishlar kiritadi."),
        ("-4574345", "O'RQ-577", "Bojxona maʼmuriyatchiligi takomillashtirilishi munosabati bilan Oʻzbekiston Respublikasining Maʼmuriy javobgarlik toʻgʻrisidagi kodeksiga oʻzgartish va qoʻshimchalar kiritish haqida", "SKIP_AMENDING_ONLY", "all", "Faqat MJtKga o'zgartirish kiritish bilan cheklangan."),
        ("-5844851", "O'RQ-748", "Oʻzbekiston Respublikasining Bojxona kodeksiga qoʻshimcha va oʻzgartishlar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Bojxona kodeksiga kiritilgan tahrirlar, mustaqil normasi yo'q."),
        ("-6020838", "O'RQ-770", "Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Bir nechta aktlarga texnik o'zgartirishlar ro'yxati."),
        ("-5388561", "O'RQ-683", "Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Bir nechta aktlarga texnik o'zgartirishlar ro'yxati."),
        ("-4631276", "O'RQ-587", "Bola huquqlarining kafolatlari yanada kuchaytirilishi munosabati bilan Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat o'zgartirishlar ro'yxati, tegishli aktlarga singdirilgan."),
        ("-4759606", "O'RQ-608", "Bola huquqlarining qoʻshimcha kafolatlari belgilanishi munosabati bilan Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat o'zgartirishlar ro'yxati."),
        ("-5764516", "O'RQ-735", "Bola huquqlarining kafolatlarini taʼminlash tizimi yanada takomillashtirilishi munosabati bilan Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat o'zgartirishlar ro'yxati."),
        ("-8302734", "O'RQ-1156", "Oʻzbekiston Respublikasining ayrim qonun hujjatlariga bola huquqlarini himoya qilish boʻyicha oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Faqat o'zgartirishlar ro'yxati."),
        ("-3747789", "VMQ-382", "Vazirlar Mahkamasining “Oʻzbekiston Respublikasi Budjet kodeksini amalga oshirish boʻyicha normativ-huquqiy hujjatlarni tasdiqlash toʻgʻrisida” 245-son qaroriga oʻzgartirish va qoʻshimchalar kiritish haqida", "SKIP_AMENDING_ONLY", "all", "Faqat 245-son qaror bandlariga tuzatish kiritadi."),
        ("-2939512", "VMQ-122", "Oʻzbekiston Respublikasi Hukumatining ayrim qarorlariga oʻzgartirish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Hukumat qarorlariga texnik o'zgartirishlar ro'yxati."),
        ("-2989282", "VMQ-211", "Oʻzbekiston Respublikasi Hukumatining ayrim qarorlariga oʻzgartirish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Hukumat qarorlariga texnik o'zgartirishlar ro'yxati."),
        ("-4655637", "VMQ-1022", "Oʻzbekiston Respublikasi Hukumatining ayrim qarorlariga qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Qarorlarga qo'shimcha bandlar ro'yxati."),
        ("-3758050", "PF-5454", "Oʻzbekiston Respublikasi Prezidentining ayrim hujjatlariga oʻzgartirish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Prezident hujjatlariga kiritilgan o'zgartirishlar matni."),
        ("-3084099", "O'RQ-416", "Oʻzbekiston Respublikasining ayrim qonun hujjatlariga oʻzgartish va qoʻshimchalar kiritish toʻgʻrisida", "SKIP_AMENDING_ONLY", "all", "Ayrim qonunlarga o'zgartish kirituvchi texnik akt.")
    ]
    for eid, enum, etitle, edec, einc, ereas in amending_config:
        add_or_update_entry(eid, "E", edec, einc, ereas, number_hint=enum, title_hint=etitle, doc_type_hint="Qonun" if "O'RQ" in enum else "Qaror")

    # 6. Include all other existing registry items as ALREADY (if not already entered above)
    for d in existing_reg:
        lid = str(d.get("lex_id"))
        if lid in plan_entries:
            continue
        g = classify_group(d.get("doc_type", ""), d.get("title", ""), lid)
        reason = f"Reestrda mavjud ({d.get('include', 'all')}), {d.get('units', 0)} birlik indekslangan."
        plan_entries[lid] = {
            "lex_id": lid,
            "url": f"https://lex.uz/uz/docs/{lid}",
            "number": d.get("number") or d.get("number_override") or "",
            "title": d.get("title", ""),
            "doc_type": d.get("doc_type", ""),
            "adopted": d.get("adopted") or "",
            "status": "active",
            "units": int(d.get("units") or 0),
            "group": g,
            "decision": "ALREADY",
            "include": d.get("include", "all"),
            "reason": reason,
            "verified_at": d.get("verified_at") or date.today().isoformat()
        }

    # 7. Add sample skipped domain candidates (to show why skipped)
    sample_skips = [
        ("-8244005", "PF-103", "Madaniyat, sanʼat va adabiyot sohalarini yanada rivojlantirish", "SKIP_IRRELEVANT", "all", "Ijodkorlar va teatr xodimlarini rag'batlantirishga doir tarmoq dasturi, ijtimoiy himoyaga taalluqli emas."),
        ("-8050771", "PQ-65", "Muborak Ramazon oyini munosib tarzda oʻtkazish toʻgʻrisida", "SKIP_IRRELEVANT", "all", "Umumxalq bayramlarini nishonlash bo'yicha tashkiliy tadbirlar rejasi."),
        ("-7834231", "VMQ-715", "“Ijtimoiy himoya fidoyisi” koʻkrak nishonini taʼsis etish toʻgʻrisida", "SKIP_IRRELEVANT", "all", "Soha xodimlarini taqdirlash uchun ta'sis etilgan idoraviy ko'krak nishoni nizomi."),
        ("-7083841", "PF-124", "Fuqarolik jamiyati institutlarini davlat tomonidan qoʻllab-quvvatlash", "SKIP_IRRELEVANT", "all", "NNTlar va jamoat fondlariga davlat grantlari ajratish tartibi."),
        ("-7027139", "PQ-264", "Oʻzbekiston Respublikasi davlat mustaqilligining oʻttiz uch yillik bayramiga tayyorgarlik koʻrish", "SKIP_IRRELEVANT", "all", "Tashkiliy bayram tadbirlari akti."),
        ("-7024842", "VMQ-431", "Arxitektura va qurilish sohasi faxriylariga qulay shart-sharoitlar yaratish", "SKIP_IRRELEVANT", "all", "Faqat bitta tor soha faxriylariga mo'ljallangan idoraviy rag'batlantirish akti.")
    ]
    for skid, sknum, sktitle, skdec, skinc, skreas in sample_skips:
        if skid not in plan_entries:
            add_or_update_entry(skid, "C", skdec, skinc, skreas, number_hint=sknum, title_hint=sktitle, doc_type_hint="Qaror" if "VMQ" in sknum else "Farmon")

    lex.close()

    # Convert to sorted list
    group_order = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    decision_order = {"ADD": 1, "ALREADY": 2, "PARSE_PROBLEM": 3, "NOT_FOUND": 4, "SKIP_REPEALED": 5, "SKIP_AMENDING_ONLY": 6, "SKIP_IRRELEVANT": 7}

    plan_list = list(plan_entries.values())
    plan_list.sort(key=lambda x: (
        group_order.get(x["group"], 99),
        decision_order.get(x["decision"], 99),
        -(x.get("units") or 0),
        x.get("number") or ""
    ))

    # Save data/sources/collection_plan.json
    out_json = SOURCES / "collection_plan.json"
    out_json.write_text(json.dumps(plan_list, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Wrote {out_json} with {len(plan_list)} entries.")

    # Save data/sources/add_commands.sh
    add_items = [p for p in plan_list if p["decision"] == "ADD"]
    add_lines = [
        "#!/usr/bin/env bash",
        "# Avtomatik shakllantirilgan qo'shish buyruqlari (data/sources/add_commands.sh)",
        "# DIQQAT: Faqat ko'rib chiqish uchun; talab bo'yicha ishga tushirilmaydi.",
        "",
    ]
    for item in add_items:
        inc = item["include"]
        lid = item["lex_id"]
        comm = f"# {item['group']}-guruh: {item['number'] or '-'} | {item['title'][:70]} (kutilayotgan birliklar: {item['units']})"
        cmd = f"python scripts/build_disability_corpus.py add --lex-id={lid} --include={inc}"
        add_lines.extend([comm, cmd, ""])
    
    out_sh = SOURCES / "add_commands.sh"
    out_sh.write_text("\n".join(add_lines), encoding="utf-8")
    out_sh.chmod(0o755)
    log.info(f"Wrote {out_sh} with {len(add_items)} ADD commands.")

    return plan_list

if __name__ == "__main__":
    main()
