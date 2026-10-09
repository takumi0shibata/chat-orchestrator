import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, BookOpen, Check, ChevronRight, Compass, Flag, RefreshCw, ScrollText, Search, Shield, Swords } from "lucide-react";
import { api } from "../api";
import { GuildScene } from "./GuildScene";
import "./GuildBoard.css";

type Status = "todo" | "in_progress" | "review" | "waiting" | "paused" | "done" | "unknown";
export interface GuildTask {
  id: string; title: string; status: Exclude<Status, "unknown">;
  due: string | null; line: number; source: string;
}
export interface GuildProject {
  id: string; label: string; summary: string; next_action: string; status: Status;
  tasks: GuildTask[];
  documents: { path: string; content: string; updated_at: string }[];
  activity: { source: string; title: string; summary: string; date: string }[];
  updated_at: string | null; synced_at: string | null; fingerprint: string;
  warnings: string[]; error: string | null;
}
export interface GuildSnapshot { synced_at: string | null; projects: GuildProject[] }
const labels: Record<Status, string> = {
  todo: "Not started", in_progress: "In progress", review: "Needs review", waiting: "Waiting", paused: "Paused", done: "Completed", unknown: "No quests",
};
const filters = [
  ["all", "All"], ["review", "Needs review"], ["in_progress", "In progress"], ["waiting", "On hold"], ["done", "Completed"],
] as const;
type Filter = typeof filters[number][0];
const dateTime = (value: string | null) => value
  ? new Date(value).toLocaleString("en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
  : "—";

function Badge({ status }: { status: Status }) {
  return <span className={`guild-badge guild-status-${status}`}><span aria-hidden="true" />{labels[status]}</span>;
}

function Crest({ name, large = false }: { name: string; large?: boolean }) {
  const number = Array.from(name).reduce((sum, char) => sum + char.codePointAt(0)!, 0) % 4;
  const Icon = [Compass, Swords, Flag, Shield][number];
  return <span className={`guild-crest guild-crest-${number}${large ? " is-large" : ""}`} aria-hidden="true"><Icon size={large ? 34 : 23} strokeWidth={1.5} /></span>;
}

function ProjectDetails({ project, onBack, onOpenChat, opening }: {
  project: GuildProject; onBack: () => void; onOpenChat: () => void; opening: boolean;
}) {
  const [showDone, setShowDone] = useState(false);
  const [limit, setLimit] = useState(30);
  const [source, setSource] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const sourceHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => { if (source) sourceHeading.current?.focus(); }, [source]);
  const tasks = project.tasks.filter((task) => showDone || task.status !== "done");
  const document = project.documents.find((item) => item.path === source);
  const done = project.tasks.filter((task) => task.status === "done").length;
  return <div className="guild-detail">
    <button className="guild-back" onClick={onBack}><ArrowLeft size={16} />Back to the board</button>
    <div className="guild-detail-title"><Crest name={project.id} large /><div><span className="guild-kicker">QUEST JOURNAL</span><h2 ref={heading} tabIndex={-1}>{project.label}</h2></div><Badge status={project.status} /></div>
    {project.error && <p className="guild-error" role="alert">{project.error} {project.synced_at ? `Showing the last successful sync (${dateTime(project.synced_at)}).` : "No records have been imported yet."}</p>}
    <div className="guild-detail-overview">
      <div><span className="guild-kicker">Current chapter</span><p>{project.summary || "No summary recorded yet."}</p></div>
      <div className="guild-next"><Flag size={17} /><div><span className="guild-kicker">Next step</span><p>{project.next_action || "No next step recorded yet."}</p></div></div>
    </div>
    <div className="guild-detail-actions">
      <button className="guild-chat-button" onClick={onOpenChat} disabled={opening}>Open project chat<ArrowUpRight size={16} /></button>
      {project.documents.some((doc) => doc.path === "overview.md") && <button className="guild-text-button" onClick={() => setSource("overview.md")}>Read overview source</button>}
      <small>Updated {dateTime(project.updated_at)} · Synced {dateTime(project.synced_at)}</small>
    </div>
    {project.warnings.length > 0 && <ul className="guild-warnings">{project.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
    <section className="guild-quest-list" aria-labelledby="guild-quests-heading">
      <div className="guild-section-heading"><h3 id="guild-quests-heading"><ScrollText size={18} />Quest log <small>{project.tasks.length - done} open</small></h3><label><input type="checkbox" checked={showDone} onChange={(event) => { setShowDone(event.target.checked); setLimit(30); }} />Show completed ({done})</label></div>
      {tasks.length === 0 ? <p className="guild-subtle">{done ? "All recorded quests are complete." : "No quests recorded yet."}</p> : <ul className="guild-tasks">{tasks.slice(0, limit).map((task) => <li key={task.id} className={task.status === "done" ? "is-done" : ""}>
        <span className="guild-task-mark" aria-hidden="true">{task.status === "done" ? <Check size={15} /> : <span />}</span>
        <div><p>{task.title}</p><button className="guild-source-link" onClick={() => setSource(task.source)}>{task.source}:{task.line}</button>{task.due && <span className="guild-due">Due {task.due}</span>}</div><Badge status={task.status} />
      </li>)}</ul>}
      {tasks.length > limit && <button className="guild-more" onClick={() => setLimit((value) => value + 30)}>Show 30 more</button>}
    </section>
    <section className="guild-project-log" aria-label="Project journal"><h3><BookOpen size={18} />Adventure journal</h3>
      {project.activity.length === 0 ? <p className="guild-subtle">No journal entries yet.</p> : project.activity.map((entry) => <button className="guild-log-link" key={entry.source} onClick={() => setSource(entry.source)}><time>{entry.date}</time><span>{entry.title}</span><ChevronRight size={15} /></button>)}
    </section>
    {document && <section className="guild-source" aria-label="Source record"><div className="guild-section-heading"><h3 ref={sourceHeading} tabIndex={-1}>{document.path}</h3><button className="guild-text-button" onClick={() => setSource(null)}>Close</button></div><pre>{document.content}</pre></section>}
  </div>;
}

export function GuildBoard({ onOpenProject }: { onOpenProject: (id: string) => Promise<void> | void }) {
  const [snapshot, setSnapshot] = useState<GuildSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [changed, setChanged] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [logLimit, setLogLimit] = useState(8);
  const [opening, setOpening] = useState(false);
  const syncLock = useRef(false);
  const boardTitle = useRef<HTMLHeadingElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    const abort = new AbortController();
    api<GuildSnapshot>("/guild", { signal: abort.signal })
      .then((result) => { if (!abort.signal.aborted) setSnapshot(result); })
      .catch((e) => { if (!abort.signal.aborted) setError(String(e)); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, []);
  useEffect(() => {
    if (!selected && restoreFocus.current) { boardTitle.current?.focus(); restoreFocus.current = false; }
  }, [selected]);

  async function sync() {
    if (syncLock.current) return;
    syncLock.current = true;
    setSyncing(true); setError(""); setMessage(""); setChanged([]);
    try {
      const result = await api<GuildSnapshot>("/guild/sync", { method: "POST" });
      const changedIds = result.projects.filter((project) => !project.error && project.fingerprint !== snapshot?.projects.find((old) => old.id === project.id)?.fingerprint).map((project) => project.id);
      setSnapshot(result); setChanged(changedIds);
      if (selected && !result.projects.some((project) => project.id === selected)) { restoreFocus.current = true; setSelected(null); }
      const failures = result.projects.filter((project) => project.error).length;
      setMessage(`${result.projects.length} projects checked · ${changedIds.length} updated${failures ? ` · ${failures} failed` : ""}`);
    } catch (e) { setError(String(e)); }
    finally { syncLock.current = false; setSyncing(false); }
  }

  async function openChat(id: string) {
    setOpening(true);
    try { await onOpenProject(id); }
    catch (e) { setError(String(e)); }
    finally { setOpening(false); }
  }

  const projects = snapshot?.projects ?? [];
  const tasks = projects.flatMap((project) => project.tasks.map((task) => ({ ...task, project })));
  const reviews = tasks.filter((task) => task.status === "review");
  const progress = tasks.filter((task) => task.status === "in_progress").length;
  const pending = tasks.filter((task) => task.status === "waiting" || task.status === "paused").length;
  const visible = projects.filter((project) => {
    const matchesState = filter === "all" || (filter === "done" ? project.status === "done" : project.tasks.some((task) => task.status === filter || (filter === "waiting" && task.status === "paused")));
    const needle = query.trim().toLocaleLowerCase();
    return matchesState && (!needle || [project.label, project.summary, project.next_action, ...project.tasks.map((task) => task.title)].some((value) => value.toLocaleLowerCase().includes(needle)));
  });
  const activity = projects.flatMap((project) => project.activity.map((entry) => ({ ...entry, project }))).sort((a, b) => b.date.localeCompare(a.date) || a.project.label.localeCompare(b.project.label));
  const project = projects.find((item) => item.id === selected);

  return <section className="guild-page" aria-label="Guild Board">
    <div className="guild-inner">
      <header className="guild-header"><div className="guild-wordmark"><Shield size={16} /><span>WORKSPACE</span><span className="guild-header-divider" />PROJECT OVERVIEW</div></header>
      <div className="guild-hero">
        <div className="guild-hero-copy"><h1 ref={boardTitle} tabIndex={-1}>Guild Board<span aria-hidden="true">✦</span></h1><p>Your projects at a glance.<br />Catch up on progress and find your next step.</p></div>
        <GuildScene />
      </div>
      <div className="guild-toolbar"><span><ScrollText size={16} />Your project records, posted at the guild.</span><div className="guild-sync"><small>{snapshot?.synced_at ? `Last sync ${dateTime(snapshot.synced_at)}` : "Not synced yet"}</small><button onClick={() => void sync()} disabled={loading || syncing} aria-busy={syncing}><RefreshCw size={16} />{syncing ? "Syncing…" : "Sync"}</button></div></div>
      <div className="guild-feedback" aria-live="polite">{loading ? "Loading the board…" : message}</div>
      {error && <p className="guild-error" role="alert">{error} · Select Sync to try again.</p>}
      {project ? <ProjectDetails key={project.id} project={project} onBack={() => { restoreFocus.current = true; setSelected(null); }} onOpenChat={() => void openChat(project.id)} opening={opening} /> : <>
        <div className="guild-stats" aria-label="Guild overview">
          <div><Compass size={20} /><strong>{projects.length}</strong><span>Projects</span></div>
          <button onClick={() => setFilter("review")} aria-pressed={filter === "review"}><Flag size={20} /><strong>{reviews.length}</strong><span>Needs review</span></button>
          <button onClick={() => setFilter("in_progress")} aria-pressed={filter === "in_progress"}><Swords size={20} /><strong>{progress}</strong><span>In progress</span></button>
          <button onClick={() => setFilter("waiting")} aria-pressed={filter === "waiting"}><BookOpen size={20} /><strong>{pending}</strong><span>On hold</span></button>
        </div>
        {!loading && projects.length === 0 ? <div className="guild-empty"><Crest name="guild" large /><span className="guild-kicker">THE ADVENTURE STARTS HERE</span><h2>Your first quest awaits</h2><p>Add <code>.chat-orchestrator/</code> to a registered project,<br />then Sync to bring its records to the board.</p><div className="guild-empty-files"><span><ScrollText size={16} />overview.md<small>Summary & next step</small></span><span><Flag size={16} />tasks.md<small>Quests & tasks</small></span><span><BookOpen size={16} />activity/*.md<small>Activity & decisions</small></span></div></div> : <div className="guild-layout">
          <div className="guild-board">
            <div className="guild-section-heading"><h2><ScrollText size={18} />Quest board <small>{visible.length} PROJECTS</small></h2><label className="guild-search"><Search size={15} /><input type="search" aria-label="Search projects and tasks" placeholder="Search projects or tasks" value={query} onChange={(event) => setQuery(event.target.value)} /></label></div>
            <div className="guild-filters" aria-label="Filter quests">{filters.map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div>
            <div className="guild-cards">{visible.map((item) => {
              const done = item.tasks.filter((task) => task.status === "done").length;
              return <button key={item.id} className={`guild-card${changed.includes(item.id) ? " is-updated" : ""}`} onClick={() => setSelected(item.id)} aria-label={`Open quest log for ${item.label}`}>
                <div className="guild-card-top"><Crest name={item.id} /><Badge status={item.status} /></div>
                <h3>{item.label}</h3><p className="guild-card-summary">{item.summary || "No summary recorded yet."}</p>
                <div className="guild-card-next"><span>Next step</span><p>{item.next_action || "Open the quest log to see your records"}</p></div>
                {item.error ? <div className="guild-card-warning">Sync failed · {item.synced_at ? "showing saved records" : "check your records"}</div> : item.warnings.length > 0 && <div className="guild-card-warning">{item.warnings.length} record notices</div>}
                <div className="guild-card-footer"><span><ScrollText size={13} />Open {item.tasks.length - done}</span><span><Check size={13} />Completed {done}</span><ChevronRight size={16} /></div>
                <div className="guild-card-date">Updated {dateTime(item.updated_at)}{changed.includes(item.id) && <span>Updated</span>}</div>
              </button>;
            })}</div>
            {!loading && visible.length === 0 && <p className="guild-no-match">No quests match your search.</p>}
          </div>
          <aside className="guild-reception" aria-label="Guild reception"><span className="guild-kicker">GUILD RECEPTION</span><h2><Shield size={17} strokeWidth={1.5} />Needs your review</h2><p className="guild-reception-intro">Decisions that help your projects move forward.</p>
            {reviews.length ? <ul>{reviews.slice(0, 5).map((task) => <li key={`${task.project.id}-${task.id}`}><button onClick={() => setSelected(task.project.id)}><span>{task.project.label}{task.project.error ? " · Saved record" : ""}</span><strong>{task.title}</strong>{task.due && <small>Due {task.due}</small>}<ArrowUpRight size={15} /></button></li>)}</ul> : <div className="guild-reception-clear"><Check size={24} /><p>Nothing waiting for review</p><small>Based on the last imported records.</small></div>}
            {reviews.length > 5 && <button className="guild-text-button" onClick={() => setFilter("review")}>View projects needing review →</button>}
            <div className="guild-reception-foot"><Shield size={16} /><span>New records? Send a courier with Sync.</span></div>
          </aside>
          <section className="guild-journal" aria-label="Recent adventure journal"><div className="guild-section-heading"><h2><BookOpen size={18} />Adventure journal</h2><span className="guild-kicker">RECENT CHAPTERS</span></div>
            {activity.length === 0 ? <p className="guild-subtle">Your progress and decisions will fill these pages.</p> : <ol>{activity.slice(0, logLimit).map((entry) => <li key={`${entry.project.id}-${entry.source}`}><time>{entry.date.slice(5).replace("-", "/")}<small>{entry.date.slice(0, 4)}</small></time><button onClick={() => setSelected(entry.project.id)}><span>{entry.project.label}{entry.project.error ? " · Saved record" : ""}</span><h3>{entry.title}</h3><p>{entry.summary}</p></button><ChevronRight size={15} /></li>)}</ol>}
            {activity.length > logLimit && <button className="guild-more" onClick={() => setLogLimit((value) => value + 8)}>Read more entries</button>}
          </section>
        </div>}
      </>}
      <footer className="guild-footer"><span>✦ Every small step is part of the story.</span><span>Manual sync · Showing saved records</span></footer>
    </div>
  </section>;
}
