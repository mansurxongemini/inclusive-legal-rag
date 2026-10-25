"""
Builds the disability-rights corpus from official Lex.uz documents.

    LexClient (cached HTML) -> LexDocumentParser (units) -> CorpusBuilder.to_articles (CanonicalArticle)
                                                         -> quality report

No legal text is ever written by hand: every article comes from a Lex.uz document whose number/date/title
were read from the document itself, and carries a deep link back to the exact paragraph.
"""
import hashlib
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Dict, List, Optional, Tuple

from src.domain.disability_taxonomy import (
    classify_category,
    detect_disability_groups,
    disability_relevance,
)
from src.ingestion.lex_client import LexClient
from src.ingestion.lex_structured import LexDocument, LexDocumentParser, LexUnit
from src.nlp.transliteration import normalize_apostrophes
from src.schema.canonical import (
    AmendmentRecord,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    CanonicalArticle,
    CrossReference,
    RefType,
    TranslationProvenanceType,
)

logger = logging.getLogger(__name__)


@dataclass
class SourceSpec:
    """One document that belongs in the corpus (a row of data/sources/disability_registry.json)."""
    lex_id: str
    law_id: str = ""
    number: str = ""                # overrides the number read from the page (codes carry none)
    title_hint: str = ""
    tier: int = 1                   # 1 core disability act, 2 related act, 3 general code (filtered)
    include: str = "all"            # all | disability_articles
    category: Optional[str] = None  # force a category for every unit
    notes: str = ""
    # with include=disability_articles, whole chapters kept as well (prefix of the unit's chapter, e.g. "66-bob"):
    # the topic a huge code is needed for (inheritance in the Civil Code) rarely mentions disability
    chapters: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceSpec":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class DocumentReport:
    lex_id: str
    law_id: str
    number: str
    title: str
    doc_type: str
    adopted: Optional[str]
    effective: Optional[str]
    status: str
    units_parsed: int
    units_kept: int
    ru_aligned: int
    chars: int
    warnings: List[str] = field(default_factory=list)
    url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_ID_PREFIX = [
    (re.compile(r"^O'RQ-(.+)$"), "o_rq"),
    (re.compile(r"^PF-(.+)$"), "pf"),
    (re.compile(r"^PQ-(.+)$"), "pq"),
    (re.compile(r"^VMQ-(.+)$"), "vmq"),
]


def slugify(text: str, max_len: int = 48) -> str:
    t = normalize_apostrophes(text or "").lower().replace("'", "")
    t = unicodedata.normalize("NFKD", t)
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t[:max_len].strip("_") or "doc"


def make_law_id(doc: LexDocument, number_override: str = "") -> str:
    number = number_override or doc.number
    if number.startswith("REG-"):
        return f"reg_{slugify(number[4:])}_{(doc.adopted_date or '')[:4]}".strip("_")
    year = (doc.adopted_date or "")[:4]
    for pattern, prefix in _ID_PREFIX:
        m = pattern.match(number)
        if m:
            core = slugify(m.group(1))
            # Act numbers of laws are cumulative; decrees/resolutions restart every year
            return f"{prefix}_{core}" if prefix == "o_rq" else f"{prefix}_{core}_{year}" if year else f"{prefix}_{core}"
    if number and re.search(r"\d", number):
        return f"doc_{slugify(number)}_{year}".strip("_")
    return slugify(doc.title, 40) + (f"_{year}" if year else "")


def _short_label(title: str, limit: int = 60) -> str:
    """Readable stand-in for acts without a number (codes, the Constitution)."""
    t = re.sub(r"^\s*(?:O['ʻʼ’‘]zbekiston Respublikasining|Oʻzbekiston Respublikasi)\s+", "", normalize_apostrophes(title), flags=re.I)
    t = normalize_apostrophes(title) if not t.strip() else t
    t = t.strip()
    return (t[:1].upper() + t[1:])[:limit]


