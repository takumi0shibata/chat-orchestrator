"""Load an image for the model inside the sandbox.

This module uses only the standard library plus optional Pillow from the sandbox
runtime: its source is sent to the container and executed there, so paths and
symlinks resolve against the sandbox filesystem.
"""

import base64
import io
import json
import os
import posixpath
import sys

WORKSPACE = "/workspace"
ROOTS = (WORKSPACE, "/input", "/resources", "/skills", "/tmp")
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_SIDE = 2048
THUMBNAIL_SIDE = 320
SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


class ImageError(Exception):
    pass


def resolve(path):
    if not isinstance(path, str) or not path.strip() or "\0" in path:
        raise ImageError("An image path is required")
    path = path.strip()
    if not path.startswith("/"):
        path = posixpath.join(WORKSPACE, path)
    real = os.path.realpath(path)
    if not any(real == root or real.startswith(root + "/") for root in ROOTS):
        raise ImageError(f"Images can be read only under {', '.join(ROOTS)}: {path}")
    if not os.path.isfile(real):
        raise ImageError(f"Image not found: {path}")
    if os.path.getsize(real) > MAX_INPUT_BYTES:
        raise ImageError(f"Image is larger than {MAX_INPUT_BYTES // (1024 * 1024)} MiB: {path}")
    return path, real


def sniff(raw):
    for signature, mime in SIGNATURES.items():
        if raw.startswith(signature):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def encode(image, keep_alpha):
    buffer = io.BytesIO()
    if keep_alpha:
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), "image/png"
    image.convert("RGB").save(buffer, format="JPEG", quality=88)
    return buffer.getvalue(), "image/jpeg"


def load_with_pillow(raw):
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(raw))
        image.seek(0)
        image.load()
    except Exception as error:
        raise ImageError(f"Unsupported or corrupt image: {error}") from error
    original = image.size
    source_mime = Image.MIME.get(image.format or "")
    keep_alpha = image.mode in ("RGBA", "LA", "P") or "transparency" in image.info
    resized = max(original) > MAX_SIDE
    if resized:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    if not resized and source_mime in ("image/png", "image/jpeg", "image/webp") \
            and len(raw) <= MAX_OUTPUT_BYTES:
        data, mime = raw, source_mime
    else:
        if image.mode not in ("RGB", "RGBA", "L", "LA"):
            image = image.convert("RGBA" if keep_alpha else "RGB")
        data, mime = encode(image, keep_alpha)
    preview = image.copy()
    preview.thumbnail((THUMBNAIL_SIDE, THUMBNAIL_SIDE))
    if preview.mode != "RGB":
        background = Image.new("RGB", preview.size, "white")
        rgba = preview.convert("RGBA")
        background.paste(rgba, mask=rgba.getchannel("A"))
        preview = background
    thumbnail = io.BytesIO()
    preview.save(thumbnail, format="JPEG", quality=80)
    return dict(
        data=data, mime=mime, width=image.size[0], height=image.size[1],
        original_width=original[0], original_height=original[1],
        thumbnail="data:image/jpeg;base64," + base64.b64encode(thumbnail.getvalue()).decode(),
    )


def view_image(path):
    try:
        shown, real = resolve(path)
        with open(real, "rb") as handle:
            raw = handle.read()
        try:
            image = load_with_pillow(raw)
        except ImportError:
            mime = sniff(raw)
            if not mime:
                raise ImageError("Unsupported image format; use PNG, JPEG, WebP or GIF") from None
            image = dict(data=raw, mime=mime, width=None, height=None,
                         original_width=None, original_height=None, thumbnail=None)
        if len(image["data"]) > MAX_OUTPUT_BYTES:
            raise ImageError("Image is too large to send after resizing")
    except (ImageError, OSError) as error:
        return dict(status="failed", output=str(error), path=path)
    data = image.pop("data")
    size = f"{image['width']}x{image['height']}" if image["width"] else "unknown size"
    resized = image["original_width"] and image["original_width"] != image["width"]
    output = f"Image {shown} ({size} {image['mime']}" + (
        f", resized from {image['original_width']}x{image['original_height']})" if resized else ")"
    )
    return dict(
        status="completed", output=output, path=shown,
        image_url=f"data:{image['mime']};base64," + base64.b64encode(data).decode(),
        **image,
    )


if __name__ == "__main__":
    json.dump(view_image(json.load(sys.stdin)["path"]), sys.stdout)
