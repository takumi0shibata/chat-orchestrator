import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { App, RunView } from "./App";
import type { AgentEvent, Run } from "./types";

vi.mock("./components/HostTerminalPanel", () => ({
  HostTerminalPanel: ({ workspacePath }: { workspacePath: string }) =>
    <div data-testid="host-terminal-mock">{workspacePath}</div>,
}));

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
  it("copies the user message and the combined assistant Markdown", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <RunView
        run={{
          ...run,
          request: {
            ...run.request,
            input: "Review the attached report",
            attachment_ids: ["attachment-1"],
          },
        }}
        timeline={[
          event(1, "text_delta", { item_id: "first", text: "**Summary**" }),
          event(2, "text_delta", { item_id: "second", text: "`report.md`" }),
        ]}
        onApproval={vi.fn()}
      />,
    );

    const copyMessageButton = screen.getByRole("button", { name: "Copy message" });
    const copyResponseButton = screen.getByRole("button", { name: "Copy response" });
    expect(copyMessageButton).toHaveAttribute("data-tooltip", "Copy message");
    expect(copyResponseButton).toHaveAttribute("data-tooltip", "Copy response");

    fireEvent.click(copyMessageButton);
    await waitFor(() => expect(writeText).toHaveBeenNthCalledWith(1, "Review the attached report"));
    expect(screen.getByRole("button", { name: "Copied" })).toHaveAttribute("data-state", "copied");

    fireEvent.click(copyResponseButton);
    await waitFor(() => expect(writeText).toHaveBeenNthCalledWith(2, "**Summary**\n\n`report.md`"));
  });

  it("reports a message copy failure", async () => {
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });

    render(<RunView run={run} timeline={[]} onApproval={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    expect(await screen.findByRole("button", { name: "Copy failed" })).toHaveAttribute("data-state", "failed");
  });

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
    expect(screen.queryByText("YOU")).not.toBeInTheDocument();
    expect(screen.getByText("変更しました")).toBeInTheDocument();
    const details = document.querySelector("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Worked for 5s"));
    expect(details).toHaveAttribute("open");
    const work = document.querySelector("details.work-group")!;
    expect(work).not.toHaveAttribute("open");
    expect(screen.getByText("Ran commands")).toBeInTheDocument();
    fireEvent.click(work.querySelector("summary")!);
    expect(work).toHaveAttribute("open");
    expect(screen.getByText("200 files analyzed")).toBeInTheDocument();
    expect(document.querySelector(".activity-body")).not.toHaveTextContent("Work completed");
    expect(document.querySelector(".activity-body")).not.toHaveTextContent("2.0s");
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

  it("never renders automatic file change notifications", () => {
    const { container } = render(
      <RunView
        run={run}
        timeline={[
          event(1, "artifacts", {
            label: "3 file changes",
            files: [
              { path: "created.md", change: "created" },
              { path: "updated.md", change: "modified" },
              { path: "deleted.md", change: "deleted" },
            ],
          }),
        ]}
        onApproval={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Worked for 5s"));
    expect(container).not.toHaveTextContent("file changes");
    expect(container).not.toHaveTextContent("created.md");
    expect(container.querySelector(".artifact-list")).toBeNull();
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
  const modelSelector = screen.getByRole("button", { name: "Model" });
  fireEvent.click(modelSelector);
  const modelMenu = screen.getByRole("listbox", { name: "Model" });
  fireEvent.keyDown(modelMenu, { key: "ArrowDown" });
  fireEvent.keyDown(modelMenu, { key: "Enter" });
  expect(modelSelector).toHaveTextContent("GPT-5.6 Luna");
  const effortSelector = screen.getByRole("button", { name: "Reasoning effort" });
  fireEvent.click(effortSelector);
  fireEvent.click(screen.getByRole("option", { name: "High" }));
  expect(effortSelector).toHaveTextContent("High");
  fireEvent.click(modelSelector);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("listbox", { name: "Model" })).not.toBeInTheDocument();
  fireEvent.click(modelSelector);
  fireEvent.click(screen.getByRole("option", { name: "GPT-5.6 Sol" }));
  expect(effortSelector).toHaveTextContent("Medium");
  fireEvent.click(modelSelector);
  fireEvent.click(screen.getByRole("option", { name: "GPT-5.6 Luna" }));
  fireEvent.click(effortSelector);
  fireEvent.click(screen.getByRole("option", { name: "High" }));
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

it("selects configured skills with an @ mention and sends their ids without the mention text", async () => {
  localStorage.setItem("workspace-conversation", "c");
  const config = {
    providers: [{ id: "openai", label: "OpenAI", enabled: true, models: [{ id: "gpt-5.6-sol", label: "GPT-5.6 Sol", model: "gpt-5.6-sol", efforts: ["medium"] }] }],
    workspaces: [{ id: "w", label: "Research", path: "/research" }],
    skills: [
      { id: "academic", label: "Academic review", name: "academic-writing", description: "Review drafts" },
      { id: "morning", label: "Morning brief", name: "morning-brief", description: "Prepare a brief" },
    ],
    resources: [],
    mcp_servers: [],
  };
  const conversation = { id: "c", workspace_id: "w", title: "Skill task", updated_at: run.updated_at };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify(config));
    if (url === "/api/settings") return new Response(JSON.stringify({ title_provider: "openai", title_model: "gpt-5.6-sol", theme_color: "#25262A" }));
    if (url === "/api/conversations") return new Response(JSON.stringify([conversation]));
    if (url === "/api/conversations/c") return new Response(JSON.stringify({ ...conversation, runs: [] }));
    if (url.startsWith("/api/conversations/c/files")) return new Response(JSON.stringify([]));
    if (url === "/api/runs" && options?.method === "POST") return new Response(JSON.stringify(run));
    return new Response(JSON.stringify({}));
  });

  render(<App />);
  const message = await screen.findByRole("textbox", { name: "Message" });
  await waitFor(() => expect(message).not.toBeDisabled());

  fireEvent.change(message, { target: { value: "@" } });
  fireEvent.keyDown(message, { key: "ArrowDown" });
  expect(screen.getByRole("option", { name: /@morning-brief/ })).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(message, { key: "Escape" });
  expect(screen.queryByRole("listbox", { name: "Skills" })).not.toBeInTheDocument();

  fireEvent.change(message, { target: { value: "@acad" } });
  expect(screen.getByRole("listbox", { name: "Skills" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /@academic-writing/ })).toHaveAttribute("aria-selected", "true");
  fireEvent.keyDown(message, { key: "Enter" });
  expect(message).toHaveValue("");
  expect(screen.getByRole("button", { name: "Remove Academic review" })).toBeInTheDocument();

  fireEvent.change(message, { target: { value: "@morning-brief" } });
  fireEvent.keyDown(message, { key: " " });
  expect(message).toHaveValue("");
  expect(screen.getByRole("button", { name: "Remove Morning brief" })).toBeInTheDocument();

  fireEvent.change(message, { target: { value: "Prepare today's update" } });
  fireEvent.keyDown(message, { key: "Enter" });
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === "/api/runs" && options?.method === "POST")).toBe(true));
  const sent = fetchMock.mock.calls.find(([url, options]) => url === "/api/runs" && options?.method === "POST");
  expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({
    input: "Prepare today's update",
    skill_ids: ["academic", "morning"],
  });
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
  expect(screen.getAllByRole("status").some((element) => /^Working for /.test(element.textContent || ""))).toBe(true);
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  fireEvent.dragEnter(container.querySelector(".main")!, {
    dataTransfer: { types: ["Files"], files: [new File(["x"], "x.txt")], items: [] },
  });
  expect(screen.queryByText("Drop files to attach")).not.toBeInTheDocument();
  fireEvent.click(stop);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === "/api/runs/r/stop" && options?.method === "POST")).toBe(true));
});

