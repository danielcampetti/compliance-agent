"""Data agent — translates natural language to SQL and interprets results."""
from __future__ import annotations

import re
import sqlite3

from src.agents.base import AgentResponse
from src.database.connection import get_db
from src.database.seed import init_db
from src.llm import ollama_client

_DATA_KEYWORDS = (
    "transação", "transações", "operação", "operações", "cliente",
    "clientes", "valor", "espécie", "coaf", "alerta", "alertas",
    "reportado", "não reportado", "agência", "depósito", "saque",
    "transferência", "pix", "quantidade", "quantas", "total", "soma",
    "média", "maior", "menor", "pep", "suspeito",
)

_SCHEMA = """
Tabelas disponíveis:

transactions (id, client_name, client_cpf, transaction_type, amount, date,
              branch, channel, reported_to_coaf, pep_flag, notes)
  - transaction_type: 'deposito_especie', 'saque_especie', 'transferencia', 'pix'
  - reported_to_coaf: 0 ou 1
  - pep_flag: 0 ou 1

alerts (id, transaction_id, alert_type, severity, description, status,
        created_at, resolved_at)
  - alert_type: 'pld_especie', 'pep_transaction', 'unusual_pattern', 'missing_coaf_report'
  - severity: 'low', 'medium', 'high', 'critical'
  - status: 'open', 'investigating', 'resolved', 'false_positive'
"""

_SQL_GENERATION_PROMPT = """\
Você é um analista de dados de compliance financeiro. Gere uma query SQL para o banco SQLite.

{schema}

Regras OBRIGATÓRIAS:
1. Gere APENAS queries SELECT (nunca DELETE, UPDATE, INSERT, DROP, CREATE).
2. Use aspas simples para strings.
3. Para datas, o formato é 'YYYY-MM-DD'.
4. Responda APENAS com a query SQL, sem nenhuma explicação, sem markdown, sem ```sql.

Pergunta: {question}
SQL:"""

_INTERPRETATION_PROMPT = """\
Você é um analista de compliance financeiro. Interprete os dados abaixo em linguagem natural, \
em português, de forma objetiva e técnica.

Pergunta original: {question}

Query SQL executada: {sql}

Resultado (até 20 primeiras linhas):
{results}

Forneça uma resposta clara e direta, citando os números relevantes. Se o resultado estiver vazio, \
diga que nenhum registro foi encontrado.
"""

_SELECT_ONLY_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


class DataAgent:
    """Agent specialized in querying and analyzing compliance transaction data."""

    name = "data"

    def can_handle(self, question: str) -> float:
        q = question.lower()
        hits = sum(1 for kw in _DATA_KEYWORDS if kw in q)
        return min(hits * 0.2, 1.0)

    async def answer(self, question: str, extra_context: str = "") -> AgentResponse:
        init_db()

        sql_prompt = _SQL_GENERATION_PROMPT.format(
            schema=_SCHEMA,
            question=question + ("\n\nContexto adicional:\n" + extra_context if extra_context else ""),
        )
        raw_sql = await ollama_client.generate(sql_prompt)
        sql = _extract_sql(raw_sql)

        if not _SELECT_ONLY_RE.match(sql):
            return AgentResponse(
                agent_name=self.name,
                answer="Não foi possível gerar uma consulta SQL segura para esta pergunta.",
                confidence=0.0,
            )

        try:
            rows, columns = _execute_sql(sql)
        except sqlite3.Error as exc:
            return AgentResponse(
                agent_name=self.name,
                answer=f"Erro ao executar consulta: {exc}",
                confidence=0.0,
            )

        results_text = _format_rows(rows, columns)
        interp_prompt = _INTERPRETATION_PROMPT.format(
            question=question, sql=sql, results=results_text
        )
        interpretation = await ollama_client.generate(interp_prompt)

        return AgentResponse(
            agent_name=self.name,
            answer=interpretation,
            data={"sql": sql, "rows": [dict(zip(columns, r)) for r in rows[:20]], "total": len(rows)},
            confidence=0.85,
        )


def _extract_sql(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _execute_sql(sql: str) -> tuple[list[tuple], list[str]]:
    with get_db() as conn:
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(100)
        columns = [d[0] for d in cursor.description] if cursor.description else []
    return rows, columns


def _format_rows(rows: list[tuple], columns: list[str]) -> str:
    if not rows:
        return "(nenhum resultado)"
    header = " | ".join(columns)
    lines = [header, "-" * len(header)]
    for row in rows[:20]:
        lines.append(" | ".join(str(v) for v in row))
    if len(rows) > 20:
        lines.append(f"... e mais {len(rows) - 20} linhas")
    return "\n".join(lines)
