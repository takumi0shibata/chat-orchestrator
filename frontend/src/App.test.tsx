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
  let configCalls = 0;
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
    if (url === "/api/config") {
      configCalls += 1;
      body = configCalls === 1
        ? config
        : { ...config, skills: [{ id: "academic-writing", label: "academic-writing", name: "academic-writing", description: "Review drafts" }] };
    }
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
  fireEvent.click(await screen.findByRole("button", { name: "academic-writing" }));
  fireEvent.click(screen.getByRole("button", { name: "Web Search" }));
  fireEvent.click(screen.getByRole("button", { name: "Add attachments and tools" }));
  expect(screen.getByRole("button", { name: "Remove academic-writing" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove Web Search" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove Web Search" }));
  expect(screen.queryByRole("button", { name: "Remove Web Search" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add attachments and tools" }));
  fireEvent.click(screen.getByRole("button", { name: "Web Search" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Model" }), { target: { value: "gpt-5.6-luna" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Reasoning effort" }), { target: { value: "high" } });
  const message = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Analyze the report" } });
  fireEvent.keyDown(message, { key: "Enter", shiftKey: true });
  expect(fetchMock.mock.calls.filter(([url, options]) => url === "/api/runs" && options?.method === "POST")).toHaveLength(0);
  fireEvent.keyDown(message, { key: "Enter" });
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url, options]) => url === "/api/runs" && options?.method === "POST")).toHaveLength(1));
  const sent = fetchMock.mock.calls.find(([url, options]) => url === "/api/runs" && options?.method === "POST");
  expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({ model: "gpt-5.6-luna", reasoning_effort: "high", web_search: true, skill_ids: ["academic-writing"], input: "Analyze the report" });
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
  const { container } = render(<App />);
  const stop = await screen.findByRole("button", { name: "Stop" });
  expect(screen.getAllByText("Waiting for model")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  fireEvent.dragEnter(container.querySelector(".main")!, {
    dataTransfer: { types: ["Files"], files: [new File(["x"], "x.txt")], items: [] },
  });
  expect(screen.queryByText("Drop files to attach")).not.toBeInTheDocument();
  fireEvent.click(stop);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === "/api/runs/r/stop" && options?.method === "POST")).toBe(true));
});

it("moves provisional text to expandable Activity and keeps the final Markdown separate", () => {
  const initial = [event(1, "round", { number: 1 }), event(2, "text_delta", { item_id: "a", text: "Checking files" })];
  const { container, rerender } = render(<RunView run={{ ...run, status: "model_wait" }} timeline={initial} onApproval={vi.fn()} />);
  expect(container.querySelector(".answer-block")).toHaveTextContent("Checking files");
  const timeline = [...initial, event(3, "response", { round: 1, continues: true, final_item_ids: [] }),
    event(4, "round", { number: 2 }), event(5, "text_delta", { item_id: "b", text: "**Final result**" }),
    event(6, "response", { round: 2, final_item_ids: ["b"], continues: false })];
  rerender(<RunView run={run} timeline={timeline} onApproval={vi.fn()} />);
  expect(container.querySelectorAll(".answer-block")).toHaveLength(1);
  expect(container.querySelector(".answer-block strong")).toHaveTextContent("Final result");
  expect(container.querySelector(".activity-message")).toHaveTextContent("Checking files");
  fireEvent.click(screen.getByText("Activity"));
  expect(container.querySelector("details")).toHaveAttribute("open");
});

it("searches with debounce, ignores stale responses, preserves the open chat, and rolls back failed pinning", async () => {
  const c = { id: "c", title: "Current chat", workspace_id: "w", updated_at: run.updated_at, pinned: false };
  const other = { ...c, id: "other", title: "Matched by body" };
  localStorage.setItem("workspace-conversation", "c");
  let finishOld: ((response: Response) => void) | undefined;
  let failPin = false;
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    let body: unknown = {};
    if (url === "/api/config") body = { providers: [], workspaces: [{ id: "w", label: "Work" }], skills: [], resources: [], mcp_servers: [] };
    else if (url === "/api/conversations") body = [c, other];
    else if (url === "/api/conversations?q=old") return new Promise<Response>((resolve) => { finishOld = resolve; });
    else if (url === "/api/conversations?q=new") body = [other];
    else if (url === "/api/conversations/c" && options?.method === "PATCH") {
      if (failPin) return new Response(JSON.stringify({ detail: "Pin failed" }), { status: 500 });
      body = { ...c, pinned: true };
    }
    else if (url === "/api/conversations/c") body = { ...c, runs: [] };
    else if (url.includes("/files")) body = [];
    return new Response(JSON.stringify(body));
  });
  render(<App />);
  await screen.findByRole("button", { name: "Current chat" });
  await screen.findByRole("textbox", { name: "Message" });
  expect(screen.queryByRole("heading", { name: "Current chat" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pin Current chat" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Unpin Current chat" })).toBeEnabled());
  failPin = true;
  fireEvent.click(screen.getByRole("button", { name: "Unpin Current chat" }));
  await screen.findByText(/Pin failed/);
  expect(screen.getByRole("button", { name: "Unpin Current chat" })).toBeInTheDocument();
  const search = screen.getByRole("searchbox", { name: "Search history" });
  fireEvent.change(search, { target: { value: "old" } });
  expect(fetchMock.mock.calls.some(([url]) => url === "/api/conversations?q=old")).toBe(false);
  await waitFor(() => expect(finishOld).toBeDefined());
  fireEvent.change(search, { target: { value: "new" } });
  await screen.findByRole("button", { name: "Matched by body" });
  finishOld!(new Response(JSON.stringify([c])));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Current chat" })).not.toBeInTheDocument());
  expect(localStorage.getItem("workspace-conversation")).toBe("c");
  expect(screen.getByRole("textbox", { name: "Message" })).toBeInTheDocument();
  fireEvent.change(search, { target: { value: "" } });
  await screen.findByRole("button", { name: "Current chat" });
});

