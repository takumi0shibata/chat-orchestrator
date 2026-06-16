# Chat Orchestrator

OpenAI / Azure OpenAI / Anthropic / Google / DeepSeek など複数 Provider に対応した、拡張しやすいチャット基盤です。フロントエンドは TypeScript + Vite + React、バックエンドは Python + FastAPI です。

## 特徴

- 会話履歴を SQLite (`backend/data/chat.db`) に永続化
- Provider 抽象化: `backend/app/providers/` にクラスを追加すれば拡張可能
- Skill 抽象化: `backend/skills/<skill_id>/skill.yaml` を正本としてローカル skill を追加可能
- Ability 抽象化: 既存 skill を agentic runtime から呼び出せる能力単位として公開
- OpenAI / Azure OpenAI の Responses API モデルに対応
- OpenAI Agents SDK による agentic orchestration に対応
- モデル能力差分を `backend/app/model_catalog.py` で一元管理

## ディレクトリ構成

- `backend/app`: API 本体
- `backend/app/abilities_runtime`: Ability contract / legacy Skill wrapper
- `backend/app/agent_runner.py`: OpenAI Agents SDK による agentic 実行
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

## Agentic 実行

OpenAI / Azure OpenAI の Responses API モデルでは、`execution_mode: "agentic"` を指定すると OpenAI Agents SDK ベースの runtime が動きます。

- `ability_ids: null`: 登録済み Ability をすべて候補として agent に渡し、必要なものを agent が選択します。
- `ability_ids: ["todo_extractor"]`: 指定した Ability だけを agent に渡します。
- `skill_id`: 後方互換の alias です。`execution_mode: "agentic"` では単一 Ability 指定として扱い、`execution_mode: "direct"` では従来の skill 先実行として扱います。
- Anthropic / Google / DeepSeek は当面 `execution_mode: "direct"` の通常チャット経路で動きます。

streaming では通常の `chunk` / `done` に加えて、Ability が実際に起動したときだけ次の agentic event が流れます。

- `ability_started`: Ability 実行開始
- `agent_status`: Ability に紐づく進捗
- `ability_completed`: Ability 実行完了
- `artifact`: Ability が生成した UI artifact
- `trace_ref`: Agents SDK trace id

UI は、通常応答では Thinking 表示だけを出し、Ability が実際に呼ばれた場合だけ Ability 名と現在工程を表示します。

## Skill 追加方法

skill は次の3点セットを必須にします。

- `backend/skills/<skill_id>/skill.yaml`
- `backend/skills/<skill_id>/skill.py`
- `backend/skills/<skill_id>/README.md`

`skill.yaml` が正本です。loader は manifest を読み込み、`skill.py` の factory を呼び、`README.md` の存在と metadata 整合性を検証します。欠落や不整合がある skill は起動時に失敗します。

既存 skill は自動的に Ability としても公開されます。Ability は「1つの能力」を表す実行単位で、agentic runtime から function tool として呼び出されます。v1 では既存 `Skill.run()` を wrapper 経由で呼び出すため、既存 skill 実装はそのまま動きます。

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
ability:
  input_schema:
    type: object
    additionalProperties: true
    properties:
      task:
        type: string
        description: Ability に渡す補足指示。
```

`ability.input_schema` は任意です。未指定の場合は `task: string` を受け取れる緩い schema が使われます。agent が structured params を渡す必要がある Ability では、ここに JSON schema を定義してください。

### `skill.py` テンプレート

```python
from typing import Any

from app.skills_runtime.base import (
    Skill,
    SkillCategory,
    SkillExecutionResult,
    SkillMetadata,
    context_only_result,
    get_skill_progress,
)


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
        progress = get_skill_progress(skill_context)
        await progress.update(stage="inspect_input", label="入力を確認しています")
        del history
        await progress.update(stage="build_context", label="結果を整えています")
        return context_only_result(f"Input: {user_text}")


def build_skill() -> Skill:
    return ExampleSkill()
```

skill 実行中に UI へ進捗ラベルを出したい場合は、`get_skill_progress(skill_context)` で reporter を取得し、`await progress.update(stage="snake_case", label="短い日本語ラベル")` を 2-5 箇所の粗い工程境界で呼んでください。未対応環境では no-op になります。

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
- `GET /api/abilities`
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
  "execution_mode": "agentic",
  "ability_ids": null,
  "reasoning_effort": "medium",
  "temperature": null,
  "enable_web_tool": false,
  "skill_id": "todo_extractor"
}
```

`POST /api/attachments/extract` は `multipart/form-data` で `conversation_id` と `files[]` を受け取り、原本ファイルと抽出 Markdown を backend の管理ディレクトリに保存します。通常チャットでは抽出 Markdown を LLM 文脈へ自動注入し、skill 実行時は自動注入せず `skill_context["attachments"]` 経由で `original_path` / `parsed_markdown_path` を参照できます。

添付抽出は [Docling](https://docling-project.github.io/docling/) を優先利用します。初回のフォーマットによってはローカルモデル取得が走るので、Docker/本番環境では起動後最初の添付処理が少し遅くなる可能性があります。
