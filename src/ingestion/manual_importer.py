"""
Manual Importer for the Inclusive Legal RAG System.
Allows administrators to upload JSON files or raw legal text directly through the API or Admin Dashboard.
"""
import hashlib
import json
import logging
import re
from datetime import date
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from src.schema.canonical import (
    CanonicalArticle,
    ArticleMetadata,
    ArticlePoint,
    ArticleStatus,
    TranslationProvenanceType,
)
from src.storage.hybrid_store import HybridStore
from src.ingestion.localized import localized, provenance_for
from src.nlp.transliteration import cyrillic_to_latin

logger = logging.getLogger(__name__)


class ManualArticleInput(BaseModel):
    article_number: str = Field(..., description="e.g. '15-modda' or '7-band'")
    title: str = Field(..., description="Title of the article or section")
    text: str = Field(..., description="Body of the norm in Uzbek, Russian, or English")
    law_title: str = Field(..., description="Full official title of the legal act")
    law_number: str = Field(..., description="e.g. 'O'RQ-641' or 'VMQ-864'")
    category: str = Field(default="disability_rights", description="Domain: labor_rights, tmek, tax_benefits, pensions, rehab, accessibility")
    disability_types: List[str] = Field(default_factory=lambda: ["general"], description="group_1, group_2, group_3, childhood_disability, visual, hearing, physical")
    source_url: str = Field(default="https://lex.uz", description="Official Lex.uz URL")


class ManualImportResult(BaseModel):
    success: bool
    imported_count: int
    articles: List[str]
    message: str


class ManualImporter:
    def __init__(self, store: Optional[HybridStore] = None):
        self.store = store or HybridStore()

    async def import_json_data(self, data: List[dict]) -> ManualImportResult:
        """Imports an array of CanonicalArticle dictionaries."""
        articles = []
        ids = []
        for item in data:
            try:
                art = CanonicalArticle.model_validate(item)
                articles.append(art)
                ids.append(art.canonical_id)
            except Exception as e:
                logger.warning(f"Error validating article payload: {e}")

        if articles:
            await self.store.index_articles_batch(articles)
            return ManualImportResult(
                success=True,
                imported_count=len(articles),
                articles=ids,
                message=f"{len(articles)} ta huquqiy norma muvaffaqiyatli saqlandi va indekslandi."
            )
        return ManualImportResult(success=False, imported_count=0, articles=[], message="Yaroqli huquqiy normalar topilmadi.")

    async def import_single_article(self, inp: ManualArticleInput) -> ManualImportResult:
        """Creates and indexes a single canonical article from manual form input."""
        law_slug = re.sub(r"[^a-z0-9_]", "_", inp.law_number.lower()).strip("_")
        art_slug = re.sub(r"[^0-9a-z_]", "", inp.article_number.lower())
        canonical_id = f"custom_{law_slug}_{art_slug}_{hashlib.sha256(inp.text.encode()).hexdigest()[:6]}"

        text_latin = cyrillic_to_latin(inp.text.strip())
        title_latin = cyrillic_to_latin(inp.title.strip())

        article = CanonicalArticle(
            canonical_id=canonical_id,
            schema_version="1.1",
            metadata=ArticleMetadata(
                law_id=f"custom_{law_slug}",
                law_title=localized(inp.law_title, inp.law_title),
                law_number=inp.law_number,
                chapter_number="",
                article_number=inp.article_number,
                article_title=localized(title_latin, inp.title),
                source_url=inp.source_url,
                effective_date=str(date.today()),
                last_verified_date=str(date.today()),
                source_hash=f"sha256:{hashlib.sha256(inp.text.encode('utf-8')).hexdigest()[:16]}",
                status=ArticleStatus.ACTIVE,
                category=inp.category,
                disability_types=inp.disability_types,
                beneficiary_type=["person_with_disability"],
                embedding_model_version="baai/bge-m3",
            ),
            points=[ArticlePoint(point_id="1", text=localized(text_latin, inp.text))],
            translations=localized(text_latin, inp.text),
            translation_provenance=provenance_for(localized(text_latin, inp.text))
        )

        await self.store.index_article(article)
        return ManualImportResult(
            success=True,
            imported_count=1,
            articles=[canonical_id],
            message=f"{inp.article_number} ({inp.law_number}) muvaffaqiyatli saqlandi va indekslandi."
        )
