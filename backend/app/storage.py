import json
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.schemas import AttachmentSummary, ChatMessage, ConversationSummary, StoredAttachment, StoredGeneratedFile
from app.skills_runtime.base import UI_BLOCKS_ADAPTER


class ChatStore:
    def __init__(
        self,
        db_path: Path,
        *,
        attachments_root: Path | None = None,
        generated_files_root: Path | None = None,
    ) -> None:
        self.db_path = db_path
        self.attachments_root = attachments_root or db_path.parent / "attachments"
        self.generated_files_root = generated_files_root or db_path.parent / "generated_files"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.attachments_root.mkdir(parents=True, exist_ok=True)
        self.generated_files_root.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    message_id INTEGER,
                    name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    original_path TEXT NOT NULL,
                    parsed_markdown_path TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                    FOREIGN KEY(message_id) REFERENCES messages(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_files (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    source_attachment_id TEXT,
                    name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id),
                    FOREIGN KEY(source_attachment_id) REFERENCES attachments(id)
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
        attachments = self.list_conversation_attachments(conversation_id)
        generated_files = self.list_generated_files(conversation_id=conversation_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM generated_files WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM attachments WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self._delete_attachment_files(attachments)
        self._delete_generated_files(generated_files)

    def delete_all_conversations(self) -> None:
        attachments = self.list_all_attachments()
        generated_files = self.list_all_generated_files()
        with self._connect() as conn:
            conn.execute("DELETE FROM generated_files")
            conn.execute("DELETE FROM attachments")
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM conversations")
        self._delete_attachment_files(attachments)
        self._delete_generated_files(generated_files)
        if self.attachments_root.exists():
            shutil.rmtree(self.attachments_root, ignore_errors=True)
            self.attachments_root.mkdir(parents=True, exist_ok=True)
        if self.generated_files_root.exists():
            shutil.rmtree(self.generated_files_root, ignore_errors=True)
            self.generated_files_root.mkdir(parents=True, exist_ok=True)

    def add_message(self, conversation_id: str, message: ChatMessage) -> int:
        artifacts_json = None
        if message.artifacts:
            artifacts_json = json.dumps(
                UI_BLOCKS_ADAPTER.dump_python(message.artifacts, mode="json"),
                ensure_ascii=False,
            )
        with self._connect() as conn:
            cursor = conn.execute(
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
        return int(cursor.lastrowid)

    def add_attachment(
        self,
        *,
        attachment_id: str,
        conversation_id: str,
        name: str,
        content_type: str,
        size_bytes: int,
        original_path: str,
        parsed_markdown_path: str,
    ) -> AttachmentSummary:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO attachments (
                    id, conversation_id, message_id, name, content_type, size_bytes, original_path, parsed_markdown_path
                )
                VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    conversation_id,
                    name,
                    content_type,
                    size_bytes,
                    original_path,
                    parsed_markdown_path,
                ),
            )
        return AttachmentSummary(
            id=attachment_id,
            name=name,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    def attach_pending_attachments(
        self,
        *,
        conversation_id: str,
        attachment_ids: list[str],
        message_id: int,
    ) -> None:
        if not attachment_ids:
            return
        with self._connect() as conn:
            for attachment_id in attachment_ids:
                conn.execute(
                    """
                    UPDATE attachments
                    SET message_id = ?
                    WHERE id = ? AND conversation_id = ? AND message_id IS NULL
                    """,
                    (message_id, attachment_id, conversation_id),
                )

    def get_attachments(
        self,
        *,
        conversation_id: str,
        attachment_ids: list[str],
    ) -> list[StoredAttachment]:
        if not attachment_ids:
            return []

        placeholders = ",".join("?" for _ in attachment_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, conversation_id, message_id, name, content_type, size_bytes, original_path, parsed_markdown_path, created_at
                FROM attachments
                WHERE conversation_id = ? AND id IN ({placeholders})
                """,
                (conversation_id, *attachment_ids),
            ).fetchall()

        by_id = {row["id"]: self._attachment_from_row(row) for row in rows}
        return [by_id[attachment_id] for attachment_id in attachment_ids if attachment_id in by_id]

    def list_conversation_attachments(self, conversation_id: str) -> list[StoredAttachment]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, message_id, name, content_type, size_bytes, original_path, parsed_markdown_path, created_at
                FROM attachments
                WHERE conversation_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [self._attachment_from_row(row) for row in rows]

    def list_all_attachments(self) -> list[StoredAttachment]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, message_id, name, content_type, size_bytes, original_path, parsed_markdown_path, created_at
                FROM attachments
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        return [self._attachment_from_row(row) for row in rows]

    def add_generated_file(
        self,
        *,
        conversation_id: str,
        skill_id: str,
        source_attachment_id: str | None,
        name: str,
        content_type: str,
        path: str,
        file_id: str | None = None,
    ) -> StoredGeneratedFile:
        generated_file_id = file_id or str(uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO generated_files (
                    id, conversation_id, skill_id, source_attachment_id, name, content_type, path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generated_file_id,
                    conversation_id,
                    skill_id,
                    source_attachment_id,
                    name,
                    content_type,
                    path,
                ),
            )
        return self.get_generated_file(generated_file_id)

    def get_generated_file(self, file_id: str) -> StoredGeneratedFile | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, conversation_id, skill_id, source_attachment_id, name, content_type, path, created_at
                FROM generated_files
                WHERE id = ?
                """,
                (file_id,),
            ).fetchone()
        if not row:
            return None
        return self._generated_file_from_row(row)

    def list_generated_files(self, *, conversation_id: str) -> list[StoredGeneratedFile]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, skill_id, source_attachment_id, name, content_type, path, created_at
                FROM generated_files
                WHERE conversation_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [self._generated_file_from_row(row) for row in rows]

    def list_all_generated_files(self) -> list[StoredGeneratedFile]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, skill_id, source_attachment_id, name, content_type, path, created_at
                FROM generated_files
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        return [self._generated_file_from_row(row) for row in rows]

    def ensure_title_from_user_input(
        self,
        conversation_id: str,
        user_input: str,
        *,
        fallback_attachment_name: str | None = None,
    ) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if not row:
                return
            current = (row["title"] or "").strip()
            if current and current != "New chat":
                return

            title_source = user_input.strip().replace("\n", " ")
            if not title_source:
                title_source = (fallback_attachment_name or "").strip()

            title = title_source
            if len(title) > 48:
                title = f"{title[:48]}..."
            if not title:
                title = "New chat"

            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, conversation_id),
            )

    def get_messages(self, conversation_id: str) -> list[ChatMessage]:
        feedback_map = self.feedback_selection_map(conversation_id=conversation_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, role, content, artifacts_json, skill_id
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
            attachment_rows = conn.execute(
                """
                SELECT id, conversation_id, message_id, name, content_type, size_bytes, original_path, parsed_markdown_path, created_at
                FROM attachments
                WHERE conversation_id = ? AND message_id IS NOT NULL
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()

        attachments_by_message: dict[int, list[AttachmentSummary]] = {}
        for row in attachment_rows:
            attachment = self._attachment_from_row(row)
            attachments_by_message.setdefault(int(attachment.message_id), []).append(
                AttachmentSummary(
                    id=attachment.id,
                    name=attachment.name,
                    content_type=attachment.content_type,
                    size_bytes=attachment.size_bytes,
                )
            )

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
                    attachments=attachments_by_message.get(int(row["id"]), []),
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

    def _attachment_from_row(self, row: sqlite3.Row) -> StoredAttachment:
        return StoredAttachment(
            id=row["id"],
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            name=row["name"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            original_path=row["original_path"],
            parsed_markdown_path=row["parsed_markdown_path"],
            created_at=row["created_at"],
        )

    def _generated_file_from_row(self, row: sqlite3.Row) -> StoredGeneratedFile:
        return StoredGeneratedFile(
            id=row["id"],
            conversation_id=row["conversation_id"],
            skill_id=row["skill_id"],
            source_attachment_id=row["source_attachment_id"],
            name=row["name"],
            content_type=row["content_type"],
            path=row["path"],
            created_at=row["created_at"],
        )

    def _delete_attachment_files(self, attachments: list[StoredAttachment]) -> None:
        seen_dirs: set[Path] = set()
        for attachment in attachments:
            for raw_path in (attachment.original_path, attachment.parsed_markdown_path):
                path = Path(raw_path)
                if path.exists():
                    path.unlink()
                seen_dirs.add(path.parent)
        for directory in sorted(seen_dirs, key=lambda item: len(item.parts), reverse=True):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

    def _delete_generated_files(self, generated_files: list[StoredGeneratedFile]) -> None:
        seen_dirs: set[Path] = set()
        for generated_file in generated_files:
            path = Path(generated_file.path)
            if path.exists():
                path.unlink()
            seen_dirs.add(path.parent)
        for directory in sorted(seen_dirs, key=lambda item: len(item.parts), reverse=True):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
