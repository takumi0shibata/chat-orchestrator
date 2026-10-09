import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GuildBoard, type GuildProject, type GuildSnapshot } from "./GuildBoard";

const project: GuildProject = {
  id: "research", label: "研究A", summary: "比較実験が完了", next_action: "比較条件を決める", status: "review",
  tasks: [
    { id: "t1", title: "比較条件を決める", status: "review", due: "2026-10-16", source: "tasks.md", line: 3 },
    { id: "t2", title: "実験を実施", status: "done", due: null, source: "tasks.md", line: 4 },
  ],
  documents: [{ path: "tasks.md", content: "<script>alert('test')</script>\n- [ ] 比較条件を決める", updated_at: "2026-10-09T00:00:00Z" }],
  activity: [{ source: "activity/2026-10-09.md", title: "実験が完了", summary: "条件Aに改善", date: "2026-10-09" }],
  synced_at: "2026-10-09T01:00:00Z", updated_at: "2026-10-09T00:00:00Z", fingerprint: "abc", warnings: [], error: null,
};
const snapshot: GuildSnapshot = { synced_at: "2026-10-09T01:00:00Z", projects: [project] };
const response = (body: unknown) => new Response(JSON.stringify(body));
afterEach(() => vi.restoreAllMocks());

it("loads only the cached snapshot, then syncs explicitly and removes opted-out projects", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(snapshot)).mockResolvedValueOnce(response({ synced_at: "2026-10-09T02:00:00Z", projects: [] }));
  render(<GuildBoard onOpenProject={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Open quest log for 研究A" })).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/guild");
  fireEvent.click(screen.getByRole("button", { name: "Sync" }));
  expect(await screen.findByText("Your first quest awaits")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][0]).toBe("/api/guild/sync");
  expect(fetch.mock.calls[1][1]?.method).toBe("POST");
  expect(screen.queryByRole("button", { name: "Open quest log for 研究A" })).not.toBeInTheDocument();
});

it("filters projects, exposes source text safely and opens the selected project's chat", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response(snapshot));
  const open = vi.fn();
  const { container } = render(<GuildBoard onOpenProject={open} />);
  await screen.findByRole("button", { name: "Open quest log for 研究A" });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "存在しない" } });
  expect(screen.getByText("No quests match your search.")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "比較条件" } });
  fireEvent.click(screen.getByRole("button", { name: "Open quest log for 研究A" }));
  expect(screen.getByRole("heading", { name: "研究A" })).toHaveFocus();
  expect(screen.queryByText("実験を実施")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "Show completed (1)" }));
  expect(screen.getByText("実験を実施")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "tasks.md:3" }));
  expect(screen.getByRole("region", { name: "Source record" })).toHaveTextContent("<script>");
  expect(container.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Open project chat" }));
  await waitFor(() => expect(open).toHaveBeenCalledWith("research"));
  fireEvent.click(screen.getByRole("button", { name: "Back to the board" }));
  expect(screen.getByRole("heading", { name: "Guild Board" })).toHaveFocus();
});

it("keeps the current board on a network failure and allows retry", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(snapshot)).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response(snapshot));
  render(<GuildBoard onOpenProject={vi.fn()} />);
  await screen.findByRole("button", { name: "Open quest log for 研究A" });
  fireEvent.click(screen.getByRole("button", { name: "Sync" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  expect(screen.getByRole("button", { name: "Open quest log for 研究A" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Sync" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});

it("shows partial failures as stale instead of hiding previous tasks", async () => {
  const stale = { ...project, error: "Save this file as UTF-8." };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ ...snapshot, projects: [stale] }));
  render(<GuildBoard onOpenProject={vi.fn()} />);
  const card = await screen.findByRole("button", { name: "Open quest log for 研究A" });
  expect(within(card).getByText("Sync failed · showing saved records")).toBeInTheDocument();
  fireEvent.click(card);
  expect(screen.getByRole("alert")).toHaveTextContent("Showing the last successful sync");
  expect(screen.getByRole("button", { name: "tasks.md:3" })).toBeInTheDocument();
});
