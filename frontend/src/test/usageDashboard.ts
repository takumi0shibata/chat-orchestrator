import type { UsageDashboard, UsageTotals } from "../types";

const empty: UsageTotals = {
  responses: 0, input_tokens: 0, cached_input_tokens: 0, cache_write_tokens: 0, output_tokens: 0, usd: 0, runs: 0,
};

/** A dashboard response for the given local day; override fields per test. */
export function usageDashboard(today: string, overrides: Partial<UsageDashboard> = {}): UsageDashboard {
  return {
    currency: "USD", estimated: true, timezone: "UTC", month_timezone: "UTC",
    exclusions: ["tool_fees", "chatgpt_plan_usage"], today, month: today.slice(0, 7), first_run_at: null,
    totals: empty, current_month: empty, models: [], days: [],
    ...overrides,
  };
}
