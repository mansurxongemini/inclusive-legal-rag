#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
havola_new.py - Lex.uz'dan nogironligi bo'lgan shaxslarning huquqlariga oid AMALDAGI barcha hujjatlarni
avtomatik aniqlaydi va ularning real havolalarini real_hujjatlar.md fayliga yozadi.

Ishlash tartibi (har safar Lex.uz'dan jonli ma'lumot olinadi):

 1. QIDIRUV - to'liqlik uchun. Lex.uz'ning rasmiy qidiruvi "faqat amaldagi hujjatlar" (status=Y) filtri bilan
    bir nechta kanal bo'yicha ishlatiladi:
      * hujjat MATNI ichidan qidiruv: o'zbekcha (lotin va kirill) va ruscha atamalar - nogiron*, nogironlik*,
        imkoniyati cheklangan, tibbiy-ijtimoiy ekspertiza (TIEK/TMEK), protez-ortopediya, Brayl, imo-ishora tili,
        ko'zi ojiz, kar, alohida ta'lim ehtiyojlari, inklyuziv ta'lim, to'siqsiz muhit, o'zgalar parvarishiga muhtoj ...
        (Lex.uz so'z o'zagi bo'yicha qidiradi: "nogiron" va "nogironlik" - turli o'zaklar, shuning uchun ikkalasi ham);
      * rasmiy klassifikator (OKOZ) ning nogironlikka oid bo'limlari (id'lari har safar klassifikator daraxtidan olinadi);
      * bo'limlar: milliy qonunchilik, Oliy Majlis, xalqaro shartnomalar, texnik normativlar, mahalliy hokimiyat.
    Har bir qidiruv natijasi Lex.uz'ning "Ro'yxatni Word ga eksport qilish" funksiyasi orqali bitta so'rovda TO'LIQ
    olinadi (sahifalab yurish shart emas) va asosiy kanallarda sahifadagi "N hujjat topildi" soni bilan solishtiriladi.

 2. TEKSHIRUV - aniqlik uchun. Har bir nomzod hujjatning to'liq matni yuklab olinadi va element-ba-element tekshiriladi:
      * Lex.uz qo'shadigan klassifikator izohlari [OKOZ: ...], o'zgartirish izohlari va "LexUZ sharhi" hisobga olinmaydi;
      * kuchini yo'qotgan moddalar/bandlar hisobga olinmaydi;
      * nogironlikni faqat "o'z kuchini yo'qotgan deb topilsin" ro'yxatida tilga olgan hujjatlar asosiy ro'yxatga kirmaydi;
      * har bir mos kelgan modda/band uchun Lex.uz'dagi aniq joyiga to'g'ridan-to'g'ri havola (#element-id) beriladi.

 3. HISOBOT - real_hujjatlar.md (+ mashina uchun real_hujjatlar.json): yuridik kuchi bo'yicha (Konstitutsiyadan
    mahalliy hujjatgacha) guruhlangan; o'zgartirish kirituvchi, operativ, hali kuchga kirmagan va qo'lda tekshirish
    kerak bo'lgan hujjatlar alohida bo'limlarda; oldingi ishga tushirishdan beri qo'shilgan/chiqib ketganlar ko'rsatiladi.

Ishga tushirish (faqat Python 3.8+ standart kutubxonasi kerak):
    python3 havola_new.py
    python3 havola_new.py --ishchilar 6 --chiqish natija.md
    python3 havola_new.py --yangilash          # hujjatlar keshini e'tiborsiz qoldirib, hammasini qayta yuklash
    python3 havola_new.py --bolimlar nat,int   # faqat tanlangan bo'limlar
