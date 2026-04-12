"""Tests for the CoordinatorAgent routing logic."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.agents.coordinator import CoordinatorAgent, CoordinatorResponse, _heuristic_route
from src.agents.base import AgentResponse


class TestHeuristicRoute:
    def test_routes_regulatory_to_knowledge(self):
        assert _heuristic_route("O que diz a Resolução CMN 5.274?") == "KNOWLEDGE"

    def test_routes_data_question_to_data(self):
        assert _heuristic_route("Quantas transações em espécie temos?") == "DATA"

    def test_routes_action_request_to_action(self):
        assert _heuristic_route("Crie um alerta para essa transação") == "ACTION"

    def test_routes_combined_to_knowledge_data(self):
        q = "Verifique se as transações em espécie estão em conformidade com a Resolução 3.978"
        assert _heuristic_route(q) == "KNOWLEDGE+DATA"


class TestCoordinatorProcess:
    @pytest.fixture
    def db_tmp(self, tmp_path, monkeypatch):
        import src.database.connection as conn_mod
        monkeypatch.setattr(conn_mod.settings, "db_path", str(tmp_path / "test.db"))

    @pytest.mark.asyncio
    async def test_routes_to_knowledge_agent(self, db_tmp):
        mock_k_response = AgentResponse(
            agent_name="knowledge", answer="Prazo: 1º de março de 2026.", confidence=0.9
        )
        coord = CoordinatorAgent.__new__(CoordinatorAgent)
        coord.knowledge_agent = AsyncMock()
        coord.knowledge_agent.answer = AsyncMock(return_value=mock_k_response)
        coord.data_agent = AsyncMock()
        coord.action_agent = AsyncMock()

        with patch("src.agents.coordinator.llm_router.generate",
                   new_callable=AsyncMock, return_value="KNOWLEDGE"), \
             patch("src.agents.coordinator.init_db"), \
             patch.object(coord, "_log", return_value=1):
            result = await coord.process("Qual o prazo da Resolução 5.274?")

        assert isinstance(result, CoordinatorResponse)
        assert result.roteamento == "KNOWLEDGE"
        assert "knowledge" in result.agentes_utilizados
        assert result.provider_utilizado == "ollama"

    @pytest.mark.asyncio
    async def test_routes_to_data_agent(self, db_tmp):
        mock_d_response = AgentResponse(
            agent_name="data", answer="50 transações.", confidence=0.85,
            data={"sql": "SELECT COUNT(*) FROM transactions", "rows": [], "total": 50}
        )
        coord = CoordinatorAgent.__new__(CoordinatorAgent)
        coord.knowledge_agent = AsyncMock()
        coord.data_agent = AsyncMock()
        coord.data_agent.answer = AsyncMock(return_value=mock_d_response)
        coord.action_agent = AsyncMock()

        with patch("src.agents.coordinator.llm_router.generate",
                   new_callable=AsyncMock, return_value="DATA"), \
             patch("src.agents.coordinator.init_db"), \
             patch.object(coord, "_log", return_value=2):
            result = await coord.process("Quantas transações temos?")

        assert result.roteamento == "DATA"
        assert "data" in result.agentes_utilizados
        assert result.detalhes_agentes[0]["dados"]["total"] == 50
        assert result.provider_utilizado == "ollama"
