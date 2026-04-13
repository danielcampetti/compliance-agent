"""LGPD data retention manager for ComplianceAgent.

Provides:
- purge_expired_pii()  — soft-purges overdue PII records (never deletes rows)
- get_retention_report() — aggregated retention status report
"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.database.connection import get_db


def purge_expired_pii() -> dict[str, Any]:
    """Overwrite PII text fields for records past their retention_expires_at date.

    Rows are NEVER deleted. Text fields are replaced with '[DADO_EXPIRADO]' and
    pii_purged is set to TRUE. Metadata (agent_name, timestamp, classification,
    token counts) is preserved for the 5-year regulatory audit trail per
    Art. 23 of Resolution CMN 4.893.

    Only rows satisfying ALL of:
    - retention_expires_at <= today
    - pii_purged = FALSE
    - input_has_pii = TRUE

    Returns:
        Dict with keys:
        - rows_purged (int): number of rows updated
        - oldest_purged (str | None): timestamp of oldest purged row
        - newest_purged (str | None): timestamp of newest purged row
    """
    today = date.today().isoformat()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp FROM audit_log
            WHERE retention_expires_at <= ?
              AND pii_purged = FALSE
              AND input_has_pii = TRUE
            ORDER BY timestamp ASC
            """,
            (today,),
        ).fetchall()

        if not rows:
            return {"rows_purged": 0, "oldest_purged": None, "newest_purged": None}

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"""
            UPDATE audit_log
            SET input_original  = '[DADO_EXPIRADO]',
                output_original = '[DADO_EXPIRADO]',
                input_masked    = '[DADO_EXPIRADO]',
                output_masked   = '[DADO_EXPIRADO]',
                pii_purged      = TRUE
            WHERE id IN ({placeholders})
            """,
            ids,
        )
        conn.commit()

    oldest = rows[0]["timestamp"]
    newest = rows[-1]["timestamp"]
    return {
        "rows_purged": len(rows),
        "oldest_purged": oldest,
        "newest_purged": newest,
    }


def get_retention_report() -> dict[str, Any]:
    """Return an aggregated report of audit_log retention status.

    Queries:
    - Total records in audit_log
    - Records with PII (input_has_pii = TRUE)
    - Records already purged (pii_purged = TRUE)
    - Records expiring within the next 30 days (and not yet purged)
    - Oldest record timestamp
    - Storage breakdown by classification

    Returns:
        Dict with keys: total_records, records_with_pii, records_purged,
        records_expiring_30_days, oldest_record, by_classification.
    """
    today = date.today().isoformat()
    from datetime import timedelta
    in_30_days = (date.today() + timedelta(days=30)).isoformat()

    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        with_pii = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE input_has_pii = TRUE"
        ).fetchone()[0]
        purged = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE pii_purged = TRUE"
        ).fetchone()[0]
        expiring = conn.execute(
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
            "SELECT MIN(timestamp) FROM audit_log"
        ).fetchone()[0]

        by_class = conn.execute(
            """
            SELECT data_classification, COUNT(*) as cnt
            FROM audit_log
            GROUP BY data_classification
            """
        ).fetchall()

    return {
        "total_records": total,
        "records_with_pii": with_pii,
        "records_purged": purged,
        "records_expiring_30_days": expiring,
        "oldest_record": oldest_row,
        "by_classification": {row["data_classification"]: row["cnt"] for row in by_class},
    }
