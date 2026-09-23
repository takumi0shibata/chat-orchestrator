import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";

type TabStatus = "connecting" | "running" | "exited" | "error";
type Tab = { id: number; generation: number; status: TabStatus; code?: number };

function socketUrl(workspaceId: string) {
  const url = new URL(`/api/terminals/${encodeURIComponent(workspaceId)}`, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function TerminalView({ workspaceId, active, onStatus }: {
  workspaceId: string;
  active: boolean;
  onStatus: (status: TabStatus, code?: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const activeRef = useRef(active);
  const fitRef = useRef<(() => void) | null>(null);

  useLayoutEffect(() => {
    activeRef.current = active;
    if (active) fitRef.current?.();
  }, [active]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const terminal = new Terminal({
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: 13,
      scrollback: 5000,
      theme: { background: "#17191e", foreground: "#e6e7ea", cursor: "#e6e7ea" },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(element);
    const socket = new WebSocket(socketUrl(workspaceId));
    socket.binaryType = "arraybuffer";
    const encoder = new TextEncoder();
    let initialized = false;
    let ended = false;
    let frame = 0;

    const fitAndSend = () => {
      if (!activeRef.current || !element.clientWidth || !element.clientHeight) return;
      fit.fit();
      if (socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({
        type: initialized ? "resize" : "init", cols: terminal.cols, rows: terminal.rows,
      }));
      initialized = true;
    };
    const scheduleFit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fitAndSend);
    };
    fitRef.current = scheduleFit;
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(scheduleFit);
    observer?.observe(element);
    socket.onopen = () => {
      if (activeRef.current) fitAndSend();
      if (!initialized) {
        socket.send(JSON.stringify({ type: "init", cols: 80, rows: 24 }));
        initialized = true;
      }
      onStatus("running");
    };
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const message = JSON.parse(event.data) as { type: string; code?: number; message?: string };
          if (message.type === "exit") {
            ended = true;
            terminal.writeln(`\r\n[Process exited${message.code == null ? "" : `: ${message.code}`}]`);
            onStatus("exited", message.code);
          } else if (message.type === "error") {
            ended = true;
            terminal.writeln(`\r\n[${message.message || "Terminal error"}]`);
            onStatus("error");
          }
        } catch {
          terminal.writeln("\r\n[Invalid terminal response]");
          onStatus("error");
        }
      } else {
        terminal.write(new Uint8Array(event.data as ArrayBuffer));
      }
    };
    socket.onerror = () => {
      if (!ended) onStatus("error");
    };
    socket.onclose = () => {
      if (!ended) {
        terminal.writeln("\r\n[Terminal connection closed]");
        onStatus("error");
      }
    };
    const sendInput = (bytes: Uint8Array) => {
      if (socket.readyState !== WebSocket.OPEN || ended) return;
      for (let offset = 0; offset < bytes.length; offset += 65536) {
        socket.send(bytes.slice(offset, offset + 65536));
      }
    };
    const dataListener = terminal.onData((data) => sendInput(encoder.encode(data)));
    const binaryListener = terminal.onBinary((data) => {
      sendInput(Uint8Array.from(data, (character) => character.charCodeAt(0)));
    });
    scheduleFit();
    return () => {
      ended = true;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      fitRef.current = null;
      dataListener.dispose();
      binaryListener.dispose();
      socket.close();
      terminal.dispose();
    };
  }, [workspaceId]);

  return <div ref={container} className="terminal-surface" />;
}

export function HostTerminalPanel({ workspaceId, workspacePath, height, onHeightChange, onClose }: {
  workspaceId: string;
  workspacePath: string;
  height: number;
  onHeightChange: (height: number) => void;
  onClose: () => void;
}) {
  const nextId = useRef(2);
  const [tabs, setTabs] = useState<Tab[]>([{ id: 1, generation: 0, status: "connecting" }]);
  const [activeId, setActiveId] = useState(1);
  const activeTab = tabs.find((tab) => tab.id === activeId);

  const addTab = () => {
    if (tabs.length >= 8) return;
    const id = nextId.current++;
    setTabs((previous) => [...previous, { id, generation: 0, status: "connecting" }]);
    setActiveId(id);
  };
  const closeTab = (id: number) => {
    if (tabs.length === 1) {
      onClose();
      return;
    }
    const index = tabs.findIndex((tab) => tab.id === id);
    const remaining = tabs.filter((tab) => tab.id !== id);
    setTabs(remaining);
    if (activeId === id) setActiveId(remaining[Math.min(index, remaining.length - 1)].id);
  };
  const updateStatus = (id: number, status: TabStatus, code?: number) => {
    setTabs((previous) => previous.map((tab) => tab.id === id ? { ...tab, status, code } : tab));
  };
  const restart = () => {
    setTabs((previous) => previous.map((tab) => tab.id === activeId
      ? { ...tab, generation: tab.generation + 1, status: "connecting", code: undefined }
      : tab));
  };

  return <section className="terminal-panel" aria-label="Host terminal">
    <div className="terminal-resizer" role="separator" aria-label="Resize terminal" aria-orientation="horizontal"
      aria-valuemin={120} aria-valuemax={Math.round(window.innerHeight * 0.7)} aria-valuenow={height} tabIndex={0}
      onPointerDown={(event) => { if (event.button === 0) event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) onHeightChange(window.innerHeight - event.clientY);
      }}
      onPointerUp={(event) => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
      onKeyDown={(event) => {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        onHeightChange(height + (event.key === "ArrowUp" ? 16 : -16));
      }} />
    <div className="terminal-toolbar">
      <span className="terminal-heading">Host terminal</span>
      <div className="terminal-tabs" role="tablist" aria-label="Terminal tabs">
        {tabs.map((tab) => <div className="terminal-tab" key={tab.id}>
          <button type="button" role="tab" aria-selected={tab.id === activeId} aria-controls={`terminal-tab-${tab.id}`}
            onClick={() => setActiveId(tab.id)}>Terminal {tab.id}{tab.status === "exited" ? " · exited" : ""}</button>
          <button type="button" className="terminal-tab-close" aria-label={`Close terminal ${tab.id}`}
            onClick={() => closeTab(tab.id)}>×</button>
        </div>)}
      </div>
      <button type="button" className="terminal-add" aria-label="Add terminal" title="Add terminal" disabled={tabs.length >= 8} onClick={addTab}>＋</button>
      {(activeTab?.status === "exited" || activeTab?.status === "error") &&
        <button type="button" className="terminal-restart" onClick={restart}>Restart</button>}
      <button type="button" className="terminal-panel-close" aria-label="Close terminal panel" onClick={onClose}>×</button>
    </div>
    <div className="terminal-workspace" title={workspacePath}>{workspacePath}</div>
    <div className="terminal-content">
      {tabs.map((tab) => <div key={`${tab.id}:${tab.generation}`} id={`terminal-tab-${tab.id}`}
        role="tabpanel" aria-label={`Terminal ${tab.id}`} className="terminal-tab-content" hidden={tab.id !== activeId}>
        <TerminalView workspaceId={workspaceId} active={tab.id === activeId}
          onStatus={(status, code) => updateStatus(tab.id, status, code)} />
      </div>)}
    </div>
  </section>;
}