it("closes Activity at final-answer start and streams the answer outside it", async () => {
  const initial = [event(1, "round", { number: 1 }), event(2, "text_delta", { item_id: "a", text: "Checking files" })];
  const { container, rerender } = render(<RunView run={{ ...run, status: "model_wait" }} timeline={initial} onApproval={vi.fn()} />);
  const details = container.querySelector("details")!;
  expect(details).toHaveAttribute("open");
  expect(container.querySelector(".activity-message")).toHaveTextContent("Checking files");
  expect(container.querySelector(".answer-block")).toBeNull();
  fireEvent.click(details.querySelector("summary")!);
  expect(details).not.toHaveAttribute("open");

  const continued = [...initial, event(3, "response", { round: 1, continues: true, final_item_ids: [] }),
    event(4, "command", { call_id: "call", index: 0, command: "npm test" })];
  rerender(<RunView run={{ ...run, status: "command_running" }} timeline={continued} onApproval={vi.fn()} />);
  expect(details).not.toHaveAttribute("open");
  const work = container.querySelector("details.work-group")!;
  expect(work).not.toHaveAttribute("open");
  expect(work).toHaveTextContent("Running commands");
  fireEvent.click(details.querySelector("summary")!);
  expect(details).toHaveAttribute("open");

  const beforeAnswer = [...continued, event(5, "command_done", { call_id: "call", index: 0, elapsed: 1, outcome: { type: "exit", exit_code: 0 } }),
    event(6, "round", { number: 2 }), event(7, "message_phase", { item_id: "b", round: 2, phase: "final_answer" })];
  rerender(<RunView run={{ ...run, status: "model_wait" }} timeline={beforeAnswer} onApproval={vi.fn()} />);
  await waitFor(() => expect(details).not.toHaveAttribute("open"));
  expect(container.querySelector(".answer-block")).toBeNull();
  const streaming = [...beforeAnswer, event(8, "text_delta", { item_id: "b", round: 2, text: "**Final" })];
  rerender(<RunView run={{ ...run, status: "model_wait" }} timeline={streaming} onApproval={vi.fn()} />);
  expect(container.querySelectorAll(".answer-block")).toHaveLength(1);
  expect(container.querySelector(".answer-block")).toHaveTextContent("Final");
  expect(container.querySelector(".activity-message")).toHaveTextContent("Checking files");
  fireEvent.click(details.querySelector("summary")!);
  expect(details).toHaveAttribute("open");
  const finished = [...streaming, event(9, "text_delta", { item_id: "b", round: 2, text: " result**" }),
    event(10, "response", { round: 2, final_item_ids: ["b"], continues: false })];
  rerender(<RunView run={run} timeline={finished} onApproval={vi.fn()} />);
  expect(details).toHaveAttribute("open");
  expect(container.querySelector(".answer-block strong")).toHaveTextContent("Final result");
});

