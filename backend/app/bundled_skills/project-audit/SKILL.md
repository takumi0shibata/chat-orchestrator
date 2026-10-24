---
name: project-audit
description: Audit project inconsistencies, contradictions, and unsupported claims (hallucinations), and record the charter, findings, and reports in .chat-orchestrator/audit/. Use when asked to audit a project, create or update its charter, record decisions on findings, or fix and recheck findings with an agreed decision. Do not use for ordinary code reviews or work that does not request an audit.
---

# Project Audit

## Record language

Write new charter prose, finding titles, explanations, decisions, and reports in the user's requested language, or their request's language when unspecified. Preserve existing record language, user wording, and verbatim evidence quotes unless explicitly asked to translate. Translate template placeholders into supported facts in that language; never translate quoted evidence.

For English records, use English section headings and verdicts `contradiction`, `unsupported`, or `suspected`. Japanese records may use `矛盾`, `根拠なし`, or `疑い`. These verdicts are display text, not fixed machine values. Keep field keys (`status`, `severity`, `relation`, `verdict`, etc.), status/severity identifiers, finding IDs, paths, and date formats unchanged. Reports must use the recognized `Not checked` heading (or `確認しなかったこと` for Japanese) for omitted checks; use `Not checked` for other languages with prose in the user's language. Preserve recognized headings in existing files.


作業対象Projectの `.chat-orchestrator/audit/` を管理する。OrchestratorのサンドボックスではProjectのルートは `/workspace`。記録は元ファイルに保存され、アプリのサイドバーでProjectのAuditを開くと読み取り専用で表示される。

監査はユーザーとの協業として行う。AIは候補と根拠を示し、どちらが正しいか・直すかどうかはユーザーが決める。

- 根拠のない指摘をしない。根拠の引用は原文から一字一句そのまま取る。
- 確認しなかった範囲・確認できなかった範囲を必ず記録する。「問題なし」と「確認していない」を混同させない。
- ユーザーの判断を推測で補わない。判断が書かれていない指摘は修正しない。

## 依頼の種類と変更してよい範囲

| 依頼 | 行うこと | 変更してよいファイル |
| --- | --- | --- |
| Charterの作成・更新 | 棚卸しし、草案をチャットで提示し、合意後に保存する | `charter.md` |
| 監査 | Charterに沿って確認し、指摘とレポートを記録する | `findings.md`、`reports/` |
| 判断の記録 | ユーザーの判断を指摘とCharterに記録する | `findings.md`、`charter.md` の「既知の例外・判断」 |
| 修正 | 判断済みの指摘を判断どおりに直し、再検証する | 修正に必要なProjectのファイル、`findings.md` |
| 再検証 | 未解決の指摘の根拠と問題が残っているかを確認し直す | `findings.md`、`reports/` |

- 修正を依頼されたRun以外では、`.chat-orchestrator/audit/` の外のファイルを作成・変更・削除しない。検証用のスクリプト・出力は `/tmp` に置く。
- 監査・判断の記録・再検証では、指摘を見つけても直さない。修正が必要なら、どの指摘を直すか判断を求める。
- 依頼がどれに当たるか曖昧なときは、ファイルを変更せずに確認する。

## Charterの作成

`charter.md` がない状態で監査を依頼されたら、監査を始めず、先にCharterを作ることを伝えて次の手順に進む。

1. Projectを棚卸しする。ファイル一覧（`.git`、`.venv`、`node_modules` などは除外）、README・docs、AIに書かせた実装計画（論文形式の仕様書）、論文・原稿、コード、テスト、設定、データ、結果、`.chat-orchestrator/` のGuild記録を把握する。大きなデータ・モデル重みは中身を全部読まず、形式と規模だけ確認する。
2. 草案を**チャットの回答として**提示する。この時点ではファイルを書かない。役割を推定した箇所は「推定」と明記し、確認したい点を5つ程度までの質問にする。
3. ユーザーが内容に合意したら（「これで保存して」など）`charter.md` を保存する。保存したRunでは監査を始めず、次の依頼で監査できると伝える。
4. 最初の監査は「確認する関係」を1〜2項目に絞ることを提案する。誤検知の傾向を見てから広げる。

```markdown
# Audit Charter

## Purpose
State the project goal, such as submitting a paper with reproducible code.

## Artifact map
| Path | Type | Role |
| --- | --- | --- |
| docs/specs/ | Implementation plan | Specification followed by the implementation |
| src/ | Code | Implementation |
| results/final/ | Results | Source of truth for numbers |
| paper/ | Paper | Downstream of results |
| README.md | Documentation | Downstream of implementation |

## Relationships to check
- [x] README ↔ implementation
- [x] Plan claims ↔ code, data, and libraries
- [ ] Plan ↔ implementation
- [ ] Paper ↔ results
- [ ] Code errors

## Out of scope
data/raw/, checkpoints/

## Allowed checks
- `pytest -q tests/unit`

## Known exceptions and decisions
```