it("opens and closes Files from the same panel icon even before selecting a chat", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify(
    String(input) === "/api/config"
      ? { providers: [], workspaces: [], skills: [], resources: [], mcp_servers: [] }
      : [],
  )));
  const { container } = render(<App />);
  const toggle = screen.getByRole("button", { name: /files panel/ });
  expect(toggle).toHaveAttribute("aria-controls", "files-panel");
  expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  expect(container.querySelector(".composer .panel-toggle")).toBeNull();
  if (toggle.getAttribute("aria-expanded") === "true") fireEvent.click(toggle);
  expect(toggle).toHaveAccessibleName("Show files panel");
  fireEvent.click(toggle);
  expect(screen.getByRole("button", { name: "Hide files panel" })).toBe(toggle);
  expect(container.querySelector("#files-panel")).toHaveClass("is-open");
  fireEvent.keyDown(container.querySelector("#files-panel")!, { key: "Escape" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
  fireEvent.click(toggle);
  fireEvent.click(toggle);
  expect(container.querySelector("#files-panel")).not.toHaveClass("is-open");
  await waitFor(() => expect(screen.getByText("Explore, analyze, create.")).toBeInTheDocument());
});

it("uploads dropped files, reports errors, and keeps nested drag state stable", async () => {
  localStorage.setItem("workspace-conversation", "c");
  const conversation = {
    id: "c",
    workspace_id: "w",
    title: "Drop files",
    updated_at: run.updated_at,
  };
  const config = {
    providers: [{
      id: "openai",
      label: "OpenAI",
      enabled: true,
      models: [{
        id: "gpt-5.6-sol",
        label: "GPT-5.6 Sol",
        model: "gpt-5.6-sol",
        efforts: ["medium"],
      }],
    }],
    workspaces: [{ id: "w", label: "Work", path: "/work" }],
    skills: [],
    resources: [],
    mcp_servers: [],
  };
  let uploaded: FormData | undefined;
  let uploadAttempts = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify(config));
    if (url === "/api/conversations")
      return new Response(JSON.stringify([conversation]));
    if (url === "/api/conversations/c")
      return new Response(JSON.stringify({ ...conversation, runs: [] }));
    if (url.startsWith("/api/conversations/c/files"))
      return new Response(JSON.stringify([]));
    if (url === "/api/attachments" && options?.method === "POST") {
      uploadAttempts += 1;
      uploaded = options.body as FormData;
      if (uploadAttempts === 1)
        return new Response(JSON.stringify({ detail: "Attachment too large" }), { status: 400 });
      return new Response(JSON.stringify([
        { id: "a1", name: "notes.txt", size: 5, content_type: "text/plain" },
        { id: "a2", name: "figure.png", size: 4, content_type: "image/png" },
      ]));
    }
    return new Response(JSON.stringify({}));
  });

  const { container } = render(<App />);
  await screen.findByRole("textbox", { name: "Message" });
  const pane = container.querySelector(".main")!;
  const files = [
    new File(["notes"], "notes.txt", { type: "text/plain" }),
    new File(["png!"], "figure.png", { type: "image/png" }),
  ];
  const dataTransfer = { types: ["Files"], files, items: [] };

  fireEvent.dragEnter(pane, { dataTransfer });
  fireEvent.dragEnter(pane, { dataTransfer });
  expect(screen.getByText("Drop files to attach")).toBeInTheDocument();
  fireEvent.dragLeave(pane, { dataTransfer });
  expect(screen.getByText("Drop files to attach")).toBeInTheDocument();
  fireEvent.drop(pane, { dataTransfer });

  expect(await screen.findByRole("alert")).toHaveTextContent("Attachment too large");
  expect(screen.queryByText("Drop files to attach")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
  fireEvent.dragEnter(pane, { dataTransfer });
  fireEvent.drop(pane, { dataTransfer });

  await waitFor(() => expect(uploadAttempts).toBe(2));
  expect(uploaded?.get("conversation_id")).toBe("c");
  expect((uploaded?.getAll("files") as File[]).map((file) => file.name)).toEqual([
    "notes.txt",
    "figure.png",
  ]);
  expect(await screen.findByText("notes.txt")).toBeInTheDocument();
  expect(screen.getByText("figure.png")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Send directly to model" })).not.toBeChecked();
  expect(screen.queryByText("Drop files to attach")).not.toBeInTheDocument();
});