it("shows one expandable work line per report interval without process noise", () => {
  const timeline = [event(1, "status", { label: "Preparing" }),
    event(2, "round", { number: 1 }),
    event(3, "text_delta", { item_id: "report", round: 1, text: "Checking the project" }),
    event(4, "response", { round: 1, continues: true, final_item_ids: [] }),
    event(5, "command", { call_id: "one", index: 0, command: "pwd" }),
    event(6, "command_output", { call_id: "one", index: 0, text: "/workspace" }),
    event(7, "command_done", { call_id: "one", index: 0, elapsed: 0.1, outcome: { type: "exit", exit_code: 0 } }),
    event(8, "command", { call_id: "two", index: 0, command: "ls" }),
    event(9, "command_done", { call_id: "two", index: 0, elapsed: 0.1, outcome: { type: "exit", exit_code: 0 } }),
    event(10, "tool", { id: "web", type: "web_search_call" }),
    event(11, "tool_result", { id: "web", type: "web_search_call", status: "completed" }),
    event(12, "text_delta", { item_id: "next", round: 2, text: "Found the files" }),
    event(13, "tool", { id: "mcp", type: "mcp_call", name: "lookup" }),
    event(14, "tool_result", { id: "mcp", type: "mcp_call", output: "record" })];
  const { container } = render(<RunView run={{ ...run, status: "model_wait" }} timeline={timeline} onApproval={vi.fn()} />);
  const history = container.querySelector(".activity-body")!;
  expect(history.querySelectorAll(".activity-message")).toHaveLength(2);
  expect(history.querySelectorAll(".work-group")).toHaveLength(2);
  expect(history).toHaveTextContent("Ran commands, Searched web");
  expect(history).toHaveTextContent("Used external tools");
  for (const noise of ["Preparing", "Model turn", "Response received", "0.1s"]) expect(history).not.toHaveTextContent(noise);
  const first = history.querySelector(".work-group")!;
  fireEvent.click(first.querySelector("summary")!);
  expect(first).toHaveTextContent("$ pwd");
  expect(first).toHaveTextContent("$ ls");
  expect(first).toHaveTextContent("/workspace");
});

it("waits for response IDs when phase is absent, then closes before terminal status", async () => {
  const start = [event(1, "text_delta", { item_id: "final", round: 1, text: "Answer" })];
  const { container, rerender } = render(<RunView run={{ ...run, status: "model_wait" }} timeline={start} onApproval={vi.fn()} />);
  const details = container.querySelector("details.activity")!;
  expect(details).toHaveAttribute("open");
  expect(container.querySelector(".answer-block")).toBeNull();
  rerender(<RunView run={{ ...run, status: "model_wait" }} timeline={[...start,
    event(2, "response", { round: 1, final_item_ids: ["final"], continues: false })]} onApproval={vi.fn()} />);
  await waitFor(() => expect(details).not.toHaveAttribute("open"));
  expect(container.querySelector(".answer-block")).toHaveTextContent("Answer");
});

