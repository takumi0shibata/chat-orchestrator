# Paper Reviewer (AI/ML/NLP)

## 概要
AI/ML/NLP 論文の草稿や本文抜粋をレビューし、判定サマリ、主要指摘、軽微指摘、LaTeX 修正案を返す補助 skill です。

## 使う場面
- Abstract や Introduction の書きぶりを見直したいとき
- ACL/ARR 中心の論文レビュー観点を素早く適用したいとき

## 必要設定
- 特になし

## 入力
- 1文から複数段落までの論文テキスト
- 可能なら対象セクション情報

## 出力 / Artifacts
- 補助コンテキストにレビュー手順、出力契約、修正方針、対象テキスト
- artifacts は返さない

## 実装メモ
- `skill.py` 単体で完結
- 出力の必須セクション順を prompt contract として埋め込んでいる
- rubric の補助資料は `docs/rubric_ai_ml_nlp.md`
