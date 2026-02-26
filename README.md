# Chat Orchestrator

OpenAI / Azure OpenAI / Anthropic / Google / DeepSeek など複数Providerに対応した、拡張しやすいチャットボット基盤です。  
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

## バージョン管理（王道の最小運用）

- ルール: SemVer (`MAJOR.MINOR.PATCH`)
- 単一のバージョン源: `VERSION`
- 同期対象:
  - `backend/pyproject.toml`
  - `frontend/package.json`
  - `CHANGELOG.md`

使い方:

```bash
# バグ修正リリース
make release-patch

# 機能追加リリース
make release-minor

# 破壊的変更リリース
make release-major
```

リリース時の流れ:

1. `make release-xxx` を実行
2. `CHANGELOG.md` の該当バージョン欄を埋める
3. `git add VERSION backend/pyproject.toml frontend/package.json CHANGELOG.md`
4. `git commit -m "chore(release): vX.Y.Z"`
5. `git tag vX.Y.Z`
6. `git push origin main --tags`

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

## Azure OpenAI の設定

`.env` に以下を設定すると、Provider 一覧に `Azure OpenAI` が追加されます。

```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>
```

任意設定:

```bash
# responses か chat_completions
AZURE_OPENAI_API_MODE=responses
```

この実装では Azure OpenAI の `model` にデプロイ名をそのまま渡します。

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

## EDINET有報QA Skill

`backend/skills/edinet_report_qa/skill.py` は、質問文から企業・年度/決算期・参照セクションを解釈し、EDINET APIから有価証券報告書（通常/訂正）を取得して XBRL 抽出コンテキストを作るスキルです。

主な仕様:

- 企業指定: `EDINETコード(E12345)` / 企業名 / 証券コード(4桁) に対応
- 期間指定: `2024年度` または `2024年3月期` などに対応（複数期比較も対応）
- セクション指定: `事業等のリスク` などを辞書（`docs/sections.json`）で解決
- 曖昧時: 候補企業を返して再指定を促す
- 意図解析: 利用中の provider/model で LLM 解析を試行し、失敗時はルールベースにフォールバック

最低限の設定:

```bash
EDINET_API_KEY=your_subscription_key
```

任意設定:

```bash
EDINET_CACHE_DIR=$HOME/.cache/chat-orchestrator/edinet
EDINET_CACHE_TTL_HOURS=24
EDINET_LOOKBACK_DAYS=365
```

利用例（`skill_id` 指定）:

```json
{
  "provider_id": "openai",
  "model": "gpt-4o-mini",
  "user_input": "トヨタ(7203)とホンダの2024年3月期の事業等のリスクを比較して",
  "skill_id": "edinet_report_qa"
}
```

`再取得` / `再実行` / `retry` などの語が質問に含まれる場合は、キャッシュより再取得を優先します。
