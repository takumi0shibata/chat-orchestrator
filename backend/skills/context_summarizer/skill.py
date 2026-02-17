from app.skills_runtime.base import Skill, SkillMetadata


class ContextSummarizerSkill(Skill):
    metadata = SkillMetadata(
        id="context_summarizer",
        name="Context Summarizer",
        description="会話履歴を短く要約して、モデルへ補助コンテキストとして渡します。",
    )

    async def run(self, user_text: str, history: list[dict[str, str]]) -> str:
        last_messages = history[-6:]
        if not last_messages:
            return "履歴はありません。"

        lines = []
        for item in last_messages:
            role = item.get("role", "unknown")
            content = item.get("content", "")
            clipped = content[:120]
            lines.append(f"- {role}: {clipped}")
        return "最近の会話要約:\n" + "\n".join(lines)


def build_skill() -> Skill:
    return ContextSummarizerSkill()
