# Local Responses Workspace

OpenAI / Azure OpenAI **Responses API** とローカルDockerサンドボックスで動く、個人向けのファイル作業チャットです。React + FastAPI + SQLite。

モデルが作業フォルダを探索し、必要なファイルを読み、Shellで分析・編集・検証します。指定したフォルダはコンテナの `/workspace` と共有され、**編集は元ファイルに即時反映**されます。200ファイルを最初から全文抽出してモデルへ送る構成ではありません。

## 起動

前提: macOS / Linux、Python 3.11以上、Node 20以上、uv、起動済みDocker DesktopまたはDocker Engine。標準ではCPU 4コア・メモリ8 GiBをコンテナに割り当てます。Windowsネイティブは対象外です。

```bash
cp .env.example .env
cp runtime.example.toml runtime.toml
# .env にAPIキー、runtime.toml に既存作業フォルダの絶対パスを設定
make setup-backend
make setup-frontend
make sandbox-build
```

2つのターミナルで起動します。

```bash
make dev-backend
make dev-frontend
```

[チャット](http://127.0.0.1:5173) / [API仕様](http://127.0.0.1:8000/docs)

バックエンドはホスト上の単一プロセスで起動してください。複数ワーカーは禁止です。同一データディレクトリを使う二重起動はロックで拒否します。通常起動ではreloadを使わず、実行中の再起動を避けます。設定変更後は再起動してください。

Docker Composeはイメージのビルド専用です (`docker compose --profile build build sandbox`)。バックエンドをDocker内で動かしたり、サンドボックスにDockerソケットを渡したりしません。

## 使い方

1. サイドバーから登録済み作業フォルダを選び「新しい作業」。
2. モデル・推論の深さを選び、必要なら `@skill-name` の入力候補または＋メニューから標準Skillsを選択し、モデル／データ、Remote MCP、Web検索を有効化。
3. ファイル名や完成形を自然言語で指示。添付ボタンのほか、中央のチャット領域へのドラッグ＆ドロップで複数ファイルを添付できます。
4. 現在工程と実行履歴で、実行コマンド・出力・所要時間・終了コードを確認。
5. ファイルパネルを更新して成果物を確認・ダウンロード。回答内の `[Word版](sandbox:/workspace/reviews/結果.docx)` のような成果物リンクからも取得できます。リンクは会話のファイルAPIへ変換し、領域外参照やシンボリックリンクは同APIで拒否します。

ブラウザを閉じても実行はバックエンドで続きます。同じ会話を開くとイベントを再取得します。「停止」はバックエンドの処理とコンテナを停止します。停止・失敗時も反映済みの変更は残り、自動ロールバックはしません。同じ作業フォルダへの実行は順番待ちになり、別フォルダなら並行実行できます。別会話への切り替えは実行を停止しません。

会話を削除しても元ファイルは削除されません。アプリ管理の添付も自動削除せず保持するため、不要になったものは停止中に `backend/data/agent/attachments/` から管理してください。

## 設定

`runtime.toml` はGit管理外です。[設定例](runtime.example.toml)を参照してください。

- `workspaces`: ID・表示名・絶対パス。相互に重なるディレクトリは禁止。APIキーやアプリ設定・状態を含むフォルダは登録しないでください。
- `skills`: 外部で用意した標準 `SKILL.md` を含むフォルダ。front matterの `name` / `description` を読み、Responsesのlocal shellへ渡します。読み取り専用の `/skills/<id>` に配置します。
- `resources`: 事前ダウンロードしたNLPモデルやデータ等。実行ごとに選択し、読み取り専用の `/resources/<id>` に配置します。
- `azure_models`: `model` に実際のモデルID、`deployment` にAzureのデプロイ名を記載。UIの名前とAPIへ渡すデプロイ名を分離しています。
- `mcp_servers`: HTTPS URL、明示的な `allowed_tools`、任意の `authorization_env`。トークンはバックエンドの環境変数としてexportします。MCP実行はAPIの承認要求をチャットで許可／拒否します。
- `project_doc_max_bytes`: ワークスペース直下から読み込むプロジェクト指示の最大バイト数。既定は32 KiBです。
- `project_doc_fallback_filenames`: `AGENTS.override.md`、`AGENTS.md` がない場合に確認する代替ファイル名。パスではなくファイル名だけを指定します。

各実行ではワークスペース直下の `AGENTS.override.md`、`AGENTS.md`、設定した代替名をこの順に確認し、最初の空でないファイルをモデルのプロジェクト指示として読み込みます。この探索順と既定上限は[Codexの公式仕様](https://developers.openai.com/codex/guides/agents-md)に合わせています。内容は実行ごとに読み直され、Activityに使用したファイル名が表示されます。サブフォルダ内の指示とホストの `~/.codex` は読み込みません。シンボリックリンクやUTF-8ではない指示ファイルは、安全のため実行エラーになります。

Remote MCPはプロバイダ側から接続されるため、ローカルの `localhost` URLは利用できません。このリポジトリにMCPサーバーや業務API本体は含みません。モデルAPI・MCP・Web検索の通信と、ネットワーク無効のローカルサンドボックスは別経路です。

ローカルShellではホスト型Skillsの `skill_reference` IDは使いません。標準Skills本体はユーザーが別途用意します。旧skill.yaml / skill.py のローダーや互換機能はありません。

OpenAIの新規会話の標準モデルは `gpt-6-sol`、新規データベースでのタイトル生成の標準モデルは `gpt-6-luna` です。`gpt-6-astra` と GPT-5.6 系も引き続き選べます。推論の標準は `medium`。GPT-6 Sol/LunaとGPT-5.6 Sol/Terraは `none/low/medium/high/xhigh/max`、GPT-6 AstraとGPT-5.6 Lunaは `low/medium/high/xhigh/max` に対応します。既存会話のモデル履歴と保存済みタイトル生成設定は変更しません。

Azure OpenAIでは `runtime.toml` の `azure_models` に登録したデプロイだけが会話・タイトル生成の選択肢に表示されます。GPT-6 Sol/LunaをAzureにデプロイしたら、`model = "gpt-6-sol"` または `model = "gpt-6-luna"` と実際の `deployment` 名を追加し、バックエンドを再起動してください。登録前はGPT-6を表示せず、Azureのタイトル生成に設定したGPT-5.6系デプロイは維持します。モデルの利用権限やAzureの対応状況は契約・デプロイに依存し、エラー時に別モデルへ自動切替しません。同じ会話内でのプロバイダ変更はできません。

## 実行環境と添付

[sandbox/](sandbox/)にアプリとは独立したPython依存ロックがあります。LibreOffice、Poppler、日本語フォント、Office/PDFライブラリ、NumPy、Pandas、Polars、SciPy、CPU版PyTorch、scikit-learn、Matplotlib、Seaborn、Transformers、Datasetsを含みます。初回ビルドは大きなダウンロードが発生します。

- `/workspace`: 元ファイルを直接読み書きする領域。
- `/input/<attachment-id>/<filename>`: アプリに添付した原本。読み取り専用。加工結果は `/workspace` に保存。
- `/skills/<id>`、`/resources/<id>`: 選択したSkills／モデル・データ。読み取り専用。
- `/tmp`: 実行終了で破棄される一時領域。

コンテナは非root・ネットワーク無効・root filesystem読み取り専用・追加capabilityなしで起動します。APIキーやホストの環境変数は渡しません。コマンドは非対話実行です。Pythonは `python ...` でコンテナに用意済みの `/opt/runtime/.venv` を使います。通常の `uv run` も `UV_PROJECT_ENVIRONMENT=/opt/runtime/.venv`、`UV_NO_SYNC=1`、`UV_FROZEN=1` によりこの環境を使い、ホストの `.venv` とロックファイルを同期しません（[uvの仕様](https://docs.astral.sh/uv/concepts/projects/sync/)）。この設定は意図的な上書きや直接のファイル削除を禁止するものではありません。ホストの環境をactivateしたり、依頼のない依存更新を行わないでください。作業先は `/workspace` であり、`cd` に続くコマンドは `&&` でつないでください。成果物の変更一覧では `.venv`、`venv`、`node_modules`、`.git`、`__pycache__`、`.pytest_cache`、`.ruff_cache` を探索から除外します。NLPモデルは事前配置し、Transformers等はofflineモードで動かします。追加ライブラリは `sandbox/pyproject.toml` を変更し、`uv lock --project sandbox` とイメージ再ビルドで導入します。macOS DockerからMetal/MPSは利用しません。

Doclingによる自動抽出はありません。通常の添付はShellで必要な部分を読みます。添付ボタンとチャット領域へのドラッグ＆ドロップは同じアップロード処理を使い、フォルダの再帰添付は行いません。PNG/JPEG/WebP/PDFはUIで「モデルに直接添付」を選べます（1ファイル20 MiB、合計40 MiBまで、通常アップロードは1ファイル50 MiB）。直接添付するとその内容をResponsesへ送ります。ローカルShellで読んだ内容・出力もモデルに返されるため、ローカル実行は完全オフラインではありません。

サンドボックスのルートfilesystemは隔離されていますが、登録した作業フォルダ内のファイルは編集・削除可能です。バックアップや版管理が必要な場合は別途用意してください。

## 実行上限・保存

`.env`で `COMMAND_TIMEOUT=600`、`RUN_TIMEOUT=3600`、`MAX_MODEL_ROUNDS=100`、`MAX_OUTPUT_CHARS=64000` 等を変更できます。出力はstdout/stderrごとに上限を設け、切り詰めを明示します。モデルの `timeout_ms` は秒に換算し、`min(COMMAND_TIMEOUT, max(COMMAND_TIMEOUT_MIN, モデル指定秒数))` を適用します。`COMMAND_TIMEOUT_MIN` は既定60秒、指定省略時は `COMMAND_TIMEOUT` を使います。上限を60秒未満に設定した場合も上限を優先します。短いモデル指定をそのまま使いたい場合は `COMMAND_TIMEOUT_MIN=1` としてください。実行履歴には適用上限を表示し、タイムアウトイベントにも値を保存します。実行全体の `RUN_TIMEOUT` は別途適用されます。コマンドのタイムアウトはプロセスを残さずコンテナごと停止し、その実行を失敗として終了します。

新しい保存先は `backend/data/agent/agent.db`。会話、実行、連番付きイベント、Responsesの完全な入出力（暗号化reasoningを含む）を保存します。旧 `backend/data/chat.db` は読み込み・移行・削除しません。

Responsesは `store=false` で完全な入出力を再送し、既定100,000トークンを超えると次の往復前に `/responses/compact` を使います。ユーザー指示はモデル呼び出し前に保存し、ツール呼び出しを含むラウンドは結果がすべて揃ってから文脈を保存します。失敗・停止・再起動時は、最後のチェックポイント以降のコマンド、結果・出力の抜粋、途中の応答、失敗理由を復旧履歴として保存します。未完了のツール呼び出しは復元・自動再実行せず、モデルには現在のファイル状態を確認して続行するよう伝えます。サーバー再起動時は中断実行を失敗扱いとし、そのコンテナを回収します。外部ファイルへの変更は維持されるため、再開時はファイルの現状を確認してください。

## API

- `GET /api/config`: プロバイダ・モデル・登録済み作業フォルダ／Skills／resources／MCP一覧。認証情報は返さない。
- `GET/POST /api/conversations`、`GET/DELETE /api/conversations/{id}`
- `GET/PATCH /api/settings`: タイトル生成モデルとテーマカラー。
- `GET /api/costs/monthly`: UTC月別の推定LLMトークン費用（USD）。
- `POST /api/attachments`: `conversation_id` と複数 `files` のmultipart。
- `GET /api/conversations/{id}/files?path=...`: フォルダ内のファイル一覧。
- `GET /api/conversations/{id}/download?path=...`: 許可領域の通常ファイルを取得。
- `POST /api/runs`、`GET /api/runs/{id}`
- `GET /api/runs/{id}/events?after=<seq>`: NDJSONイベント購読・再取得。
- `POST /api/runs/{id}/stop`
- `POST /api/runs/{id}/approvals`: `request_id`、`approve`。

ファイルAPIでは絶対パス・領域外参照・シンボリックリンクを拒否します。loopbackバインド、Host/Origin検証を行います。信頼された個人利用向けで、インターネット公開やマルチユーザー用の認証は実装していません。

## 検証

```bash
make test
make test-docker
# 設定済みAPIキーを使う有料の最小実APIテスト
cd backend && RUN_LIVE_TESTS=1 uv run pytest -m live -rs
```

Dockerテストは200ファイル・元ファイル編集・Office/PDF・CPU分析・日本語グラフ・隔離・タイムアウト／停止を検証します。実APIテストは一時フォルダ内だけを編集します。指定モデルが利用できないアカウントでは理由付きでskipします。Azureの実APIテストは実デプロイを設定した環境で別途行ってください。