"""
import argparse
import gzip
import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LEX = "https://lex.uz"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
              "havola_new/1.0 (nogironlik huquqlari bo'yicha tadqiqot)")
SCRIPT_DIR = Path(__file__).resolve().parent

# Lex.uz qidiruv bo'limlari: /uz/search/<kod>
BOLIMLAR = OrderedDict([
    ("nat", "Milliy qonunchilik"),
    ("oliy", "Oliy Majlis palatalari"),
    ("int", "Xalqaro shartnomalar"),
    ("tech", "Texnik normativ hujjatlar"),
    ("loc", "Mahalliy davlat hokimiyati"),
])
NATURE_BOLIMLAR = {"nat", "oliy"}   # "normativ-huquqiy / operativ" filtri faqat shu bo'limlarda bor

# Lex.uz hujjat tillari: 4 - o'zbek (lotin), 3 - o'zbek (kirill), 1 - rus
QUERIES: Dict[str, List[str]] = {
    "4": [
        "nogiron", "nogironlik", "imkoniyati cheklangan", "tibbiy-ijtimoiy ekspertiza", "tibbiy-mehnat ekspert",
        "protez-ortopediya", "reabilitatsiya texnik vositalari", "kreslo-aravacha", "eshitish apparati",
        "koxlear implant", "Brayl", "imo-ishora", "surdotarjimon", "ko'zi ojiz", "zaif ko'ruvchi", "karlar",
        "soqov", "alohida ta'lim ehtiyojlari", "inklyuziv ta'lim", "to'siqsiz muhit", "kam harakatlanuvchi",
        "o'zgalar parvarishiga muhtoj", "serebral falaj", "autizm", "Daun sindromi", "rivojlanishida nuqsoni",
        "aqliy zaif", "mehnat qobiliyatini yo'qotish",
    ],
    "3": ["ногирон", "ногиронлик", "имконияти чекланган", "тиббий-ижтимоий экспертиза", "тиббий-меҳнат эксперт"],
    "1": [
        "инвалид", "инвалидность", "ограниченными возможностями", "медико-социальной экспертизы",
        "врачебно-трудовой экспертной", "протезно-ортопедических", "технических средств реабилитации",
        "Брайля", "жестового языка", "сурдопереводчик", "слепых", "глухих",
        "особыми образовательными потребностями", "инклюзивного образования", "безбарьерной среды",
        "маломобильных", "постороннем уходе", "церебральный паралич", "аутизм",
    ],
}
LANG_NOMI = {"4": "o'zbek (lotin)", "3": "o'zbek (kirill)", "1": "rus"}

# Rasmiy klassifikator (OKOZ) ning nogironlikka oid bo'limlari. Id'lar har safar daraxtdan kod bo'yicha topiladi,
# nomida "nogiron" so'zi bo'lgan barcha bo'limlar ham avtomatik qo'shiladi.
OKOZ_KODLAR = [
    "06.10.00.00",  # Nogironligi bo'lgan shaxslar va fuqarolarning boshqa toifalarining ijtimoiy himoyasi
    "06.06.03.00",  # Nogironlik pensiyasi
    "06.06.17.00",  # Nogironlikni belgilash
    "06.07.01.03",  # Nogironligi bo'lgan bolalarga nafaqalar
    "06.07.02.01",  # Nogironligi bo'lgan shaxslarga kompensatsiya to'lovlari
    "06.09.01.00",  # Nogironligi bo'lgan shaxslar uchun imtiyozlar
    "05.09.03.00",  # Nogironligi bo'lgan shaxslar mehnati
    "06.08.02.00",  # Internatlar, nogironligi bo'lgan shaxslar uylarida ijtimoiy xizmat
    "06.08.04.00",  # Reabilitatsiya
    "14.01.07.00",  # Keksalar va nogironligi bo'lgan shaxslarga tibbiy yordam
    "14.01.10.00",  # Tibbiy-ijtimoiy ekspertiza
    "14.01.03.05",  # Protez-ortopediya yordami
    "01.17.09.00",  # ... nogironligi bo'lgan shaxslar uyushmalari
    "08.01.05.00",  # Ixtisoslashtirilgan uylar (nogironligi bo'lgan shaxslar uchun internat uylari ...)
]

# --------------------------------------------------------------------------------------------------------------
# Atamalar lug'ati: hujjat matnida shulardan kamida bittasi (amaldagi, operativ qismda) bo'lishi shart.
# O'zbekcha qoidalar kichik harfli, apostroflari "'" ga keltirilgan lotin matnga qo'llanadi (kirill - lotinga o'giriladi).
ATAMALAR_UZ: List[Tuple[str, str]] = [
    ("nogironlik", r"nogiron|\bmayip"),          # "майып" - qoraqalpoqcha "nogiron"
    ("imkoniyati cheklangan",
     r"(?:jismoniy|aqliy|ruhiy|sog'lig'i|harakatlanish)\s+imkoniyat\w*\s+cheklangan|"
     r"imkoniyat(?:i|lari)\s+cheklangan\s+(?:shaxs|bola|fuqaro|o'quvchi|talaba|kishi|inson|yosh|ayol|xotin|"
     r"tarbiyalanuvchi|odam|pensioner|nafaqaxo'r|xodim|ishchi|bemor|yo'lovchi|o'g'il|qiz|sportchi|shaxmatchi)"),
    ("tibbiy-ijtimoiy ekspertiza", r"tibbiy[\s-]+(?:ijtimoiy|mehnat)\s+ekspert|\b(?:tiek|tmek|vtek)\b"),
    ("protez-ortopediya", r"protez[\s-]+ortoped"),
    ("reabilitatsiya texnik vositalari",
     r"reabilitatsiya\w*\s+(?:qilish\w*\s+)?texnik\s+vosita|kreslo[\s-]+aravacha|aravachada\s+harakatlan|"
     r"eshitish\s+(?:apparat|moslama)|koxlear\s+implant"),
    ("Brayl / imo-ishora tili / surdo-tiflo",
     r"\bbrayl|imo[\s-]+ishora\w*\s+(?:til|tarjim|orqali|bilan\s+muloqot)|\bsurdo|\btiflo"),
    # "ko'r" / "kar" faqat odamga nisbatan ishlatilganda: "ko'r ichak", "elektr-kar", "Sanjib Kar" hisobga olinmaydi
    ("ko'rish / eshitish nuqsoni",
     r"ko'zi\s+ojiz|zaif\s+ko'ruvchi|\bsoqov|zaif\s+eshituvchi|qulog'i\s+og'ir|"
     r"(?<![-\w])(?:ko'r|kar)(?:lar\w*|lik\w*|-soqov\w*)|"
     r"(?<![-\w])(?:ko'r|kar)(?=\s*(?:,|\)|va\b|yoki\b|bola|shaxs|fuqaro|inson|odam|kishi|o'quvchi|ayol|erkak))|"
     r"(?:ko'rish|eshitish)\s+(?:qobiliyat|imkoniyat)\w*\s+(?:zaif|cheklangan|buzilgan|past|yo'q)(?!\w*\s+sharoit)"),
    ("alohida ta'lim ehtiyojlari / inklyuziv ta'lim",
     r"alohida\s+ta'lim\w*\s+ehtiyoj|alohida\s+ehtiyojli\s+(?:bola|shaxs|o'quvchi|tarbiyalanuvchi|talaba)|"
     r"inklyuziv\s+(?:ta'lim|o'qitish|sinf|guruh|maktab|sport|turizm|muhit|bandlik|kasb)"),
    ("to'siqsiz muhit",
     r"to'siq(?:siz|larsiz)\s+(?:va\s+qulay\s+)?(?:muhit|turizm|infratuzilma)|qulay\s+va\s+to'siq(?:siz|larsiz)|"
     r"kam\s+harakatlanuvchi"),
    ("rivojlanish nuqsoni (aqliy, serebral falaj, autizm, Daun)",
     r"(?:jismoniy|aqliy|ruhiy|psixik)(?:\w*[\s-]+(?:va\s+|yoki\s+)?(?:jismoniy|aqliy|ruhiy|psixik))?\w*[\s-]+"
     r"rivojlanish\w*\s+(?:nuqson|orqada\s+qol|buzil)|aqliy\s+(?:zaif|qoloq)|serebral\s+falaj|\bautizm|autistik|"
     r"daun\s+sindrom"),
    # faqat kasbiy (TMEK belgilaydigan) mehnat qobiliyatini yo'qotish; "vaqtincha" yoki "to'satdan" yo'qotish hisobga olinmaydi
    ("kasbiy mehnat qobiliyatini yo'qotish", r"kasbiy\s+mehnat\s+qobiliyatini\s+(?:\w+\s+)?yo'qot"),
]
ATAMALAR_RU: List[Tuple[str, str]] = [
    ("инвалидность", r"инвалид"),
    ("ограниченные возможности",
     r"(?:лиц|людей|детей|граждан|человек\w*|студент\w*|учащ\w*|обучающ\w*|молодеж\w*|женщин\w*|спортсмен\w*)"
     r"\s+с\s+ограниченн\w+\s+(?:физическ\w+\s+)?возможност|ограниченн\w+\s+возможност\w*\s+(?:здоровья|по\s+зрению|по\s+слуху)"),
    ("медико-социальная экспертиза", r"медико[\s-]+социальн\w*\s+эксперт|врачебно[\s-]+трудов\w*\s+эксперт|"
                                     r"\b(?:втэк|мсэк)\b"),
    ("протезирование и ТСР", r"протезно[\s-]+ортопед|техническ\w*\s+средств\w*\s+реабилитац|кресл\w*[\s-]+коляс|"
                             r"слухов\w*\s+аппарат|кохлеарн"),
    ("Брайль / жестовый язык", r"брайл|жестов\w*\s+язык|\bсурдо|\bтифло"),
    # "глухие заклепки/короба", "слепые стволы" (шахты) не считаются
    ("слепые / глухие", r"незрячи|слабовидящ|слабослышащ|глухонем|слепоглух|"
                        r"\bслеп(?:ых|ым|ыми|ые)\b(?!\s+(?:ствол|выработ|шахт|зон|короб|перемыч))|"
                        r"\bглух(?:их|им|ими|ие)\s+(?:и\s+слабослышащ|дет|людей|граждан|лиц|учащ|школьник)"),
    ("особые образовательные потребности", r"особ\w+\s+образовательн\w+\s+потребност|"
                                           r"инклюзивн\w+\s+(?:образован|обучен)"),
    ("безбарьерная среда", r"безбарьерн|маломобильн"),
    ("посторонний уход", r"посторонне\w*\s+уход"),
    ("нарушения развития", r"церебральн\w*\s+паралич|\bаутизм|синдром\w*\s+дауна|умственн\w*\s+отстал"),
    ("стойкая утрата трудоспособности",
     r"(?:стойк|профессиональн)\w*\s+утрат\w*\s+(?:\w+\s+)?трудоспособност|"
     r"утрат\w*\s+(?:стойк|профессиональн)\w*\s+трудоспособност"),
]
_RX_UZ = [(lab, re.compile(rx)) for lab, rx in ATAMALAR_UZ]
_RX_RU = [(lab, re.compile(rx)) for lab, rx in ATAMALAR_RU]

# Nogironlikni faqat bekor qilinayotgan hujjatlar ro'yxatida tilga olish ("... o'z kuchini yo'qotgan deb topilsin")
_RX_BEKOR_ROYXAT = re.compile(r"kuchini\s+yo'qotgan\s+deb|утративш\w*\s+силу|признать\s+утративш")
# Kuchini yo'qotgan modda/band belgisi ("17-modda. Kuchini yo'qotgan.", "5. Kuchini yo'qotgan.", "Статья 7. Утратила силу")
_RX_KUCHSIZ = re.compile(
    r"^(?:(?:\d+[\d.\-–^]*\s*(?:-?\s*(?:modda|band))?|статья\s+\d+[\d\-–^]*)\s*[.:]?\s*)?\(?\s*"
    r"(?:kuchini\s+yo'qotgan|утратил\w*\s+силу|исключен[аоы]?\b)")
_RX_PDF = re.compile(r"hujjat\s+matni\s+pdf\s+shaklda|текст\s+документа\s+(?:представлен|приведен)\s+в\s+(?:формате\s+)?pdf",
                     re.IGNORECASE)
# Lex.uz qo'shadigan klassifikator izohlari
_RX_IZOH = re.compile(r"\[\s*(?:OKOZ|TSZ|QTUK|ОКОЗ|ТСЗ)\s*:[^\]]*\]", re.IGNORECASE)
_RX_UI = re.compile(r"Hujjatga taklif yuborish|Audioni tinglash|Hujjat elementidan havola olish|"
                    r"Oldingi tahrirga qarang\.?|Предложение к документу|Прослушать аудио|Получить ссылку на элемент")

# Matn hisoblanmaydigan elementlar (imzo, rekvizit, izohlar, o'zgartirish manbalari)
ROLES_SKIP = {
    "CHANGES_ORIGINS", "COMMENT", "COMMENTLEXUZ", "INDEXES_ON_REF", "SIGNATURE", "SIGNATURE_WITH_BOLD",
    "ACCEPTING_BODY", "ACT_FORM", "GRIF_PARLAMENT", "GRIF_PRESIDENT", "LX_PLACE_DATE", "ACT_ESSENTIAL_ELEMENTS",
    "ACT_ESSENTIAL_ELEMENTS_NUM", "PUBLICATION_ORIGIN",
}
ROLES_ANNEX = {"APPL_BANNER_LANDSCAPE_TITLE", "APPL_BANNER_PORTRAIT_TITLE", "APPL_BANNER_TITLE"}
ROLES_ANNEX_TITLE = {"ACT_TITLE_APPL", "ACT_TITLE_APPL_ADD"}

# Yuridik kuchi bo'yicha tartib (yuqoridan pastga)
DARAJALAR = OrderedDict([
    ("konstitutsiya", "Konstitutsiya"),
    ("xalqaro", "Xalqaro shartnomalar va hujjatlar"),
    ("kodeks", "Kodekslar"),
    ("qonun", "Qonunlar"),
    ("oliy_majlis", "Oliy Majlis palatalari qarorlari"),
    ("farmon", "Prezident farmonlari"),
    ("pq", "Prezident qarorlari"),
    ("prezident_farmoyish", "Prezident farmoyishlari"),
    ("vmq", "Vazirlar Mahkamasi qarorlari"),
    ("vm_farmoyish", "Vazirlar Mahkamasi farmoyishlari"),
    ("sud", "Oliy sud Plenumi va Konstitutsiyaviy sud qarorlari"),
    ("idoraviy", "Vazirlik va idoralarning hujjatlari"),
    ("texnik", "Texnik normativ hujjatlar (QMQ, SHNQ, standartlar)"),
    ("mahalliy", "Mahalliy davlat hokimiyati hujjatlari"),
    ("boshqa", "Boshqa hujjatlar (shu jumladan sobiq ittifoq davri)"),
])
TOIFA_BELGI = {"asosiy": "🟢 Asosiy", "muhim": "🟡 Muhim", "qisman": "⚪ Qisman"}
TOIFA_TARTIB = {"asosiy": 0, "muhim": 1, "qisman": 2}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------------------------------------------
# Matnni normallashtirish
_APOS = dict.fromkeys(map(ord, "ʻʼ’‘`´ʹ′"), "'")
_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ь": "", "ы": "i", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}


def norm_latin(text: str) -> str:
    t = (text or "").translate(_APOS).lower()
    if re.search(r"[а-яёўқғҳ]", t):
        t = "".join(_CYR2LAT.get(ch, ch) for ch in t)
    return re.sub(r"\s+", " ", t)


def to_lex_spelling(text: str) -> str:
    """Lex.uz lotin matnida o'/g' - U+02BB, boshqa apostroflar - U+02BC."""
    t = re.sub(r"([oOgG])['`’‘ʻʼ]", lambda m: m.group(1) + "ʻ", text)
    return re.sub(r"['`’‘]", "ʼ", t)


def find_terms(text: str, til: str) -> List[Tuple[str, int, int]]:
    """Matndagi atamalar: (yorliq, boshlanish, tugash) - pozitsiyalar normallashtirilgan matn bo'yicha."""
    found = []
    if til == "ru":
        low = re.sub(r"\s+", " ", (text or "").lower().replace("ё", "е"))
        for lab, rx in _RX_RU:
            m = rx.search(low)
            if m:
                found.append((lab, m.start(), m.end()))
    else:
        low = norm_latin(text)
        for lab, rx in _RX_UZ:
            m = rx.search(low)
            if m:
                found.append((lab, m.start(), m.end()))
    return found


