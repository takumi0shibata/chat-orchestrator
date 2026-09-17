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
        onApproval={vi.fn()}
      />,
    );
    expect(screen.getByText("変更しました")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Activity"));
    expect(screen.getByText("200 files analyzed")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Stop" }),
    ).not.toBeInTheDocument();
  });
  it("allows a pending MCP approval and a real stop", async () => {
    const approval = vi.fn().mockResolvedValue(undefined);
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
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Allow" }));
    await waitFor(() =>
      expect(approval).toHaveBeenCalledWith("approval_1", true),
    );
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
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
          {
            id: "gpt-5.6-luna",
            label: "GPT-5.6 Luna",
            model: "gpt-5.6-luna",
            efforts: ["low", "medium", "high"],
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
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
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
  expect(screen.queryByText("元ファイルを直接編集")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Message" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add attachments and tools" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Web Search" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), { target: { value: "gpt-5.6-luna" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Reasoning effort" }), { target: { value: "high" } });
  const message = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Analyze the report" } });
  fireEvent.keyDown(message, { key: "Enter", shiftKey: true });
  expect(fetchMock.mock.calls.filter(([url, options]) => url === "/api/runs" && options?.method === "POST")).toHaveLength(0);
  fireEvent.keyDown(message, { key: "Enter" });
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url, options]) => url === "/api/runs" && options?.method === "POST")).toHaveLength(1));
  const sent = fetchMock.mock.calls.find(([url, options]) => url === "/api/runs" && options?.method === "POST");
  expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({ model: "gpt-5.6-luna", reasoning_effort: "high", web_search: true, input: "Analyze the report" });
  expect(screen.getByRole("link", { name: /report.csv/ })).toHaveAttribute(
    "href",
    "/api/conversations/c/download?path=report.csv",
  );
});

it("uses the composer button as the only stop control for an active run", async () => {
  localStorage.setItem("workspace-conversation", "c");
  const activeRun = { ...run, status: "model_wait" };
  const conversation = { id: "c", workspace_id: "w", title: "Active task", updated_at: run.updated_at };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/events?")) return new Response("");
    const body = url === "/api/config"
      ? { providers: [{ id: "openai", label: "OpenAI", enabled: true, models: [{ id: "gpt-5.6-sol", label: "GPT-5.6 Sol", model: "gpt-5.6-sol", efforts: ["medium"] }] }], workspaces: [{ id: "w", label: "Research", path: "/research" }], skills: [], resources: [], mcp_servers: [] }
      : url === "/api/conversations" ? [conversation]
      : url === "/api/conversations/c" ? { ...conversation, runs: [activeRun] }
      : url === "/api/runs/r" ? activeRun : [];
    return new Response(JSON.stringify(body));
  });
  render(<App />);
  const stop = await screen.findByRole("button", { name: "Stop" });
  expect(screen.getAllByText("Waiting for model")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  fireEvent.click(stop);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === "/api/runs/r/stop" && options?.method === "POST")).toBe(true));
});
