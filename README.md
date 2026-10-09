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
2. モデル・推論の深さを選び、モデル／データ、Remote MCP、Web検索を必要に応じて有効化。登録済みSkillsは依頼に応じて自動利用されます。明示的に適用する場合は `@skill-name` の入力候補または＋メニューから選択します。
3. ファイル名や完成形を自然言語で指示。添付ボタンのほか、中央のチャット領域へのドラッグ＆ドロップで複数ファイルを添付できます。
4. 現在工程と実行履歴で、実行コマンド・出力・所要時間・終了コードを確認。
5. ファイルパネルを更新して成果物を確認。Files のファイルやフォルダをチャット入力欄へドラッグすると、作業フォルダからの相対パスをカーソル位置へ挿入できます。回答内の `[Word版](sandbox:/workspace/reviews/結果.docx)` のような成果物リンクからも取得できます。リンクは会話のファイルAPIへ変換し、領域外参照やシンボリックリンクは同APIで拒否します。

成果物リンクは `file:///workspace/...`、`/workspace/...`、作業フォルダからの相対パスにも対応し、保存済み回答にも適用されます。ファイル名に空白を含む場合は `[結果](<sandbox:/workspace/my report.docx>)` のようにリンク先を `<...>` で囲むか、空白を `%20` にします。日本語・括弧を含むファイル名や、リンクラベル内のコード表記も使用できます。

チャット本文のLaTeX数式は `$…$`・`\(…\)`（行内）、`$$…$$`・`\[…\]`（独立数式）で表示します。独立数式は複数行も扱えます。コード内は数式に変換せず、不正な数式はエラー表示、入力途中の数式は文字列として残します。通常のドル記号は `\$` と書けます。KaTeXのCSS・フォントをアプリに同梱しているため、表示に外部CDNは不要です。LaTeX文書全体のPDFコンパイルには対応しません。

右上の端末アイコンから、チャットとFilesの下にホスト端末を開けます。左の履歴サイドバーの下には表示しません。上端をドラッグまたは矢印キーで高さを変え、＋で最大8つの独立した端末タブを開けます。各タブは作成時に選択されていた作業フォルダをカレントディレクトリとするホストOSのログインシェルです。パネルを閉じる、⌘Jで隠す、会話やProjectを切り替えるだけでは端末セッションを終了せず、同じページ内で再表示できます。Projectを切り替えると現在の端末workspaceとの不一致を警告し、「Open new terminal」で新しいProject用タブを追加できます。個別タブの×はその端末を終了します。ブラウザの再読み込み・終了、ページ離脱、バックエンド終了時は端末セッションも終了します。端末の入出力はアプリの会話履歴やSQLiteに保存しません（シェル自身の履歴設定は別です）。

ブラウザを閉じてもAIの実行はバックエンドで続きます。同じ会話を開くとイベントを再取得します。「停止」はバックエンドの処理とコンテナを停止します。停止・失敗時も反映済みの変更は残り、自動ロールバックはしません。終了した実行の回答の下に変更ファイル一覧と差分を表示し、「Undo」でその実行前の状態へ戻せます（後述のチェックポイント）。同じ作業フォルダへの実行は順番待ちになり、別フォルダなら並行実行できます。別会話への切り替えは実行を停止しません。

会話を削除しても元ファイルは削除されません。アプリ管理の添付も自動削除せず保持するため、不要になったものは停止中に `backend/data/agent/attachments/` から管理してください。

## 設定

`runtime.toml` はGit管理外です。[設定例](runtime.example.toml)を参照してください。

- `workspaces`: ID・表示名・絶対パス。相互に重なるディレクトリは禁止。APIキーやアプリ設定・状態を含むフォルダは登録しないでください。
- `skills`: 外部で用意した標準 `SKILL.md` を含むフォルダ。全登録Skillsのfront matterの `name` / `description` を毎回Responsesのlocal shellへ渡し、読み取り専用の `/skills/<id>` に配置します。モデルは依頼に関連するSkillsを判断し、必要な本文・参照ファイルだけを読んで適用します。
- `resources`: 事前ダウンロードしたNLPモデルやデータ等。実行ごとに選択し、読み取り専用の `/resources/<id>` に配置します。
- `azure_connections`: 接続先ID・表示名・Endpoint/APIキーの環境変数名を登録。実値は `.env` またはプロセス環境変数に保存します。
- `azure_models`: `model` にモデルID、`deployment` にAzureのデプロイ名、`connection_id` に接続先IDを記載。任意の `id` はアプリの選択用IDで、省略時はデプロイ名を使います。選択用IDは全Azureモデルで一意にしてください。
- `mcp_servers`: HTTPS URL、明示的な `allowed_tools`、任意の `authorization_env`。トークンはバックエンドの環境変数としてexportします。MCP実行はAPIの承認要求をチャットで許可／拒否します。
- `project_doc_max_bytes`: ワークスペース直下から読み込むプロジェクト指示の最大バイト数。既定は32 KiBです。
- `project_doc_fallback_filenames`: `AGENTS.override.md`、`AGENTS.md` がない場合に確認する代替ファイル名。パスではなくファイル名だけを指定します。

