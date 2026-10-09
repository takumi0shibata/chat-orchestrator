import asyncio
import os
from uuid import uuid4

import pytest
from app.config import Folder, Settings, Skill
from app.sandbox import CommandTimeoutError, Sandbox, docker

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("RUN_DOCKER_TESTS") != "1", reason="Set RUN_DOCKER_TESTS=1"
    ),
]


async def emit(*args):
    pass


def test_git_local_operations_in_sandbox(tmp_path):
    async def scenario():
        work = tmp_path / "work"
        work.mkdir()
        sandbox = Sandbox(
            Settings(_env_file=None), Folder(id="w", label="Work", path=work),
            uuid4().hex, [], [], tmp_path / "input",
        )
        await sandbox.start()
        try:
            result = await sandbox.execute(
                """set -eu
git --version
git init -q
printf 'original\\n' > tracked.txt
test "$(git status --porcelain)" = '?? tracked.txt'
git add tracked.txt
test "$(git diff --cached --name-only)" = tracked.txt
git -c user.name='Sandbox Test' -c user.email=sandbox@example.invalid commit -q -m initial
test "$(git log -1 --format=%s)" = initial
printf 'updated\\n' > tracked.txt
git diff -- tracked.txt
test "$(git status --porcelain)" = ' M tracked.txt'
git add tracked.txt
git -c user.name='Sandbox Test' -c user.email=sandbox@example.invalid commit -q -m updated
test "$(git log --format=%s)" = "$(printf 'updated\\ninitial')"
test -z "$(git status --porcelain)"
printf 'Git local operations OK\\n'
""",
                emit,
            )
            assert result["outcome"]["exit_code"] == 0, result
            assert "git version" in result["stdout"]
            assert "-original" in result["stdout"]
            assert "+updated" in result["stdout"]
            assert "Git local operations OK" in result["stdout"]
            assert (work / ".git").is_dir()
            assert (work / "tracked.txt").read_text() == "updated\n"
        finally:
            await sandbox.close()

    asyncio.run(scenario())


def test_200_files_office_pdf_research_and_isolation(tmp_path):
    async def scenario():
        work = tmp_path / "workspace"
        work.mkdir()
        inputs = tmp_path / "input"
        inputs.mkdir()
        skill_path = tmp_path / "skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            "---\nname: test\ndescription: Test\n---\nUse local files."
        )
        (tmp_path / "host-secret").write_text("DO NOT READ")
        (work / "escape").symlink_to(tmp_path / "host-secret")
        for i in range(195):
            (work / f"file-{i}.txt").write_text(f"original {i}")
        sandbox = Sandbox(
            Settings(_env_file=None),
            Folder(id="w", label="w", path=work),
            uuid4().hex,
            [Skill(id="test", label="test", path=skill_path)],
            [],
            inputs,
        )
        await sandbox.start()
        try:
            script = r"""
import os, socket
from pathlib import Path
import numpy as np, pandas as pd, polars as pl, scipy, torch, sklearn
from sklearn.linear_model import LinearRegression
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import seaborn as sns
import transformers, datasets
from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from reportlab.pdfgen import canvas
from pypdf import PdfReader
assert os.getuid() != 0
assert not torch.cuda.is_available()
assert torch.version.cuda is None
assert not Path('/var/run/docker.sock').exists()
assert not Path('/workspace/escape').exists()
assert not os.environ.get('OPENAI_API_KEY')
assert not os.environ.get('AZURE_OPENAI_API_KEY')
try:
    Path('/skills/test/SKILL.md').write_text('overwrite')
    raise AssertionError('skill was writable')
except OSError: pass
try:
    Path('/input/test.txt').write_text('overwrite')
    raise AssertionError('input was writable')
except OSError: pass
try:
    socket.create_connection(('1.1.1.1',443),timeout=1)
    raise AssertionError('network was available')
except OSError: pass
Document().save('paper.docx')
doc=Document('paper.docx'); doc.add_paragraph('edited original'); doc.save('paper.docx')
wb=Workbook(); wb.active['A1']=42; wb.save('table.xlsx'); assert load_workbook('table.xlsx').active['A1'].value==42
prs=Presentation(); prs.slides.add_slide(prs.slide_layouts[6]); prs.save('slides.pptx'); assert len(Presentation('slides.pptx').slides)==1
c=canvas.Canvas('paper.pdf'); c.drawString(40,750,'PDF test'); c.save(); assert 'PDF test' in PdfReader('paper.pdf').pages[0].extract_text()
pd.DataFrame({'x':[1,2,3],'y':[2,4,6]}).to_csv('data.csv',index=False)
assert len([p for p in Path('.').iterdir() if p.is_file()])==200
Path('file-194.txt').write_text('direct edit')
assert torch.tensor([1.,2.]).sum().item()==3
assert np.isclose(LinearRegression().fit([[1],[2],[3]],[2,4,6]).predict([[4]])[0],8)
plt.rcParams['font.family']='Noto Sans CJK JP'
assert font_manager.findfont('Noto Sans CJK JP',fallback_to_default=False)
sns.lineplot(x=[1,2,3],y=[2,4,6]); plt.title('日本語の分析結果'); plt.savefig('analysis.png'); plt.close()
print('200 mixed files + direct edit + Office/PDF + CPU ML + Japanese plot + isolation OK')
"""
            result = await sandbox.execute(
                "python - <<'PY'\n" + script + "\nPY", emit, 180
            )
            assert result["outcome"]["exit_code"] == 0, result
            assert "isolation OK" in result["stdout"]
            assert (work / "file-194.txt").read_text() == "direct edit"
            assert (work / "analysis.png").stat().st_size > 1000
            # Actual LibreOffice conversion works without network or a writable root filesystem.
            converted = await sandbox.execute(
                "mkdir -p converted && libreoffice -env:UserInstallation=file:///tmp/lo-test --headless --convert-to pdf --outdir converted paper.docx",
                emit,
                60,
            )
            assert converted["outcome"]["exit_code"] == 0, converted
            assert (work / "converted/paper.pdf").exists()
        finally:
            await sandbox.close()
        assert (work / "file-194.txt").read_text() == "direct edit"

    asyncio.run(scenario())


