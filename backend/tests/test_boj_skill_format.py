import asyncio
import json
import re
import sys
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from skills.boj_timeseries_insight.skill import BojTimeseriesInsightSkill


async def _fake_fetch_with_cache(self, *, namespace, **kwargs):
    if namespace.startswith("metadata_"):
        return {
            "RESULT": {"STATUS": 0},
            "rows": [
                {"SERIES_CODE": "PRCG3M_2200000000", "NAME_OF_TIME_SERIES_J": "国内企業物価指数 総平均"},
            ],
        }
    if namespace == "get_data_code":
        return {
            "STATUS": 200,
            "RESULTSET": [
                {
                    "SERIES_CODE": "PRCG20_2200000000",
                    "VALUES": {
                        "SURVEY_DATES": [202401, 202402, 202403, 202404],
                        "VALUES": [102.0, 102.3, None, 102.8],
                    },
                }
            ],
        }
    return None


def test_skill_output_has_required_sections(monkeypatch) -> None:
    skill = BojTimeseriesInsightSkill()
    skill._fetch_with_cache = types.MethodType(_fake_fetch_with_cache, skill)

    output = asyncio.run(skill.run(user_text="全国CPIの推移を見せて", history=[]))

    assert "BOJ時系列統計コンテキスト" in output
    assert "## 解釈結果" in output
    assert "## 分析サマリ" in output
    assert "## 生データ（抜粋）" in output
    assert "## API・データ品質メモ" in output
    assert "## 回答ポリシー" in output


def test_skill_output_includes_chart_json_block() -> None:
    skill = BojTimeseriesInsightSkill()
    skill._fetch_with_cache = types.MethodType(_fake_fetch_with_cache, skill)

    output = asyncio.run(skill.run(user_text="全国CPIの推移を見せて", history=[]))
    match = re.search(r"```chart-json\s*\n([\s\S]*?)```", output)
    assert match is not None

    payload = json.loads(match.group(1))
    assert payload["schema"] == "boj_timeseries_chart/v1"
    assert payload["series_label"]
    assert payload["frequency"] in {"D", "M", "Q", "A"}
    assert payload["points"]
    assert all("time" in point and "value" in point and "raw" in point for point in payload["points"])


def test_skill_ambiguous_has_candidates(monkeypatch) -> None:
    skill = BojTimeseriesInsightSkill()
    output = asyncio.run(skill.run(user_text="景況感を見たい", history=[]))

    assert "選択系列: 未確定" in output
    assert "候補系列" in output


async def _fake_no_numeric_fetch(self, *, namespace, **kwargs):
    if namespace == "get_data_code":
        return {
            "STATUS": 200,
            "RESULTSET": [
                {
                    "SERIES_CODE": "PRCG20_2200000000",
                    "VALUES": {
                        "SURVEY_DATES": [202401, 202402],
                        "VALUES": ["NA", "..."],
                    },
                }
            ],
        }
    if namespace.startswith("metadata_"):
        return {"RESULT": {"STATUS": 0}}
    return None


def test_skill_output_omits_chart_when_no_numeric_points() -> None:
    skill = BojTimeseriesInsightSkill()
    skill._fetch_with_cache = types.MethodType(_fake_no_numeric_fetch, skill)

    output = asyncio.run(skill.run(user_text="無担保コール翌日物の推移", history=[]))
    assert "```chart-json" not in output


async def _fake_daily_fetch(self, *, namespace, **kwargs):
    if namespace == "get_data_code":
        return {
            "STATUS": 200,
            "RESULTSET": [
                {
                    "SERIES_CODE": "FXERD04",
                    "VALUES": {
                        "SURVEY_DATES": [20250101, 20250102, 20250103],
                        "VALUES": [157.5, 157.8, 158.0],
                    },
                }
            ],
        }
    return None


def test_daily_preset_uses_daily_frequency() -> None:
    """Daily presets should report 日次 frequency and produce valid output."""
    skill = BojTimeseriesInsightSkill()
    skill._fetch_with_cache = types.MethodType(_fake_daily_fetch, skill)

    output = asyncio.run(skill.run(user_text="ドル円の日次為替を見せて", history=[]))

    assert "BOJ時系列統計コンテキスト" in output
    assert "頻度: 日次" in output
    assert "## 分析サマリ" in output


def test_daily_period_parsing_is_order_independent_for_month_tokens() -> None:
    skill = BojTimeseriesInsightSkill()
    start, end = skill._extract_explicit_period(user_text="2025-12 から 2024-01 まで", freq="D")
    assert start == "20240101"
    assert end == "20251231"
