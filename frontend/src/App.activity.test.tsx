import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Conversation, Run } from "./types";
import { MockEventSource } from "./test/MockEventSource";
import { usageDashboard } from "./test/usageDashboard";

beforeEach(() => localStorage.clear());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

function setup({ completed = false, focused = true, delayEvents = false } = {}) {
  localStorage.setItem("workspace-conversation", "a");
  const focus = vi.spyOn(document, "hasFocus").mockReturnValue(focused);
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  const conversations: Conversation[] = [
    { id: "a", workspace_id: "alpha", title: "First chat", updated_at: "2026-10-16T00:00:00Z",
      active_run: completed ? null : { id: "ra", status: "preparing", label: "Waiting for workspace availability" },
      latest_finished_run: completed ? { id: "ra", status: "completed" } : null, has_unread: completed },
    { id: "b", workspace_id: "beta", title: "Second chat", updated_at: "2026-10-16T00:00:00Z", pinned: true,
      active_run: { id: "rb", status: "approval_wait", label: "Waiting for external tool approval" },
      latest_finished_run: null, has_unread: false },
  ];
  const runFor = (c: Conversation): Run => ({
    id: `r${c.id}`, conversation_id: c.id, status: c.active_run?.status || "completed",
    created_at: c.updated_at, updated_at: c.updated_at,
    request: { conversation_id: c.id, provider: "openai", model: "gpt-6.1-sol", reasoning_effort: "medium",
      input: "Work", attachment_ids: [], direct_attachment_ids: [], skill_ids: [], resource_ids: [], mcp_ids: [], web_search: false },
  });
  let releaseEvents: () => void = () => {};
  let listOverride: (() => Promise<Response>) | undefined;
  let readOverride: (() => Promise<Response>) | undefined;
  let requestOverride: ((url: string, options?: RequestInit) => Response | Promise<Response> | undefined) | undefined;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    const override = requestOverride?.(url, options);
    if (override) return override;
    const json = (body: unknown) => new Response(JSON.stringify(body));
    if (url === "/api/config") return json({
      providers: [{ id: "openai", label: "OpenAI", enabled: true, models: [{ id: "gpt-6.1-sol", model: "gpt-6.1-sol", label: "Sol", efforts: ["medium"] }] }],
      workspaces: [{ id: "alpha", label: "Alpha", path: "/alpha" }, { id: "beta", label: "Beta", path: "/beta" }],
      skills: [], resources: [], mcp_servers: [],
    });
    if (url === "/api/settings") return json({ title_provider: "openai", title_model: "gpt-6-luna", theme_color: "#315C47" });
    if (url.startsWith("/api/usage/dashboard")) return json(usageDashboard("2026-10-19"));
    if (url === "/api/conversations") return listOverride ? listOverride() : json(conversations);
    if (url.startsWith("/api/conversations?q=")) return json(conversations);
    const conversation = conversations.find((c) => url === `/api/conversations/${c.id}`);
    if (conversation) return json({ ...conversation, runs: [runFor(conversation)] });
    const read = conversations.find((c) => url === `/api/conversations/${c.id}/read`);
    if (read) {
      if (readOverride) return readOverride();
      expect(JSON.parse(String(options?.body))).toEqual({ run_id: read.latest_finished_run?.id });
      read.has_unread = false;
      return json(read);
    }
    const eventConversation = conversations.find((c) => url.startsWith(`/api/runs/r${c.id}/events`));
    if (eventConversation) {
      const stream = new ReadableStream({ start(controller) {
        const finish = () => {
          controller.enqueue(new TextEncoder().encode(JSON.stringify({ run_id: `r${eventConversation.id}`, seq: 1,
            type: "status", data: { status: "completed" }, created_at: eventConversation.updated_at }) + "\n"));
          controller.close();
        };
        if (delayEvents) releaseEvents = finish;
        else if (!eventConversation.active_run) finish();
        else options?.signal?.addEventListener("abort", () => controller.close(), { once: true });
      } });
      return new Response(stream);
    }
    const runConversation = conversations.find((c) => url === `/api/runs/r${c.id}`);
    if (runConversation) return json(runFor(runConversation));
    return json([]);
  });
  return {
    conversations, focus, visibility, fetch,
    notify: async () => {
      if (!MockEventSource.instances.length)
        await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
      await act(async () => {
        MockEventSource.instances[MockEventSource.instances.length - 1].snapshot(conversations);
      });
    },
    releaseEvents: () => act(async () => { releaseEvents(); }),
    setListOverride: (value?: () => Promise<Response>) => { listOverride = value; },
    setReadOverride: (value?: () => Promise<Response>) => { readOverride = value; },
    setRequestOverride: (value: typeof requestOverride) => { requestOverride = value; },
    readCalls: () => fetch.mock.calls.filter(([url]) => String(url).endsWith("/read")),
  };
}

