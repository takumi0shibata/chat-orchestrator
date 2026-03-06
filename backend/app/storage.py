import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.schemas import ChatMessage, ConversationSummary
from app.skills_runtime.base import UI_BLOCKS_ADAPTER


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
            self._ensure_column(
                conn,
                "messages",
                "artifacts_json",
                "ALTER TABLE messages ADD COLUMN artifacts_json TEXT",
            )
            self._ensure_column(
                conn,
                "messages",
                "skill_id",
                "ALTER TABLE messages ADD COLUMN skill_id TEXT",
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
        artifacts_json = None
        if message.artifacts:
            artifacts_json = json.dumps(
                UI_BLOCKS_ADAPTER.dump_python(message.artifacts, mode="json"),
                ensure_ascii=False,
            )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, artifacts_json, skill_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, message.role, message.content, artifacts_json, message.skill_id),
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
        feedback_map = self.feedback_selection_map(conversation_id=conversation_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, artifacts_json, skill_id
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()

        messages: list[ChatMessage] = []
        for row in rows:
            artifacts = self._load_artifacts(row["artifacts_json"])
            self._apply_feedback_selection(artifacts=artifacts, feedback_map=feedback_map)
            messages.append(
                ChatMessage(
                    role=row["role"],
                    content=row["content"],
                    artifacts=artifacts,
                    skill_id=row["skill_id"],
                )
            )
        return messages

    def _load_artifacts(self, artifacts_json: str | None) -> list:
        if not artifacts_json:
            return []
        try:
            parsed = json.loads(artifacts_json)
            return list(UI_BLOCKS_ADAPTER.validate_python(parsed))
        except Exception:
            return []

    def _apply_feedback_selection(self, *, artifacts: list, feedback_map: dict[tuple[str, str], str]) -> None:
        for artifact in artifacts:
            if getattr(artifact, "type", None) != "card_list":
                continue
            for section in artifact.sections:
                for item in section.items:
                    for action in item.actions:
                        key = (action.run_id, action.item_id)
                        action.selected = feedback_map.get(key)

    def record_feedback_targets(self, *, conversation_id: str, run_id: str, item_ids: list[str]) -> None:
        if not item_ids:
            return
        with self._connect() as conn:
            for item_id in item_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO skill_action_alerts (conversation_id, run_id, alert_id)
                    VALUES (?, ?, ?)
                    """,
                    (conversation_id, run_id, item_id),
                )

    def record_skill_alerts(self, *, conversation_id: str, run_id: str, alert_ids: list[str]) -> None:
        self.record_feedback_targets(conversation_id=conversation_id, run_id=run_id, item_ids=alert_ids)

    def add_feedback(
        self,
        *,
        conversation_id: str,
        run_id: str,
        item_id: str,
        decision: str,
        note: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skill_action_feedback (conversation_id, run_id, alert_id, decision, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, run_id, item_id, decision, note),
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
        self.add_feedback(
            conversation_id=conversation_id,
            run_id=run_id,
            item_id=alert_id,
            decision=decision,
            note=note,
        )

    def feedback_selection_map(self, *, conversation_id: str) -> dict[tuple[str, str], str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, alert_id, decision
                FROM skill_action_feedback
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        result: dict[tuple[str, str], str] = {}
        for row in rows:
            result[(row["run_id"], row["alert_id"])] = row["decision"]
        return result

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
