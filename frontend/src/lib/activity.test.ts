import { expect, it } from "vitest";
import { activityCellSize, activityGrid } from "./activity";
import type { UsageDay } from "../types";

const day = (date: string, runs: number, tokens = 0, usd = 0): UsageDay => ({
  date, runs, input_tokens: tokens, cached_input_tokens: 0, output_tokens: 0, usd,
});

it("ends with the week containing today and starts each column on Sunday", () => {
  // 2026-10-19 is a Monday.
  const grid = activityGrid("2026-10-19", [], "runs");
  expect(grid.weeks).toHaveLength(53);
  expect(grid.weeks[0][0].date).toBe("2025-10-19");
  expect(new Date(`${grid.weeks[0][0].date}T00:00:00Z`).getUTCDay()).toBe(0);
  const last = grid.weeks[52];
  expect(last.map((cell) => cell.future)).toEqual([false, false, true, true, true, true, true]);
  expect(last[1].date).toBe("2026-10-19");
});

it("scales levels to the busiest day and switches metrics", () => {
  const days = [day("2026-10-17", 1, 100), day("2026-10-18", 4, 50, 2), day("2026-10-19", 2, 0, 1)];
  const runs = activityGrid("2026-10-19", days, "runs").weeks.flat();
  expect(Object.fromEntries(runs.filter((cell) => cell.value).map((cell) => [cell.date, cell.level]))).toEqual({
    "2026-10-17": 1, "2026-10-18": 4, "2026-10-19": 2,
  });
  const tokens = activityGrid("2026-10-19", days, "tokens");
  expect(tokens.total).toBe(150);
  expect(tokens.weeks.flat().find((cell) => cell.date === "2026-10-17")?.level).toBe(4);
  expect(activityGrid("2026-10-19", days, "cost").activeDays).toBe(2);
});

it("counts streaks, keeping one that ran through yesterday", () => {
  const days = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-10-17", "2026-10-18"].map((date) => day(date, 1));
  const grid = activityGrid("2026-10-19", days, "runs");
  expect(grid.currentStreak).toBe(2);
  expect(grid.longestStreak).toBe(3);
  expect(activityGrid("2026-10-20", days, "runs").currentStreak).toBe(0);
});

it("labels months at the column holding their first day", () => {
  // Nov 1, 2025 (a Saturday) falls in column 1, leaving no room for the leading "Oct".
  const { months } = activityGrid("2026-10-19", [], "runs");
  expect(months[0]).toEqual({ column: 1, label: "Nov" });
  expect(months.map((month) => month.label)).toEqual(["Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]);
  // With the first of the next month further away, the leading month keeps its label.
  expect(activityGrid("2026-09-06", [], "runs").months.slice(0, 2)).toEqual([
    { column: 0, label: "Sep" }, { column: 3, label: "Oct" },
  ]);
});

it("sizes calendar cells in whole pixels that fit the available width", () => {
  const span = (width: number) => {
    const { cell, gap } = activityCellSize(width, 53);
    return 28 + 53 * cell + 52 * gap;
  };
  // A settings-width card: 10px cells need the tighter gap to fit without scrolling.
  expect(activityCellSize(663, 53)).toEqual({ cell: 10, gap: 2 });
  expect(span(663)).toBeLessThanOrEqual(663);
  // Wide cards keep the roomier gap; very wide ones stop growing.
  expect(activityCellSize(900, 53)).toEqual({ cell: 13, gap: 3 });
  expect(activityCellSize(2000, 53)).toEqual({ cell: 15, gap: 3 });
  // Narrow screens keep a minimum size and scroll instead.
  expect(activityCellSize(300, 53)).toEqual({ cell: 8, gap: 2 });
});
