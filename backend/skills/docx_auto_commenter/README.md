# DOCX Auto Commenter

添付された `.docx` を全文レビューし、LLM が生成したコメントを Word コメントとして埋め込んだ新しい DOCX を返す skill です。

## 使い方

- `.docx` を 1 つだけ添付する
- 任意で修正方針を書く
  - 例: `読みやすさを優先して、曖昧な表現と冗長な箇所を中心にコメントしてください`

## 制約

- OpenAI / Azure OpenAI の Responses API モデル専用
- 1 回の実行で扱える添付は 1 つの `.docx` のみ
- コメント付与対象は本文と表セル内の段落のみ
- header/footer、textbox、脚注、複数段落をまたぐ引用は対象外
- LLM が返した `quote` を本文に一意に見つけられない場合、その候補はスキップされる
