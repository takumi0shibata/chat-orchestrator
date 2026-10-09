import type { AgentEvent } from "../types";

/** Events that represent an operation in Activity, as opposed to model text. */
export const ACTION_TYPES = ["command", "patch", "image_view", "tool", "approval"];

export interface MessageBlock {
  key: string;
  seq: number;
  created_at: string;
  itemId: string;
  round: number;
  content: string;
  progress: boolean;
  final: boolean;
}

export interface ReasoningBlock {
  key: string;
  seq: number;
  lastSeq: number;
  /** Summary parts in index order; each is a separate paragraph from the API. */
  parts: string[];
}

export type ActivityEntry =
  | { kind: "message"; block: MessageBlock }
  | { kind: "reasoning"; block: ReasoningBlock }
  | { kind: "compaction"; seq: number; compaction: Compaction }
  | { kind: "work"; seq: number; actions: AgentEvent[] };

export interface Compaction {
  seq: number;
  /** Context size that triggered compaction, when known. */
  before: number | null;
  /** Input size of the first response after compaction (the compact API's own usage understates it). */
  after: number | null;
  threshold: number | null;
  done: boolean;
}

const TERMINAL_STATUSES = ["completed", "failed", "stopped"];

/** Pair compaction start and finish events; older runs only have the finish event. */
export function compactions(events: AgentEvent[]): Compaction[] {
  const result: Compaction[] = [];
  let awaitingSize: Compaction | null = null;
  for (const event of events) {
    const threshold = Number(event.data.threshold) || null;
    if (event.type === "compaction_start") {
      result.push({ seq: event.seq, before: Number(event.data.tokens) || null, after: null, threshold, done: false });
    } else if (event.type === "compaction") {
      const usage = (event.data.usage ?? {}) as Record<string, unknown>;
      let item = result.find((candidate) => !candidate.done);
      if (!item) {
        item = { seq: event.seq, before: Number(event.data.tokens_before) || Number(usage.input_tokens) || null,
          after: null, threshold, done: false };
        result.push(item);
      }
      item.done = true;
      item.threshold = item.threshold ?? threshold;
      awaitingSize = item;
    } else if (event.type === "response" && awaitingSize) {
      const usage = (event.data.usage ?? {}) as Record<string, unknown>;
      awaitingSize.after = Number(usage.input_tokens) || null;
      awaitingSize = null;
    }
  }
  return result;
}

/** Group reasoning summary deltas by response round and reasoning item. */
export function reasoningBlocks(events: AgentEvent[]): ReasoningBlock[] {
  const blocks = new Map<string, ReasoningBlock>();
  let round = 1;
  for (const event of events) {
    if (event.type === "round") round = Number(event.data.number) || round;
    if (event.type !== "reasoning_delta") continue;
    const key = `${Number(event.data.round) || round}:${String(event.data.item_id || "")}`;
    let block = blocks.get(key);
    if (!block) {
      block = { key, seq: event.seq, lastSeq: event.seq, parts: [] };
      blocks.set(key, block);
    }
    const index = Math.max(0, Number(event.data.summary_index) || 0);
    while (block.parts.length <= index) block.parts.push("");
    block.parts[index] += String(event.data.text || "");
    block.lastSeq = event.seq;
  }
  return [...blocks.values()].map((block) => ({ ...block, parts: block.parts.filter((part) => part.trim()) }))
    .filter((block) => block.parts.length > 0);
}

/** Summaries usually open with a bold heading; it labels the collapsed row. */
export function reasoningTitle(part: string): string {
  const heading = part.trim().match(/^\*\*(.+?)\*\*/);
  return (heading ? heading[1] : part).replace(/\s+/g, " ").trim().slice(0, 120);
}

/** A summary is still streaming until the model emits anything after it. */
export function reasoningActive(block: ReasoningBlock, events: AgentEvent[], status: string): boolean {
  if (["completed", "failed", "stopped"].includes(status)) return false;
  return !events.some((event) => event.seq > block.lastSeq &&
    ["text_delta", ...ACTION_TYPES, "response", "round", "reasoning_delta"].includes(event.type));
}

