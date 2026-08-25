"""test_lock_guard.py — git-based лока: acquire/status/release на мини-репо.

git через CLI (герметично); push замокан — в тесте нет remote. Проверяются
жизненный цикл лока, запрет повторного acquire и чужой лок не снимается.
"""

import subprocess
from pathlib import Path

import pytest

import scripts.lock_guard as lg


def _make_repo(tmp_path) -> Path:
    repo = tmp_path / "proj"
    repo.mkdir()
    assert subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True).returncode == 0
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, capture_output=True)
    (repo / "a.py").write_text("A = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, capture_output=True)
    return repo


@pytest.fixture
def patched(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(lg, "LOCKS_DIR", repo / ".locks")
    monkeypatch.setattr(lg, "_repo", lambda: repo)
    real_git = lg._git

    def fake_git(cwd, *args):
        if args and args[0] == "push":
            return subprocess.CompletedProcess(args, 0, "")  # нет remote — замок
        return real_git(cwd, *args)

    monkeypatch.setattr(lg, "_git", fake_git)
    return repo


def test_acquire_status_release_lifecycle(patched, capsys):
    repo = patched
    assert lg.cmd_acquire(repo, "src/core/a.py", "rework") == 0
    lock_file = repo / ".locks" / "src_core_a_py.lock"
    assert lock_file.exists()
    assert "src/core/a.py" in lock_file.read_text(encoding="utf-8")

    assert lg.cmd_status(repo) == 0
    assert "src_core_a_py.lock" in capsys.readouterr().out

    assert lg.cmd_release(repo, "src/core/a.py") == 0
    assert not lock_file.exists()


def test_second_acquire_rejected(patched, capsys):
    repo = patched
    assert lg.cmd_acquire(repo, "src/core/a.py", "one") == 0
    assert lg.cmd_acquire(repo, "src/core/a.py", "two") != 0
    assert "уже существует" in capsys.readouterr().out


def test_foreign_lock_not_released(patched, monkeypatch, capsys):
    repo = patched
    # чужой лок: владелец в файле ≠ текущий git user.name ("t")
    lock_dir = repo / ".locks"
    lock_dir.mkdir(exist_ok=True)
    (lock_dir / "src_x_py.lock").write_text(
        '{"resource": "src/x.py", "agent": "someone-else", "purpose": "y"}',
        encoding="utf-8",
    )
    assert lg.cmd_release(repo, "src/x.py") != 0
    assert "чужой" in capsys.readouterr().out
    assert (lock_dir / "src_x_py.lock").exists()