def strip_tags(fragment: str) -> str:
    t = re.sub(r"<(?:br|/p|/td|/tr|/li|/div)\b[^>]*>", " ", fragment, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = _RX_IZOH.sub(" ", t)
    t = _RX_UI.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_dmy(text: str) -> str:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text or "")
    if not m:
        return ""
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return ""


def iso_to_dmy(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if iso and len(iso) == 10 else ""


# --------------------------------------------------------------------------------------------------------------
class Http:
    """Lex.uz uchun xushmuomala HTTP klient: global tezlik cheklovi, qayta urinish, gzip."""

    def __init__(self, min_interval: float = 0.25, timeout: float = 90.0, retries: int = 5):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        self._next = 0.0
        self.count = 0

    def _wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.min_interval
            self.count += 1
        if slot > now:
            time.sleep(slot - now)

    def request(self, url: str, data: Optional[dict] = None, headers: Optional[dict] = None) -> Tuple[int, str, str]:
        """(status, content-type, matn). 404 xato emas - (404, '', '') qaytadi."""
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept-Language": "uz,ru;q=0.8"}
        hdrs.update(headers or {})
        last = None
        for attempt in range(self.retries):
            self._wait_turn()
            try:
                req = urllib.request.Request(url, data=body, headers=hdrs, method="POST" if body is not None else "GET")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    return resp.status, resp.headers.get("Content-Type", ""), raw.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return 404, "", ""
                last = f"HTTP {e.code}"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as e:  # tarmoq uzilishi, timeout
                last = f"{type(e).__name__}: {e}"
            time.sleep(min(30.0, 2.0 * (2 ** attempt)))
        raise RuntimeError(f"{url}: {last}")


# --------------------------------------------------------------------------------------------------------------
class LexSearch:
    """Lex.uz qidiruvi: natijalar ro'yxati 'Word ga eksport' orqali bitta so'rovda olinadi."""

    EXPORT_TARGET = "ucFoundActsControl$ctl00"

    def __init__(self, http: Http):
        self.http = http
        self._fields: Dict[str, dict] = {}
        self._flock = threading.Lock()

    @staticmethod
    def url(section: str, params: dict) -> str:
        return f"{LEX}/uz/search/{section}?" + urllib.parse.urlencode(params)

    @staticmethod
    def _hidden_fields(page: str) -> dict:
        return {m.group(1): html.unescape(m.group(2))
                for m in re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page)}

    @staticmethod
    def parse_count(page: str) -> Optional[int]:
        text = re.sub(r"<[^>]+>", " ", page)
        m = re.search(r"(\d[\d\s ]*)\s*hujjat\s+topildi", text)
        if m:
            return int(re.sub(r"\D", "", m.group(1)))
        return 0 if "dd-table__main-item" not in page else None

    def _form_fields(self, section: str, refresh_url: Optional[str] = None) -> dict:
        """ASP.NET forma maydonlari (__VIEWSTATE ...) - bo'lim uchun bir marta olinadi va qayta ishlatiladi."""
        with self._flock:
            if section not in self._fields or refresh_url:
                _, _, page = self.http.request(refresh_url or self.url(section, {"query": "nogiron", "status": "Y", "lang": "4"}))
                f = self._hidden_fields(page)
                if "__VIEWSTATE" not in f:
                    raise RuntimeError("Lex.uz qidiruv sahifasi kutilgan shaklda emas (__VIEWSTATE topilmadi)")
                self._fields[section] = f
            return dict(self._fields[section])

    @staticmethod
    def parse_export(doc: str) -> List[dict]:
        rows = []
        for tr in re.findall(r"<tr><td>\d+</td>(.*?)(?=<tr><td>\d+</td>|</tbody>|</table>|$)", doc, re.S):
            cells = re.findall(r"<td>(.*?)</td>", "<td>" + tr if not tr.startswith("<td>") else tr, re.S)
            link = re.search(r'href="([^"]+/docs/(-?\d+))"', tr)
            if not link or len(cells) < 3:
                continue
            rekv = cells[0]
            number = ""
            if re.search(r"<br\s*/?>", rekv):
                number = strip_tags(re.split(r"<br\s*/?>", rekv)[0]).rstrip(", ")
            rows.append({
                "id": link.group(2),
                "number": number,
                "date": parse_dmy(strip_tags(rekv)),
                "title": strip_tags(cells[1]),
                "effective": parse_dmy(strip_tags(cells[2])) if len(cells) > 2 else "",
            })
        return rows

    def export(self, section: str, params: dict) -> List[dict]:
        url = self.url(section, params)
        for attempt in range(3):
            fields = self._form_fields(section, refresh_url=url if attempt else None)
            fields["__EVENTTARGET"] = self.EXPORT_TARGET
            fields["__EVENTARGUMENT"] = ""
            status, ctype, doc = self.http.request(url, data=fields, headers={"Referer": url})
            if status == 200 and ("msword" in ctype or "schemas-microsoft-com:office:word" in doc[:2000]):
                return self.parse_export(doc)
            # eksport o'rniga oddiy sahifa qaytdi: natija yo'q bo'lsa - bo'sh ro'yxat, aks holda qayta urinish
            if status == 200 and self.parse_count(doc) == 0:
                return []
        raise RuntimeError(f"eksport ishlamadi: {url}")

    def count(self, section: str, params: dict) -> Optional[int]:
        _, _, page = self.http.request(self.url(section, params))
        return self.parse_count(page)

    def okoz_tree(self) -> List[Tuple[int, str]]:
        _, _, t = self.http.request(f"{LEX}/uz/ajax_methods_url?action=GetOkozTree&ucId=okoz_1",
                                    headers={"X-Requested-With": "XMLHttpRequest"})
        return [(int(m.group(1)), html.unescape(m.group(2)).strip()) for m in re.finditer(
            r'<div class="stm_item lvl_\d" id="okoz_1_(\d+)"><div class="stm_hdr">.*?<label for="[^"]+">([^<]+)</label>', t)]