def unit_canonical_id(law_id: str, u: LexUnit) -> str:
    n = u.number.replace("-", "_")
    if u.kind == "preamble":
        return f"{law_id}_preamble"
    if u.kind == "article":
        return f"{law_id}_art_{n}" if not u.annex_number else f"{law_id}_a{u.annex_number}_art_{n}"
    if u.annex_number:
        return f"{law_id}_a{u.annex_number}_p_{n}"
    return f"{law_id}_p_{n}"


def _first_sentence(text: str, limit: int = 110) -> str:
    t = re.sub(r"^\s*\d+(?:-\d+)?[\.\)]\s*", "", text.strip().split("\n", 1)[0])
    if len(t) <= limit:
        return t
    cut = t[:limit]
    return cut[: cut.rfind(" ")] + "…" if " " in cut else cut + "…"


def _unit_key(u: LexUnit) -> Tuple[str, str, str]:
    group = "article" if u.kind == "article" else "clause"
    return (group, u.annex_number or "", u.number)


def _points_from_text(text: str) -> List[ArticlePoint]:
    points: List[ArticlePoint] = []
    for line in text.split("\n"):
        m = re.match(r"^\s*(\d+)[\)\.]\s+(.+)$", line)
        if m:
            points.append(ArticlePoint(point_id=m.group(1), text={"uz": m.group(2).strip()}))
    return points if len(points) >= 2 else []


def _move_russian_overflow(articles: List[CanonicalArticle]) -> None:
    """Russian points glued to the previous point (the Russian edition has no repeal notes) go to their own units."""
    from src.ingestion.translation_alignment import split_russian_overflow
    by_id = {a.canonical_id: a for a in articles}
    changes = split_russian_overflow({cid: (a.get_text("uz"), a.translations.get("ru", "")) for cid, a in by_id.items()})
    for cid, ru in changes.items():
        art = by_id[cid]
        if ru:
            art.translations["ru"] = ru
            art.translation_provenance["ru"] = TranslationProvenanceType.OFFICIAL
        else:
            art.translations.pop("ru", None)


