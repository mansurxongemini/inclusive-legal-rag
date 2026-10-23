import hashlib
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ArticleStatus(str, Enum):
    ACTIVE = "active"
    AMENDED = "amended"
    REPEALED = "repealed"


class RefType(str, Enum):
    IMPLEMENTS = "implements"
    REFERS_TO = "refers_to"
    AMENDS = "amends"
    SUPERSEDES = "supersedes"


class TranslationProvenanceType(str, Enum):
    OFFICIAL = "official"
    MACHINE_TRANSLATED_REVIEWED = "machine_translated_reviewed"
    MACHINE_TRANSLATED_UNREVIEWED = "machine_translated_unreviewed"


class AmendmentRecord(BaseModel):
    amending_law_number: str = Field(..., description="Number of the amending law (e.g. O'RQ-712)")
    date: str = Field(..., description="Date of the amendment (YYYY-MM-DD)")
    summary_of_change: str = Field(..., description="Brief summary of the changes made")


class CrossReference(BaseModel):
    ref_type: RefType = Field(..., description="Relationship type")
    target_canonical_id: str = Field(..., description="Target canonical_id")


class ArticleMetadata(BaseModel):
    law_id: str = Field(..., description="Identifier for law (e.g. law_disability_2020)")
    law_title: Dict[str, str] = Field(..., description="Title of the law in uz, ru, en")
    law_number: str = Field(..., description="Official law number (e.g. O'RQ-641)")
    chapter_number: Optional[str] = Field(default=None, description="Chapter/Bob/Глава")
    article_number: str = Field(..., description="Article number (e.g. 15-modda)")
    article_title: Dict[str, str] = Field(..., description="Article title in uz, ru, en")
    annex_title: Optional[str] = Field(default=None, description="Title of the annex/list this unit is an item of (ilova/ro'yxat sarlavhasi)")
    source_url: str = Field(..., description="Official source URL on lex.uz")
    effective_date: str = Field(..., description="Effective date (YYYY-MM-DD)")
    last_verified_date: str = Field(..., description="Last verification date (YYYY-MM-DD)")
    source_hash: str = Field(..., description="SHA-256 hash of original text content")
    status: ArticleStatus = Field(default=ArticleStatus.ACTIVE, description="Current legal status")
    superseded_by: Optional[str] = Field(default=None, description="canonical_id of superseding article if amended/repealed")
    supersedes: Optional[str] = Field(default=None, description="canonical_id of old article if this is a replacement")
    amendment_history: List[AmendmentRecord] = Field(default_factory=list, description="List of amendments")
    category: str = Field(..., description="Legal domain (social_protection, labor_code, disability_rights)")
    disability_types: List[str] = Field(default_factory=lambda: ["general"], description="Target disability categories")
    beneficiary_type: List[str] = Field(default_factory=lambda: ["individual"], description="Beneficiary roles")
    cross_references: List[CrossReference] = Field(default_factory=list, description="Cross references to other articles/laws")
    embedding_model_version: str = Field(default="bge-m3-2025-11-18", description="Embedding model version used")
    # Source type: "lex" = official Lex.uz norm, "curated" = editorial curated answer projection,
    # "huquqplus" = Huquq+ portal commentary (never a substitute for statutory text).
    source_type: str = Field(default="lex", description='Source type: "lex" | "curated" | "huquqplus"')
    published_url: Optional[str] = Field(default=None, description="Public URL of the curated answer, if any")
    # Provenance (optional: older records do not carry them)
    promulgation_date: Optional[str] = Field(default=None, description="Adoption date of the act (YYYY-MM-DD)")
    document_type: Optional[str] = Field(default=None, description="Qonun | Kodeks | Farmon | PQ | VMQ | Buyruq | ...")
    issuing_body: Optional[str] = Field(default=None, description="Adopting authority as printed by Lex.uz")
    source_element_id: Optional[str] = Field(default=None, description="Lex.uz element id for deep links (#id)")
    source_element_ids: List[str] = Field(
        default_factory=list,
        description="All Lex.uz element ids of the unit (paragraphs, points) - resolves deep links to inner parts",
    )
    # Lex.uz publishes the Russian edition under its own document and element ids; external sites often link there
    ru_document_id: Optional[str] = Field(default=None, description="Lex.uz id of the Russian edition of the act")
    ru_element_ids: List[str] = Field(default_factory=list, description="Element ids of the aligned Russian unit")


