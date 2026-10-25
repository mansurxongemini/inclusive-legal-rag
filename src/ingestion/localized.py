"""Language fields for imported text: only languages that really exist are stored."""
from typing import Dict

from src.nlp.transliteration import is_genuine_russian
from src.schema.canonical import TranslationProvenanceType


def localized(uz: str, raw: str = "") -> Dict[str, str]:
    """
    {"uz": <Uzbek Latin>} plus {"ru": raw} when `raw` is genuine Russian.

    Importers read Uzbek documents (Latin or Cyrillic); copying that text under "ru" or "en" indexed it as a
    translation it is not.
    """
    out = {"uz": uz}
    if raw and raw.strip() and is_genuine_russian(raw):
        out["ru"] = raw
    return out


def provenance_for(texts: Dict[str, str]) -> Dict[str, TranslationProvenanceType]:
    return {lang: TranslationProvenanceType.OFFICIAL for lang in texts}
