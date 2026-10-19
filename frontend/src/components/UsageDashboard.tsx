import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { activityCellSize, activityGrid, type ActivityCell, type ActivityMetric } from "../lib/activity";
import type { UsageDashboard as Dashboard, UsageTotals } from "../types";
import "./UsageDashboard.css";

export interface BudgetStatus {
  spent: number;
  budget: number;
  ratio: number;
  level: "ok" | "near" | "over";
}

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat("en-US");
const percent = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });
const cents = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const small = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 });
const day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const monthName = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

/** Cents for normal amounts; sub-dollar amounts keep up to four decimals so they don't read as $0.00. */
const usd = (value: number) => (value > 0 && value < 1 ? small : cents).format(value);
const tokens = (value: number) => compact.format(value);
/** Share of input tokens served from the prompt cache; null before any input. */
export const cacheHitRate = (usage: UsageTotals) => (usage.input_tokens ? usage.cached_input_tokens / usage.input_tokens : null);

const METRICS: { id: ActivityMetric; label: string }[] = [
  { id: "runs", label: "Runs" },
  { id: "tokens", label: "Tokens" },
  { id: "cost", label: "Cost" },
];
const WEEKDAYS = ["", "Mon", "", "Wed", "", "Fri", ""];

function metricText(metric: ActivityMetric, value: number) {
  if (metric === "runs") return `${whole.format(value)} ${value === 1 ? "run" : "runs"}`;
  if (metric === "tokens") return `${tokens(value)} tokens`;
  return usd(value);
}

/** Fraction of the current UTC month that has passed, for the spending pace. */
function monthElapsed(now = new Date()) {
  const start = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1);
  const end = Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1);
  return { elapsed: (now.getTime() - start) / (end - start), daysLeft: Math.ceil((end - now.getTime()) / 86_400_000) };
}

