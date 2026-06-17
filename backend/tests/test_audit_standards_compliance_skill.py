import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from skills.audit_standards_compliance.skill import AuditStandardsComplianceSkill  # noqa: E402


def test_skill_returns_retrieved_compliance_context() -> None:
    skill = AuditStandardsComplianceSkill()

    result = asyncio.run(
        skill.run(
            user_text="監査証拠について、回答時に確認すべき観点を教えて",
            history=[],
            skill_context={},
        )
    )

    assert "監査基準準拠モード" in result.llm_context
    assert "Source 1" in result.llm_context
    assert "監査証拠" in result.llm_context
    assert "official/authoritative" in result.llm_context
    assert "日本公認会計士協会" in result.llm_context


def test_skill_accepts_ability_params_for_filters_and_limit() -> None:
    skill = AuditStandardsComplianceSkill()

    result = asyncio.run(
        skill.run(
            user_text="この質問本文より ability params を優先する",
            history=[],
            skill_context={
                "ability_params": {
                    "query": "独立性と倫理の阻害要因",
                    "jurisdictions": ["JP"],
                    "standard_families": ["auditing"],
                    "max_sources": 1,
                }
            },
        )
    )

    assert "検索クエリ: 独立性と倫理の阻害要因" in result.llm_context
    assert "推定 jurisdiction: JP" in result.llm_context
    assert "推定 document family: auditing" in result.llm_context
    assert result.llm_context.count("### Source") == 1
    assert "独立性と倫理" in result.llm_context
