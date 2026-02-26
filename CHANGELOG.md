# Changelog

このプロジェクトの主な変更履歴を記録します。

## [Unreleased]

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
