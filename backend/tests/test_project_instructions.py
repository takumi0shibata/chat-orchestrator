import pytest
from app.config import RuntimeConfig
from app.project_instructions import load_project_instructions
from pydantic import ValidationError


def config(**updates):
    return RuntimeConfig(**updates)


def test_instruction_precedence_and_empty_files(tmp_path):
    (tmp_path / "AGENTS.override.md").write_text("\n")
    (tmp_path / "AGENTS.md").write_text("use agents")
    (tmp_path / "TEAM_GUIDE.md").write_text("use fallback")
    loaded = load_project_instructions(
        tmp_path,
        config(project_doc_fallback_filenames=["TEAM_GUIDE.md"]),
    )
    assert loaded.filename == "AGENTS.md"
    assert loaded.text == "use agents"

    (tmp_path / "AGENTS.override.md").write_text("use override")
    loaded = load_project_instructions(
        tmp_path,
        config(project_doc_fallback_filenames=["TEAM_GUIDE.md"]),
    )
    assert loaded.filename == "AGENTS.override.md"
    assert loaded.text == "use override"

    (tmp_path / "AGENTS.override.md").unlink()
    (tmp_path / "AGENTS.md").write_text("  \n")
    loaded = load_project_instructions(
        tmp_path,
        config(project_doc_fallback_filenames=["TEAM_GUIDE.md"]),
    )
    assert loaded.filename == "TEAM_GUIDE.md"


def test_instruction_limit_preserves_utf8_boundary(tmp_path):
    (tmp_path / "AGENTS.md").write_bytes("abcあ".encode())
    loaded = load_project_instructions(tmp_path, config(project_doc_max_bytes=5))
    assert loaded.text == "abc"
    assert loaded.truncated is True


def test_invalid_instruction_sources_are_rejected(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    (tmp_path / "AGENTS.md").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        load_project_instructions(tmp_path, config())

    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").write_bytes(b"bad \xff")
    with pytest.raises(ValueError, match="UTF-8"):
        load_project_instructions(tmp_path, config())


@pytest.mark.parametrize(
    "names",
    [
        ["nested/TEAM.md"],
        ["nested\\TEAM.md"],
        ["AGENTS.md"],
        ["TEAM.md", "TEAM.md"],
        ["  "],
        ["BAD\nNAME.md"],
    ],
)
def test_fallback_names_must_be_unique_basenames(names):
    with pytest.raises(ValidationError):
        config(project_doc_fallback_filenames=names)


def test_missing_instruction_file_is_optional(tmp_path):
    assert load_project_instructions(tmp_path, config()) is None
