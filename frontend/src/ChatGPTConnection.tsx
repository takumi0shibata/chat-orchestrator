import { useEffect, useState } from "react";
import { api } from "./api";
import type { Model } from "./types";

interface Connection {
  connected: boolean;
  plan_usage: boolean;
  email: string | null;
  login_status: "idle" | "pending" | "completed" | "failed";
  error: string | null;
}

export function ChatGPTConnection({ models, onRefresh }: {
  models: Model[];
  onRefresh: () => Promise<void>;
}) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const [selected, setSelected] = useState("");
  const model = models.some((item) => item.id === selected) ? selected : models[0]?.id || "";

  useEffect(() => {
    let alive = true;
    api<Connection>("/auth/chatgpt").then((value) => alive && setConnection(value))
      .catch((e) => alive && setError(String(e)));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (connection?.login_status !== "pending") return;
    let alive = true;
    let polling = false;
    const timer = window.setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await api<Connection>("/auth/chatgpt");
        if (!alive) return;
        setConnection(next);
        if (next.login_status !== "pending") await onRefresh();
      } catch (e) { if (alive) setError(String(e)); }
      finally { polling = false; }
    }, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [connection?.login_status, onRefresh]);

  async function signIn() {
    // Open synchronously to preserve the browser's user gesture for popup blockers.
    const popup = window.open("about:blank", "_blank");
    if (!popup) { setError("Allow popups to continue with ChatGPT."); return; }
    popup.opener = null;
    setBusy(true); setError(""); setResult("");
    try {
      const { authorization_url } = await api<{ authorization_url: string }>("/auth/chatgpt/login", { method: "POST" });
      popup.location.href = authorization_url;
      setConnection(await api<Connection>("/auth/chatgpt"));
    } catch (e) { popup.close(); setError(String(e)); }
    finally { setBusy(false); }
  }

  async function action(path: "logout" | "cancel" | "test", kind: "response" | "compact" = "response") {
    setBusy(true); setError(""); setResult("");
    try {
      if (path === "test") {
        const value = await api<{ completed: boolean; text: string }>("/auth/chatgpt/test", {
          method: "POST", body: JSON.stringify({ model, kind }),
        });
        setResult(value.completed ? `${kind === "compact" ? "Compact + continuation" : "Response"}: ${value.text}` : "The response did not complete.");
      } else {
        setConnection(await api<Connection>(`/auth/chatgpt/${path}`, { method: "POST" }));
        await onRefresh();
      }
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  const pending = connection?.login_status === "pending";
  return <section className="title-model-setting" aria-label="ChatGPT connection">
    <h2>ChatGPT connection</h2>
    <p className="settings-description">Connect an eligible ChatGPT account to use your plan in this local app. API-key and Azure connections remain available.</p>
    {connection?.connected && <p>{connection.email || "ChatGPT account"} · Connected</p>}
    {connection?.connected && <p className="settings-description">{connection.plan_usage ? "ChatGPT plan usage is enabled." : "ChatGPT plan usage was not granted. Reconnect to enable it."}</p>}
    {pending && <p role="status">Complete sign-in in your browser.</p>}
    <div className="settings-actions">
      <button className="settings-primary" type="button" disabled={busy || pending || !connection} onClick={() => void signIn()}>{connection?.connected ? "Reconnect with ChatGPT" : "Continue with ChatGPT"}</button>
      {pending && <button className="settings-secondary" type="button" disabled={busy} onClick={() => void action("cancel")}>Cancel sign-in</button>}
      {connection?.connected && <button className="settings-secondary" type="button" disabled={busy || pending} onClick={() => void action("logout")}>Disconnect ChatGPT</button>}
    </div>
    {connection?.plan_usage && <>
      <div className="title-model-controls"><label>Test model<select aria-label="ChatGPT test model" value={model} disabled={busy || pending} onChange={(e) => setSelected(e.target.value)}>
        {models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label><button className="settings-secondary" type="button" disabled={busy || pending || !model} onClick={() => void action("test")}>Test ChatGPT response</button>
      <button className="settings-secondary" type="button" disabled={busy || pending || !model} onClick={() => void action("test", "compact")}>Test ChatGPT compact</button></div>
      <p className="settings-description">Tests use your ChatGPT plan allowance. Compact calls the native endpoint and checks that a following response remembers the test value. ChatGPT usage is excluded from API cost estimates. Remote MCP is unavailable on this connection.</p>
    </>}
    {busy && <p role="status">Working…</p>}
    {result && <p role="status">Test completed · {result}</p>}
    {(error || connection?.error) && <p role="alert">{error || connection?.error}</p>}
  </section>;
}