def test_timeout_removes_container_and_descendants(tmp_path):
    async def scenario():
        s = Settings(_env_file=None, command_timeout=1)
        sandbox = Sandbox(
            s,
            Folder(id="w", label="w", path=tmp_path),
            uuid4().hex,
            [],
            [],
            tmp_path / "input",
        )
        await sandbox.start()
        with pytest.raises(CommandTimeoutError) as error:
            await sandbox.execute("sleep 100 & wait", emit)
        assert error.value.timeout_seconds == 1
        with pytest.raises(RuntimeError):
            await docker("inspect", sandbox.name)
        await sandbox.close()

    asyncio.run(scenario())


def test_recursive_search_skips_generated_directories_and_symlinks(tmp_path):
    async def scenario():
        generated = [".venv", "venv", "node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"]
        for name in generated:
            directory = tmp_path / name
            directory.mkdir()
            (directory / "dependency.py").write_text("target_summary = 'dependency'\n")
        # grep -R follows host environment links and can block on special files.
        (tmp_path / ".venv" / "python").symlink_to("/missing-host-python")
        os.mkfifo(tmp_path / ".venv" / "blocked")
        source = tmp_path / "src"
        source.mkdir()
        (source / "analysis.py").write_text("target_summary = 'source'\n")
        sandbox = Sandbox(
            Settings(_env_file=None, command_timeout=5),
            Folder(id="w", label="w", path=tmp_path),
            uuid4().hex, [], [], tmp_path / "input",
        )
        await sandbox.start()
        try:
            excludes = ",".join(generated)
            commands = [
                f"rg --hidden --no-ignore -n -g '*.py' -g '!{{{excludes}}}/**' target_summary .",
                f"grep -rI --devices=skip --exclude-dir={{{excludes}}} -n target_summary .",
            ]
            for command in commands:
                result = await sandbox.execute(command, emit)
                assert result["outcome"]["exit_code"] == 0, result
                assert "src/analysis.py:1:target_summary = 'source'" in result["stdout"]
                assert "dependency" not in result["stdout"]
                assert result["stderr"] == ""
        finally:
            await sandbox.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["stop", "run_timeout"])
def test_cancel_removes_container(tmp_path, mode):
    async def scenario():
        sandbox = Sandbox(
            Settings(_env_file=None),
            Folder(id="w", label="w", path=tmp_path),
            uuid4().hex,
            [],
            [],
            tmp_path / "input",
        )
        await sandbox.start()
        if mode == "stop":
            task = asyncio.create_task(sandbox.execute("sleep 100 & wait", emit))
            await asyncio.sleep(0.5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError) as error:
                async with asyncio.timeout(0.5):
                    await sandbox.execute("sleep 100 & wait", emit)
            assert not isinstance(error.value, CommandTimeoutError)
        with pytest.raises(RuntimeError):
            await docker("inspect", sandbox.name)

    asyncio.run(scenario())


