"""Action agent — creates alerts, updates statuses, generates reports."""
from __future__ import annotations

import re
from datetime import datetime

from src.agents.base import AgentResponse
from src.database.connection import get_db
from src.database.seed import init_db

_ACTION_KEYWORDS = (
    "criar alerta", "crie alerta", "criar um alerta", "crie um alerta",
    "atualizar status", "atualize status", "atualizar alerta",
    "gerar relatório", "gere relatório", "relatório de alertas",
    "marcar como reportado", "marque como reportado", "reportar coaf",
    "fechar alerta", "resolver alerta", "investigar alerta",
)


class ActionAgent:
    """Agent specialized in executing compliance actions."""

    name = "action"

    def can_handle(self, question: str) -> float:
        q = question.lower()
        hits = sum(1 for kw in _ACTION_KEYWORDS if kw in q)
        return min(hits * 0.5, 1.0)

    async def answer(self, question: str) -> AgentResponse:
        init_db()
        q = question.lower()

        if "relatório" in q and "alerta" in q:
            return await self._report_open_alerts()
        if "criar alerta" in q or ("crie" in q and "alerta" in q):
            return await self._create_alert(question)
        if any(w in q for w in ("resolver", "resolvido", "fechar")):
            return await self._update_alert_status(question, "resolved")
        if "investigar" in q or "investigando" in q:
            return await self._update_alert_status(question, "investigating")
        if "reportar coaf" in q or "marcar como reportado" in q or ("marque" in q and "reportado" in q):
            return await self._mark_coaf_reported(question)

        return AgentResponse(
            agent_name=self.name,
            answer="Ação não reconhecida. Ações suportadas: gerar relatório de alertas, "
                   "criar alerta, atualizar status de alerta, marcar transação como reportada ao COAF.",
            confidence=0.0,
        )

    async def _report_open_alerts(self) -> AgentResponse:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, alert_type, severity, description, status, created_at "
                "FROM alerts WHERE status != 'resolved' ORDER BY severity DESC, created_at DESC"
            ).fetchall()

        if not rows:
            summary = "Não há alertas abertos no momento."
        else:
            lines = [f"Relatório de alertas abertos/em investigação ({len(rows)} total):\n"]
            for r in rows:
                lines.append(
                    f"  • [ID {r['id']}] [{r['severity'].upper()}] {r['alert_type']} "
                    f"— Status: {r['status']}\n    {r['description']}"
                )
            summary = "\n".join(lines)

        self._log("action", "report_open_alerts", "relatório solicitado", f"{len(rows)} alertas")
        return AgentResponse(
            agent_name=self.name,
            answer=summary,
            actions_taken=["Gerou relatório de alertas abertos"],
            data={"total_open": len(rows)},
            confidence=1.0,
        )

    async def _create_alert(self, question: str) -> AgentResponse:
        now = datetime.utcnow().isoformat()
        tx_match = re.search(r"transa[cç][aã]o\s+(?:id\s+)?(\d+)", question, re.IGNORECASE)
        tx_id = int(tx_match.group(1)) if tx_match else None

        with get_db() as conn:
            conn.execute(
                "INSERT INTO alerts (transaction_id, alert_type, severity, description, status, created_at) "
                "VALUES (?, ?, ?, ?, 'open', ?)",
                (tx_id, "unusual_pattern", "medium", question[:500], now),
            )
            alert_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        self._log("action", "create_alert", question[:200], f"alerta {alert_id} criado")
        return AgentResponse(
            agent_name=self.name,
            answer=f"Alerta #{alert_id} criado com sucesso (status: aberto, severidade: médio).",
            actions_taken=[f"Criou alerta #{alert_id}"],
            data={"alert_id": alert_id},
            confidence=1.0,
        )

    async def _update_alert_status(self, question: str, new_status: str) -> AgentResponse:
        id_match = re.search(r"alerta\s+#?(\d+)", question, re.IGNORECASE)
        if not id_match:
            return AgentResponse(
                agent_name=self.name,
                answer="Informe o ID do alerta. Exemplo: 'Resolver alerta #3'.",
                confidence=0.0,
            )
        alert_id = int(id_match.group(1))
        now = datetime.utcnow().isoformat()

        with get_db() as conn:
            resolved_at = now if new_status == "resolved" else None
            conn.execute(
                "UPDATE alerts SET status=?, resolved_at=? WHERE id=?",
                (new_status, resolved_at, alert_id),
            )

        self._log("action", f"update_alert_status_{new_status}", f"alerta {alert_id}", f"status → {new_status}")
        return AgentResponse(
            agent_name=self.name,
            answer=f"Status do alerta #{alert_id} atualizado para '{new_status}'.",
            actions_taken=[f"Atualizou alerta #{alert_id} → {new_status}"],
            confidence=1.0,
        )

    async def _mark_coaf_reported(self, question: str) -> AgentResponse:
        id_match = re.search(r"transa[cç][aã]o\s+#?(\d+)", question, re.IGNORECASE)
        if not id_match:
            return AgentResponse(
                agent_name=self.name,
                answer="Informe o ID da transação. Exemplo: 'Marcar transação #4 como reportada ao COAF'.",
                confidence=0.0,
            )
        tx_id = int(id_match.group(1))

        with get_db() as conn:
            conn.execute("UPDATE transactions SET reported_to_coaf=1 WHERE id=?", (tx_id,))

        self._log("action", "mark_coaf_reported", f"transação {tx_id}", "reported_to_coaf=1")
        return AgentResponse(
            agent_name=self.name,
            answer=f"Transação #{tx_id} marcada como reportada ao COAF.",
            actions_taken=[f"Marcou transação #{tx_id} como reportada ao COAF"],
            confidence=1.0,
        )

    def _log(self, agent: str, action: str, input_summary: str, output_summary: str) -> None:
        now = datetime.utcnow().isoformat()
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO agent_log (timestamp, agent_name, action, input_summary, output_summary) "
                    "VALUES (?,?,?,?,?)",
                    (now, agent, action, input_summary[:500], output_summary[:500]),
                )
        except Exception:
            pass