it("keeps a phased partial answer and visible error if the run fails", async () => {
  const timeline = [event(1, "message_phase", { item_id: "final", round: 1, phase: "final_answer" }),
    event(2, "text_delta", { item_id: "final", round: 1, text: "Partial answer" }),
    event(3, "error", { message: "Cleanup failed" })];
  const { container, rerender } = render(<RunView run={{ ...run, status: "model_wait" }} timeline={timeline} onApproval={vi.fn()} />);
  expect(container.querySelector(".answer-block")).toHaveTextContent("Partial answer");
  rerender(<RunView run={{ ...run, status: "failed" }} timeline={timeline} onApproval={vi.fn()} />);
  await waitFor(() => expect(container.querySelector("details.activity")).toHaveAttribute("open"));
  expect(container.querySelector(".answer-block")).toHaveTextContent("Partial answer");
  expect(screen.getByRole("alert")).toHaveTextContent("Cleanup failed");
});

it("opens Activity when an active run fails and when a stopped run is restored", async () => {
  const timeline = [event(1, "text_delta", { item_id: "a", text: "Checking before failure" })];
  const { container, rerender } = render(<RunView run={{ ...run, status: "model_wait" }} timeline={timeline} onApproval={vi.fn()} />);
  const details = container.querySelector("details")!;
  fireEvent.click(details.querySelector("summary")!);
  expect(details).not.toHaveAttribute("open");

  rerender(<RunView run={{ ...run, status: "failed" }} timeline={timeline} onApproval={vi.fn()} />);
  await waitFor(() => expect(details).toHaveAttribute("open"));
  expect(container.querySelector(".activity-message")).toHaveTextContent("Checking before failure");
  expect(container.querySelector(".answer-block")).toBeNull();

  const restored = render(<RunView run={{ ...run, status: "stopped" }} timeline={timeline} onApproval={vi.fn()} />);
  expect(restored.container.querySelector("details")).toHaveAttribute("open");
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
  expect(screen.getByRole("heading", { name: "Current chat" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Pin Current chat" }));
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Unpin Current chat" })).toHaveLength(2));
  failPin = true;
  fireEvent.click(screen.getAllByRole("button", { name: "Unpin Current chat" })[0]);
  await screen.findByText(/Pin failed/);
  expect(screen.getAllByRole("button", { name: "Unpin Current chat" })).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
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
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Current chat" })).toHaveLength(2));
  fireEvent.keyDown(search, { key: "Escape" });
  expect(screen.queryByRole("searchbox", { name: "Search history" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Search" })).toBeInTheDocument();
});

it("groups chats by project and creates from the recent or chosen project", async () => {
  const alpha = { id: "a", title: "Alpha chat", workspace_id: "alpha", updated_at: "2026-09-16T00:00:00Z", pinned: false };
  const beta = { id: "b", title: "Beta chat", workspace_id: "beta", updated_at: "2026-09-17T00:00:00Z", pinned: true };
  const created = { id: "new", title: "New chat", workspace_id: "beta", updated_at: "2026-09-18T00:00:00Z", pinned: false };
  localStorage.setItem("workspace-conversation", "b");
  localStorage.setItem("workspace-last-project", "beta");
  const posts: string[] = [];
  let conversations = [alpha, beta];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify({
      providers: [],
      workspaces: [
        { id: "alpha", label: "Alpha", path: "/alpha" },
        { id: "beta", label: "Beta", path: "/beta" },
      ],
      skills: [], resources: [], mcp_servers: [],
    }));
    if (url === "/api/conversations" && options?.method === "POST") {
      const projectId = JSON.parse(String(options.body)).workspace_id as string;
      posts.push(projectId);
      const next = { ...created, id: `new-${posts.length}`, workspace_id: projectId };
      conversations = [...conversations, next];
      return new Response(JSON.stringify(next));
    }
    if (url === "/api/conversations") return new Response(JSON.stringify(conversations));
    if (url.startsWith("/api/conversations/") && !url.includes("/files")) {
      const id = url.split("/").pop();
      const conversation = conversations.find((item) => item.id === id);
      return new Response(JSON.stringify({ ...conversation, runs: [] }));
    }
    if (url.includes("/files")) return new Response(JSON.stringify([]));
    return new Response(JSON.stringify({}));
  });

  render(<App />);
  const betaToggle = await screen.findByRole("button", { name: "Collapse Beta" });
  const alphaToggle = screen.getByRole("button", { name: "Expand Alpha" });
  expect(betaToggle.querySelector('[data-icon="folder-open"]')).toBeInTheDocument();
  expect(alphaToggle.querySelector('[data-icon="folder"]')).toBeInTheDocument();
  fireEvent.click(alphaToggle);
  const expandedAlpha = screen.getByRole("button", { name: "Collapse Alpha" });
  const alphaConversations = expandedAlpha.closest(".project-group")?.querySelector(".project-conversations");
  expect(expandedAlpha.querySelector('[data-icon="folder-open"]')).toBeInTheDocument();
  expect(alphaConversations).toHaveClass("is-expanded");
  expect(alphaConversations).toHaveAttribute("aria-hidden", "false");
  fireEvent.click(expandedAlpha);
  expect(alphaConversations).not.toHaveClass("is-expanded");
  expect(alphaConversations).toHaveAttribute("aria-hidden", "true");
  const betaTitles = screen.getAllByRole("button", { name: "Beta chat" });
  expect(betaTitles).toHaveLength(2);
  expect(betaTitles[0]).toHaveClass("history-title");
  expect(screen.queryByText("Recents")).not.toBeInTheDocument();

  const sidebarResize = screen.getByRole("separator", { name: "Resize sidebar" });
  expect(sidebarResize).toHaveAttribute("aria-valuenow", "236");
  fireEvent.keyDown(sidebarResize, { key: "ArrowRight" });
  expect(sidebarResize).toHaveAttribute("aria-valuenow", "246");
  expect(localStorage.getItem("workspace-sidebar-width")).toBe("246");

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(posts).toEqual(["beta"]));
  fireEvent.click(screen.getByRole("button", { name: "New chat in Alpha" }));
  await waitFor(() => expect(posts).toEqual(["beta", "alpha"]));
  expect(localStorage.getItem("workspace-last-project")).toBe("alpha");
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
  const filesResize = screen.getByRole("separator", { name: "Resize files panel" });
  expect(filesResize).toHaveAttribute("aria-valuenow", "270");
  fireEvent.keyDown(filesResize, { key: "ArrowLeft" });
  expect(filesResize).toHaveAttribute("aria-valuenow", "280");
  expect(localStorage.getItem("workspace-files-width")).toBe("280");
  expect(container.querySelector(".app-shell")).toHaveStyle("--files-width: 280px");
  let captured = false;
  Object.assign(filesResize, {
    setPointerCapture: () => { captured = true; },
    hasPointerCapture: () => captured,
    releasePointerCapture: () => { captured = false; },
  });
  fireEvent(filesResize, new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
  fireEvent(filesResize, new MouseEvent("pointermove", { bubbles: true, clientX: 704 }));
  fireEvent(filesResize, new MouseEvent("pointerup", { bubbles: true }));
  expect(filesResize).toHaveAttribute("aria-valuenow", "320");
  expect(localStorage.getItem("workspace-files-width")).toBe("320");
  fireEvent.keyDown(container.querySelector("#files-panel")!, { key: "Escape" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
  fireEvent.click(toggle);
  fireEvent.click(toggle);
  expect(container.querySelector("#files-panel")).not.toHaveClass("is-open");
  await waitFor(() => expect(screen.getByText("Explore, analyze, create.")).toBeInTheDocument());
});

it("places the terminal beside the sidebar and closes it on chat change", async () => {
  const conversation = { id: "new", workspace_id: "w", title: "New chat", updated_at: run.updated_at };
  let created = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify({
      providers: [], workspaces: [{ id: "w", label: "Work", path: "/work" }],
      skills: [], resources: [], mcp_servers: [],
    }));
    if (url === "/api/settings") return new Response(JSON.stringify({
      title_provider: "openai", title_model: "gpt-6-luna", theme_color: "#25262A",
    }));
    if (url === "/api/conversations" && options?.method === "POST") {
      created = true;
      return new Response(JSON.stringify(conversation));
    }
    if (url === "/api/conversations") return new Response(JSON.stringify(created ? [conversation] : []));
    if (url === "/api/conversations/new") return new Response(JSON.stringify({ ...conversation, runs: [] }));
    return new Response(JSON.stringify([]));
  });
  const { container } = render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Show host terminal" }));
  expect(await screen.findByTestId("host-terminal-mock")).toHaveTextContent("/work");
  const shell = container.querySelector(".app-shell");
  expect(shell).toHaveClass("has-terminal");
  expect(shell?.querySelector(":scope > .sidebar")).toBeInTheDocument();
  expect(shell?.querySelector(":scope > .terminal-grid-cell")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /files panel/ }));
  expect(shell).toHaveClass("with-files");
  expect(screen.getByTestId("host-terminal-mock")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await waitFor(() => expect(screen.queryByTestId("host-terminal-mock")).not.toBeInTheDocument());
  expect(shell).not.toHaveClass("has-terminal");
});

it("toggles the host terminal with Cmd+J", async () => {
  const conversation = { id: "new", workspace_id: "w", title: "New chat", updated_at: run.updated_at };
  let created = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify({
      providers: [], workspaces: [{ id: "w", label: "Work", path: "/work" }],
      skills: [], resources: [], mcp_servers: [],
    }));
    if (url === "/api/settings") return new Response(JSON.stringify({
      title_provider: "openai", title_model: "gpt-6-luna", theme_color: "#25262A",
    }));
    if (url === "/api/conversations" && options?.method === "POST") {
      created = true;
      return new Response(JSON.stringify(conversation));
    }
    if (url === "/api/conversations") return new Response(JSON.stringify(created ? [conversation] : []));
    if (url === "/api/conversations/new") return new Response(JSON.stringify({ ...conversation, runs: [] }));
    return new Response(JSON.stringify([]));
  });

  render(<App />);
  await screen.findByRole("button", { name: "Show host terminal" });
  fireEvent.keyDown(document, { key: "j", metaKey: true });
  expect(await screen.findByTestId("host-terminal-mock")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Hide host terminal" })).toHaveAttribute("aria-keyshortcuts", "Meta+J");

  fireEvent.keyDown(document, { key: "j", metaKey: true });
  await waitFor(() => expect(screen.queryByTestId("host-terminal-mock")).not.toBeInTheDocument());
});

