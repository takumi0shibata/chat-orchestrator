# EDINET Annual Report QA

## 概要
質問から企業・年度・参照セクションを推定し、EDINET API と XBRL 抽出を使って有価証券報告書ベースの補助コンテキストを作ります。

## 使う場面
- 企業の有報内容を比較・要約・照会したいとき
- セクション単位で根拠付きの補助コンテキストがほしいとき

## 必要設定
- `EDINET_API_KEY`
- `backend/skills/edinet_report_qa/docs/EdinetcodeDlInfo.csv`
- 任意: `EDINET_CACHE_DIR`, `EDINET_CACHE_TTL_HOURS`, `EDINET_LOOKBACK_DAYS`

## 入力
- 企業名、証券コード、EDINET コード、年度、セクション名を含む自然文

## 出力 / Artifacts
- 補助コンテキストに解釈結果、曖昧性、抽出根拠、本文抜粋
- artifacts は返さない

## 実装メモ
- `intent_parser.py` が意図解析
- `documents_repository.py` が EDINET 取得とキャッシュ
- `xbrl_extractor.py` が XBRL 本文抽出
