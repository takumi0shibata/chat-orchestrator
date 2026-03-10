from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"
COMMENTS_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"

NS = {"w": W_NS, "r": R_NS}
PARSE = etree.XMLParser(remove_blank_text=False)


def _qn(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


@dataclass(frozen=True)
class QuoteMatch:
    paragraph: etree._Element
    start: int
    end: int


@dataclass(frozen=True)
class AppliedComment:
    quote: str
    comment: str
    category: str
    priority: str


@dataclass(frozen=True)
class SkippedComment:
    quote: str
    reason: str


class DocxCommentGenerator:
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self._files: dict[str, bytes] = {}
        self._document_root: etree._Element | None = None
        self._comments_root: etree._Element | None = None
        self._rels_root: etree._Element | None = None
        self._content_types_root: etree._Element | None = None

    def load(self) -> None:
        with ZipFile(self.source_path) as archive:
            self._files = {name: archive.read(name) for name in archive.namelist()}

        self._document_root = etree.fromstring(self._files["word/document.xml"], parser=PARSE)
        comments_xml = self._files.get("word/comments.xml")
        if comments_xml:
            self._comments_root = etree.fromstring(comments_xml, parser=PARSE)
        else:
            self._comments_root = etree.Element(_qn(W_NS, "comments"), nsmap={"w": W_NS})

        rels_xml = self._files.get("word/_rels/document.xml.rels")
        if rels_xml:
            self._rels_root = etree.fromstring(rels_xml, parser=PARSE)
        else:
            self._rels_root = etree.Element(f"{{{REL_NS}}}Relationships", nsmap={None: REL_NS})

        self._content_types_root = etree.fromstring(self._files["[Content_Types].xml"], parser=PARSE)

    def review_text(self, *, max_chars: int | None = None) -> str:
        paragraphs = [text for text in (self._paragraph_text(p) for p in self._iter_paragraphs()) if text]
        text = "\n\n".join(paragraphs)
        if max_chars is not None:
            return text[:max_chars]
        return text

    def apply_comments(self, candidates: list[dict[str, str]]) -> tuple[list[AppliedComment], list[SkippedComment]]:
        applied: list[AppliedComment] = []
        skipped: list[SkippedComment] = []
        used_spans: set[tuple[int, int, int]] = set()

        for candidate in candidates:
            quote = (candidate.get("quote") or "").strip()
            comment = (candidate.get("comment") or "").strip()
            category = (candidate.get("category") or "general").strip() or "general"
            priority = (candidate.get("priority") or "medium").strip() or "medium"
            if not quote or not comment:
                skipped.append(SkippedComment(quote=quote or "[missing quote]", reason="Candidate is missing quote/comment"))
                continue

            match, reason = self.find_quote(quote)
            if not match:
                skipped.append(SkippedComment(quote=quote, reason=reason))
                continue

            span_key = (id(match.paragraph), match.start, match.end)
            if span_key in used_spans:
                skipped.append(SkippedComment(quote=quote, reason="Candidate overlaps an earlier applied comment"))
                continue

            self.attach_comment(match=match, comment_text=comment)
            used_spans.add(span_key)
            applied.append(AppliedComment(quote=quote, comment=comment, category=category, priority=priority))

        return applied, skipped

    def find_quote(self, quote: str) -> tuple[QuoteMatch | None, str]:
        matches: list[QuoteMatch] = []
        for paragraph in self._iter_paragraphs():
            text = self._paragraph_text(paragraph)
            if not text:
                continue
            occurrences = self._find_occurrences(text, quote)
            for start in occurrences:
                matches.append(QuoteMatch(paragraph=paragraph, start=start, end=start + len(quote)))
                if len(matches) > 1:
                    return None, "Quote matched multiple locations in the document"

        if not matches:
            return None, "Quote was not found in the document body"
        return matches[0], ""

    def attach_comment(self, *, match: QuoteMatch, comment_text: str) -> None:
        selected_runs = self._select_runs_for_match(match)
        if not selected_runs:
            raise ValueError("Unable to isolate quote into selectable runs")

        comment_id = self._next_comment_id()
        self._append_comment(comment_id=comment_id, comment_text=comment_text)
        self._ensure_comments_relationship()
        self._ensure_comments_content_type()

        paragraph = match.paragraph
        first_run = selected_runs[0]
        last_run = selected_runs[-1]

        paragraph.insert(paragraph.index(first_run), etree.Element(_qn(W_NS, "commentRangeStart"), {_qn(W_NS, "id"): str(comment_id)}))
        paragraph.insert(paragraph.index(last_run) + 1, etree.Element(_qn(W_NS, "commentRangeEnd"), {_qn(W_NS, "id"): str(comment_id)}))
        paragraph.insert(paragraph.index(last_run) + 2, self._comment_reference_run(comment_id))

    def save(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._files["word/document.xml"] = etree.tostring(
            self._document_root,
            encoding="utf-8",
            xml_declaration=True,
            standalone="yes",
        )
        self._files["word/comments.xml"] = etree.tostring(
            self._comments_root,
            encoding="utf-8",
            xml_declaration=True,
            standalone="yes",
        )
        self._files["word/_rels/document.xml.rels"] = etree.tostring(
            self._rels_root,
            encoding="utf-8",
            xml_declaration=True,
            standalone="yes",
        )
        self._files["[Content_Types].xml"] = etree.tostring(
            self._content_types_root,
            encoding="utf-8",
            xml_declaration=True,
            standalone="yes",
        )

        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for name, content in sorted(self._files.items()):
                archive.writestr(name, content)
        output_path.write_bytes(buffer.getvalue())

    def _iter_paragraphs(self) -> list[etree._Element]:
        return self._document_root.xpath(
            "/w:document/w:body//w:p[not(ancestor::w:txbxContent)]",
            namespaces=NS,
        )

    def _paragraph_runs(self, paragraph: etree._Element) -> list[etree._Element]:
        return paragraph.xpath("./w:r[w:t]", namespaces=NS)

    def _paragraph_text(self, paragraph: etree._Element) -> str:
        return "".join(self._run_text(run) for run in self._paragraph_runs(paragraph))

    def _run_text(self, run: etree._Element) -> str:
        return "".join(text for text in run.xpath("./w:t/text()", namespaces=NS))

    def _find_occurrences(self, text: str, quote: str) -> list[int]:
        positions: list[int] = []
        start = 0
        while True:
            idx = text.find(quote, start)
            if idx < 0:
                return positions
            positions.append(idx)
            start = idx + 1

    def _select_runs_for_match(self, match: QuoteMatch) -> list[etree._Element]:
        paragraph = match.paragraph
        runs = self._paragraph_runs(paragraph)
        offsets = self._run_offsets(runs)
        start_idx, start_offset = self._locate_run_offset(offsets, match.start)
        end_idx, end_offset = self._locate_run_offset(offsets, match.end - 1)
        end_offset += 1

        if start_idx == end_idx:
            run = runs[start_idx]
            text = self._run_text(run)
            split_runs = self._replace_run(run, [text[:start_offset], text[start_offset:end_offset], text[end_offset:]])
            return [split_runs[1 if start_offset > 0 else 0]]

        end_run = runs[end_idx]
        end_text = self._run_text(end_run)
        if end_offset < len(end_text):
            end_parts = self._replace_run(end_run, [end_text[:end_offset], end_text[end_offset:]])
            end_run = end_parts[0]

        start_run = runs[start_idx]
        start_text = self._run_text(start_run)
        if start_offset > 0:
            start_parts = self._replace_run(start_run, [start_text[:start_offset], start_text[start_offset:]])
            start_run = start_parts[1]

        updated_runs = self._paragraph_runs(paragraph)
        selected = False
        chosen: list[etree._Element] = []
        for run in updated_runs:
            if run is start_run:
                selected = True
            if selected:
                chosen.append(run)
            if run is end_run:
                break
        return chosen

    def _run_offsets(self, runs: list[etree._Element]) -> list[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        cursor = 0
        for run in runs:
            text = self._run_text(run)
            offsets.append((cursor, cursor + len(text)))
            cursor += len(text)
        return offsets

    def _locate_run_offset(self, offsets: list[tuple[int, int]], index: int) -> tuple[int, int]:
        for run_idx, (start, end) in enumerate(offsets):
            if start <= index < end:
                return run_idx, index - start
        raise ValueError("Quote offset fell outside paragraph text")

    def _replace_run(self, run: etree._Element, parts: list[str]) -> list[etree._Element]:
        parent = run.getparent()
        insert_at = parent.index(run)
        rpr = run.find("./w:rPr", namespaces=NS)
        new_runs: list[etree._Element] = []
        for part in parts:
            if not part:
                continue
            new_run = etree.Element(_qn(W_NS, "r"))
            if rpr is not None:
                new_run.append(deepcopy(rpr))
            text_element = etree.SubElement(new_run, _qn(W_NS, "t"))
            if part != part.strip() or "  " in part:
                text_element.set(_qn(XML_NS, "space"), "preserve")
            text_element.text = part
            parent.insert(insert_at, new_run)
            insert_at += 1
            new_runs.append(new_run)
        parent.remove(run)
        return new_runs

    def _next_comment_id(self) -> int:
        existing = [int(node.get(_qn(W_NS, "id"))) for node in self._comments_root.findall(f".//{_qn(W_NS, 'comment')}")]
        return (max(existing) + 1) if existing else 0

    def _append_comment(self, *, comment_id: int, comment_text: str) -> None:
        comment = etree.SubElement(
            self._comments_root,
            _qn(W_NS, "comment"),
            {
                _qn(W_NS, "id"): str(comment_id),
                _qn(W_NS, "author"): "Chat Orchestrator",
                _qn(W_NS, "initials"): "CO",
                _qn(W_NS, "date"): datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            },
        )
        paragraph = etree.SubElement(comment, _qn(W_NS, "p"))
        run = etree.SubElement(paragraph, _qn(W_NS, "r"))
        text = etree.SubElement(run, _qn(W_NS, "t"))
        if comment_text != comment_text.strip() or "  " in comment_text:
            text.set(_qn(XML_NS, "space"), "preserve")
        text.text = comment_text

    def _comment_reference_run(self, comment_id: int) -> etree._Element:
        run = etree.Element(_qn(W_NS, "r"))
        rpr = etree.SubElement(run, _qn(W_NS, "rPr"))
        style = etree.SubElement(rpr, _qn(W_NS, "rStyle"))
        style.set(_qn(W_NS, "val"), "CommentReference")
        reference = etree.SubElement(run, _qn(W_NS, "commentReference"))
        reference.set(_qn(W_NS, "id"), str(comment_id))
        return run

    def _ensure_comments_relationship(self) -> None:
        existing = self._rels_root.xpath(
            f"./rel:Relationship[@Type='{COMMENTS_REL_TYPE}']",
            namespaces={"rel": REL_NS},
        )
        if existing:
            return

        existing_ids = {
            rel.get("Id")
            for rel in self._rels_root.findall(f"{{{REL_NS}}}Relationship")
            if rel.get("Id")
        }
        next_id = 1
        while f"rId{next_id}" in existing_ids:
            next_id += 1
        etree.SubElement(
            self._rels_root,
            f"{{{REL_NS}}}Relationship",
            {
                "Id": f"rId{next_id}",
                "Type": COMMENTS_REL_TYPE,
                "Target": "comments.xml",
            },
        )

    def _ensure_comments_content_type(self) -> None:
        existing = self._content_types_root.xpath(
            "./ct:Override[@PartName='/word/comments.xml']",
            namespaces={"ct": CONTENT_TYPES_NS},
        )
        if existing:
            return
        etree.SubElement(
            self._content_types_root,
            f"{{{CONTENT_TYPES_NS}}}Override",
            {
                "PartName": "/word/comments.xml",
                "ContentType": COMMENTS_CONTENT_TYPE,
            },
        )
