"""
Tests for LegalTools, LegalAgent, and SmartLegalRouter.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.agents.legal_tools import LegalTools
from src.agents.legal_agent import LegalAgent, AgentResponse, AgentHop
from src.agents.smart_router import SmartLegalRouter, RoutingDecision
from src.clients.openrouter import OpenRouterClient


def test_legal_tools_search():
    tools = LegalTools()
    results = tools.search_articles("pensiya nafaqa tayinlash", limit=3)
    assert isinstance(results, list)
    if results:
        r = results[0]
        assert "canonical_id" in r
        assert "law_number" in r
        assert "snippet" in r


def test_legal_tools_read_full():
    tools = LegalTools()
    res = tools.read_article_full("O'RQ-641", "44")
    if res:
        assert res["law_number"] == "O'RQ-641"
        assert "44" in res["article_number"]
        assert "full_text" in res
        assert len(res["full_text"]) > 20


def test_legal_tools_subordinate():
    tools = LegalTools()
    res = tools.find_subordinate_regulations("O'RQ-641", limit=2)
    assert isinstance(res, list)


def test_smart_router_fast():
    router = SmartLegalRouter()
    r = router.route("Qayerga murojaat qilish kerak?")
    assert r.decision == RoutingDecision.FAST_RAG


def test_smart_router_agentic():
    router = SmartLegalRouter()
    q = "Xususiy korxona nogiron xodimga ish vaqtini qisqartirmadi, sudga qanday ariza yozaman va tovon undiraman?"
    r = router.route(q)
    assert r.decision == RoutingDecision.AGENTIC_RAG


@pytest.mark.asyncio
async def test_legal_agent_mock_run():
    client = OpenRouterClient()
    client.is_mock = True
    agent = LegalAgent(client=client)
    
    resp = await agent.run("Nogironligi bo'lgan bolalarga ijtimoiy yordam ko'rsatish tartibi qanday?")
    assert isinstance(resp, AgentResponse)
    assert resp.total_hops == 2
    assert len(resp.final_answer) > 50
    assert resp.is_mock is True
    assert len(resp.cited_sources) > 0


@pytest.mark.asyncio
async def test_legal_agent_empty_query():
    client = OpenRouterClient()
    client.is_mock = True
    agent = LegalAgent(client=client)
    
    resp = await agent.run("   ")
    assert resp.total_hops == 0
    assert "Iltimos" in resp.final_answer