it("renders a lazy file tree with typed icons, caching, refresh, empty and retry states", async () => {
  localStorage.setItem("workspace-conversation", "c");
  const conversation = { id: "c", workspace_id: "w", title: "File tree", updated_at: run.updated_at };
  const config = {
    providers: [],
    workspaces: [{ id: "w", label: "Work", path: "/work" }],
    skills: [], resources: [], mcp_servers: [],
  };
  const calls: Record<string, number> = {};
  let brokenAttempts = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify(config));
    if (url === "/api/settings") return new Response(JSON.stringify({ title_provider: "openai", title_model: "gpt-5.6-luna", theme_color: "#25262A" }));
    if (url === "/api/conversations") return new Response(JSON.stringify([conversation]));
    if (url === "/api/conversations/c") return new Response(JSON.stringify({ ...conversation, runs: [] }));
    if (url.startsWith("/api/conversations/c/files")) {
      const path = decodeURIComponent(url.split("path=")[1] || "");
      calls[path] = (calls[path] || 0) + 1;
      if (path === "documents") return new Response(JSON.stringify([
        { name: "report.pdf", path: "documents/report.pdf", directory: false, size: 1536 },
      ]));
      if (path === "empty") return new Response(JSON.stringify([]));
      if (path === "broken") {
        brokenAttempts += 1;
        if (brokenAttempts === 1) return new Response(JSON.stringify({ detail: "Unavailable" }), { status: 500 });
        return new Response(JSON.stringify([{ name: "fixed.py", path: "broken/fixed.py", directory: false, size: 12 }]));
      }
      return new Response(JSON.stringify([
        { name: "documents", path: "documents", directory: true, size: 0 },
        { name: "empty", path: "empty", directory: true, size: 0 },
        { name: "broken", path: "broken", directory: true, size: 0 },
        { name: "photo.png", path: "photo.png", directory: false, size: 2 * 1024 * 1024 },
        { name: "data.csv", path: "data.csv", directory: false, size: 100 },
        { name: ".DS_Store", path: ".DS_Store", directory: false, size: 6 },
      ]));
    }
    return new Response(JSON.stringify({}));
  });

  const { container } = render(<App />);
  const documents = await screen.findByRole("button", { name: "documents" });
  expect(documents).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByRole("link", { name: /photo.png/ }).querySelector('[data-icon="file-image"]')).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /data.csv/ }).querySelector('[data-icon="file-spreadsheet"]')).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /photo.png/ })).toHaveTextContent("2.0 MB");
  expect(screen.getByRole("link", { name: /.DS_Store/ })).toBeInTheDocument();

  fireEvent.click(documents);
  expect(documents).toHaveAttribute("aria-expanded", "true");
  const report = await screen.findByRole("link", { name: /report.pdf/ });
  expect(report).toHaveAttribute("href", "/api/conversations/c/download?path=documents%2Freport.pdf");
  expect(report).toHaveTextContent("1.5 KB");
  expect(report.querySelector('[data-icon="file-pdf"]')).toBeInTheDocument();
  fireEvent.click(documents);
  fireEvent.click(documents);
  expect(calls.documents).toBe(1);

  fireEvent.click(screen.getByRole("button", { name: "empty" }));
  expect(await screen.findByText("Empty folder")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "broken" }));
  expect(await screen.findByText("Couldn’t load folder.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry loading broken" }));
  expect(await screen.findByRole("link", { name: /fixed.py/ })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Refresh files" }));
  await waitFor(() => expect(calls[""]).toBe(2));
  await waitFor(() => expect(calls.documents).toBe(2));
  expect(container.querySelector('.file-tree-chevron.is-expanded')).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "documents" })).toHaveAttribute("aria-expanded", "true");
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

