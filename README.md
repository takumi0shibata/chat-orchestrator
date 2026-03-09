# Chat Orchestrator

OpenAI / Azure OpenAI / Anthropic / Google / DeepSeek など複数 Provider に対応した、拡張しやすいチャット基盤です。フロントエンドは TypeScript + Vite + React、バックエンドは Python + FastAPI です。

## 特徴

- 会話履歴を SQLite (`backend/data/chat.db`) に永続化
- Provider 抽象化: `backend/app/providers/` にクラスを追加すれば拡張可能
- Skill 抽象化: `backend/skills/<skill_id>/skill.yaml` を正本としてローカル skill を追加可能
- OpenAI / Azure OpenAI の Responses API モデルに対応
- モデル能力差分を `backend/app/model_catalog.py` で一元管理

## ディレクトリ構成

- `backend/app`: API 本体
- `backend/app/providers`: LLM Provider 実装
- `backend/app/model_catalog.py`: モデル能力定義
- `backend/app/skills_runtime`: Skill loader / validation
- `backend/skills`: ローカル skill 実装
- `docs/skill-template`: skill 追加用テンプレート
- `frontend/src`: Vite フロントエンド

## セットアップ

前提: Python 3.11+, Node 20+, `uv`

```bash
cp .env.example .env
make setup-backend
make dev-backend
make setup-frontend
make dev-frontend
```

アクセス先:

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Backend Docs: http://localhost:8000/docs

## モデル管理

OpenAI / Azure OpenAI のモデルは `backend/app/model_catalog.py` で管理します。

Responses API モデル例:

```python
ModelCapability(
    id="gpt-5.4-2026-03-05",
    label="GPT-5.4",
    api_mode="responses",
    supports_temperature=False,
    supports_reasoning_effort=True,
    default_temperature=None,
    default_reasoning_effort="medium",
    reasoning_effort_options=("none", "low", "medium", "high", "xhigh"),
)
```

`POST /api/chat` / `POST /api/chat/stream` では `reasoning_effort` に `none | low | medium | high | xhigh` を指定できます。

## Skill 追加方法

skill は次の3点セットを必須にします。

- `backend/skills/<skill_id>/skill.yaml`
- `backend/skills/<skill_id>/skill.py`
- `backend/skills/<skill_id>/README.md`

`skill.yaml` が正本です。loader は manifest を読み込み、`skill.py` の factory を呼び、`README.md` の存在と metadata 整合性を検証します。欠落や不整合がある skill は起動時に失敗します。

### 追加手順

1. `docs/skill-template/` をコピーして新しい skill ディレクトリを作る
2. `skill.yaml` の `id / name / description / primary_category / tags` を更新する
3. `skill.py` に `build_skill()` と `run()` を実装する
4. `README.md` に人間向けの使い方を書く
5. `GET /api/skills` と対象テストで読み込みを確認する

### `skill.yaml` テンプレート

```yaml
id: example_skill
name: Example Skill
description: 何をする skill かを1文で書く。
primary_category:
  id: general
  label: General
tags:
  - general
  - example
entrypoint: skill.py
factory: build_skill
readme: README.md
```

### `skill.py` テンプレート

```python
from typing import Any

from app.skills_runtime.base import Skill, SkillCategory, SkillExecutionResult, SkillMetadata, context_only_result


class ExampleSkill(Skill):
    metadata = SkillMetadata(
        id="example_skill",
        name="Example Skill",
        description="何をする skill かを1文で書く。",
        primary_category=SkillCategory(id="general", label="General"),
        tags=["general", "example"],
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> SkillExecutionResult:
        del history, skill_context
        return context_only_result(f"Input: {user_text}")


def build_skill() -> Skill:
    return ExampleSkill()
```

### `README.md` テンプレート

`docs/skill-template/README.md` を使ってください。少なくとも次の見出しを揃えます。

- `概要`
- `使う場面`
- `必要設定`
- `入力`
- `出力 / Artifacts`
- `実装メモ`

## API 概要

- `GET /api/providers`
- `GET /api/providers/{provider_id}/models`
- `GET /api/skills`
- `GET /api/conversations`
- `POST /api/conversations`
- `GET /api/conversations/{id}/messages`
- `POST /api/attachments/extract`
- `POST /api/chat`
- `POST /api/chat/stream`
- `POST /api/skill-feedback`

`POST /api/chat/stream` body 例:

```json
{
  "provider_id": "openai",
  "model": "gpt-5.4-2026-03-05",
  "conversation_id": "<conversation-id>",
  "user_input": "こんにちは",
  "attachment_ids": [],
  "reasoning_effort": "medium",
  "temperature": null,
  "enable_web_tool": false,
  "skill_id": "todo_extractor"
}
```

`POST /api/attachments/extract` は `multipart/form-data` で `conversation_id` と `files[]` を受け取り、原本ファイルと抽出 Markdown を backend の管理ディレクトリに保存します。通常チャットでは抽出 Markdown を LLM 文脈へ自動注入し、skill 実行時は自動注入せず `skill_context["attachments"]` 経由で `original_path` / `parsed_markdown_path` を参照できます。

添付抽出は [Docling](https://docling-project.github.io/docling/) を優先利用します。初回のフォーマットによってはローカルモデル取得が走るので、Docker/本番環境では起動後最初の添付処理が少し遅くなる可能性があります。
