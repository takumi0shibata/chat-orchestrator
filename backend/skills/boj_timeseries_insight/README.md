# BOJ Timeseries Insight

## 概要
日銀の時系列統計 API から代表系列を取得し、分析サマリと数値系列を補助コンテキストとして返します。

## 使う場面
- 金融・マクロ系列を自然文から素早く確認したいとき
- 数値をチャット上で折れ線グラフとして見たいとき

## 必要設定
- API キー不要
- 任意: `BOJ_STAT_CACHE_DIR`, `BOJ_STAT_CACHE_TTL_HOURS`

## 入力
- 系列名、期間、頻度、再取得要否を含む自然文

## 出力 / Artifacts
- 補助コンテキストに系列解釈、分析サマリ、生データ抜粋、品質メモ
- 数値系列があれば `line_chart` artifact

## 実装メモ
- `series_catalog.py` が系列プリセットと解決ロジックを持つ
- `client.py` が BOJ API クライアント
- `cache.py` がローカルキャッシュを担当