it("navigates settings, saves the title model and theme, and shows monthly cost", async () => {
  const config = {
    providers: [{
      id: "openai", label: "OpenAI", enabled: true,
      models: [
        { id: "gpt-5.6-sol", label: "GPT-5.6 Sol", model: "gpt-5.6-sol", efforts: ["low"] },
        { id: "gpt-5.6-luna", label: "GPT-5.6 Luna", model: "gpt-5.6-luna", efforts: ["low"] },
      ],
    }],
    workspaces: [{ id: "w", label: "Work", path: "/work" }],
    skills: [], resources: [], mcp_servers: [],
  };
  let settings = { title_provider: "openai", title_model: "gpt-5.6-luna", theme_color: "#25262A" };
  const patches: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify(config));
    if (url === "/api/conversations") return new Response(JSON.stringify([]));
    if (url === "/api/settings" && options?.method === "PATCH") {
      const change = JSON.parse(String(options.body));
      patches.push(change);
      settings = { ...settings, ...change };
      return new Response(JSON.stringify(settings));
    }
    if (url === "/api/settings") return new Response(JSON.stringify(settings));
    if (url === "/api/costs/monthly") return new Response(JSON.stringify({
      currency: "USD", estimated: true, timezone: "UTC", exclusions: ["tool_fees"],
      months: [{ month: new Date().toISOString().slice(0, 7), usd: 0.012345 }],
    }));
    return new Response(JSON.stringify({}));
  });

  const { container } = render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Settings" }));
  expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Title model" }), { target: { value: "gpt-5.6-sol" } });
  await waitFor(() => expect(patches).toContainEqual({ title_provider: "openai", title_model: "gpt-5.6-sol" }));

  fireEvent.click(screen.getByRole("button", { name: /Theme color/ }));
  fireEvent.click(screen.getByRole("button", { name: "Use #315C47" }));
  await waitFor(() => expect(container.querySelector(".app-shell")).toHaveStyle("--theme-color: #315C47"));
  expect(patches).toContainEqual({ theme_color: "#315C47" });

  fireEvent.click(screen.getByRole("button", { name: "← Settings" }));
  fireEvent.click(screen.getByRole("button", { name: /Cost/ }));
  expect((await screen.findAllByText("$0.012345")).length).toBe(2);
  expect(screen.getByText("Tool fees excluded")).toBeInTheDocument();
});