各実行ではワークスペース直下の `AGENTS.override.md`、`AGENTS.md`、設定した代替名をこの順に確認し、最初の空でないファイルをモデルのプロジェクト指示として読み込みます。この探索順と既定上限は[Codexの公式仕様](https://developers.openai.com/codex/guides/agents-md)に合わせています。内容は実行ごとに読み直され、Activityに使用したファイル名が表示されます。サブフォルダ内の指示とホストの `~/.codex` は読み込みません。シンボリックリンクやUTF-8ではない指示ファイルは、安全のため実行エラーになります。

Remote MCPはプロバイダ側から接続されるため、ローカルの `localhost` URLは利用できません。このリポジトリにMCPサーバーや業務API本体は含みません。モデルAPI・MCP・Web検索の通信と、ネットワーク無効のローカルサンドボックスは別経路です。

ローカルShellではホスト型Skillsの `skill_reference` IDは使いません。標準Skills本体はユーザーが別途用意します。旧skill.yaml / skill.py のローダーや互換機能はありません。

Skillsの自動利用は標準動作で、ON/OFF設定はありません。`@skill-name` または＋メニューの選択は明示的な適用指定です。チップや選択を解除すると明示指定を外し、自動判断に戻ります。自動候補からの除外ではありません。モデルには、適用するSkill名と目的を日本語の進捗で短く伝え、本文を読んでから実行するよう指示します。明示指定と自動利用の方針は各実行・履歴圧縮に渡します。ユーザーの依頼とsandboxの制約がSkillの指示に優先し、Skillから未選択のモデル／データ、Web検索、Remote MCPが有効になることはありません。

OpenAIの新規会話の標準モデルは `gpt-6-sol`、新規データベースでのタイトル生成の標準モデルは `gpt-6-luna` です。`gpt-6.1-sol`、`gpt-6-astra` と GPT-5.6 系も選べます。推論の標準は `medium`。GPT-6 Sol/LunaとGPT-5.6 Sol/Terraは `none/low/medium/high/xhigh/max`、GPT-6.1 Sol・GPT-6 Astra・GPT-5.6 Lunaは `low/medium/high/xhigh/max` に対応します。既存会話のモデル履歴と保存済みタイトル生成設定は変更しません。

Azure OpenAIでは `runtime.toml` の `azure_models` に登録し、接続先のEndpointとAPIキーが設定されたデプロイだけが会話・タイトル生成の選択肢に表示されます。GPT-6 Astra・Sol・Lunaは対応済みです。新しいAzureリソースを使う場合は、以下のように接続先を登録して各デプロイに紐づけます。

```toml
[[azure_connections]]
id = "gpt6"
label = "GPT-6用Azure"
endpoint_env = "AZURE_GPT6_ENDPOINT"
api_key_env = "AZURE_GPT6_API_KEY"

[[azure_models]]
id = "gpt6-astra"
model = "gpt-6-astra"
deployment = "実際のAstraデプロイ名"
connection_id = "gpt6"

[[azure_models]]
id = "gpt6-sol"
model = "gpt-6-sol"
deployment = "実際のSolデプロイ名"
connection_id = "gpt6"

[[azure_models]]
id = "gpt6-luna"
model = "gpt-6-luna"
deployment = "実際のLunaデプロイ名"
connection_id = "gpt6"
```

`.env` に `AZURE_GPT6_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/` と `AZURE_GPT6_API_KEY=...` を設定し、バックエンドを再起動してください。EndpointはリソースのルートURLまたは `/openai/v1/` までのHTTPS URLを指定します。モデルが別リソースにある場合は接続先をそれぞれ登録します。会話・タイトル生成・履歴圧縮は、選択したモデルの接続先と実際のデプロイ名を使用します。APIキーやEndpointの実値は画面/APIには返しません。

任意名の環境変数も、プロセス環境変数 → ルート `.env` → `backend/.env` の順で優先します。認証情報不足の接続先は、そのモデルだけを選択肢から外し、必要な環境変数名をログに表示します。重複ID、不明な接続先、不正なEndpointは起動時の設定エラーになります。

GPT-6.1 Solも、`model = "gpt-6.1-sol"` と実際のデプロイ名を `azure_models` に登録すれば利用できます。接続先の紐づけは他モデルと同じです。設定例は `runtime.example.toml` にあります。

`connection_id` を省略した既存モデルは、従来の `AZURE_OPENAI_ENDPOINT` と `AZURE_OPENAI_API_KEY` を使う `default` 接続先になります。`default` は予約IDです。既存会話を継続するには従来Endpointを維持し、新リソースは別の接続先として追加してください。旧DBのAzure会話は初回移行時に `default` と従来Endpointへ紐づけます。

最初のチャット実行で接続先を固定します。同じ接続先内ではモデルを変更できますが、接続先IDやEndpointが変わる場合は新規チャットが必要です。APIキーだけの更新は会話を継続できます。タイトル生成の接続先は会話とは独立し、有効な保存済み設定を維持します。モデルの利用権限やAzureの対応状況は契約・デプロイに依存し、エラー時に別モデルや接続先へ自動切替しません。同じ会話内でのプロバイダ変更はできません。

## 実行環境と添付

[sandbox/](sandbox/)にアプリとは独立したPython依存ロックがあります。Git、LibreOffice、Poppler、日本語フォント、Office/PDFライブラリ、NumPy、Pandas、Polars、SciPy、CPU版PyTorch、scikit-learn、Matplotlib、Seaborn、Transformers、Datasets、pytestを含みます。初回ビルドは大きなダウンロードが発生します。sandboxイメージの変更後は `make sandbox-build` で再ビルドし、バックエンドも再起動してください。

Gitは `/workspace` 内のローカルリポジトリで `status`、`diff`、`log`、`add`、`commit` などを利用できます。Shellはネットワーク無効のため、リモートへの `clone`、`fetch`、`pull`、`push` は利用できません。ホストのGit認証情報やグローバル設定は引き継ぎません。コミットにはリポジトリ内の作者設定、または `git -c user.name=... -c user.email=... commit ...` が必要です。

- `/workspace`: 元ファイルを直接読み書きする領域。
- `/input/<attachment-id>/<filename>`: アプリに添付した原本。読み取り専用。加工結果は `/workspace` に保存。
- `/skills/<id>`: 登録済みの全Skills。読み取り専用。
- `/resources/<id>`: 選択したモデル・データ。読み取り専用。
- `/tmp`: 実行終了で破棄される一時領域。

コンテナは非root・ネットワーク無効・root filesystem読み取り専用・追加capabilityなしで起動します。APIキーやホストの環境変数は渡しません。コマンドは非対話実行です。Pythonは `python ...` でコンテナに用意済みの `/opt/runtime/.venv` を使います。作業フォルダのPythonテストは `pytest -q` または `python -m pytest -q` で実行できます。通常の `uv run` も `UV_PROJECT_ENVIRONMENT=/opt/runtime/.venv`、`UV_NO_SYNC=1`、`UV_FROZEN=1` によりこの環境を使い、ホストの `.venv` とロックファイルを同期しません（[uvの仕様](https://docs.astral.sh/uv/concepts/projects/sync/)）。この設定は意図的な上書きや直接のファイル削除を禁止するものではありません。モデルにはホストの環境をactivate・同期しないよう指示します。作業先は `/workspace` であり、`cd` に続くコマンドは `&&` でつないでください。成果物の変更一覧では `.venv`、`venv`、`node_modules`、`.git`、`__pycache__`、`.pytest_cache`、`.ruff_cache` を探索から除外します。NLPモデルは事前配置し、Transformers等はofflineモードで動かします。macOS DockerからMetal/MPSは利用しません。

チャット作業中のサンドボックスのランタイム・ライブラリ・CLIは固定として扱います。モデルには、明示的に依頼された場合も `pip install`、`brew install`、インストール用の `curl` などによる導入・更新を行わないよう指示します。オフラインのwheel・キャッシュ、新しい仮想環境、外部ライブラリや実行用バイナリの持ち込みも解決手段にしません。ホストへのインストールはサンドボックスに反映されないため、ユーザーへの環境変更やイメージ再ビルドの依頼も行いません。必要な機能が不足していれば既存ツールで代替し、代替できなければ、できた部分と実行できない部分を説明します。既存ライブラリを使う作業用スクリプトの作成は可能です。

Shellからの外部取得や通信確認・再試行も行わないよう指示します。有効なWeb検索・Remote MCPは別の通信経路として利用できますが、Shellの通信や環境変更を可能にするものではなく、検索結果が自動で作業フォルダへ保存されるわけでもありません。この方針と、ホストOS・作業フォルダの対応・有効な外部ツール・選択済みリソースは、各実行のモデル指示に含まれ、履歴圧縮にも渡されます。

Doclingによる自動抽出はありません。通常の添付はShellで必要な部分を読みます。添付ボタンとチャット領域へのドラッグ＆ドロップは同じアップロード処理を使い、フォルダの再帰添付は行いません。PNG/JPEG/WebP/PDFはUIで「モデルに直接添付」を選べます（1ファイル20 MiB、合計40 MiBまで、通常アップロードは1ファイル50 MiB）。直接添付するとその内容をResponsesへ送ります。ローカルShellで読んだ内容・出力もモデルに返されるため、ローカル実行は完全オフラインではありません。

画面下のホスト端末は上記のAI用Dockerサンドボックスとは別で、ホストユーザーのファイル・ネットワーク権限を持ちます。端末にはバックエンドのAPIキーなどを環境変数として継承せず、HOME・PATH・ロケールなど端末に必要な環境だけを渡します。AI実行中も同じ作業フォルダで端末を操作できるため、同じファイルの同時編集には注意してください。

既存環境で扱える資料・データ・モデル重みなどの入力ファイルを外部取得する必要がある場合は、次の流れでユーザーへ引き継ぎます。

1. モデルがローカルの入力を確認し、通信に依存しない準備を進めたうえで、取得が必要な理由、ホストOS用のコマンド、共有作業フォルダ内の保存先と対応する `/workspace` パスを回答します。環境の導入や、不足機能をホストで実行するための依頼にはしません。
2. ユーザーが対象Projectのホスト端末でコマンドを実行し、チャットへ完了を返信します。失敗した場合は必要なエラー出力を返信してください。モデルはホスト端末を操作できず、端末出力も自動で読めません。認証情報をチャットに貼る必要はありません。
3. 次の実行でモデルが `/workspace` の実際のファイルを確認して続行します。依頼は通常の最終回答で行い、自動再開や専用の待機状態は設けません。ユーザーへの依頼で実行が終了した場合も、タスク自体は入力待ちです。

サンドボックスのルートfilesystemは隔離されていますが、登録した作業フォルダ内のファイルは編集・削除可能です。

## ファイル編集とチェックポイント

UTF-8テキストの編集にはResponses APIの `apply_patch` ツールを使います。パッチはサンドボックス内で適用するため、パスは `/workspace` 内に限られ、シンボリックリンク経由の書き込みや読み取り専用領域への書き込みは失敗としてモデルに返します。Office・PDF・画像などのバイナリ、生成物、一括置換はShellで扱います。Activityには編集ごとの差分を表示します。

各実行の開始前と終了時（停止・失敗を含む）に作業フォルダのチェックポイントを取り、`backend/data/agent/checkpoints/` のアプリ専用Gitリポジトリへ保存します。作業フォルダ自身の `.git`、`.gitignore`、`.gitattributes`（Git LFSなどのフィルタ）やホストのGit設定は使わず、ネストしたリポジトリや無視対象のファイルも記録します。成果物の変更一覧と同じ生成ディレクトリ（`.venv`、`node_modules`、`.git` など）、シンボリックリンク、`CHECKPOINT_MAX_FILE_BYTES`（既定50 MiB）を超えるファイルは対象外で、対象外ファイルの件数を変更パネルに表示します。ホストに `git` が必要です。`CHECKPOINTS=false` で無効にできます。

「Undo」はその実行で変わったファイルだけを実行前の内容に戻し、実行中に追加されたファイルと空になったディレクトリは削除します。実行後にユーザーや後続の実行が同じファイルを変更していた場合は一覧を示して確認を求め、承認すると上書きします。複数の実行を戻す場合は新しい実行から順に戻してください。同じ作業フォルダで実行中の間はUndoできません。同一内容のファイルは共有して保存しますが、大きな作業フォルダでは初回のチェックポイントにファイル全体の容量が必要です。完全なバックアップや版管理の代替ではありません。

## 実行上限・保存

`.env`で `COMMAND_TIMEOUT=600`、`RUN_TIMEOUT=3600`、`MAX_MODEL_ROUNDS=100`、`MAX_OUTPUT_CHARS=64000` 等を変更できます。出力はstdout/stderrごとに上限を設け、切り詰めを明示します。モデルの `timeout_ms` は秒に換算し、`min(COMMAND_TIMEOUT, max(COMMAND_TIMEOUT_MIN, モデル指定秒数))` を適用します。`COMMAND_TIMEOUT_MIN` は既定60秒、指定省略時は `COMMAND_TIMEOUT` を使います。上限を60秒未満に設定した場合も上限を優先します。短いモデル指定をそのまま使いたい場合は `COMMAND_TIMEOUT_MIN=1` としてください。実行履歴には適用上限を表示し、タイムアウトイベントにも値を保存します。実行全体の `RUN_TIMEOUT` は別途適用されます。コマンドのタイムアウトはプロセスを残さずコンテナごと停止し、その実行を失敗として終了します。

タイムアウト時はコマンドの上限（`Command time limit reached`）と実行全体の上限（`Run time limit reached`）を区別し、実際に適用した秒数を表示します。Docker起動などの個別処理のタイムアウトも全体上限の到達として扱いません。モデルにはテキスト検索で `rg` と対象パス・拡張子の絞り込みを使い、通常は `.venv`、`node_modules` などの生成ディレクトリを除外するよう指示します。`grep -R` はシンボリックリンクや仮想環境内も探索するため避け、必要な場合は `grep -rI --devices=skip` と `--exclude-dir` を使います。

新しい保存先は `backend/data/agent/agent.db`。会話、実行、連番付きイベント、Responsesの完全な入出力（暗号化reasoningを含む）を保存します。旧 `backend/data/chat.db` は読み込み・移行・削除しません。

Activityには推論サマリー（Thought）を表示します。`REASONING_SUMMARY` で `auto`（既定）・`concise`・`detailed`・`off` を選べます。推論の深さが `none` の場合は要求しません。サマリーの言語はモデル側で決まり、英語になることがあります。チャット応答には会話IDを `prompt_cache_key` として渡し、同じ会話の各ラウンドでプロンプトキャッシュが効きやすくしています。

モデルの出力上限は `MAX_MODEL_OUTPUT_TOKENS=32768`、タイトル生成は `MAX_TITLE_OUTPUT_TOKENS=1024` が既定値です。どちらも推論と本文を合計した1応答あたりのトークン上限で、`.env` で変更できます。チャット応答が上限に達した場合は実行を失敗として終了し、途中の回答を復旧履歴に保存します。中断応答でもAPIから使用量が返された場合は費用に計上します。`MAX_OUTPUT_CHARS` はShellのstdout/stderrの文字数上限で、モデルの出力トークン上限とは別です。

Responsesは `store=false` で完全な入出力を再送し、保存済みの応答の入力・出力合計が既定100,000トークン以上になると次のAPI呼び出し前に `/responses/compact` を使います。実行をまたぐ追加メッセージやサーバー再起動後も、保存済みの使用量から圧縮を判定します。ユーザー指示はモデル呼び出し前に保存し、ツール呼び出しを含むラウンドは結果がすべて揃ってから文脈を保存します。失敗・停止・再起動時は、最後のチェックポイント以降のコマンド、結果・出力の抜粋、途中の応答、失敗理由を復旧履歴として保存します。未完了のツール呼び出しは復元・自動再実行せず、モデルには現在のファイル状態を確認して続行するよう伝えます。サーバー再起動時は中断実行を失敗扱いとし、そのコンテナを回収します。外部ファイルへの変更は維持されるため、再開時はファイルの現状を確認してください。

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
- `WS /api/terminals/{workspace_id}`: 登録済み作業フォルダでホスト端末を起動。バイナリフレームでPTY入出力、JSONで初期サイズ・サイズ変更・終了状態をやり取りする。Host・Originを検証する。

ファイルAPIでは絶対パス・領域外参照・シンボリックリンクを拒否します。loopbackバインド、Host/Origin検証を行います。信頼された個人利用向けで、インターネット公開やマルチユーザー用の認証は実装していません。

## 検証

```bash
make test
make test-docker
# 設定済みAPIキーを使う有料の最小実APIテスト
cd backend && RUN_LIVE_TESTS=1 uv run pytest -m live -rs
```

DockerテストはGitのローカル操作・200ファイル・元ファイル編集・Office/PDF・CPU分析・日本語グラフ・隔離・タイムアウト／停止を検証します。実APIテストは一時フォルダ内だけを編集し、Skill名を含まない依頼での自動利用、明示指定、無関係なSkillを実行しないことを検証します。指定モデルが利用できないアカウントでは理由付きでskipします。Azureの実APIテストは実デプロイを設定した環境で別途行ってください。
