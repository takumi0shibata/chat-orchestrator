from app.attachments import file_snapshot
from app.config import Folder, Settings, Skill
from app.sandbox import Sandbox, command_time_limit
from app.workspace_files import scan_files


def test_timeout_bounds():
    settings = Settings(_env_file=None)
    assert command_time_limit(settings, 10) == 60
    assert command_time_limit(settings, 180) == 180
    assert command_time_limit(settings, 1000) == 600
    assert command_time_limit(settings) == 600
    assert command_time_limit(Settings(_env_file=None, command_timeout=5), 10) == 5
    assert command_time_limit(Settings(_env_file=None, command_timeout_min=1), 10) == 10


def test_snapshot_prunes_generated_environments(tmp_path):
    for directory in ['.venv', 'node_modules', '.git', '__pycache__']:
        folder = tmp_path / directory
        folder.mkdir()
        (folder / 'generated').write_text('ignored')
    (tmp_path / 'result.txt').write_text('output')
    assert list(file_snapshot(tmp_path)) == ['result.txt']


def test_shared_scan_skips_links_and_resolves_storage_exclusion(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    storage = work / "storage"
    storage.mkdir()
    (storage / "blob").write_text("checkpoint data")
    alias = tmp_path / "storage-link"
    alias.symlink_to(storage, target_is_directory=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("outside workspace")
    (work / "linked-dir").symlink_to(outside, target_is_directory=True)
    (work / "linked-file").symlink_to(outside / "private.txt")
    (work / "result.txt").write_text("output")
    assert set(scan_files(work, excluded=(alias,))) == {"result.txt"}


def test_skill_mounts_are_read_only_and_network_remains_disabled(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    skills = []
    for sid in ("review", "brief"):
        folder = tmp_path / sid
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {sid}\ndescription: Test {sid}\n---\nUse local files.")
        skills.append(Skill(id=sid, label=sid, path=folder))
    sandbox = Sandbox(Settings(_env_file=None), Folder(id="w", label="Work", path=work), "test", skills, [], tmp_path / "input")
    args = sandbox.arguments()
    mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
    for skill in skills:
        assert f"type=bind,src={skill.path},dst=/skills/{skill.id},readonly" in mounts
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