it("starts new conversations with GPT-6 Sol and offers registered Azure GPT-6 for titles", async () => {
  localStorage.setItem("workspace-conversation", "c");
  const config = {
    providers: [
      { id: "openai", label: "OpenAI", enabled: true, models: [
        { id: "gpt-6-sol", model: "gpt-6-sol", label: "GPT-6 Sol", efforts: ["none", "medium"] },
        { id: "gpt-6-luna", model: "gpt-6-luna", label: "GPT-6 Luna", efforts: ["none", "medium"] },
        { id: "gpt-5.6-sol", model: "gpt-5.6-sol", label: "GPT-5.6 Sol", efforts: ["medium"] },
        { id: "gpt-5.6-terra", model: "gpt-5.6-terra", label: "GPT-5.6 Terra", efforts: ["medium"] },
        { id: "gpt-5.6-luna", model: "gpt-5.6-luna", label: "GPT-5.6 Luna", efforts: ["medium"] },
        { id: "gpt-6-astra", model: "gpt-6-astra", label: "GPT-6 Astra", efforts: ["medium"] },
      ] },
      { id: "azure_openai", label: "Azure OpenAI", enabled: true, models: [
        { id: "azure-old-luna", model: "gpt-5.6-luna", label: "GPT-5.6 Luna", efforts: ["medium"] },
        { id: "azure-new-luna", model: "gpt-6-luna", label: "GPT-6 Luna", efforts: ["none", "medium"] },
      ] },
    ],
    workspaces: [{ id: "w", label: "Work", path: "/work" }],
    skills: [], resources: [], mcp_servers: [],
  };
  const conversation = { id: "c", workspace_id: "w", title: "New task", updated_at: "2026-09-23T00:00:00Z" };
  let settings = { title_provider: "openai", title_model: "gpt-6-luna", theme_color: "#25262A" };
  const patches: Record<string, string>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify(config));
    if (url === "/api/conversations") return new Response(JSON.stringify([conversation]));
    if (url === "/api/conversations/c") return new Response(JSON.stringify({ ...conversation, runs: [] }));
    if (url.startsWith("/api/conversations/c/files")) return new Response(JSON.stringify([]));
    if (url === "/api/settings" && options?.method === "PATCH") {
      const change = JSON.parse(String(options.body));
      patches.push(change);
      settings = { ...settings, ...change };
      return new Response(JSON.stringify(settings));
    }
    if (url === "/api/settings") return new Response(JSON.stringify(settings));
    return new Response(JSON.stringify({}));
  });

  render(<App />);
  const modelSelect = await screen.findByRole("button", { name: "Model" });
  await waitFor(() => expect(modelSelect).toHaveTextContent("GPT-6 Sol"));
  const expectedOrder = [
    "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
  ];
  fireEvent.click(modelSelect);
  expect(Array.from(screen.getAllByRole("option"), (option) => option.textContent)).toEqual([
    "GPT-6 Astra", "GPT-6 Sol", "GPT-6 Luna", "GPT-5.6 Sol", "GPT-5.6 Terra", "GPT-5.6 Luna",
  ]);
  expect(Array.from(screen.getByRole("listbox", { name: "Model" }).querySelectorAll("[data-model-icon]"), (icon) => icon.getAttribute("data-model-icon"))).toEqual([
    "astra", "sol", "luna", "sol", "terra", "luna",
  ]);
  fireEvent.keyDown(screen.getByRole("listbox", { name: "Model" }), { key: "Escape" });
  expect(screen.queryByRole("listbox", { name: "Model" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reasoning effort" })).toHaveTextContent("Medium");
  fireEvent.click(screen.getByRole("button", { name: "Reasoning effort" }));
  expect(Array.from(screen.getByRole("listbox", { name: "Reasoning effort" }).querySelectorAll('[role="option"]'), (option) => option.textContent)).toEqual([
    "Instant", "Medium",
  ]);
  fireEvent.keyDown(screen.getByRole("listbox", { name: "Reasoning effort" }), { key: "Escape" });

  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  const titleModelSelect = screen.getByRole("combobox", { name: "Title model" });
  expect(titleModelSelect).toHaveValue("gpt-6-luna");
  expect(Array.from((titleModelSelect as HTMLSelectElement).options, (option) => option.value)).toEqual(expectedOrder);
  fireEvent.change(screen.getByRole("combobox", { name: "Title provider" }), { target: { value: "azure_openai" } });
  await waitFor(() => expect(patches).toContainEqual({ title_provider: "azure_openai", title_model: "azure-old-luna" }));
  expect(Array.from((titleModelSelect as HTMLSelectElement).options, (option) => option.value)).toEqual([
    "azure-new-luna", "azure-old-luna",
  ]);
  fireEvent.change(screen.getByRole("combobox", { name: "Title model" }), { target: { value: "azure-new-luna" } });
  await waitFor(() => expect(patches).toContainEqual({ title_provider: "azure_openai", title_model: "azure-new-luna" }));
});

it("shows five recent chats per project and reveals ten more at a time", async () => {
  const conversations = Array.from({ length: 17 }, (_, index) => ({
    id: `history-${index}`,
    title: `History ${index + 1}`,
    workspace_id: "w",
    updated_at: `2026-09-${String(23 - index).padStart(2, "0")}T00:00:00Z`,
    pinned: index === 16,
  }));
  localStorage.setItem("workspace-conversation", conversations[0].id);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/config") return new Response(JSON.stringify({
      providers: [],
      workspaces: [{ id: "w", label: "Work", path: "/work" }],
      skills: [], resources: [], mcp_servers: [],
    }));
    if (url === "/api/conversations") return new Response(JSON.stringify(conversations));
    if (url === `/api/conversations/${conversations[0].id}`) return new Response(JSON.stringify({ ...conversations[0], runs: [] }));
    if (url.includes("/files")) return new Response(JSON.stringify([]));
    if (url === "/api/settings") return new Response(JSON.stringify({ title_provider: "openai", title_model: "gpt-6-luna", theme_color: "#25262A" }));
    return new Response(JSON.stringify({}));
  });

  render(<App />);
  await screen.findByRole("button", { name: "History 1" });
  expect(screen.getByText("Sandboxed: network access is disabled; only files in the mounted workspace can be modified.")).toBeInTheDocument();
  const project = screen.getByRole("button", { name: "Collapse Work" }).closest(".project-group")!;
  const projectHistory = () => project.querySelectorAll(".project-conversations .history-title");
  expect(projectHistory()).toHaveLength(6);
  expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "History 17" })).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "History 6" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(projectHistory()).toHaveLength(16));
  expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "History 16" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(projectHistory()).toHaveLength(17));
  expect(screen.getByRole("button", { name: "History 16" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
});