def test_uv_run_preserves_host_environment_and_lockfile(tmp_path):
    async def scenario():
        work = tmp_path / "work"
        work.mkdir()
        host_env = work / ".venv"
        (host_env / "bin").mkdir(parents=True)
        (host_env / "bin/python").symlink_to("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3")
        (host_env / "pyvenv.cfg").write_text("home = /Library/Frameworks/Python.framework/Versions/3.12/bin\nversion = 3.12.0\n")
        (host_env / "host-package.py").write_text("# macOS package sentinel")
        (work / "pyproject.toml").write_text('[project]\nname="host-project"\nversion="0.1.0"\nrequires-python=">=3.12"\ndependencies=[]\n')
        (work / "uv.lock").write_text("# host lock sentinel\n")
        before = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob("*") if p.is_file() and not p.is_symlink()}
        sandbox = Sandbox(Settings(_env_file=None), Folder(id="w", label="w", path=work), uuid4().hex, [], [], tmp_path / "input")
        await sandbox.start()
        try:
            for command in ["python -c 'import numpy; print(numpy.__version__)'", "cd /workplace; uv run python -c 'import numpy; print(numpy.__version__)'"]:
                result = await sandbox.execute(command, emit)
                assert result["outcome"]["exit_code"] == 0, result
            after = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob("*") if p.is_file() and not p.is_symlink()}
            assert before == after
            assert (host_env / "bin/python").readlink().as_posix().startswith("/Library/")
        finally:
            await sandbox.close()
    asyncio.run(scenario())


def test_pytest_runs_workspace_tests_in_sandbox(tmp_path):
    async def scenario():
        work = tmp_path / "work"
        work.mkdir()
        (work / "test_example.py").write_text(
            "import numpy as np\n\n"
            "def test_sandbox_dependency():\n"
            "    assert np.array([1, 2, 3]).sum() == 6\n"
        )
        sandbox = Sandbox(
            Settings(_env_file=None),
            Folder(id="w", label="w", path=work),
            uuid4().hex,
            [],
            [],
            tmp_path / "input",
        )
        await sandbox.start()
        try:
            for command in ("pytest -q", "python -m pytest -q"):
                result = await sandbox.execute(command, emit)
                assert result["outcome"]["exit_code"] == 0, result
                assert "1 passed" in result["stdout"], result
        finally:
            await sandbox.close()

    asyncio.run(scenario())


def test_find_longer_than_model_ten_second_hint(tmp_path):
    async def scenario():
        (tmp_path / "target.txt").write_text("target")
        sandbox = Sandbox(Settings(_env_file=None, command_timeout=30), Folder(id="w", label="w", path=tmp_path), uuid4().hex, [], [], tmp_path / "input")
        await sandbox.start()
        try:
            result = await sandbox.execute(r"find . -name target.txt -exec sleep 11 \; -print", emit, 10)
            assert result["outcome"]["exit_code"] == 0, result
            assert "target.txt" in result["stdout"]
        finally:
            await sandbox.close()
    asyncio.run(scenario())


def test_apply_patch_runs_inside_sandbox(tmp_path):
    async def scenario():
        work = tmp_path / "work"
        work.mkdir()
        (work / "a.txt").write_text("one\n")
        outside = tmp_path / "outside"
        outside.mkdir()
        (work / "link").symlink_to(outside)
        sandbox = Sandbox(
            Settings(_env_file=None), Folder(id="w", label="Work", path=work),
            uuid4().hex, [], [], tmp_path / "input",
        )
        await sandbox.start()
        try:
            updated = await sandbox.apply_patch(
                dict(type="update_file", path="/workspace/a.txt", diff="@@\n-one\n+two\n")
            )
            assert updated["status"] == "completed", updated
            created = await sandbox.apply_patch(
                dict(type="create_file", path="新規/b.txt", diff="+日本語\n")
            )
            assert created["status"] == "completed", created
            escaped = await sandbox.apply_patch(
                dict(type="create_file", path="link/x.txt", diff="+x\n")
            )
            assert escaped["status"] == "failed"
            readonly = await sandbox.apply_patch(
                dict(type="create_file", path="/input/x.txt", diff="+x\n")
            )
            assert readonly["status"] == "failed"
        finally:
            await sandbox.close()
        assert (work / "a.txt").read_text() == "two\n"
        assert (work / "新規/b.txt").read_text() == "日本語\n"
        assert (work / "新規/b.txt").stat().st_uid == os.getuid()
        assert not (outside / "x.txt").exists()

    asyncio.run(scenario())
