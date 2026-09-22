import asyncio
import fcntl
import json
import mimetypes
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent_runner import RunManager
from app.attachments import list_files, open_regular, save_upload
from app.config import get_settings
from app.model_catalog import models_for
from app.schemas import (
    AppSettingsUpdate,
    Approval,
    ConversationCreate,
    ConversationUpdate,
    RunCreate,
)
from app.storage import TERMINAL, Store


def create_app(settings=None, manager_factory=RunManager):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        config = settings.load_runtime()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with (settings.data_dir / "server.lock").open("a") as process_lock:
            try:
                fcntl.flock(process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError(
                    "Only one backend process may use this data directory"
                ) from None
            store = Store(settings.data_dir)
            # Never expose the app's credential/state directory as a workspace.
            for w in [*config.workspaces, *config.skills, *config.resources]:
                for private in (
                    settings.data_dir.resolve(),
                    settings.runtime_config.resolve(),
                    settings.runtime_config.parent / ".env",
                    Path(__file__).resolve().parents[2] / ".env",
                    Path(__file__).resolve().parents[1] / ".env",
                ):
                    if private.is_relative_to(w.path):
                        raise ValueError(
                            f"Workspace {w.id} contains application configuration/state"
                        )
            manager = manager_factory(settings, config, store)
            manager.title_selection()
            app.state.config, app.state.store, app.state.manager = (
                config,
                store,
                manager,
            )
            await manager.recover()
            try:
                yield
            finally:
                await manager.shutdown()

    app = FastAPI(title="Local Responses Workspace", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": "Cross-site access is not allowed"}, status_code=403
            )
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing(_, error):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_, error):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(_, error):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"detail": "This conversation already has an active run"}, status_code=409
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/config")
    async def config():
        c = app.state.config
        return dict(
            providers=[
                dict(
                    id="openai",
                    label="OpenAI",
                    enabled=bool(settings.openai_api_key),
                    models=models_for("openai", c),
                ),
                dict(
                    id="azure_openai",
                    label="Azure OpenAI",
                    enabled=bool(
                        settings.azure_openai_api_key and settings.azure_openai_endpoint
                    ),
                    models=models_for("azure_openai", c),
                ),
            ],
            workspaces=[
                dict(id=w.id, label=w.label, path=str(w.path)) for w in c.workspaces
            ],
            skills=[
                dict(id=s.id, label=s.label, name=s.name, description=s.description)
                for s in c.skills
            ],
            resources=[dict(id=r.id, label=r.label) for r in c.resources],
            mcp_servers=[dict(id=m.id, label=m.label) for m in c.mcp_servers],
        )

    @app.get("/api/settings")
    async def app_settings():
        return app.state.manager.title_selection()

    @app.patch("/api/settings")
    async def update_app_settings(body: AppSettingsUpdate):
        provider, model = body.title_selection()
        if provider and model:
            app.state.manager.validate_title_selection(provider, model)
        changes = body.model_dump(exclude_none=True)
        if "theme_color" in changes:
            changes["theme_color"] = changes["theme_color"].upper()
        return app.state.store.update_settings(**changes)

    @app.get("/api/costs/monthly")
    async def monthly_costs():
        return dict(
            currency="USD",
            estimated=True,
            timezone="UTC",
            exclusions=["tool_fees"],
            months=app.state.store.monthly_costs(),
        )

    @app.get("/api/conversations")
    async def conversations(q: str = ""):
        return app.state.store.conversations(q)

    @app.post("/api/conversations")
    async def new_conversation(body: ConversationCreate):
        app.state.manager.select(app.state.config.workspaces, [body.workspace_id])
        c = app.state.store.create_conversation(body.workspace_id)
        return {k: v for k, v in c.items() if k != "context"}

    @app.get("/api/conversations/{cid}")
    async def conversation(cid: str):
        c = app.state.store.conversation(cid)
        return {
            **{k: v for k, v in c.items() if k != "context"},
            "runs": app.state.store.runs(cid),
        }

    @app.patch("/api/conversations/{cid}")
    async def update_conversation(cid: str, body: ConversationUpdate):
        c = app.state.store.pin_conversation(cid, body.pinned)
        return {k: v for k, v in c.items() if k != "context"}

    @app.delete("/api/conversations/{cid}")
    async def delete_conversation(cid: str):
        app.state.store.delete_conversation(cid)
        # Intentionally retain managed files as well; no recursive delete touches user mounts.
        return {"ok": True}

    @app.post("/api/attachments")
    async def attachments(
        conversation_id: str = Form(...), files: list[UploadFile] = File(...)
    ):
        return [
            await save_upload(
                app.state.store, conversation_id, f, settings.max_upload_bytes
            )
            for f in files
        ]

    def workspace(cid):
        c = app.state.store.conversation(cid)
        return app.state.manager.select(
            app.state.config.workspaces, [c["workspace_id"]]
        )[0]

    @app.get("/api/conversations/{cid}/files")
    async def files(cid: str, path: str = ""):
        try:
            return list_files(workspace(cid).path, path)
        except (OSError, ValueError):
            raise HTTPException(400, "Invalid or unavailable directory") from None

    @app.get("/api/conversations/{cid}/download")
    async def download(cid: str, path: str):
        try:
            file = open_regular(workspace(cid).path, path)
        except (OSError, ValueError):
            raise HTTPException(400, "Invalid or unavailable file") from None

        def chunks():
            try:
                while block := file.read(65536):
                    yield block
            finally:
                file.close()

        return StreamingResponse(
            chunks(),
            media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(path.split("/")[-1])
            },
        )

    @app.post("/api/runs")
    async def run(body: RunCreate):
        return app.state.manager.start(body)

    @app.get("/api/runs/{rid}")
    async def get_run(rid: str):
        return app.state.store.run(rid)

    @app.post("/api/runs/{rid}/stop")
    async def stop(rid: str):
        await app.state.manager.stop(rid)
        return app.state.store.run(rid)

    @app.post("/api/runs/{rid}/approvals")
    async def approval(rid: str, body: Approval):
        app.state.manager.approve(rid, body)
        return {"ok": True}

    @app.get("/api/runs/{rid}/events")
    async def events(rid: str, after: int = Query(0, ge=0)):
        app.state.store.run(rid)

        async def stream():
            cursor = after
            while True:
                batch = app.state.store.events(rid, cursor)
                for event in batch:
                    cursor = event["seq"]
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                if batch:
                    continue
                latest_run = app.state.store.run(rid)
                if latest_run["status"] in TERMINAL:
                    conversation_state = app.state.store.conversation(
                        latest_run["conversation_id"]
                    )
                    if conversation_state.get("title_status") == "generating":
                        await asyncio.sleep(0.2)
                        continue
                    # Re-read after terminal status so events committed concurrently are drained.
                    for event in app.state.store.events(rid, cursor):
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                    break
                yield "\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
