import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from app.attachments import save_attachment
from app.chat_service import ChatOrchestrator
from app.config import Settings, get_settings
from app.model_catalog import list_models, to_api
from app.providers.registry import ProviderRegistry
from app.schemas import (
    AuditNewsFeedbackRequest,
    AuditNewsMetricsResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConversationInfo,
    ConversationSummary,
    ExtractAttachmentsResponse,
    ModelInfo,
    ProviderInfo,
    SkillFeedbackRequest,
    SkillFeedbackResponse,
    SkillInfo,
)
from app.skills_runtime.base import SkillProgressReporter, SkillProgressUpdate
from app.skills_runtime.manager import SkillManager
from app.storage import ChatStore


class AppState:
    settings: Settings
    providers: ProviderRegistry
    skills: SkillManager
    store: ChatStore
    chat: ChatOrchestrator


state = AppState()
_ALLOWED_FEEDBACK_DECISIONS = {"acted", "monitor", "not_relevant"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    state.settings = settings
    state.providers = ProviderRegistry(settings=settings)

    project_root = Path(__file__).resolve().parents[1]
    skills_root = project_root / "skills"
    state.skills = SkillManager(skills_root=skills_root)
    state.skills.load()

    db_path = project_root / "data" / "chat.db"
    attachments_root = project_root / "data" / "attachments"
    state.store = ChatStore(db_path=db_path, attachments_root=attachments_root)
    state.chat = ChatOrchestrator(store=state.store, skills=state.skills)
    yield


app = FastAPI(title="Chat Orchestrator API", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/providers", response_model=list[ProviderInfo])
def list_providers() -> list[ProviderInfo]:
    return [ProviderInfo(**item) for item in state.settings.provider_catalog]


@app.get("/api/providers/{provider_id}/models", response_model=list[ModelInfo])
def list_provider_models(provider_id: str) -> list[ModelInfo]:
    return [ModelInfo(**item) for item in to_api(list_models(provider_id))]


@app.get("/api/skills", response_model=list[SkillInfo])
def list_skills() -> list[SkillInfo]:
    return [
        SkillInfo(
            id=skill.metadata.id,
            name=skill.metadata.name,
            description=skill.metadata.description,
            primary_category={
                "id": skill.metadata.primary_category.id,
                "label": skill.metadata.primary_category.label,
            },
            tags=list(skill.metadata.tags),
        )
        for skill in state.skills.list_skills()
    ]


@app.post("/api/attachments/extract", response_model=ExtractAttachmentsResponse)
async def extract_uploaded_attachments(
    conversation_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> ExtractAttachmentsResponse:
    normalized_conversation_id = state.store.ensure_conversation(conversation_id)
    uploaded = []
    for upload in files:
        pending = await save_attachment(
            conversation_id=normalized_conversation_id,
            upload=upload,
            attachments_root=state.store.attachments_root,
        )
        uploaded.append(
            state.store.add_attachment(
                attachment_id=pending.id,
                conversation_id=normalized_conversation_id,
                name=pending.name,
                content_type=pending.content_type,
                size_bytes=pending.size_bytes,
                original_path=pending.original_path,
                parsed_markdown_path=pending.parsed_markdown_path,
            )
        )
    return ExtractAttachmentsResponse(files=uploaded)


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    return state.store.list_conversations()


@app.get("/api/generated-files/{file_id}/download")
def download_generated_file(file_id: str) -> FileResponse:
    generated_file = state.store.get_generated_file(file_id)
    if not generated_file:
        raise HTTPException(status_code=404, detail=f"Unknown generated file: {file_id}")

    path = Path(generated_file.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Generated file is missing: {file_id}")

    return FileResponse(
        path=path,
        media_type=generated_file.content_type,
        filename=generated_file.name,
    )


@app.post("/api/conversations", response_model=ConversationInfo)
def create_conversation() -> ConversationInfo:
    conversation_id = state.store.create_conversation()
    return ConversationInfo(id=conversation_id)


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    state.store.delete_conversation(conversation_id)
    return {"ok": True}


@app.delete("/api/conversations")
def delete_all_conversations() -> dict[str, bool]:
    state.store.delete_all_conversations()
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[ChatMessage])
def get_conversation_messages(conversation_id: str) -> list[ChatMessage]:
    return state.store.get_messages(conversation_id=conversation_id)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    prepared = await state.chat.prepare_turn(payload)
    if state.chat.should_skip_model_response(prepared.skill_result):
        output = state.chat.resolve_assistant_content(content="", skill_result=prepared.skill_result)
    else:
        provider = state.providers.get(payload.provider_id)
        output = await provider.chat(
            model=payload.model,
            messages=prepared.prepared_messages,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            reasoning_effort=payload.reasoning_effort,
            enable_web_tool=prepared.effective_web_tool,
        )

    assistant_message = state.chat.build_assistant_message(
        content=output,
        skill_id=payload.skill_id,
        skill_result=prepared.skill_result,
    )
    state.chat.persist_user_message(
        conversation_id=prepared.conversation_id,
        user_input=prepared.user_input,
        attachments=prepared.attachments,
    )
    state.chat.persist_assistant_message(
        conversation_id=prepared.conversation_id,
        message=assistant_message,
        skill_result=prepared.skill_result,
    )
    return ChatResponse(
        provider_id=payload.provider_id,
        model=payload.model,
        output=output,
        conversation_id=prepared.conversation_id,
        message=assistant_message,
    )


@app.post("/api/skill-feedback", response_model=SkillFeedbackResponse)
def submit_skill_feedback(payload: SkillFeedbackRequest) -> SkillFeedbackResponse:
    decision = payload.decision.strip()
    if not decision:
        raise HTTPException(status_code=400, detail="decision cannot be empty")
    if not state.store.conversation_exists(payload.conversation_id):
        raise HTTPException(status_code=400, detail=f"Unknown conversation_id: {payload.conversation_id}")

    state.store.add_feedback(
        conversation_id=payload.conversation_id,
        run_id=payload.run_id,
        item_id=payload.item_id,
        decision=decision,
        note=payload.note,
    )
    return SkillFeedbackResponse(ok=True)


@app.post(
    "/api/skills/audit_news_action_brief/feedback",
    response_model=SkillFeedbackResponse,
)
def submit_audit_news_feedback(payload: AuditNewsFeedbackRequest) -> SkillFeedbackResponse:
    if payload.decision not in _ALLOWED_FEEDBACK_DECISIONS:
        raise HTTPException(status_code=400, detail="decision must be one of: acted, monitor, not_relevant")
    return submit_skill_feedback(
        SkillFeedbackRequest(
            conversation_id=payload.conversation_id,
            run_id=payload.run_id,
            item_id=payload.alert_id,
            decision=payload.decision,
            note=payload.note,
        )
    )


@app.get(
    "/api/skills/audit_news_action_brief/metrics",
    response_model=AuditNewsMetricsResponse,
)
def audit_news_metrics(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
) -> AuditNewsMetricsResponse:
    try:
        if from_date:
            date.fromisoformat(from_date)
        if to_date:
            date.fromisoformat(to_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {exc}") from exc

    metrics = state.store.audit_news_metrics(date_from=from_date, date_to=to_date)
    return AuditNewsMetricsResponse(**metrics)


@app.post("/api/chat/stream")
async def stream_chat(payload: ChatRequest) -> StreamingResponse:
    async def generate():
        try:
            prepared = None
            if payload.skill_id:
                startup_update = SkillProgressUpdate(stage="starting", label="準備しています")
                progress_queue: asyncio.Queue[SkillProgressUpdate] = asyncio.Queue()

                async def on_progress(update: SkillProgressUpdate) -> None:
                    await progress_queue.put(update)

                progress_reporter = SkillProgressReporter(
                    callback=on_progress,
                    last_update=startup_update,
                )
                yield json.dumps(
                    {
                        "type": "skill_status",
                        "status": "running",
                        "skill_id": payload.skill_id,
                        "stage": startup_update.stage,
                        "label": startup_update.label,
                    }
                ) + "\n"

                prepare_task = asyncio.create_task(
                    state.chat.prepare_turn(payload, progress_reporter=progress_reporter)
                )
                while not prepare_task.done():
                    try:
                        update = await asyncio.wait_for(progress_queue.get(), timeout=0.05)
                    except asyncio.TimeoutError:
                        continue
                    yield json.dumps(
                        {
                            "type": "skill_status",
                            "status": "running",
                            "skill_id": payload.skill_id,
                            "stage": update.stage,
                            "label": update.label,
                        }
                    ) + "\n"

                prepared = await prepare_task
                while not progress_queue.empty():
                    update = progress_queue.get_nowait()
                    yield json.dumps(
                        {
                            "type": "skill_status",
                            "status": "running",
                            "skill_id": payload.skill_id,
                            "stage": update.stage,
                            "label": update.label,
                        }
                    ) + "\n"
            else:
                prepared = await state.chat.prepare_turn(payload)
            state.chat.persist_user_message(
                conversation_id=prepared.conversation_id,
                user_input=prepared.user_input,
                attachments=prepared.attachments,
            )

            if payload.skill_id:
                yield json.dumps(
                    {
                        "type": "skill_status",
                        "status": "done",
                        "skill_id": payload.skill_id,
                        "stage": "completed",
                        "label": "完了しました",
                    }
                ) + "\n"

            accumulated = ""
            if state.chat.should_skip_model_response(prepared.skill_result):
                accumulated = state.chat.resolve_assistant_content(content="", skill_result=prepared.skill_result)
            else:
                provider = state.providers.get(payload.provider_id)
                async for chunk in provider.stream_chat(
                    model=payload.model,
                    messages=prepared.prepared_messages,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                    reasoning_effort=payload.reasoning_effort,
                    enable_web_tool=prepared.effective_web_tool,
                ):
                    accumulated += chunk
                    yield json.dumps({"type": "chunk", "delta": chunk}) + "\n"

            assistant_message = state.chat.build_assistant_message(
                content=accumulated,
                skill_id=payload.skill_id,
                skill_result=prepared.skill_result,
            )
            state.chat.persist_assistant_message(
                conversation_id=prepared.conversation_id,
                message=assistant_message,
                skill_result=prepared.skill_result,
            )
            yield json.dumps(
                {
                    "type": "done",
                    "conversation_id": prepared.conversation_id,
                    "provider_id": payload.provider_id,
                    "model": payload.model,
                    "message": assistant_message.model_dump(mode="json"),
                }
            ) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
