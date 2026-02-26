from typing import Any

from app.skills_runtime.base import Skill, SkillMetadata


class PaperReviewerSkill(Skill):
    metadata = SkillMetadata(
        id="paper_reviewer",
        name="Paper Reviewer (AI/ML/NLP)",
        description=(
            "論文本文やセンテンス単位の草稿をACL/ARR中心の観点でレビューし、"
            "AI/ML/NLP向けに実行可能なフィードバックとLaTeX修正案を生成する補助コンテキストを返します。"
        ),
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> str:
        text = user_text.strip()
        if not text:
            return (
                "Paper Reviewer コンテキスト\n\n"
                "## 不足情報 / 追加で欲しい情報\n"
                "- レビュー対象の文章を貼り付けてください（1文〜論文本文の抜粋まで可）。\n"
                "- 可能なら対象セクション（例: Abstract, Introduction）も指定してください。"
            )

        granularity = self._infer_granularity(text)
        language = self._infer_language(text)
        rewrite_mode = self._infer_rewrite_mode(text)

        last_user_messages = [
            item.get("content", "").strip()
            for item in history[-6:]
            if item.get("role") == "user" and item.get("content", "").strip()
        ]
        context_note = " / ".join(last_user_messages[-2:]) if last_user_messages else "履歴情報なし"

        lines = [
            "Paper Reviewer コンテキスト (AI/ML/NLP)",
            "",
            "## タスク定義",
            "- あなたは AI/ML/NLP 論文のアカデミックライティング・レビュアーです。",
            "- 入力テキストの範囲内だけを根拠に評価し、外部事実の捏造をしないでください。",
            "- デフォルト評価軸は ACL/ARR を主軸にし、ICML/NeurIPS の一般的観点で補強してください。",
            "",
            "## 入力解釈",
            f"- 推定粒度: {granularity}",
            f"- 推定言語: {language}",
            f"- 修正案方針: {rewrite_mode}",
            f"- 直近文脈: {context_note}",
            "",
            "## Review Protocol (ACL/ARR中心 + ML共通観点)",
            "- Claim-evidence alignment: 主張が提示結果・分析で裏付けられているか。",
            "- Novelty positioning: 関連研究との差分・貢献の境界が明確か。",
            "- Soundness: 設定・手法説明・評価方法の妥当性に飛躍がないか。",
            "- Clarity: 定義/記法/論理接続が明瞭で、曖昧表現や過剰断定がないか。",
            "- Reproducibility: データ分割、ハイパラ探索、計算資源、統計の記述が十分か。",
            "- Limitations/Responsible: 限界・失敗ケース・潜在的リスクの記述があるか。",
            "",
            "## 参照ガイドライン（一次情報）",
            "- ACL Rolling Review CFP / Reviewer Guidelines / Responsible NLP Checklist",
            "- ICML Reviewer Instructions (soundness, presentation, significance, originality)",
            "- NeurIPS Paper Checklist & Code/Data Submission Guidelines",
            "- EMNLP Reproducibility Criteria",
            "",
            "## 出力契約（必須フォーマット）",
            "- 次の5セクションをこの順で必ず出力する:",
            "  1. 判定サマリ",
            "  2. 主要指摘 (Major)",
            "  3. 軽微指摘 (Minor)",
            "  4. 修正案 (LaTeX)",
            "  5. 不足情報 / 追加で欲しい情報",
            "- フィードバック本文は日本語で書く。",
            "- 修正案は入力原文の言語を維持する（英語原稿なら英語で修正）。",
            "- 指摘は必ず『問題 -> 理由 -> 修正方針』の順で actionable に書く。",
            "- 修正案を出すときは、各項目を必ず `修正前:` と `修正後:` のペアで示す。",
            "- 情報不足時は断定を避け、必要な追加情報を具体的に列挙する。",
            "",
            "## 修正案ポリシー",
            "- 問題箇所のみ最小編集を優先し、全文リライトは避ける。",
            "- 重大な文章問題がある場合は、明示依頼がなくても修正案を提示する。",
            "- 修正案を提示する場合、最低1つは必ず `latex` コードブロックで示す。",
            "",
            "## LaTeX出力テンプレート（必須）",
            "```latex",
            "% 修正前",
            "% <original text>",
            "",
            "% 修正後",
            "% <revised text>",
            "```",
            "",
            "## レビュー対象テキスト",
            text,
        ]
        return "\n".join(lines)

    def _infer_granularity(self, text: str) -> str:
        normalized = text.strip()
        if len(normalized) < 280:
            return "sentence-level (短文/数文)"
        if len(normalized) < 1800:
            return "paragraph-level (段落/短い節)"
        return "full-text excerpt (長文/複数節)"

    def _infer_language(self, text: str) -> str:
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        ratio = ascii_chars / max(len(text), 1)
        if ratio > 0.9:
            return "English-oriented"
        return "Japanese or mixed"

    def _infer_rewrite_mode(self, text: str) -> str:
        lowered = text.lower()
        rewrite_keywords = [
            "rewrite",
            "revise",
            "polish",
            "添削",
            "修正",
            "書き直",
            "改善",
        ]
        if any(keyword in lowered for keyword in rewrite_keywords):
            return "explicit rewrite requested (problem-focused minimal edit)"
        return "review-first + rewrite when high-impact issues exist"


def build_skill() -> Skill:
    return PaperReviewerSkill()
