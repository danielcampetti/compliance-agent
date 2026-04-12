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


class TestConversationService:

    def test_create_returns_dict_with_id(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(user_id=1, title="Test conv")
        assert isinstance(conv["id"], int) and conv["id"] > 0
        assert conv["title"] == "Test conv"
        assert "created_at" in conv and "updated_at" in conv

    def test_list_ordered_by_updated_at_desc(self, tmp_db):
        import time
        from src.services.conversation import ConversationService
        svc = ConversationService()
        svc.create(1, "A")
        time.sleep(0.01)
        svc.create(1, "B")
        result = svc.list_by_user(1)
        assert len(result) == 2
        assert result[0]["title"] == "B"  # newer first

    def test_list_includes_preview_and_message_count(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Conv")
        svc.add_message(conv["id"], "user", "Qual o prazo da Circular 3.978?")
        svc.add_message(conv["id"], "assistant", "O prazo é 180 dias.")
        result = svc.list_by_user(1)
        assert result[0]["message_count"] == 2
        assert "Qual o prazo" in result[0]["preview"]

    def test_get_messages_chronological(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        svc.add_message(conv["id"], "user", "First")
        svc.add_message(conv["id"], "assistant", "Second")
        msgs = svc.get_messages(conv["id"], 1)
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "First"
        assert msgs[1]["role"] == "assistant"

    def test_get_messages_wrong_user_returns_none(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        assert svc.get_messages(conv["id"], 2) is None

    def test_add_message_updates_updated_at(self, tmp_db):
        import time
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        before = svc.list_by_user(1)[0]["updated_at"]
        time.sleep(0.01)
        svc.add_message(conv["id"], "user", "Hello")
        after = svc.list_by_user(1)[0]["updated_at"]
        assert after > before

    def test_auto_title_short(self):
        from src.services.conversation import ConversationService
        assert ConversationService.auto_title("Curto") == "Curto"

    def test_auto_title_truncates_at_50(self):
        from src.services.conversation import ConversationService
        result = ConversationService.auto_title("A" * 60)
        assert result == "A" * 50 + "..."
        assert len(result) == 53

    def test_delete_removes_conversation(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        svc.add_message(conv["id"], "user", "Hi")
        assert svc.delete(conv["id"], 1) is True
        assert svc.get_messages(conv["id"], 1) is None

    def test_delete_unauthorized_returns_false(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        assert svc.delete(conv["id"], 2) is False

    def test_get_context_messages_format(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        svc.add_message(conv["id"], "user", "Q1")
        svc.add_message(conv["id"], "assistant", "A1")
        ctx = svc.get_context_messages(conv["id"])
        assert ctx == [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}]

    def test_get_context_messages_respects_max(self, tmp_db):
        from src.services.conversation import ConversationService
        svc = ConversationService()
        conv = svc.create(1, "Test")
        for i in range(8):
            svc.add_message(conv["id"], "user", f"Q{i}")
            svc.add_message(conv["id"], "assistant", f"A{i}")
        ctx = svc.get_context_messages(conv["id"], max_messages=6)
        assert len(ctx) == 6
        # Must be last 6 in chronological order
        assert ctx[0]["content"] == "Q5"
