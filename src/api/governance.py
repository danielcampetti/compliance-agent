"""LGPD Governance API endpoints.

Provides:
  GET  /governance/dashboard        — PII metrics, classification breakdown, retention alerts
  GET  /governance/daily-stats      — time-series data for the last 30 days (line chart)
  GET  /governance/audit-log        — paginated audit log (masked fields only)
  GET  /governance/retention-report — retention status report
  POST /governance/purge-expired    — soft-purge PII records past retention date
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.api.auth import TokenUser, require_role
from src.database.connection import get_db
from src.database.setup import create_tables
from src.governance.retention import get_retention_report, purge_expired_pii

governance_router = APIRouter(prefix="/governance", tags=["governance"])


@governance_router.get("/daily-stats")
async def governance_daily_stats(
    _: TokenUser = Depends(require_role("manager")),
) -> dict:
    """Return daily query and PII counts for the last 30 days (time-series for line chart)."""
    create_tables()
    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT date, total_queries, queries_with_pii,
                   classification_public, classification_internal,
                   classification_confidential, classification_restricted,
                   pii_cpf_count, pii_name_count, pii_money_count
            FROM governance_daily_stats
            WHERE date >= ?
            ORDER BY date ASC
            """,
            (thirty_days_ago,),
        ).fetchall()
    return {
        "dias": [
            {
                "date": r["date"],
                "total_queries": r["total_queries"],
                "queries_with_pii": r["queries_with_pii"],
                "classification_public": r["classification_public"],
                "classification_internal": r["classification_internal"],
                "classification_confidential": r["classification_confidential"],
                "classification_restricted": r["classification_restricted"],
                "pii_cpf_count": r["pii_cpf_count"],
                "pii_name_count": r["pii_name_count"],
                "pii_money_count": r["pii_money_count"],
            }
            for r in rows
        ]
    }


@governance_router.get("/dashboard")
async def governance_dashboard(
    _: TokenUser = Depends(require_role("manager")),
) -> dict:
    """Return PII metrics, classification breakdown, and retention alerts for the last 30 days."""
    create_tables()
    today = date.today().isoformat()
    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()

    with get_db() as conn:
        # --- Metrics from governance_daily_stats ---
        stats_rows = conn.execute(
            """
            SELECT * FROM governance_daily_stats
            WHERE date >= ?
            ORDER BY date DESC
            """,
            (thirty_days_ago,),
        ).fetchall()

        total_consultas = sum(r["total_queries"] for r in stats_rows)
        consultas_com_pii = sum(r["queries_with_pii"] for r in stats_rows)
        percentual_pii = round(
            (consultas_com_pii / total_consultas * 100) if total_consultas > 0 else 0.0, 1
        )

        por_classificacao = {
            "public": sum(r["classification_public"] for r in stats_rows),
            "internal": sum(r["classification_internal"] for r in stats_rows),
            "confidential": sum(r["classification_confidential"] for r in stats_rows),
            "restricted": sum(r["classification_restricted"] for r in stats_rows),
        }

        pii_por_tipo = {
            "cpf": sum(r["pii_cpf_count"] for r in stats_rows),
            "name": sum(r["pii_name_count"] for r in stats_rows),
            "money": sum(r["pii_money_count"] for r in stats_rows),
        }

        # --- Per-agent breakdown from audit_log ---
        agent_rows = conn.execute(
            """
            SELECT agent_name, COUNT(*) as cnt
            FROM audit_log
            WHERE timestamp >= ?
            GROUP BY agent_name
            """,
            (thirty_days_ago + "T00:00:00",),
        ).fetchall()
        por_agente = {r["agent_name"]: r["cnt"] for r in agent_rows}

        # --- Phone and email counts from audit_log pii_types_detected JSON ---
        pii_rows = conn.execute(
            """
            SELECT pii_types_detected FROM audit_log
            WHERE pii_types_detected IS NOT NULL
              AND timestamp >= ?
            """,
            (thirty_days_ago + "T00:00:00",),
        ).fetchall()
        phone_count = 0
        email_count = 0
        for r in pii_rows:
            try:
                pii_data = json.loads(r["pii_types_detected"])
                phone_count += pii_data.get("phone", 0)
                email_count += pii_data.get("email", 0)
            except (json.JSONDecodeError, TypeError):
                pass
        pii_por_tipo["phone"] = phone_count
        pii_por_tipo["email"] = email_count

        # --- Retention summary ---
        registros_com_pii = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE input_has_pii = TRUE"
        ).fetchone()[0]
        registros_purgados = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE pii_purged = TRUE"
        ).fetchone()[0]

        in_30_days = (date.today() + timedelta(days=30)).isoformat()
        expirando = conn.execute(
            """
            SELECT COUNT(*) FROM audit_log
            WHERE retention_expires_at <= ?
              AND retention_expires_at > ?
              AND pii_purged = FALSE
              AND input_has_pii = TRUE
            """,
            (in_30_days, today),
        ).fetchone()[0]

        oldest_row = conn.execute(
            "SELECT MIN(DATE(timestamp)) FROM audit_log"
        ).fetchone()[0]

    # --- Alerts ---
    alertas = []
    if expirando > 0:
        alertas.append(
            f"⚠️ {expirando} registro(s) com PII irão expirar nos próximos 30 dias."
        )
    if not alertas:
        alertas.append("Nenhum alerta de governança ativo")

    return {
        "periodo": "últimos 30 dias",
        "metricas": {
            "total_consultas": total_consultas,
            "consultas_com_pii": consultas_com_pii,
            "percentual_pii": percentual_pii,
            "por_classificacao": por_classificacao,
            "por_agente": por_agente,
            "pii_por_tipo": pii_por_tipo,
        },
        "retencao": {
            "registros_com_pii": registros_com_pii,
            "registros_pii_purgados": registros_purgados,
            "registros_expirando_30_dias": expirando,
            "registro_mais_antigo": oldest_row,
        },
        "alertas": alertas,
    }


