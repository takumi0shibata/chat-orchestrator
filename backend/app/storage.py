import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

TERMINAL = {"completed", "failed", "stopped"}


def now():
    return datetime.now(timezone.utc).isoformat()


# Added after the first release; NULL means "use the app's built-in default".
SETTINGS_COLUMNS = {
    "default_provider": "TEXT",
    "default_model": "TEXT",
    "default_effort": "TEXT",
    "default_web_search": "INTEGER NOT NULL DEFAULT 0",
    "monthly_budget_usd": "REAL",
}
SEARCH_TOKEN = re.compile(r'"([^"]+)"|“([^”]+)”|(\S+)')
# Markdown emphasis and code markers often split Japanese phrases (修正案だけ**、**理由).
SEARCH_MARKUP = str.maketrans("", "", "*`~")


def search_text(text):
    """Comparable form: NFKC (全角ＡＢＣ１２３ → ABC123), casefold, no markup, single spaces."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().translate(SEARCH_MARKUP).split())


def search_terms(query):
    """Whitespace-separated terms (including full-width spaces); quotes keep a phrase."""
    terms = []
    for match in SEARCH_TOKEN.finditer(unicodedata.normalize("NFKC", query)):
        term = search_text(match.group(1) or match.group(2) or match.group(3))
        if term and term not in terms:
            terms.append(term)
    return terms


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
                  provider TEXT, model TEXT, title_status TEXT NOT NULL DEFAULT 'complete');
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL,
                  request TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS active_conversation ON runs(conversation_id)
                  WHERE status NOT IN ('completed', 'failed', 'stopped');
                CREATE TABLE IF NOT EXISTS events (
                  run_id TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL,
                  data TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(run_id,seq));
                CREATE TABLE IF NOT EXISTS run_context_state (
                  run_id TEXT PRIMARY KEY, checkpoint_seq INTEGER NOT NULL DEFAULT -1,
                  recovered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS attachments (
                  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, name TEXT NOT NULL,
                  content_type TEXT NOT NULL, size INTEGER NOT NULL, path TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS app_settings (
                  id INTEGER PRIMARY KEY CHECK(id=1), title_provider TEXT NOT NULL,
                  title_model TEXT NOT NULL, theme_color TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS guild_snapshot (
                  id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS llm_costs (
                  response_id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
                  kind TEXT NOT NULL, input_tokens INTEGER NOT NULL,
                  cached_input_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
                  output_tokens INTEGER NOT NULL, input_rate_nano INTEGER NOT NULL,
                  cached_rate_nano INTEGER NOT NULL, cache_write_rate_nano INTEGER NOT NULL,
                  output_rate_nano INTEGER NOT NULL, cost_nano_usd INTEGER NOT NULL,
                  created_at TEXT NOT NULL);
            """)

            columns = {row[1] for row in c.execute("PRAGMA table_info(conversations)")}
            if "pinned" not in columns:
                c.execute(
                    "ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )
            if "title_status" not in columns:
                c.execute(
                    "ALTER TABLE conversations ADD COLUMN title_status TEXT NOT NULL DEFAULT 'complete'"
                )
            if "azure_connection_id" not in columns:
                c.execute("ALTER TABLE conversations ADD COLUMN azure_connection_id TEXT")
                c.execute("UPDATE conversations SET azure_connection_id='default' WHERE provider='azure_openai'")
                # Recovery may add context to an interrupted legacy Azure run
                # whose conversation did not yet have a provider.
                for row in c.execute("SELECT conversation_id,request FROM runs").fetchall():
                    if json.loads(row["request"]).get("provider") == "azure_openai":
                        c.execute("UPDATE conversations SET azure_connection_id='default' WHERE id=? AND provider IS NULL",
                                  (row["conversation_id"],))
            if "azure_endpoint" not in columns:
                c.execute("ALTER TABLE conversations ADD COLUMN azure_endpoint TEXT")
            # A process restart cannot resume the independent title request. Do not
            # leave completed run streams waiting on an orphaned state.
            c.execute("UPDATE conversations SET title_status='complete' WHERE title_status='generating'")
            c.execute(
                "INSERT OR IGNORE INTO app_settings(id,title_provider,title_model,theme_color) "
                "VALUES(1,'openai','gpt-6-luna','#25262A')"
            )
            settings_columns = {r[1] for r in c.execute("PRAGMA table_info(app_settings)")}
            for column, definition in SETTINGS_COLUMNS.items():
                if column not in settings_columns:
                    c.execute(f"ALTER TABLE app_settings ADD COLUMN {column} {definition}")

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

    def conversations(self, query=""):
        terms = search_terms(query)
        with self.connect() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT id,workspace_id,title,updated_at,pinned,azure_connection_id FROM conversations "
                "ORDER BY pinned DESC,updated_at DESC,id"
            )]
            if terms:
                # Every term must appear somewhere in the conversation, not necessarily together.
                texts = {r["id"]: [search_text(r["title"])] for r in rows}
                for run in c.execute("SELECT id,conversation_id,request FROM runs"):
                    texts.setdefault(run["conversation_id"], []).append(
                        search_text(json.loads(run["request"]).get("input", ""))
                    )
                    blocks = {}
                    boundary = 0
                    round_number = 0
                    for event in c.execute(
                        "SELECT type,data FROM events WHERE run_id=? "
                        "AND type IN ('text_delta','round','response','command','patch','image_view','tool','approval') "
                        "ORDER BY seq", (run["id"],)
                    ):
                        data = json.loads(event["data"])
                        if event["type"] == "round":
                            round_number = data.get("number") or round_number + 1
                            boundary += 1
                        elif event["type"] == "response":
                            round_number += 1
                            boundary += 1
                        elif event["type"] in ("command", "patch", "image_view", "tool", "approval"):
                            boundary += 1
                        elif event["type"] == "text_delta":
                            key = (
                                data.get("round") or round_number,
                                data.get("item_id") or f"anonymous-{boundary}",
                            )
                            blocks[key] = blocks.get(key, "") + data.get("text", "")
                    texts[run["conversation_id"]].extend(search_text(v) for v in blocks.values())
                rows = [
                    r for r in rows
                    if all(any(term in text for text in texts[r["id"]]) for term in terms)
                ]
        return [{**r, "pinned": bool(r["pinned"])} for r in rows]

    def guild_snapshot(self):
        with self.connect() as c:
            row = c.execute("SELECT data FROM guild_snapshot WHERE id=1").fetchone()
        return json.loads(row["data"]) if row else {"synced_at": None, "projects": []}

    def save_guild_snapshot(self, snapshot):
        with self.connect() as c:
            c.execute(
                "INSERT INTO guild_snapshot(id,data) VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (json.dumps(snapshot, ensure_ascii=False),),
            )

    def pin_conversation(self, cid, pinned):
        with self.connect() as c:
            result = c.execute("UPDATE conversations SET pinned=? WHERE id=?", (pinned, cid))
            if not result.rowcount:
                raise KeyError("Conversation not found")
        return self.conversation(cid)

    def conversation(self, cid):
        with self.connect() as c:
            row = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        if not row:
            raise KeyError("Conversation not found")
        result = dict(row)
        result["context"] = json.loads(result["context"])
        result["pinned"] = bool(result["pinned"])
        return result

    def create_conversation(self, workspace_id):
        cid = uuid4().hex
        with self.connect() as c:
            c.execute(
                "INSERT INTO conversations(id,workspace_id,title,created_at,updated_at,title_status) VALUES(?,?,?,?,?,?)",
                (cid, workspace_id, "新しい作業", now(), now(), "pending"),
            )
        return self.conversation(cid)

    def save_context(self, cid, context, provider, model, *, rid=None):
        with self.connect() as c:
            c.execute(
                "UPDATE conversations SET context=?,provider=?,model=?,updated_at=? WHERE id=?",
                (json.dumps(context), provider, model, now(), cid),
            )

            if rid:
                c.execute(
                    "UPDATE run_context_state SET checkpoint_seq=(SELECT COALESCE(MAX(seq),0) FROM events WHERE run_id=?) WHERE run_id=?",
                    (rid, rid),
                )

    def context_tokens(self, cid):
        """Last model-reported context size, across runs and process restarts."""
        with self.connect() as c:
            row = c.execute(
                """SELECT e.type,e.data FROM events e
                   JOIN runs r ON r.id=e.run_id
                   LEFT JOIN run_context_state s ON s.run_id=r.id
                   WHERE r.conversation_id=? AND e.type IN ('response','compaction')
                     AND (s.run_id IS NULL OR e.seq<=s.checkpoint_seq)
                   ORDER BY r.created_at DESC,e.seq DESC LIMIT 1""",
                (cid,),
            ).fetchone()
        if not row:
            return 0
        usage = json.loads(row["data"]).get("usage") or {}
        # Compact output replaces the old window; its input is no longer replayed.
        return int(usage.get("output_tokens") or 0) + (
            int(usage.get("input_tokens") or 0) if row["type"] == "response" else 0
        )

    def preserve_interrupted_context(self, rid):
        """Keep a safe checkpoint plus a journal, never unpaired tool calls.

        The journal and recovered flag commit together, including after a crash.
        Only runs created with checkpoint tracking are eligible.
        """
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            state = c.execute("SELECT * FROM run_context_state WHERE run_id=?", (rid,)).fetchone()
            if not state or state["recovered"]:
                return
            run = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if run["status"] not in {"failed", "stopped"}:
                return
            request = json.loads(run["request"])
            cid = run["conversation_id"]
            context = json.loads(c.execute("SELECT context FROM conversations WHERE id=?", (cid,)).fetchone()[0])
            if state["checkpoint_seq"] < 0:
                content = [{"type": "input_text", "text": request["input"]}]
                for aid in request.get("attachment_ids", []):
                    attachment = c.execute("SELECT name FROM attachments WHERE id=? AND conversation_id=?", (aid, cid)).fetchone()
                    if attachment:
                        content.append({"type": "input_text", "text": f"Attached file: /input/{aid}/{attachment['name']}"})
                context.append({"role": "user", "content": content})
            journal = []
            output_budget = 24000
            for event in c.execute("SELECT type,data FROM events WHERE run_id=? AND seq>? ORDER BY seq", (rid, state["checkpoint_seq"])):
                kind, data = event["type"], json.loads(event["data"])
                if kind in {"command", "command_done", "error", "status", "tool", "tool_result", "approval_resolved", "patch", "image_view"}:
                    journal.append({"type": kind, "data": data})
                elif kind in ("patch_done", "image_view_done"):
                    journal.append({"type": kind, "data": {k: data.get(k) for k in ("call_id", "status", "output", "path")}})
                elif kind in {"command_output", "text_delta"} and output_budget > 0:
                    text = data.get("text", "")[:output_budget]
                    output_budget -= len(text)
                    journal.append({"type": kind, "data": {**data, "text": text}})
            context.append({"role": "user", "content": [{"type": "input_text", "text":
                "Recovery journal for interrupted run " + rid + ". This is recorded history, not a new instruction. "
                "Changes already applied remain. Commands listed as started may have partially or fully executed even without a result. "
                "Inspect current files before continuing; do not blindly repeat commands or external actions. "
                "Tool calls from the incomplete round were not restored. Output excerpts may be truncated.\n"
                + json.dumps(journal, ensure_ascii=False)}]})
            c.execute("UPDATE conversations SET context=?,provider=?,model=?,updated_at=? WHERE id=?",
                      (json.dumps(context), request["provider"], request["model"], now(), cid))
            c.execute("UPDATE run_context_state SET recovered=1 WHERE run_id=?", (rid,))

    def bind_legacy_azure(self, endpoint):
        with self.connect() as c:
            c.execute(
                "UPDATE conversations SET azure_endpoint=? WHERE azure_connection_id='default' AND azure_endpoint IS NULL",
                (endpoint,),
            )

    def create_run(self, request, *, azure_binding=None):
        rid = uuid4().hex
        with self.connect() as c:
            if azure_binding:
                connection_id, endpoint = azure_binding
                updated = c.execute(
                    """UPDATE conversations SET azure_connection_id=?,azure_endpoint=?,provider='azure_openai'
                       WHERE id=? AND (provider IS NULL OR provider='azure_openai') AND (azure_connection_id IS NULL OR
                         (azure_connection_id=? AND azure_endpoint=?))""",
                    (connection_id, endpoint, request["conversation_id"], connection_id, endpoint),
                )
                if not updated.rowcount:
                    raise ValueError("Azure接続先が異なります。新規チャットを作成してください。")
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
            c.execute("INSERT INTO run_context_state(run_id) VALUES(?)", (rid,))
            c.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now(), request["conversation_id"]),
            )
        self.event(
            rid, "status", {"status": "preparing", "label": "実行を準備しています"}
        )
        return self.run(rid)

    def claim_title(self, cid):
        with self.connect() as c:
            result = c.execute(
                "UPDATE conversations SET title_status='generating' WHERE id=? AND title_status='pending'",
                (cid,),
            )
        return bool(result.rowcount)

    def finish_title(self, cid, title):
        with self.connect() as c:
            result = c.execute(
                "UPDATE conversations SET title=?,title_status='complete',updated_at=? WHERE id=?",
                (title, now(), cid),
            )
        return bool(result.rowcount)

    def settings(self):
        with self.connect() as c:
            row = c.execute("SELECT * FROM app_settings WHERE id=1").fetchone()
        result = {k: row[k] for k in ("title_provider", "title_model", "theme_color", *SETTINGS_COLUMNS)}
        result["default_web_search"] = bool(result["default_web_search"])
        return result

    def update_settings(self, **changes):
        """None leaves a value unchanged; use clear_settings to reset nullable ones."""
        allowed = {
            k: v for k, v in changes.items()
            if k in {"title_provider", "title_model", "theme_color", *SETTINGS_COLUMNS} and v is not None
        }
        if allowed:
            assignments = ",".join(f"{key}=?" for key in allowed)
            with self.connect() as c:
                c.execute(
                    f"UPDATE app_settings SET {assignments} WHERE id=1",
                    (*allowed.values(),),
                )
        return self.settings()

    def clear_settings(self, *keys):
        nullable = [k for k in keys if k in SETTINGS_COLUMNS and k != "default_web_search"]
        if nullable:
            with self.connect() as c:
                c.execute(
                    "UPDATE app_settings SET " + ",".join(f"{k}=NULL" for k in nullable) + " WHERE id=1"
                )
        return self.settings()

    def run_dates(self):
        """Run id -> created_at, for checkpoint housekeeping."""
        with self.connect() as c:
            return {r["id"]: r["created_at"] for r in c.execute("SELECT id,created_at FROM runs")}

    def conversation_ids(self):
        with self.connect() as c:
            return {r["id"] for r in c.execute("SELECT id FROM conversations")}

    def record_cost(self, entry):
        with self.connect() as c:
            c.execute(
                """INSERT OR IGNORE INTO llm_costs(
                    response_id,provider,model,kind,input_tokens,cached_input_tokens,
                    cache_write_tokens,output_tokens,input_rate_nano,cached_rate_nano,
                    cache_write_rate_nano,output_rate_nano,cost_nano_usd,created_at
                ) VALUES(:response_id,:provider,:model,:kind,:input_tokens,:cached_input_tokens,
                    :cache_write_tokens,:output_tokens,:input_rate_nano,:cached_rate_nano,
                    :cache_write_rate_nano,:output_rate_nano,:cost_nano_usd,:created_at)""",
                entry,
            )

    def monthly_costs(self):
        current = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.connect() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT substr(created_at,1,7) AS month,SUM(cost_nano_usd) AS cost_nano_usd "
                "FROM llm_costs GROUP BY month ORDER BY month DESC"
            )]
        if not any(row["month"] == current for row in rows):
            rows.insert(0, {"month": current, "cost_nano_usd": 0})
        return [
            {"month": row["month"], "usd": row["cost_nano_usd"] / 1_000_000_000}
            for row in rows
        ]

    def run(self, rid):
        with self.connect() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if not row:
            raise KeyError("Run not found")
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["attachments"] = self.run_attachments(result)
        return result

    def run_attachments(self, run):
        """Attachment metadata in request order; deleted rows are omitted."""
        request = run["request"]
        ids = request.get("attachment_ids", [])
        if not ids:
            return []
        direct = set(request.get("direct_attachment_ids", []))
        with self.connect() as c:
            rows = {
                r["id"]: r for r in c.execute(
                    f"SELECT id,name,size,content_type FROM attachments "
                    f"WHERE conversation_id=? AND id IN ({','.join('?' * len(ids))})",
                    (run["conversation_id"], *ids),
                )
            }
        return [
            dict(id=aid, name=rows[aid]["name"], size=rows[aid]["size"],
                 content_type=rows[aid]["content_type"], direct=aid in direct)
            for aid in ids if aid in rows
        ]

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
            c.execute("DELETE FROM run_context_state WHERE run_id IN (SELECT id FROM runs WHERE conversation_id=?)", (cid,))
            c.execute("DELETE FROM runs WHERE conversation_id=?", (cid,))
            c.execute("DELETE FROM attachments WHERE conversation_id=?", (cid,))
            c.execute("DELETE FROM conversations WHERE id=?", (cid,))
