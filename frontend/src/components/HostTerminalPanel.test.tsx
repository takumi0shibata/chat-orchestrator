import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ terminals: [] as Array<{ input?: (data: string) => void }> }));

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 80;
    rows = 24;
    input?: (data: string) => void;
    constructor() { mocks.terminals.push(this); }
    loadAddon() {}
    open() {}
    write() {}
    writeln() {}
    dispose() {}
    onData(callback: (data: string) => void) { this.input = callback; return { dispose() {} }; }
    onBinary() { return { dispose() {} }; }
  },
}));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: class { fit() {} } }));

import { HostTerminalPanel } from "./HostTerminalPanel";

class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  binaryType = "";
  sent: Array<string | ArrayBufferLike | Blob | ArrayBufferView> = [];
  closed = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) { FakeWebSocket.instances.push(this); }
  send(value: string | ArrayBufferLike | Blob | ArrayBufferView) { this.sent.push(value); }
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.closed = true; this.readyState = 3; this.onclose?.(); }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  mocks.terminals = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(240);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => window.setTimeout(callback, 0));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("keeps tabs independent, sends input and resize, and closes each socket", async () => {
  const onClose = vi.fn();
  const onHeightChange = vi.fn();
  const { unmount } = render(<HostTerminalPanel workspaceId="work" workspacePath="/work"
    height={300} onHeightChange={onHeightChange} onClose={onClose} />);
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
  const first = FakeWebSocket.instances[0];
  expect(first.url).toContain("/api/terminals/work");
  first.open();
  expect(JSON.parse(first.sent[0] as string)).toEqual({ type: "init", cols: 80, rows: 24 });
  mocks.terminals[0].input?.("日本語\n");
  expect(new TextDecoder().decode(first.sent[1] as Uint8Array)).toBe("日本語\n");

  fireEvent.click(screen.getByRole("button", { name: "Add terminal" }));
  await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
  const second = FakeWebSocket.instances[1];
  second.open();
  fireEvent.click(screen.getByRole("tab", { name: "Terminal 1" }));
  await waitFor(() => expect(first.sent.some((value) =>
    typeof value === "string" && JSON.parse(value).type === "resize")).toBe(true));
  fireEvent.keyDown(screen.getByRole("separator", { name: "Resize terminal" }), { key: "ArrowUp" });
  expect(onHeightChange).toHaveBeenCalledWith(316);

  fireEvent.click(screen.getByRole("button", { name: "Close terminal 2" }));
  expect(second.closed).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Close terminal 1" }));
  expect(onClose).toHaveBeenCalledOnce();
  unmount();
  expect(first.closed).toBe(true);
});