# --------------------------------------------------------------------------------------------------------------
class Kesh:
    """Hujjat HTML'lari uchun disk keshi (gzip). Amaldagilik holati har safar qidiruvdan yangidan olinadi."""

    def __init__(self, folder: Path, max_age_days: float, disabled: bool):
        self.folder = folder
        self.max_age = max_age_days * 86400
        self.disabled = disabled
        (folder / "docs").mkdir(parents=True, exist_ok=True)

    def _path(self, doc_id: str) -> Path:
        return self.folder / "docs" / f"{doc_id}.html.gz"

    def get(self, doc_id: str) -> Optional[str]:
        p = self._path(doc_id)
        if self.disabled or not p.exists() or time.time() - p.stat().st_mtime > self.max_age:
            return None
        try:
            return gzip.decompress(p.read_bytes()).decode("utf-8")
        except Exception:
            return None

    def put(self, doc_id: str, text: str) -> None:
        tmp = self._path(doc_id).with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(text.encode("utf-8"), 6))
        tmp.replace(self._path(doc_id))


# --------------------------------------------------------------------------------------------------------------
_EL_START = re.compile(r'<div class="([A-Z][A-Z0-9_]*)((?:\s+[\w-]+)*)"([^>]*)>')
_ART_RE = re.compile(r"^(\d+(?:[-–^]\d+)?)\s*[-–]?\s*(?:modda|модда)\b", re.IGNORECASE)
_ART_RU_RE = re.compile(r"^стать[яи]\s+(\d+(?:[-–^]\d+)?|[IVXLC]+)\b", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"^(\d+)(?:\.\d+)*\.\s")
_ANNEX_RE = re.compile(r"(\d+)\s*[-–]?\s*(?:son\s+)?(?:ilova|илова)|(?:приложение|прил\.)\s*(?:№|N)?\s*(\d+)", re.IGNORECASE)


def parse_document(page: str) -> dict:
    """Hujjat sahifasidan sarlavha ma'lumotlari va matn elementlari (rol, id, matn)."""
    info = {"kind": "", "effective": "", "repealed": False, "warning": "", "pdf_only": False, "links": {}, "elements": []}
    m = re.search(r'<div class="docHeader__item-label">(.*?)</div>', page, re.S)
    if m:
        info["kind"] = strip_tags(m.group(1))
    m = re.search(r"(?:Kuchga kirish sanasi|Кучга кириш санаси|Дата вступления в силу)\s*</div>\s*"
                  r'<div class="docHeader__item-value[^"]*"[^>]*>([^<]+)<', page)
    if m:
        info["effective"] = parse_dmy(m.group(1))
    # Lex.uz kuchini yo'qotgan / amalda bo'lmagan hujjat ustiga ogohlantirish chiqaradi:
    # <div class="act_warning"> Hujjat kuchini yo'qotgan 01.07.2025 </div>
    warn = " ".join(strip_tags(w) for w in re.findall(r'<div class="act_warning">(.*?)</div>', page, re.S))
    info["warning"] = warn
    if re.search(r"kuchini\s+yo[ʻ'`’‘ʼ]?qotgan|кучини\s+йўқотган|утратил\w*\s+силу|amalda\s+emas|кучга\s+кирмаган|"
                 r"kuchga\s+kirmagan|не\s+вступ", warn, re.IGNORECASE):
        info["repealed"] = True
    for mm in re.finditer(r"""<div[^>]*onclick="openUrl\('((?:/[a-z]{2})?/docs/(-?\d+))'\)"[^>]*title="([^"]+)\"""", page):
        label = mm.group(3).lower()
        key = ("ru" if "русск" in label else "en" if "english" in label else
               "uz_cyrl" if "ўзбекча" in label else "uz_latn" if "zbekcha" in label else None)
        if key:
            info["links"][key] = mm.group(2)

    starts = list(_EL_START.finditer(page))
    if not starts:
        return info
    end = len(page)
    for marker in ('<div class="lx_revive_adserver"', "</main>", "<footer"):
        pos = page.find(marker, starts[-1].start())
        if pos != -1:
            end = min(end, pos)
    for i, m in enumerate(starts):
        seg_end = starts[i + 1].start() if i + 1 < len(starts) else end
        seg = page[m.end():seg_end]
        role = m.group(1)
        hidden = "lx_no_select" in m.group(2) or "display:none" in m.group(3)
        eid = re.search(r"lx_mo\(event,\s*(-?\d+)\)", m.group(3))
        if not eid:
            eid = re.search(r'<div name="(-?\d+)" id="-?\d+"', seg)
        seg = re.sub(r'<div class="lx_elem2">.*?</div>\s*</div>', " ", seg, count=1, flags=re.S)
        info["elements"].append({"role": role, "hidden": hidden, "id": eid.group(1) if eid else "",
                                 "text": strip_tags(seg)})
    body = [e["text"] for e in info["elements"] if not e["hidden"] and e["role"] not in ROLES_SKIP and e["text"]]
    info["pdf_only"] = any(_RX_PDF.search(t) for t in body) and sum(len(t) for t in body) < 3000
    return info


