import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SectionDefinition:
    section_id: str
    title: str
    tag_candidates: list[str]
    keywords: list[str]
    aliases: list[str]


_DEFAULT_SECTION_IDS = ["2-4", "2-3", "1-3"]

_DEFAULT_SECTIONS = [
    {"section_id": "1-1", "title": "主要な経営指標等の推移", "keywords": ["経営指標", "kpi", "推移"], "tag_candidates": ["BusinessResultsOfGroupTextBlock"], "aliases": ["主要KPI", "指標推移"]},
    {"section_id": "1-2", "title": "沿革", "keywords": ["沿革", "歴史", "創業"], "tag_candidates": ["CompanyHistoryTextBlock"], "aliases": ["会社の歴史"]},
    {"section_id": "1-3", "title": "事業の内容", "keywords": ["事業", "ビジネスモデル", "セグメント"], "tag_candidates": ["DescriptionOfBusinessTextBlock"], "aliases": ["事業内容", "ビジネス"]},
    {"section_id": "1-4", "title": "関係会社の状況", "keywords": ["関係会社", "子会社", "関連会社"], "tag_candidates": ["OverviewOfAffiliatedEntitiesTextBlock"], "aliases": []},
    {"section_id": "1-5", "title": "従業員の状況", "keywords": ["従業員", "社員", "人員"], "tag_candidates": ["InformationAboutEmployeesTextBlock"], "aliases": ["人的資本"]},
    {"section_id": "2-1", "title": "経営方針、経営環境及び対処すべき課題等", "keywords": ["経営方針", "経営環境", "課題", "対処"], "tag_candidates": ["BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock", "OverviewOfBusinessResultsTextBlock"], "aliases": ["経営課題"]},
    {"section_id": "2-2", "title": "サステナビリティに関する考え方及び取組", "keywords": ["サステナビリティ", "esg", "気候", "脱炭素", "人的資本"], "tag_candidates": ["DisclosureOfSustainabilityRelatedFinancialInformationTextBlock"], "aliases": ["ESG"]},
    {"section_id": "2-3", "title": "事業等のリスク", "keywords": ["リスク", "不確実性", "懸念", "継続企業"], "tag_candidates": ["BusinessRisksTextBlock", "MaterialMattersRelatingToGoingConcernEtcBusinessRisksTextBlock"], "aliases": ["リスク情報"]},
    {"section_id": "2-4", "title": "経営者による財政状態、経営成績及びキャッシュ・フローの状況の分析", "keywords": ["財政状態", "経営成績", "キャッシュフロー", "md&a", "分析"], "tag_candidates": ["ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock"], "aliases": ["MD&A", "経営者分析"]},
    {"section_id": "2-5", "title": "重要な契約等", "keywords": ["契約", "提携", "ライセンス"], "tag_candidates": ["MaterialContractsTextBlock", "SignificantContractsTextBlock"], "aliases": []},
    {"section_id": "2-6", "title": "研究開発活動", "keywords": ["研究開発", "r&d"], "tag_candidates": ["ResearchAndDevelopmentActivitiesTextBlock"], "aliases": []},
    {"section_id": "3-1", "title": "設備投資等の概要", "keywords": ["設備投資", "capex"], "tag_candidates": ["CapitalExpendituresOverviewTextBlock", "OverviewOfCapitalExpendituresEtcTextBlock"], "aliases": []},
    {"section_id": "3-2", "title": "主要な設備の状況", "keywords": ["設備", "工場", "拠点"], "tag_candidates": ["MajorFacilitiesTextBlock", "MainFacilitiesTextBlock"], "aliases": []},
    {"section_id": "3-3", "title": "設備の新設、除却等の計画", "keywords": ["新設", "除却", "設備計画"], "tag_candidates": ["PlansForNewConstructionRemovalEtcOfFacilitiesTextBlock"], "aliases": []},
    {"section_id": "4-1-1", "title": "株式の総数等", "keywords": ["株式数", "発行済株式", "株数"], "tag_candidates": ["TotalNumberOfSharesEtcTextBlock"], "aliases": []},
    {"section_id": "4-1-5", "title": "所有者別状況", "keywords": ["所有者別", "株主構成"], "tag_candidates": ["DistributionOfShareholdersTextBlock"], "aliases": []},
    {"section_id": "4-1-6", "title": "大株主の状況", "keywords": ["大株主", "主要株主"], "tag_candidates": ["MajorShareholdersTextBlock"], "aliases": []},
    {"section_id": "4-3", "title": "配当政策", "keywords": ["配当", "配当政策", "配当性向"], "tag_candidates": ["DividendPolicyTextBlock"], "aliases": []},
    {"section_id": "4-4-1", "title": "コーポレート・ガバナンスの概要", "keywords": ["コーポレートガバナンス", "ガバナンス"], "tag_candidates": ["OverviewOfCorporateGovernanceTextBlock"], "aliases": []},
    {"section_id": "4-4-2", "title": "役員の状況", "keywords": ["役員", "取締役", "監査役"], "tag_candidates": ["OfficersTextBlock", "StatusOfOfficersTextBlock"], "aliases": []},
    {"section_id": "4-4-3", "title": "監査の状況", "keywords": ["監査", "内部監査", "会計監査"], "tag_candidates": ["AuditTextBlock", "StatusOfAuditTextBlock"], "aliases": []},
    {"section_id": "4-4-4", "title": "役員の報酬等", "keywords": ["報酬", "役員報酬"], "tag_candidates": ["CompensationForOfficersTextBlock", "RemunerationForDirectorsTextBlock"], "aliases": []},
    {"section_id": "5-1-1", "title": "連結財務諸表", "keywords": ["連結財務諸表", "連結"], "tag_candidates": ["ConsolidatedFinancialStatementsTextBlock"], "aliases": []},
    {"section_id": "5-1-2", "title": "その他（連結）", "keywords": ["連結注記", "連結その他"], "tag_candidates": ["OtherInformationConsolidatedTextBlock"], "aliases": []},
    {"section_id": "5-2-1", "title": "財務諸表（単体）", "keywords": ["財務諸表", "単体", "貸借対照表", "損益計算書"], "tag_candidates": ["NonConsolidatedFinancialStatementsTextBlock", "FinancialStatementsTextBlock"], "aliases": []},
    {"section_id": "5-2-2", "title": "主な資産及び負債の内容", "keywords": ["資産", "負債"], "tag_candidates": ["MajorAssetsAndLiabilitiesTextBlock"], "aliases": []},
    {"section_id": "5-2-3", "title": "その他（単体）", "keywords": ["単体その他"], "tag_candidates": ["OtherInformationNonConsolidatedTextBlock"], "aliases": []},
    {"section_id": "6", "title": "提出会社の株式事務の概要", "keywords": ["株式事務"], "tag_candidates": ["ShareHandlingProceduresTextBlock"], "aliases": []},
    {"section_id": "7-1", "title": "提出会社の親会社等の情報", "keywords": ["親会社"], "tag_candidates": ["InformationAboutParentCompanyEtcTextBlock"], "aliases": []},
    {"section_id": "7-2", "title": "その他の参考情報", "keywords": ["参考情報"], "tag_candidates": ["OtherReferenceInformationTextBlock"], "aliases": []},
    {"section_id": "8", "title": "提出会社の保証会社等の情報", "keywords": ["保証会社"], "tag_candidates": ["InformationAboutGuarantorCompaniesEtcTextBlock"], "aliases": []},
]


