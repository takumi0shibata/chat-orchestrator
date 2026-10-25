# Changelog

## 0.2.0

- OpenAI / Azure Responses API とローカルDockerサンドボックスに統一。
- 標準Skills・Remote MCP・元ファイル編集・永続化した実行履歴と停止UIを追加。
- 独自Skill/Ability、他社プロバイダ、Docling、旧API互換を削除。
- 研究用CPU実行環境と200ファイルのDocker統合テストを追加。

このプロジェクトの主な変更履歴を記録します。

## [Unreleased]

### Added

- Added the MIT License for Orchestrator and matching application license metadata, preserving third-party licenses and attribution.

## [0.3.2] - 2026-10-24

This release includes the appearance selector as a PATCH by explicit maintainer decision. No manual data migration is required.

### Added

- Added a browser-local Appearance selector in Settings → General with System, Light, and Dark modes. System mode follows live OS changes.

### Changed

- Softened the chat and Files sidebar backgrounds in both appearances and made Show more neutral gray.

- Reworked the English README with setup, authentication, everyday workflows, safety limits, and troubleshooting. Standardized application-generated labels, messages, and audit drafts in English while preserving user content and existing records.

### Fixed
- Apply saved or system appearance before the application bundle loads to avoid a light flash in dark mode.
- Make bundled Guild Journal and Project Audit records follow the requested language, preserve user wording, and use recognized English or Japanese structural headings.
- Coalesce streamed recovery text and cap serialized journal size so stopped replies do not inflate later model context with per-token JSON.
- Use singular file wording for one-file artifact events and Undo confirmation.
- Reject oversized attachments before upload using the configured limit, and include the limit in server errors.
- Reuse the currently selected untouched new chat instead of creating repeated empty chats in the same project.
- Retry failed title generation on the next run using the original task while retaining the fallback title in the meantime.
- Render large file-browser folders in batches of 100 with Show more, keeping all paths accessible.
- Close cancelled shell-command activity with a stopped outcome and document unreported usage on interrupted requests.
- Name observed file changes that have no complete checkpoint backup and cannot be restored by Undo.
- Clarify that dashboard run counts cover stored chats while API usage survives deletion and excludes unreported usage.
- Explain how to build or configure a missing sandbox image instead of only suggesting a Docker retry.
- Show provider setup guidance beside the composer when the selected connection cannot send messages.
- Show an inline error for unavailable result files instead of downloading a JSON error response.
- Refresh the Files panel after a successful Undo.
- Explain rejected provider credentials with setup guidance instead of exposing the SDK error representation.
- Label failed and stopped runs explicitly instead of displaying the successful-work heading.
- Confirm chat deletion, prevent duplicate deletion and editing while it is pending, and leave chats removed in another window.
- Redact masked OpenAI key fragments from provider errors in logs and run events.
- Return readable API validation and missing-resource errors without Python quotes or echoed request contents.
- Disable MIME sniffing for workspace downloads, consistent with attachment downloads.
- Reject empty Docker server-version checks so older CLIs cannot lock an untouched workspace when the daemon is unavailable.
- Docker availability failures before container creation allow retry without restarting the backend. Startup cancellation, timeouts, and uncertain container removal still require confirmed cleanup and retain workspace protection when cleanup fails.

## [0.3.1] - 2026-10-22

### Fixed
- checkpointの除外警告だけがある応答に「0 files changed」のUndoカードを表示する問題を修正。変更ファイルがない場合はカードを表示せず、保存対象外ファイルや旧checkpointの安全上の警告は単独で保持する。
- 会話の削除完了前に別の会話へ切り替えた場合、遅れて返る削除結果が移動先の選択を解除する問題を修正。移動先の画面と下書きを保持する。

## [0.3.0] - 2026-10-20

### Added
- ダークモードに対応。OSのライト／ダーク設定に自動で追従する。ライトモードの見た目は変更なし。ダークモードではテーマカラーの明度を補正し、送信ボタンなどの主要ボタンには明るい色調を使う。
- Settingsを開くと最初に表示するDashboardを追加。月間バジェットに対する今月の使用率と月末見込み、累計・今月の入力／出力トークン、キャッシュヒット率、推定費用、モデル別内訳、GitHub風の日別アクティビティ（実行数・トークン・費用）を表示する。既存の設定項目はGeneralタブへ移動。集計API `GET /api/usage/dashboard?tz=<IANAタイムゾーン>` を追加。

