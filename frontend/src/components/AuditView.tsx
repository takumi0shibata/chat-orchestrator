import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Check, CircleAlert, FileText, RefreshCw, ScrollText, ShieldCheck, TriangleAlert } from "lucide-react";
import { api } from "../api";
import { MarkdownContent } from "./MarkdownContent";
import "./AuditView.css";

export type FindingStatus = "open" | "decided" | "fixed" | "intended" | "dismissed";
export type EvidenceCheck =
  | "verified" | "moved" | "missing" | "note" | "file_missing" | "invalid_path" | "line_out_of_range"
  | "unreadable" | "too_large" | "not_checked" | "invalid_quote" | "unparsed";
export interface AuditEvidence {
  raw: string; path: string | null; start: number | null; end: number | null; quote: string | null; note: string;
  check: EvidenceCheck; found_line: number | null; context: { line: number; text: string }[];
}
export interface AuditFinding {
  id: string; title: string; line: number; status: FindingStatus; severity: "blocker" | "major" | "minor" | null;
  relation: string; verdict: string; verified: string; found: string; decision: string; resolved: string;
  options: string[]; evidence: AuditEvidence[];
}
export interface AuditReport { id: string; path: string; title: string; content: string; updated_at: string; unchecked: string[] }
export interface ProjectAudit {
  project_id: string; exists: boolean;
  charter: { path: string; content: string; updated_at: string } | null;
  findings_document: { path: string; updated_at: string } | null;
  findings: AuditFinding[]; reports: AuditReport[]; reports_truncated: boolean;
  warnings: string[]; errors: string[];
}

