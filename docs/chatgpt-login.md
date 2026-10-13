# ChatGPT接続

OpenAI APIキー、Azure OpenAIとは別に `chatgpt` プロバイダを追加しています。個人がローカルで使うSign in with ChatGPTの動的登録フローです。APIキー・Azureの既存設定、モデル接続、ネイティブShell・Apply Patch、履歴圧縮は維持しています。

## 使い方

1. 通常どおりバックエンドとフロントエンドを起動します。追加依存関係は `make setup-backend` で同期してください。
2. Settings → ChatGPT connection → Continue with ChatGPT を押します。ポップアップを許可し、ブラウザで本人がログインとChatGPT利用枠の許可を完了します。対象アカウント・ワークスペースの利用資格やポリシーに依存します。
3. 接続ページのManage usageから利用枠を管理できます。再接続・切断もこのページで行います。設定一覧ではNew chat defaults、Monthly budgetと同じ階層です。応答・compactの確認ボタンとデバッグ用APIは製品から削除しています。
4. 新規チャットの＋メニュー → ProviderでChatGPTを選択します。既存会話でプロバイダは変更できません。

タイトル生成プロバイダも独立して選べます。ChatGPT会話でOpenAI APIキー・Azureのタイトルモデルを選択した場合、タイトル生成はその接続のAPI課金です。ChatGPTのトークン利用はAPI単価による月額推計に加算しません。利用枠の管理・許可の取り消しはChatGPT側の設定から行います。Disconnect ChatGPTはこのアプリのローカルトークンを削除します。

## 認証と保管

- インストールを表す `ext_agent_host_id` を初回生成し、同じホストでは再利用します。
- 初回は `dynamic_agent_client` で登録を開始し、発行されたclient IDでコードを交換します。client secretやPlatform APIキーは不要です。
- OAuthのPKCE/S256、state、nonce、署名・issuer・audience・期限・subjectを検証します。コールバックは短時間だけ起動する `127.0.0.1` の専用HTTPリスナーです。OAuthコードを通常のAPIアクセスログへ記録しません。
- 資格情報は `DATA_DIR/chatgpt-auth.json`（標準: `backend/data/agent/chatgpt-auth.json`）に0600で原子的に保存します。access/refresh/IDトークンをReactの接続状態API、Agentの入力、Dockerへ渡しません。認証ファイルはGit管理外のアプリ状態ディレクトリにあります。
- 更新はバックエンドで直列化し、refresh tokenのローテーションを保存します。一時的な通信失敗で資格情報を消去せず、失効が確認された場合は再ログインを求めます。
- この版は1つのChatGPT登録・アカウントを扱います。再ログインは同じ検証済みsubject/client IDに限ります。
- 実行中の認証変更は拒否します。認証・利用枠エラーでAPIキー課金に自動切替しません。

## Responsesとツール

ChatGPT接続も公開エンドポイント `https://api.openai.com/v1/responses` と公式Python SDKを使います。`store=false` / `stream=true` とし、毎回必要な履歴を入力配列で送ります。非対応の `max_output_tokens` と `prompt_cache_key` はこの接続だけで外します。最終 `response.completed` が届くまでは成功扱いにしません。

実APIでは終端のresponseの `output` が空でも、その前に `response.output_item.done` が届くケースを確認しました。ChatGPT接続のストリームアダプタが完了アイテムを順序どおり集約し、本文・ツール呼び出しを履歴へ保存します。

ChatGPT接続のShellは名前空間内のfunction toolとして公開し、既存のDocker実行処理を共用します。コマンド出力イベント、タイムアウト、停止、チェックポイントを維持します。編集はShellで行い、この接続ではネイティブApply Patchを広告しません。Skills・添付・選択済みResourcesのマウントは既存処理を使います。view_imageも同じ名前空間に公開しますが、この版の実アカウント検証はShellのみです。

ホスト型Remote MCPはこの経路で非対応のため、ChatGPT接続のUIでは選択肢を出さず、APIでも指定を拒否します。Web検索は従来の選択方式を維持しますが、モデル・アカウントポリシーに依存し、今回の実API検証には含めません。

## 2026-10-13の検証結果

本人が確認用の一時環境でログインし、ChatGPT利用枠を許可した後、`gpt-6-luna` で確認しました。

| 検証 | 結果 |
|---|---|
| OAuthログイン・再起動後の資格情報読込 | 成功 |
| アカウント別モデル一覧 | 成功 |
| 最小Responsesリクエスト | 成功。本文 `Hello, world!` を確認 |
| 既存のネイティブ `type=shell` | HTTP 400、`Unsupported tool type: shell` |
| function toolから既存Docker Shellを実行 | 成功。`printf shell-ok` の終了コード0、出力とコマンド履歴を確認 |
| ネイティブ `/v1/responses/compact` | HTTP 401、`hardened_oauth_rule_missing` |
| 公式サーバー側compactionと会話継続 | 成功。圧縮後の再起動・Shell実行・次ターンでの記憶保持を確認 |

ChatGPT接続では独立compactを呼びません。通常のResponsesに `context_management=[{"type":"compaction","compact_threshold": COMPACT_TOKEN_THRESHOLD}]` を指定し、公式サーバー側compactionを利用します。閾値は従来と共通で既定258,000トークンです。完了した応答内の最新compactionアイテムより前の履歴を除き、暗号化アイテムとそれ以降の履歴を保存します。圧縮の直前に発行されたShell呼び出しは、実行結果と対応する形で保持します。途中失敗時は未確認の圧縮結果で履歴を置き換えません。人間向け要約による代替圧縮はありません。

実アカウントで、圧縮後にランタイムを再起動し、覚えた値をShellでファイルに書き込み・読み戻し、次のターンでもその値を回答できることを検証しました。テスト用閾値は2048です。APIキー・Azure接続は従来の独立 `/responses/compact` を維持します。

応答全体のトークン使用量は、圧縮して保存した文脈だけのサイズではないため、圧縮直後の使用量表示は未計測になります。次の応答の実測値で更新します。

確認用サーバーは `/private/tmp/chat-orchestrator-chatgpt-dev/` をデータ・作業フォルダに使い、既存の会話データは使っていません。通常のアプリを標準データディレクトリで起動した場合は、そのアプリのSettingsから改めて接続してください。

## 自動テスト

認証のstate/nonce/署名/issuer/audience/期限検証、再利用拒否、0600保存、更新の直列化とローテーション、失効と一時エラーの区別、利用枠許可の欠落、ストリーム完了とアイテム集約、Shell結果と履歴の対応、複数のサーバー側compaction境界と会話継続を検証します。

```sh
backend/.venv/bin/python -m pytest backend/tests -m 'not live and not docker' -q
cd frontend
npm test
npm run build
```

## 公式資料

- [Sign in with ChatGPT Quickstart](https://developers.openai.com/siwc/quickstart)
- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference)
- [公式Compaction仕様](https://developers.openai.com/api/docs/guides/compaction)

## 実アカウント統合テスト

バックエンドを停止し、既存Dockerイメージと本人が許可したChatGPT資格情報を使います。既存データと作業フォルダは変更せず、pytestの一時領域で検証します。トークン更新が競合しないよう、資格情報を使うアプリはテスト中に停止してください。

```sh
RUN_CHATGPT_LIVE_TESTS=1 CHATGPT_AUTH_FILE=/absolute/path/to/chatgpt-auth.json \
  backend/.venv/bin/python -m pytest backend/tests/test_chatgpt_live.py -q
```
