import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AuditView, auditPrompts, type AuditFinding, type ProjectAudit } from "./AuditView";

const finding: AuditFinding = {
  id: "F-001", title: "README の make train が存在しない", line: 3, status: "open", severity: "major",
  relation: "README ↔ 実態", verdict: "矛盾", verified: "executed `make -n train`", found: "2026-10-14-01",
  decision: "", resolved: "", options: ["READMEを直す", "Makefileに追加する"],
  evidence: [
    { raw: "README.md:2 `make train`", path: "README.md", start: 2, end: 2, quote: "make train", note: "", check: "verified", found_line: 2,
      context: [{ line: 1, text: "# Demo" }, { line: 2, text: "Run make train" }] },
    { raw: "paper.tex:9 `81.2`", path: "paper.tex", start: 9, end: 9, quote: "81.2", note: "", check: "missing", found_line: null, context: [] },
  ],
};
const audit: ProjectAudit = {
  project_id: "w", exists: true,
  charter: { path: "charter.md", content: "# Audit Charter\n<script>alert(1)</script>", updated_at: "2026-10-14T00:00:00Z" },
  findings_document: { path: "findings.md", updated_at: "2026-10-14T00:00:00Z" },
  findings: [
    finding,
    { ...finding, id: "F-002", title: "Blocker", line: 20, severity: "blocker", evidence: [] },
    { ...finding, id: "F-003", title: "Decided one", line: 30, status: "decided", decision: "READMEを直す" },
    { ...finding, id: "F-004", title: "Done", line: 40, status: "fixed" },
  ],
  reports: [{ id: "2026-10-14-01", path: "reports/2026-10-14-01.md", title: "監査", content: "# 監査\n本文", updated_at: "2026-10-14T00:00:00Z", unchecked: ["paper/（対象外）"] }],
  reports_truncated: false, warnings: ["findings.md:9: F-002 has an unknown severity \"urgent\"."], errors: [],
};
const response = (body: unknown) => new Response(JSON.stringify(body));
afterEach(() => vi.restoreAllMocks());

function renderView(onDraft = vi.fn(async () => "Audit chat"), onOpenDraft = vi.fn()) {
  const view = render(<AuditView project={{ id: "w", label: "Research" }} draftTarget="Audit chat" onDraft={onDraft} onOpenDraft={onOpenDraft} />);
  return { ...view, onDraft, onOpenDraft };
}

it("asks for a charter first and starts it in a new chat", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ ...audit, exists: false, charter: null, findings_document: null, findings: [], reports: [], warnings: [] }));
  const { onDraft } = renderView();
  fireEvent.click(await screen.findByRole("button", { name: /Create charter/ }));
  expect(fetch.mock.calls[0][0]).toBe("/api/workspaces/w/audit");
  await waitFor(() => expect(onDraft).toHaveBeenCalledWith(auditPrompts.charter, true));
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
});

it("lists findings by status with blockers first and shows unchecked areas and warnings", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response(audit));
  renderView();
  const list = await screen.findByRole("region", { name: "Findings" });
  const titles = within(list).getAllByRole("button", { name: /^Open F-/ }).map((button) => button.getAttribute("aria-label"));
  expect(titles).toEqual(["Open F-002 Blocker", "Open F-001 README の make train が存在しない"]);
  expect(within(list).getByText("1 evidence not found")).toBeInTheDocument();
  expect(within(list).getByText("No evidence")).toBeInTheDocument();
  expect(screen.getByText("paper/（対象外）")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Record problems" })).toHaveTextContent("unknown severity");
  fireEvent.click(screen.getByRole("tab", { name: /Decided/ }));
  expect(screen.getByRole("button", { name: "Open F-003 Decided one" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: /Resolved/ }));
  expect(screen.getByRole("button", { name: "Open F-004 Done" })).toBeInTheDocument();
});

it("shows checked evidence and only drafts decisions without leaving the page", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response(audit));
  const { onDraft, onOpenDraft } = renderView();
  fireEvent.click(await screen.findByRole("button", { name: "Open F-001 README の make train が存在しない" }));
  expect(screen.getByRole("heading", { name: /F-001/ })).toHaveFocus();
  const evidence = screen.getByRole("region", { name: "Evidence" });
  expect(within(evidence).getByText("Quote found")).toBeInTheDocument();
  expect(within(evidence).getByText("Quote not found")).toBeInTheDocument();
  expect(within(evidence).getByLabelText("Lines from README.md")).toHaveTextContent("Run make train");
  expect(screen.queryByRole("button", { name: "Request fix" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "READMEを直す" }));
  await waitFor(() => expect(onDraft).toHaveBeenCalledWith(auditPrompts.option(finding, "READMEを直す"), false));
  expect(await screen.findByRole("status")).toHaveTextContent("Added to the draft in “Audit chat”");
  fireEvent.click(screen.getByRole("button", { name: /Open chat/ }));
  expect(onOpenDraft).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "False positive…" }));
  await waitFor(() => expect(onDraft).toHaveBeenLastCalledWith(auditPrompts.dismissed(finding), false));
  fireEvent.click(screen.getByRole("button", { name: "Back to findings" }));
  fireEvent.click(screen.getByRole("tab", { name: /Decided/ }));
  fireEvent.click(screen.getByRole("button", { name: "Open F-003 Decided one" }));
  fireEvent.click(screen.getByRole("button", { name: "Request fix" }));
  await waitFor(() => expect(onDraft).toHaveBeenLastCalledWith(auditPrompts.fix(audit.findings[2]), false));
});

it("renders records as text, reloads on request and reports draft failures", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(response(audit));
  const onDraft = vi.fn(async () => { throw new Error("offline"); });
  const { container } = renderView(onDraft);
  fireEvent.click(await screen.findByRole("button", { name: "Charter" }));
  expect(screen.getByRole("region", { name: "Audit record" })).toHaveTextContent("Audit Charter");
  expect(container.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /2026-10-14-01/ }));
  expect(screen.getByRole("region", { name: "Audit record" })).toHaveTextContent("本文");
  fireEvent.click(screen.getByRole("button", { name: "Reload audit records" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  fireEvent.click(await screen.findByRole("button", { name: "Run audit" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("offline");
});