class ArticlePoint(BaseModel):
    point_id: str = Field(..., description="Point or paragraph index, e.g. '1', '2', 'a'")
    text: Dict[str, str] = Field(..., description="Point text in uz, ru, en")


class CanonicalArticle(BaseModel):
    canonical_id: str = Field(..., description="Unique immutable canonical identifier (e.g. law_disability_2020_art_15)")
    schema_version: str = Field(default="1.1", description="Schema version")
    metadata: ArticleMetadata = Field(..., description="Article metadata")
    points: List[ArticlePoint] = Field(default_factory=list, description="Sub-article paragraphs/points for precise citation")
    translations: Dict[str, str] = Field(..., description="Full text in uz, ru, en")
    translation_provenance: Dict[str, TranslationProvenanceType] = Field(
        default_factory=lambda: {
            "uz": TranslationProvenanceType.OFFICIAL,
            "ru": TranslationProvenanceType.OFFICIAL,
            "en": TranslationProvenanceType.MACHINE_TRANSLATED_REVIEWED,
        },
        description="Provenance of each translation"
    )

    @field_validator("canonical_id")
    @classmethod
    def validate_canonical_id(cls, v: str) -> str:
        if not v or " " in v:
            raise ValueError("canonical_id must be non-empty and contain no spaces")
        return v

    def calculate_source_hash(self) -> str:
        """Computes deterministic SHA256 of article text across available languages."""
        hasher = hashlib.sha256()
        for lang in sorted(self.translations.keys()):
            hasher.update(lang.encode("utf-8"))
            hasher.update(self.translations[lang].strip().encode("utf-8"))
        return f"sha256:{hasher.hexdigest()}"

    def get_text(self, language: str = "uz") -> str:
        """Returns text in requested language, falling back to uz or ru."""
        if language in self.translations and self.translations[language].strip():
            return self.translations[language]
        if "uz" in self.translations and self.translations["uz"].strip():
            return self.translations["uz"]
        if "ru" in self.translations and self.translations["ru"].strip():
            return self.translations["ru"]
        return next(iter(self.translations.values()), "")

    def get_title(self, language: str = "uz") -> str:
        """Returns article title in requested language."""
        if language in self.metadata.article_title and self.metadata.article_title[language].strip():
            return self.metadata.article_title[language]
        return self.metadata.article_title.get("uz", "")

    def get_law_title(self, language: str = "uz") -> str:
        """Returns law title in requested language."""
        if language in self.metadata.law_title and self.metadata.law_title[language].strip():
            return self.metadata.law_title[language]
        return self.metadata.law_title.get("uz", "")

    def get_point_text(self, point_id: str, language: str = "uz") -> Optional[str]:
        """Returns specific point text by point_id."""
        for pt in self.points:
            if pt.point_id == str(point_id):
                return pt.text.get(language, pt.text.get("uz", ""))
        return None

    def to_fts_document(self, language: str = "uz") -> str:
        """Formats comprehensive search text for full-text indexing."""
        title = self.get_title(language)
        law_title = self.get_law_title(language)
        body = self.get_text(language)
        points_text = " ".join([pt.text.get(language, "") for pt in self.points])
        annex = self.metadata.annex_title or ""
        chapter = self.metadata.chapter_number or ""
        extra = f"{annex} {chapter}".strip() if chapter not in annex else annex

        return f"{self.metadata.law_number} {self.metadata.article_number} {title} {law_title} {extra} {body} {points_text}".strip()
