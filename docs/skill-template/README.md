# Example Skill

## 概要
skill の目的を短く書く。

## 使う場面
- どういうユーザー要求で使うか

## 必要設定
- 必要な環境変数、外部ファイル、API キー

## 入力
- 想定するユーザー入力
- 添付を使う skill の場合は `skill_context["attachments"]` から `original_path` / `parsed_markdown_path` を読む
- agentic runtime から呼ばれる場合は `skill_context["ability_params"]` に `skill.yaml` の `ability.input_schema` に沿った補足パラメータが入る
- 進捗表示を出す場合は `get_skill_progress(skill_context)` で reporter を取得し、`await progress.update(stage="...", label="...")` を coarse-grained に呼ぶ

## 出力 / Artifacts
- 補助コンテキストの形
- artifacts を返すならその型

## 実装メモ
- 関連モジュールや補足事項
- 1 skill / 1 ability は 1 つの明確な能力に寄せる
- LLM による判断、分解、文章生成は可能な限り agentic runtime に任せ、skill 本体は観測可能な処理や成果物生成に集中する
