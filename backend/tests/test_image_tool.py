import base64

import pytest
from app import image_tool

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    work, other = tmp_path / "workspace", tmp_path / "outside"
    work.mkdir()
    other.mkdir()
    monkeypatch.setattr(image_tool, "WORKSPACE", str(work))
    monkeypatch.setattr(image_tool, "ROOTS", (str(work),))
    return work, other


def test_reads_relative_and_absolute_paths(roots):
    work, _ = roots
    (work / "plots").mkdir()
    (work / "plots/a.png").write_bytes(PNG)
    for path in ("plots/a.png", str(work / "plots/a.png")):
        result = image_tool.view_image(path)
        assert result["status"] == "completed", result
        assert result["image_url"].startswith("data:image/png;base64,")
        assert result["path"].endswith("plots/a.png")


def test_rejects_paths_outside_roots_and_non_images(roots):
    work, other = roots
    (other / "secret.png").write_bytes(PNG)
    (work / "link.png").symlink_to(other / "secret.png")
    (work / "notes.txt").write_text("not an image")
    for path, message in [
        (str(other / "secret.png"), "only under"), ("link.png", "only under"),
        ("../outside/secret.png", "only under"), ("missing.png", "not found"),
        ("", "required"), ("notes.txt", "Unsupported"),
    ]:
        result = image_tool.view_image(path)
        assert result["status"] == "failed"
        assert message in result["output"]
        assert "image_url" not in result


def test_rejects_oversized_files(roots, monkeypatch):
    work, _ = roots
    (work / "big.png").write_bytes(PNG + b"\0" * 100)
    monkeypatch.setattr(image_tool, "MAX_INPUT_BYTES", 50)
    assert "larger than" in image_tool.view_image("big.png")["output"]