def heading_label(text: str) -> str:
    """'1-bob. Umumiy qoidalar' -> '1-bob'; 'IV. Ruhiy ...' -> 'IV bo'lim'; aks holda qisqartirilgan sarlavha."""
    m = _ART_RE.match(text) or _ART_RU_RE.match(text)
    if m:
        return f"{m.group(1)}-modda"
    m = re.match(r"^((?:\d+|[IVXLC]+)\s*-\s*(?:bob|bo['ʻʼ‘’]?lim|qism|paragraf|глава|раздел))\b", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    m = re.match(r"^([IVXLC]+|\d+)\.\s", text)
    if m:
        return f"{m.group(1)} bo'lim"
    m = re.match(r"^(?:глава|раздел)\s+(\d+|[IVXLC]+)", text, re.IGNORECASE)
    if m:
        return m.group(0)
    return text[:40].rsplit(" ", 1)[0] + "…" if len(text) > 40 else text


def analyse(info: dict, til: str) -> dict:
    """Element-ba-element tahlil: qaysi modda/bandlarda nogironlikka oid atama bor."""
    annex = chapter = ""
    article = clause = ""
    unit_repealed = False
    weak_ctx_annex = weak_ctx_unit = False
    last_id = ""
    units: "OrderedDict[str, dict]" = OrderedDict()
    title_hit = False

    for el in info["elements"]:
        role, text = el["role"], el["text"]
        if el["id"]:
            last_id = el["id"]
        if el["hidden"] or role in ROLES_SKIP or not text:
            continue
        low = norm_latin(text) if til != "ru" else text.lower()

        if role in ROLES_ANNEX:
            am = _ANNEX_RE.search(text)
            annex = f"{am.group(1) or am.group(2)}-ilova" if am else "Ilova"
            chapter, article, clause = "", "", ""
            unit_repealed = weak_ctx_unit = False
            weak_ctx_annex = bool(_RX_BEKOR_ROYXAT.search(low))
        elif role in ROLES_ANNEX_TITLE:
            if not annex:
                annex = "Ilova"
            weak_ctx_annex = weak_ctx_annex or bool(_RX_BEKOR_ROYXAT.search(low))
        elif role == "TEXT_HEADER_DEFAULT":
            chapter, article, clause = heading_label(text), "", ""
            unit_repealed = weak_ctx_unit = False
        elif role == "CLAUSE_DEFAULT":
            am = _ART_RE.match(text) or _ART_RU_RE.match(text)
            article = f"{am.group(1)}-modda" if am else text[:40]
            clause = ""
            unit_repealed = bool(_RX_KUCHSIZ.match(low)) and len(text) < 200
            weak_ctx_unit = bool(_RX_BEKOR_ROYXAT.search(low))
        elif role not in ("ACT_TITLE",):
            cm = _CLAUSE_RE.match(text)
            if cm and not article:
                clause = f"{cm.group(1)}-band"
                unit_repealed = bool(_RX_KUCHSIZ.match(low)) and len(text) < 200
                weak_ctx_unit = bool(_RX_BEKOR_ROYXAT.search(low))
            elif len(text) < 200 and _RX_KUCHSIZ.match(low):
                unit_repealed = True

        hits = find_terms(text, til)
        if not hits:
            continue
        if role == "ACT_TITLE" and not annex:
            # "... qarorini o'z kuchini yo'qotgan deb topish to'g'risida" - nomidagi atama hisobga olinmaydi
            title_hit = title_hit or not _RX_BEKOR_ROYXAT.search(low)
            label = "Hujjat nomi"
        else:
            if unit_repealed:
                continue
            label = ", ".join(x for x in (annex, article or clause or chapter) if x) or "Kirish qismi"
        weak = bool(weak_ctx_annex or weak_ctx_unit or _RX_BEKOR_ROYXAT.search(low))
        u = units.get(label)
        if u is None:
            lab, s, e = hits[0]
            src = norm_latin(text) if til != "ru" else re.sub(r"\s+", " ", text)
            snippet = src[max(0, s - 90):e + 90].strip()
            units[label] = u = {"label": label, "id": el["id"] or last_id, "terms": set(), "weak": True,
                                "snippet": ("…" if s > 90 else "") + snippet + ("…" if e + 90 < len(src) else "")}
        u["terms"].update(h[0] for h in hits)
        u["weak"] = u["weak"] and weak
    return {"units": list(units.values()), "title_hit": title_hit}


def classify_level(sections: set, kind: str, title: str) -> str:
    # lotin qoidalari uchun - lotinlashtirilgan, ruscha qoidalar uchun - asl (kirill) ko'rinish
    k, t = norm_latin(kind) + " | " + (kind or "").lower(), norm_latin(title)
    national = re.search(r"\bqonuni\b|prezident|vazirlar mahkamasi|\bзакон\b|президент|кабинета министров", k)
    if "int" in sections and not national:
        return "xalqaro"
    if "tech" in sections and not national:
        return "texnik"
    if "loc" in sections and not national:
        return "mahalliy"
    if "oliy" in sections and not national or re.search(
            r"oliy majlis|senat|qonunchilik palatasi|олий мажлис|сенат|законодательной палат", k):
        return "oliy_majlis"
    if (re.search(r"konstitutsiyasi\b|конституция", k) and not re.search(r"sud|суд", k)) or \
            re.match(r"^(?:o'zbekiston respublikasi(?:ning)? )?konstitutsiyasi$", t):
        return "konstitutsiya"
    if re.search(r"\bkodeksi\b|кодекс", k) or (re.match(r"^(?:o'zbekiston respublikasining )?\w+ kodeksi$", t)):
        return "kodeks"
    if re.search(r"plenum|oliy sudi|konstitutsiyaviy sud|oliy xo'jalik sudi|пленум|верховного суда|конституционного суда", k):
        return "sud"
    if re.search(r"prezident|президент", k):
        if re.search(r"farmoni|указ", k):
            return "farmon"
        if re.search(r"farmoyishi|распоряжение", k):
            return "prezident_farmoyish"
        return "pq"
    if re.search(r"vazirlar mahkamasi|кабинета министров", k):
        return "vm_farmoyish" if re.search(r"farmoyishi|распоряжение", k) else "vmq"
    if re.search(r"hokim|xalq deputatlari|хоким|народных депутатов", k):
        return "mahalliy"
    if re.search(r"\bqonuni\b|konstitutsiyaviy qonun|\bзакон\b", k):
        return "qonun"
    if re.search(r"ro'yxat raqami|ro'yxatdan o'tgan|vazir|qo'mita|agentlig|markaziy bank|inspeksiya|xizmati|komissiya|"
                 r"зарегистрирован|министр|комитет|агентств|центрального банка|комисси", k):
        return "idoraviy"
    return "boshqa"


# --------------------------------------------------------------------------------------------------------------
def doc_url(doc_id: str, til: str) -> str:
    return f"{LEX}/{'ru' if til == 'ru' else 'uz'}/docs/{doc_id}"


def flip_id(doc_id: str) -> str:
    """Lex.uz'da o'zbekcha lotin va kirill nashrlari bir xil raqamli, ishorasi qarama-qarshi id'ga ega (-N <-> N)."""
    return doc_id[1:] if doc_id.startswith("-") else "-" + doc_id


def merge_key(number: str, d: str) -> Optional[Tuple[str, str]]:
    digits = re.sub(r"\D", "", number or "")
    return (digits, d) if digits and d else None


def run_search(args, http: Http) -> Tuple[Dict[str, dict], List[dict], List[str]]:
    lex = LexSearch(http)
    sections = [s.strip() for s in args.bolimlar.split(",") if s.strip() in BOLIMLAR]
    langs = [l for l in ("4", "3", "1") if not (l == "1" and args.rus_emas)]

    # OKOZ bo'limlarini klassifikator daraxtidan kod bo'yicha aniqlash
    okoz: List[Tuple[int, str]] = []
    try:
        tree = lex.okoz_tree()
        wanted = set(OKOZ_KODLAR)
        for node_id, name in tree:
            code = name.split(" ", 1)[0]
            if code in wanted or ("nogiron" in norm_latin(name) and "kuchini yo'qotgan" not in norm_latin(name)
                                  and "кучини" not in name.lower()):
                okoz.append((node_id, name))
        missing = wanted - {n.split(" ", 1)[0] for _, n in okoz}
        if missing:
            log(f"OGOHLANTIRISH: klassifikatorda topilmagan kodlar: {', '.join(sorted(missing))}")
        log(f"OKOZ: nogironlikka oid {len(okoz)} ta bo'lim aniqlandi")
    except Exception as e:
        log(f"OGOHLANTIRISH: OKOZ daraxtini olib bo'lmadi ({e}) - klassifikator kanali o'tkazib yuboriladi")

    channels = []   # (nom, section, params, til)
    for sec in sections:
        for lang in langs:
            for q in QUERIES[lang]:
                qq = to_lex_spelling(q) if lang == "4" else q
                channels.append((f"matn: «{q}»", sec, {"query": qq, "status": "Y", "lang": lang}, lang))
    if "nat" in sections:
        for node_id, name in okoz:
            for lang in langs:
                channels.append((f"OKOZ {name[:70]}", "nat", {"okoz": str(node_id), "status": "Y", "lang": lang}, lang))

    log(f"QIDIRUV: {len(channels)} ta kanal (bo'limlar: {', '.join(sections)}; tillar: "
        f"{', '.join(LANG_NOMI[l] for l in langs)})")
    cands: Dict[str, dict] = {}
    amending: set = set()
    normative: set = set()
    stats: List[dict] = []
    errors: List[str] = []
    lock = threading.Lock()

    def do_channel(ch):
        name, sec, params, lang = ch
        rows = lex.export(sec, params)
        tags = {}
        if rows:
            tags["minor"] = {r["id"] for r in lex.export(sec, {**params, "minor": "Y"})}
            if sec in NATURE_BOLIMLAR:
                tags["nature"] = {r["id"] for r in lex.export(sec, {**params, "nature": "1"})}
        return ch, rows, tags

    done = 0
    with ThreadPoolExecutor(max_workers=args.ishchilar) as pool:
        futs = [pool.submit(do_channel, ch) for ch in channels]
        for fut in as_completed(futs):
            done += 1
            try:
                (name, sec, params, lang), rows, tags = fut.result()
            except Exception as e:
                errors.append(str(e))
                continue
            til = "ru" if lang == "1" else "uz"
            with lock:
                stats.append({"kanal": name, "bolim": sec, "til": LANG_NOMI[lang], "topildi": len(rows)})
                for r in rows:
                    c = cands.get(r["id"])
                    if c is None:
                        c = cands[r["id"]] = {**r, "til": til, "lang": lang, "bolimlar": set(), "kanallar": set()}
                    c["bolimlar"].add(sec)
                    c["kanallar"].add(name)
                amending |= tags.get("minor", set())
                if sec in NATURE_BOLIMLAR:
                    normative |= tags.get("nature", set())
                else:
                    normative |= {r["id"] for r in rows}
            if done % 40 == 0 or done == len(channels):
                log(f"  qidiruv: {done}/{len(channels)} kanal, nomzodlar: {len(cands)}")

    # To'liqlik nazorati: asosiy kanallarda eksport soni sahifadagi "N hujjat topildi" bilan solishtiriladi
    checks = []
    for q in ("nogiron", "nogironlik"):
        if "nat" not in sections:
            break
        params = {"query": q, "status": "Y", "lang": "4"}
        try:
            n_page = lex.count("nat", params)
            n_exp = next((s["topildi"] for s in stats if s["kanal"] == f"matn: «{q}»" and s["bolim"] == "nat"
                          and s["til"] == LANG_NOMI["4"]), None)
            ok = n_page is not None and n_page == n_exp
            checks.append(f"«{q}» (milliy qonunchilik): sahifada {n_page}, eksportda {n_exp} - {'mos' if ok else 'MOS EMAS'}")
            if not ok:
                errors.append(f"to'liqlik nazorati: «{q}» sahifada {n_page}, eksportda {n_exp}")
        except Exception as e:
            errors.append(f"to'liqlik nazorati bajarilmadi: {e}")

    for c in cands.values():
        c["amending"] = c["id"] in amending
        c["normative"] = c["id"] in normative

    # Tillar bo'yicha birlashtirish: kirill/rus nashrlari lotin nashri bilan bir xil bo'lsa - takror
    latin_ids = {i for i, c in cands.items() if c["lang"] == "4"}
    latin_keys = {}
    for i in latin_ids:
        k = merge_key(cands[i]["number"], cands[i]["date"])
        if k:
            latin_keys.setdefault(k, i)
    for i, c in list(cands.items()):
        if c["lang"] == "4":
            continue
        twin = flip_id(i) if c["lang"] == "3" else None
        k = merge_key(c["number"], c["date"])
        target = twin if twin in latin_ids else latin_keys.get(k) if k else None
        if target and target in cands:
            cands[target]["kanallar"] |= c["kanallar"]
            cands[target]["bolimlar"] |= c["bolimlar"]
            del cands[i]
    stats.sort(key=lambda s: (list(BOLIMLAR).index(s["bolim"]), s["til"], s["kanal"]))
    log(f"QIDIRUV tugadi: tillar bo'yicha birlashtirilgandan keyin {len(cands)} ta noyob nomzod hujjat")
    return cands, stats, errors + [f"[nazorat] {c}" for c in checks]


def verify(args, http: Http, kesh: Kesh, cands: Dict[str, dict]) -> None:
    today = date.today().isoformat()
    items = list(cands.values())
    if args.sinov:
        items = items[: args.sinov]
        keep = {c["id"] for c in items}
        for i in list(cands):
            if i not in keep:
                del cands[i]
    log(f"TEKSHIRUV: {len(items)} ta hujjat matni moddama-modda tekshiriladi ({args.ishchilar} ta parallel ishchi)")

    def fetch(c: dict) -> Optional[str]:
        page = kesh.get(c["id"])
        if page is None:
            status, _, page = http.request(f"{LEX}/uz/docs/{c['id']}")
            if status == 404:
                return None
            if "lx_elem" not in page and "docHeader" not in page:
                # texnik ishlar / cheklov sahifasi - "matni yo'q" deb emas, xato deb hisoblanadi
                raise RuntimeError(f"Lex.uz kutilmagan sahifa qaytardi (HTTP {status})")
            kesh.put(c["id"], page)
        return page

    def work(c: dict) -> None:
        page = fetch(c)
        if page is None:
            c["holat"] = "topilmadi"
            return
        info = parse_document(page)
        c["kind"] = info["kind"]
        c["effective"] = c.get("effective") or info["effective"]
        c["links"] = info["links"]
        c["level"] = classify_level(c["bolimlar"], info["kind"], c["title"])
        title_terms = [] if _RX_BEKOR_ROYXAT.search(norm_latin(c["title"]) if c["til"] != "ru" else c["title"].lower()) \
            else find_terms(c["title"], c["til"])
        if info["repealed"]:
            c["holat"] = "kuchini_yoqotgan"
            c["xato"] = info["warning"]
            return
        if not info["elements"] or info["pdf_only"]:
            # matnni tekshirib bo'lmaydi: nomida aniq atama bo'lsa - asosiy ro'yxatga (belgi bilan), aks holda - qo'lda
            c["units"] = []
            c["title_hit"] = bool(title_terms)
            c["pdf"] = True
            if c["title_hit"]:
                c["holat"], c["toifa"] = "tasdiqlandi", "asosiy"
            else:
                c["holat"] = "matn_yoq"
            return
        res = analyse(info, c["til"])
        c["units"] = res["units"]
        c["title_hit"] = res["title_hit"] or bool(title_terms)
        strong = [u for u in res["units"] if not u["weak"] and u["label"] != "Hujjat nomi"]
        if not strong and not c["title_hit"]:
            c["holat"] = "faqat_bekor_qilish" if res["units"] else "mos_emas"
            return
        c["holat"] = "tasdiqlandi"
        c["toifa"] = "asosiy" if c["title_hit"] else ("muhim" if len(strong) >= 3 else "qisman")
        if c.get("effective") and c["effective"] > today:
            c["holat"] = "kuchga_kirmagan"

    done = 0
    with ThreadPoolExecutor(max_workers=args.ishchilar) as pool:
        futs = {pool.submit(work, c): c for c in items}
        for fut in as_completed(futs):
            done += 1
            c = futs[fut]
            try:
                fut.result()
            except Exception as e:
                c["holat"] = "xato"
                c["xato"] = str(e)[:300]
            if done % 50 == 0 or done == len(items):
                hol = Counter(x.get("holat", "?") for x in items)
                log(f"  tekshiruv: {done}/{len(items)} - tasdiqlandi {hol['tasdiqlandi']}, mos emas {hol['mos_emas']}, "
                    f"xato {hol['xato']}")

    # Rus/kirill nashri o'zbek lotin nashri bilan bir hujjat bo'lsa (til havolalari orqali) - takrorni olib tashlash
    latin_ids = {i for i, c in cands.items() if c["lang"] == "4"}
    for i, c in list(cands.items()):
        if c["lang"] != "4":
            links = c.get("links") or {}
            twins = [t for x in (links.get("uz_latn"), links.get("uz_cyrl")) if x for t in (x, flip_id(x))]
            twin = next((t for t in twins if t in latin_ids and t != i), None)
            if twin:
                cands[twin]["kanallar"] |= c["kanallar"]
                del cands[i]


# --------------------------------------------------------------------------------------------------------------
def md_escape(text: str) -> str:
    return (text or "").replace("|", "/").replace("\n", " ").replace("[", "(").replace("]", ")")


def rekvizit(c: dict) -> str:
    parts = [md_escape(c.get("number") or "")]
    if c.get("date"):
        parts.append(iso_to_dmy(c["date"]))
    return ", ".join(p for p in parts if p) or "-"


def unit_links(c: dict, limit: int) -> str:
    units = [u for u in c.get("units", []) if not u["weak"] and u["label"] != "Hujjat nomi"]
    if not units:
        if c.get("pdf"):
            return "matni PDF'da — nomi bo'yicha"
        return "hujjat nomida" if c.get("title_hit") else "-"
    base = doc_url(c["id"], c["til"])
    out = [f"[{md_escape(u['label'])}]({base}#{u['id']})" if u["id"] else md_escape(u["label"]) for u in units[:limit]]
    if len(units) > limit:
        out.append(f"… (+{len(units) - limit})")
    return f"**{len(units)}**: " + ", ".join(out)


def title_link(c: dict) -> str:
    t = md_escape(c["title"]) or "(nomsiz)"
    s = f"[{t}]({doc_url(c['id'], c['til'])})"
    if c["til"] == "ru":
        uz = (c.get("links") or {}).get("uz_latn") or (c.get("links") or {}).get("uz_cyrl")
        s += " _(rus tilida tekshirildi" + (f"; [o'zbekcha]({LEX}/uz/docs/{uz})" if uz else "") + ")_"
    return s


def sort_key(c: dict):
    return (TOIFA_TARTIB.get(c.get("toifa"), 3), -int((c.get("date") or "0").replace("-", "") or 0), c["title"])


def write_report(args, cands: Dict[str, dict], stats: List[dict], errors: List[str], started: datetime,
                 http: Http) -> None:
    out_md = Path(args.chiqish).resolve()
    out_json = out_md.with_suffix(".json")
    all_c = list(cands.values())
    ok = [c for c in all_c if c.get("holat") == "tasdiqlandi"]
    main = [c for c in ok if c["normative"] and not c["amending"]]
    amend = [c for c in ok if c["amending"]]
    operative = [c for c in ok if not c["normative"] and not c["amending"]]
    pending = [c for c in all_c if c.get("holat") == "kuchga_kirmagan"]
    manual = [c for c in all_c if c.get("holat") in ("matn_yoq", "xato", "topilmadi")]
    hol = Counter(c.get("holat", "tekshirilmagan") for c in all_c)

    prev_ids = set()
    if out_json.exists():
        try:
            prev = json.loads(out_json.read_text(encoding="utf-8"))
            prev_ids = {d["id"] for d in prev.get("hujjatlar", [])}
        except Exception:
            prev_ids = set()
    cur_ids = {c["id"] for c in main}
    added = [c for c in main if prev_ids and c["id"] not in prev_ids]
    removed = sorted(prev_ids - cur_ids) if prev_ids else []

    by_level: Dict[str, List[dict]] = OrderedDict((k, []) for k in DARAJALAR)
    for c in main:
        by_level.setdefault(c.get("level", "boshqa"), []).append(c)
    for lst in by_level.values():
        lst.sort(key=sort_key)
    toifa = Counter(c["toifa"] for c in main)
    L: List[str] = []
    L += [
        "# Nogironligi bo'lgan shaxslarning huquqlariga oid amaldagi hujjatlar (Lex.uz)",
        "",
        f"_Avtomatik yaratildi: {started:%Y-%m-%d %H:%M} · dastur: `havola_new.py` · manba: rasmiy [Lex.uz]({LEX}) · "
        f"Lex.uz'ga {http.count} ta so'rov, {(datetime.now() - started).seconds // 60} daqiqa. "
        "Qo'lda tahrirlamang — dasturni qayta ishga tushiring._",
        "",
        "## Qisqacha",
        "",
        f"- **Asosiy ro'yxat: {len(main)} ta amaldagi hujjat** — 🟢 asosiy (nomidan nogironlikka bag'ishlangan) "
        f"{toifa['asosiy']}, 🟡 muhim (3 va undan ortiq modda/band) {toifa['muhim']}, "
        f"⚪ qisman (1–2 modda/band) {toifa['qisman']}.",
        f"- O'zgartirish va qo'shimchalar kirituvchi amaldagi hujjatlar: {len(amend)}; "
        f"normativ bo'lmagan (operativ) hujjatlar: {len(operative)}; kuchga kirishi kutilayotganlar: {len(pending)}.",
        f"- Tekshirilgan nomzodlar: {len(all_c)} (qidiruv kanallari: {len(stats)}). Matnida nogironlikka oid amaldagi "
        f"norma topilmagani uchun chiqarilganlar: {hol['mos_emas']}; faqat bekor qilish ro'yxatida tilga olinganlar: "
        f"{hol['faqat_bekor_qilish']}; sahifasida kuchini yo'qotgan deb ko'rsatilganlar: {hol['kuchini_yoqotgan']}.",
        f"- Qo'lda tekshirish tavsiya etiladi: {len(manual)} ta (matni HTML'da yo'q yoki yuklab bo'lmadi).",
    ]
    if prev_ids:
        L.append(f"- Oldingi ishga tushirishga nisbatan: **+{len(added)}** yangi, **−{len(removed)}** ro'yxatdan chiqqan.")
    real_errors = [e for e in errors if not e.startswith("[nazorat]")]
    if real_errors:
        L.append(f"- ⚠️ **{len(real_errors)} ta qidiruv/tekshiruv xatosi bo'ldi — to'liqlik kafolatlanmaydi, dasturni "
                 "qayta ishga tushiring** (pastdagi \"Nazorat\" bo'limiga qarang).")
    L += [
        "",
        "Har bir hujjat uchun «Tegishli qismlar» ustunida nogironlikka oid atama uchragan **amaldagi** modda/bandlarga "
        "Lex.uz'dagi aniq joyiga to'g'ridan-to'g'ri havolalar berilgan (raqam — shunday qismlar soni).",
        "",
        "## Mundarija",
        "",
    ]
    n = 0
    for key, name in DARAJALAR.items():
        if by_level.get(key):
            n += 1
            L.append(f"{n}. [{name}](#{n}-{slug(name)}) — {len(by_level[key])}")
    extra = [("Kuchga kirishi kutilayotgan hujjatlar", pending), ("O'zgartirish va qo'shimchalar kirituvchi hujjatlar", amend),
             ("Normativ bo'lmagan (operativ) hujjatlar", operative), ("Qo'lda tekshirish tavsiya etiladi", manual)]
    for name, lst in extra:
        if lst:
            n += 1
            L.append(f"{n}. [{name}](#{n}-{slug(name)}) — {len(lst)}")
    n += 1
    L.append(f"{n}. [Usul va nazorat](#{n}-usul-va-nazorat)")
    L.append("")

    n = 0
    for key, name in DARAJALAR.items():
        lst = by_level.get(key) or []
        if not lst:
            continue
        n += 1
        L += [f"## {n}. {name}", "", "| № | Rekvizit | Hujjat nomi | Bog'liqlik | Tegishli qismlar |", "|---:|---|---|---|---|"]
        for i, c in enumerate(lst, 1):
            L.append(f"| {i} | {rekvizit(c)} | {title_link(c)} | {TOIFA_BELGI[c['toifa']]} | {unit_links(c, args.qismlar)} |")
        L.append("")

    def compact(name: str, lst: List[dict], note: str, show_units: bool = True):
        nonlocal n
        if not lst:
            return
        n += 1
        L.extend([f"## {n}. {name}", "", note, "", "| № | Rekvizit | Hujjat nomi | Turi | Tegishli qismlar |", "|---:|---|---|---|---|"])
        for i, c in enumerate(sorted(lst, key=lambda x: x.get("date") or "", reverse=True), 1):
            parts = unit_links(c, 6) if show_units else md_escape(c.get("xato") or {"matn_yoq": "matni HTML'da yo'q",
                                                                                   "topilmadi": "sahifa topilmadi"}.get(c.get("holat"), ""))
            L.append(f"| {i} | {rekvizit(c)} | {title_link(c)} | {DARAJALAR.get(c.get('level', 'boshqa'), '-')} | {parts} |")
        L.append("")

    compact("Kuchga kirishi kutilayotgan hujjatlar", pending,
            "Lex.uz'da amaldagi deb belgilangan, lekin kuchga kirish sanasi hali kelmagan hujjatlar.")
    compact("O'zgartirish va qo'shimchalar kirituvchi hujjatlar", amend,
            "Bu hujjatlar boshqa hujjatlarga o'zgartirish kiritgan; ularning normalari asosiy hujjatlar matniga allaqachon "
            "kiritilgan, shuning uchun asosiy ro'yxatdan ajratildi.")
    compact("Normativ bo'lmagan (operativ) hujjatlar", operative,
            "Lex.uz'da \"operativ va boshqalar\" deb belgilangan (masalan, majlis kun tartibi, tadbirlar rejasi).")
    compact("Qo'lda tekshirish tavsiya etiladi", manual,
            "Qidiruvda topilgan, lekin matnini avtomatik tekshirib bo'lmagan hujjatlar (masalan, faqat PDF/skaner ko'rinishida).",
            show_units=False)

    n += 1
    L += [f"## {n}. Usul va nazorat", "",
          "1. **Qidiruv (to'liqlik).** Lex.uz qidiruvi faqat amaldagi (`status=Y`) hujjatlar bo'yicha: matn ichidan "
          "o'zbekcha (lotin, kirill) va ruscha atamalar hamda rasmiy klassifikator (OKOZ) ning nogironlikka oid bo'limlari. "
          "Har bir natijalar ro'yxati Lex.uz'ning «Word ga eksport» funksiyasi orqali to'liq olinadi.",
          "2. **Tekshiruv (aniqlik).** Har bir nomzodning to'liq matni moddama-modda tekshirildi; klassifikator izohlari, "
          "o'zgartirish izohlari va LexUZ sharhlari, kuchini yo'qotgan qismlar, bekor qilinayotgan hujjatlar ro'yxatlari "
          "hisobga olinmadi.",
          "3. **Tasnif.** 🟢 asosiy — hujjat nomida nogironlikka oid atama bor; 🟡 muhim — 3 va undan ortiq amaldagi "
          "modda/bandda; ⚪ qisman — 1–2 modda/bandda.",
          "",
          "Matnda izlangan atamalar: " + "; ".join(f"`{lab}`" for lab, _ in ATAMALAR_UZ) + " (ruscha nashrlarda: "
          + "; ".join(f"`{lab}`" for lab, _ in ATAMALAR_RU) + ").",
          ""]
    if errors:
        L += ["**Nazorat va xatolar:**", ""] + [f"- {md_escape(e)}" for e in errors[:60]] + [""]
    if removed:
        L += ["**Oldingi ishga tushirishdan keyin ro'yxatdan chiqqan hujjatlar** (kuchini yo'qotgan yoki o'zgargan): "
              + ", ".join(f"[{i}]({LEX}/uz/docs/{i})" for i in removed[:200]), ""]
    if added and len(added) < len(main):
        L += ["**Yangi qo'shilganlar:** " + "; ".join(title_link(c) for c in added[:100]), ""]
    L += ["<details><summary>Qidiruv kanallari bo'yicha natijalar</summary>", "",
          "| Kanal | Bo'lim | Til | Topildi |", "|---|---|---|---:|"]
    for s in stats:
        if s["topildi"]:
            L.append(f"| {md_escape(s['kanal'])} | {BOLIMLAR[s['bolim']]} | {s['til']} | {s['topildi']} |")
    L += ["", "</details>", ""]
    out_md.write_text("\n".join(L), encoding="utf-8")

    def ser(c: dict) -> dict:
        d = {k: v for k, v in c.items() if k not in ("units",)}
        d["bolimlar"] = sorted(c.get("bolimlar", []))
        d["kanallar"] = sorted(c.get("kanallar", []))
        d["url"] = doc_url(c["id"], c["til"])
        d["daraja"] = DARAJALAR.get(c.get("level", ""), "")
        d["qismlar"] = [{"qism": u["label"], "havola": f"{d['url']}#{u['id']}" if u["id"] else d["url"],
                         "atamalar": sorted(u["terms"]), "faqat_bekor_qilish": u["weak"], "parcha": u["snippet"]}
                        for u in c.get("units", [])]
        return d

    payload = {
        "yaratilgan": started.isoformat(timespec="seconds"),
        "manba": LEX,
        "hujjatlar": [ser(c) for k in DARAJALAR for c in by_level.get(k, [])],
        "kuchga_kirmagan": [ser(c) for c in pending],
        "ozgartiruvchi": [ser(c) for c in amend],
        "operativ": [ser(c) for c in operative],
        "qolda_tekshirish": [ser(c) for c in manual],
        "rad_etilganlar": [ser(c) for c in all_c if c.get("holat") in ("mos_emas", "faqat_bekor_qilish", "kuchini_yoqotgan")],
        "kanallar": stats,
        "xatolar": errors,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=sorted), encoding="utf-8")
    log(f"TAYYOR: {out_md} ({len(main)} ta asosiy hujjat) va {out_json.name}")


