import { describe, expect, it } from "vitest";
import {
  activityEntries, activityLabel, compactions, contextUsage, finalAnswerStart, messageBlocks, reasoningActive, reasoningBlocks, reasoningTitle,
} from "./timeline";
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
  it("identifies phased final text before the response completes, including a failed run", () => {
    const events = [e(1, "message_phase", { item_id: "before", round: 1, phase: "commentary" }),
      e(2, "text_delta", { item_id: "before", round: 1, text: "Checking" }),
      e(3, "message_phase", { item_id: "final", round: 1, phase: "final_answer" }),
      e(4, "text_delta", { item_id: "final", round: 1, text: "Done" })];
    expect(finalAnswerStart(events)).toBe(3);
    expect(messageBlocks(events, "model_wait").map((block) => block.progress)).toEqual([true, false]);
    expect(messageBlocks(events, "failed").map((block) => block.progress)).toEqual([true, false]);
  });
  it("uses completed response IDs when no phase is available", () => {
    const events = [e(1, "text_delta", { item_id: "final", text: "Done" }),
      e(2, "response", { final_item_ids: ["final"] })];
    expect(finalAnswerStart(events.slice(0, 1))).toBeNull();
    expect(finalAnswerStart(events)).toBe(2);
  });
});

it("groups adjacent work by progress reports while omitting system events", () => {
  const events = [e(1, "status", { label: "Preparing" }),
    e(2, "text_delta", { item_id: "a", text: "First report" }),
    e(3, "command", { call_id: "c1", index: 0 }),
    e(4, "command_done", { call_id: "c1", index: 0 }),
    e(5, "round", { number: 2 }), e(6, "command", { call_id: "c2", index: 0 }),
    e(7, "tool", { id: "web", type: "web_search_call" }),
    e(8, "text_delta", { item_id: "b", text: "Second report" }),
    e(9, "tool", { id: "mcp", type: "mcp_call" })];
  const entries = activityEntries(events, messageBlocks(events, "model_wait"), "model_wait");
  expect(entries.map((entry) => entry.kind === "message" ? entry.block.content :
    entry.kind === "work" ? entry.actions.map((action) => action.seq) : []))
    .toEqual(["First report", [3, 6, 7], "Second report", [9]]);
});

describe("reasoning summaries", () => {
  const events = [e(1, "round", { number: 1 }),
    e(2, "reasoning_delta", { item_id: "rs", round: 1, summary_index: 0, text: "**Inspect" }),
    e(3, "reasoning_delta", { item_id: "rs", round: 1, summary_index: 0, text: " files**\n\nLook first." }),
    e(4, "reasoning_delta", { item_id: "rs", round: 1, summary_index: 1, text: "**Run tests**" }),
    e(5, "command", { call_id: "c1", index: 0, command: "pytest" }),
    e(6, "response", { round: 1, continues: true, final_item_ids: [] }),
    e(7, "round", { number: 2 }),
    e(8, "reasoning_delta", { item_id: "rs", round: 2, summary_index: 0, text: "**Summarize**" })];
  it("joins deltas per part and separates rounds that reuse an item ID", () => {
    expect(reasoningBlocks(events).map((block) => block.parts)).toEqual([
      ["**Inspect files**\n\nLook first.", "**Run tests**"], ["**Summarize**"],
    ]);
    expect(reasoningTitle("**Inspect files**\n\nLook first.")).toBe("Inspect files");
    expect(reasoningTitle("No heading here")).toBe("No heading here");
  });
  it("places summaries before the work they precede and tracks streaming", () => {
    const blocks = reasoningBlocks(events);
    const entries = activityEntries(events, messageBlocks(events, "model_wait"), "model_wait", blocks);
    expect(entries.map((entry) => entry.kind)).toEqual(["reasoning", "work", "reasoning"]);
    expect(blocks.map((block) => reasoningActive(block, events, "model_wait"))).toEqual([false, true]);
    expect(reasoningActive(blocks[1], events, "completed")).toBe(false);
    const finished = [...events, e(9, "command_done", { call_id: "c1", index: 0 })];
    expect(activityLabel(finished, "model_wait", [])).toBe("Thinking · Summarize");
  });
});

describe("current activity", () => {
  it("reports an unfinished image view", () => {
    const events = [e(1, "image_view", { call_id: "i", path: "plot.png" })];
    expect(activityLabel(events, "command_running", [])).toBe("Viewing: plot.png");
    expect(activityLabel([...events, e(2, "image_view_done", { call_id: "i" })], "model_wait", [])).toBe("Waiting for model");
  });
  it("reports an unfinished file edit", () => {
    const events = [e(1, "patch", { call_id: "p", path: "src/app.py" })];
    expect(activityLabel(events, "command_running", [])).toBe("Editing: src/app.py");
    expect(activityLabel([...events, e(2, "patch_done", { call_id: "p" })], "model_wait", [])).toBe("Waiting for model");
    expect(activityEntries(events, [], "command_running").map((entry) => entry.kind)).toEqual(["work"]);
  });
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

describe("context usage", () => {
  it("uses the latest response across runs and resets after compaction", () => {
    const first = [e(1, "response", { usage: { input_tokens: 1000, output_tokens: 200 } })];
    const second = [e(1, "response", { usage: { input_tokens: 5000, output_tokens: 300 } })];
    expect(contextUsage([])).toBeNull();
    expect(contextUsage([first, second])).toEqual({ tokens: 5300, compacted: false, compacting: false });
    const compacted = [...second, e(2, "compaction", {})];
    expect(contextUsage([first, compacted])).toEqual({ tokens: null, compacted: true, compacting: false });
    expect(contextUsage([first, [...compacted, e(3, "response", { usage: { input_tokens: 800, output_tokens: 20 } })]]))
      .toEqual({ tokens: 820, compacted: true, compacting: false });
  });
});

describe("auto-compaction", () => {
  const start = e(2, "compaction_start", { tokens: 260_000, threshold: 258_000 });
  const done = e(3, "compaction", { usage: { input_tokens: 260_000, output_tokens: 14_000 }, tokens_before: 260_000, threshold: 258_000 });
  it("pairs start and finish and shows it in Activity", () => {
    expect(compactions([start])).toEqual([{ seq: 2, before: 260_000, after: null, threshold: 258_000, done: false }]);
    expect(compactions([start, done])).toEqual([{ seq: 2, before: 260_000, after: null, threshold: 258_000, done: true }]);
    const next = e(4, "response", { usage: { input_tokens: 21_000, output_tokens: 500 } });
    expect(compactions([start, done, next])[0].after).toBe(21_000);
    // Runs recorded before the start event existed still show the finished compaction.
    expect(compactions([done, next])[0]).toMatchObject({ seq: 3, before: 260_000, after: 21_000, done: true });
    expect(activityLabel([start], "model_wait", [])).toBe("Compacting context");
    const entries = activityEntries([e(1, "command", { call_id: "c", index: 0 }), start, done], [], "model_wait");
    expect(entries.map((entry) => entry.kind)).toEqual(["work", "compaction"]);
  });
  it("marks the ring as compacting until the compaction finishes or the run ends", () => {
    const before = [e(1, "response", { usage: { input_tokens: 259_000, output_tokens: 1000 } })];
    expect(contextUsage([[...before, start]])).toEqual({ tokens: 260_000, compacted: false, compacting: true });
    expect(contextUsage([[...before, start, done]])?.compacting).toBe(false);
    expect(contextUsage([[...before, start, e(4, "status", { status: "failed" })]])?.compacting).toBe(false);
  });
});
