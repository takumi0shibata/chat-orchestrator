# Audit Standards Compliance

## 概要
監査・会計・倫理・品質管理に関するローカル基準文書を検索し、main LLM が根拠付きで回答するための補助コンテキストを返す。

## 使う場面
- 監査基準、JICPA倫理規則、品質管理基準、日本基準、IFRS などに照らした質問
- 監査調書、独立性、監査証拠、重要性、後発事象、継続企業、会計処理の基準参照
- 「どの基準を見るべきか」も含めて根拠候補を探したい場合

## 文書の追加
1. `docs/sources/` 配下に Markdown 化した基準文書を置く。
2. `docs/manifest.json` の `documents` に文書メタデータを追加する。
3. 可能なら見出しや項番号を Markdown 見出しに残す。

公式基準本文は著作権・利用条件を確認してから配置する。初期同梱の `internal/audit-compliance-starter.md` は動作確認用の非公式サンプルであり、監査基準本文ではない。

## 出力
`SkillExecutionResult.llm_context` に、質問解釈、採用候補、抜粋、回答時の制約を返す。

## 実装メモ
- MVP はローカル Markdown コーパスの lexical search。
- manifest の `standard_family` / `jurisdiction` / `is_authoritative` を使って候補を絞る。
- embeddings や外部更新ジョブは後から `docs/index/` へ追加できる。