it("tracks two projects, aggregates collapsed state, and acknowledges only the opened result", async () => {
  const state = setup();
  const { container } = render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  expect(screen.getByRole("img", { name: "Waiting for workspace availability" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Waiting for approval" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "1 active chats" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Delete Second chat" })[0]).toBeDisabled();
  expect(container.querySelector(".app-shell")).toHaveStyle("--theme-color: #315C47");

  state.conversations[1].active_run = null;
  state.conversations[1].latest_finished_run = { id: "rb", status: "completed" };
  state.conversations[1].has_unread = true;
  await state.notify();
  expect(screen.getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "1 unread results" })).toBeInTheDocument();
  expect(state.readCalls()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Second chat" }));
  await waitFor(() => expect(state.readCalls()).toHaveLength(1));
  await waitFor(() => expect(screen.queryByRole("img", { name: "Unread result" })).not.toBeInTheDocument());
});

function remoteRun(id: string, status = "command_running"): Run {
  return { id, conversation_id: "a", status, created_at: `2026-10-16T00:00:0${id === "ra2" ? 1 : 2}Z`,
    updated_at: "2026-10-16T00:00:03Z",
    request: { conversation_id: "a", provider: "openai", model: "gpt-6.1-sol", reasoning_effort: "medium",
      input: `Remote instruction ${id}`, attachment_ids: [], direct_attachment_ids: [], skill_ids: [],
      resource_ids: [], mcp_ids: [], web_search: false } };
}

function frame(run: Run, seq: number, type: string, data: Record<string, unknown>) {
  return new TextEncoder().encode(JSON.stringify({ run_id: run.id, seq, type, data, created_at: run.updated_at }) + "\n");
}

