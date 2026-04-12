"""Unit tests for all agent classes. LLM calls are mocked."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.agents.base import AgentResponse
from src.agents.knowledge_agent import KnowledgeAgent


# ── KnowledgeAgent ──────────────────────────────────────────────────────────

class TestKnowledgeAgentCanHandle:
    def test_high_confidence_for_resolution_question(self):
        agent = KnowledgeAgent()
        score = agent.can_handle("O que diz a Resolução CMN 5.274 sobre segurança cibernética?")
        assert score >= 0.4

    def test_low_confidence_for_data_question(self):
        agent = KnowledgeAgent()
        score = agent.can_handle("Quantas transações acima de R$50.000 temos?")
        assert score < 0.3


class TestKnowledgeAgentAnswer:
    @pytest.mark.asyncio
    async def test_returns_agent_response(self):
        from src.retrieval.query_engine import RetrievedChunk
        mock_chunks = [
            RetrievedChunk(content="Prazo: 1º de março de 2026.", score=0.9,
                           metadata={"source": "res_5274.pdf", "page": 3})
        ]
        with patch("src.agents.knowledge_agent.retrieve", return_value=mock_chunks), \
             patch("src.agents.knowledge_agent.ollama_client.generate",
                   new_callable=AsyncMock, return_value="O prazo é 1º de março de 2026."):
            agent = KnowledgeAgent()
            response = await agent.answer("Qual é o prazo da Resolução 5.274?")

        assert isinstance(response, AgentResponse)
        assert response.agent_name == "knowledge"
        assert "março" in response.answer
        assert len(response.sources) == 1

    @pytest.mark.asyncio
    async def test_no_chunks_returns_not_found(self):
        with patch("src.agents.knowledge_agent.retrieve", return_value=[]):
            agent = KnowledgeAgent()
            response = await agent.answer("pergunta qualquer")

        assert response.confidence == 0.0
        assert "Nenhum" in response.answer


# ── DataAgent ────────────────────────────────────────────────────────────────

from src.agents.data_agent import DataAgent, _extract_sql, _SELECT_ONLY_RE
import re


class TestDataAgentHelpers:
    def test_extract_sql_strips_markdown(self):
        raw = "```sql\nSELECT * FROM transactions\n```"
        assert _extract_sql(raw) == "SELECT * FROM transactions"

    def test_extract_sql_plain(self):
        raw = "SELECT COUNT(*) FROM alerts"
        assert _extract_sql(raw) == "SELECT COUNT(*) FROM alerts"

    def test_select_only_regex_blocks_delete(self):
        assert not _SELECT_ONLY_RE.match("DELETE FROM transactions")

    def test_select_only_regex_allows_select(self):
        assert _SELECT_ONLY_RE.match("SELECT * FROM transactions")


class TestDataAgentCanHandle:
    def test_high_for_data_question(self):
        agent = DataAgent()
        score = agent.can_handle("Quantas transações em espécie não foram reportadas ao COAF?")
        assert score >= 0.4

    def test_low_for_regulatory_question(self):
        agent = DataAgent()
        score = agent.can_handle("O que diz o artigo 49 da Circular 3.978?")
        assert score < 0.3


class TestDataAgentAnswer:
    @pytest.mark.asyncio
    async def test_returns_agent_response_with_data(self, tmp_path, monkeypatch):
        import src.database.connection as conn_mod
        monkeypatch.setattr(conn_mod.settings, "db_path", str(tmp_path / "test.db"))

        with patch("src.agents.data_agent.ollama_client.generate",
                   new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = [
                "SELECT COUNT(*) FROM transactions",
                "Existem 50 transações no total.",
            ]
            agent = DataAgent()
            response = await agent.answer("Quantas transações temos?")

        assert isinstance(response, AgentResponse)
        assert response.agent_name == "data"
        assert response.data is not None
        assert "sql" in response.data

    @pytest.mark.asyncio
    async def test_blocks_non_select_sql(self, tmp_path, monkeypatch):
        import src.database.connection as conn_mod
        monkeypatch.setattr(conn_mod.settings, "db_path", str(tmp_path / "test.db"))

        with patch("src.agents.data_agent.ollama_client.generate",
                   new_callable=AsyncMock, return_value="DELETE FROM transactions"):
            agent = DataAgent()
            response = await agent.answer("Apague tudo")

        assert response.confidence == 0.0
        assert "segura" in response.answer
