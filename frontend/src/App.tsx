import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { api, events } from "./api";
import { MarkdownContent } from "./components/MarkdownContent";
import { terminal } from "./types";
import type {
  AgentEvent,
  Attachment,
  Config,
  Conversation,
  Named,
  Run,
  WorkspaceFile,
} from "./types";

const statusLabels: Record<string, string> = {
  preparing: "Preparing",
  model_wait: "Waiting for model",
  command_running: "Running command",
  approval_wait: "Approval needed",
  completed: "Completed",
  failed: "Failed",
  stopped: "Stopped",
};
const text = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value ?? "");
const legacySystemLabels: Record<string, string> = {
  "準備中": "Preparing",
  "モデル応答待ち": "Waiting for model",
  "コマンドを実行しています": "Running command",
  "次の操作を判断しています": "Deciding the next action",
  "作業が完了しました": "Work completed",
  "作業フォルダの実行順を待っています": "Waiting for workspace availability",
  "サンドボックスを起動しています": "Starting sandbox",
  "長い会話の作業文脈を整理しています": "Organizing conversation context",
  "作業文脈を圧縮しました": "Conversation context compacted",
  "外部ツールの実行承認を待っています": "Waiting for external tool approval",
  "停止しました。既に反映された変更は残ります": "Stopped. Applied changes remain.",
  "実行時間の上限に達しました。変更済みファイルは保持されます": "Time limit reached. Modified files remain.",
  "実行に失敗しました。履歴を確認してください": "Run failed. Check the activity log.",
};
const systemText = (value: unknown) => legacySystemLabels[text(value)] || text(value);

function Icon({ name, size = 18 }: { name: "refresh" | "paperclip" | "globe" | "check" | "close" | "spark"; size?: number }) {
  const paths = {
    refresh: <><path d="M20 11a8 8 0 1 0-2.2 6.4" /><path d="M20 4v7h-7" /></>,
    paperclip: <path d="m20.5 11.5-8.8 8.8a6 6 0 0 1-8.5-8.5l9.5-9.5a4 4 0 0 1 5.7 5.7l-9.5 9.5a2 2 0 0 1-2.8-2.8l8.8-8.8" />,
    globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    close: <path d="M6 6l12 12M18 6 6 18" />,
    spark: <><path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2Z" /><path d="m19 17 .6 1.4L21 19l-1.4.6L19 21l-.6-1.4L17 19l1.4-.6L19 17Z" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function Choices({
  label,
  items,
  selected,
  change,
  disabled,
}: {
  label: string;
  items: Named[];
  selected: string[];
  change: (ids: string[]) => void;
  disabled: boolean;
}) {
  if (!items.length) return null;
  return (
    <fieldset disabled={disabled}>
      <legend>{label}</legend>
      {items.map((item) => (
        <button
          className={`tool-option ${selected.includes(item.id) ? "is-selected" : ""}`}
          key={item.id}
          type="button"
          aria-pressed={selected.includes(item.id)}
          disabled={disabled}
          onClick={() => change(selected.includes(item.id)
            ? selected.filter((id) => id !== item.id)
            : [...selected, item.id])}
        >
          <Icon name="spark" />
          <span>{item.label}</span>
          {selected.includes(item.id) && <Icon name="check" size={16} />}
        </button>
      ))}
    </fieldset>
  );
}

