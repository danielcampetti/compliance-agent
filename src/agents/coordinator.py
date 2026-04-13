"""Coordinator agent — classifies intent and routes to specialized agents."""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from typing import AsyncGenerator, Optional

from pydantic import BaseModel

from src.agents.action_agent import ActionAgent
from src.agents.base import AgentResponse
from src.agents.data_agent import DataAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.database.connection import get_db
from src.database.seed import init_db
from src.governance import audit
from src.governance.pii_detector import detect_pii, has_pii
from src.llm import llm_router

_LGPD_FOOTER = (
    "\n\n---\n🔒 Esta resposta contém dados pessoais protegidos pela LGPD. "
    "Uso restrito a fins de compliance."
)


class CoordinatorResponse(BaseModel):
    """Full response from the coordinator including routing metadata."""

    pergunta: str
    roteamento: str
    agentes_utilizados: list[str]
    resposta_final: str
    detalhes_agentes: list[dict]
    log_id: int
    provider_utilizado: str
    pii_detected: bool = False
    data_classification: str = "public"
    session_id: str = ""


class CoordinatorAgent:
    """Routes questions to the appropriate specialized agent(s)."""

    def __init__(self) -> None:
        self.knowledge_agent = KnowledgeAgent()
        self.data_agent = DataAgent()
        self.action_agent = ActionAgent()

    async def process(
        self,
        question: str,
        provider: str = "ollama",
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> CoordinatorResponse:
        """Classify and route a question to the appropriate agent(s).

        Args:
            question: Natural language question in Portuguese.
            provider: LLM backend — "ollama" (default) or "claude".
            user_id: Authenticated user ID for audit logging.
            username: Authenticated username for audit logging.
            conversation_history: Prior conversation messages for context.

        Returns:
            CoordinatorResponse with the final answer and routing metadata.
        """
        init_db()
        session_id = audit.generate_session_id()
        routing = await self._classify(question)
        details: list[dict] = []
        agents_used: list[str] = []
        model = "claude-sonnet-4-6" if provider == "claude" else "llama3:8b"

        if routing == "KNOWLEDGE":
            response = await self.knowledge_agent.answer(
                question, provider=provider,
                conversation_history=conversation_history,
            )
            details.append(_to_detail(response))
            agents_used.append("knowledge")
            final = response.answer

            pii_found = bool(detect_pii(response.answer)) or has_pii(question)
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="knowledge", action="answer",
                input_text=question, output_text=response.answer,
                provider=provider, model=model, tokens_used=0,
                chunks_count=getattr(response, "chunks_count", 0),
                user_id=user_id, username=username,
            )
            classification = audit.classify_query("knowledge", pii_found, question)

        elif routing == "DATA":
            response = await self.data_agent.answer(question, provider=provider)
            details.append(_to_detail(response))
            agents_used.append("data")
            final = response.answer

            pii_found = bool(detect_pii(response.answer)) or has_pii(question)
            if pii_found:
                final = final + _LGPD_FOOTER

            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="data", action="answer",
                input_text=question, output_text=response.answer,
                provider=provider, model=model, tokens_used=0,
                chunks_count=getattr(response, "chunks_count", 0),
                user_id=user_id, username=username,
            )
            classification = audit.classify_query("data", pii_found, question)

        elif routing == "ACTION":
            response = await self.action_agent.answer(question)
            details.append(_to_detail(response))
            agents_used.append("action")
            final = response.answer

            pii_found = bool(detect_pii(response.answer)) or has_pii(question)
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="action", action="answer",
                input_text=question, output_text=response.answer,
                provider=provider, model=model, tokens_used=0,
                chunks_count=getattr(response, "chunks_count", 0),
                user_id=user_id, username=username,
            )
            classification = audit.classify_query("action", pii_found, question)

        else:  # KNOWLEDGE+DATA
            k_resp = await self.knowledge_agent.answer(
                question, provider=provider,
                conversation_history=conversation_history,
            )
            d_resp = await self.data_agent.answer(
                question, extra_context=k_resp.answer, provider=provider
            )
            details.extend([_to_detail(k_resp), _to_detail(d_resp)])
            agents_used.extend(["knowledge", "data"])
            final = (
                f"**Análise Regulatória:**\n{k_resp.answer}\n\n"
                f"**Análise de Dados:**\n{d_resp.answer}"
            )

            pii_found = bool(detect_pii(final)) or has_pii(question)
            if pii_found:
                final = final + _LGPD_FOOTER

            await audit.log_interaction(
                session_id=session_id, agent_name="knowledge", action="answer",
                input_text=question, output_text=k_resp.answer,
                provider=provider, model=model, tokens_used=0,
                chunks_count=getattr(k_resp, "chunks_count", 0),
                user_id=user_id, username=username,
            )
            log_id = await audit.log_interaction(
                session_id=session_id, agent_name="data", action="answer",
                input_text=question, output_text=d_resp.answer,
                provider=provider, model=model, tokens_used=0,
                chunks_count=getattr(d_resp, "chunks_count", 0),
                user_id=user_id, username=username,
            )
            k_class = audit.classify_query("knowledge", pii_found, question)
            d_class = audit.classify_query("data", pii_found, question)
            _order = ["public", "internal", "confidential", "restricted"]
            classification = (
                k_class if _order.index(k_class) >= _order.index(d_class) else d_class
            )

        return CoordinatorResponse(
            pergunta=question,
            roteamento=routing,
            agentes_utilizados=agents_used,
            resposta_final=final,
            detalhes_agentes=details,
            log_id=log_id,
            provider_utilizado=provider,
            pii_detected=pii_found,
            data_classification=classification,
            session_id=session_id,
        )

    async def process_stream(
        self,
        question: str,
        provider: str = "ollama",
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream the agent response as SSE events.

        Yields SSE-formatted strings for each event:
        - metadata: routing info, sent first
        - sources: chunk references (KNOWLEDGE routes only)
        - token: individual LLM tokens (KNOWLEDGE streams one-by-one;
                 DATA/ACTION send a single token with the full answer)
        - sql: SQL details (DATA agent only)
        - actions: action list (ACTION agent only)
        - done: final metadata including full_response for persistence
        - error: on exception

        Args:
            question: Natural language question in Portuguese.
            provider: LLM backend — "ollama" (default) or "claude".
            user_id: Authenticated user ID for audit logging.
            username: Authenticated username for audit logging.
            conversation_history: Prior conversation messages for context injection.
        """
        init_db()
        session_id = audit.generate_session_id()
        routing = await self._classify(question)
        model = "claude-sonnet-4-6" if provider == "claude" else "llama3:8b"

        _route_agents = {
            "KNOWLEDGE": ["knowledge"],
            "DATA": ["data"],
            "ACTION": ["action"],
            "KNOWLEDGE+DATA": ["knowledge", "data"],
        }
        agents_used = _route_agents.get(routing, ["knowledge"])

        yield f'data: {json.dumps({"type": "metadata", "roteamento": routing, "agentes_utilizados": agents_used})}\n\n'

        try:
            if routing == "KNOWLEDGE":
                prompt, chunks = await self.knowledge_agent.prepare(
                    question, conversation_history=conversation_history
                )

                if prompt is None:
                    msg = "Nenhum documento relevante encontrado para esta pergunta."
                    yield f'data: {json.dumps({"type": "token", "content": msg})}\n\n'
                    yield f'data: {json.dumps({"type": "done", "pii_detected": False, "data_classification": "public", "session_id": session_id, "full_response": msg})}\n\n'
                    return

                sources = list({
                    f"{c.metadata.get('source', 'Desconhecido')}, p. {c.metadata.get('page', '?')}"
                    for c in chunks
                })
                yield f'data: {json.dumps({"type": "sources", "chunks": sources})}\n\n'

                full_response = ""
                async for token in llm_router.generate_stream(prompt, provider=provider):
                    full_response += token
                    yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'

                pii_found = bool(detect_pii(full_response)) or has_pii(question)
                await audit.log_interaction(
                    session_id=session_id, agent_name="knowledge",
                    action="stream_answer", input_text=question,
                    output_text=full_response, provider=provider, model=model,
                    tokens_used=0, chunks_count=len(chunks),
                    user_id=user_id, username=username,
                )
                classification = audit.classify_query("knowledge", pii_found, question)
                yield f'data: {json.dumps({"type": "done", "pii_detected": pii_found, "data_classification": classification, "session_id": session_id, "full_response": full_response})}\n\n'

            elif routing == "DATA":
                response = await self.data_agent.answer(question, provider=provider)
                yield f'data: {json.dumps({"type": "token", "content": response.answer})}\n\n'

                if response.data and response.data.get("sql"):
                    yield f'data: {json.dumps({"type": "sql", "sql": response.data.get("sql"), "total": response.data.get("total")})}\n\n'

                pii_found = bool(detect_pii(response.answer)) or has_pii(question)
                await audit.log_interaction(
                    session_id=session_id, agent_name="data",
                    action="stream_answer", input_text=question,
                    output_text=response.answer, provider=provider, model=model,
                    tokens_used=0, chunks_count=0,
                    user_id=user_id, username=username,
                )
                classification = audit.classify_query("data", pii_found, question)
                yield f'data: {json.dumps({"type": "done", "pii_detected": pii_found, "data_classification": classification, "session_id": session_id, "full_response": response.answer})}\n\n'

            elif routing == "ACTION":
                response = await self.action_agent.answer(question)
                yield f'data: {json.dumps({"type": "token", "content": response.answer})}\n\n'

                if response.actions_taken:
                    yield f'data: {json.dumps({"type": "actions", "acoes": response.actions_taken})}\n\n'

                pii_found = bool(detect_pii(response.answer)) or has_pii(question)
                await audit.log_interaction(
                    session_id=session_id, agent_name="action",
                    action="stream_answer", input_text=question,
                    output_text=response.answer, provider=provider, model=model,
                    tokens_used=0, chunks_count=0,
                    user_id=user_id, username=username,
                )
                classification = audit.classify_query("action", pii_found, question)
                yield f'data: {json.dumps({"type": "done", "pii_detected": pii_found, "data_classification": classification, "session_id": session_id, "full_response": response.answer})}\n\n'

            else:  # KNOWLEDGE+DATA
                prompt, chunks = await self.knowledge_agent.prepare(
                    question, conversation_history=conversation_history
                )
                sources = list({
                    f"{c.metadata.get('source', 'Desconhecido')}, p. {c.metadata.get('page', '?')}"
                    for c in (chunks or [])
                })
                if sources:
                    yield f'data: {json.dumps({"type": "sources", "chunks": sources})}\n\n'

                yield f'data: {json.dumps({"type": "token", "content": "**Análise Regulatória:**\n"})}\n\n'

                full_knowledge = ""
                if prompt:
                    async for token in llm_router.generate_stream(prompt, provider=provider):
                        full_knowledge += token
                        yield f'data: {json.dumps({"type": "token", "content": token})}\n\n'

                yield f'data: {json.dumps({"type": "token", "content": "\n\n**Análise de Dados:**\n"})}\n\n'

                d_resp = await self.data_agent.answer(
                    question, extra_context=full_knowledge, provider=provider
                )
                yield f'data: {json.dumps({"type": "token", "content": d_resp.answer})}\n\n'

                if d_resp.data and d_resp.data.get("sql"):
                    yield f'data: {json.dumps({"type": "sql", "sql": d_resp.data.get("sql"), "total": d_resp.data.get("total")})}\n\n'

                full_response = (
                    f"**Análise Regulatória:**\n{full_knowledge}\n\n"
                    f"**Análise de Dados:**\n{d_resp.answer}"
                )
                pii_found = bool(detect_pii(full_response)) or has_pii(question)

                await audit.log_interaction(
                    session_id=session_id, agent_name="knowledge",
                    action="stream_answer", input_text=question,
                    output_text=full_knowledge, provider=provider, model=model,
                    tokens_used=0, chunks_count=len(chunks or []),
                    user_id=user_id, username=username,
                )
                await audit.log_interaction(
                    session_id=session_id, agent_name="data",
                    action="stream_answer", input_text=question,
                    output_text=d_resp.answer, provider=provider, model=model,
                    tokens_used=0, chunks_count=0,
                    user_id=user_id, username=username,
                )
                k_class = audit.classify_query("knowledge", pii_found, question)
                d_class = audit.classify_query("data", pii_found, question)
                _order = ["public", "internal", "confidential", "restricted"]
                classification = k_class if _order.index(k_class) >= _order.index(d_class) else d_class

                yield f'data: {json.dumps({"type": "done", "pii_detected": pii_found, "data_classification": classification, "session_id": session_id, "full_response": full_response})}\n\n'

        except Exception as exc:
            yield f'data: {json.dumps({"type": "error", "message": str(exc)})}\n\n'

    async def _classify(self, question: str) -> str:
        # Short-circuit: conversational/meta questions always go to KNOWLEDGE
        if _is_conversational(question):
            return "KNOWLEDGE"

        # Keyword classifier — covers 95%+ of queries with no LLM call
        keyword_result = _heuristic_route(question)
        if keyword_result != "KNOWLEDGE":
            # DATA, ACTION, or KNOWLEDGE+DATA was detected — return immediately
            return keyword_result

        # For pure KNOWLEDGE questions (no data/action keywords detected),
        # also return immediately — the LLM would just confirm KNOWLEDGE.
        # LLM routing is disabled: it added 5+ seconds of latency with no benefit.
        return "KNOWLEDGE"

    def _log(self, question: str, routing: str, answer: str) -> int:
        now = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO agent_log (timestamp, agent_name, action, input_summary, output_summary) "
                "VALUES (?,?,?,?,?)",
                (now, "coordinator", f"route:{routing}", question[:500], answer[:500]),
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _is_conversational(question: str) -> bool:
    """Return True for meta/conversational questions that refer to the conversation itself.

    These must route to KNOWLEDGE regardless of LLM classification, because only
    KnowledgeAgent receives the conversation_history injected into build_prompt().
    Input is accent-normalized before matching so users can omit diacritics.
    """
    q = unicodedata.normalize("NFD", question.lower())
    q = "".join(c for c in q if unicodedata.category(c) != "Mn")  # strip combining marks

    patterns = (
        "pergunta anterior", "pergunta passada",
        "o que voce disse", "o que foi dito", "voce disse antes",
        "explique melhor", "pode explicar melhor", "mais detalhes sobre isso",
        "resuma nossa conversa", "resuma o que discutimos", "resuma a conversa",
        "o que discutimos", "nossa conversa",
        "me lembra", "pode repetir", "repita o que",
        "contexto da conversa", "historico da conversa",
        "qual foi a ultima", "qual foi o ultimo",
        "como assim", "nao entendi", "elabore mais",
    )
    return any(p in q for p in patterns)


def _heuristic_route(question: str) -> str:
    """Route by keyword matching. Accent-insensitive, case-insensitive.

    Priority: ACTION > KNOWLEDGE+DATA > DATA > KNOWLEDGE (default).
    """
    q = unicodedata.normalize("NFD", question.lower())
    q = "".join(c for c in q if unicodedata.category(c) != "Mn")

    action_kws = (
        "gere relatorio", "gere um relatorio",
        "crie alerta", "criar alerta", "crie um alerta",
        "atualizar status", "atualizar alerta",
        "marcar como reportada", "marcar como reportado",
        "relatorio de alertas", "relatorio de transacoes",
        "resolver alerta", "resolver o alerta",
        "investigar", "reportar coaf",
        "atualizar",
    )
    data_kws = (
        "transacao", "transacoes",
        "operacao", "operacoes", "operacoes em especie",
        "coaf", "reportada", "nao reportada", "nao foram reportadas",
        "banco de dados",
        "quantas", "quantos",
        "cliente", "clientes", "pep",
        "valor total", "valor medio", "valor maximo",
        "r$", "reais",
        "especie", "em especie",
        "alertas abertos", "alertas pendentes",
    )
    reg_kws = (
        "resolucao", "circular", "artigo", "art.", "normativo",
        "regulamentacao", "bcb", "cmn",
        "instrucao normativa", "deliberacao",
        "prazo", "obrigacao", "obrigacoes",
    )

    is_action = any(kw in q for kw in action_kws)
    is_data = any(kw in q for kw in data_kws)
    is_reg = any(kw in q for kw in reg_kws)

    if is_action:
        return "ACTION"
    if is_reg and is_data:
        return "KNOWLEDGE+DATA"
    if is_data:
        return "DATA"
    return "KNOWLEDGE"


def _to_detail(r: AgentResponse) -> dict:
    return {
        "agente": r.agent_name,
        "resposta": r.answer,
        "fontes": r.sources,
        "dados": r.data,
        "acoes": r.actions_taken,
    }