def slug(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="Lex.uz'dan nogironlik huquqlariga oid amaldagi hujjatlarni aniqlash",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("Ishga tushirish")[0])
    ap.add_argument("--chiqish", default=str(SCRIPT_DIR / "real_hujjatlar.md"), help="natija fayli (.md); yonida .json ham yoziladi")
    ap.add_argument("--ishchilar", type=int, default=4, help="parallel so'rovlar soni (standart 4)")
    ap.add_argument("--oraliq", type=float, default=0.25, help="Lex.uz'ga so'rovlar orasidagi eng kam vaqt, soniya (standart 0.25)")
    ap.add_argument("--bolimlar", default=",".join(BOLIMLAR), help="qidiruv bo'limlari: " + ", ".join(f"{k}={v}" for k, v in BOLIMLAR.items()))
    ap.add_argument("--rus-emas", action="store_true", help="ruscha nashrlar bo'yicha qidirmaslik")
    ap.add_argument("--kesh", default=str(SCRIPT_DIR / ".havola_kesh"), help="hujjatlar keshi papkasi")
    ap.add_argument("--kesh-kun", type=float, default=7.0, help="keshdagi hujjat matni necha kun yaroqli (standart 7)")
    ap.add_argument("--yangilash", action="store_true", help="keshni e'tiborsiz qoldirib hamma hujjatni qayta yuklash")
    ap.add_argument("--qismlar", type=int, default=12, help="har bir hujjat uchun ko'rsatiladigan modda havolalari soni")
    ap.add_argument("--sinov", type=int, default=0, help=argparse.SUPPRESS)  # faqat birinchi N nomzodni tekshirish
    args = ap.parse_args()

    started = datetime.now()
    http = Http(min_interval=args.oraliq)
    kesh = Kesh(Path(args.kesh), args.kesh_kun, args.yangilash)
    try:
        cands, stats, errors = run_search(args, http)
    except Exception as e:
        log(f"XATO: Lex.uz qidiruvi ishlamadi: {e}")
        return 2
    if not cands:
        log("XATO: hech qanday nomzod topilmadi - Lex.uz javobini tekshiring")
        return 2
    verify(args, http, kesh, cands)
    write_report(args, cands, stats, errors, started, http)
    return 1 if any(not e.startswith("[nazorat]") for e in errors) else 0


if __name__ == "__main__":
    sys.exit(main())