/** A phase is available before text deltas; response IDs cover older events. */
export function finalAnswerStart(events: AgentEvent[]): number | null {
  const marker = events.find((event) =>
    (event.type === "message_phase" && event.data.phase === "final_answer") ||
    (event.type === "response" && Array.isArray(event.data.final_item_ids) &&
      event.data.final_item_ids.length > 0));
  return marker?.seq ?? null;
}

/** Reconstruct messages without ever joining different model responses. */
export function messageBlocks(events: AgentEvent[], status: string): MessageBlock[] {
  const blocks: MessageBlock[] = [];
  let round = 1;
  let boundary = 0;
  const completed = new Map<number, AgentEvent>();
  const phases = new Map<string, string>();
  for (const event of events) {
    if (event.type === "round") {
      round = Number(event.data.number) || round + 1;
      boundary++;
    } else if (event.type === "response") {
      completed.set(Number(event.data.round) || round, event);
      boundary++;
      round++;
    } else if (event.type === "message_phase") {
      phases.set(`${Number(event.data.round) || round}:${String(event.data.item_id || "")}`,
        String(event.data.phase || ""));
    } else if (ACTION_TYPES.includes(event.type)) {
      boundary++;
    } else if (event.type === "text_delta") {
      const itemId = String(event.data.item_id || "");
      const messageRound = Number(event.data.round) || round;
      const key = `${messageRound}:${itemId || `anonymous-${boundary}`}`;
      let block = blocks.find((item) => item.key === key);
      if (!block) {
        block = { key, seq: event.seq, created_at: event.created_at, itemId,
          round: messageRound, content: "", progress: false, final: false };
        blocks.push(block);
      }
      block.content += String(event.data.text || "");
    }
  }
  for (const block of blocks) {
    const phase = phases.get(`${block.round}:${block.itemId}`);
    if (phase === "final_answer") {
      block.final = true;
      continue;
    }
    if (phase === "commentary") {
      block.progress = true;
      continue;
    }
    const response = completed.get(block.round);
    const finals = response?.data.final_item_ids;
    if (Array.isArray(finals) && finals.includes(block.itemId)) {
      block.final = true;
      continue;
    }
    block.progress = Array.isArray(finals) || response?.data.continues === true ||
      ["failed", "stopped"].includes(status) ||
      events.some((event) => event.seq > block.seq &&
        (ACTION_TYPES.includes(event.type) ||
          (event.type === "message_phase" && event.data.phase === "final_answer") ||
          (event.type === "round" && Number(event.data.number) > block.round)));
  }
  return blocks;
}

/** Group adjacent operations between natural-language progress reports. */
export function activityEntries(events: AgentEvent[], blocks: MessageBlock[], status: string,
  reasoning: ReasoningBlock[] = []): ActivityEntry[] {
  const provisional = !["completed", "failed", "stopped"].includes(status);
  const items = [
    ...compactions(events).map((compaction) => ({ seq: compaction.seq, kind: "compaction" as const, compaction })),
    ...reasoning.map((block) => ({ seq: block.seq, kind: "reasoning" as const, block })),
    ...blocks.filter((block) => block.progress || (provisional && !block.final)).map((block) =>
      ({ seq: block.seq, kind: "message" as const, block })),
    ...events.filter((event) => ACTION_TYPES.includes(event.type)).map((event) =>
      ({ seq: event.seq, kind: "action" as const, event })),
  ].sort((a, b) => a.seq - b.seq);
  const entries: ActivityEntry[] = [];
  for (const item of items) {
    if (item.kind === "compaction") {
      entries.push({ kind: "compaction", seq: item.seq, compaction: item.compaction });
      continue;
    }
    if (item.kind === "message" || item.kind === "reasoning") {
      entries.push(item.kind === "message" ? { kind: "message", block: item.block } : { kind: "reasoning", block: item.block });
      continue;
    }
    const last = entries[entries.length - 1];
    if (last?.kind === "work") last.actions.push(item.event);
    else entries.push({ kind: "work", seq: item.seq, actions: [item.event] });
  }
  return entries;
}