役割は「正（ほかを合わせる基準）」「下流（正に合わせる）」「仕様（実装が従う）」「実態」「草稿（矛盾してもよい）」などで書く。正が決まっていない組み合わせの矛盾は、どちらが正しいかをユーザーに選んでもらう。Charterの更新を依頼された場合も、変更案をチャットで示して合意を得てから保存する。

## 監査の観点

Charterの「確認する関係」でチェックされた項目だけを確認する。判定は次の3つとする。

| 判定 | 意味 |
| --- | --- |
| 矛盾 | 根拠同士がはっきり食い違う、または実行・計算で誤りが示せる |
| 根拠なし | 事実として書かれているのに、Project内・ライブラリ・実行結果のどこにも出所がない |
| 疑い | 誤りの可能性が高いが、再現・確定できていない |

裏付けが取れた記述や確認しなかった記述は指摘にせず、レポートの確認範囲に書く。

| 関係 | 確認すること | 確認方法 |
| --- | --- | --- |
| README ↔ 実態 | 記載されたコマンド、Makefileのターゲット、CLIの引数、パス、環境変数、依存関係、機能が実在し、記載どおりか。実装済みなのに書かれていない主要な機能・手順 | `make -n`、`--help`、ファイルの存在確認、`pyproject.toml` などとの照合 |
| 実装計画の主張 ↔ コード・データ | 「既存の〜は…する」といった現状の記述、言及された関数・ファイル・設定キーの実在、本文中の数値・データ統計の出所 | コードを読む、`grep`、集計スクリプトの実行 |
| 実装計画 ↔ ライブラリ | 言及されたライブラリ・API・引数・バージョン固有の機能が実在するか | サンドボックスで `import`、`inspect.signature`、`help` を使って確認する |
| 実装計画の内部整合 | 節の間での記法・ハイパーパラメータ・評価指標・データ分割の食い違い、定義前の記号、式の次元、主張と根拠の飛躍 | 文書を読む。式や数値は計算し直す |
| 実装計画 ↔ 実装 | レビュー済みの仕様と、実装されたコードの食い違い | 仕様の各項目をコードに対応づける |
| 論文 ↔ 結果 | 表・本文の数値、データ統計、設定と、結果ファイル・ログ・config | スクリプトで突き合わせる |
| コードの誤り | 既存テストの失敗。評価・前処理によくある誤り（split前に全データでfit、testのshuffle、seed未固定、平均の取り方、ラベル対応のずれ、評価時の `eval()` / `no_grad` 漏れ、読まれていない設定） | `pytest`、最小の再現スクリプト |
| Guild記録 ↔ 実態 | `overview.md`・`tasks.md`・日誌と実際の状態 | ファイルを読む |

- 文献の引用は、Project内の `.bib` などにキーがあるかだけを確認できる。文献の実在はWeb検索が有効な場合だけ確認し、それ以外は確認しなかったことにレポートで明記する。引用先の内容を正しく要約しているかは確認しない。
- AIが書いた実装計画では、もっともらしい既存実装の説明、存在しないAPI・引数、出所のない数値が典型的な誤りである。仕様にある記述を1つずつ根拠と照合する。
- コードの誤りを「矛盾」とするには、`/tmp` に最小の再現スクリプトを書いて実行し、誤りを示す。再現できなければ「疑い」とし、深刻度を上げすぎない。
- 長時間かかる処理、GPUや外部通信が必要な処理、Charterの「実行してよい確認」にない重い処理は実行せず、確認しなかったことに記録する。パッケージのインストールや外部取得はしない。

## 監査の進め方

1. `charter.md`、`findings.md`、`reports/` の最新レポートを読む。Charterの「既知の例外・判断」に該当するもの、`intended` / `dismissed` の指摘は再提起しない。根拠が変わった場合だけ、新しい根拠を示して新しい指摘にする。
2. 依頼された範囲（指定がなければCharterでチェックされた関係すべて）を確認する。決定論的に確かめられるものはスクリプトを実行する。
3. 既存の指摘と同じ問題は新しいIDにせず「継続」とし、行番号がずれていれば根拠を更新する。既存の指摘の問題がなくなっていれば `fixed` にし、`resolved` に日付と経緯を書く。
4. 迷うものは指摘にせず、レポートの「気になった点」に書く。指摘の数より、1件ごとの確かさを優先する。
5. `findings.md` を更新し、`reports/` にレポートを作り、チャットで要約する。要約には新規・継続・解消の件数、重大なもの、ユーザーの判断が必要なもの、確認しなかったことを含める。

## findings.md の形式

