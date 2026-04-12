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


@pytest.mark.asyncio
async def test_data_agent_passes_provider_to_router():
    with patch("src.agents.data_agent.init_db"), \
         patch("src.agents.data_agent.llm_router.generate", new_callable=AsyncMock, side_effect=["SELECT 1", "interpretação"]) as mock_gen, \
         patch("src.agents.data_agent._execute_sql", return_value=([(1,)], ["count"])):
        import importlib
        import src.agents.data_agent as _m
        importlib.reload(_m)
        agent = _m.DataAgent()
        resp = await agent.answer("Quantas transações?", provider="claude")
    assert mock_gen.await_count == 2
    for call in mock_gen.await_args_list:
        args = call.args
        kwargs = call.kwargs
        assert kwargs.get("provider") == "claude" or (len(args) > 1 and args[1] == "claude")


@pytest.mark.asyncio
async def test_coordinator_threads_provider_to_knowledge_agent():
    from src.agents.coordinator import CoordinatorAgent

    mock_k_resp = MagicMock()
    mock_k_resp.answer = "resposta regulatória"
    mock_k_resp.sources = []
    mock_k_resp.data = None
    mock_k_resp.actions_taken = []
    mock_k_resp.agent_name = "knowledge"

    with patch("src.agents.coordinator.init_db"), \
         patch("src.agents.coordinator.CoordinatorAgent._classify", new_callable=AsyncMock, return_value="KNOWLEDGE"), \
         patch("src.agents.coordinator.CoordinatorAgent._log", return_value=1):
        coordinator = CoordinatorAgent()
        coordinator.knowledge_agent = MagicMock()
        coordinator.knowledge_agent.answer = AsyncMock(return_value=mock_k_resp)

        result = await coordinator.process("Qual o prazo?", provider="claude")

    coordinator.knowledge_agent.answer.assert_awaited_once_with("Qual o prazo?", provider="claude")
    assert result.provider_utilizado == "claude"
