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


class TestConversationAPI:

    @pytest.fixture
    def client(self, tmp_db):
        from fastapi.testclient import TestClient
        from src.api.main import app
        return TestClient(app)

    def _token(self, role: str = "analyst") -> str:
        from src.api.auth import create_access_token
        uid, uname = (1, "admin") if role == "manager" else (2, "analista")
        return create_access_token(uid, uname, role)

    def test_create_conversation(self, client):
        h = {"Authorization": f"Bearer {self._token()}"}
        res = client.post("/conversations", json={}, headers=h)
        assert res.status_code == 201
        data = res.json()
        assert "id" in data and data["title"] == "Nova conversa"

    def test_list_empty(self, client):
        h = {"Authorization": f"Bearer {self._token()}"}
        res = client.get("/conversations", headers=h)
        assert res.status_code == 200
        assert res.json()["conversations"] == []

    def test_create_then_list(self, client):
        h = {"Authorization": f"Bearer {self._token()}"}
        client.post("/conversations", json={"title": "Minha conversa"}, headers=h)
        convs = client.get("/conversations", headers=h).json()["conversations"]
        assert len(convs) == 1 and convs[0]["title"] == "Minha conversa"

    def test_get_conversation_messages(self, client):
        h = {"Authorization": f"Bearer {self._token()}"}
        conv = client.post("/conversations", json={}, headers=h).json()
        res = client.get(f"/conversations/{conv['id']}", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert "conversation" in data and data["messages"] == []

    def test_get_conversation_wrong_user_404(self, client):
        ha = {"Authorization": f"Bearer {self._token('analyst')}"}
        hm = {"Authorization": f"Bearer {self._token('manager')}"}
        conv = client.post("/conversations", json={}, headers=ha).json()
        assert client.get(f"/conversations/{conv['id']}", headers=hm).status_code == 404

    def test_rename_conversation(self, client):
        h = {"Authorization": f"Bearer {self._token()}"}
        conv = client.post("/conversations", json={}, headers=h).json()
        res = client.patch(f"/conversations/{conv['id']}/title", json={"title": "Novo nome"}, headers=h)
        assert res.status_code == 200
        assert res.json() == {"ok": True}
        listing = client.get("/conversations", headers=h).json()["conversations"]
        assert listing[0]["title"] == "Novo nome"

    def test_delete_conversation(self, client):
        h = {"Authorization": f"Bearer {self._token()}"}
        conv = client.post("/conversations", json={}, headers=h).json()
        assert client.delete(f"/conversations/{conv['id']}", headers=h).status_code == 204
        assert client.get("/conversations", headers=h).json()["conversations"] == []

    def test_unauthenticated_returns_401_or_403(self, client):
        assert client.get("/conversations").status_code in (401, 403)


class TestAgentMemoryIntegration:

    @pytest.fixture
    def client_with_mock(self, tmp_db):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.agents.coordinator import CoordinatorResponse

        mock_response = CoordinatorResponse(
            pergunta="test", roteamento="KNOWLEDGE", agentes_utilizados=["knowledge"],
            resposta_final="Resposta teste", detalhes_agentes=[],
            log_id=1, provider_utilizado="ollama",
            pii_detected=False, data_classification="public", session_id="abc123",
        )
        with patch("src.api.main.CoordinatorAgent") as MockCoord:
            MockCoord.return_value.process = AsyncMock(return_value=mock_response)
            yield TestClient(app)

    def _token(self, role: str = "analyst") -> str:
        from src.api.auth import create_access_token
        uid, uname = (1, "admin") if role == "manager" else (2, "analista")
        return create_access_token(uid, uname, role)

    def test_agent_without_conversation_id_still_works(self, client_with_mock):
        h = {"Authorization": f"Bearer {self._token()}"}
        res = client_with_mock.post("/agent", json={"pergunta": "Qual o prazo?"}, headers=h)
        assert res.status_code == 200

    def test_agent_with_conversation_id_saves_both_messages(self, tmp_db):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.api.auth import create_access_token
        from src.agents.coordinator import CoordinatorResponse
        from src.services.conversation import ConversationService

        svc = ConversationService()
        conv = svc.create(user_id=2, title="Test")

        mock_response = CoordinatorResponse(
            pergunta="Qual o prazo?", roteamento="KNOWLEDGE",
            agentes_utilizados=["knowledge"], resposta_final="O prazo é 180 dias.",
            detalhes_agentes=[], log_id=1, provider_utilizado="ollama",
            pii_detected=False, data_classification="public", session_id="abc",
        )
        with patch("src.api.main.CoordinatorAgent") as MockCoord:
            MockCoord.return_value.process = AsyncMock(return_value=mock_response)
            c = TestClient(app)
            token = create_access_token(2, "analista", "analyst")
            c.post("/agent",
                json={"pergunta": "Qual o prazo?", "conversation_id": conv["id"]},
                headers={"Authorization": f"Bearer {token}"})

        msgs = svc.get_messages(conv["id"], 2)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "Qual o prazo?"
        assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "O prazo é 180 dias."

    def test_first_message_auto_titles_conversation(self, tmp_db):
        from unittest.mock import AsyncMock, patch
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.api.auth import create_access_token
        from src.agents.coordinator import CoordinatorResponse
        from src.services.conversation import ConversationService

        svc = ConversationService()
        conv = svc.create(user_id=2, title="Nova conversa")

        mock_response = CoordinatorResponse(
            pergunta="Quais são os requisitos?", roteamento="KNOWLEDGE",
            agentes_utilizados=["knowledge"], resposta_final="Resposta.",
            detalhes_agentes=[], log_id=1, provider_utilizado="ollama",
            pii_detected=False, data_classification="public", session_id="x",
        )
        with patch("src.api.main.CoordinatorAgent") as MockCoord:
            MockCoord.return_value.process = AsyncMock(return_value=mock_response)
            c = TestClient(app)
            token = create_access_token(2, "analista", "analyst")
            c.post("/agent",
                json={"pergunta": "Quais são os requisitos?", "conversation_id": conv["id"]},
                headers={"Authorization": f"Bearer {token}"})

        listing = svc.list_by_user(2)
        assert listing[0]["title"] == "Quais são os requisitos?"
