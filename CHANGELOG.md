# Changelog

## 0.2.0

- OpenAI / Azure Responses API とローカルDockerサンドボックスに統一。
- 標準Skills・Remote MCP・元ファイル編集・永続化した実行履歴と停止UIを追加。
- 独自Skill/Ability、他社プロバイダ、Docling、旧API互換を削除。
- 研究用CPU実行環境と200ファイルのDocker統合テストを追加。

このプロジェクトの主な変更履歴を記録します。

## [Unreleased]

### Changed
- macOSでは作業フォルダのファイル変更イベント（FSEvents）を使い、checkpointで変更のあったファイルだけをstat・ハッシュするよう変更。最後の状態とGitのindexを保存して差分だけを更新し、5万ファイルで変更が少ない場合のcheckpointを約1.2秒から約0.3秒に短縮。イベントの完全性を確認できない場合は全ファイル走査に戻る。`WORKSPACE_WATCH=false` で無効化可能。
- バックエンド起動時に登録済み作業フォルダのcheckpointをバックグラウンドで作成し、初回実行のハッシュ待ちを解消。完了前に始めた実行は待機中の進捗を表示。
- 前回のcheckpoint以降に変更イベントがない場合は、ファイル一覧を取らずに前回の内容を再利用（5万ファイルで約0.1秒）。
- 古い実行のcheckpointを削除しても、最新の保存状態が参照するファイル内容は保持するよう変更。

### Fixed
- 実行前後の作業フォルダ走査がイベントループを止め、大きな作業フォルダで画面全体が固まる問題を修正。成果物の変更一覧はcheckpointの走査結果を再利用し、1実行あたりの全体走査を4回から2回に削減。

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
