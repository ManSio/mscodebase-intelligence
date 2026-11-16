"""Guard: git-секции не висят в фоновом потоке и не зовут git на каждый коммит.

Замер 2026-11-16:
- `get_context(intent="explain")` — таймаут 30 с: git-секция использовала
  `subprocess.run(capture_output=True)` внутри `asyncio.to_thread`
  (Windows-ловушка из AGENTS.md §6);
- `CommitMemory.fetch_commits` — 14.3 с / 17.9 с на 244/316 коммитов
  (по `git diff-tree` на коммит), из-за чего `get_bug_correlation` уходил в таймаут.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from src.core.commit_memory import CommitMemory
from src.mcp.tools.context_tool import GetContextTool


def _git(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    if env_extra:
        env.update(env_extra)
    import os

    full_env = {**os.environ, **env}
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=full_env, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return (r.stdout or "").strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "feat: alpha")
    (repo / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-q", "-m", "fix: beta bugfix")
    return repo


@pytest.mark.asyncio
async def test_git_section_does_not_hang(git_repo: Path):
    """Секция git обязана вернуться быстро (висящий пайп ловится таймаутом).

    Живой замер (сервер): 30 016 мс таймаута → 235 мс после перехода на
    Popen+communicate. В юнит-контексте ловушка не воспроизводится (виснет
    только когда stdout сервера — JSON-RPC-пайп), поэтому регрессию держит
    ещё и структурный guard ниже.
    """
    tool = GetContextTool.__new__(GetContextTool)  # без DI: нужен только git
    tool._services = None
    tool._resolve_target_path = lambda _x=None: git_repo

    result = await asyncio.wait_for(
        tool._section_git("alpha", {"meta": {"file_path": str(git_repo / "a.py")}}),
        timeout=15,
    )

    assert result is not None, "git-секция должна вернуть коммиты"
    assert "feat: alpha" in result["text"]


def test_context_tool_has_no_capture_output():
    """Структурный guard: в context_tool нельзя `capture_output=True`.

    Именно эта форма внутри `asyncio.to_thread` вешает пайп на Windows
    (AGENTS.md §6). Проверяем AST, а не текст, чтобы не ловить комментарии.
    """
    import ast
    import pathlib as _pl

    src = _pl.Path("src/mcp/tools/context_tool.py").read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "capture_output" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value is True:
                    offenders.append(node.lineno)
    assert not offenders, f"capture_output=True в context_tool.py, строки {offenders}"


def test_fetch_commits_uses_one_bulk_git_call(git_repo: Path, monkeypatch):
    """Файлы коммитов берутся batch-вызовом, без diff-tree на каждый коммит."""
    memory = CommitMemory(git_repo, cache_dir=git_repo / ".cache")

    def _forbidden(self, commit_hash):
        raise AssertionError(f"per-commit git call for {commit_hash}")

    monkeypatch.setattr(CommitMemory, "_get_commit_files", _forbidden)

    commits = memory.fetch_commits(limit=10)

    assert commits, "коммиты должны читаться из reflog"
    with_files = [c for c in commits if c["files"]]
    assert with_files, f"batch git log не наполнил файлы: {commits[:1]}"
    all_files = {f for c in commits for f in c["files"]}
    assert {"a.py", "b.py"} <= all_files


def test_bulk_call_is_bounded_in_time(git_repo: Path):
    """Батч-вызов ограничен таймаутом и не оставляет процесс висеть."""
    memory = CommitMemory(git_repo, cache_dir=git_repo / ".cache2")
    memory._load_commit_files_bulk(50)
    assert memory._files_cache, "кэш файлов должен заполниться"