```markdown
# Audit findings

## F-003 The README command `make train` does not exist
- status: open
- severity: major
- relation: README ↔ implementation
- verdict: contradiction
- verified: executed `make -n train` → "No rule to make target 'train'"
- evidence:
  - README.md:42 `make train`
  - Makefile — no train target; the existing target is train-bert
- options: Correct README to `make train-bert` / add `train` to Makefile
- found: 2026-10-14-01
- decision:
```

- 1件を `## F-番号 タイトル` で始める。番号は3桁以上の連番で、削除・再利用しない。新しい指摘は末尾に追加する。解消・却下した指摘も消さない。
- 各項目は `- キー: 値` の1行で書く。`evidence` だけは次の行から2スペース字下げした箇条書きにする。
- `status`: `open`（未判断）、`decided`（方針が決まり未修正）、`fixed`（修正または再検証で解消を確認）、`intended`（意図どおり）、`dismissed`（誤検知）。
- `severity`: `blocker`（論文・報告の主張や結果の正しさに影響する、または実行できない）、`major`（誤解・再現の失敗を招く）、`minor`（表記の揺れなど）。
- `relation`: 監査の観点の表の関係名。`verdict`: use `contradiction` / `unsupported` / `suspected` for English records, or `矛盾` / `根拠なし` / `疑い` for Japanese records.
- `verified`: 実行した場合は `executed` に続けてコマンドと結果の要点、読んで確認した場合は `read` に続けて確認内容を書く。
- `evidence`: 1行に1件、`パス:行` または `パス:開始行-終了行` の後に、そのファイルに実在する原文をバッククォートで1つだけ引用する。パスはProjectルートからの相対パスで、`/workspace/` は付けない。引用は200文字以内の1行内の文字列とし、引用の中にバッククォートを含めない。引用の後に補足を書いてよい。「〜がない」という不在の根拠は `パス — 説明` の形で書く。`—` 以降は照合しない補足として扱われる。矛盾なら食い違う根拠を2件以上挙げる。
- `options`: ユーザーが選べる解決案を ` / ` で区切って書く。どちらが正しいか分からない矛盾では、それぞれを正とする案を並べる。
- `found`: 見つけた監査レポートのID。`decision`: ユーザーの判断。判断前は空のままにする。
- 解消したら `- resolved: 日付 経緯と変更したファイル` を追加する。

Auditの画面は引用がファイルに実在するかを機械的に照合して表示する。引用を言い換えたり要約したりすると「根拠が見つからない」と表示される。

## reports/ の形式

監査・再検証の1回ごとに `reports/YYYY-MM-DD-NN.md` を作る（例：`2026-10-14-01.md`）。日付は実行した日、同日の2回目以降は未使用の番号にする。過去のレポートは書き換えない。

```markdown
# Audit 2026-10-14-01

## Scope
README ↔ implementation / Plan claims ↔ code and data

## Results
- New: F-004, F-005
- Continuing: F-001
- Resolved: F-002

## Checked
- Checked all README commands with `make -n`
- Checked 32 claims in docs/specs/retrieval.md (29 supported, 3 findings)

## Not checked
- paper/ (excluded by the charter)
- GPU tests (tests/gpu/)
- Existence of cited literature (web search unavailable)

## Open questions
- Unconfirmed concerns that were not recorded as findings
```

「確認しなかったこと」は画面の上部に表示される。何も省略していない場合も、その旨を1行で書く。

## 判断の記録

- ユーザーの言葉どおりに `decision` を書き、`status` を更新する。選択肢を選んだだけなら `decided`、意図どおりなら `intended`、誤検知なら `dismissed`。
- `intended` にした指摘は、`charter.md` の「既知の例外・判断」に `- YYYY-MM-DD F-003: 理由` の形で追記する。誤検知の理由が今後の監査に役立つ場合も同じ節に追記する。
- 理由が示されていない `intended` / `dismissed` は、理由を尋ねてから記録する。

## 修正

- `status: decided` の指摘、または同じ依頼の中でユーザーが判断を示した指摘だけを修正する。修正は判断に沿った最小限の変更にする。
- 修正後に `verified` と同じ方法で確認し直す。解消していれば `fixed` にして `resolved` を書く。解消しなければ `decided` のまま、残った問題を伝える。
- 回答で、変更したファイルと指摘ごとの結果を伝える。

## 保存前の確認

- UTF-8の通常ファイルを使い、シンボリックリンクは編集しない。`findings.md` は256 KiB以内、`charter.md` と各レポートは64 KiB以内、指摘は500件以内に収める。超えそうな場合は勝手に削除せず、整理を提案する。
- 保存後に `findings.md` を読み直し、すべての引用がファイルに実在するか（`grep -F` など）、IDが重複していないか、無関係な指摘を失っていないかを確認する。
- 完了時に、変更したファイルと主な内容を伝え、サイドバーのProjectからAuditを開くと確認できると案内する。ShellからアプリのAPIへ接続したり、画面の更新が済んだと報告したりしない。
