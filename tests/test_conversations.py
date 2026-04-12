"""Tests for conversation memory — database, service, API, and integration."""
import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    import src.database.connection as conn_mod
    monkeypatch.setattr(conn_mod.settings, "db_path", str(tmp_path / "test.db"))
    from src.database.seed import init_db
    init_db()


def test_conversations_table_exists(tmp_db):
    from src.database.connection import get_db
    with get_db() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "conversations" in tables
    assert "messages" in tables


def test_conversations_columns(tmp_db):
    from src.database.connection import get_db
    with get_db() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
    assert cols >= {"id", "user_id", "title", "created_at", "updated_at", "is_active"}


def test_messages_columns(tmp_db):
    from src.database.connection import get_db
    with get_db() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    assert cols >= {
        "id", "conversation_id", "role", "content", "agent_used",
        "provider", "data_classification", "pii_detected", "timestamp",
    }
