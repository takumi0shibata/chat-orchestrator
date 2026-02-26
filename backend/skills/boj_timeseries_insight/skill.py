from __future__ import annotations

import os
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.skills_runtime.base import Skill, SkillMetadata

_SKILL_DIR = Path(__file__).resolve().parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.append(str(_SKILL_DIR))

from datetime import timedelta  # noqa: E402

from cache import JsonFileCache  # noqa: E402
from client import BojApiError, BojStatClient  # noqa: E402
from series_catalog import PRESETS, SeriesPreset, resolve_series  # noqa: E402


class BojTimeseriesInsightSkill(Skill):
    _CHART_SCHEMA = "boj_timeseries_chart/v1"
    _CHART_MAX_POINTS = 300

    metadata = SkillMetadata(
        id="boj_timeseries_insight",
        name="BOJ Timeseries Insight",
        description=(
            "日銀の時系列統計APIを使って代表系列を取得し、分析サマリと生データを含む補助コンテキストを返します。"
        ),
    )

    async def run(
        self,
        user_text: str,
        history: list[dict[str, str]],
        skill_context: dict[str, Any] | None = None,
    ) -> str:
        del history, skill_context

        resolution = resolve_series(user_text)
        if resolution.selected is None:
            return self._build_ambiguous_response(user_text=user_text, candidates=resolution.candidates)

        preset = resolution.selected
        freq = preset.frequency
        start_period, end_period = self._infer_period(freq=freq, user_text=user_text)
        force_refresh = self._is_retry_request(user_text)

        errors: list[str] = []
        notes: list[str] = []
        data_payload: dict[str, Any] | None = None

        if preset.advisory_note:
            notes.append(preset.advisory_note)

        cache = JsonFileCache(root=self._cache_root(), ttl_hours=self._cache_ttl_hours())
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            client = BojStatClient(client=http_client)
            resolved_code = preset.code
            if not resolved_code:
                resolved_code = await self._resolve_series_code(
                    cache=cache,
                    client=client,
                    preset=preset,
                    force_refresh=force_refresh,
                    errors=errors,
                )
                if not resolved_code:
                    return self._build_unsupported_series_response(
                        user_text=user_text,
                        preset=preset,
                    )
                notes.append(f"メタデータ検索で系列コードを解決: {resolved_code}")
            data_params = {
                "db": preset.db,
                "code": resolved_code,
                "startDate": start_period,
                "endDate": end_period,
                "format": "json",
            }

            data_payload = await self._fetch_with_cache(
                cache=cache,
                namespace="get_data_code",
                params=data_params,
                force_refresh=force_refresh,
                fetcher=lambda: client.get_data_code(data_params),
                errors=errors,
            )

        observations = self._extract_observations(data_payload)
        numeric_rows = []
        dropped_non_numeric = 0
        for time_key, raw_value in observations:
            value = self._to_float(raw_value)
            if value is None:
                dropped_non_numeric += 1
                continue
            numeric_rows.append((time_key, value, raw_value))

        numeric_rows.sort(key=lambda item: item[0])

        lines = [
            "BOJ時系列統計コンテキスト",
            "",
            "## 解釈結果",
            f"- 質問: {user_text}",
            f"- 選択系列: {preset.label}",
            f"- 系列説明: {preset.description}",
            f"- 頻度: {self._freq_label(freq)}",
            f"- 期間: {start_period} 〜 {end_period}",
            f"- データ点数（数値）: {len(numeric_rows)}",
            "",
            "## 分析サマリ",
        ]

        if not numeric_rows:
            lines.extend(
                [
                    "- 数値データを取得できませんでした。期間指定を広げるか、系列を具体化してください。",
                    "- 例: `長期金利 2018年から` / `CPI 2020-01から2025-12`",
                ]
            )
        else:
            first = numeric_rows[0]
            latest = numeric_rows[-1]
            delta = latest[1] - first[1]
            pct = (delta / first[1] * 100.0) if first[1] != 0 else None
            min_row = min(numeric_rows, key=lambda item: item[1])
            max_row = max(numeric_rows, key=lambda item: item[1])
            lines.append(f"- 直近値: {latest[0]} = {latest[1]:,.4f}")
            lines.append(f"- 期間変化: {first[0]}({first[1]:,.4f}) -> {latest[0]}({latest[1]:,.4f})")
            if pct is None:
                lines.append(f"- 変化量: {delta:,.4f}（増減率は基準値が0のため算出不可）")
            else:
                lines.append(f"- 変化量: {delta:,.4f} ({pct:+.2f}%)")
            lines.append(f"- 期間最小: {min_row[0]} = {min_row[1]:,.4f}")
            lines.append(f"- 期間最大: {max_row[0]} = {max_row[1]:,.4f}")

        lines.extend(["", "## 生データ（抜粋）"])
        if not numeric_rows:
            lines.append("- 利用可能な数値データはありません。")
        else:
            head = numeric_rows[:5]
            tail = numeric_rows[-5:] if len(numeric_rows) > 5 else []
            lines.append("- 先頭（古い順）")
            for row in head:
                lines.append(f"  - {row[0]}: {row[2]}")
            if tail:
                lines.append("- 末尾（新しい順）")
                for row in reversed(tail):
                    lines.append(f"  - {row[0]}: {row[2]}")

        lines.extend(["", "## API・データ品質メモ"])
        if data_payload is None:
            lines.append("- getDataCode の取得に失敗しました。")
        else:
            lines.append("- getDataCode 応答は取得済みです。")
        lines.append(f"- 非数値/欠損として除外した点数: {dropped_non_numeric}")
        if force_refresh:
            lines.append("- 再取得指定によりキャッシュをスキップしました。")
        else:
            lines.append(f"- キャッシュTTL: {self._cache_ttl_hours()} 時間")
        for note in notes:
            lines.append(f"- {note}")
        if errors:
            lines.append("- APIエラー:")
            for err in sorted(set(errors)):
                lines.append(f"  - {err}")

        lines.extend(
            [
                "",
                "## 回答ポリシー",
                "- 上記データを根拠として回答すること。",
                "- 根拠にない推測は避け、不明点は不明と明示すること。",
                "- 単位や定義が不明な場合は断定せず、追加確認を促すこと。",
            ]
        )
        chart_payload = self._build_chart_payload(preset=preset, freq=freq, numeric_rows=numeric_rows)
        if chart_payload is not None:
            lines.extend(
                [
                    "",
                    "```chart-json",
                    json.dumps(chart_payload, ensure_ascii=False),
                    "```",
                ]
            )
        return "\n".join(lines)

    async def _fetch_with_cache(
        self,
        *,
        cache: JsonFileCache,
        namespace: str,
        params: dict[str, str],
        force_refresh: bool,
        fetcher: Any,
        errors: list[str],
    ) -> dict[str, Any] | None:
        cache_key = {"namespace": namespace, **params}
        if not force_refresh:
            cached = cache.get(namespace=namespace, params=cache_key)
            if cached is not None:
                return cached
        try:
            payload = await fetcher()
        except BojApiError as exc:
            errors.append(str(exc))
            return None
        except Exception as exc:  # pragma: no cover
            errors.append(f"{namespace}: unexpected_error={exc}")
            return None
        cache.set(namespace=namespace, params=cache_key, payload=payload)
        return payload

    async def _resolve_series_code(
        self,
        *,
        cache: JsonFileCache,
        client: BojStatClient,
        preset: SeriesPreset,
        force_refresh: bool,
        errors: list[str],
    ) -> str | None:
        metadata_params = {"db": preset.db, "lang": "jp", "format": "json"}
        payload = await self._fetch_with_cache(
            cache=cache,
            namespace=f"metadata_{preset.db}",
            params=metadata_params,
            force_refresh=force_refresh,
            fetcher=lambda: client.get_metadata(metadata_params),
            errors=errors,
        )
        if payload is None:
            return None
        candidates = self._extract_series_candidates(payload)
        if not candidates:
            return None

        best_score = -1
        best_code: str | None = None
        for row in candidates:
            text = self._normalize_text(" ".join(str(v) for v in row.values()))
            score = 0
            for keyword in preset.metadata_keywords:
                if self._normalize_text(keyword) in text:
                    score += 1
            if score > best_score:
                best_score = score
                best_code = self._pick_first_str(row, ("SERIES_CODE", "seriesCode", "CODE", "code"))

        if best_score <= 0:
            return None
        if not best_code:
            return None
        return best_code.split("'")[-1]

    def _extract_series_candidates(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                code = self._pick_first_str(node, ("SERIES_CODE", "seriesCode", "CODE", "code"))
                if code:
                    rows.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return rows

    def _pick_first_str(self, node: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                scalar = self._extract_scalar_text(value)
                if scalar:
                    return scalar
        return None

    def _extract_scalar_text(self, node: dict[str, Any]) -> str | None:
        for key in ("$", "@value", "value", "VALUE", "text", "#text"):
            raw = node.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    def _extract_observations(self, payload: dict[str, Any] | None) -> list[tuple[str, str]]:
        if payload is None:
            return []

        observations: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        # BOJ getDataCode の標準形式:
        # RESULTSET[].VALUES.SURVEY_DATES[] と RESULTSET[].VALUES.VALUES[] をペアで読む。
        resultset = payload.get("RESULTSET")
        if isinstance(resultset, list):
            for series in resultset:
                if not isinstance(series, dict):
                    continue
                values_obj = series.get("VALUES")
                if not isinstance(values_obj, dict):
                    continue
                survey_dates = values_obj.get("SURVEY_DATES")
                values = values_obj.get("VALUES")
                if not isinstance(survey_dates, list) or not isinstance(values, list):
                    continue
                for date_raw, value_raw in zip(survey_dates, values):
                    if value_raw is None:
                        continue
                    time_value = str(date_raw).strip()
                    raw_value = str(value_raw).strip()
                    if not time_value or not raw_value:
                        continue
                    key = (time_value, raw_value)
                    if key in seen:
                        continue
                    seen.add(key)
                    observations.append(key)

        def pick_value(node: dict[str, Any], keys: tuple[str, ...]) -> str | None:
            for key in keys:
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    scalar = self._extract_scalar_text(value)
                    if scalar:
                        return scalar
            return None

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                time_value = pick_value(
                    node,
                    (
                        "time",
                        "TIME",
                        "Time",
                        "period",
                        "PERIOD",
                        "obsTime",
                        "obs_time",
                        "@time",
                        "年月",
                        "date",
                        "PERIOD_NAME",
                        "timeCode",
                        "@TIME_PERIOD",
                        "TIME_PERIOD",
                        "@PERIOD",
                    ),
                )
                raw_value = pick_value(
                    node,
                    (
                        "value",
                        "VALUE",
                        "Value",
                        "obsValue",
                        "obs_value",
                        "$",
                        "@value",
                        "data",
                        "DATA_VALUE",
                        "dataValue",
                        "@OBS_VALUE",
                        "OBS_VALUE",
                    ),
                )
                if time_value and raw_value:
                    key = (time_value, raw_value)
                    if key not in seen:
                        seen.add(key)
                        observations.append(key)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return observations

    def _to_float(self, value: str) -> float | None:
        cleaned = value.replace(",", "").replace("%", "").strip()
        if cleaned in {"", "-", "...", "NA", "N/A"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _infer_period(self, *, freq: str, user_text: str) -> tuple[str, str]:
        start, end = self._extract_explicit_period(user_text=user_text, freq=freq)
        if start and end:
            return start, end
        return self._default_period(freq=freq)

    def _extract_explicit_period(self, *, user_text: str, freq: str) -> tuple[str | None, str | None]:
        yyyymmdd = re.findall(
            r"(20\d{2})[-/年](1[0-2]|0?[1-9])[-/月](3[01]|[12]\d|0?[1-9])日?",
            user_text,
        )
        yyyymm = re.findall(r"(20\d{2})[-/年](1[0-2]|0?[1-9])", user_text)
        years = re.findall(r"(20\d{2})年", user_text)

        if freq == "D":
            if yyyymmdd:
                points = [f"{y}{int(m):02d}{int(d):02d}" for y, m, d in yyyymmdd]
                points.sort()
                if len(points) >= 2:
                    return points[0], points[-1]
                return points[0], self._default_period(freq="D")[1]
            if yyyymm:
                months = sorted((f"{y}{int(m):02d}", int(y), int(m)) for y, m in yyyymm)
                if len(months) >= 2:
                    first_month = months[0][0]
                    last_y, last_m = months[-1][1], months[-1][2]
                    _, end_day = self._last_day_of_month(int(last_y), int(last_m))
                    return f"{first_month}01", f"{last_y}{int(last_m):02d}{end_day:02d}"
                return f"{months[0][0]}01", self._default_period(freq="D")[1]
            return None, None

        if freq == "M" and yyyymm:
            points = [f"{y}{int(m):02d}" for y, m in yyyymm]
            points.sort()
            if len(points) >= 2:
                return points[0], points[-1]
            return points[0], self._default_period(freq="M")[1]

        if freq == "A" and years:
            years_sorted = sorted(years)
            if len(years_sorted) >= 2:
                return years_sorted[0], years_sorted[-1]
            return years_sorted[0], str(datetime.now(UTC).year)

        return None, None

    def _default_period(self, *, freq: str) -> tuple[str, str]:
        now = datetime.now(UTC)
        if freq == "D":
            end_date = now
            start_date = end_date - timedelta(days=90)
            return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")

        if freq == "A":
            end_year = now.year
            return str(end_year - 9), str(end_year)

        if freq == "Q":
            end_q = (now.month - 1) // 3 + 1
            end_year = now.year
            start_year, start_q = self._shift_quarters(end_year, end_q, -11)
            return f"{start_year}Q{start_q}", f"{end_year}Q{end_q}"

        end_year = now.year
        end_month = now.month
        start_year, start_month = self._shift_months(end_year, end_month, -23)
        return f"{start_year}{start_month:02d}", f"{end_year}{end_month:02d}"

    def _shift_months(self, year: int, month: int, delta: int) -> tuple[int, int]:
        value = year * 12 + (month - 1) + delta
        new_year = value // 12
        new_month = value % 12 + 1
        return new_year, new_month

    def _shift_quarters(self, year: int, quarter: int, delta: int) -> tuple[int, int]:
        value = year * 4 + (quarter - 1) + delta
        new_year = value // 4
        new_quarter = value % 4 + 1
        return new_year, new_quarter

    def _last_day_of_month(self, year: int, month: int) -> tuple[int, int]:
        """Return (year, last_day) for the given year/month."""
        import calendar

        _, last_day = calendar.monthrange(year, month)
        return year, last_day

    def _freq_label(self, freq: str) -> str:
        return {"D": "日次", "M": "月次", "Q": "四半期", "A": "年次"}.get(freq, freq)

    def _is_retry_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ("retry", "refresh", "再取得", "再実行"))

    def _cache_root(self) -> Path:
        settings = get_settings()
        if settings.boj_stat_cache_dir:
            expanded = Path(os.path.expandvars(os.path.expanduser(settings.boj_stat_cache_dir)))
            return expanded if expanded.is_absolute() else Path.home() / expanded
        xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache_home:
            return Path(xdg_cache_home) / "chat-orchestrator" / "boj-stat"
        return Path.home() / ".cache" / "chat-orchestrator" / "boj-stat"

    def _cache_ttl_hours(self) -> int:
        try:
            value = int(get_settings().boj_stat_cache_ttl_hours)
        except Exception:
            value = 24
        return max(1, value)

    def _build_ambiguous_response(self, *, user_text: str, candidates: list[SeriesPreset]) -> str:
        rows = candidates or list(PRESETS)
        lines = [
            "BOJ時系列統計コンテキスト",
            "",
            "## 解釈結果",
            f"- 質問: {user_text}",
            "- 選択系列: 未確定（候補提示）",
            "- 頻度: 系列未確定",
            "- 期間: 系列確定後に決定",
            "- データ点数（数値）: 0",
            "",
            "## 分析サマリ",
            "- 系列を特定できませんでした。候補から1つ指定してください。",
            "",
            "## 生データ（抜粋）",
            "- 系列未確定のため取得していません。",
            "",
            "## API・データ品質メモ",
            "- 曖昧性: 系列候補が複数または未一致です。",
            "- 候補系列:",
        ]
        for preset in rows:
            lines.append(f"  - {preset.label}: {preset.description}")
        lines.extend(
            [
                "- 再入力例: `全国CPIを直近2年で` / `長期金利 2019年から`",
                "",
                "## 回答ポリシー",
                "- 根拠にない推測はしない。",
                "- まず系列を確定してから分析する。",
            ]
        )
        return "\n".join(lines)

    def _build_unsupported_series_response(self, *, user_text: str, preset: SeriesPreset) -> str:
        lines = [
            "BOJ時系列統計コンテキスト",
            "",
            "## 解釈結果",
            f"- 質問: {user_text}",
            f"- 選択系列: {preset.label}",
            f"- 系列説明: {preset.description}",
            "",
            "## 分析サマリ",
            "- この系列のデータコードをメタデータから解決できず、取得できませんでした。",
            "",
            "## 生データ（抜粋）",
            "- データ未取得です。",
            "",
            "## API・データ品質メモ",
            f"- {preset.advisory_note or '対象DB内で系列コードを特定できませんでした。'}",
            "- 原因: メタデータ上で一致する `SERIES_CODE` が見つからないため、getDataCode を実行できませんでした。",
            "",
            "## 回答ポリシー",
            "- 根拠にない推測はしない。",
            "- 系列コード確定後に再実行する。",
        ]
        return "\n".join(lines)

    def _build_chart_payload(
        self,
        *,
        preset: SeriesPreset,
        freq: str,
        numeric_rows: list[tuple[str, float, str]],
    ) -> dict[str, Any] | None:
        if not numeric_rows:
            return None
        chart_rows = self._sample_chart_rows(numeric_rows=numeric_rows, max_points=self._CHART_MAX_POINTS)
        points = [
            {
                "time": time_key,
                "value": value,
                "raw": raw_value,
            }
            for time_key, value, raw_value in chart_rows
        ]
        return {
            "schema": self._CHART_SCHEMA,
            "series_label": preset.label,
            "frequency": freq,
            "points": points,
        }

    def _sample_chart_rows(
        self,
        *,
        numeric_rows: list[tuple[str, float, str]],
        max_points: int,
    ) -> list[tuple[str, float, str]]:
        if len(numeric_rows) <= max_points:
            return numeric_rows
        if max_points <= 1:
            return [numeric_rows[-1]]

        last_index = len(numeric_rows) - 1
        step = last_index / (max_points - 1)
        sampled_indices = sorted({round(step * idx) for idx in range(max_points)} | {0, last_index})
        return [numeric_rows[idx] for idx in sampled_indices]


def build_skill() -> Skill:
    return BojTimeseriesInsightSkill()
