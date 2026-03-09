from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 12000
MAX_PDF_PAGES = 30
DOCLING_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm", ".md", ".csv"}
PLAIN_TEXT_EXTENSIONS = {".txt", ".json"}
ALLOWED_EXTENSIONS = DOCLING_EXTENSIONS | PLAIN_TEXT_EXTENSIONS


@dataclass(frozen=True)
class PendingAttachment:
    id: str
    name: str
    content_type: str
    size_bytes: int
    original_path: str
    parsed_markdown_path: str


async def _read_bytes(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large: {upload.filename}")
    return raw


def _extract_text_from_plain(raw: bytes, filename: str) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            return text[:MAX_TEXT_CHARS]
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail=f"Unsupported encoding: {filename}")


@lru_cache(maxsize=1)
def _docling_converter():
    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=500,
            detail="Docling is not installed in the backend environment.",
        ) from exc
    return DocumentConverter()


def _extract_text_with_docling(path: Path, filename: str) -> str:
    converter = _docling_converter()
    try:
        result = converter.convert(
            path,
            max_num_pages=MAX_PDF_PAGES,
            max_file_size=MAX_FILE_BYTES,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse attachment: {filename}") from exc

    text = result.document.export_to_markdown().strip()
    if not text:
        text = f"[No extractable text in {filename}]"
    return text[:MAX_TEXT_CHARS]


async def save_attachment(
    *,
    conversation_id: str,
    upload: UploadFile,
    attachments_root: Path,
) -> PendingAttachment:
    filename = upload.filename or "unnamed"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

    raw = await _read_bytes(upload)
    attachment_id = str(uuid4())
    attachment_dir = attachments_root / conversation_id / attachment_id
    attachment_dir.mkdir(parents=True, exist_ok=True)

    original_path = attachment_dir / f"original{suffix}"
    original_path.write_bytes(raw)

    if suffix in PLAIN_TEXT_EXTENSIONS:
        parsed_markdown = _extract_text_from_plain(raw, filename)
    else:
        parsed_markdown = _extract_text_with_docling(original_path, filename)

    parsed_markdown_path = attachment_dir / "parsed.md"
    parsed_markdown_path.write_text(parsed_markdown, encoding="utf-8")

    return PendingAttachment(
        id=attachment_id,
        name=filename,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=len(raw),
        original_path=str(original_path),
        parsed_markdown_path=str(parsed_markdown_path),
    )