class SectionCatalog:
    def __init__(self, sections: list[SectionDefinition]):
        self.sections = sections
        self._by_id = {section.section_id: section for section in sections}

    @classmethod
    def load(cls, path: Path) -> "SectionCatalog":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("sections must be a list")
            sections: list[SectionDefinition] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                section_id = str(row.get("section_id") or "").strip()
                title = str(row.get("title") or "").strip()
                if not section_id or not title:
                    continue
                sections.append(
                    SectionDefinition(
                        section_id=section_id,
                        title=title,
                        tag_candidates=[str(x).strip() for x in row.get("tag_candidates", []) if str(x).strip()],
                        keywords=[str(x).strip() for x in row.get("keywords", []) if str(x).strip()],
                        aliases=[str(x).strip() for x in row.get("aliases", []) if str(x).strip()],
                    )
                )
            if sections:
                return cls(sections)
        except Exception:
            pass

        fallback = [
            SectionDefinition(
                section_id=row["section_id"],
                title=row["title"],
                tag_candidates=list(row["tag_candidates"]),
                keywords=list(row["keywords"]),
                aliases=list(row["aliases"]),
            )
            for row in _DEFAULT_SECTIONS
        ]
        return cls(fallback)

    def select_sections(
        self,
        *,
        question: str,
        intent_section_queries: list[str],
        max_sections: int = 3,
    ) -> tuple[list[SectionDefinition], dict[str, str], list[str]]:
        reasons: dict[str, str] = {}
        unresolved_queries: list[str] = []
        selected_ids: list[str] = []

        for query in intent_section_queries:
            section = self._match_section(query)
            if section is None:
                unresolved_queries.append(query)
                continue
            if section.section_id in selected_ids:
                continue
            selected_ids.append(section.section_id)
            reasons[section.section_id] = f"LLM指定: {query}"

        if len(selected_ids) < max_sections:
            scored = self._rank_by_keywords(question)
            for section in scored:
                if section.section_id in selected_ids:
                    continue
                selected_ids.append(section.section_id)
                reasons.setdefault(section.section_id, "キーワード一致")
                if len(selected_ids) >= max_sections:
                    break

        if not selected_ids:
            for section_id in _DEFAULT_SECTION_IDS:
                section = self._by_id.get(section_id)
                if section is None:
                    continue
                selected_ids.append(section_id)
                reasons[section_id] = "デフォルト"
                if len(selected_ids) >= max_sections:
                    break

        selected = [self._by_id[sec_id] for sec_id in selected_ids if sec_id in self._by_id]
        return selected, reasons, unresolved_queries

    def _match_section(self, query: str) -> SectionDefinition | None:
        normalized_query = _norm_text(query)
        if not normalized_query:
            return None

        by_id = self._by_id.get(query)
        if by_id is not None:
            return by_id

        for section in self.sections:
            variants = [section.title, section.section_id, *section.aliases]
            for variant in variants:
                normalized_variant = _norm_text(variant)
                if not normalized_variant:
                    continue
                if normalized_query == normalized_variant:
                    return section
                if normalized_query in normalized_variant:
                    return section
                if normalized_variant in normalized_query:
                    return section
        return None

    def _rank_by_keywords(self, question: str) -> list[SectionDefinition]:
        normalized_question = _norm_text(question)
        scored: list[tuple[int, int, SectionDefinition]] = []
        for index, section in enumerate(self.sections):
            score = 0
            for keyword in section.keywords:
                normalized_keyword = _norm_text(keyword)
                if normalized_keyword and normalized_keyword in normalized_question:
                    score += 2
            if section.section_id.startswith("2-"):
                score += 1
            scored.append((score, -index, section))
        scored.sort(reverse=True)
        return [section for score, _, section in scored if score > 0]


def _norm_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower().strip()
    normalized = normalized.replace("株式会社", "")
    normalized = normalized.replace("(株)", "")
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("　", "")
    normalized = re.sub(r"[\[\]【】()（）]", "", normalized)
    return normalized
