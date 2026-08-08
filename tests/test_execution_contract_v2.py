"""WS4: Execution Contract 2.0 — ChangeIntent, ledger, hash-верификация, base_commit."""

import subprocess

import pytest

from src.core.execution_contract import (
    ChangeIntent,
    ChangeIntentLedger,
    ExecutionContract,
    get_base_commit,
    invalidate_base_commit_cache,
    sha256_file,
)
from src.mcp.tools.write_tools import _sha256_text


@pytest.fixture(autouse=True)
def _isolate_data_root(tmp_path, monkeypatch):
    """Артефакты ledger'а — во временной папке, не в реальной системной."""
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data"))
    invalidate_base_commit_cache()
    yield
    invalidate_base_commit_cache()


def test_sha256_file_deterministic(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert sha256_file(f) == sha256_file(f)
    assert len(sha256_file(f)) == 64  # sha256 hex


def test_sha256_file_missing(tmp_path):
    assert sha256_file(tmp_path / "nope.py") is None


def test_sha256_text_equals_file(tmp_path):
    f = tmp_path / "b.py"
    # newline="\n" — как _atomic_write (детерминированно, без \r\n Windows).
    # open() вместо Path.read_text(newline=...): newline в read_text — Python 3.13+
    # (CI matrix: 3.10-3.12).
    f.write_text("y = 2\n", encoding="utf-8", newline="\n")
    with f.open(encoding="utf-8", newline="\n") as fh:
        text = fh.read()
    assert _sha256_text(text) == sha256_file(f)


def test_get_base_commit_in_git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.t"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp_path, check=True
    )
    (tmp_path / "f.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    commit = get_base_commit(str(tmp_path))
    assert len(commit) == 40


def test_get_base_commit_non_git(tmp_path):
    assert get_base_commit(str(tmp_path)) == ""


def test_verify_file_write_hash_match(tmp_path):
    f = tmp_path / "c.py"
    f.write_text("z = 3\n", encoding="utf-8", newline="\n")
    ok = ExecutionContract.verify_file_write(
        str(f), expected_hash=_sha256_text("z = 3\n")
    )
    assert ok["verified"] is True
    assert ok["actual_hash"] == _sha256_text("z = 3\n")


def test_verify_file_write_hash_mismatch(tmp_path):
    f = tmp_path / "d.py"
    f.write_text("z = 3\n", encoding="utf-8", newline="\n")
    bad = ExecutionContract.verify_file_write(
        str(f), expected_hash=_sha256_text("different")
    )
    assert bad["verified"] is False
    assert any("SHA-256" in e for e in bad["errors"])


def test_ledger_record_and_query(tmp_path):
    ledger = ChangeIntentLedger(tmp_path)
    assert ledger.count() == 0
    assert ledger.record(ChangeIntent(operation="replace", file=str(tmp_path / "x.py")))
    assert ledger.count() == 1
    ledger.record(
        ChangeIntent(
            operation="safe_delete",
            file=str(tmp_path / "y.py"),
            base_commit="abc123",
            before_hash="b",
            after_hash="a",
            expected_hash="a",
            symbol="foo",
            verified=True,
        )
    )
    entries = ledger.query()
    assert len(entries) == 2
    assert entries[0]["operation"] == "replace"
    assert entries[1]["operation"] == "safe_delete"
    assert entries[1]["base_commit"] == "abc123"
    assert entries[1]["symbol"] == "foo"
    assert entries[1]["verified"] is True


def test_ledger_query_limit(tmp_path):
    ledger = ChangeIntentLedger(tmp_path)
    for i in range(10):
        ledger.record(ChangeIntent(operation=f"op{i}", file=str(tmp_path / f"{i}.py")))
    assert len(ledger.query(limit=3)) == 3
    assert ledger.query(limit=3)[0]["operation"] == "op7"


def test_ledger_isolated_from_project(tmp_path):
    """Ledger пишется в системную папку, НЕ в проект."""
    project = tmp_path / "user_project"
    project.mkdir()
    ledger = ChangeIntentLedger(project)
    ledger.record(ChangeIntent(operation="replace", file=str(project / "x.py")))
    assert ledger.path.exists()
    assert not (project / "change_intents.jsonl").exists()
