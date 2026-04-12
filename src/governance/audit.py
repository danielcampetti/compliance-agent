"""LGPD-compliant audit module for ComplianceAgent.

Provides session ID generation, query classification, retention expiry
calculation, and interaction logging with PII masking.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Optional

from src.database.connection import get_db
from src.governance.pii_detector import MaskLevel, PIIType, count_pii, mask_text


def generate_session_id() -> str:
    """Return an 8-character hex prefix of a UUID4.

    Returns:
        8-character string unique enough for session correlation.
    """
    return uuid.uuid4().hex[:8]


def classify_query(agent_name: str, has_pii: bool, query: str) -> str:
    """Determine the data classification level for an agent interaction.

    Rules:
    - DataAgent with PII → "restricted"
    - DataAgent without PII → "confidential" (financial data regardless)
    - ActionAgent → "confidential" (modifies data)
    - KnowledgeAgent → "public" (regulatory documents)
    - knowledge+data combined → "confidential"
    - unknown → "public"

    Args:
        agent_name: Lowercase agent identifier (e.g. "data", "knowledge").
        has_pii: Whether PII was detected in the interaction.
        query: The original query string (reserved for future use).

    Returns:
        One of: "public", "internal", "confidential", "restricted".
    """
    name = agent_name.lower()
    if name == "data":
        return "restricted" if has_pii else "confidential"
    if name == "action":
        return "confidential"
    if name == "knowledge":
        return "public"
    if name == "knowledge+data":
        return "confidential"
    return "public"


def get_retention_expiry(classification: str) -> str:
    """Return ISO date string for when a record's PII should be purged.

    Retention periods per Art. 23 of Resolution CMN 4.893:
    - restricted  → today + 1 year  (365 days)
    - confidential → today + 2 years (730 days)
    - public / internal → today + 5 years (1825 days)

    Args:
        classification: Data classification level.

    Returns:
        ISO format date string (YYYY-MM-DD).
    """
    today = date.today()
    if classification == "restricted":
        return (today + timedelta(days=365)).isoformat()
    if classification == "confidential":
        return (today + timedelta(days=730)).isoformat()
    return (today + timedelta(days=1825)).isoformat()


async def log_interaction(
    session_id: str,
    agent_name: str,
    action: str,
    input_text: str,
    output_text: str,
    provider: str,
    model: str,
    tokens_used: int,
    chunks_count: int,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> int:
    """Log an agent interaction to audit_log and update daily stats.

    Detects PII in input and output, masks them before storage.
    input_original / output_original are set to NULL when PII is present.
    Updates governance_daily_stats via INSERT OR REPLACE upsert.

    Args:
        session_id: 8-char session identifier from generate_session_id().
        agent_name: Agent that handled the interaction (e.g. "knowledge").
        action: Action type (e.g. "answer", "query").
        input_text: Original user query.
        output_text: Agent response.
        provider: LLM provider used (e.g. "ollama", "claude").
        model: Model identifier (e.g. "llama3:8b").
        tokens_used: Token count for the generation.
        chunks_count: Number of RAG chunks used.

    Returns:
        Row ID of the inserted audit_log record.
    """
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()

    # --- Mask input ---
    input_masked, input_matches = mask_text(input_text, MaskLevel.FULL)
    input_has_pii = bool(input_matches)
    input_original = None if input_has_pii else input_text

    # --- Mask output ---
    output_masked, output_matches = mask_text(output_text, MaskLevel.FULL)
    output_has_pii = bool(output_matches)
    output_original = None if output_has_pii else output_text

    # --- PII type counts (combined from input + output) ---
    all_matches = input_matches + output_matches
    pii_counts: dict[PIIType, int] = {}
    for m in all_matches:
        pii_counts[m.type] = pii_counts.get(m.type, 0) + 1
    pii_types_json = json.dumps({t.value: c for t, c in pii_counts.items()}) if pii_counts else None

    # --- Classification ---
    has_pii_flag = input_has_pii or output_has_pii
    classification = classify_query(agent_name, has_pii_flag, input_text)
    retention_expires_at = get_retention_expiry(classification)

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_log (
                session_id, timestamp, agent_name, action,
                input_original, input_masked,
                output_original, output_masked,
                input_has_pii, output_has_pii, pii_types_detected,
                data_classification, provider, model,
                tokens_used, chunks_count,
                retention_expires_at, pii_purged,
                user_id, username
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?, ?)
            """,
            (
                session_id, timestamp, agent_name, action,
                input_original, input_masked,
                output_original, output_masked,
                input_has_pii, output_has_pii, pii_types_json,
                classification, provider, model,
                tokens_used, chunks_count,
                retention_expires_at,
                user_id, username,
            ),
        )
        row_id = cursor.lastrowid

        # --- Upsert daily stats ---
        cpf_count = pii_counts.get(PIIType.CPF, 0)
        name_count = pii_counts.get(PIIType.NAME, 0)
        money_count = pii_counts.get(PIIType.MONEY, 0)

        cls_col = f"classification_{classification}"
        conn.execute(
            f"""
            INSERT INTO governance_daily_stats (
                date, total_queries, queries_with_pii,
                classification_public, classification_internal,
                classification_confidential, classification_restricted,
                pii_cpf_count, pii_name_count, pii_money_count
            ) VALUES (?, 1, ?, 0, 0, 0, 0, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_queries = total_queries + 1,
                queries_with_pii = queries_with_pii + ?,
                {cls_col} = {cls_col} + 1,
                pii_cpf_count = pii_cpf_count + ?,
                pii_name_count = pii_name_count + ?,
                pii_money_count = pii_money_count + ?
            """,
            (
                today,
                1 if has_pii_flag else 0,
                cpf_count, name_count, money_count,
                1 if has_pii_flag else 0,
                cpf_count, name_count, money_count,
            ),
        )
        conn.commit()

    return row_id
