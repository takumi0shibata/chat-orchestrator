import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { App, RunView } from "./App";
import type { AgentEvent, Run } from "./types";

const run: Run = {
  id: "r",
  conversation_id: "c",
  status: "completed",
  created_at: "2026-09-17T00:00:00Z",
  updated_at: "2026-09-17T00:00:05Z",
  request: {
    conversation_id: "c",
    provider: "openai",
    model: "gpt-5.6-sol",
    reasoning_effort: "medium",
    input: "ファイルを編集",
    attachment_ids: [],
    direct_attachment_ids: [],
    skill_ids: [],
    resource_ids: [],
    mcp_ids: [],
    web_search: false,
  },
};
const event = (
  seq: number,
  type: string,
  data: Record<string, unknown>,
): AgentEvent => ({
  run_id: "r",
  seq,
  type,
  data,
  created_at: "2026-09-17T00:00:00Z",
});

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("Run timeline", () => {
  it("keeps command output, errors and status after completion", () => {
    render(
      <RunView
        run={run}
        timeline={[
          event(1, "command", {
            call_id: "call",
            index: 0,
            command: "python analyze.py",
          }),
          event(2, "command_output", {
            call_id: "call",
            index: 0,
            channel: "stdout",
            text: "200 files analyzed",
          }),
          event(3, "command_done", {
            call_id: "call",
            index: 0,
            elapsed: 2,
            outcome: { type: "exit", exit_code: 0 },
          }),
          event(4, "text_delta", { text: "変更しました" }),
          event(5, "status", {
            status: "completed",
            label: "作業が完了しました",
          }),
        ]}
        onStop={vi.fn()}
        onApproval={vi.fn()}
      />,
    );
    expect(screen.getByText("変更しました")).toBeInTheDocument();
    fireEvent.click(screen.getByText("実行履歴"));
    expect(screen.getByText("200 files analyzed")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("作業が完了しました");
    expect(
      screen.queryByRole("button", { name: "停止" }),
    ).not.toBeInTheDocument();
  });
  it("allows a pending MCP approval and a real stop", async () => {
    const approval = vi.fn().mockResolvedValue(undefined),
      stop = vi.fn();
    render(
      <RunView
        run={{ ...run, status: "approval_wait" }}
        timeline={[
          event(1, "approval", {
            id: "approval_1",
            name: "search",
            server_label: "papers",
            arguments: "{}",
          }),
        ]}
        onApproval={approval}
        onStop={stop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "許可" }));
    await waitFor(() =>
      expect(approval).toHaveBeenCalledWith("approval_1", true),
    );
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    expect(stop).toHaveBeenCalledOnce();
  });
});

it("restores selected conversation and replays persistent events on reload", async () => {
  localStorage.setItem("workspace-conversation", "c");
  const config = {
    providers: [
      {
        id: "openai",
        label: "OpenAI",
        enabled: true,
        models: [
          {
            id: "gpt-5.6-sol",
            label: "GPT-5.6 Sol",
            model: "gpt-5.6-sol",
            efforts: ["medium"],
          },
        ],
      },
    ],
    workspaces: [{ id: "w", label: "Research", path: "/research" }],
    skills: [],
    resources: [],
    mcp_servers: [],
  };
  const conversation = {
    id: "c",
    workspace_id: "w",
    title: "Existing task",
    updated_at: run.updated_at,
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/events?"))
      return new Response(
        JSON.stringify(event(1, "text_delta", { text: "保存された回答" })) +
          "\n" +
          JSON.stringify(
            event(2, "status", {
              status: "completed",
              label: "作業が完了しました",
            }),
          ) +
          "\n",
      );
    let body: unknown = {};
    if (url === "/api/config") body = config;
    else if (url === "/api/conversations") body = [conversation];
    else if (url === "/api/conversations/c")
      body = { ...conversation, runs: [run] };
    else if (url.startsWith("/api/conversations/c/files"))
      body = [
        { name: "report.csv", path: "report.csv", directory: false, size: 100 },
      ];
    else if (url === "/api/runs/r") body = run;
    return new Response(JSON.stringify(body));
  });
  render(<App />);
  await screen.findByText("保存された回答");
  expect(screen.getByText("元ファイルを直接編集")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /report.csv/ })).toHaveAttribute(
    "href",
    "/api/conversations/c/download?path=report.csv",
  );
});
