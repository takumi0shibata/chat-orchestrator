"""Read-only, on-demand view of a project's audit records. No model calls.

Evidence quotes are checked mechanically against the cited files so that a
fabricated or stale citation is visible to the user without trusting the model.
"""

import os
import re
from pathlib import PurePosixPath

from app.attachments import open_regular
from app.guild import FOLDER, MAX_DIRECTORY_ENTRIES, WorkspaceUnavailable, directory, prose_lines, read_document

FINDINGS_LIMIT = 256 * 1024
MAX_FINDINGS = 500
MAX_EVIDENCE = 20
MAX_REPORTS = 30
MAX_EVIDENCE_FILES = 200
MAX_EVIDENCE_FILE_BYTES = 4 * 1024 * 1024
MAX_QUOTE = 200
CONTEXT_LINES = 2
MAX_CONTEXT_LINES = 12
MAX_CONTEXT_CHARS = 240
STATUSES = ("open", "decided", "fixed", "intended", "dismissed")
SEVERITIES = ("blocker", "major", "minor")
FINDING = re.compile(r"^##\s+(F-\d{3,})\s+(.+?)\s*#*\s*$")
FIELD = re.compile(r"^[-*+]\s+([A-Za-z_]+)\s*:\s*(.*)$")
NESTED = re.compile(r"^\s{2,}[-*+]\s+(.+)$")
LOCATION = re.compile(
    r"^(?:<(?P<bracketed>[^>]+)>|(?P<path>[^\s`<]+?))(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?(?=\s|$)"
)
UNCHECKED = {"確認しなかったこと", "確認できなかったこと", "未確認", "not checked", "unchecked"}


