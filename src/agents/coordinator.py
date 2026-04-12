"""Coordinator agent — classifies intent and routes to specialized agents."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.agents.action_agent import ActionAgent
from src.agents.base import AgentResponse
from src.agents.data_agent import DataAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.database.connection import get_db
from src.database.seed import init_db
from src.llm import llm_router

_ROUTING_PROMPT = """\
Você é um roteador de agentes de compliance financeiro. Classifique a intenção da pergunta.

Agentes disponíveis:
- KNOWLEDGE: Perguntas sobre regulamentações, normas, resoluções, circulares, artigos, prazos legais.
  Exemplos: "O que diz o Art. 49 da Circular 3.978?", "Quais são os requisitos de cibersegurança?"
- DATA: Perguntas sobre dados de transações, clientes, operações, alertas no banco de dados.
  Exemplos: "Quantas operações acima de R$50.000 temos?", "Quais clientes são PEP?"
- ACTION: Solicitações de ações concretas no sistema.
  Exemplos: "Crie um alerta", "Gere um relatório de alertas abertos", "Resolver alerta #3"
- KNOWLEDGE+DATA: Perguntas que cruzam regulamentação com dados reais.
  Exemplos: "Verifique se estamos em conformidade com o Art. 49 sobre operações em espécie"

Responda APENAS com uma das opções: KNOWLEDGE, DATA, ACTION, KNOWLEDGE+DATA

Pergunta: {question}
Classificação:"""


class CoordinatorResponse(BaseModel):
    """Full response from the coordinator including routing metadata."""

    pergunta: str
    roteamento: str
    agentes_utilizados: list[str]
    resposta_final: str
    detalhes_agentes: list[dict]
    log_id: int
    provider_utilizado: str


class CoordinatorAgent:
    """Routes questions to the appropriate specialized agent(s)."""

    def __init__(self) -> None:
        self.knowledge_agent = KnowledgeAgent()
        self.data_agent = DataAgent()
        self.action_agent = ActionAgent()

    async def process(self, question: str, provider: str = "ollama") -> CoordinatorResponse:
        """Classify and route a question to the appropriate agent(s).

        Args:
            question: Natural language question in Portuguese.
            provider: LLM backend — "ollama" (default) or "claude".

        Returns:
            CoordinatorResponse with the final answer and routing metadata.
        """
        init_db()
        routing = await self._classify(question, provider=provider)
        details: list[dict] = []
        agents_used: list[str] = []

        if routing == "KNOWLEDGE":
            response = await self.knowledge_agent.answer(question, provider=provider)
            details.append(_to_detail(response))
            agents_used.append("knowledge")
            final = response.answer

        elif routing == "DATA":
            response = await self.data_agent.answer(question, provider=provider)
            details.append(_to_detail(response))
            agents_used.append("data")
            final = response.answer

        elif routing == "ACTION":
            response = await self.action_agent.answer(question)
            details.append(_to_detail(response))
            agents_used.append("action")
            final = response.answer

        else:  # KNOWLEDGE+DATA
            k_resp = await self.knowledge_agent.answer(question, provider=provider)
            d_resp = await self.data_agent.answer(
                question, extra_context=k_resp.answer, provider=provider
            )
            details.extend([_to_detail(k_resp), _to_detail(d_resp)])
            agents_used.extend(["knowledge", "data"])
            final = (
                f"**Análise Regulatória:**\n{k_resp.answer}\n\n"
                f"**Análise de Dados:**\n{d_resp.answer}"
            )

        log_id = self._log(question, routing, final)
        return CoordinatorResponse(
            pergunta=question,
            roteamento=routing,
            agentes_utilizados=agents_used,
            resposta_final=final,
            detalhes_agentes=details,
            log_id=log_id,
            provider_utilizado=provider,
        )

    async def _classify(self, question: str, provider: str = "ollama") -> str:
        try:
            prompt = _ROUTING_PROMPT.format(question=question)
            raw = await llm_router.generate(prompt, provider=provider)
            classification = raw.strip().upper().split()[0]
            valid = {"KNOWLEDGE", "DATA", "ACTION", "KNOWLEDGE+DATA"}
            if "KNOWLEDGE" in classification and "DATA" in raw.upper():
                return "KNOWLEDGE+DATA"
            if classification in valid:
                return classification
        except Exception:
            pass
        return _heuristic_route(question)

    def _log(self, question: str, routing: str, answer: str) -> int:
        now = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO agent_log (timestamp, agent_name, action, input_summary, output_summary) "
                "VALUES (?,?,?,?,?)",
                (now, "coordinator", f"route:{routing}", question[:500], answer[:500]),
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _heuristic_route(question: str) -> str:
    q = question.lower()
    action_kws = ("criar alerta", "crie", "relatório", "atualizar", "resolver", "investigar", "reportar coaf")
    data_kws = ("transação", "operação", "cliente", "valor", "quantas", "total", "espécie", "coaf reportado")
    reg_kws = ("resolução", "circular", "artigo", "normativo", "regulamentação", "bcb", "cmn")

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
