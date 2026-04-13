"""Tests for the CoordinatorAgent routing logic."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from src.agents.coordinator import CoordinatorAgent, CoordinatorResponse, _heuristic_route, _is_conversational
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


class TestEnhancedHeuristicRoute:
    """Tests for the enhanced accent-insensitive keyword classifier."""

    def test_data_route_transacoes(self):
        assert _heuristic_route("Quantas transações não foram reportadas ao COAF?") == "DATA"

    def test_data_route_transacoes_no_accent(self):
        assert _heuristic_route("Quantas transacoes nao foram reportadas ao coaf?") == "DATA"

    def test_data_route_clientes_pep(self):
        assert _heuristic_route("Quais clientes são PEP?") == "DATA"

    def test_data_route_valor_total(self):
        assert _heuristic_route("Qual o valor total em espécie não reportado?") == "DATA"

    def test_data_route_reais(self):
        assert _heuristic_route("Operações acima de R$ 50.000") == "DATA"

    def test_action_route_gere_relatorio(self):
        assert _heuristic_route("Gere um relatório de alertas abertos") == "ACTION"

    def test_action_route_crie_alerta(self):
        assert _heuristic_route("Crie um alerta para cliente suspeito") == "ACTION"

    def test_action_route_resolver(self):
        assert _heuristic_route("Resolver alerta #3") == "ACTION"

    def test_knowledge_data_combined(self):
        assert _heuristic_route("Verifique se estamos em conformidade com o Art. 49 sobre operações em espécie") == "KNOWLEDGE+DATA"

    def test_knowledge_regulation_only(self):
        assert _heuristic_route("Qual o prazo da Resolução CMN 5.274/2025?") == "KNOWLEDGE"

    def test_knowledge_default(self):
        assert _heuristic_route("O que é PLD?") == "KNOWLEDGE"

    def test_knowledge_ciberseguranca(self):
        assert _heuristic_route("Quais são os requisitos de cibersegurança?") == "KNOWLEDGE"


class TestClassifyNoLlm:
    """_classify() should never call llm_router.generate for routing."""

    @pytest.mark.asyncio
    async def test_classify_data_does_not_call_llm(self):
        from unittest.mock import patch, AsyncMock
        with patch("src.agents.coordinator.llm_router") as mock_router:
            mock_router.generate = AsyncMock(return_value="DATA")
            coordinator = CoordinatorAgent.__new__(CoordinatorAgent)
            result = await coordinator._classify("Quantas transações não foram reportadas?")
        mock_router.generate.assert_not_called()
        assert result == "DATA"

    @pytest.mark.asyncio
    async def test_classify_knowledge_does_not_call_llm(self):
        from unittest.mock import patch, AsyncMock
        with patch("src.agents.coordinator.llm_router") as mock_router:
            mock_router.generate = AsyncMock(return_value="KNOWLEDGE")
            coordinator = CoordinatorAgent.__new__(CoordinatorAgent)
            result = await coordinator._classify("O que é compliance financeiro?")
        mock_router.generate.assert_not_called()
        assert result == "KNOWLEDGE"

    @pytest.mark.asyncio
    async def test_classify_action_does_not_call_llm(self):
        from unittest.mock import patch, AsyncMock
        with patch("src.agents.coordinator.llm_router") as mock_router:
            mock_router.generate = AsyncMock(return_value="ACTION")
            coordinator = CoordinatorAgent.__new__(CoordinatorAgent)
            result = await coordinator._classify("Crie um alerta para cliente suspeito")
        mock_router.generate.assert_not_called()
        assert result == "ACTION"

    @pytest.mark.asyncio
    async def test_classify_knowledge_data_does_not_call_llm(self):
        from unittest.mock import patch, AsyncMock
        with patch("src.agents.coordinator.llm_router") as mock_router:
            mock_router.generate = AsyncMock(return_value="KNOWLEDGE+DATA")
            coordinator = CoordinatorAgent.__new__(CoordinatorAgent)
            result = await coordinator._classify("Verifique o Art. 49 sobre transações em espécie")
        mock_router.generate.assert_not_called()
        assert result == "KNOWLEDGE+DATA"


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