@governance_router.get("/audit-log")
async def get_audit_log(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    classification: Optional[str] = None,
    agent: Optional[str] = None,
    has_pii: Optional[bool] = None,
    username: Optional[str] = None,
    _: TokenUser = Depends(require_role("manager")),
) -> dict:
    """Return paginated audit log entries. Returns masked fields only (never _original).

    Query params:
    - page: page number (default 1)
    - limit: entries per page (default 20, max 100)
    - classification: filter by data_classification
    - agent: filter by agent_name
    - has_pii: filter by input_has_pii (true/false)
    """
    create_tables()
    offset = (page - 1) * limit

    conditions: list[str] = []
    params: list = []

    if classification:
        conditions.append("data_classification = ?")
        params.append(classification)
    if agent:
        conditions.append("agent_name = ?")
        params.append(agent)
    if has_pii is not None:
        conditions.append("input_has_pii = ?")
        params.append(1 if has_pii else 0)
    if username:
        conditions.append("username = ?")
        params.append(username)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT
                id, session_id, timestamp, agent_name, action,
                input_masked, output_masked,
                input_has_pii, output_has_pii, pii_types_detected,
                data_classification, provider, model,
                tokens_used, chunks_count,
                retention_expires_at, pii_purged
            FROM audit_log {where}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    pages = max(1, (total + limit - 1) // limit)

    registros = []
    for r in rows:
        registros.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "timestamp": r["timestamp"],
            "agent_name": r["agent_name"],
            "action": r["action"],
            "input_masked": r["input_masked"],
            "output_masked": r["output_masked"],
            "input_has_pii": bool(r["input_has_pii"]),
            "output_has_pii": bool(r["output_has_pii"]),
            "pii_types_detected": r["pii_types_detected"],
            "data_classification": r["data_classification"],
            "provider": r["provider"],
            "model": r["model"],
            "tokens_used": r["tokens_used"],
            "chunks_count": r["chunks_count"],
            "retention_expires_at": r["retention_expires_at"],
            "pii_purged": bool(r["pii_purged"]),
        })

    return {
        "total": total,
        "page": page,
        "pages": pages,
        "registros": registros,
    }


@governance_router.get("/retention-report")
async def retention_report(
    _: TokenUser = Depends(require_role("manager")),
) -> dict:
    """Return a retention status report from the audit_log table."""
    create_tables()
    return get_retention_report()


@governance_router.post("/purge-expired")
async def purge_expired(
    _: TokenUser = Depends(require_role("manager")),
) -> dict:
    """Soft-purge PII fields on audit_log records past their retention_expires_at date."""
    create_tables()
    return purge_expired_pii()
