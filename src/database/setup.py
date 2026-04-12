"""Create all compliance database tables."""
from __future__ import annotations

from src.database.connection import get_db


_DDL = """
CREATE TABLE IF NOT EXISTS transactions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name        TEXT    NOT NULL,
    client_cpf         TEXT    NOT NULL,
    transaction_type   TEXT    NOT NULL,
    amount             REAL    NOT NULL,
    date               TEXT    NOT NULL,
    branch             TEXT,
    channel            TEXT,
    reported_to_coaf   BOOLEAN DEFAULT FALSE,
    pep_flag           BOOLEAN DEFAULT FALSE,
    notes              TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   INTEGER,
    alert_type       TEXT NOT NULL,
    severity         TEXT NOT NULL,
    description      TEXT NOT NULL,
    status           TEXT DEFAULT 'open',
    created_at       TEXT NOT NULL,
    resolved_at      TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
);

CREATE TABLE IF NOT EXISTS agent_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    action          TEXT NOT NULL,
    input_summary   TEXT,
    output_summary  TEXT,
    tokens_used     INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'analyst',
    created_at    TEXT    NOT NULL,
    last_login    TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT    NOT NULL DEFAULT 'Nova conversa',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id     INTEGER NOT NULL,
    role                TEXT    NOT NULL,
    content             TEXT    NOT NULL,
    agent_used          TEXT,
    provider            TEXT,
    data_classification TEXT,
    pii_detected        BOOLEAN DEFAULT FALSE,
    timestamp           TEXT    NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, timestamp ASC);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT    NOT NULL,
    timestamp            TEXT    NOT NULL,
    agent_name           TEXT    NOT NULL,
    action               TEXT    NOT NULL,
    input_original       TEXT,
    input_masked         TEXT,
    output_original      TEXT,
    output_masked        TEXT,
    input_has_pii        BOOLEAN NOT NULL DEFAULT FALSE,
    output_has_pii       BOOLEAN NOT NULL DEFAULT FALSE,
    pii_types_detected   TEXT,
    data_classification  TEXT    NOT NULL,
    provider             TEXT    NOT NULL,
    model                TEXT    NOT NULL,
    tokens_used          INTEGER NOT NULL DEFAULT 0,
    chunks_count         INTEGER NOT NULL DEFAULT 0,
    retention_expires_at TEXT    NOT NULL,
    pii_purged           BOOLEAN NOT NULL DEFAULT FALSE,
    user_id              INTEGER,
    username             TEXT
);

CREATE TABLE IF NOT EXISTS governance_daily_stats (
    date                        TEXT    PRIMARY KEY,
    total_queries               INTEGER NOT NULL DEFAULT 0,
    queries_with_pii            INTEGER NOT NULL DEFAULT 0,
    classification_public       INTEGER NOT NULL DEFAULT 0,
    classification_internal     INTEGER NOT NULL DEFAULT 0,
    classification_confidential INTEGER NOT NULL DEFAULT 0,
    classification_restricted   INTEGER NOT NULL DEFAULT 0,
    pii_cpf_count               INTEGER NOT NULL DEFAULT 0,
    pii_name_count              INTEGER NOT NULL DEFAULT 0,
    pii_money_count             INTEGER NOT NULL DEFAULT 0
)
"""


def create_tables() -> None:
    """Create all tables if they do not already exist."""
    with get_db() as conn:
        for statement in _DDL.strip().split(";"):
            s = statement.strip()
            if s:
                conn.execute(s)


def migrate_audit_log_add_user_columns() -> None:
    """Add user_id/username to audit_log if missing (idempotent).

    Only needed for databases created before these columns were added to the DDL.
    Safe to call on any database — new columns are already present in CREATE TABLE.
    """
    with get_db() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
        if not cols:
            return  # Table doesn't exist yet — CREATE TABLE IF NOT EXISTS will handle it
        if "user_id" not in cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN user_id INTEGER")
        if "username" not in cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN username TEXT")


if __name__ == "__main__":
    create_tables()
    print("Tables created.")
