# Changelog

## 0.2.0

- OpenAI / Azure Responses API とローカルDockerサンドボックスに統一。
- 標準Skills・Remote MCP・元ファイル編集・永続化した実行履歴と停止UIを追加。
- 独自Skill/Ability、他社プロバイダ、Docling、旧API互換を削除。
- 研究用CPU実行環境と200ファイルのDocker統合テストを追加。

このプロジェクトの主な変更履歴を記録します。

## [Unreleased]

## [0.2.1] - 2026-10-12

### Fixed
- 停止要求が通常終了の後片付けを中断して作業フォルダのロックを残す問題を修正。
- サイズと更新日時を維持した内容変更をチェックポイントで検出し、Undo前に変更対象を再ハッシュしてユーザー編集の上書きを防止。
- 未送信の本文・添付・モデルへの直接添付指定を会話ごとにメモリ保持。送信成功または会話削除時に該当下書きだけ消去（再読み込み後は保持しない）。

## [0.1.2] - 2026-02-26

### Added
- AI/ML/NLP 論文向けの `paper_reviewer` Skill を追加
- `paper_reviewer` 用 rubric ドキュメント（ACL/ARR, ICML, NeurIPS, EMNLP の一次情報リンク）を追加

### Changed
- EDINET Skill のデフォルトキャッシュ先を `~/.cache/chat-orchestrator/edinet`（`XDG_CACHE_HOME` 優先）へ変更
- フロントエンドのストリーミング送信にキャンセル機能（Stop ボタン + AbortController）を追加
- README の EDINET Skill 説明を実装挙動に合わせて更新し、Paper Reviewer Skill の利用説明を追記

### Fixed
- EDINET 関連の未使用環境変数 `EDINET_ROUTER_ENABLE_LLM` / `EDINET_ROUTER_MODEL` の記載・設定差分を整理

## [0.1.0] - 2026-02-17

### Added
- 初期リリース
- マルチProvider対応チャット基盤
- セッション履歴、ストリーミング、添付ファイル処理、Markdown表示
