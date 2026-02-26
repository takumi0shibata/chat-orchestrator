import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "boj_timeseries_insight"
if str(SKILL_DIR) not in sys.path:
    sys.path.append(str(SKILL_DIR))

from series_catalog import PRESETS, resolve_series


def test_resolve_specific_series() -> None:
    result = resolve_series("全国CPIの推移を見せて")
    assert result.selected is not None
    assert result.selected.key == "cpi_all_japan"


def test_resolve_ambiguous_candidates() -> None:
    result = resolve_series("ドル円の為替推移")
    assert result.selected is None
    keys = sorted(item.key for item in result.candidates)
    assert keys == ["usdjpy_daily", "usdjpy_monthly"]


def test_resolve_no_match_returns_all_candidates() -> None:
    result = resolve_series("家計調査の話")
    assert result.selected is None
    assert len(result.candidates) == len(PRESETS)


def test_resolve_current_account() -> None:
    result = resolve_series("経常収支を見せて")
    assert result.selected is not None
    assert result.selected.key == "bop_current_account"


def test_resolve_lending_rate() -> None:
    result = resolve_series("貸出金利の推移")
    assert result.selected is not None
    assert result.selected.key == "lending_rate_new"


def test_resolve_money_stock() -> None:
    result = resolve_series("M2マネーストックの推移")
    assert result.selected is not None
    assert result.selected.key == "money_stock_m2"


def test_resolve_policy_rate() -> None:
    result = resolve_series("政策金利はどうなってる？")
    assert result.selected is not None
    assert result.selected.key == "boj_policy_rate"


def test_resolve_real_effective_fx() -> None:
    result = resolve_series("実質実効為替レートの推移")
    assert result.selected is not None
    assert result.selected.key == "effective_fx_real"


def test_preset_frequency_field() -> None:
    daily_presets = [p for p in PRESETS if p.frequency == "D"]
    monthly_presets = [p for p in PRESETS if p.frequency == "M"]
    assert len(daily_presets) >= 2
    assert len(monthly_presets) >= 8
    for preset in PRESETS:
        assert preset.frequency in ("D", "M")
