import json
import inspect
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.attachments import extract_attachments
from app.config import Settings, get_settings
from app.model_catalog import list_models, to_api
from app.providers.registry import ProviderRegistry
from app.schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConversationInfo,
    ConversationSummary,
    ExtractAttachmentsResponse,
    ModelInfo,
    ProviderInfo,
    SkillInfo,
)
from app.skills_runtime.manager import SkillManager
from app.storage import ChatStore


class AppState:
    settings: Settings
    providers: ProviderRegistry
    skills: SkillManager
    store: ChatStore


state = AppState()


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
    state.store = ChatStore(db_path=db_path)
    yield


app = FastAPI(title="Chat Orchestrator API", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def run_skill_if_needed(
    *,
    skill_id: str | None,
    provider_id: str,
    model: str,
    user_input: str,
    messages: list[ChatMessage],
) -> tuple[list[ChatMessage], str | None]:
    if not skill_id:
        return messages, None

    skill = state.skills.get(skill_id)
    if not skill:
        raise HTTPException(status_code=400, detail=f"Unknown skill: {skill_id}")

    history = [m.model_dump() for m in messages]
    run_params = inspect.signature(skill.run).parameters
    if "skill_context" in run_params:
        skill_output = await skill.run(
            user_text=user_input,
            history=history,
            skill_context={"provider_id": provider_id, "model": model},
        )
    else:
        skill_output = await skill.run(user_text=user_input, history=history)
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You have supplemental context from a local skill. Use it when relevant.\n"
                f"[Skill:{skill_id}]\n{skill_output}"
            ),
        ),
        *messages,
    ]
    return messages, skill_output


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
        )
        for skill in state.skills.list_skills()
    ]


@app.post("/api/attachments/extract", response_model=ExtractAttachmentsResponse)
async def extract_uploaded_attachments(files: list[UploadFile] = File(...)) -> ExtractAttachmentsResponse:
    extracted = await extract_attachments(files)
    return ExtractAttachmentsResponse(
        files=[{"name": item.name, "content": item.content} for item in extracted]
    )


@app.get("/api/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[ConversationSummary]:
    return state.store.list_conversations()


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
    if not payload.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input cannot be empty")

    provider = state.providers.get(payload.provider_id)
    conversation_id = state.store.ensure_conversation(payload.conversation_id)
    history = state.store.get_messages(conversation_id)

    user_input = payload.user_input.strip()
    messages = [*history, ChatMessage(role="user", content=user_input)]
    prepared_messages, skill_output = await run_skill_if_needed(
        skill_id=payload.skill_id,
        provider_id=payload.provider_id,
        model=payload.model,
        user_input=user_input,
        messages=messages,
    )

    output = await provider.chat(
        model=payload.model,
        messages=prepared_messages,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        reasoning_effort=payload.reasoning_effort,
    )

    state.store.ensure_title_from_user_input(conversation_id, user_input)
    state.store.add_message(conversation_id, ChatMessage(role="user", content=user_input))
    state.store.add_message(conversation_id, ChatMessage(role="assistant", content=output))

    return ChatResponse(
        provider_id=payload.provider_id,
        model=payload.model,
        output=output,
        conversation_id=conversation_id,
        skill_output=skill_output,
    )


@app.post("/api/chat/stream")
async def stream_chat(payload: ChatRequest) -> StreamingResponse:
    if not payload.user_input.strip():
        raise HTTPException(status_code=400, detail="user_input cannot be empty")

    provider = state.providers.get(payload.provider_id)
    conversation_id = state.store.ensure_conversation(payload.conversation_id)
    history = state.store.get_messages(conversation_id)
    if payload.skill_id and not state.skills.get(payload.skill_id):
        raise HTTPException(status_code=400, detail=f"Unknown skill: {payload.skill_id}")

    user_input = payload.user_input.strip()
    messages = [*history, ChatMessage(role="user", content=user_input)]

    async def generate():
        state.store.ensure_title_from_user_input(conversation_id, user_input)
        state.store.add_message(conversation_id, ChatMessage(role="user", content=user_input))
        accumulated = ""
        skill_output: str | None = None
        prepared_messages = messages

        try:
            if payload.skill_id:
                yield json.dumps(
                    {"type": "skill_status", "status": "running", "skill_id": payload.skill_id}
                ) + "\n"

            prepared_messages, skill_output = await run_skill_if_needed(
                skill_id=payload.skill_id,
                provider_id=payload.provider_id,
                model=payload.model,
                user_input=user_input,
                messages=messages,
            )

            if payload.skill_id:
                yield json.dumps({"type": "skill_status", "status": "done", "skill_id": payload.skill_id}) + "\n"

            async for chunk in provider.stream_chat(
                model=payload.model,
                messages=prepared_messages,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                reasoning_effort=payload.reasoning_effort,
            ):
                accumulated += chunk
                yield json.dumps({"type": "chunk", "delta": chunk}) + "\n"

            state.store.add_message(conversation_id, ChatMessage(role="assistant", content=accumulated))
            yield json.dumps(
                {
                    "type": "done",
                    "conversation_id": conversation_id,
                    "provider_id": payload.provider_id,
                    "model": payload.model,
                    "skill_output": skill_output,
                }
            ) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