it("merges another window's run, preserves existing DOM and draft, and can stop and acknowledge it", async () => {
  const state = setup({ completed: true, focused: false });
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  const originalMessage = await screen.findByText("Work");
  const message = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(message, { target: { value: "Keep my draft" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  const remote = remoteRun("ra2");
  let resolveHistory!: (response: Response) => void;
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  state.setRequestOverride((url) => {
    if (url === "/api/conversations/a") return new Promise((resolve) => { resolveHistory = resolve; });
    if (url === "/api/runs/ra2/events?after=0") return new Response(new ReadableStream({ start(controller) {
      stream = controller;
      controller.enqueue(frame(remote, 1, "message_phase", { item_id: "remote", phase: "final_answer" }));
      controller.enqueue(frame(remote, 2, "text_delta", { item_id: "remote", text: "Remote partial answer" }));
    } }));
    if (url === "/api/runs/ra2/stop") {
      remote.status = "stopped";
      stream.enqueue(frame(remote, 3, "status", { status: "stopped" }));
      stream.close();
      return new Response(JSON.stringify(remote));
    }
    if (url === "/api/runs/ra2") return new Response(JSON.stringify(remote));
  });
  state.conversations[0].active_run = { id: remote.id, status: remote.status, label: "Remote command" };
  await state.notify();
  expect(message).toBeDisabled();
  expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  await act(async () => { resolveHistory(new Response(JSON.stringify({ ...state.conversations[0], runs: [remote] }))); });
  await screen.findByText("Remote partial answer");
  expect(screen.getByText("Work")).toBe(originalMessage);
  expect(message).toHaveValue("Keep my draft");
  await state.notify();
  expect(state.fetch.mock.calls.filter(([url]) => url === "/api/runs/ra2/events?after=0")).toHaveLength(1);
  expect(state.fetch.mock.calls.filter(([url]) => url === "/api/runs/ra/events?after=0")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() => expect(message).toBeEnabled());
  state.conversations[0].active_run = null;
  state.conversations[0].latest_finished_run = { id: remote.id, status: "stopped" };
  state.conversations[0].has_unread = true;
  await state.notify();
  expect(state.readCalls()).toHaveLength(0);
  state.focus.mockReturnValue(true);
  fireEvent.focus(window);
  await waitFor(() => expect(state.readCalls()).toHaveLength(1));
  expect(JSON.parse(String(state.readCalls()[0][1]?.body))).toEqual({ run_id: "ra2" });
  expect(message).toHaveValue("Keep my draft");
});

it("loads all missed completed runs and retries a failed history request without resetting the chat", async () => {
  const state = setup({ completed: true, focused: false });
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  const originalMessage = await screen.findByText("Work");
  const missed = [remoteRun("ra2", "completed"), remoteRun("ra3", "completed")];
  let attempts = 0;
  state.setRequestOverride((url) => {
    if (url === "/api/conversations/a") {
      if (++attempts === 1) return new Response(JSON.stringify({ detail: "offline" }), { status: 503 });
      return new Response(JSON.stringify({ ...state.conversations[0], runs: missed }));
    }
    const run = missed.find((run) => url.startsWith(`/api/runs/${run.id}/events`));
    if (run) return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(frame(run, 1, "text_delta", { text: `Answer ${run.id}` }));
      controller.enqueue(frame(run, 2, "status", { status: "completed" }));
      controller.close();
    } }));
    const finished = missed.find((run) => url === `/api/runs/${run.id}`);
    if (finished) return new Response(JSON.stringify(finished));
  });
  state.conversations[0].latest_finished_run = { id: "ra3", status: "completed" };
  state.conversations[0].has_unread = true;
  await state.notify();
  await screen.findByText("Answer ra3", {}, { timeout: 3000 });
  expect(screen.getByText("Answer ra2")).toBeInTheDocument();
  expect(screen.getByText("Work")).toBe(originalMessage);
  expect(attempts).toBe(2);
  state.focus.mockReturnValue(true);
  fireEvent.focus(window);
  await waitFor(() => expect(state.readCalls()).toHaveLength(1));
  expect(JSON.parse(String(state.readCalls()[0][1]?.body))).toEqual({ run_id: "ra3" });
});

it("ignores delayed other-window history after switching conversations", async () => {
  const state = setup({ completed: true, focused: false });
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  let resolveHistory!: (response: Response) => void;
  let historySignal: AbortSignal | undefined;
  state.setRequestOverride((url, options) => {
    if (url === "/api/conversations/a") {
      historySignal = options?.signal as AbortSignal;
      return new Promise((resolve) => { resolveHistory = resolve; });
    }
  });
  state.conversations[0].active_run = { id: "ra2", status: "command_running", label: "Remote command" };
  await state.notify();
  fireEvent.click(screen.getByRole("button", { name: "Second chat" }));
  await screen.findByRole("heading", { name: "Second chat" });
  expect(historySignal?.aborted).toBe(true);
  await act(async () => { resolveHistory(new Response(JSON.stringify({ ...state.conversations[0], runs: [remoteRun("ra2")] }))); });
  expect(screen.queryByText("Remote instruction ra2")).not.toBeInTheDocument();
  expect(state.fetch.mock.calls.some(([url]) => String(url).includes("/runs/ra2"))).toBe(false);
});

