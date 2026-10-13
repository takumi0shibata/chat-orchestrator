import { useEffect, useState } from "react";
import { api } from "./api";

interface Connection {
  connected: boolean;
  plan_usage: boolean;
  email: string | null;
  login_status: "idle" | "pending" | "completed" | "failed";
  error: string | null;
}

export function ChatGPTConnection({ onRefresh, onBack }: {
  onRefresh: () => Promise<void>;
  onBack: () => void;
}) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
    setBusy(true); setError("");
    try {
      const { authorization_url } = await api<{ authorization_url: string }>("/auth/chatgpt/login", { method: "POST" });
      popup.location.href = authorization_url;
      setConnection(await api<Connection>("/auth/chatgpt"));
    } catch (e) { popup.close(); setError(String(e)); }
    finally { setBusy(false); }
  }

  async function action(path: "logout" | "cancel") {
    setBusy(true); setError("");
    try {
      setConnection(await api<Connection>(`/auth/chatgpt/${path}`, { method: "POST" }));
      await onRefresh();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  async function refresh() {
    setBusy(true); setError("");
    try { setConnection(await api<Connection>("/auth/chatgpt")); await onRefresh(); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  const pending = connection?.login_status === "pending";
  const enabled = connection?.connected && connection.plan_usage;
  const status = pending ? "Awaiting sign-in" : enabled ? "Connected" : connection?.connected ? "Permission needed" : connection ? "Not connected" : "Loading…";
  return <section className="settings-page chatgpt-page">
    <button className="settings-back" type="button" onClick={onBack}>← Settings</button>
    <h1>ChatGPT connection</h1>
    <p className="settings-description">Use your ChatGPT plan for chats in this app.</p>
    <div className="chatgpt-card" aria-label="ChatGPT account">
      <div className="chatgpt-card-heading">
        <div className="chatgpt-account-mark" aria-hidden="true">C</div>
        <div className="chatgpt-account-info">
          <h2>ChatGPT</h2>
          <p>{connection?.connected ? connection.email || "Your ChatGPT account" : "Connect your account"}</p>
        </div>
        <span className={`chatgpt-status${enabled ? " is-connected" : ""}`}>{status}</span>
      </div>
      <div className="chatgpt-card-body">
        <p>{pending ? "Complete sign-in in the browser tab that opened. This page will update automatically." : enabled ? "Your plan is ready. Select ChatGPT as the provider in a new chat." : connection?.connected ? "Your account is connected, but permission to use your plan is missing. Reconnect and allow ChatGPT plan usage." : "Sign in and allow this app to use your ChatGPT plan. An eligible account is required."}</p>
        <div className="chatgpt-actions">
          {!enabled && !pending && <button className="settings-primary" type="button" disabled={busy || !connection} onClick={() => void signIn()}>Continue with ChatGPT</button>}
          {enabled && !pending && <>
            <a className="chatgpt-manage" href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer">Manage usage ↗</a>
            <button className="settings-secondary" type="button" disabled={busy} onClick={() => void signIn()}>Reconnect</button>
          </>}
          {pending && <button className="settings-secondary" type="button" disabled={busy} onClick={() => void action("cancel")}>Cancel sign-in</button>}
          {connection?.connected && !pending && <button className="settings-secondary" type="button" disabled={busy} onClick={() => void action("logout")}>Disconnect</button>}
          {!connection && error && <button className="settings-secondary" type="button" disabled={busy} onClick={() => void refresh()}>Try again</button>}
        </div>
        {busy && <p className="chatgpt-feedback" role="status">Updating connection…</p>}
        {(error || connection?.error) && <p className="chatgpt-error" role="alert">{error || connection?.error}</p>}
      </div>
    </div>
    <p className="chatgpt-footnote">ChatGPT plan usage is separate from API billing. Your OpenAI and Azure connections are available independently.</p>
    {connection?.connected && <p className="chatgpt-footnote">Disconnect removes the connection from this app. You can also manage app access in ChatGPT settings.</p>}
  </section>;
}