function Stat({ label, value, title, detail }: { label: string; value: string; title?: string; detail: string }) {
  return (
    <div className="dashboard-stat">
      <span>{label}</span>
      <strong title={title}>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export function UsageDashboard({ budget, refreshKey, labelFor, onSetBudget }: {
  budget: BudgetStatus | null;
  refreshKey: number;
  labelFor: (provider: string, model: string) => string;
  onSetBudget: () => void;
}) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [metric, setMetric] = useState<ActivityMetric>("runs");
  const [hovered, setHovered] = useState<ActivityCell | null>(null);

  useEffect(() => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    api<Dashboard>(`/usage/dashboard?tz=${encodeURIComponent(zone)}`)
      .then((next) => { setData(next); setError(""); })
      .catch((e) => setError(String(e)));
  }, [refreshKey]);

  const grid = useMemo(() => data && activityGrid(data.today, data.days, metric), [data, metric]);
  const calendar = useRef<HTMLDivElement>(null);
  const loaded = Boolean(grid);
  const weeks = grid?.weeks.length ?? 0;
  const [{ cell, gap }, setGeometry] = useState({ cell: 11, gap: 3 });
  useLayoutEffect(() => {
    const element = calendar.current;
    if (!element || !weeks) return;
    const measure = () => {
      // Unlaid-out (e.g. hidden) calendars report no width; keep the last size.
      if (element.clientWidth > 0) setGeometry(activityCellSize(element.clientWidth, weeks));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [weeks]);
  // Narrow screens scroll the calendar; start at the most recent weeks.
  useLayoutEffect(() => {
    if (calendar.current) calendar.current.scrollLeft = calendar.current.scrollWidth;
  }, [loaded, cell]);
  if (error && !data) return <p className="settings-message" role="alert">{error}</p>;
  if (!data || !grid) return <p className="settings-description" role="status">Loading…</p>;

  const { totals, current_month: month } = data;
  const allRate = cacheHitRate(totals);
  const monthRate = cacheHitRate(month);
  const { elapsed, daysLeft } = monthElapsed();
  const spent = budget?.spent ?? month.usd;
  const pace = spent > 0 && elapsed > 0 ? spent / elapsed : null;
  const label = monthName.format(new Date(`${data.month}-01T00:00:00Z`));

  return (
    <div className="dashboard">
      <section className="dashboard-card dashboard-budget" aria-label="Monthly budget">
        <div className="dashboard-budget-head">
          <div>
            <span className="dashboard-eyebrow">{label} · UTC</span>
            <strong className="dashboard-budget-spent">{usd(spent)}</strong>
            <small>{budget ? `of ${usd(budget.budget)} monthly budget` : "spent this month"}</small>
          </div>
          {budget
            ? <span className={`dashboard-budget-ratio budget-${budget.level}`}>{Math.round(budget.ratio * 100)}%</span>
            : <button className="settings-secondary" type="button" onClick={onSetBudget}>Set a budget</button>}
        </div>
        {budget && (
          <div className={`budget-bar budget-${budget.level}`} role="meter" aria-label="Monthly budget used"
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(budget.ratio * 100)}>
            <span style={{ width: `${Math.min(100, budget.ratio * 100)}%` }} />
          </div>
        )}
        <div className="dashboard-budget-foot">
          <span>{daysLeft} {daysLeft === 1 ? "day" : "days"} left</span>
          {pace !== null && <span>On pace for {usd(pace)}{budget && pace > budget.budget ? " · over budget" : ""}</span>}
          {budget && budget.budget > spent && <span>{usd(budget.budget - spent)} remaining</span>}
        </div>
      </section>

      <div className="dashboard-stats">
        <Stat label="Input tokens" value={tokens(totals.input_tokens)} title={whole.format(totals.input_tokens)}
          detail={`${tokens(month.input_tokens)} this month`} />
        <Stat label="Output tokens" value={tokens(totals.output_tokens)} title={whole.format(totals.output_tokens)}
          detail={`${tokens(month.output_tokens)} this month`} />
        <Stat label="Cache hit rate" value={allRate === null ? "—" : percent.format(allRate)}
          title={`${whole.format(totals.cached_input_tokens)} of ${whole.format(totals.input_tokens)} input tokens`}
          detail={monthRate === null ? "No input this month" : `${percent.format(monthRate)} this month`} />
        <Stat label="Estimated cost" value={usd(totals.usd)} detail={`${whole.format(totals.responses)} API responses`} />
      </div>

      <section className="dashboard-card" aria-label="Activity">
        <div className="dashboard-card-head">
          <div>
            <h2>Activity</h2>
            <small>{metricText(metric, grid.total)} in the last year</small>
          </div>
          <div className="dashboard-segmented" role="group" aria-label="Activity metric">
            {METRICS.map((item) => (
              <button key={item.id} type="button" aria-pressed={metric === item.id} onClick={() => setMetric(item.id)}>{item.label}</button>
            ))}
          </div>
        </div>
        <div className="activity-scroll" ref={calendar}>
          <div className="activity-calendar"
            style={{ ["--weeks" as string]: grid.weeks.length, ["--cell" as string]: `${cell}px`, ["--activity-gap" as string]: `${gap}px` }} onMouseLeave={() => setHovered(null)}>
            <div className="activity-months" aria-hidden="true">
              {grid.months.map((item) => <span key={item.column} style={{ gridColumnStart: item.column + 1 }}>{item.label}</span>)}
            </div>
            <div className="activity-weekdays" aria-hidden="true">{WEEKDAYS.map((name, index) => <span key={index}>{name}</span>)}</div>
            <div className="activity-grid" role="img" aria-label={`${metricText(metric, grid.total)} across ${grid.activeDays} active days in the last year`}>
              {grid.weeks.flat().map((cell) => cell.future
                ? <span key={cell.date} className="activity-cell is-future" />
                : <span key={cell.date} className={`activity-cell level-${cell.level}`} data-date={cell.date}
                  title={`${metricText(metric, cell.value)} on ${day.format(new Date(`${cell.date}T00:00:00Z`))}`}
                  onMouseEnter={() => setHovered(cell)} />)}
            </div>
          </div>
        </div>
        <div className="activity-foot">
          <span className="activity-detail" aria-live="polite">
            {hovered
              ? `${day.format(new Date(`${hovered.date}T00:00:00Z`))} · ${metricText(metric, hovered.value)}`
              : `${grid.activeDays} active days · Current streak ${grid.currentStreak} · Longest ${grid.longestStreak}`}
          </span>
          <span className="activity-legend" aria-hidden="true">
            Less{[0, 1, 2, 3, 4].map((level) => <span key={level} className={`activity-cell level-${level}`} />)}More
          </span>
        </div>
      </section>

      <section className="dashboard-card" aria-label="Usage by model">
        <div className="dashboard-card-head"><div><h2>By model</h2><small>All time</small></div></div>
        {data.models.length === 0 ? <p className="settings-description">No API usage recorded yet.</p> : (
          <div className="dashboard-table-scroll">
            <table className="dashboard-table">
              <thead><tr><th>Model</th><th>Responses</th><th>Input</th><th>Output</th><th>Cache hit</th><th>Cost</th></tr></thead>
              <tbody>
                {data.models.map((item) => {
                  const rate = cacheHitRate(item);
                  return (
                    <tr key={`${item.provider}/${item.model}`}>
                      <td>{labelFor(item.provider, item.model)}</td>
                      <td>{whole.format(item.responses)}</td>
                      <td title={whole.format(item.input_tokens)}>{tokens(item.input_tokens)}</td>
                      <td title={whole.format(item.output_tokens)}>{tokens(item.output_tokens)}</td>
                      <td>{rate === null ? "—" : percent.format(rate)}</td>
                      <td>{usd(item.usd)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="cost-notes">
        <span>Estimated</span>
        <span>Tokens and cost exclude ChatGPT plan usage</span>
        <span>Tool fees excluded</span>
        <span>Budget uses UTC months</span>
        <span>Activity in {data.timezone}</span>
      </div>
    </div>
  );
}
