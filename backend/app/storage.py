import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

TERMINAL = {"completed", "failed", "stopped"}


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "agent.db"
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS conversations (
                  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, context TEXT NOT NULL DEFAULT '[]',
                  provider TEXT, model TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL,
                  request TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS active_conversation ON runs(conversation_id)
                  WHERE status NOT IN ('completed', 'failed', 'stopped');
                CREATE TABLE IF NOT EXISTS events (
                  run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL,
                  data TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(run_id,seq));
                CREATE TABLE IF NOT EXISTS attachments (
                  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, name TEXT NOT NULL,
                  content_type TEXT NOT NULL, size INTEGER NOT NULL, path TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=20)
        try:
            c.row_factory = sqlite3.Row
            # SQLite's context manager commits/rolls back but does not close.
            with c:
                yield c
        finally:
            c.close()

    def conversations(self):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,workspace_id,title,updated_at FROM conversations ORDER BY updated_at DESC"
                )
            ]

    def conversation(self, cid):
        with self.connect() as c:
            row = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not row:
            raise KeyError("Conversation not found")
        result = dict(row)
        result["context"] = json.loads(result["context"])
        return result

    def create_conversation(self, workspace_id):
        cid = uuid4().hex
        with self.connect() as c:
            c.execute(
                "INSERT INTO conversations(id,workspace_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (cid, workspace_id, "新しい作業", now(), now()),
            )
        return self.conversation(cid)

    def save_context(self, cid, context, provider, model):
        with self.connect() as c:
            c.execute(
                "UPDATE conversations SET context=?,provider=?,model=?,updated_at=? WHERE id=?",
                (json.dumps(context), provider, model, now(), cid),
            )

    def create_run(self, request):
        rid = uuid4().hex
        with self.connect() as c:
            c.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?)",
                (
                    rid,
                    request["conversation_id"],
                    "preparing",
                    json.dumps(request),
                    now(),
                    now(),
                ),
            )
            c.execute(
                "UPDATE conversations SET title=CASE WHEN title='新しい作業' THEN ? ELSE title END,updated_at=? WHERE id=?",
                (
                    request["input"][:60] or "添付ファイルの作業",
                    now(),
                    request["conversation_id"],
                ),
            )
        self.event(
            rid, "status", {"status": "preparing", "label": "実行を準備しています"}
        )
        return self.run(rid)

    def run(self, rid):
        with self.connect() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if not row:
            raise KeyError("Run not found")
        result = dict(row)
        result["request"] = json.loads(result["request"])
        return result

    def runs(self, cid):
        with self.connect() as c:
            ids = [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM runs WHERE conversation_id=? ORDER BY created_at",
                    (cid,),
                )
            ]
        return [self.run(rid) for rid in ids]

    def event(self, rid, kind, data):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            seq = c.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (rid,)
            ).fetchone()[0]
            stamp = now()
            c.execute(
                "INSERT INTO events VALUES(?,?,?,?,?)",
                (rid, seq, kind, json.dumps(data), stamp),
            )
        return dict(run_id=rid, seq=seq, type=kind, data=data, created_at=stamp)

    def events(self, rid, after=0, limit=500):
        with self.connect() as c:
            return [
                dict(
                    run_id=r["run_id"],
                    seq=r["seq"],
                    type=r["type"],
                    data=json.loads(r["data"]),
                    created_at=r["created_at"],
                )
                for r in c.execute(
                    "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (rid, after, limit),
                )
            ]

    def needs_cleanup(self, rid):
        with self.connect() as c:
            row = c.execute(
                "SELECT type FROM events WHERE run_id=? AND type IN ('sandbox_cleanup_failed','sandbox_cleanup_completed') ORDER BY seq DESC LIMIT 1",
                (rid,),
            ).fetchone()
        return bool(row and row["type"] == "sandbox_cleanup_failed")

    def status(self, rid, status, label):
        # Status and its event commit atomically so reconnect never misses a terminal event.
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "UPDATE runs SET status=?,updated_at=? WHERE id=?", (status, now(), rid)
            )
            seq = c.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (rid,)
            ).fetchone()[0]
            c.execute(
                "INSERT INTO events VALUES(?,?,?,?,?)",
                (
                    rid,
                    seq,
                    "status",
                    json.dumps(dict(status=status, label=label)),
                    now(),
                ),
            )

    def attachment(self, aid, cid):
        with self.connect() as c:
            row = c.execute(
                "SELECT * FROM attachments WHERE id=? AND conversation_id=?", (aid, cid)
            ).fetchone()
        if not row:
            raise KeyError("Attachment not found in this conversation")
        return dict(row)

    def add_attachment(self, data):
        with self.connect() as c:
            c.execute(
                "INSERT INTO attachments VALUES(:id,:conversation_id,:name,:content_type,:size,:path)",
                data,
            )

    def delete_conversation(self, cid):
        self.conversation(cid)
        if any(r["status"] not in TERMINAL for r in self.runs(cid)):
            raise ValueError("Stop the active run before deleting the conversation")
        with self.connect() as c:
            c.execute(
                "DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE conversation_id=?)",
                (cid,),
            )
            c.execute("DELETE FROM runs WHERE conversation_id=?", (cid,))
            c.execute("DELETE FROM attachments WHERE conversation_id=?", (cid,))
            c.execute("DELETE FROM conversations WHERE id=?", (cid,))
