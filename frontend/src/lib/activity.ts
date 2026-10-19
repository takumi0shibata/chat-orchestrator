import type { UsageDay } from "../types";

export type ActivityMetric = "runs" | "tokens" | "cost";
export interface ActivityCell {
  date: string;
  value: number;
  /** 0 for no activity, then 1–4 by share of the busiest day. */
  level: number;
  /** Past the last day of the range; rendered as an empty slot. */
  future: boolean;
}
export interface ActivityGrid {
  /** Columns of seven days, Sunday first. */
  weeks: ActivityCell[][];
  months: { column: number; label: string }[];
  total: number;
  activeDays: number;
  currentStreak: number;
  longestStreak: number;
}

const DAY = 24 * 60 * 60 * 1000;
const monthLabel = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });

/** Calendar dates as UTC midnights, so arithmetic is immune to local DST. */
function parse(date: string) {
  return new Date(`${date}T00:00:00Z`);
}
function format(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function metricValue(day: UsageDay | undefined, metric: ActivityMetric) {
  if (!day) return 0;
  if (metric === "runs") return day.runs;
  if (metric === "tokens") return day.input_tokens + day.output_tokens;
  return day.usd;
}

/** A GitHub-style grid of `weeks` columns ending with the week that contains `today`. */
export function activityGrid(today: string, days: UsageDay[], metric: ActivityMetric, weeks = 53): ActivityGrid {
  const end = parse(today);
  const start = new Date(end.getTime() - ((weeks - 1) * 7 + end.getUTCDay()) * DAY);
  const byDate = new Map(days.map((day) => [day.date, day]));
  const values: { date: string; value: number }[] = [];
  for (let time = start.getTime(); time <= end.getTime(); time += DAY) {
    const date = format(new Date(time));
    values.push({ date, value: metricValue(byDate.get(date), metric) });
  }
  const max = Math.max(0, ...values.map((item) => item.value));
  const level = (value: number) => (value > 0 && max > 0 ? Math.max(1, Math.ceil((value / max) * 4)) : 0);

  const grid: ActivityCell[][] = [];
  const months: ActivityGrid["months"] = [];
  for (let column = 0; column < weeks; column += 1) {
    const week: ActivityCell[] = [];
    for (let row = 0; row < 7; row += 1) {
      const index = column * 7 + row;
      const item = values[index];
      week.push(item
        ? { date: item.date, value: item.value, level: level(item.value), future: false }
        : { date: format(new Date(start.getTime() + index * DAY)), value: 0, level: 0, future: true });
    }
    // Label a column when it holds the first day of a month (and always the first column).
    const first = week.find((cell) => cell.date.endsWith("-01"));
    if (column === 0 || first) months.push({ column, label: monthLabel.format(parse(first?.date ?? week[0].date)) });
    grid.push(week);
  }
  // The leading partial month has no room for its label when the next one follows closely.
  if (months.length > 1 && months[1].column <= 2) months.shift();

  let longestStreak = 0;
  let run = 0;
  for (const item of values) {
    run = item.value > 0 ? run + 1 : 0;
    longestStreak = Math.max(longestStreak, run);
  }
  // Today without activity yet does not break a streak that ran through yesterday.
  let currentStreak = 0;
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index].value > 0) currentStreak += 1;
    else if (index !== values.length - 1) break;
  }
  return {
    weeks: grid,
    months,
    total: values.reduce((sum, item) => sum + item.value, 0),
    activeDays: values.filter((item) => item.value > 0).length,
    currentStreak,
    longestStreak,
  };
}

/**
 * Calendar geometry in whole pixels: fractional cells round unevenly and look ragged.
 * The weekday column is 24px plus a 4px gap (see UsageDashboard.css); small cells get a 2px gap to stay legible.
 */
const WEEKDAY_COLUMN = 28;
const MIN_CELL = 8;
const MAX_CELL = 15;

export function activityCellSize(width: number, weeks: number) {
  const fit = (gap: number) => Math.floor((width - WEEKDAY_COLUMN - (weeks - 1) * gap) / weeks);
  const gap = fit(3) >= 11 ? 3 : 2;
  return { cell: Math.max(MIN_CELL, Math.min(MAX_CELL, fit(gap))), gap };
}