it("waits for rendered events, keeps settings unread, and requires a visible focused window", async () => {
  const state = setup({ completed: true, delayEvents: true });
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  expect(state.readCalls()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Settings" }));
  await state.releaseEvents();
  expect(state.readCalls()).toHaveLength(0);
  state.focus.mockReturnValue(false);
  fireEvent.blur(window);
  fireEvent.click(screen.getByRole("button", { name: "First chat" }));
  await screen.findByRole("heading", { name: "First chat" });
  expect(state.readCalls()).toHaveLength(0);
  state.focus.mockReturnValue(true);
  state.visibility.mockReturnValue("hidden");
  fireEvent.focus(window);
  const hiddenCount = state.fetch.mock.calls.length;
  await state.notify();
  expect(state.fetch.mock.calls).toHaveLength(hiddenCount);
  expect(state.readCalls()).toHaveLength(0);
  state.visibility.mockReturnValue("visible");
  fireEvent(document, new Event("visibilitychange"));
  await waitFor(() => expect(state.readCalls()).toHaveLength(1));
});

it("retains unread on acknowledgement failure and retries the write without polling", async () => {
  const state = setup({ completed: true, focused: false });
  state.setReadOverride(async () => new Response(JSON.stringify({ detail: "offline" }), { status: 503 }));
  render(<App />);
  await screen.findByRole("img", { name: "Unread result" });
  vi.useFakeTimers();
  state.focus.mockReturnValue(true);
  await act(async () => { fireEvent.focus(window); });
  expect(state.readCalls()).toHaveLength(1);
  expect(screen.getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  state.setReadOverride();
  const before = state.fetch.mock.calls.filter(([url]) => url === "/api/conversations").length;
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(state.readCalls()).toHaveLength(2);
  expect(screen.queryByRole("img", { name: "Unread result" })).not.toBeInTheDocument();
  expect(state.fetch.mock.calls.filter(([url]) => url === "/api/conversations")).toHaveLength(before);
});

it("keeps one SSE connection while idle and replaces it when a hidden tab returns", async () => {
  const state = setup();
  const { unmount } = render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
  const first = MockEventSource.instances[0];
  expect(first.url).toBe("/api/conversations/events");
  const count = state.fetch.mock.calls.length;
  vi.useFakeTimers();
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(state.fetch.mock.calls).toHaveLength(count);
  fireEvent.focus(window);
  fireEvent.blur(window);
  expect(MockEventSource.instances).toHaveLength(1);
  expect(state.fetch.mock.calls).toHaveLength(count);
  state.visibility.mockReturnValue("hidden");
  fireEvent(document, new Event("visibilitychange"));
  expect(first.readyState).toBe(2);
  state.conversations[1].active_run = null;
  state.conversations[1].has_unread = true;
  state.conversations[1].latest_finished_run = { id: "rb", status: "completed" };
  state.visibility.mockReturnValue("visible");
  fireEvent(document, new Event("visibilitychange"));
  expect(MockEventSource.instances).toHaveLength(2);
  await state.notify();
  expect(screen.getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  // Buffered events from the closed connection cannot replace the new snapshot.
  await act(async () => { first.snapshot([]); });
  expect(screen.getByRole("button", { name: "Second chat" })).toBeInTheDocument();
  unmount();
  expect(MockEventSource.instances[1].readyState).toBe(2);
});

it("uses SSE activity in search results without rerunning the search on every snapshot", async () => {
  const state = setup();
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  const search = screen.getByRole("searchbox", { name: "Search history" });
  fireEvent.change(search, { target: { value: "chat" } });
  await waitFor(() => expect(state.fetch.mock.calls.some(([url]) => String(url).includes("?q=chat"))).toBe(true));
  const before = state.fetch.mock.calls.filter(([url]) => String(url).includes("?q=")).length;
  state.conversations[1].active_run = null;
  state.conversations[1].latest_finished_run = { id: "rb", status: "stopped" };
  state.conversations[1].has_unread = true;
  await state.notify();
  const row = screen.getAllByRole("button", { name: "Second chat" })[0];
  expect(within(row).getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  expect(state.fetch.mock.calls.filter(([url]) => String(url).includes("?q=")).length).toBe(before);
});

it("retains state on disconnect and accepts an authoritative snapshot after reconnect", async () => {
  const state = setup();
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
  const connection = MockEventSource.instances[0];
  const count = state.fetch.mock.calls.length;
  await act(async () => { connection.dispatchEvent(new Event("error")); });
  expect(screen.getByRole("img", { name: "Waiting for approval" })).toBeInTheDocument();
  expect(state.fetch.mock.calls).toHaveLength(count);
  // Native EventSource reconnects on the same object; the server sends a new snapshot.
  state.conversations[1].active_run = null;
  state.conversations[1].has_unread = true;
  state.conversations[1].latest_finished_run = { id: "rb", status: "failed" };
  await state.notify();
  expect(screen.getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  expect(MockEventSource.instances).toHaveLength(1);
});

it("ignores an older GET after SSE while still refreshing search after a mutation", async () => {
  const state = setup({ completed: true, focused: false });
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
  fireEvent.change(screen.getByRole("searchbox", { name: "Search history" }), { target: { value: "chat" } });
  await waitFor(() => expect(state.fetch.mock.calls.some(([url]) => String(url).includes("?q=chat"))).toBe(true));
  const searches = state.fetch.mock.calls.filter(([url]) => String(url).includes("?q=chat")).length;
  const old = JSON.stringify(state.conversations);
  let resolveList: (response: Response) => void = () => {};
  state.setListOverride(() => new Promise((resolve) => { resolveList = resolve; }));
  // Deleting a completed chat starts an explicit list refresh.
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete First chat" })); });
  state.conversations.shift();
  state.conversations[0].title = "New title from SSE";
  await state.notify();
  await act(async () => { resolveList(new Response(old)); });
  expect((await screen.findAllByRole("button", { name: "New title from SSE" })).length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: "First chat" })).not.toBeInTheDocument();
  expect(state.fetch.mock.calls.filter(([url]) => String(url).includes("?q=chat")).length).toBeGreaterThan(searches);
});

it("keeps a newer result unread when it finishes during an acknowledgement", async () => {
  const state = setup({ completed: true });
  let acknowledge: (response: Response) => void = () => {};
  state.setReadOverride(() => new Promise((resolve) => { acknowledge = resolve; }));
  render(<App />);
  await waitFor(() => expect(state.readCalls()).toHaveLength(1));
  expect(screen.getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  state.conversations[0].latest_finished_run = { id: "ra2", status: "failed" };
  await act(async () => { acknowledge(new Response(JSON.stringify(state.conversations[0]))); });
  expect(screen.getByRole("img", { name: "Unread result" })).toBeInTheDocument();
  expect(state.readCalls()).toHaveLength(1);
});

it("aggregates unread and running together while prioritizing the spinner on chat rows", async () => {
  const state = setup();
  state.conversations[1].has_unread = true;
  state.conversations[1].latest_finished_run = { id: "older", status: "completed" };
  render(<App />);
  await screen.findByRole("heading", { name: "First chat" });
  const beta = screen.getByRole("button", { name: "Expand Beta" });
  expect(within(beta).getByRole("img", { name: "1 active chats" })).toBeInTheDocument();
  expect(within(beta).getByRole("img", { name: "1 unread results" })).toBeInTheDocument();
  const row = screen.getByRole("button", { name: "Second chat" });
  expect(within(row).getByRole("img", { name: "Waiting for approval" })).toBeInTheDocument();
  expect(within(row).queryByRole("img", { name: "Unread result" })).not.toBeInTheDocument();
  fireEvent.click(beta);
  expect(screen.queryByRole("img", { name: "1 active chats" })).not.toBeInTheDocument();
});
