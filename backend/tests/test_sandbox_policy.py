from app.attachments import file_snapshot
from app.config import Settings
from app.sandbox import command_time_limit


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
