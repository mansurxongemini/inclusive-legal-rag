"""
Legal Tools for Agentic RAG multi-hop reasoning.
Provides fast, safe, read-only tools to search, inspect, and trace legislation in SQLite FTS5 and disability registry.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.schema.canonical import CanonicalArticle
from src.storage.fts_store import SqliteFtsStore

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path("data/sources/disability_registry.json")


class LegalTools:
    """Read-only toolset for autonomous legal reasoning agents."""

    def __init__(self, fts_store: Optional[SqliteFtsStore] = None, registry_path: Optional[Path] = None):
        self.fts_store = fts_store or SqliteFtsStore()
        self.registry_path = registry_path or REGISTRY_PATH
        self._registry_docs: List[Dict[str, Any]] = []
        self._load_registry()

    def _load_registry(self):
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._registry_docs = data.get("documents", [])
            except Exception as e:
                logger.warning(f"Failed to load registry in LegalTools: {e}")
                self._registry_docs = []

    def search_articles(
        self,
        query: str,
        domain: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Qonunchilik bazasidan kalit so'zlar bo'yicha eng tegishli moddalarni qidiradi.
        
        Args:
            query: Qidiruv so'rovi (masalan: "nogironlik nafaqasi tayinlash shartlari").
            domain: Ixtiyoriy soha filtri (masalan: "mehnat", "soliq", "tiek", "reabilitatsiya").
            limit: Qaytariladigan moddalar soni (odatda 3-5 ta).
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        search_query = clean_q
        if domain and domain.lower() not in clean_q.lower():
            search_query = f"{domain} {clean_q}"

        bm25_res = self.fts_store.bm25_search(search_query, language="uz", top_k=limit * 2)
        if not bm25_res:
            # Fallback retry without domain
            bm25_res = self.fts_store.bm25_search(clean_q, language="uz", top_k=limit)

        canonical_ids = [r["canonical_id"] for r in bm25_res[:limit]]
        articles_map = self.fts_store.get_articles_batch(canonical_ids)

        output: List[Dict[str, Any]] = []
        for r in bm25_res[:limit]:
            cid = r["canonical_id"]
            art = articles_map.get(cid)
            if not art:
                continue

            text_uz = art.get_text("uz")
            snippet = text_uz[:350] + ("..." if len(text_uz) > 350 else "")

            law_title_uz = art.metadata.law_title.get("uz", "") if isinstance(art.metadata.law_title, dict) else str(art.metadata.law_title)
            article_title_uz = art.get_title("uz") or (art.metadata.article_title.get("uz", "") if isinstance(art.metadata.article_title, dict) else "")

            output.append({
                "canonical_id": art.canonical_id,
                "law_number": art.metadata.law_number,
                "law_title": law_title_uz,
                "article_number": art.metadata.article_number,
                "article_title": article_title_uz,
                "status": art.metadata.status.value,
                "snippet": snippet,
                "source_url": art.metadata.source_url,
                "relevance_score": round(r["score"], 3)
            })

        return output

    def read_article_full(
        self,
        identifier: str,
        article_number: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Aniq bitta modda yoki bandning to'liq matnini ochib beradi.
        
        Args:
            identifier: Moddaning aniq canonical_id si (masalan: "law_disability_2020_art_44")
                        yoki qonun raqami (masalan: "O'RQ-641", "VMQ-505", "Mehnat kodeksi").
            article_number: Agar birinchi argumentda qonun raqami berilgan bo'lsa,
                            modda raqami (masalan: "44-modda", "44", "15-band").
        """
        ident = identifier.strip()
        
        # 1. Direct canonical_id lookup
        art = self.fts_store.get_article(ident)
        if art:
            return self._format_article_full(art)

        # 2. Lookup by law_number and article_number
        target_art_num = article_number.strip() if article_number else ""
        
        # If no separate article_number provided, try parsing from identifier
        if not target_art_num:
            match = re.search(r"(\d+)[- ]?(?:modda|band|m|p)", ident, re.I)
            if match:
                target_art_num = match.group(1)

        with self.fts_store._get_connection() as conn:
            cursor = conn.cursor()
            
            clean_num = re.sub(r"[^\d]", "", target_art_num)
            
            if clean_num:
                query = """
                    SELECT json_data FROM articles_metadata 
                    WHERE (
                        json_extract(json_data, '$.metadata.law_number') LIKE ? 
                        OR json_extract(json_data, '$.metadata.title') LIKE ?
                        OR canonical_id LIKE ?
                    )
                    AND (
                        json_extract(json_data, '$.metadata.article_number') LIKE ?
                        OR canonical_id LIKE ?
                    )
                    LIMIT 1
                """
                cursor.execute(query, (
                    f"%{ident}%", f"%{ident}%", f"%{ident}%",
                    f"%{clean_num}%", f"%art_{clean_num}%"
                ))
            else:
                query = """
                    SELECT json_data FROM articles_metadata 
                    WHERE json_extract(json_data, '$.metadata.law_number') LIKE ? 
                       OR json_extract(json_data, '$.metadata.law_title.uz') LIKE ?
                       OR canonical_id LIKE ?
                    LIMIT 1
                """
                cursor.execute(query, (f"%{ident}%", f"%{ident}%", f"%{ident}%"))

            row = cursor.fetchone()
            if row:
                found_art = CanonicalArticle.model_validate_json(row["json_data"])
                return self._format_article_full(found_art)

        return None

    def _format_article_full(self, art: CanonicalArticle) -> Dict[str, Any]:
        law_title_uz = art.metadata.law_title.get("uz", "") if isinstance(art.metadata.law_title, dict) else str(art.metadata.law_title)
        article_title_uz = art.get_title("uz") or (art.metadata.article_title.get("uz", "") if isinstance(art.metadata.article_title, dict) else "")
        return {
            "canonical_id": art.canonical_id,
            "law_number": art.metadata.law_number,
            "law_title": law_title_uz,
            "article_number": art.metadata.article_number,
            "article_title": article_title_uz,
            "full_text": art.get_text("uz"),
            "status": art.metadata.status.value,
            "chapter_number": art.metadata.chapter_number,
            "annex_title": art.metadata.annex_title,
            "source_url": art.metadata.source_url,
        }

    def find_subordinate_regulations(
        self,
        parent_act: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Qonun yoki asosiy hujjat ijrosini ta'minlovchi Vazirlar Mahkamasi qarorlari
        va quyi idoraviy nizomlarni topadi.
        
        Args:
            parent_act: Qonun raqami yoki nomi (masalan: "O'RQ-641", "Mehnat kodeksi", "Nogironlik to'g'risidagi qonun").
            limit: Natijalar soni.
        """
        clean_act = parent_act.strip()
        results: List[Dict[str, Any]] = []

        # 1. Search in registry titles
        act_tokens = [w for w in re.split(r"\W+", clean_act.lower()) if len(w) > 2]
        for doc in self._registry_docs:
            title = doc.get("title", "").lower()
            num = doc.get("number", "").lower()
            if any(t in title or t in num for t in act_tokens):
                results.append({
                    "law_number": doc.get("number", ""),
                    "title": doc.get("title", ""),
                    "lex_id": doc.get("lex_id", ""),
                    "source_url": f"https://lex.uz/docs/{doc.get('lex_id')}"
                })
                if len(results) >= limit:
                    break

        # 2. If needed, FTS query for decrees mentioning parent_act
        if len(results) < limit:
            decree_search = self.fts_store.bm25_search(
                f"{clean_act} qaror nizom", language="uz", top_k=limit * 2
            )
            for item in decree_search:
                cid = item["canonical_id"]
                art = self.fts_store.get_article(cid)
                if art and art.metadata.law_number != clean_act:
                    lt = art.metadata.law_title.get("uz", "") if isinstance(art.metadata.law_title, dict) else str(art.metadata.law_title)
                    entry = {
                        "law_number": art.metadata.law_number,
                        "title": lt,
                        "source_url": art.metadata.source_url
                    }
                    if not any(r["law_number"] == entry["law_number"] for r in results):
                        results.append(entry)
                        if len(results) >= limit:
                            break

        return results[:limit]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Executes a tool dynamically by name and args."""
        if tool_name == "search_articles":
            return self.search_articles(
                query=args.get("query", ""),
                domain=args.get("domain"),
                limit=args.get("limit", 5)
            )
        elif tool_name == "read_article_full":
            return self.read_article_full(
                identifier=args.get("identifier", ""),
                article_number=args.get("article_number")
            )
        elif tool_name == "find_subordinate_regulations":
            return self.find_subordinate_regulations(
                parent_act=args.get("parent_act", ""),
                limit=args.get("limit", 5)
            )
        else:
            return {"error": f"Noma'lum asbob: {tool_name}"}

    def get_tool_specs(self) -> List[Dict[str, Any]]:
        """Returns tool specs formatted for function calling / agent system prompt."""
        return [
            {
                "name": "search_articles",
                "description": "Qonunchilik bazasidan kalit so'zlar bo'yicha eng tegishli moddalarni qidiradi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Qidiruv so'rovi yoki kalit iboralar"},
                        "domain": {"type": "string", "description": "Ixtiyoriy huquqiy soha (tiek, mehnat, pensiya_nafaqa, soliq, reabilitatsiya, talim)"},
                        "limit": {"type": "integer", "description": "Qaytariladigan moddalar soni (default 5)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "read_article_full",
                "description": "Aniq bir moddaning to'liq matnini ochib ko'radi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "identifier": {"type": "string", "description": "Modda canonical_id si yoki qonun raqami (masalan: O'RQ-641, VMQ-505)"},
                        "article_number": {"type": "string", "description": "Ixtiyoriy modda raqami (masalan: 44-modda yoki 12)"}
                    },
                    "required": ["identifier"]
                }
            },
            {
                "name": "find_subordinate_regulations",
                "description": "Qonunga bog'liq Hukumat qarorlari va quyi nizomlarni topadi.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "parent_act": {"type": "string", "description": "Qonun raqami yoki nomi"}
                    },
                    "required": ["parent_act"]
                }
            }
        ]
