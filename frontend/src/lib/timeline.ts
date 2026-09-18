import type { AgentEvent } from "../types";

export interface MessageBlock {
  key: string;
  seq: number;
  created_at: string;
  itemId: string;
  round: number;
  content: string;
  progress: boolean;
}

/** Reconstruct messages without ever joining different model responses. */
export function messageBlocks(events: AgentEvent[], status: string): MessageBlock[] {
  const blocks: MessageBlock[] = [];
  let round = 0;
  let boundary = 0;
  const completed = new Map<number, AgentEvent>();
  for (const event of events) {
    if (event.type === "round") {
      round = Number(event.data.number) || round + 1;
      boundary++;
    } else if (event.type === "response") {
      completed.set(Number(event.data.round) || round, event);
      boundary++;
      round++;
    } else if (["command", "tool", "approval"].includes(event.type)) {
      boundary++;
    } else if (event.type === "text_delta") {
      const itemId = String(event.data.item_id || "");
      const messageRound = Number(event.data.round) || round;
      const key = `${messageRound}:${itemId || `anonymous-${boundary}`}`;
      let block = blocks.find((item) => item.key === key);
      if (!block) {
        block = { key, seq: event.seq, created_at: event.created_at, itemId,
          round: messageRound, content: "", progress: false };
        blocks.push(block);
      }
      block.content += String(event.data.text || "");
    }
  }
  for (const block of blocks) {
    const response = completed.get(block.round);
    const finals = response?.data.final_item_ids;
    if (Array.isArray(finals) && finals.includes(block.itemId)) continue;
    block.progress = Array.isArray(finals) || response?.data.continues === true ||
      ["failed", "stopped"].includes(status) ||
      events.some((event) => event.seq > block.seq &&
        (["command", "tool", "approval"].includes(event.type) ||
          (event.type === "round" && Number(event.data.number) > block.round)));
  }
  return blocks;
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
  const tool = [...events].reverse().find((event) => event.type === "tool" &&
    !events.some((other) => other.type === "tool_result" && other.data.id === event.data.id));
  if (tool) return tool.data.type === "web_search_call" ? "Searching the web" :
    `Using ${short(tool.data.server_label || tool.data.name || "external tool")}`;
  const latest = blocks[blocks.length - 1];
  const lastStatus = [...events].reverse().find((event) => event.type === "status");
  if (latest && !latest.progress && (!lastStatus || latest.seq > lastStatus.seq)) return "Writing response";
  const label = short(lastStatus?.data.label);
  if (label && !["Deciding the next action", "次の操作を判断しています", "Running command"].includes(label)) return label;
  return latest ? `Waiting for model · ${short(latest.content)}` : "Waiting for model";
}
