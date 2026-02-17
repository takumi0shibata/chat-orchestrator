from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 12000
MAX_PDF_PAGES = 30
ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".pdf"}


@dataclass
class ExtractedAttachment:
    name: str
    content: str


async def _read_bytes(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large: {upload.filename}")
    return raw


def _extract_text_from_pdf(raw: bytes, filename: str) -> str:
    if PdfReader is None:
        raise HTTPException(
            status_code=500,
            detail="PDF extraction backend dependency missing. Install pypdf in backend environment.",
        )

    reader = PdfReader(BytesIO(raw))
    chunks: list[str] = []
    max_pages = min(len(reader.pages), MAX_PDF_PAGES)
    for idx in range(max_pages):
        page_text = reader.pages[idx].extract_text() or ""
        page_text = page_text.strip()
        if page_text:
            chunks.append(f"[Page {idx + 1}] {page_text}")

    text = "\n".join(chunks).strip()
    if not text:
        text = f"[No extractable text in {filename}]"
    return text[:MAX_TEXT_CHARS]


def _extract_text_from_plain(raw: bytes, filename: str) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            return text[:MAX_TEXT_CHARS]
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail=f"Unsupported encoding: {filename}")


async def extract_attachments(files: list[UploadFile]) -> list[ExtractedAttachment]:
    extracted: list[ExtractedAttachment] = []

    for upload in files:
        filename = upload.filename or "unnamed"
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

        raw = await _read_bytes(upload)
        if suffix == ".pdf":
            content = _extract_text_from_pdf(raw, filename)
        else:
            content = _extract_text_from_plain(raw, filename)

        extracted.append(ExtractedAttachment(name=filename, content=content))

    return extracted
