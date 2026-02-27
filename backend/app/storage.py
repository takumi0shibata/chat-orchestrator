import sqlite3
from pathlib import Path
from uuid import uuid4

from app.schemas import ChatMessage, ConversationSummary


class ChatStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            conn.execute(ddl)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New chat',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_action_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(run_id, alert_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_action_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            self._ensure_column(
                conn,
                "conversations",
                "title",
                "ALTER TABLE conversations ADD COLUMN title TEXT NOT NULL DEFAULT 'New chat'",
            )
            self._ensure_column(
                conn,
                "conversations",
                "updated_at",
                "ALTER TABLE conversations ADD COLUMN updated_at DATETIME",
            )
            conn.execute(
                "UPDATE conversations SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
            )

    def create_conversation(self) -> str:
        conversation_id = str(uuid4())
        with self._connect() as conn:
            conn.execute("INSERT INTO conversations (id) VALUES (?)", (conversation_id,))
        return conversation_id

    def ensure_conversation(self, conversation_id: str | None) -> str:
        if not conversation_id:
            return self.create_conversation()

        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row:
                return conversation_id
            conn.execute("INSERT INTO conversations (id) VALUES (?)", (conversation_id,))
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return row is not None

    def list_conversations(self, limit: int = 100) -> list[ConversationSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    c.id,
                    c.title,
                    COALESCE(c.updated_at, c.created_at, CURRENT_TIMESTAMP) AS updated_at,
                    COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                updated_at=row["updated_at"],
                message_count=row["message_count"],
            )
            for row in rows
        ]

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def delete_all_conversations(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM conversations")

    def add_message(self, conversation_id: str, message: ChatMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
                (conversation_id, message.role, message.content),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (conversation_id,),
            )

    def ensure_title_from_user_input(self, conversation_id: str, user_input: str) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if not row:
                return
            current = (row["title"] or "").strip()
            if current and current != "New chat":
                return

            title = user_input.strip().replace("\n", " ")
            if len(title) > 48:
                title = f"{title[:48]}..."
            if not title:
                title = "New chat"

            conn.execute("UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (title, conversation_id))

    def get_messages(self, conversation_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()

        return [ChatMessage(role=row["role"], content=row["content"]) for row in rows]

    def record_skill_alerts(self, *, conversation_id: str, run_id: str, alert_ids: list[str]) -> None:
        if not alert_ids:
            return
        with self._connect() as conn:
            for alert_id in alert_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO skill_action_alerts (conversation_id, run_id, alert_id)
                    VALUES (?, ?, ?)
                    """,
                    (conversation_id, run_id, alert_id),
                )

    def add_skill_feedback(
        self,
        *,
        conversation_id: str,
        run_id: str,
        alert_id: str,
        decision: str,
        note: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_action_feedback (conversation_id, run_id, alert_id, decision, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, run_id, alert_id, decision, note),
            )

    def audit_news_metrics(self, *, date_from: str | None, date_to: str | None) -> dict[str, int | float]:
        range_condition = ""
        range_params: tuple[str, ...] = ()
        if date_from and date_to:
            range_condition = " WHERE date(created_at) BETWEEN ? AND ? "
            range_params = (date_from, date_to)
        elif date_from:
            range_condition = " WHERE date(created_at) >= ? "
            range_params = (date_from,)
        elif date_to:
            range_condition = " WHERE date(created_at) <= ? "
            range_params = (date_to,)

        with self._connect() as conn:
            total_alerts = conn.execute(
                f"SELECT COUNT(*) AS c FROM skill_action_alerts{range_condition}",
                range_params,
            ).fetchone()["c"]
            total_feedback = conn.execute(
                f"SELECT COUNT(*) AS c FROM skill_action_feedback{range_condition}",
                range_params,
            ).fetchone()["c"]
            acted_count = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM skill_action_feedback
                {range_condition}{' AND ' if range_condition else ' WHERE '}decision = 'acted'
                """,
                range_params,
            ).fetchone()["c"]

        action_rate = (acted_count / total_alerts) if total_alerts > 0 else 0.0
        return {
            "total_alerts": int(total_alerts),
            "total_feedback": int(total_feedback),
            "acted_count": int(acted_count),
            "action_rate": float(round(action_rate, 4)),
        }
