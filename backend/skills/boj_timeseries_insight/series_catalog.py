from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeriesPreset:
    key: str
    label: str
    description: str
    keywords: tuple[str, ...]
    db: str
    code: str | None
    frequency: str  # "D" (daily) or "M" (monthly)
    metadata_keywords: tuple[str, ...]
    advisory_note: str | None = None


@dataclass(frozen=True)
class SeriesResolution:
    selected: SeriesPreset | None
    candidates: list[SeriesPreset]


PRESETS: tuple[SeriesPreset, ...] = (
    # --- 金利 ---
    SeriesPreset(
        key="call_rate_overnight",
        label="無担保コール翌日物",
        description="短期金利の代表として無担保コール翌日物を対象にする系列",
        keywords=("短期金利", "コール", "無担保コール", "翌日物", "call rate", "overnight"),
        db="FM01",
        code="STRDCLUCON",
        frequency="M",
        metadata_keywords=("無担保コール", "翌日物"),
    ),
    SeriesPreset(
        key="boj_policy_rate",
        label="基準割引率・基準貸付利率",
        description="日本銀行の基準割引率および基準貸付利率（旧公定歩合）",
        keywords=("基準割引率", "基準貸付利率", "公定歩合", "政策金利", "policy rate", "discount rate"),
        db="IR01",
        code="MADR1M",
        frequency="M",
        metadata_keywords=("基準割引率", "基準貸付利率"),
    ),
    SeriesPreset(
        key="lending_rate_new",
        label="新規貸出約定平均金利（国内銀行）",
        description="国内銀行の新規貸出約定平均金利（総合）",
        keywords=("貸出金利", "貸出約定", "lending rate", "新規貸出", "bank lending", "ローン金利"),
        db="IR04",
        code="DLLR2CIDBNL1",
        frequency="M",
        metadata_keywords=("新規貸出", "約定平均金利"),
    ),
    # --- 為替 ---
    SeriesPreset(
        key="usdjpy_daily",
        label="ドル円為替レート（日次・17時時点）",
        description="東京市場ドル・円スポットレート 17時時点（日次）",
        keywords=("ドル円", "usdjpy", "usd/jpy", "円ドル", "ドル", "日次為替"),
        db="FM08",
        code="FXERD04",
        frequency="D",
        metadata_keywords=("ドル・円", "スポット", "17時"),
    ),
    SeriesPreset(
        key="usdjpy_monthly",
        label="ドル円為替レート（月次平均）",
        description="東京市場ドル・円スポットレート 17時時点（月中平均）",
        keywords=("ドル円", "usdjpy", "usd/jpy", "為替", "円ドル", "月次為替", "月平均"),
        db="FM08",
        code="FXERM07",
        frequency="M",
        metadata_keywords=("ドル・円", "月中平均"),
    ),
    SeriesPreset(
        key="eurusd_daily",
        label="ユーロドル為替レート（日次・9時時点）",
        description="ユーロ・ドル スポットレート 9時時点（日次）",
        keywords=("ユーロドル", "eurusd", "eur/usd", "ユーロ"),
        db="FM08",
        code="FXERD31",
        frequency="D",
        metadata_keywords=("ユーロ・ドル", "スポット", "9時"),
    ),
    SeriesPreset(
        key="effective_fx_real",
        label="実質実効為替レート",
        description="実質実効為替レート指数（2020年=100）",
        keywords=("実質実効", "実効為替", "real effective", "REER", "実効レート"),
        db="FM09",
        code="FX180110002",
        frequency="M",
        metadata_keywords=("実質実効為替レート",),
    ),
    # --- マネー ---
    SeriesPreset(
        key="money_stock_m2",
        label="マネーストック M2（前年比）",
        description="マネーストック M2 前年同月比増減率",
        keywords=("マネーストック", "M2", "money stock", "通貨供給", "マネサプ"),
        db="MD02",
        code="MAM1YAM2M2MO",
        frequency="M",
        metadata_keywords=("M2", "前年比"),
    ),
    SeriesPreset(
        key="monetary_base_avg",
        label="マネタリーベース平残",
        description="マネタリーベース（月中平均残高）の代表系列",
        keywords=("マネタリーベース", "平残", "資金供給", "ベースマネー", "monetary base"),
        db="MD01",
        code=None,
        frequency="M",
        metadata_keywords=("マネタリーベース", "平均残高"),
    ),
    # --- 国際収支 ---
    SeriesPreset(
        key="bop_current_account",
        label="経常収支",
        description="国際収支統計 経常収支（ネット、億円）",
        keywords=("経常収支", "current account", "国際収支"),
        db="BP01",
        code="BPBP6JYNCB",
        frequency="M",
        metadata_keywords=("経常収支",),
    ),
    SeriesPreset(
        key="bop_trade_balance",
        label="貿易収支",
        description="国際収支統計 貿易収支（ネット、億円）",
        keywords=("貿易収支", "trade balance", "輸出入", "貿易"),
        db="BP01",
        code="BPBP6JYNTB",
        frequency="M",
        metadata_keywords=("貿易収支",),
    ),
    # --- 物価 ---
    SeriesPreset(
        key="cpi_all_japan",
        label="企業物価指数（国内企業物価指数・総平均）",
        description="BOJ APIで取得可能な物価系列（全国CPI指定時の代替系列）",
        keywords=("cpi", "消費者物価", "物価", "インフレ", "全国cpi", "全国消費者物価", "企業物価"),
        db="PR01",
        code=None,
        frequency="M",
        metadata_keywords=("国内企業物価指数", "総平均"),
        advisory_note=(
            "全国CPI（総合）はBOJ APIの主要提供系列に含まれないため、"
            "企業物価指数（国内企業物価指数・総平均）を代替として使用しています。"
        ),
    ),
)


def resolve_series(user_text: str) -> SeriesResolution:
    lowered = user_text.lower()
    scored: list[tuple[int, SeriesPreset]] = []

    for preset in PRESETS:
        score = 0
        for keyword in preset.keywords:
            if keyword.lower() in lowered:
                score += 1
        if score > 0:
            scored.append((score, preset))

    if not scored:
        return SeriesResolution(selected=None, candidates=list(PRESETS))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score = scored[0][0]
    top = [preset for score, preset in scored if score == top_score]

    if len(top) > 1:
        return SeriesResolution(selected=None, candidates=top)

    return SeriesResolution(selected=top[0], candidates=top)
