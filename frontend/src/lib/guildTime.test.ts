import { expect, it } from "vitest";
import { guildPeriod, nextGuildPeriodDelay } from "./guildTime";

it.each([
  [4, 59, "night"], [5, 0, "morning"], [10, 59, "morning"],
  [11, 0, "day"], [16, 59, "day"], [17, 0, "evening"],
  [19, 59, "evening"], [20, 0, "night"], [0, 0, "night"],
] as const)("uses local time at %s:%s", (hour, minute, expected) => {
  expect(guildPeriod(new Date(2026, 9, 9, hour, minute))).toBe(expected);
});

it("schedules the next boundary precisely, including midnight and a month change", () => {
  expect(nextGuildPeriodDelay(new Date(2026, 9, 9, 10, 59, 59, 999))).toBe(1);
  expect(nextGuildPeriodDelay(new Date(2026, 9, 9, 11))).toBe(6 * 60 * 60 * 1000);
  expect(nextGuildPeriodDelay(new Date(2026, 9, 31, 23))).toBe(6 * 60 * 60 * 1000);
  expect(nextGuildPeriodDelay(new Date(2026, 9, 9, 0))).toBe(5 * 60 * 60 * 1000);
});
