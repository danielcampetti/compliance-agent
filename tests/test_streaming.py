"""Tests for SSE streaming endpoint and supporting LLM router."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestLlmRouterStream:

    @pytest.mark.asyncio
    async def test_generate_stream_routes_to_ollama(self):
        """generate_stream yields tokens from ollama when provider=ollama."""
        async def fake_stream(prompt):
            for token in ["Hello", " world"]:
                yield token

        with patch("src.llm.ollama_client.generate_stream", new=fake_stream):
            from src.llm import llm_router
            tokens = []
            async for t in llm_router.generate_stream("test prompt", provider="ollama"):
                tokens.append(t)
            assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_generate_stream_routes_to_claude(self):
        """generate_stream yields tokens from claude when provider=claude."""
        async def fake_stream(prompt):
            for token in ["Olá", " mundo"]:
                yield token

        with patch("src.llm.claude_client.generate_stream", new=fake_stream), \
             patch("src.llm.llm_router.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-test"
            from src.llm import llm_router
            tokens = []
            async for t in llm_router.generate_stream("test prompt", provider="claude"):
                tokens.append(t)
            assert tokens == ["Olá", " mundo"]


class TestKnowledgeAgentPrepare:

    @pytest.mark.asyncio
    async def test_prepare_returns_prompt_and_chunks(self):
        """prepare() returns (prompt_str, chunks) without calling the LLM."""
        mock_chunks = [MagicMock(metadata={"source": "doc.pdf", "page": 1})]
        with patch("src.agents.knowledge_agent.retrieve", return_value=mock_chunks), \
             patch("src.agents.knowledge_agent.build_prompt", return_value="assembled prompt"):
            from src.agents.knowledge_agent import KnowledgeAgent
            agent = KnowledgeAgent()
            prompt, chunks = await agent.prepare("qual o prazo?")
            assert prompt == "assembled prompt"
            assert chunks is mock_chunks

    @pytest.mark.asyncio
    async def test_prepare_passes_conversation_history_to_build_prompt(self):
        """prepare() forwards conversation_history to build_prompt."""
        mock_chunks = [MagicMock(metadata={"source": "doc.pdf", "page": 1})]
        history = [{"role": "user", "content": "anterior"}]
        with patch("src.agents.knowledge_agent.retrieve", return_value=mock_chunks), \
             patch("src.agents.knowledge_agent.build_prompt", return_value="p") as mock_bp:
            from src.agents.knowledge_agent import KnowledgeAgent
            agent = KnowledgeAgent()
            await agent.prepare("question", conversation_history=history)
            mock_bp.assert_called_once_with("question", mock_chunks, conversation_history=history)

    @pytest.mark.asyncio
    async def test_prepare_returns_none_when_no_chunks(self):
        """prepare() returns (None, []) when retrieve finds nothing."""
        with patch("src.agents.knowledge_agent.retrieve", return_value=[]):
            from src.agents.knowledge_agent import KnowledgeAgent
            agent = KnowledgeAgent()
            prompt, chunks = await agent.prepare("sem resultado")
            assert prompt is None
            assert chunks == []


class TestCoordinatorProcessStream:

    @pytest.mark.asyncio
    async def test_process_stream_yields_metadata_token_done(self):
        """process_stream yields metadata, at least one token, and done events."""
        from src.agents.coordinator import CoordinatorAgent

        async def fake_token_stream(prompt, provider="ollama"):
            yield "Resposta"

        with patch("src.agents.coordinator.CoordinatorAgent._classify",
                   new_callable=AsyncMock, return_value="KNOWLEDGE"), \
             patch("src.agents.coordinator.KnowledgeAgent") as MockKA, \
             patch("src.agents.coordinator.llm_router") as mock_router, \
             patch("src.agents.coordinator.audit") as mock_audit, \
             patch("src.agents.coordinator.init_db"):
            mock_audit.generate_session_id.return_value = "abc12345"
            mock_audit.log_interaction = AsyncMock(return_value=1)
            mock_audit.classify_query.return_value = "public"
            MockKA.return_value.prepare = AsyncMock(
                return_value=("prompt text", [MagicMock(metadata={"source": "doc.pdf", "page": 1})])
            )
            mock_router.generate_stream = fake_token_stream

            coordinator = CoordinatorAgent()
            events = []
            async for event in coordinator.process_stream("qual o prazo?"):
                events.append(event)

        parsed = [
            json.loads(e.replace("data: ", "").strip())
            for e in events if e.startswith("data:")
        ]
        event_types = [p["type"] for p in parsed]
        assert "metadata" in event_types
        assert "token" in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_process_stream_done_has_full_response(self):
        """done event contains the concatenation of all token events."""
        from src.agents.coordinator import CoordinatorAgent

        async def fake_token_stream(prompt, provider="ollama"):
            yield "Olá"
            yield " mundo"

        with patch("src.agents.coordinator.CoordinatorAgent._classify",
                   new_callable=AsyncMock, return_value="KNOWLEDGE"), \
             patch("src.agents.coordinator.KnowledgeAgent") as MockKA, \
             patch("src.agents.coordinator.llm_router") as mock_router, \
             patch("src.agents.coordinator.audit") as mock_audit, \
             patch("src.agents.coordinator.init_db"):
            mock_audit.generate_session_id.return_value = "sess1"
            mock_audit.log_interaction = AsyncMock(return_value=1)
            mock_audit.classify_query.return_value = "public"
            MockKA.return_value.prepare = AsyncMock(return_value=("prompt", []))
            mock_router.generate_stream = fake_token_stream

            coordinator = CoordinatorAgent()
            events = []
            async for event in coordinator.process_stream("test"):
                events.append(event)

        done_events = [
            json.loads(e.replace("data: ", "").strip())
            for e in events
            if e.startswith("data:") and '"type": "done"' in e
        ]
        assert len(done_events) == 1
        assert done_events[0]["full_response"] == "Olá mundo"


class TestStreamEndpoint:

    def _make_token(self, role: str = "analyst") -> str:
        """Create a JWT for test auth."""
        from src.api.auth import create_access_token
        uid, uname = (2, "analista") if role == "analyst" else (1, "admin")
        return create_access_token(uid, uname, role)

    def test_stream_endpoint_returns_event_stream(self):
        """POST /agent/stream returns text/event-stream content type."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        async def fake_stream(question, provider="ollama", user_id=None,
                              username=None, conversation_history=None):
            yield 'data: {"type": "metadata", "roteamento": "KNOWLEDGE", "agentes_utilizados": ["knowledge"]}\n\n'
            yield 'data: {"type": "token", "content": "Olá"}\n\n'
            yield 'data: {"type": "done", "pii_detected": false, "data_classification": "public", "session_id": "abc", "full_response": "Olá"}\n\n'

        with patch("src.api.main.CoordinatorAgent") as MockCoord:
            MockCoord.return_value.process_stream = fake_stream
            client = TestClient(app)
            token = self._make_token()
            res = client.post(
                "/agent/stream",
                json={"pergunta": "test"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("content-type", "")

    def test_stream_endpoint_yields_expected_event_types(self):
        """POST /agent/stream body contains metadata, token, and done events."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        async def fake_stream(question, provider="ollama", user_id=None,
                              username=None, conversation_history=None):
            yield 'data: {"type": "metadata", "roteamento": "DATA", "agentes_utilizados": ["data"]}\n\n'
            yield 'data: {"type": "token", "content": "Resultado"}\n\n'
            yield 'data: {"type": "done", "pii_detected": false, "data_classification": "confidential", "session_id": "x", "full_response": "Resultado"}\n\n'

        with patch("src.api.main.CoordinatorAgent") as MockCoord:
            MockCoord.return_value.process_stream = fake_stream
            client = TestClient(app)
            token = self._make_token()
            res = client.post(
                "/agent/stream",
                json={"pergunta": "quantas transacoes?"},
                headers={"Authorization": f"Bearer {token}"},
            )
            lines = [l for l in res.text.split("\n") if l.startswith("data: ")]
            events = [json.loads(l[6:]) for l in lines if l[6:].strip()]
            event_types = [e["type"] for e in events]
            assert "metadata" in event_types
            assert "token" in event_types
            assert "done" in event_types

    def test_stream_endpoint_requires_auth(self):
        """POST /agent/stream returns 401/403 without JWT."""
        from fastapi.testclient import TestClient
        from src.api.main import app
        client = TestClient(app)
        res = client.post("/agent/stream", json={"pergunta": "test"})
        assert res.status_code in (401, 403)

    def test_stream_saves_agent_used_and_data_classification(self):
        """svc.add_message is called with correct agent_used and data_classification."""
        from fastapi.testclient import TestClient
        from src.api.main import app

        async def fake_stream(question, provider="ollama", user_id=None,
                              username=None, conversation_history=None):
            yield 'data: {"type": "metadata", "roteamento": "KNOWLEDGE", "agentes_utilizados": ["knowledge"]}\n\n'
            yield 'data: {"type": "token", "content": "Ol\u00e1"}\n\n'
            yield 'data: {"type": "done", "pii_detected": false, "data_classification": "public", "session_id": "abc", "full_response": "Ol\u00e1"}\n\n'

        mock_conv = MagicMock()
        mock_svc = MagicMock()
        mock_svc.get_by_id.return_value = mock_conv
        mock_svc.get_context_messages.return_value = []

        with patch("src.api.main.CoordinatorAgent") as MockCoord, \
             patch("src.api.main.ConversationService", return_value=mock_svc):
            MockCoord.return_value.process_stream = fake_stream
            client = TestClient(app)
            token = self._make_token()
            client.post(
                "/agent/stream",
                json={"pergunta": "test", "conversation_id": 1},
                headers={"Authorization": f"Bearer {token}"},
            )

        # add_message is called twice: once for the user turn, once for the assistant.
        # Verify the assistant call has the correct metadata fields.
        mock_svc.add_message.assert_called_with(
            1,
            "assistant",
            "Olá",
            agent_used="knowledge",
            provider="ollama",
            data_classification="public",
            pii_detected=False,
        )

    def test_original_agent_endpoint_still_works(self):
        """POST /agent still returns JSON (backward compat)."""
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.agents.coordinator import CoordinatorResponse

        mock_response = CoordinatorResponse(
            pergunta="test", roteamento="KNOWLEDGE",
            agentes_utilizados=["knowledge"], resposta_final="OK",
            detalhes_agentes=[], log_id=1, provider_utilizado="ollama",
            pii_detected=False, data_classification="public", session_id="x",
        )
        with patch("src.api.main.CoordinatorAgent") as MockCoord:
            MockCoord.return_value.process = AsyncMock(return_value=mock_response)
            client = TestClient(app)
            token = self._make_token()
            res = client.post(
                "/agent",
                json={"pergunta": "test"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 200
            assert res.json()["resposta_final"] == "OK"
