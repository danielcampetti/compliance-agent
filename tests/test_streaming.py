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
