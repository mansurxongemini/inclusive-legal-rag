"""
Autonomous ReAct Legal Agent for multi-hop legal reasoning.
Performs iterative question decomposition, tool-assisted statutory retrieval,
cross-reference inspection, and grounded citation synthesis.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.clients.openrouter import OpenRouterClient
from src.agents.legal_tools import LegalTools
from src.config import settings

logger = logging.getLogger(__name__)


class AgentHop(BaseModel):
    step: int
    thought: str
    action_name: str
    action_args: Dict[str, Any]
    observation_summary: str
    raw_observation: Any = Field(default=None)


class AgentResponse(BaseModel):
    question: str
    final_answer: str
    hops: List[AgentHop] = Field(default_factory=list)
    total_hops: int = 0
    cited_canonical_ids: List[str] = Field(default_factory=list)
    cited_sources: List[Dict[str, str]] = Field(default_factory=list)
    is_mock: bool = False
    duration_seconds: float = 0.0


AGENT_SYSTEM_PROMPT = """Siz O'zbekiston Respublikasi qonunchiligi bo'yicha mustaqil professional yurist-agentsiz.
Vazifangiz: fuqaroning murakkab, kazuistik va ziddiyatli huquqiy savollarini tahlil qilib, faqat amaldagi qonun hujjatlariga asoslangan, xolis va to'liq yuridik xulosa berish.

