import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TextFileEditor } from "./TextFileEditor";

afterEach(() => vi.restoreAllMocks());

const original = { path: "notes/日本語.md", content: "# Original\n", revision: "a".repeat(64), size: 11 };

it("loads text, saves with its revision, and uses the new revision for the next save", async () => {
  const onSaved = vi.fn();
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
    if (options?.method === "PUT") return new Response(JSON.stringify({ ...original,
      content: JSON.parse(String(options.body)).content, revision: "b".repeat(64),
    }));
    return new Response(JSON.stringify(original));
  });
  render(<TextFileEditor conversationId="c" path={original.path} onClose={vi.fn()} onSaved={onSaved} />);
  const editor = await screen.findByRole("textbox", { name: "File content" });
  expect(editor).toHaveValue(original.content);
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  fireEvent.change(editor, { target: { value: "# 編集\n" } });
  expect(screen.getByRole("status")).toHaveTextContent("Unsaved changes");
  fireEvent.keyDown(editor, { key: "s", metaKey: true });
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenLastCalledWith(`/api/conversations/c/file?path=${encodeURIComponent(original.path)}`, expect.objectContaining({
    method: "PUT", body: JSON.stringify({ content: "# 編集\n", revision: original.revision }),
  }));
  expect(screen.getByRole("status")).toHaveTextContent("Saved");
  fireEvent.change(editor, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2));
  expect(fetch).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({
    body: JSON.stringify({ content: "", revision: "b".repeat(64) }),
  }));
});

it("keeps edits after a conflict and confirms closing, Escape, reloading, and page unload", async () => {
  const onClose = vi.fn();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  let reads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
    if (options?.method === "PUT") return new Response(JSON.stringify({ detail: "This file changed since it was opened." }), { status: 409 });
    return new Response(JSON.stringify({ ...original, content: ++reads === 1 ? original.content : "external edits" }));
  });
  render(<TextFileEditor conversationId="c" path={original.path} onClose={onClose} onSaved={vi.fn()} />);
  const editor = await screen.findByRole("textbox", { name: "File content" });
  fireEvent.change(editor, { target: { value: "my edits" } });
  fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
  expect(await screen.findByRole("alert")).toHaveTextContent("This file changed");
  expect(editor).toHaveValue("my edits");
  fireEvent.click(screen.getByRole("button", { name: "Close file editor" }));
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Reload" }));
  expect(reads).toBe(1);
  const unload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Reload" }));
  await waitFor(() => expect(editor).toHaveValue("external edits"));
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  fireEvent.change(editor, { target: { value: "discard this" } });
  fireEvent.click(screen.getByRole("button", { name: "Close file editor" }));
  expect(onClose).toHaveBeenCalledOnce();
});

it("prevents duplicate saves and closing during a pending write", async () => {
  let finish!: (value: Response) => void;
  const onClose = vi.fn();
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
    if (options?.method === "PUT") return new Promise<Response>((resolve) => { finish = resolve; });
    return new Response(JSON.stringify(original));
  });
  render(<TextFileEditor conversationId="c" path={original.path} onClose={onClose} onSaved={vi.fn()} />);
  const editor = await screen.findByRole("textbox", { name: "File content" });
  fireEvent.change(editor, { target: { value: "changed" } });
  fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
  fireEvent.keyDown(editor, { key: "s", ctrlKey: true });
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }));
  expect(editor).toHaveAttribute("readonly");
  expect(onClose).not.toHaveBeenCalled();
  expect(fetch.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(1);
  await act(async () => finish(new Response(JSON.stringify({ ...original, content: "changed" }))));
  expect(editor).not.toHaveAttribute("readonly");
});

it("offers a download and retry when a file cannot be edited", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "This file type is not supported." }), { status: 400 }));
  render(<TextFileEditor conversationId="c" path="report.docx" onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("not supported");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/conversations/c/download?path=report.docx");
});
