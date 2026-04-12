"""Tests for database setup and connection."""
import sqlite3

import pytest

from src.database.connection import get_db
from src.database.setup import create_tables


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp path."""
    import src.database.connection as conn_mod
    monkeypatch.setattr(conn_mod.settings, "db_path", str(tmp_path / "test.db"))
    yield str(tmp_path / "test.db")


def test_get_db_yields_connection(tmp_db):
    with get_db() as conn:
        assert isinstance(conn, sqlite3.Connection)


def test_create_tables_creates_all_three(tmp_db):
    create_tables()
    with get_db() as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"transactions", "alerts", "agent_log"} <= tables


def test_get_db_commits_on_success(tmp_db):
    create_tables()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO agent_log (timestamp, agent_name, action) VALUES (?, ?, ?)",
            ("2025-01-01T00:00:00", "test", "ping"),
        )
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM agent_log").fetchone()[0]
    assert count == 1


def test_get_db_rolls_back_on_exception(tmp_db):
    create_tables()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO agent_log (timestamp, agent_name, action) VALUES (?, ?, ?)",
                ("2025-01-01T00:00:00", "test", "ping"),
            )
            raise ValueError("forced error")
    except ValueError:
        pass
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM agent_log").fetchone()[0]
    assert count == 0


def test_row_factory_is_set(tmp_db):
    with get_db() as conn:
        assert conn.row_factory == sqlite3.Row


from src.database.seed import init_db


def test_seed_inserts_50_transactions(tmp_db):
    init_db()
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == 50


def test_seed_inserts_5_alerts(tmp_db):
    init_db()
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 5


def test_seed_is_idempotent(tmp_db):
    init_db()
    init_db()
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == 50


def test_unreported_large_cash_deposits(tmp_db):
    init_db()
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_type='deposito_especie' AND amount >= 50000 AND reported_to_coaf=0"
        ).fetchone()[0]
    assert count == 2


def test_pep_transactions_exist(tmp_db):
    init_db()
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM transactions WHERE pep_flag=1").fetchone()[0]
    assert count == 3
