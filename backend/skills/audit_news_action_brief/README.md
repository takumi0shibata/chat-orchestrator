# Audit News Action Brief

## 概要
監査クライアントのニュースを `自社 / 他社 / マクロ` の3視点で探索し、action-oriented な候補を `card_list` artifacts と補助コンテキストで返します。

## 使う場面
- 監査クライアントの直近ニュースを短時間で把握したいとき
- Web 検索付き Responses API モデルで外部情報を使いたいとき

## 必要設定
- OpenAI または Azure OpenAI の Responses API モデル
- 推奨モデル: `gpt-5.4-2026-03-05`

## 入力
- クライアント名、業種、競合、注目論点、参照期間を含む自然文

## 出力 / Artifacts
- `message.artifacts` に `card_list`
- 補助コンテキストに探索方針、抽出理由、注意点
- generic feedback action を各カードへ付与

## 実装メモ
- `skill.py` が実装本体
- `audit_news_llm_client.py` が Responses API 呼び出しを担当
- Web 検索が前提のため、非 Responses モデルでは説明メッセージを返す