### Changed
- 新規チャットでは入力欄を画面中央に見出し「What should we work on?」とともに表示し、最初の実行が始まると従来どおり画面下に移るよう変更。
- 選択中のSkill・Web Search・Resources・Remote MCPを入力欄の中にテーマカラーのトークンとして表示するよう変更。ホバーで×に切り替わりクリックで外せるほか、空の入力欄でBackspaceを押すと最後のトークンを外す。横並びの領域や×ボタン用の余白は廃止。
- モデルとreasoning effortの選択を「GPT-6 Astra High」形式の1つのボタンに統合し、モデルファミリーのアイコンと電波強度風のメーターを廃止。パネルはテーマカラーのeffortスライダーを中心に、モデル名から一覧へ切り替え、既定のeffortへ戻すボタンを備える。
- Dashboard > Activityのマスを整数ピクセルで描画するよう変更し、マスごとの幅や間隔の不揃いを解消。色はテーマカラーの濃淡に変更。
- +メニューやSkill候補で選択中の項目をテーマカラーで表示するよう変更。
- コンテキスト使用率のリングを最初の応答前から0%で表示し、モデル選択の左に配置するよう変更。

## [0.2.4] - 2026-10-18

### Fixed
- checkpointの実行前後の除外情報を保持し、サイズ上限をまたいだ既存ファイルをUndoが削除・上書きする問題を防止。保存不完全なファイルを差分・Undoから除外して警告し、除外情報が不完全な旧実行はUndoを無効化。

## [0.2.3] - 2026-10-16

### Added
- サイドバーに会話の実行中・未読表示を追加し、折りたたんだProjectにも件数を表示。

### Changed
- 会話一覧の定期取得をSSEによる変更通知へ置換し、非表示タブから戻った際も現在の状態を取得。

### Fixed
- Undo・checkpoint作成・ストレージ整理を共通の排他制御で直列化し、必要なrefの登録と復元完了の記録まで保持。整理が復元データを削除してUndoが途中で失敗する競合を防止。
- 別ウィンドウで開始・完了した実行を開いている会話へ取り込み、既存表示と下書きを保持。取得失敗時は再試行し、会話切替後の遅延応答は破棄。

## [0.2.2] - 2026-10-15

### Removed
- 成果物の変更一覧・checkpoint・Undoでの `.gitignore` による除外と、Filesパネルのignore表示を撤廃。ignoreされたファイルも差分・Undoの対象になる。固定の除外ディレクトリ（`.venv`、`node_modules`、`.git` など）とシンボリックリンクの除外は維持。ファイル一覧はGitではなくディレクトリ走査で取得。

### Added
- ProjectごとのAudit画面と同梱Skill `project-audit` を追加。初回に監査のCharterを対話で作成し、READMEと実態、実装計画（論文形式の仕様書）とコード・ライブラリ、論文と結果、コードの誤りなどの不整合・根拠のない記述を `.chat-orchestrator/audit/` のMarkdown（Charter・指摘台帳・レポート）に記録する。画面は読み取り専用で、根拠の引用がファイルに実在するかを開くたびに機械的に照合して表示する。判断・修正・再検証はチャット入力欄への下書きで行い、送信するまで何も変更しない。DBは使わない。

### Changed
- 同梱Skillの表示名を英語に変更（「ギルド記録」から「Guild Journal」へ）。
- macOSでは作業フォルダのファイル変更イベント（FSEvents）を使い、checkpointで変更のあったファイルだけをstat・ハッシュするよう変更。最後の状態とGitのindexを保存して差分だけを更新し、5万ファイルで変更が少ない場合のcheckpointを約1.2秒から約0.3秒に短縮。イベントの完全性を確認できない場合は全ファイル走査に戻る。`WORKSPACE_WATCH=false` で無効化可能。
- バックエンド起動時に登録済み作業フォルダのcheckpointをバックグラウンドで作成し、初回実行のハッシュ待ちを解消。完了前に始めた実行は待機中の進捗を表示。
- 前回のcheckpoint以降に変更イベントがない場合は、ファイル一覧を取らずに前回の内容を再利用（5万ファイルで約0.1秒）。
- 古い実行のcheckpointを削除しても、最新の保存状態が参照するファイル内容は保持するよう変更。

### Fixed
- 実行中に `.gitignore` が変更された場合、Undoが実行前からあったファイルを削除することがある問題を修正（`.gitignore` の撤廃による）。
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