QAT'IY QOIDALAR:
1. Hech qachon o'zingizdan qonun, modda yoki raqam to'qimang (galusinatsiya 0% bo'lishi shart).
2. Savolga darhol yuzaki javob bermang. Avval asboblardan foydalanib barcha tegishli moddalarni o'qib chiqing.
3. Agar asosiy qonunda "tartibi Hukumat qarori bilan belgilanadi" deb ko'rsatilgan bo'lsa, albatta o'sha qarorni ham topib, o'qing.
4. Javobingizda fuqaro uchun amaliy qadamlar, muddatlar va murojaat qilish joylarini aniq ko'rsating.
5. Dasturchi jargonlari (art_..., law_...) yoki nemis huquqiy atamalarini ISHLATMANG. Professional va samimiy o'zbek tilida yozing.

SIZNING ASBOBLARINGIZ (TOOLS):
1. search_articles(query, domain, limit) - Qonunchilik bazasidan kalit so'zlar bo'yicha moddalarni qidiradi.
2. read_article_full(identifier, article_number) - Aniq bitta moddaning to'liq matnini ochib ko'radi.
3. find_subordinate_regulations(parent_act) - Qonunga bog'liq qaror va nizomlarni topadi.

HAR BIR QADAMDA FORMATGA QAT'IY AMAL QILING:
Thought: [Nima qilmoqchiligingiz va nima uchun kerakligi haqida yuridik mulohazangiz]
Action: asbob_nomi({"parametr": "qiymat"})

Tizim sizga asbob natijasini qaytaradi:
Observation: [Asbob natijalari]

Barcha ma'lumotlar to'liq to'plangach, yakuniy xulosa bering:
Thought: Endi menda barcha zarur huquqiy asoslar mavjud, yakuniy xulosani shakllantiraman.
Final Answer: [Fuqaro uchun professional, aniq va asoslangan yuridik javob]
"""


class LegalAgent:
    """Multi-hop autonomous legal assistant leveraging ReAct reasoning."""

    def __init__(
        self,
        tools: Optional[LegalTools] = None,
        client: Optional[OpenRouterClient] = None,
        max_hops: int = 3,
        model: Optional[str] = None
    ):
        self.tools = tools or LegalTools()
        self.client = client or OpenRouterClient()
        self.max_hops = max_hops
        self.model = model or settings.GENERATION_MODEL_PRIMARY

    async def run(self, question: str) -> AgentResponse:
        """Executes the autonomous reasoning loop for a complex legal question."""
        import time
        start_time = time.time()
        
        clean_q = question.strip()
        if not clean_q:
            return AgentResponse(
                question="",
                final_answer="Iltimos, huquqiy savolingizni bayon qiling.",
                duration_seconds=0.0
            )

        if self.client.is_mock:
            return self._run_mock(clean_q, start_time)

        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Fuqaro savoli: {clean_q}"}
        ]

        hops: List[AgentHop] = []
        collected_articles: Dict[str, Dict[str, Any]] = {}
        final_answer = ""

        for step in range(1, self.max_hops + 1):
            try:
                response_text = await self.client.chat_completion(
                    messages=messages,
                    model=self.model,
                    temperature=0.0,
                    max_tokens=4096
                )
            except Exception as e:
                logger.error(f"Agent LLM completion failed at hop {step}: {e}")
                break

            # Check if model arrived at Final Answer
            final_match = re.search(r"Final Answer:\s*(.*)", response_text, re.DOTALL | re.IGNORECASE)
            if final_match:
                final_answer = final_match.group(1).strip()
                # Record the final thought if present
                thought_match = re.search(r"Thought:\s*(.*?)(?=Final Answer:|$)", response_text, re.DOTALL | re.IGNORECASE)
                final_thought = thought_match.group(1).strip() if thought_match else "Yakuniy xulosaga kelindi."
                hops.append(AgentHop(
                    step=step,
                    thought=final_thought,
                    action_name="final_answer",
                    action_args={},
                    observation_summary="Yakuniy javob shakllantirildi."
                ))
                break

            # Parse Thought and Action
            thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", response_text, re.DOTALL | re.IGNORECASE)
            action_match = re.search(r"Action:\s*(\w+)\((.*?)\)", response_text, re.DOTALL)

            thought = thought_match.group(1).strip() if thought_match else f"{step}-qadam tahlili."
            
            if not action_match:
                # If no explicit action format, check if the text itself contains a direct answer
                if len(response_text) > 100 and ("modda" in response_text or "qonun" in response_text):
                    final_answer = response_text.strip()
                    break
                # Otherwise, force a fallback search action
                action_name = "search_articles"
                action_args = {"query": clean_q, "limit": 4}
            else:
                action_name = action_match.group(1).strip()
                args_str = action_match.group(2).strip()
                try:
                    action_args = json.loads(args_str)
                except Exception:
                    # Try simple single-quote fix
                    try:
                        action_args = json.loads(args_str.replace("'", '"'))
                    except Exception:
                        action_args = {"query": clean_q}

            # Execute tool
            try:
                raw_obs = self.tools.execute_tool(action_name, action_args)
            except Exception as ex:
                raw_obs = {"error": f"Asbobni bajarishda xatolik: {ex}"}

            obs_summary = self._summarize_observation(raw_obs, collected_articles)

            hops.append(AgentHop(
                step=step,
                thought=thought,
                action_name=action_name,
                action_args=action_args,
                observation_summary=obs_summary[:300],
                raw_observation=raw_obs
            ))

            # Append assistant step and tool observation to prompt history
            messages.append({"role": "assistant", "content": f"Thought: {thought}\nAction: {action_name}({json.dumps(action_args, ensure_ascii=False)})"})
            messages.append({"role": "user", "content": f"Observation: {obs_summary}"})

        # If loop finished without explicit Final Answer, synthesize one from observations
        if not final_answer:
            final_answer = await self._synthesize_fallback_answer(clean_q, collected_articles)

        elapsed = time.time() - start_time
        cited_cids = list(collected_articles.keys())
        sources = [
            {
                "law_number": art.get("law_number", ""),
                "article_number": art.get("article_number", ""),
                "title": art.get("law_title", "") or art.get("title", ""),
                "source_url": art.get("source_url", "")
            }
            for art in collected_articles.values()
            if art.get("source_url")
        ]

        return AgentResponse(
            question=clean_q,
            final_answer=final_answer,
            hops=hops,
            total_hops=len(hops),
            cited_canonical_ids=cited_cids,
            cited_sources=sources,
            is_mock=False,
            duration_seconds=round(elapsed, 2)
        )

    def _summarize_observation(
        self,
        raw_obs: Any,
        collected_articles: Dict[str, Dict[str, Any]]
    ) -> str:
        """Summarizes tool output cleanly for next LLM step and caches articles."""
        if isinstance(raw_obs, list):
            if not raw_obs:
                return "Hech qanday ma'lumot topilmadi. Iltimos, boshqa kalit so'zlar bilan qidirib ko'ring."
            summaries = []
            for item in raw_obs:
                if isinstance(item, dict):
                    cid = item.get("canonical_id")
                    if cid:
                        collected_articles[cid] = item
                    law_num = item.get("law_number", "")
                    art_num = item.get("article_number", "")
                    title = item.get("article_title") or item.get("title", "")
                    snippet = item.get("snippet", "")
                    summaries.append(f"[{law_num} {art_num}] {title}: {snippet}")
            return "\n".join(summaries)
        elif isinstance(raw_obs, dict):
            cid = raw_obs.get("canonical_id")
            if cid:
                collected_articles[cid] = raw_obs
            law_num = raw_obs.get("law_number", "")
            art_num = raw_obs.get("article_number", "")
            full_text = raw_obs.get("full_text", "")
            return f"[{law_num} {art_num}]: {full_text[:600]}..."
        return str(raw_obs)

    async def _synthesize_fallback_answer(
        self,
        question: str,
        collected_articles: Dict[str, Dict[str, Any]]
    ) -> str:
        """Synthesizes final answer from collected articles if max hops reached without final answer."""
        if not collected_articles:
            # Fallback search
            top_arts = self.tools.search_articles(question, limit=3)
            for a in top_arts:
                if a.get("canonical_id"):
                    collected_articles[a["canonical_id"]] = a

        context_blocks = []
        for a in collected_articles.values():
            law_num = a.get("law_number", "")
            art_num = a.get("article_number", "")
            text = a.get("full_text") or a.get("snippet", "")
            context_blocks.append(f"{law_num} ({art_num}): {text}")

        context_str = "\n\n".join(context_blocks)
        prompt = (
            f"Fuqaro savoli: {question}\n\n"
            f"O'rganilgan qonunchilik asoslari:\n{context_str}\n\n"
            f"Ushbu qonun moddalariga tayanib, fuqaro uchun to'liq, amaliy va aniq yuridik javob yozing."
        )

        try:
            return await self.client.chat_completion(
                messages=[
                    {"role": "system", "content": "Siz tajribali o'zbek yuristisiz. Berilgan qonuniy asoslardan kelib chiqib aniq javob bering."},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=0.0
            )
        except Exception:
            return "Huquqiy tahlil yakunlandi. Tegishli qonun moddalari asosida o'rganib chiqildi."

    def _run_mock(self, question: str, start_time: float) -> AgentResponse:
        """Deterministic mock run for offline execution and automated tests."""
        import time
        results = self.tools.search_articles(question, limit=2)
        collected_articles: Dict[str, Dict[str, Any]] = {}
        for r in results:
            if r.get("canonical_id"):
                collected_articles[r["canonical_id"]] = r

        first_art = results[0] if results else {
            "law_number": "O'RQ-641",
            "article_number": "44-modda",
            "article_title": "Huquqlarni ta'minlash",
            "source_url": "https://lex.uz/docs/-5049511"
        }

        hops = [
            AgentHop(
                step=1,
                thought=f"Fuqaro savoli bo'yicha bazadan tegishli moddalarni qidiraman: {question[:40]}...",
                action_name="search_articles",
                action_args={"query": question, "limit": 2},
                observation_summary=f"Topildi: {first_art.get('law_number')} {first_art.get('article_number')}",
                raw_observation=results
            ),
            AgentHop(
                step=2,
                thought="Moddaning to'liq matnini o'rganib, fuqaro uchun yakuniy xulosani shakllantiraman.",
                action_name="read_article_full",
                action_args={"identifier": first_art.get("law_number", "O'RQ-641"), "article_number": first_art.get("article_number", "44-modda")},
                observation_summary="Modda to'liq matni o'rganildi.",
                raw_observation=first_art
            )
        ]

        final_answer = (
            f"Oʻzbekiston Respublikasining {first_art.get('law_number')} sonli qonuni "
            f"({first_art.get('article_number')})ga muvofiq, fuqaroning mazkur masaladagi huquqlari "
            f"qonun bilan toʻliq kafolatlangan. Mazkur xizmat yoki imtiyozdan foydalanish uchun "
            f"hududiy 'Inson' ijtimoiy xizmatlar markaziga yoki Yagona interaktiv davlat xizmatlari portali (my.gov.uz) "
            f"orqali ariza bilan murojaat qilish lozim."
        )

        return AgentResponse(
            question=question,
            final_answer=final_answer,
            hops=hops,
            total_hops=len(hops),
            cited_canonical_ids=[first_art.get("canonical_id", "law_disability_2020_art_44")],
            cited_sources=[{
                "law_number": first_art.get("law_number", "O'RQ-641"),
                "article_number": first_art.get("article_number", "44-modda"),
                "title": first_art.get("article_title", "Huquqlarni ta'minlash"),
                "source_url": first_art.get("source_url", "https://lex.uz/docs/-5049511")
            }],
            is_mock=True,
            duration_seconds=round(time.time() - start_time, 2)
        )