export function RunView({
  run,
  timeline,
  onApproval,
}: {
  run: Run;
  timeline: AgentEvent[];
  onApproval: (id: string, approve: boolean) => Promise<void>;
}) {
  const [clock, setClock] = useState(Date.now());
  const [pending, setPending] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState("");
  useEffect(() => {
    if (terminal(run.status)) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [run.status]);
  const lastStatus = [...timeline].reverse().find((e) => e.type === "status");
  const currentStep = lastStatus ? systemText(lastStatus.data.label) : "Loading activity";
  const answer = timeline
    .filter((e) => e.type === "text_delta")
    .map((e) => text(e.data.text))
    .join("");
  const approvals = timeline.filter(
    (e) =>
      e.type === "approval" &&
      !timeline.some(
        (r) =>
          r.type === "approval_resolved" && r.data.request_id === e.data.id,
      ),
  );
  const seconds = Math.max(
    0,
    Math.round(
      ((terminal(run.status) ? Date.parse(run.updated_at) : clock) -
        Date.parse(run.created_at)) /
        1000,
    ),
  );
  async function approve(id: string, yes: boolean) {
    setPending(id);
    setApprovalError("");
    try {
      await onApproval(id, yes);
    } catch (e) {
      setApprovalError(String(e));
    } finally {
      setPending(null);
    }
  }
  return (
    <article className="turn">
      <div className="user-message">
        <span className="eyebrow">YOU</span>
        <p>{run.request.input || "Work with attached files"}</p>
        {run.request.attachment_ids.length > 0 && (
          <small>{run.request.attachment_ids.length} attachments</small>
        )}
      </div>
      <div className="assistant-message">
        <div className="run-heading">
          <span className={`status ${run.status}`}>
            <i />
            {statusLabels[run.status] || run.status}
          </span>
          <span className="muted">
            {run.request.model} · {seconds}s
          </span>
        </div>
        {!terminal(run.status) && currentStep !== statusLabels[run.status] && (
          <div className="current-step" role="status">
            {currentStep}
          </div>
        )}
        {answer && <MarkdownContent content={answer} />}
        {!terminal(run.status) &&
          approvals.map((e) => (
            <div className="approval" key={e.seq}>
              <strong>Approve external tool</strong>
              <p>
                {text(e.data.server_label)} / {text(e.data.name)}
              </p>
              <pre>{text(e.data.arguments)}</pre>
              <button
                disabled={pending !== null}
                onClick={() => void approve(text(e.data.id), true)}
              >
                Allow
              </button>
              <button
                disabled={pending !== null}
                onClick={() => void approve(text(e.data.id), false)}
              >
                Deny
              </button>
            </div>
          ))}
        {approvalError && (
          <p role="alert" className="error">
            {approvalError}
          </p>
        )}
        {timeline
          .filter((e) => e.type === "error")
          .map((e) => (
            <p role="alert" className="error" key={e.seq}>
              {text(e.data.message)}
            </p>
          ))}
        {timeline
          .filter((e) => e.type === "artifacts")
          .map((e) => (
            <div className="artifact-list" key={e.seq}>
              {((e.data.files as { path: string; change: string }[]) || []).map(
                (f) =>
                  f.change === "deleted" ? (
                    <span key={f.path}>{f.path} · deleted</span>
                  ) : (
                    <a
                      key={f.path}
                      href={`/api/conversations/${run.conversation_id}/download?path=${encodeURIComponent(f.path)}`}
                      download
                    >
                      ▤ {f.path} · {f.change === "created" ? "created" : "updated"} ↓
                    </a>
                  ),
              )}
            </div>
          ))}
        <details className="activity">
          <summary>
            Activity{" "}
            <span>
              {timeline.filter((e) => e.type === "command").length} commands
            </span>
          </summary>
          <div className="activity-body">
            {timeline
              .filter((e) => !["text_delta", "command_output"].includes(e.type))
              .map((e) => {
                if (e.type === "command") {
                  const output = timeline.filter(
                    (o) =>
                      o.type === "command_output" &&
                      o.data.call_id === e.data.call_id &&
                      o.data.index === e.data.index,
                  );
                  const done = timeline.find(
                    (o) =>
                      o.type === "command_done" &&
                      o.data.call_id === e.data.call_id &&
                      o.data.index === e.data.index,
                  );
                  return (
                    <div className="command" key={e.seq}>
                      <pre className="command-code">
                        $ {text(e.data.command)}
                      </pre>
                      {output.length > 0 && (
                        <pre className="command-output">
                          {output.map((o) => text(o.data.text)).join("")}
                        </pre>
                      )}
                      <small>
                        {done
                          ? `${text(done.data.outcome)} · ${Number(done.data.elapsed).toFixed(1)}s`
                          : terminal(run.status)
                            ? "Interrupted"
                            : "Running…"}
                      </small>
                    </div>
                  );
                }
                if (e.type === "command_done") return null;
                return (
                  <div className="activity-row" key={e.seq}>
                    <time>{new Date(e.created_at).toLocaleTimeString()}</time>
                    <span>
                      {systemText(
                        e.data.label || e.data.message || e.data.name || e.type,
                      )}
                    </span>
                    {e.type === "tool_result" && (
                      <pre>
                        {text(e.data.output || e.data.error || e.data.status)}
                      </pre>
                    )}
                  </div>
                );
              })}
          </div>
        </details>
      </div>
    </article>
  );
}

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [cid, setCid] = useState(
    localStorage.getItem("workspace-conversation") || "",
  );
  const [workspace, setWorkspace] = useState("");
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-5.6-sol");
  const [effort, setEffort] = useState("medium");
  const [skills, setSkills] = useState<string[]>([]);
  const [resources, setResources] = useState<string[]>([]);
  const [mcps, setMcps] = useState<string[]>([]);
  const [web, setWeb] = useState(false);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [direct, setDirect] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [timelines, setTimelines] = useState<Record<string, AgentEvent[]>>({});
  const [revision, setRevision] = useState(0);
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [folder, setFolder] = useState("");
  const [showFiles, setShowFiles] = useState(false);
  const [fileRevision, setFileRevision] = useState(0);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const [busy, setBusy] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [loadedCid, setLoadedCid] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const plusWrap = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const current = conversations.find((c) => c.id === cid);
  const currentWorkspace = config?.workspaces.find(
    (w) => w.id === (current?.workspace_id || workspace),
  );
  const activeRun = runs.find((r) => !terminal(r.status));
  const active = Boolean(activeRun);
  const selectedProvider = config?.providers.find((p) => p.id === provider);
  const configReady = Boolean(config);
  const models = selectedProvider?.models || [];
  const selectedModel = models.find((m) => m.id === model);
  const selectedTools = [
    ...(web ? [{ key: "web", label: "Web Search", icon: "globe" as const, remove: () => setWeb(false) }] : []),
    ...skills.map((id) => ({ key: `skill-${id}`, label: config?.skills.find((item) => item.id === id)?.label || id, icon: "spark" as const, remove: () => setSkills((old) => old.filter((value) => value !== id)) })),
    ...resources.map((id) => ({ key: `resource-${id}`, label: config?.resources.find((item) => item.id === id)?.label || id, icon: "spark" as const, remove: () => setResources((old) => old.filter((value) => value !== id)) })),
    ...mcps.map((id) => ({ key: `mcp-${id}`, label: config?.mcp_servers.find((item) => item.id === id)?.label || id, icon: "spark" as const, remove: () => setMcps((old) => old.filter((value) => value !== id)) })),
  ];
  const canSend = Boolean(
    selectedProvider?.enabled && selectedModel && cid && loadedCid === cid &&
    !busy && !active && (input.trim() || attachments.length),
  );

  async function refreshConversations() {
    setConversations(await api<Conversation[]>("/conversations"));
  }
  async function refreshConfig() {
    try {
      setConfig(await api<Config>("/config"));
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    let alive = true;
    Promise.all([api<Config>("/config"), api<Conversation[]>("/conversations")])
      .then(([c, cs]) => {
        if (!alive) return;
        setConfig(c);
        setConversations(cs);
        setWorkspace(c.workspaces[0]?.id || "");
        const enabled = c.providers.find((p) => p.enabled && p.models.length);
        if (enabled) {
          setProvider(enabled.id);
          setModel(enabled.models[0].id);
        }
        setCid((old) => (cs.some((x) => x.id === old) ? old : ""));
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem("workspace-conversation", cid);
    const abort = new AbortController();
    setRuns([]);
    setTimelines({});
    setLoadedCid("");
    setConnection("");
    if (!cid || !config) return;
    async function watch(run: Run) {
      let cursor = 0;
      while (!abort.signal.aborted) {
        try {
          await events(run.id, cursor, abort.signal, (event) => {
            if (abort.signal.aborted || event.seq <= cursor) return;
            cursor = event.seq;
            setTimelines((old) => {
              const existing = old[run.id] || [];
              if (existing.some((item) => item.seq === event.seq)) return old;
              return { ...old, [run.id]: [...existing, event] };
            });
            if (event.type === "status") {
              setRuns((old) =>
                old.map((r) =>
                  r.id === run.id
                    ? {
                        ...r,
                        status: text(event.data.status),
                        updated_at: event.created_at,
                      }
                    : r,
                ),
              );
              if (terminal(text(event.data.status)))
                setFileRevision((v) => v + 1);
            }
            setConnection("");
          });
          if (abort.signal.aborted) return;
          const latest = await api<Run>(`/runs/${run.id}`, {
            signal: abort.signal,
          });
          if (terminal(latest.status)) {
            setRuns((old) => old.map((r) => (r.id === run.id ? latest : r)));
            return;
          }
          throw new Error("stream disconnected");
        } catch {
          if (abort.signal.aborted) return;
          setConnection(
            "Reconnecting. The run continues on the server.",
          );
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
      }
    }
    api<Conversation & { runs: Run[] }>(`/conversations/${cid}`, {
      signal: abort.signal,
    })
      .then((c) => {
        if (abort.signal.aborted) return;
        setRuns(c.runs);
        setLoadedCid(cid);
        if (c.runs.length) {
          const last = c.runs[c.runs.length - 1].request;
          setProvider(last.provider);
          setModel(last.model);
          setEffort(last.reasoning_effort);
          setSkills(last.skill_ids);
          setResources(last.resource_ids);
          setMcps(last.mcp_ids);
          setWeb(last.web_search);
        }
        for (const run of c.runs) void watch(run);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(String(e));
      });
    return () => abort.abort();
  }, [cid, revision, configReady]);

  useEffect(() => {
    setFolder("");
    setAttachments([]);
    setDirect([]);
    setInput("");
    setPlusOpen(false);
    setError("");
    follow.current = true;
  }, [cid]);
  useEffect(() => {
    if (!cid) {
      setFiles([]);
      return;
    }
    const abort = new AbortController();
    api<WorkspaceFile[]>(
      `/conversations/${cid}/files?path=${encodeURIComponent(folder)}`,
      { signal: abort.signal },
    )
      .then(setFiles)
      .catch((e) => {
        if (!abort.signal.aborted) setError(String(e));
      });
    return () => abort.abort();
  }, [cid, folder, fileRevision]);
  useEffect(() => {
    if (follow.current) bottom.current?.scrollIntoView?.({ block: "end" });
  }, [timelines]);
  useEffect(() => {
    if (!plusOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (!plusWrap.current?.contains(event.target as Node)) setPlusOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [plusOpen]);

  async function newConversation() {
    setBusy(true);
    setError("");
    try {
      const c = await api<Conversation>("/conversations", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace }),
      });
      await refreshConversations();
      setCid(c.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    setError("");
    setBusy(true);
    follow.current = true;
    try {
      await api<Run>("/runs", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: cid,
          provider,
          model,
          reasoning_effort: effort,
          input,
          attachment_ids: attachments.map((a) => a.id),
          direct_attachment_ids: direct,
          skill_ids: skills,
          resource_ids: resources,
          mcp_ids: mcps,
          web_search: web,
        }),
      });
      setInput("");
      setAttachments([]);
      setDirect([]);
      setRevision((v) => v + 1);
      await refreshConversations();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function handleComposerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    if (canSend) e.currentTarget.form?.requestSubmit();
  }
  async function stopRun() {
    if (!activeRun) return;
    try {
      await api(`/runs/${activeRun.id}/stop`, { method: "POST" });
    } catch (e) {
      setError(String(e));
    }
  }
  async function upload(selected: FileList | null) {
    if (!selected?.length) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("conversation_id", cid);
      Array.from(selected).forEach((f) => body.append("files", f));
      const added = await api<Attachment[]>("/attachments", {
        method: "POST",
        body,
      });
      setAttachments((old) => [...old, ...added]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function removeConversation(id: string) {
    try {
      await api(`/conversations/${id}`, { method: "DELETE" });
      await refreshConversations();
      if (cid === id) setCid("");
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          ◈{" "}
          <span>
            Workspace<span className="brand-sub">RESPONSES AGENT</span>
          </span>
        </a>
        <label className="field-label" htmlFor="workspace">
          Workspace
        </label>
        <select
          id="workspace"
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
        >
          {config?.workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.label}
            </option>
          ))}
        </select>
        <button
          className="new-chat"
          disabled={!workspace || busy}
          onClick={() => void newConversation()}
        >
          + New chat
        </button>
        <div className="eyebrow section-label">History</div>
        <nav>
          {conversations.map((c) => (
            <div
              className={`conversation ${c.id === cid ? "selected" : ""}`}
              key={c.id}
            >
              <button disabled={busy} onClick={() => setCid(c.id)}>
                {c.title}
              </button>
              <button
                className="delete"
                aria-label={`Delete ${c.title}`}
                disabled={busy || (c.id === cid && active)}
                onClick={() => void removeConversation(c.id)}
              >
                ×
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          LOCAL EXECUTION
          <br />
          <span>Docker · Network off · CPU</span>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <h1>{current?.title || "Your workspace"}</h1>
          </div>
          <button
            className="files-toggle"
            type="button"
            aria-expanded={showFiles}
            onClick={() => setShowFiles((v) => !v)}
          >
            Files
          </button>
        </header>
        <div
          className="chat-scroll"
          ref={scroll}
          onScroll={() => {
            const el = scroll.current;
            if (el)
              follow.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < 100;
          }}
        >
          {!cid ? (
            <div className="welcome">
              <div className="welcome-icon">◈</div>
              <h2>Explore, analyze, create.</h2>
              <p>
                Choose a workspace and start a new chat.
                <br />
                Ask the agent to inspect, edit, and check your files.
              </p>
              {!config?.workspaces.length && (
                <p className="setup-note">
                  Copy runtime.example.toml to runtime.toml and set an absolute
                  workspace path.
                </p>
              )}
              <div className="examples">
                <span>Compare papers in a research folder</span>
                <span>Analyze a CSV and save a chart</span>
                <span>Review and edit a Word or Excel file</span>
              </div>
            </div>
          ) : (
            <div className="chat-column">
              {runs.length === 0 && (
                <div className="welcome compact">
                  <h2>What would you like to work on?</h2>
                  <p>Describe the files and the result you want.</p>
                </div>
              )}
              {runs.map((run) => (
                <RunView
                  key={run.id}
                  run={run}
                  timeline={timelines[run.id] || []}
                  onApproval={async (id, approve) => {
                    await api(`/runs/${run.id}/approvals`, {
                      method: "POST",
                      body: JSON.stringify({ request_id: id, approve }),
                    });
                  }}
                />
              ))}
              <div ref={bottom} />
            </div>
          )}
        </div>
        {cid && (
          <form className="composer" onSubmit={submit}>
            {connection && (
              <p className="connection" role="status">
                {connection}
              </p>
            )}
            <div className="composer-box">
              <div className="attachments">
                {attachments.map((a) => (
                  <div className="attachment" key={a.id}>
                    <span>{a.name}</span>
                    {/\.(pdf|png|jpe?g|webp)$/i.test(a.name) && (
                      <label>
                        <input
                          type="checkbox"
                          checked={direct.includes(a.id)}
                          onChange={(e) =>
                            setDirect((old) =>
                              e.target.checked
                                ? [...old, a.id]
                                : old.filter((id) => id !== a.id),
                            )
                          }
                        />
                        Send directly to model
                      </label>
                    )}
                    <button
                      type="button"
                      aria-label={`Remove ${a.name}`}
                      onClick={() => {
                        setAttachments((old) => old.filter((f) => f.id !== a.id));
                        setDirect((old) => old.filter((id) => id !== a.id));
                      }}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
              <textarea
                aria-label="Message"
                placeholder="Ask anything"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleComposerKeyDown}
                disabled={busy || active}
                rows={3}
              />
              <div className="composer-actions">
                <div className="plus-wrap" ref={plusWrap}>
                  <button
                    className="plus-button"
                    type="button"
                    aria-label="Add attachments and tools"
                    aria-expanded={plusOpen}
                    onClick={() => {
                      setPlusOpen((v) => !v);
                      if (!plusOpen) void refreshConfig();
                    }}
                    disabled={active || busy}
                  >
                    +
                  </button>
                  {plusOpen && (
                    <div className="plus-menu" aria-label="Attachments and tools" onKeyDown={(e) => {
                      if (e.key === "Escape") setPlusOpen(false);
                    }}>
                      <button className="tool-option attach-option" type="button" onClick={() => fileInput.current?.click()}>
                        <Icon name="paperclip" />
                        <span>Attach files</span>
                      </button>
                      <button className={`tool-option ${web ? "is-selected" : ""}`} type="button" aria-pressed={web} onClick={() => setWeb((value) => !value)}>
                        <Icon name="globe" />
                        <span>Web Search</span>
                        {web && <Icon name="check" size={16} />}
                      </button>
                      <Choices
                        label="Skills"
                        items={config?.skills || []}
                        selected={skills}
                        change={setSkills}
                        disabled={active}
                      />
                      <Choices
                        label="Resources"
                        items={config?.resources || []}
                        selected={resources}
                        change={setResources}
                        disabled={active}
                      />
                      <Choices
                        label="Remote MCP"
                        items={config?.mcp_servers || []}
                        selected={mcps}
                        change={setMcps}
                        disabled={active}
                      />
                      <label className="provider-choice">
                        Provider
                        <select
                          aria-label="Provider"
                          value={provider}
                          disabled={active || runs.length > 0}
                          onChange={(e) => {
                            setProvider(e.target.value);
                            setModel(
                              config?.providers.find((p) => p.id === e.target.value)
                                ?.models[0]?.id || "",
                            );
                            setEffort("medium");
                          }}
                        >
                          {config?.providers.map((p) => (
                            <option key={p.id} value={p.id} disabled={!p.enabled}>
                              {p.label}
                              {!p.enabled ? " (unavailable)" : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  )}
                </div>
                {selectedTools.length > 0 && (
                  <div className="selected-tools" aria-label="Selected tools">
                    {selectedTools.map((tool) => (
                      <span className="selected-tool" key={tool.key}>
                        <Icon name={tool.icon} size={14} />
                        <span>{tool.label}</span>
                        <button type="button" aria-label={`Remove ${tool.label}`} title={`Remove ${tool.label}`} disabled={active || busy} onClick={tool.remove}>
                          <Icon name="close" size={13} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <input
                  ref={fileInput}
                  className="visually-hidden"
                  type="file"
                  multiple
                  disabled={!cid || busy || active}
                  onChange={(e) => {
                    void upload(e.target.files);
                    e.target.value = "";
                    setPlusOpen(false);
                  }}
                />
                <div className="composer-selection">
                  <select
                    aria-label="Model"
                    value={model}
                    disabled={active}
                    onChange={(e) => {
                      setModel(e.target.value);
                      setEffort("medium");
                    }}
                  >
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>{m.label}</option>
                    ))}
                  </select>
                  <select
                    aria-label="Reasoning effort"
                    value={effort}
                    disabled={active}
                    onChange={(e) => setEffort(e.target.value)}
                  >
                    {selectedModel?.efforts.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                </div>
                {activeRun ? (
                  <button
                    className="send stop-send"
                    type="button"
                    aria-label="Stop"
                    onClick={() => void stopRun()}
                  >
                    <span className="stop-square" />
                  </button>
                ) : (
                  <button
                    className="send"
                    type="submit"
                    aria-label="Send"
                    disabled={!canSend}
                  >
                    ↑
                  </button>
                )}
              </div>
            </div>
            <p className="composer-note">Responses may contain mistakes.</p>
          </form>
        )}
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
      </main>
      <aside className={`files-panel ${showFiles ? "is-open" : ""}`}>
        <div className="files-header">
          <h2>Files</h2>
          <button
            className="files-toggle"
            type="button"
            onClick={() => setShowFiles(false)}
          >
            Close
          </button>
          <button className="refresh-files" type="button" aria-label="Refresh files" title="Refresh files" disabled={!cid} onClick={() => setFileRevision((v) => v + 1)}>
            <Icon name="refresh" size={17} />
          </button>
        </div>
        <p className="workspace-path">
          {currentWorkspace?.path || "No workspace selected"}
        </p>
        <div className="folder-path">/workspace{folder && `/${folder}`}</div>
        {folder && (
          <button
            className="file-row"
            onClick={() => setFolder(folder.split("/").slice(0, -1).join("/"))}
          >
            ↰ Parent folder
          </button>
        )}
        <div className="file-list">
          {files.map((f) =>
            f.directory ? (
              <button
                key={f.path}
                className="file-row"
                onClick={() => setFolder(f.path)}
              >
                ▸ <span>{f.name}</span>
              </button>
            ) : (
              <a
                key={f.path}
                className="file-row"
                href={`/api/conversations/${cid}/download?path=${encodeURIComponent(f.path)}`}
                download
              >
                <span className="file-icon">▤</span>
                <span>{f.name}</span>
                <small>{Math.ceil(f.size / 1024)} KB</small>
              </a>
            ),
          )}
        </div>
        <p className="files-note">
          Created files appear here. Select a file to download it.
        </p>
      </aside>
    </div>
  );
}