const short = (value: unknown) => String(value || "").replace(/\s+/g, " ").trim().slice(0, 120);

/** Only unmatched operations can be shown as currently running. */
export function activityLabel(events: AgentEvent[], status: string, blocks: MessageBlock[]): string {
  if (["completed", "failed", "stopped"].includes(status)) return "Activity";
  const approval = [...events].reverse().find((event) => event.type === "approval" &&
    !events.some((other) => other.type === "approval_resolved" && other.data.request_id === event.data.id));
  if (approval) return `Approval needed: ${short(approval.data.name)}`;
  const command = [...events].reverse().find((event) => event.type === "command" &&
    !events.some((other) => other.type === "command_done" && other.data.call_id === event.data.call_id && other.data.index === event.data.index));
  if (command) return `Running: ${short(command.data.command)}`;
  const patch = [...events].reverse().find((event) => event.type === "patch" &&
    !events.some((other) => other.type === "patch_done" && other.data.call_id === event.data.call_id));
  if (patch) return `Editing: ${short(patch.data.path)}`;
  const image = [...events].reverse().find((event) => event.type === "image_view" &&
    !events.some((other) => other.type === "image_view_done" && other.data.call_id === event.data.call_id));
  if (image) return `Viewing: ${short(image.data.path)}`;
  const tool = [...events].reverse().find((event) => event.type === "tool" &&
    !events.some((other) => other.type === "tool_result" && other.data.id === event.data.id));
  if (tool) return tool.data.type === "web_search_call" ? "Searching the web" :
    `Using ${short(tool.data.server_label || tool.data.name || "external tool")}`;
  if (compactions(events).some((item) => !item.done)) return "Compacting context";
  const reasoning = reasoningBlocks(events);
  const thinking = reasoning[reasoning.length - 1];
  if (thinking && reasoningActive(thinking, events, status)) {
    return `Thinking · ${reasoningTitle(thinking.parts[thinking.parts.length - 1])}`;
  }
  const latest = blocks[blocks.length - 1];
  const lastStatus = [...events].reverse().find((event) => event.type === "status");
  if (latest && !latest.progress && (!lastStatus || latest.seq > lastStatus.seq)) return "Writing response";
  const label = short(lastStatus?.data.label);
  if (label && !["Deciding the next action", "次の操作を判断しています", "Running command"].includes(label)) return label;
  return latest ? `Waiting for model · ${short(latest.content)}` : "Waiting for model";
}

export interface ContextUsage {
  /** Tokens the next request starts from; null right after compaction until a response reports usage. */
  tokens: number | null;
  compacted: boolean;
  /** A compaction request is in flight in the latest run. */
  compacting: boolean;
}

/** Latest context size across a conversation's runs, given in creation order. */
export function contextUsage(timelines: AgentEvent[][]): ContextUsage | null {
  let usage = null as ContextUsage | null;
  for (const events of timelines) {
    for (const event of events) {
      if (event.type === "compaction_start") {
        usage = { tokens: usage?.tokens ?? (Number(event.data.tokens) || null), compacted: usage?.compacted ?? false, compacting: true };
      } else if (event.type === "compaction") {
        usage = { tokens: null, compacted: true, compacting: false };
      } else if (usage?.compacting && (event.type === "error" ||
        (event.type === "status" && TERMINAL_STATUSES.includes(String(event.data.status))))) {
        usage = { ...usage, compacting: false };
      } else if (event.type === "response") {
        const data = (event.data.usage ?? {}) as Record<string, unknown>;
        const tokens = (Number(data.input_tokens) || 0) + (Number(data.output_tokens) || 0);
        if (tokens > 0) usage = { tokens, compacted: usage?.compacted ?? false, compacting: false };
      }
    }
  }
  return usage;
}
