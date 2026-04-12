"""Tests that agents thread the provider parameter to llm_router."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.retrieval.query_engine import RetrievedChunk


def _mock_chunk():
    return RetrievedChunk(
        content="Art. 1 — Prazo até 1º de março de 2026.",
        score=0.95,
        metadata={"source": "resolucao.pdf", "page": 1},
    )


@pytest.mark.asyncio
async def test_knowledge_agent_passes_provider_to_router():
    mock_gen = AsyncMock(return_value="resposta")
    with patch("src.agents.knowledge_agent.retrieve", return_value=[_mock_chunk()]), \
         patch("src.agents.knowledge_agent.build_prompt", return_value="prompt"), \
         patch("src.agents.knowledge_agent.llm_router.generate", mock_gen):
        from src.agents.knowledge_agent import KnowledgeAgent
        agent = KnowledgeAgent()
        resp = await agent.answer("Qual o prazo?", provider="claude")
    mock_gen.assert_awaited_once_with("prompt", provider="claude")
    assert resp.answer == "resposta"


@pytest.mark.asyncio
async def test_knowledge_agent_default_provider_is_ollama():
    mock_gen = AsyncMock(return_value="resp")
    with patch("src.agents.knowledge_agent.retrieve", return_value=[_mock_chunk()]), \
         patch("src.agents.knowledge_agent.build_prompt", return_value="prompt"), \
         patch("src.agents.knowledge_agent.llm_router.generate", mock_gen):
        from src.agents.knowledge_agent import KnowledgeAgent
        agent = KnowledgeAgent()
        await agent.answer("Qual o prazo?")
    mock_gen.assert_awaited_once_with("prompt", provider="ollama")
