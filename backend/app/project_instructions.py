import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.attachments import open_regular


@dataclass(frozen=True)
class ProjectInstructions:
    filename: str
    text: str
    truncated: bool

    def message(self):
        return {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "# AGENTS.md instructions for /workspace\n\n"
                        "<INSTRUCTIONS>\n"
                        f"{self.text}\n"
                        "</INSTRUCTIONS>"
                    ),
                }
            ],
        }


def _decode_limited(raw: bytes, truncated: bool, filename: str):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        # A byte cap may split the last UTF-8 code point. Remove only that partial
        # code point; invalid UTF-8 elsewhere is a configuration error.
        if truncated and error.end == len(raw) and error.reason == "unexpected end of data":
            return raw[: error.start].decode("utf-8")
        raise ValueError(f"Project instruction file must be UTF-8: {filename}") from None


def load_project_instructions(root: Path, config):
    candidates = [
        "AGENTS.override.md",
        "AGENTS.md",
        *config.project_doc_fallback_filenames,
    ]
    for filename in candidates:
        path = root / filename
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError(
                f"Could not inspect project instruction file: {filename}"
            ) from error
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(
                f"Project instruction file cannot be a symbolic link: {filename}"
            )
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(
                f"Project instruction path must be a regular file: {filename}"
            )
        try:
            with open_regular(root, filename) as file:
                raw = file.read(config.project_doc_max_bytes + 1)
        except (OSError, ValueError) as error:
            raise ValueError(
                f"Could not read project instruction file: {filename}"
            ) from error
        truncated = len(raw) > config.project_doc_max_bytes
        payload = raw[: config.project_doc_max_bytes]
        text = _decode_limited(payload, truncated, filename)
        if not text.strip():
            continue
        return ProjectInstructions(filename, text, truncated)
    return None
