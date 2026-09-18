import { describe, expect, it } from "vitest";
import { activityLabel, messageBlocks } from "./timeline";
import type { AgentEvent } from "../types";
const e = (seq: number, type: string, data: Record<string, unknown> = {}): AgentEvent =>
  ({ run_id: "r", seq, type, data, created_at: "2026-09-18T00:00:00Z" });

describe("message reconstruction", () => {
  it("separates rounds and message IDs while preserving streamed Markdown", () => {
    const events = [e(1, "round", { number: 1 }), e(2, "text_delta", { item_id: "a", text: "Inspect" }),
      e(3, "response", { round: 1, continues: true, final_item_ids: [] }),
      e(4, "round", { number: 2 }), e(5, "text_delta", { item_id: "b", text: "**Re" }),
      e(6, "text_delta", { item_id: "b", text: "sult**" }),
      e(7, "text_delta", { item_id: "c", text: "Another message" }),
      e(8, "response", { round: 2, continues: false, final_item_ids: ["b", "c"] })];
    expect(messageBlocks(events, "completed").map((b) => [b.content, b.progress])).toEqual([
      ["Inspect", true], ["**Result**", false], ["Another message", false],
    ]);
  });
  it("streams provisionally, then moves commentary into history", () => {
    const start = [e(1, "text_delta", { item_id: "a", text: "Checking" })];
    expect(messageBlocks(start, "model_wait")[0].progress).toBe(false);
    expect(messageBlocks([...start, e(2, "command", { command: "ls" })], "command_running")[0].progress).toBe(true);
    for (const status of ["failed", "stopped"]) expect(messageBlocks(start, status)[0].progress).toBe(true);
  });
  it("restores legacy rounds and preserves ambiguous old content", () => {
    const events = [e(1, "round", { number: 1 }), e(2, "text_delta", { text: "Before" }),
      e(3, "response"), e(4, "round", { number: 2 }), e(5, "text_delta", { text: "Answer" }), e(6, "response")];
    expect(messageBlocks(events, "completed").map((b) => b.progress)).toEqual([true, false]);
    expect(messageBlocks([e(1, "text_delta", { text: "Old answer" })], "completed")[0].progress).toBe(false);
  });
  it("moves built-in tool commentary into Activity when final IDs arrive", () => {
    const events = [e(1, "text_delta", { item_id: "before", text: "Searching" }),
      e(2, "tool", { id: "web", type: "web_search_call" }),
      e(3, "tool_result", { id: "web" }), e(4, "text_delta", { item_id: "final", text: "Found" }),
      e(5, "response", { final_item_ids: ["final"], continues: false })];
    expect(messageBlocks(events, "completed").map((b) => b.progress)).toEqual([true, false]);
  });
});

describe("current activity", () => {
  it("does not report finished commands or tools as running", () => {
    const events = [e(1, "status", { label: "Deciding the next action" }),
      e(2, "command", { call_id: "c", index: 0, command: "python review.py" })];
    expect(activityLabel(events, "command_running", [])).toBe("Running: python review.py");
    events.push(e(3, "command_done", { call_id: "c", index: 0 }));
    expect(activityLabel(events, "model_wait", [])).toBe("Waiting for model");
    events.push(e(4, "tool", { id: "web", type: "web_search_call" }));
    expect(activityLabel(events, "model_wait", [])).toBe("Searching the web");
    events.push(e(5, "tool_result", { id: "web" }));
    expect(activityLabel(events, "model_wait", [])).toBe("Waiting for model");
  });
  it("prioritizes approval and retains context while waiting", () => {
    const events = [e(1, "text_delta", { text: "Inspect files" }), e(2, "command", { call_id: "c", index: 0 }),
      e(3, "command_done", { call_id: "c", index: 0 }), e(4, "status", { label: "Deciding the next action" })];
    expect(activityLabel(events, "model_wait", messageBlocks(events, "model_wait"))).toBe("Waiting for model · Inspect files");
    events.push(e(5, "approval", { id: "a", name: "search" }));
    expect(activityLabel(events, "approval_wait", [])).toBe("Approval needed: search");
    expect(activityLabel(events, "completed", [])).toBe("Activity");
  });
});