def plain(text):
    """Drop code and emphasis markers but keep identifiers such as label_smoothing."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"`|\*\*|(?<!\w)[*_]{1,2}(?=\S)|(?<=\S)[*_]{1,2}(?!\w)", "", text).strip()


def normalize(text):
    return " ".join(text.split())


def parse_evidence(text):
    match = LOCATION.match(text.strip())
    if not match:
        return {"raw": text.strip(), "path": None, "start": None, "end": None, "quote": None, "note": text.strip()}
    path = match["bracketed"] or match["path"]
    for prefix in ("/workspace/", "./"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    rest = text.strip()[match.end():]
    # "path — explanation" records an absence; its code spans are not quotes.
    quote = None if rest.lstrip().startswith(("—", "–")) else re.search(r"`([^`]+)`", rest)
    note = (rest[:quote.start()] + rest[quote.end():]) if quote else rest
    start = int(match["start"]) if match["start"] else None
    end = int(match["end"]) if match["end"] else start
    return {
        "raw": text.strip(), "path": path, "start": start, "end": max(end, start) if start else None,
        "quote": quote[1] if quote else None, "note": note.strip(" \t—–-:："),
    }


def parse_findings(content):
    findings, warnings, seen = [], [], set()
    current, in_evidence = None, False
    for number, line in prose_lines(content):
        heading = FINDING.match(line)
        if heading or re.match(r"^#{1,2}\s", line):
            current, in_evidence = None, False
        if heading:
            if heading[1] in seen:
                warnings.append(f"findings.md:{number}: Duplicate ID {heading[1]}.")
            seen.add(heading[1])
            current = {"id": heading[1], "title": plain(heading[2]), "line": number, "fields": {}, "evidence": []}
            findings.append(current)
            if len(findings) > MAX_FINDINGS:
                raise ValueError("findings.md: Up to 500 findings can be shown.")
            continue
        if current is None:
            continue
        field = FIELD.match(line)
        if field:
            key, value = field[1].lower(), field[2].strip()
            in_evidence = key == "evidence"
            if in_evidence:
                if value:
                    current["evidence"].append(value)
            else:
                current["fields"][key] = value
            continue
        nested = NESTED.match(line)
        if nested and in_evidence:
            current["evidence"].append(nested[1])
    result = []
    for item in findings:
        fields = item.pop("fields")
        status = fields.get("status", "").lower() or "open"
        if status not in STATUSES:
            warnings.append(f"findings.md:{item['line']}: {item['id']} has an unknown status \"{status}\"; shown as open.")
            status = "open"
        severity = fields.get("severity", "").lower() or None
        if severity and severity not in SEVERITIES:
            warnings.append(f"findings.md:{item['line']}: {item['id']} has an unknown severity \"{severity}\".")
            severity = None
        if len(item["evidence"]) > MAX_EVIDENCE:
            warnings.append(f"{item['id']}: Showing the first {MAX_EVIDENCE} evidence items.")
        result.append({
            **item, "status": status, "severity": severity,
            "relation": fields.get("relation", ""), "verdict": fields.get("verdict", ""),
            "verified": fields.get("verified", ""), "found": fields.get("found", ""),
            "decision": fields.get("decision", ""), "resolved": fields.get("resolved", ""),
            "options": [o.strip() for o in fields.get("options", "").split(" / ") if o.strip()],
            "evidence": [parse_evidence(text) for text in item["evidence"][:MAX_EVIDENCE]],
        })
    return result, warnings


class EvidenceFiles:
    """Caches each cited file once per request; never follows symbolic links."""

    def __init__(self, root):
        self.root, self.cache = root, {}

    def lines(self, path):
        if path in self.cache:
            return self.cache[path]
        if len(self.cache) >= MAX_EVIDENCE_FILES:
            return "not_checked"
        parts = PurePosixPath(path).parts
        if not parts or PurePosixPath(path).is_absolute() or ".." in parts or "\\" in path:
            result = "invalid_path"
        else:
            try:
                with open_regular(self.root, path) as stream:
                    raw = stream.read(MAX_EVIDENCE_FILE_BYTES + 1)
                result = "too_large" if len(raw) > MAX_EVIDENCE_FILE_BYTES else raw.decode("utf-8-sig").splitlines()
            except FileNotFoundError:
                result = "file_missing"
            except (OSError, ValueError):
                # Includes symbolic links, special files and non-UTF-8 content.
                result = "unreadable"
        self.cache[path] = result
        return result


def context(lines, start, end):
    first = max(1, start - CONTEXT_LINES)
    last = min(len(lines), end + CONTEXT_LINES, first + MAX_CONTEXT_LINES - 1)
    return [{"line": n, "text": lines[n - 1][:MAX_CONTEXT_CHARS]} for n in range(first, last + 1)]


def find_line(lines, quote, first=1, last=None):
    last = len(lines) if last is None else min(last, len(lines))
    return next((n for n in range(max(first, 1), last + 1) if quote in normalize(lines[n - 1])), None)


def check_evidence(files, evidence):
    if not evidence["path"]:
        return {**evidence, "check": "unparsed", "found_line": None, "context": []}
    lines = files.lines(evidence["path"])
    if isinstance(lines, str):
        return {**evidence, "check": lines, "found_line": None, "context": []}
    start, end, quote = evidence["start"], evidence["end"], evidence["quote"]
    if start and start > len(lines):
        return {**evidence, "check": "line_out_of_range", "found_line": None, "context": []}
    if not quote:
        return {**evidence, "check": "note", "found_line": None, "context": context(lines, start, end) if start else []}
    quote = normalize(quote)
    if not quote or len(quote) > MAX_QUOTE:
        return {**evidence, "check": "invalid_quote", "found_line": None, "context": []}
    near = find_line(lines, quote, start - CONTEXT_LINES, end + CONTEXT_LINES) if start else None
    found = near or find_line(lines, quote)
    check = "verified" if near or (found and not start) else "moved" if found else "missing"
    shown = (found, found) if found else (start, end) if start else None
    return {**evidence, "check": check, "found_line": found, "context": context(lines, *shown) if shown else []}


def report_entry(document):
    lines = list(prose_lines(document["content"]))
    title = next((plain(re.sub(r"^#+\s+", "", line)) for _, line in lines if line.strip()), document["path"])
    unchecked, section = [], None
    for _, line in lines:
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            section = plain(heading[1]).casefold()
            continue
        item = re.match(r"^\s*[-*+]\s+(.+)$", line)
        if section in UNCHECKED and item:
            unchecked.append(plain(item[1]))
    name = document["path"].split("/")[-1]
    return {
        "id": name.removesuffix(".md"), "path": document["path"], "title": title[:200],
        "content": document["content"], "updated_at": document["updated_at"], "unchecked": unchecked[:50],
    }


def read_reports(audit_fd, errors):
    try:
        reports_fd = os.open("reports", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=audit_fd)
    except FileNotFoundError:
        return [], False
    except OSError:
        errors.append("reports/: Unable to read the folder. Check permissions and symbolic links.")
        return [], False
    try:
        names = []
        with os.scandir(reports_fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > MAX_DIRECTORY_ENTRIES:
                    errors.append("reports/: More than 2,000 directory entries.")
                    return [], False
                if entry.name.endswith(".md"):
                    names.append(entry.name)
        reports = []
        for name in sorted(names, reverse=True)[:MAX_REPORTS]:
            try:
                document = read_document(reports_fd, name, f"reports/{name}")
            except ValueError as error:
                errors.append(str(error))
                continue
            except OSError:
                errors.append(f"reports/{name}: Unable to read the file. Check permissions and symbolic links.")
                continue
            if document is not None:
                reports.append(report_entry(document))
        return reports, len(names) > MAX_REPORTS
    finally:
        os.close(reports_fd)


def read_audit(workspace):
    result = {
        "project_id": workspace.id, "exists": False, "charter": None, "findings_document": None,
        "findings": [], "reports": [], "reports_truncated": False, "warnings": [], "errors": [],
    }
    try:
        with directory(workspace.path) as root:
            try:
                guild_fd = os.open(FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            except FileNotFoundError:
                return result
            try:
                audit_fd = os.open("audit", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=guild_fd)
            except FileNotFoundError:
                return result
            finally:
                os.close(guild_fd)
            try:
                result["exists"] = True
                documents = {}
                for name, limit in (("charter.md", 64 * 1024), ("findings.md", FINDINGS_LIMIT)):
                    try:
                        documents[name] = read_document(audit_fd, name, name, limit)
                    except ValueError as error:
                        result["errors"].append(str(error))
                    except OSError:
                        result["errors"].append(f"{name}: Unable to read the file. Check permissions and symbolic links.")
                result["reports"], result["reports_truncated"] = read_reports(audit_fd, result["errors"])
            finally:
                os.close(audit_fd)
    except (WorkspaceUnavailable, OSError):
        raise ValueError("Unable to read audit records. Check the folder location, permissions, and symbolic links.") from None
    result["charter"] = documents.get("charter.md")
    findings = documents.get("findings.md")
    if findings is not None:
        result["findings_document"] = {"path": findings["path"], "updated_at": findings["updated_at"]}
        try:
            parsed, result["warnings"] = parse_findings(findings["content"])
        except ValueError as error:
            result["errors"].append(str(error))
            parsed = []
        files = EvidenceFiles(workspace.path)
        result["findings"] = [
            {**item, "evidence": [check_evidence(files, evidence) for evidence in item["evidence"]]}
            for item in parsed
        ]
    return result
