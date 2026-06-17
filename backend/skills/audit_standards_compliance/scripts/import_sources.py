from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = SKILL_DIR / "docs"
CATALOG_PATH = DOCS_DIR / "source_catalog.json"
MANIFEST_PATH = DOCS_DIR / "manifest.json"


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    sources = catalog.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("source_catalog.json: sources must be a list")

    manifest_documents: list[dict[str, Any]] = []
    errors: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        try:
            manifest_documents.append(import_source(source))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source.get('document_id', '(unknown)')}: {exc}")

    manifest = {
        "version": 2,
        "generated_at": date.today().isoformat(),
        "notes": (
            "Generated from docs/source_catalog.json. User confirmed licensing/permission "
            "for local use of registered standards. IFRS Navigator pages are metadata unless "
            "licensed full text files are separately imported."
        ),
        "documents": manifest_documents,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Imported {len(manifest_documents)} sources into {DOCS_DIR / 'sources'}")
    return 0


def import_source(source: dict[str, Any]) -> dict[str, Any]:
    url = str(source["source_url"])
    target_path = DOCS_DIR / str(source["target_path"])
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if url.lower().endswith(".pdf"):
        pdf_bytes = download(url)
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "source.pdf"
            text_path = Path(tmp_dir) / "source.txt"
            pdf_path.write_bytes(pdf_bytes)
            run_pdftotext(pdf_path=pdf_path, text_path=text_path)
            body = normalize_pdf_text(text_path.read_text(encoding="utf-8", errors="replace"))
        target_path.write_text(build_markdown(source=source, body=body, pdf_sha256=pdf_sha256), encoding="utf-8")
        content_sha256 = hashlib.sha256(target_path.read_bytes()).hexdigest()
    else:
        body = focus_text(
            html_to_text(download(url).decode("utf-8", errors="replace")),
            title=str(source.get("title") or ""),
        )
        target_path.write_text(build_markdown(source=source, body=body, pdf_sha256=""), encoding="utf-8")
        content_sha256 = hashlib.sha256(target_path.read_bytes()).hexdigest()

    return {
        "document_id": source["document_id"],
        "title": source["title"],
        "issuer": source["issuer"],
        "jurisdiction": source["jurisdiction"],
        "standard_family": source["standard_family"],
        "effective_date": source["effective_date"],
        "version": source["version"],
        "source_url": source["source_url"],
        "file_path": source["target_path"],
        "is_authoritative": bool(source.get("is_authoritative", True)),
        "license_note": source.get("license_note", ""),
        "content_sha256": content_sha256,
    }


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "chat-orchestrator-audit-skill/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def run_pdftotext(*, pdf_path: Path, text_path: Path) -> None:
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext is required to import PDF standards")
    subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), str(text_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def normalize_pdf_text(text: str) -> str:
    lines: list[str] = []
    previous_blank = False
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue
        previous_blank = False
        lines.append(line)
    return "\n".join(lines).strip()


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>", "\n", html)
    html = re.sub(r"(?is)<style.*?</style>", "\n", html)
    html = re.sub(r"(?i)</(h[1-6]|p|div|li|tr|section|article)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return normalize_pdf_text(text)


def focus_text(text: str, *, title: str) -> str:
    candidates = [title]
    if " - " in title:
        candidates.append(title.split(" - ", 1)[0])
    focused = text
    lower_text = text.lower()
    for candidate in candidates:
        index = lower_text.find(candidate.lower())
        if index >= 0:
            focused = text[index:]
            break
    about_marker = "About Standard News"
    about_index = focused.find(about_marker)
    if about_index > 0:
        title_index = -1
        for candidate in candidates:
            title_index = max(title_index, focused.rfind(candidate, 0, about_index))
        focused = focused[title_index if title_index >= 0 else about_index:]
    home_index = focused.find("\n                 Home")
    if home_index > 0:
        focused = focused[home_index:]
    for marker in ["Your privacy", "Cookie preferences", "Share this page"]:
        marker_index = focused.find(marker)
        if marker_index > 0:
            focused = focused[:marker_index]
            break
    return normalize_pdf_text(focused)


def build_markdown(*, source: dict[str, Any], body: str, pdf_sha256: str) -> str:
    metadata_lines = [
        "---",
        f"document_id: {source['document_id']}",
        f"title: {json.dumps(source['title'], ensure_ascii=False)}",
        f"issuer: {json.dumps(source['issuer'], ensure_ascii=False)}",
        f"jurisdiction: {source['jurisdiction']}",
        f"standard_family: {source['standard_family']}",
        f"effective_date: {source['effective_date']}",
        f"version: {source['version']}",
        f"source_url: {source['source_url']}",
        f"is_authoritative: {str(bool(source.get('is_authoritative', True))).lower()}",
        f"license_note: {json.dumps(source.get('license_note', ''), ensure_ascii=False)}",
    ]
    if pdf_sha256:
        metadata_lines.append(f"source_pdf_sha256: {pdf_sha256}")
    metadata_lines.extend(["---", "", f"# {source['title']}", "", body, ""])
    return "\n".join(metadata_lines)


if __name__ == "__main__":
    raise SystemExit(main())
