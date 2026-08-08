"""WS6: Commit Memory 2.0 — significance gate (RecMem-подход)."""

import subprocess
from pathlib import Path

import pytest

from src.core.commit_memory import CommitMemory


@pytest.fixture(autouse=True)
def _isolate_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MSCODEBASE_DATA_DIR", str(tmp_path / "data"))
    yield


def _make_repo(tmp_path: Path, commits: list[tuple[str, list[str]]]) -> Path:
    """Создаёт git-репо: commits = [(message, [files])]."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    for i, (msg, files) in enumerate(commits):
        for f in files:
            p = repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"content {i}\n", encoding="utf-8", newline="\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", msg], cwd=repo, check=True)
    return repo


def test_significance_scores_synthetic():
    cm = CommitMemory(Path("."))  # репо не нужен для чистого скоринга
    doc_commit = {"message": "docs: update readme", "body": "", "files": ["README.md"]}
    bug_commit = {
        "message": "fix: race condition in queue",
        "body": "lock was not held during batch",
        "files": ["src/core/task_queue.py"],
    }
    refactor_commit = {
        "message": "refactor: move search pipeline",
        "body": "",
        "files": ["src/a.py", "src/b.py", "src/c.py", "src/d.py"],
    }
    doc_score = cm.significance_score(doc_commit)
    bug_score = cm.significance_score(bug_commit)
    refactor_score = cm.significance_score(refactor_commit)
    assert doc_score < bug_score
    assert doc_score < refactor_score
    assert bug_score >= 0.4  # bug fix = значимый
    assert refactor_score >= 0.4  # multi-file refactor = значимый


def test_significance_integration_git(tmp_path):
    repo = _make_repo(
        tmp_path,
        [
            ("docs: update readme", ["README.md"]),
            ("fix: race in queue", ["src/q.py"]),
            ("refactor: move pipeline", ["src/a.py", "src/b.py", "src/c.py", "src/d.py"]),
        ],
    )
    cm = CommitMemory(repo)
    commits = cm.fetch_commits(limit=10)
    assert len(commits) == 3

    significant = cm.get_significant_commits(limit=10, min_score=0.4)
    assert len(significant) >= 1
    # Рефакторинг — самая значимая запись.
    assert significant[0]["message"].startswith("refactor")
    for entry in significant:
        assert entry["significance_score"] >= 0.4


def test_significance_no_false_positives_for_docs(tmp_path):
    repo = _make_repo(tmp_path, [("docs: update readme", ["README.md"])])
    cm = CommitMemory(repo)
    cm.fetch_commits(limit=10)
    assert cm.get_significant_commits(min_score=0.4) == []


def test_significance_returns_score_field(tmp_path):
    repo = _make_repo(tmp_path, [("fix: crash on shutdown", ["src/x.py"])])
    cm = CommitMemory(repo)
    cm.fetch_commits(limit=10)
    entries = cm.get_significant_commits()
    assert entries
    assert all("significance_score" in e for e in entries)