class CorpusBuilder:
    def __init__(self, client: Optional[LexClient] = None, today: Optional[str] = None):
        self.client = client or LexClient()
        self.parser = LexDocumentParser()
        self.today = today or date.today().isoformat()

    # -- loading ----------------------------------------------------------------------------------------
    def load(
        self, spec: SourceSpec, with_russian: bool = True, force: bool = False
    ) -> Tuple[Optional[LexDocument], Optional[LexDocument]]:
        """force=True bypasses the HTML cache (refresh must see the live, possibly amended, text)."""
        html = self.client.fetch_document(spec.lex_id, force=force)
        if html is None:
            logger.warning(f"{spec.lex_id}: not available on lex.uz")
            return None, None
        doc = self.parser.parse(html, spec.lex_id, language="uz")
        ru_doc: Optional[LexDocument] = None
        if with_russian and doc.language_links.get("ru"):
            ru_html = self.client.fetch_url(doc.language_links["ru"], force=force)
            if ru_html:
                ru_doc = self.parser.parse(ru_html, doc.language_links["ru"], language="ru")
        return doc, ru_doc

    # -- conversion -------------------------------------------------------------------------------------
    def to_articles(
        self, doc: LexDocument, spec: SourceSpec, ru_doc: Optional[LexDocument] = None
    ) -> Tuple[List[CanonicalArticle], DocumentReport]:
        number = spec.number or doc.number
        if number.startswith("REG-"):
            number = f"Adliya vazirligi ro'yxat raqami {number[4:]}"
        law_id = spec.law_id or make_law_id(doc, spec.number)
        law_title_uz = normalize_apostrophes(doc.title or spec.title_hint)
        law_title_ru = normalize_apostrophes(ru_doc.title) if ru_doc and ru_doc.title else ""

        # The n-th Uzbek unit with a key is paired with the n-th Russian unit with that key. Annexes that number several
        # lists 1, 2, 3 ... repeat keys; pairing every repeat with the first Russian unit gave point 7 of one list the
        # Russian point 7 of another (284 units, removed 2026-10-25 by scripts/audit_translations.py). When the two
        # editions repeat a key a different number of times the order says nothing, and the repeats get no Russian text.
        ru_units: Dict[Tuple[str, str, str], List[LexUnit]] = {}
        uz_repeats = Counter(_unit_key(u) for u in doc.units)
        ru_doc_id = None
        if ru_doc:
            m_ru = re.search(r"/docs/(-?\d+)", str(ru_doc.doc_id))
            ru_doc_id = m_ru.group(1) if m_ru else (str(ru_doc.doc_id) if str(ru_doc.doc_id).lstrip("-").isdigit() else None)
            for u in ru_doc.units:
                ru_units.setdefault(_unit_key(u), []).append(u)
        occurrence: Dict[Tuple[str, str, str], int] = {}

        # The act's own category (from its title and the official OKOZ nodes); units inherit it unless their
        # own heading/body clearly points elsewhere.
        doc_category = spec.category or classify_category(title=law_title_uz, default="")
        if not doc_category:
            specific = [n for n in doc.okoz if n.startswith("06.10")]
            doc_category = "disability_rights" if specific else classify_category(
                title="", okoz=doc.okoz, default="disability_rights")
        doc_status = ArticleStatus.REPEALED if doc.status == "repealed" else ArticleStatus.ACTIVE
        articles: List[CanonicalArticle] = []
        seen_ids: Dict[str, int] = {}
        ru_aligned = 0
        total_chars = 0

        for unit in doc.units:
            key = _unit_key(unit)
            nth = occurrence.get(key, 0)
            occurrence[key] = nth + 1
            if unit.kind == "preamble" and len(unit.text) < 80:
                continue
            if len(unit.text.strip()) < 3:                       # header-only unit (sub-items are not published)
                continue
            if unit.status == "repealed" and len(unit.text) < 200:   # just "(o'z kuchini yo'qotgan)"
                continue
            cid = unit_canonical_id(law_id, unit)
            if cid in seen_ids:                       # duplicate numbers inside one document
                seen_ids[cid] += 1
                cid = f"{cid}_{seen_ids[cid]}"
            else:
                seen_ids[cid] = 1

            probe = f"{unit.annex_title}\n{unit.chapter}\n{unit.title}\n{unit.text}"
            if spec.include == "disability_articles" and disability_relevance(probe) == 0 \
                    and not any((unit.chapter or "").startswith(c) for c in spec.chapters):
                continue

            candidates = ru_units.get(key) or []
            paired = len(candidates) == uz_repeats[key] or (uz_repeats[key] == 1 and len(candidates) >= 1)
            ru_unit = candidates[nth] if paired and nth < len(candidates) else None
            ru_text = ru_unit.text if ru_unit and ru_unit.text else ""
            if ru_text:
                ru_aligned += 1

            title_uz = normalize_apostrophes(unit.title or _first_sentence(unit.text))
            title_ru = (ru_unit.title or _first_sentence(ru_text)) if ru_unit else ""
            category = spec.category or classify_category(
                title=f"{unit.annex_title} {title_uz}".strip(), text=unit.text, default=doc_category, min_score=6.0
            )
            groups = detect_disability_groups(f"{law_title_uz}\n{unit.annex_title}\n{unit.text}")

            text_for_hash = unit.text.strip()
            source_hash = "sha256:" + hashlib.sha256(text_for_hash.encode("utf-8")).hexdigest()

            amendments: List[AmendmentRecord] = []
            for note in unit.amendments:
                if note.date:
                    amendments.append(AmendmentRecord(
                        amending_law_number=note.amending_act or "Noma'lum",
                        date=note.date,
                        summary_of_change=(note.raw[:300]),
                    ))

            deep_link = f"https://lex.uz/uz/docs/{doc.doc_id}"
            if unit.element_ids:
                deep_link += f"#{unit.element_ids[0]}"

            status = ArticleStatus.REPEALED if (doc_status == ArticleStatus.REPEALED or unit.status == "repealed") \
                else ArticleStatus.ACTIVE

            translations = {"uz": unit.text}
            provenance = {"uz": TranslationProvenanceType.OFFICIAL}
            if ru_text:
                translations["ru"] = ru_text
                provenance["ru"] = TranslationProvenanceType.OFFICIAL

            article_title = {"uz": title_uz}
            if title_ru:
                article_title["ru"] = title_ru
            law_title = {"uz": law_title_uz}
            if law_title_ru:
                law_title["ru"] = law_title_ru

            chap = normalize_apostrophes(unit.chapter or unit.section).strip()
            annex_t = normalize_apostrophes(unit.annex_title).strip()
            if annex_t and chap and annex_t.lower() not in chap.lower():
                chapter_label = f"{annex_t} — {chap}"
            else:
                chapter_label = chap or annex_t or None

            articles.append(CanonicalArticle(
                canonical_id=cid,
                schema_version="1.2",
                metadata=ArticleMetadata(
                    law_id=law_id,
                    law_title=law_title,
                    law_number=number or _short_label(law_title_uz),
                    chapter_number=chapter_label,
                    article_number=unit.display_number,
                    article_title=article_title,
                    annex_title=normalize_apostrophes(unit.annex_title) or None,
                    source_url=deep_link,
                    effective_date=doc.effective_date or doc.adopted_date or self.today,
                    last_verified_date=self.today,
                    source_hash=source_hash,
                    status=status,
                    category=category,
                    disability_types=groups,
                    beneficiary_type=["person_with_disability"],
                    amendment_history=amendments,
                    embedding_model_version="baai/bge-m3",
                    promulgation_date=doc.adopted_date,
                    document_type=doc.doc_type,
                    issuing_body=normalize_apostrophes(doc.body) or None,
                    source_element_id=unit.element_ids[0] if unit.element_ids else None,
                    source_element_ids=list(unit.element_ids),
                    ru_document_id=ru_doc_id,
                    ru_element_ids=list(ru_unit.element_ids) if ru_unit else [],
                ),
                points=_points_from_text(unit.text),
                translations=translations,
                translation_provenance=provenance,
            ))
            total_chars += len(unit.text)

        self._link_references(articles, law_id)
        _move_russian_overflow(articles)

        report = DocumentReport(
            lex_id=doc.doc_id, law_id=law_id, number=number, title=law_title_uz, doc_type=doc.doc_type,
            adopted=doc.adopted_date, effective=doc.effective_date, status=doc.status,
            units_parsed=len(doc.units), units_kept=len(articles), ru_aligned=ru_aligned, chars=total_chars,
            warnings=list(doc.warnings), url=f"https://lex.uz/uz/docs/{doc.doc_id}",
        )
        if articles and ru_doc and ru_aligned == 0:
            report.warnings.append("no_russian_alignment")
        return articles, report

    @staticmethod
    def _link_references(articles: List[CanonicalArticle], law_id: str) -> None:
        """Resolves 'N-modda' mentions that point to another article of the same act."""
        by_number: Dict[str, str] = {}
        for a in articles:
            if a.canonical_id.startswith(f"{law_id}_art_"):
                by_number[a.metadata.article_number.split("-modda")[0]] = a.canonical_id
        for a in articles:
            text = a.translations.get("uz", "")
            refs: Dict[str, CrossReference] = {}
            for m in re.finditer(r"(\d+(?:-\d+)?)\s*-\s*(?:modda|moddasi|moddaning|moddada|moddaga|moddani)", text):
                target = by_number.get(m.group(1))
                if target and target != a.canonical_id and target not in refs:
                    refs[target] = CrossReference(ref_type=RefType.REFERS_TO, target_canonical_id=target)
                if len(refs) >= 6:
                    break
            a.metadata.cross_references = list(refs.values())
