"""Conversation memory service — CRUD for conversations and messages."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.database.connection import get_db


class ConversationService:
    """Handles all conversation and message persistence."""

    def create(self, user_id: int, title: str = "Nova conversa") -> dict:
        """Create a new conversation. Returns the new conversation as a dict."""
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?,?,?,?)",
                (user_id, title, now, now),
            )
            row = conn.execute(
                "SELECT id, user_id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row)

    def get_by_id(self, conversation_id: int, user_id: int) -> Optional[dict]:
        """Return conversation dict if owned by user_id, else None."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE id = ? AND user_id = ? AND is_active = 1",
                (conversation_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def list_by_user(self, user_id: int, limit: int = 50) -> list[dict]:
        """Return conversations ordered by updated_at DESC with preview and message_count."""
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                    (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) AS message_count,
                    (SELECT content FROM messages WHERE conversation_id = c.id AND role = 'user'
                     ORDER BY timestamp ASC LIMIT 1) AS _preview_raw
                FROM conversations c
                WHERE c.user_id = ? AND c.is_active = 1
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            raw = d.pop("_preview_raw") or ""
            d["preview"] = (raw[:60] + "...") if len(raw) > 60 else raw
            result.append(d)
        return result

    def get_messages(self, conversation_id: int, user_id: int) -> Optional[list[dict]]:
        """Return all messages for a conversation.

        Returns None if the conversation does not exist or is not owned by user_id.
        """
        with get_db() as conn:
            owner = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND user_id = ? AND is_active = 1",
                (conversation_id, user_id),
            ).fetchone()
            if not owner:
                return None
            rows = conn.execute(
                "SELECT id, role, content, agent_used, provider, data_classification, "
                "pii_detected, timestamp FROM messages "
                "WHERE conversation_id = ? ORDER BY timestamp ASC",
                (conversation_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        agent_used: Optional[str] = None,
        provider: Optional[str] = None,
        data_classification: Optional[str] = None,
        pii_detected: bool = False,
    ) -> int:
        """Insert a message and update conversation's updated_at. Returns message id."""
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO messages "
                "(conversation_id, role, content, agent_used, provider, "
                "data_classification, pii_detected, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (conversation_id, role, content, agent_used, provider,
                 data_classification, pii_detected, now),
            )
            msg_id = cursor.lastrowid
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return msg_id

    def update_title(self, conversation_id: int, user_id: int, title: str) -> bool:
        """Update conversation title. Returns True if updated, False if not found/not owned."""
        with get_db() as conn:
            result = conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ? AND is_active = 1",
                (title, conversation_id, user_id),
            )
        return result.rowcount > 0

    def delete(self, conversation_id: int, user_id: int) -> bool:
        """Soft-delete a conversation. Returns True if deleted, False if not found/unauthorised."""
        with get_db() as conn:
            result = conn.execute(
                "UPDATE conversations SET is_active = 0 WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
        return result.rowcount > 0

    def get_context_messages(
        self, conversation_id: int, max_messages: int = 10
    ) -> list[dict]:
        """Return last max_messages in chronological order for LLM context.

        Content is truncated to 500 chars per message.
        Returns list of {"role": ..., "content": ...} dicts.
        """
        with get_db() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (conversation_id, max_messages),
            ).fetchall()
        return [
            {"role": r["role"], "content": r["content"][:500]}
            for r in reversed(rows)
        ]

    @staticmethod
    def auto_title(first_question: str) -> str:
        """Truncate first_question to 50 chars + '...' if longer."""
        if len(first_question) <= 50:
            return first_question
        return first_question[:50] + "..."
