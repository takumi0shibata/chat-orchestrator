# Project Audit

Projectの不整合・矛盾・根拠のない記述（ハルシネーション）を、ユーザーと協業して洗い出す機能です。監査は同梱Skill [project-audit](../backend/app/bundled_skills/project-audit/SKILL.md)が行い、結果はProject内のMarkdownに保存します。画面はそれを読み取り専用で表示します。

- 監査・判断・修正はすべて通常のチャットのRunとして行います。変更されたファイルは回答の下の変更一覧と差分で確認でき、Undoで戻せます。
- Audit画面のボタンはチャット入力欄に依頼文を下書きするだけです。送信するまで何も変わりません。
- アプリのSQLiteには何も保存しません。Skillと `.chat-orchestrator/audit/` を消せば元の状態に戻ります。

## 使い方

1. サイドバーのProject名にカーソルを合わせ、盾のアイコン（Audit）を開きます。
2. 初回は「Create charter in a new chat」。AIがProjectを棚卸ししてCharterの草案をチャットで提示します。内容を直して合意すると `charter.md` を保存します。最初は確認する関係を1〜2項目に絞ることを勧めます。
3. 「Run audit」で新しいチャットに監査の依頼を下書きします。送信すると、AIがCharterに沿って確認し、`findings.md` と `reports/` を更新します。
4. Audit画面で指摘を開き、根拠と照合結果を確認して判断します。選択肢、「Write my own decision」「Intended…」「False positive…」はチャットの下書きに追記されるだけなので、複数の指摘をまとめて判断してから送信できます。「Intended…」「False positive…」には理由を書き足してください。
5. 判断済み（Decided）の指摘は「Request fix」で修正を依頼します。AIは判断どおりに直し、再検証して結果を記録します。
6. 「Re-check open findings」で未解決の指摘を再検証します。画面の内容は開くたびにファイルから読み直します。手動で更新したい場合は「Reload」を押します。

判断の下書きは、そのProjectで最後に下書きした会話に追記します。まだない場合は、表示中の会話がそのProjectのものならそこに、それ以外は新しい会話に追記します。「Run audit」「Create charter」「Re-check open findings」は常に新しい会話を作ります。いずれも `Project Audit` Skillを選択した状態にします。

`@project-audit` または＋メニューの「Project Audit」で、通常のチャットから明示的に指定することもできます。

## 記録

```text
プロジェクト/
└── .chat-orchestrator/
    └── audit/
        ├── charter.md          # 監査の憲章。目的・成果物の役割・確認する関係・対象外・既知の例外
        ├── findings.md         # 指摘の台帳（F-001〜）
        └── reports/
            └── 2026-10-14-01.md  # 監査1回ごとの範囲・確認したこと・確認しなかったこと
```

形式の詳細はSkill本体に記載しています。画面が読み取るのは次の要素です。

- `findings.md`: `## F-番号 タイトル` から次の見出しまでを1件とし、`- status:`、`- severity:`、`- relation:`、`- verdict:`、`- verified:`、`- options:`（` / ` 区切り）、`- found:`、`- decision:`、`- resolved:` と、`- evidence:` の下の字下げした箇条書きを読みます。コードフェンス内は読みません。
- `status` は `open` / `decided` / `fixed` / `intended` / `dismissed`。未記入は `open`、不明な値は警告を出して `open` として表示します。`severity` は `blocker` / `major` / `minor`。
- `reports/*.md`: ファイル名の降順で30件まで。最初の見出しをタイトルとし、「確認しなかったこと」（`確認できなかったこと` / `未確認` / `Not checked` も可）の節の箇条書きを、最新のレポートの分だけ画面上部に表示します。
- 上限は `charter.md` と各レポートが64 KiB、`findings.md` が256 KiB、指摘が500件、1件あたりの根拠が20件です。読めないファイル（上限超過、UTF-8以外、シンボリックリンクなど）があっても、ほかの記録は表示します。

## 根拠の照合

画面を開くたびに、バックエンドが各根拠 `パス:行 \`引用\`` の引用文が実際にファイルにあるかを機械的に確認します（モデルは使いません）。空白の違いは無視します。

| 表示 | 意味 |
| --- | --- |
| Quote found | 指定行の前後2行以内に引用がある |
| Quote found elsewhere | 指定行の近くにはないが、同じファイルの別の行にある（行番号を表示） |
| Quote not found | ファイルに引用がない。言い換え、捏造、または修正済みの可能性 |
| File exists (not a quote) | `パス — 説明` 形式の不在の根拠など、照合する引用がない |
| File not found / Invalid path / Line out of range / Unreadable file | ファイルがない、Project外のパス、行番号がファイルより大きい、シンボリックリンクやUTF-8以外のファイル |

照合はProject内の通常ファイルだけを対象にし、シンボリックリンクはたどりません。1回の表示で読むファイルは200件、1ファイル4 MiBまでです。照合で確かめられるのは「引用がそこにあるか」だけで、指摘の結論の正しさまでは保証しません。

## 安全のための約束

- 監査・判断の記録・再検証のRunでは、Skillの指示により `.chat-orchestrator/audit/` 以外を変更しません。これは指示であって強制ではないので、回答の下の変更一覧に監査記録以外のファイルが含まれていないかを確認してください。含まれていればUndoで戻せます。
- 修正は、判断済みの指摘か、同じ依頼でユーザーが判断を示した指摘だけを対象にします。
- サンドボックスはネットワークなしです。文献の実在はWeb検索を有効にした場合だけ確認し、それ以外は「確認しなかったこと」に記録します。

API: `GET /api/workspaces/{workspace_id}/audit`（読み取り専用。ファイルの作成・変更は行いません）。
