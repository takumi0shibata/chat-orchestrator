import { FormEvent, useEffect, useRef, useState } from "react";
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
  preparing: "準備中",
  model_wait: "モデル応答待ち",
  command_running: "実行中",
  approval_wait: "承認待ち",
  completed: "完了",
  failed: "失敗",
  stopped: "停止",
};
const text = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value ?? "");

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
        <label className="check" key={item.id}>
          <input
            type="checkbox"
            checked={selected.includes(item.id)}
            onChange={(e) =>
              change(
                e.target.checked
                  ? [...selected, item.id]
                  : selected.filter((id) => id !== item.id),
              )
            }
          />
          {item.label}
        </label>
      ))}
    </fieldset>
  );
}

export function RunView({
  run,
  timeline,
  onStop,
  onApproval,
}: {
  run: Run;
  timeline: AgentEvent[];
  onStop: () => void;
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
        <p>{run.request.input || "添付ファイルを使用した作業"}</p>
        {run.request.attachment_ids.length > 0 && (
          <small>添付 {run.request.attachment_ids.length} 件</small>
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
          {!terminal(run.status) && (
            <button className="stop" onClick={onStop}>
              停止
            </button>
          )}
        </div>
        <div className="current-step" role="status">
          {lastStatus
            ? text(lastStatus.data.label)
            : "実行履歴を読み込んでいます"}
        </div>
        {answer && <MarkdownContent content={answer} />}
        {!terminal(run.status) &&
          approvals.map((e) => (
            <div className="approval" key={e.seq}>
              <strong>外部ツールの実行承認</strong>
              <p>
                {text(e.data.server_label)} / {text(e.data.name)}
              </p>
              <pre>{text(e.data.arguments)}</pre>
              <button
                disabled={pending !== null}
                onClick={() => void approve(text(e.data.id), true)}
              >
                許可
              </button>
              <button
                disabled={pending !== null}
                onClick={() => void approve(text(e.data.id), false)}
              >
                拒否
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
                    <span key={f.path}>{f.path} · 削除</span>
                  ) : (
                    <a
                      key={f.path}
                      href={`/api/conversations/${run.conversation_id}/download?path=${encodeURIComponent(f.path)}`}
                      download
                    >
                      ▤ {f.path} · {f.change === "created" ? "作成" : "更新"} ↓
                    </a>
                  ),
              )}
            </div>
          ))}
        <details className="activity">
          <summary>
            実行履歴{" "}
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
                            ? "中断"
                            : "実行中…"}
                      </small>
                    </div>
                  );
                }
                if (e.type === "command_done") return null;
                return (
                  <div className="activity-row" key={e.seq}>
                    <time>{new Date(e.created_at).toLocaleTimeString()}</time>
                    <span>
                      {text(
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
  const [loadedCid, setLoadedCid] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const current = conversations.find((c) => c.id === cid);
  const currentWorkspace = config?.workspaces.find(
    (w) => w.id === (current?.workspace_id || workspace),
  );
  const activeRun = runs.find((r) => !terminal(r.status));
  const active = Boolean(activeRun);
  const currentEvent = activeRun
    ? [...(timelines[activeRun.id] || [])]
        .reverse()
        .find((e) => ["status", "command"].includes(e.type))
    : undefined;
  const selectedProvider = config?.providers.find((p) => p.id === provider);
  const models = selectedProvider?.models || [];
  const selectedModel = models.find((m) => m.id === model);

  async function refreshConversations() {
    setConversations(await api<Conversation[]>("/conversations"));
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
            setTimelines((old) => ({
              ...old,
              [run.id]: [...(old[run.id] || []), event],
            }));
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
            "接続を復旧しています。実行はバックエンドで継続しています。",
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
  }, [cid, revision, config]);

  useEffect(() => {
    setFolder("");
    setAttachments([]);
    setDirect([]);
    setInput("");
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
          作業フォルダ
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
          ＋ 新しい作業
        </button>
        <div className="eyebrow section-label">履歴</div>
        <nav>
          {conversations.map((c) => (
            <div
              className={`conversation ${c.id === cid ? "selected" : ""}`}
              key={c.id}
            >
              <button disabled={busy} onClick={() => setCid(c.id)}>
                {c.title}
                <small>
                  {
                    config?.workspaces.find((w) => w.id === c.workspace_id)
                      ?.label
                  }
                </small>
              </button>
              <button
                className="delete"
                aria-label={`${c.title}を削除`}
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
          <span>Docker · ネットワーク無効 · CPU</span>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <span className="eyebrow">LOCAL WORKSPACE</span>
            <h1>{current?.title || "ファイルから、次の成果へ。"}</h1>
          </div>
          {currentWorkspace && (
            <div className="workspace-badge">
              <strong>{currentWorkspace.label}</strong>
              <span>元ファイルを直接編集</span>
            </div>
          )}
          <button
            className="files-toggle"
            type="button"
            aria-expanded={showFiles}
            onClick={() => setShowFiles((v) => !v)}
          >
            ファイル
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
              <h2>調べる。分析する。仕上げる。</h2>
              <p>
                作業フォルダを選んで、新しい作業を始めましょう。
                <br />
                必要なファイルを探索し、編集と検証まで進めます。
              </p>
              {!config?.workspaces.length && (
                <p className="setup-note">
                  runtime.example.toml を runtime.toml
                  にコピーし、作業フォルダの絶対パスを設定してください。
                </p>
              )}
              <div className="examples">
                <span>論文フォルダを調べて比較表を作成</span>
                <span>CSVを分析して日本語グラフを保存</span>
                <span>Word・Excelの内容を確認して修正</span>
              </div>
            </div>
          ) : (
            <div className="chat-column">
              {runs.length === 0 && (
                <div className="welcome compact">
                  <h2>何に取り組みますか？</h2>
                  <p>対象ファイルや完成形を自然言語で指示してください。</p>
                </div>
              )}
              {runs.map((run) => (
                <RunView
                  key={run.id}
                  run={run}
                  timeline={timelines[run.id] || []}
                  onStop={() => {
                    void api(`/runs/${run.id}/stop`, { method: "POST" }).catch(
                      (e) => setError(String(e)),
                    );
                  }}
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
            {activeRun && (
              <div className="active-banner" role="status">
                <span className="status command_running">
                  <i />
                  {statusLabels[activeRun.status]}
                </span>
                <span className="active-label">
                  {currentEvent
                    ? text(currentEvent.data.label || currentEvent.data.command)
                    : "準備しています"}
                </span>
                <button
                  type="button"
                  className="stop"
                  onClick={() => {
                    void api(`/runs/${activeRun.id}/stop`, {
                      method: "POST",
                    }).catch((e) => setError(String(e)));
                  }}
                >
                  停止
                </button>
              </div>
            )}
            {connection && (
              <p className="connection" role="status">
                {connection}
              </p>
            )}
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
                      モデルに直接添付
                    </label>
                  )}
                  <button
                    type="button"
                    aria-label={`${a.name}の添付を解除`}
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
              aria-label="指示"
              placeholder="このフォルダで、何を進めますか？"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy || active}
              rows={3}
            />
            <div className="composer-actions">
              <label className="attach-button">
                ＋ 添付
                <input
                  type="file"
                  multiple
                  disabled={!cid || busy || active}
                  onChange={(e) => {
                    void upload(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              <select
                aria-label="プロバイダ"
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
                    {!p.enabled ? "（未設定）" : ""}
                  </option>
                ))}
              </select>
              <select
                aria-label="モデル"
                value={model}
                disabled={active}
                onChange={(e) => {
                  setModel(e.target.value);
                  setEffort("medium");
                }}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              <button
                className="send"
                disabled={
                  !selectedProvider?.enabled ||
                  !selectedModel ||
                  !cid ||
                  loadedCid !== cid ||
                  busy ||
                  active ||
                  (!input.trim() && !attachments.length)
                }
              >
                実行 ↑
              </button>
            </div>
            <details className="settings">
              <summary>推論・Skills・外部ツール</summary>
              <div className="settings-grid">
                <label>
                  推論の深さ{" "}
                  <select
                    aria-label="推論の深さ"
                    value={effort}
                    disabled={active}
                    onChange={(e) => setEffort(e.target.value)}
                  >
                    {selectedModel?.efforts.map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={web}
                    disabled={active}
                    onChange={(e) => setWeb(e.target.checked)}
                  />
                  Web検索
                </label>
                <Choices
                  label="Skills"
                  items={config?.skills || []}
                  selected={skills}
                  change={setSkills}
                  disabled={active}
                />
                <Choices
                  label="モデル・データ"
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
              </div>
            </details>
            <p className="composer-note">
              指定フォルダに直接保存します。停止しても反映済みの変更は残ります。
            </p>
          </form>
        )}
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button aria-label="エラーを閉じる" onClick={() => setError("")}>
              ×
            </button>
          </div>
        )}
      </main>
      <aside className={`files-panel ${showFiles ? "is-open" : ""}`}>
        <div className="files-header">
          <h2>ファイル</h2>
          <button
            className="files-toggle"
            type="button"
            onClick={() => setShowFiles(false)}
          >
            閉じる
          </button>
          <button disabled={!cid} onClick={() => setFileRevision((v) => v + 1)}>
            更新
          </button>
        </div>
        <p className="workspace-path">
          {currentWorkspace?.path || "作業フォルダ未選択"}
        </p>
        <div className="folder-path">/workspace{folder && `/${folder}`}</div>
        {folder && (
          <button
            className="file-row"
            onClick={() => setFolder(folder.split("/").slice(0, -1).join("/"))}
          >
            ↰ 親フォルダへ
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
          生成した成果物もここに表示されます。ファイル名を押すとダウンロードできます。
        </p>
      </aside>
    </div>
  );
}
