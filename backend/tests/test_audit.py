import os

import pytest

from app.audit import parse_evidence, parse_findings, plain, read_audit
from app.config import Folder
from test_api import app_client  # noqa: F401 - shared API fixture

FINDINGS = """# Audit findings

```markdown
## F-999 Example in a fence is ignored
- status: open
```

## F-001 READMEに書かれた `make train` が存在しない
- status: open
- severity: major
- relation: README ↔ 実態
- verdict: 矛盾
- verified: executed `make -n train` → "No rule"
- evidence:
  - README.md:2 `make train`
  - Makefile — `train` ターゲットはない
- options: READMEを直す / Makefileに `train` を追加する
- found: 2026-10-14-01
- decision:

## F-002 Moved and fabricated quotes
- status: Decided
- severity: urgent
- evidence:
  - README.md:1 `uv run   pytest`
  - README.md:2 `make deploy`
  - missing.py:3 `x = 1`
  - ../outside.txt `secret`
  - README.md:99 `make train`
- decision: READMEを直す

## F-003 Unknown status
- status: maybe
- evidence: README.md `# Demo`
"""


def project(tmp_path, name="work"):
    path = tmp_path / name
    path.mkdir()
    return Folder(id=name, label=name, path=path)


def audit_folder(work):
    folder = work.path / ".chat-orchestrator" / "audit"
    folder.mkdir(parents=True)
    (work.path / "README.md").write_text("# Demo\nRun make train to train.\n\n\n\nuv run pytest\n")
    (work.path / "Makefile").write_text("train-bert:\n\tpython train.py\n")
    (folder / "charter.md").write_text("# Audit Charter\n## 確認する関係\n- [x] README ↔ 実態\n")
    (folder / "findings.md").write_text(FINDINGS)
    (folder / "reports").mkdir()
    (folder / "reports" / "2026-10-13-01.md").write_text("# 監査 2026-10-13-01\n## 確認しなかったこと\n- 古い\n")
    (folder / "reports" / "2026-10-14-01.md").write_text(
        "# 監査 2026-10-14-01\n## 確認したこと\n- `make -n`\n## 確認しなかったこと\n- paper/（対象外）\n- GPUが必要なテスト\n"
    )
    return folder


def test_missing_folder_is_reported_without_creating_records(tmp_path):
    work = project(tmp_path)
    assert read_audit(work)["exists"] is False
    (work.path / ".chat-orchestrator").mkdir()
    result = read_audit(work)
    assert result["exists"] is False and result["findings"] == []
    assert not (work.path / ".chat-orchestrator" / "audit").exists()


def test_reads_charter_findings_and_reports_newest_first(tmp_path):
    work = project(tmp_path)
    audit_folder(work)
    result = read_audit(work)
    assert result["exists"] is True
    assert result["charter"]["content"].startswith("# Audit Charter")
    assert [r["id"] for r in result["reports"]] == ["2026-10-14-01", "2026-10-13-01"]
    assert result["reports"][0]["unchecked"] == ["paper/（対象外）", "GPUが必要なテスト"]
    assert [f["id"] for f in result["findings"]] == ["F-001", "F-002", "F-003"]
    first = result["findings"][0]
    assert first["title"] == "READMEに書かれた make train が存在しない"
    assert first["status"] == "open" and first["severity"] == "major"
    assert first["verdict"] == "矛盾" and first["relation"] == "README ↔ 実態"
    assert first["options"] == ["READMEを直す", "Makefileに `train` を追加する"]
    assert first["decision"] == "" and first["found"] == "2026-10-14-01"
    assert result["errors"] == []


def test_evidence_quotes_are_checked_against_files(tmp_path):
    work = project(tmp_path)
    audit_folder(work)
    findings = read_audit(work)["findings"]
    quote, note = findings[0]["evidence"]
    assert quote["check"] == "verified" and quote["found_line"] == 2
    assert {"line": 2, "text": "Run make train to train."} in quote["context"]
    assert note["check"] == "note" and note["quote"] is None and note["path"] == "Makefile"
    checks = [(e["check"], e["found_line"]) for e in findings[1]["evidence"]]
    assert checks == [
        ("moved", 6),  # whitespace-normalized quote found away from the cited line
        ("missing", None),
        ("file_missing", None),
        ("invalid_path", None),
        ("line_out_of_range", None),
    ]
    assert findings[2]["evidence"][0]["check"] == "verified"


def test_unknown_values_are_warned_and_shown_safely(tmp_path):
    work = project(tmp_path)
    audit_folder(work)
    result = read_audit(work)
    assert result["findings"][1]["status"] == "decided"
    assert result["findings"][1]["severity"] is None
    assert result["findings"][2]["status"] == "open"
    assert any("unknown severity" in w for w in result["warnings"])
    assert any("unknown status" in w for w in result["warnings"])


def test_symlinked_evidence_and_records_are_not_followed(tmp_path):
    work = project(tmp_path)
    folder = audit_folder(work)
    secret = tmp_path / "secret.txt"
    secret.write_text("token\n")
    os.symlink(secret, work.path / "link.txt")
    (folder / "findings.md").write_text("## F-001 Link\n- evidence:\n  - link.txt:1 `token`\n")
    evidence, = read_audit(work)["findings"][0]["evidence"]
    assert evidence["check"] == "unreadable" and evidence["context"] == []
    (folder / "findings.md").unlink()
    os.symlink(secret, folder / "findings.md")
    result = read_audit(work)
    assert result["findings"] == [] and result["errors"]


def test_invalid_documents_do_not_hide_other_records(tmp_path):
    work = project(tmp_path)
    folder = audit_folder(work)
    (folder / "charter.md").write_bytes(b"\xff\xfe")
    (folder / "reports" / "2026-10-14-01.md").write_bytes(b"x" * (64 * 1024 + 1))
    result = read_audit(work)
    assert result["charter"] is None
    assert len(result["findings"]) == 3
    assert [r["id"] for r in result["reports"]] == ["2026-10-13-01"]
    assert len(result["errors"]) == 2


@pytest.mark.parametrize("text,expected", [
    ("`Trainer.fit(label_smoothing=0.1)` と **太字** と _強調_", "Trainer.fit(label_smoothing=0.1) と 太字 と 強調"),
    ("[spec](docs/spec.md) の tests/gpu_only", "spec の tests/gpu_only"),
])
def test_plain_keeps_identifiers(text, expected):
    assert plain(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("README.md:42 `make train`", ("README.md", 42, 42, "make train", "")),
    ("/workspace/paper/main.tex:10-12 `81.2` 表2", ("paper/main.tex", 10, 12, "81.2", "表2")),
    ("<docs/my spec.md>:3 `x`", ("docs/my spec.md", 3, 3, "x", "")),
    ("Makefile — ない", ("Makefile", None, None, None, "ない")),
])
def test_parse_evidence(text, expected):
    e = parse_evidence(text)
    assert (e["path"], e["start"], e["end"], e["quote"], e["note"]) == expected


def test_finding_limit():
    content = "".join(f"## F-{i:03d} x\n" for i in range(501))
    with pytest.raises(ValueError, match="500"):
        parse_findings(content)


def test_audit_api_reads_registered_projects_only(app_client):
    http, work, _ = app_client
    assert http.get("/api/workspaces/work/audit").json()["exists"] is False
    audit_folder(Folder(id="work", label="Work", path=work))
    body = http.get("/api/workspaces/work/audit").json()
    assert body["exists"] is True and len(body["findings"]) == 3
    assert http.get("/api/workspaces/unknown/audit").status_code == 400