const tabs: [FindingStatus, string][] = [
  ["open", "Needs decision"], ["decided", "Decided"], ["fixed", "Resolved"], ["intended", "Intended"], ["dismissed", "Dismissed"],
];
const severityRank = (finding: AuditFinding) => finding.severity ? { blocker: 0, major: 1, minor: 2 }[finding.severity] : 3;
const checks: Record<EvidenceCheck, [tone: "ok" | "warn" | "bad", label: string]> = {
  verified: ["ok", "Quote found"],
  note: ["ok", "File exists (not a quote)"],
  moved: ["warn", "Quote found elsewhere"],
  too_large: ["warn", "File too large to check"],
  not_checked: ["warn", "Not checked"],
  unparsed: ["warn", "Unrecognized format"],
  missing: ["bad", "Quote not found"],
  file_missing: ["bad", "File not found"],
  invalid_path: ["bad", "Invalid path"],
  line_out_of_range: ["bad", "Line out of range"],
  unreadable: ["bad", "Unreadable file"],
  invalid_quote: ["bad", "Quote too long"],
};
const dateTime = (value: string) => new Date(value).toLocaleString("en-US", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
const label = (finding: AuditFinding) => `${finding.id} ("${finding.title}")`;

export const auditPrompts = {
  charter: "Create an audit charter for this project. First inspect the project and present a draft in chat. Do not save any files until I approve it.",
  audit: "Audit this project according to its charter. During the audit, do not modify files outside .chat-orchestrator/audit/.",
  recheck: "Recheck unresolved audit findings (open or decided), and update findings.md and the report. Do not make fixes.",
  option: (f: AuditFinding, option: string) => `Decision for ${label(f)}: proceed with "${option}". Update decision and status in findings.md. Do not make fixes yet.`,
  custom: (f: AuditFinding) => `Decision for ${label(f)}: `,
  intended: (f: AuditFinding) => `${label(f)} is intended behavior. Record this in findings.md and the charter's known exceptions and decisions section. Reason: `,
  dismissed: (f: AuditFinding) => `${label(f)} is a false positive. Record this in findings.md. Reason: `,
  fix: (f: AuditFinding) => `Fix ${label(f)} according to my decision, verify it again, and update findings.md.`,
};

function evidenceSummary(finding: AuditFinding) {
  const bad = finding.evidence.filter((e) => checks[e.check][0] === "bad").length;
  const warn = finding.evidence.filter((e) => checks[e.check][0] === "warn").length;
  if (bad) return <span className="audit-check is-bad"><CircleAlert size={13} />{bad} evidence not found</span>;
  if (warn) return <span className="audit-check is-warn"><TriangleAlert size={13} />Check evidence</span>;
  if (finding.evidence.length) return <span className="audit-check is-ok"><Check size={13} />Evidence found</span>;
  return <span className="audit-check is-warn"><TriangleAlert size={13} />No evidence</span>;
}

function Evidence({ item }: { item: AuditEvidence }) {
  const [tone, text] = checks[item.check];
  const cited = item.start ? `:${item.start}${item.end && item.end !== item.start ? `-${item.end}` : ""}` : "";
  const highlighted = item.found_line ?? null;
  return <li className="audit-evidence">
    <div className="audit-evidence-head">
      <code>{item.path ? `${item.path}${cited}` : item.raw}</code>
      <span className={`audit-check is-${tone}`}>{tone === "ok" ? <Check size={13} /> : tone === "warn" ? <TriangleAlert size={13} /> : <CircleAlert size={13} />}{text}{item.check === "moved" && item.found_line ? ` (line ${item.found_line})` : ""}</span>
    </div>
    {item.quote && <p className="audit-quote">“{item.quote}”</p>}
    {item.note && <p className="audit-note">{item.note}</p>}
    {item.context.length > 0 && <pre className="audit-context" aria-label={`Lines from ${item.path}`}>{item.context.map((line) =>
      <span key={line.line} className={line.line === highlighted ? "is-hit" : ""}><em>{line.line}</em>{line.text || " "}{"\n"}</span>)}</pre>}
  </li>;
}

function FindingDetail({ finding, onBack, onDraft }: { finding: AuditFinding; onBack: () => void; onDraft: (text: string) => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [finding.id]);
  const meta: [string, string][] = [
    ["Relation", finding.relation], ["Verdict", finding.verdict], ["How verified", finding.verified],
    ["Found in", finding.found], ["Decision", finding.decision], ["Resolved", finding.resolved],
  ];
  return <article className="audit-detail" aria-labelledby="audit-finding-title">
    <button className="audit-back" onClick={onBack}><ArrowLeft size={15} />Back to findings</button>
    <div className="audit-detail-title">
      <span className={`audit-severity is-${finding.severity || "unrated"}`}>{finding.severity || "unrated"}</span>
      <h2 id="audit-finding-title" ref={heading} tabIndex={-1}><span>{finding.id}</span>{finding.title}</h2>
    </div>
    <dl className="audit-meta">{meta.filter(([, value]) => value).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
    <section aria-label="Evidence">
      <h3>Evidence <small>quotes are checked against the files when this page loads</small></h3>
      {finding.evidence.length ? <ul className="audit-evidence-list">{finding.evidence.map((item, index) => <Evidence key={index} item={item} />)}</ul> : <p className="audit-subtle">No evidence recorded.</p>}
    </section>
    <section className="audit-actions" aria-label="Decide">
      <h3>Your decision <small>adds a draft to the chat; nothing changes until you send it</small></h3>
      {(finding.status === "open" || finding.status === "decided") && <div className="audit-options">
        {finding.options.map((option) => <button key={option} onClick={() => onDraft(auditPrompts.option(finding, option))}>{option}</button>)}
        <button onClick={() => onDraft(auditPrompts.custom(finding))}>Write my own decision</button>
        <button onClick={() => onDraft(auditPrompts.intended(finding))}>Intended…</button>
        <button onClick={() => onDraft(auditPrompts.dismissed(finding))}>False positive…</button>
      </div>}
      {finding.status === "decided" && <button className="audit-primary" onClick={() => onDraft(auditPrompts.fix(finding))}>Request fix</button>}
      {finding.status !== "open" && finding.status !== "decided" && <p className="audit-subtle">This finding is closed. Ask in chat to reopen it if the situation changed.</p>}
    </section>
  </article>;
}

export function AuditView({ project, draftTarget, onDraft, onOpenDraft }: {
  project: { id: string; label: string };
  draftTarget: string | null;
  onDraft: (text: string, fresh: boolean) => Promise<string>;
  onOpenDraft: () => void;
}) {
  const [audit, setAudit] = useState<ProjectAudit | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<FindingStatus>("open");
  const [selected, setSelected] = useState<string | null>(null);
  const [openDocument, setOpenDocument] = useState<string | null>(null);
  const [drafted, setDrafted] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true); setError("");
    api<ProjectAudit>(`/workspaces/${encodeURIComponent(project.id)}/audit`, { signal: abort.signal })
      .then((result) => { if (!abort.signal.aborted) setAudit(result); })
      .catch((e) => { if (!abort.signal.aborted) setError(String(e)); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [project.id, revision]);
  useEffect(() => { setSelected(null); setOpenDocument(null); setDrafted(""); setTab("open"); }, [project.id]);

  async function draft(text: string, fresh = false) {
    setError("");
    try {
      const title = await onDraft(text, fresh);
      if (!fresh) setDrafted(title);
    } catch (e) {
      setError(String(e));
    }
  }

  const findings = audit?.findings || [];
  const finding = findings.find((item) => `${item.id}:${item.line}` === selected);
  const latest = audit?.reports[0];
  const shown = findings.filter((item) => item.status === tab).sort((a, b) => severityRank(a) - severityRank(b) || a.line - b.line);
  const viewing = openDocument === "charter" ? audit?.charter : audit?.reports.find((report) => report.id === openDocument);

  return <div className="audit-page"><div className="audit-inner">
    <header className="audit-header">
      <div><span className="audit-kicker"><ShieldCheck size={13} />PROJECT AUDIT</span><h1>{project.label}</h1></div>
      <button className="audit-refresh" onClick={() => setRevision((value) => value + 1)} disabled={loading} aria-label="Reload audit records"><RefreshCw size={15} />{loading ? "Loading…" : "Reload"}</button>
    </header>
    {error && <p className="audit-error" role="alert">{error}</p>}
    {audit && [...audit.errors, ...audit.warnings].length > 0 && <ul className="audit-warnings" aria-label="Record problems">
      {[...audit.errors, ...audit.warnings].map((message) => <li key={message}>{message}</li>)}
    </ul>}
    {drafted && <div className="audit-drafted" role="status">
      <span>Added to the draft in “{drafted}”. Review it and send when ready.</span>
      <button onClick={onOpenDraft}>Open chat<ArrowUpRight size={14} /></button>
    </div>}
    {audit && !audit.charter && <section className="audit-empty">
      <h2>Start with a charter</h2>
      <p>The charter records what this project is for, which files are the source of truth, which relationships to check and what is out of scope. The assistant inventories the project and proposes a draft in chat; it saves nothing until you agree.</p>
      <button className="audit-primary" onClick={() => void draft(auditPrompts.charter, true)}>Create charter in a new chat<ArrowUpRight size={15} /></button>
    </section>}
    {audit?.charter && <>
      <section className="audit-summary" aria-label="Audit summary">
        <div className="audit-stats">
          <div><strong>{findings.filter((f) => f.status === "open").length}</strong><span>Needs decision</span></div>
          <div><strong>{findings.filter((f) => f.status === "decided").length}</strong><span>Decided, not fixed</span></div>
          <div><strong>{findings.filter((f) => f.status === "fixed").length}</strong><span>Resolved</span></div>
          <div><strong>{latest ? latest.id : "—"}</strong><span>Latest report</span></div>
        </div>
        <div className="audit-commands">
          <button className="audit-primary" onClick={() => void draft(auditPrompts.audit, true)}>Run audit</button>
          <button onClick={() => void draft(auditPrompts.recheck, true)} disabled={!findings.some((f) => f.status === "open" || f.status === "decided")}>Re-check open findings</button>
          <button onClick={() => setOpenDocument("charter")}><FileText size={14} />Charter</button>
        </div>
        {latest && <div className="audit-unchecked">
          <TriangleAlert size={15} />
          <div><strong>Not checked in {latest.id}</strong>
            {latest.unchecked.length ? <ul>{latest.unchecked.map((item) => <li key={item}>{item}</li>)}</ul> : <p>The report does not list unchecked areas. Treat anything outside its scope as unchecked.</p>}
          </div>
        </div>}
        <p className="audit-target">Decisions are drafted into {draftTarget ? `“${draftTarget}”` : "a new chat in this project"}. Run audit and Create charter always start a new chat.</p>
      </section>
      {finding ? <FindingDetail finding={finding} onBack={() => setSelected(null)} onDraft={(text) => void draft(text)} /> : <section className="audit-findings" aria-label="Findings">
        <div className="audit-tabs" role="tablist" aria-label="Finding status">
          {tabs.map(([value, name]) => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>{name}<span>{findings.filter((f) => f.status === value).length}</span></button>)}
        </div>
        {shown.length === 0 ? <p className="audit-subtle">{findings.length ? "No findings in this state." : audit.findings_document ? "No findings recorded yet." : "No findings yet. Run an audit to create findings.md."}</p>
          : <ul className="audit-list">{shown.map((item) => <li key={`${item.id}:${item.line}`}>
            <button onClick={() => setSelected(`${item.id}:${item.line}`)} aria-label={`Open ${item.id} ${item.title}`}>
              <span className={`audit-severity is-${item.severity || "unrated"}`}>{item.severity || "unrated"}</span>
              <span className="audit-list-main"><span className="audit-list-title"><em>{item.id}</em>{item.title}</span>
                <span className="audit-list-meta">{[item.relation, item.verdict].filter(Boolean).join(" · ")}</span></span>
              {evidenceSummary(item)}
            </button>
          </li>)}</ul>}
      </section>}
      <section className="audit-reports" aria-label="Audit reports">
        <h2><ScrollText size={16} />Reports</h2>
        {audit.reports.length === 0 ? <p className="audit-subtle">No reports yet.</p> : <ul>{audit.reports.map((report) => <li key={report.id}>
          <button onClick={() => setOpenDocument(report.id)}><time>{report.id}</time><span>{report.title}</span></button>
        </li>)}</ul>}
        {audit.reports_truncated && <p className="audit-subtle">Showing the latest 30 reports. Older reports remain in the folder.</p>}
      </section>
    </>}
    {viewing && <section className="audit-document" aria-label="Audit record">
      <div className="audit-document-head"><h2>{viewing.path}</h2><button onClick={() => setOpenDocument(null)}>Close</button></div>
      <MarkdownContent content={viewing.content} />
    </section>}
  </div></div>;
}
