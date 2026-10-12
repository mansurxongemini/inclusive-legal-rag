"""
TypeSafe Jev 1.13 Legal Decision Engine for Inclusive Legal RAG.
Interacts with OpenRouter /api/alpha/decisions to make fast, structured categorical,
actionability (score), and relevance (noul) decisions on statutory clauses.
"""
import logging
import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from src.clients.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


class JevClassificationResult(BaseModel):
    category_slug: str
    category_name_uz: str
    category_probabilities: Dict[str, float] = Field(default_factory=dict)
    confidence: float = 0.0
    actionability_score: float = 0.0
    actionability_level: int = 0
    actionability_label: str = ""
    is_disability_relevant: bool = True
    disability_relevance_prob: float = 0.0
    duration_ms: float = 0.0
    model: str = "typesafe/jev-1.13"


class JevLegalClassifier:
    """Classifies statutory articles using TypeSafe Jev 1.13 System One decision model."""

    INCLUSIVE_CATEGORIES = {
        "court_appeal": {
            "name_uz": "Sud himoyasi va qarorlar ustidan shikoyat qilish",
            "criteria": "Sudga murojaat qilish, da'vo arizasi, apellyatsiya, komissiya, TMEK yoki mansabdor shaxs qarorlaridan norozi bo'lganda shikoyat qilish tartibi",
        },
        "medical_social_expertise": {
            "name_uz": "Tibbiy-ijtimoiy ekspertiza (TMEK / TIEK)",
            "criteria": "TMEK, tibbiy ko'rik, nogironlikni belgilash, sabablari va muddatlari, ekspertiza komissiyasi tekshiruvi",
        },
        "pensions_and_benefits": {
            "name_uz": "Nafaqalar, pensiyalar va moddiy to'lovlar",
            "criteria": "Nogironlik pensiyasi, oylik nafaqalar, bir martalik moddiy yordam, kompensatsiya to'lovlari, parvarishlash nafaqasi",
        },
        "labor_rights": {
            "name_uz": "Mehnat huquqlari va ish o'rinlari kafolati",
            "criteria": "Ishga qabul qilish, 3 foizli maxsus ish o'rni kvotasi, qisqartirilgan ish vaqti, qo'shimcha ta'tillar, mehnatni muhofaza qilish",
        },
        "tax_benefits": {
            "name_uz": "Soliq va davlat boji imtiyozlari",
            "criteria": "Jismoniy shaxslar daromad solig'i, mol-mulk va yer solig'idan ozod qilish, sudga murojaatda davlat bojidan ozod etish",
        },
        "transport_benefits": {
            "name_uz": "Transportdan imtiyozli foydalanish",
            "criteria": "Jamoat transporti, poyezd va aviachiptalarda bepul yoki chegirmali yo'l yurish, maxsus transport vositalari",
        },
        "rehabilitation_prosthetics": {
            "name_uz": "Reabilitatsiya va protez-ortopediya vositalari",
            "criteria": "Aravachalar, eshitish apparatlari, protez-ortopediya buyumlari, reabilitatsiya texnik vositalari bilan bepul ta'minlash",
        },
        "sanatorium_health": {
            "name_uz": "Sanatoriy-kurortda bepul davolanish",
            "criteria": "Sanatoriylarga bepul yo'llanmalar berish, tibbiy reabilitatsiya muassasalarida bepul davolanish tartibi",
        },
        "inclusive_education": {
            "name_uz": "Inklyuziv ta'lim va grant kvotalari",
            "criteria": "Bog'cha, maktab, texnikum va OTMlarga 2 foizli davlat granti kvotasi, stipendiyalar, maxsus o'quv sharoitlari",
        },
        "accessibility_infrastructure": {
            "name_uz": "To'siqsiz muhit va shaharsozlik qoidalari",
            "criteria": "Binolarda panduslar, liftlar, maxsus yo'laklar, infratuzilmani nogironligi bo'lgan shaxslarga moslashtirish talablari",
        },
        "disability_rights": {
            "name_uz": "Umumiy huquqlar va kamsitmaslik kafolatlari",
            "criteria": "O'RQ-641 qonunining umumiy tamoyillari, nogironlik belgisi bo'yicha kamsitishga yo'l qo'ymaslik, sha'n va qadr-qimmatni himoya qilish",
        },
        "international_treaty": {
            "name_uz": "Xalqaro konvensiya va bitimlar",
            "criteria": "BMT Nogironlar huquqlari to'g'risidagi konvensiyasi normalari va O'zbekistonning xalqaro majburiyatlari",
        },
    }

    ACTIONABILITY_LEVELS = [
        "0: Texnik yoki formal norma (ijro nazorati, e'lon qilinishi, muddatlar)",
        "1: Tashkiliy tartib yoki umumiy deklarativ tushuncha",
        "2: Nogironligi bo'lgan shaxsga to'g'ridan-to'g'ri amaliy huquq, to'lov yoki imtiyoz beruvchi qoida",
    ]

    def __init__(self, client: Optional[OpenRouterClient] = None):
        self.client = client or OpenRouterClient()

    async def classify_clause(
        self,
        clause_text: str,
        parent_law_title: Optional[str] = None
    ) -> JevClassificationResult:
        """Runs TypeSafe Jev 1.13 decision call to categorize, score, and evaluate a clause."""
        t0 = time.time()

        state = f"Hujjat: {parent_law_title or 'O‘zbekiston Respublikasi Qonunchiligi'}\nNorma matni:\n{clause_text.strip()}"

        choice_criteria = {slug: data["criteria"] for slug, data in self.INCLUSIVE_CATEGORIES.items()}

        questions = {
            "category": {
                "type": "choice",
                "instructions": "Ushbu norma quyidagi 12 ta sohadan qaysi biriga eng ko'p taalluqli?",
                "criteria": choice_criteria,
            },
            "actionability": {
                "type": "score",
                "instructions": "Ushbu norma nogironligi bo'lgan shaxsga to'g'ridan-to'g'ri amaliy huquq yoki imtiyoz beradimi?",
                "criteria": self.ACTIONABILITY_LEVELS,
            },
            "is_disability_relevant": {
                "type": "noul",
                "instructions": "Ushbu qoida nogironligi bo'lgan shaxslar manfaati, himoyasi, sud yoki ijtimoiy ta'minotiga taalluqlimi?",
                "criteria": {
                    "true": "Nogironlik, imtiyoz, pensiya, TMEK, sud, qulaylik yoki ijtimoiy himoyaga tegishli",
                    "false": "Umuman aloqasiz yoki faqat umumiy boshqa masala",
                }
            }
        }

        answers = await self.client.get_decision(state=state, questions=questions, model="typesafe/jev-1.13")
        dur_ms = (time.time() - t0) * 1000

        # Parse Choice
        cat_ans = answers.get("category", {})
        chosen_slug = cat_ans.get("choice") or "disability_rights"
        cat_meta = self.INCLUSIVE_CATEGORIES.get(chosen_slug, {"name_uz": chosen_slug})
        cat_probs = cat_ans.get("probabilities", {})
        cat_conf = cat_ans.get("confidence", 0.8)

        # Parse Score
        score_ans = answers.get("actionability", {})
        score_val = float(score_ans.get("score", 1.5))
        level_idx = min(2, max(0, int(round(score_val))))
        score_label = self.ACTIONABILITY_LEVELS[level_idx]

        # Parse Noul
        noul_ans = answers.get("is_disability_relevant", {})
        noul_prob = float(noul_ans.get("noul", 0.9))
        is_relevant = noul_prob >= 0.5

        return JevClassificationResult(
            category_slug=chosen_slug,
            category_name_uz=cat_meta["name_uz"],
            category_probabilities={k: round(v, 4) for k, v in cat_probs.items()},
            confidence=round(cat_conf, 2),
            actionability_score=round(score_val, 2),
            actionability_level=level_idx,
            actionability_label=score_label,
            is_disability_relevant=is_relevant,
            disability_relevance_prob=round(noul_prob, 2),
            duration_ms=round(dur_ms, 1),
            model="typesafe/jev-1.13"
        )
