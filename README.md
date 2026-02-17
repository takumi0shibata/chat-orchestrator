# Chat Orchestrator

OpenAI / Anthropic / Google / DeepSeek など複数Providerに対応した、拡張しやすいチャットボット基盤です。  
フロントエンドは TypeScript + Vite + React、バックエンドは Python + FastAPI です。

## 特徴

- ChatGPT風のモダンUI（セッション一覧・会話切替・ストリーミング表示）
- 会話履歴を SQLite (`backend/data/chat.db`) に永続化
- Provider抽象化: `backend/app/providers/` にProviderクラスを追加するだけで拡張可能
- Skill抽象化: `backend/skills/<skill_id>/skill.py` を置くだけでローカルSkillを追加可能
- OpenAIモデル能力差分をモデルカタログで管理
  - 例: `temperature` 非対応モデル / `reasoning_effort` 対応モデル
  - Responses APIを使うモデルを `api_mode="responses"` で指定可能

## ディレクトリ構成

- `backend/app`: API本体
- `backend/app/providers`: LLM Provider実装
- `backend/app/model_catalog.py`: モデル能力定義
- `backend/app/skills_runtime`: Skillローダー
- `backend/skills`: ユーザー定義Skill
- `backend/data`: 永続化DB
- `frontend/src`: Viteフロントエンド

## セットアップ (ローカル)

前提: Python 3.11+, Node 20+, `uv`

1. 環境変数

```bash
cp .env.example .env
# .env に各APIキーを設定
```

2. バックエンド

```bash
make setup-backend
make dev-backend
```

3. フロントエンド

```bash
make setup-frontend
make dev-frontend
```

アクセス先:
- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Backend Docs: http://localhost:8000/docs

## セットアップ (Docker)

```bash
cp .env.example .env
docker compose up --build
```

## モデル追加方法（特にOpenAI）

`backend/app/model_catalog.py` の `OPENAI_MODELS` に1件追加するだけです。

例:

```python
ModelCapability(
    id="gpt-5.2",
    label="GPT-5.2",
    api_mode="responses",
    supports_temperature=False,
    supports_reasoning_effort=True,
    default_temperature=None,
    default_reasoning_effort="medium",
)
```

## API概要

- `GET /api/providers`: 利用可能Provider一覧
- `GET /api/providers/{provider_id}/models`: モデル能力一覧
- `GET /api/skills`: Skill一覧
- `GET /api/conversations`: 会話セッション一覧
- `POST /api/conversations`: 会話作成
- `GET /api/conversations/{id}/messages`: 会話履歴取得
- `POST /api/attachments/extract`: 添付ファイル（PDF/TXT等）からテキスト抽出
- `POST /api/chat`: 非ストリーミング応答
- `POST /api/chat/stream`: NDJSONストリーミング応答

`POST /api/chat/stream` body例:

```json
{
  "provider_id": "openai",
  "model": "gpt-5.2",
  "conversation_id": "<conversation-id>",
  "user_input": "こんにちは",
  "reasoning_effort": "medium",
  "temperature": null,
  "skill_id": "todo_extractor"
}
```
