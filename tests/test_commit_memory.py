"""
Тесты для Semantic Commit Memory.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from src.core.commit_memory import CommitMemory

# Git-hook окружение (git commit экспортирует GIT_DIR/GIT_INDEX_FILE/... в hooks)
# ломает вложенные git-команды в temp-репо: они оперируют НЕ тем репозиторием.
# Санируем: убираем все GIT_* из env для git-субпроцессов (см. REFC-03).
_CLEAN_GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(args, cwd):
    """Запускает git с чистым env (без унаследованных GIT_*)."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=_CLEAN_GIT_ENV)


class TestCommitMemory:
    """Тесты CommitMemory."""

    def _init_git(self, path: Path):
        """Инициализирует git репозиторий."""
        _git(["init"], path)
        _git(["config", "user.email", "test@test.com"], path)
        _git(["config", "user.name", "Test"], path)

    def _create_commit(self, path: Path, content: str, message: str):
        """Создаёт коммит для файла test.py."""
        (path / "test.py").write_text(content)
        _git(["add", "."], path)
        _git(["commit", "-m", message], path)

    def test_no_git_repo(self):
        """Без git — пустой результат."""
        with tempfile.TemporaryDirectory() as tmp:
            memory = CommitMemory(Path(tmp))
            commits = memory.fetch_commits()
            assert commits == []

    def test_fetch_commits(self):
        """Получение коммитов."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_commit(tmp_path, "x = 1", "Initial commit")
            self._create_commit(tmp_path, "x = 2", "Update value")

            memory = CommitMemory(tmp_path)
            commits = memory.fetch_commits()

            assert len(commits) == 2
            assert commits[0]["message"] == "Initial commit"
            assert commits[1]["message"] == "Update value"

    def test_get_commits_for_file(self):
        """Коммиты для конкретного файла."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "a.py").write_text("a = 1")
            (tmp_path / "b.py").write_text("b = 1")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "Add both files"], tmp_path)

            (tmp_path / "a.py").write_text("a = 2")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "Update a.py"], tmp_path)

            memory = CommitMemory(tmp_path)
            memory.fetch_commits()

            a_commits = memory.get_commits_for_file("a.py")
            assert len(a_commits) == 2  # Оба коммита изменили a.py

            b_commits = memory.get_commits_for_file("b.py")
            assert len(b_commits) == 1  # Только первый коммит

    def test_search_commits(self):
        """Поиск коммитов по сообщению."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "test.py").write_text("x = 1")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "feat: add authentication"], tmp_path)

            (tmp_path / "test.py").write_text("x = 2")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "fix: resolve bug"], tmp_path)

            memory = CommitMemory(tmp_path)
            memory.fetch_commits()

            feat_commits = memory.search_commits("feat")
            assert len(feat_commits) == 1
            assert "authentication" in feat_commits[0]["message"]

    def test_get_file_stability(self):
        """Анализ стабильности файла."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "stable.py").write_text("x = 1")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "Add stable"], tmp_path)

            memory = CommitMemory(tmp_path)
            memory.fetch_commits()

            stability = memory.get_file_stability("stable.py")
            assert stability["change_count"] == 1
            assert stability["stability"] == "stable"

    def test_get_cochange_frequency(self):
        """Анализа совместных изменений файлов."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "a.py").write_text("a = 1")
            (tmp_path / "b.py").write_text("b = 1")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "Add both"], tmp_path)

            memory = CommitMemory(tmp_path)
            memory.fetch_commits()

            cochange = memory.get_cochange_frequency()
            assert len(cochange) > 0

    def test_get_stats(self):
        """Статистика коммитов."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "test.py").write_text("x = 1")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "Initial"], tmp_path)

            memory = CommitMemory(tmp_path)
            stats = memory.get_stats()

            assert stats["total"] == 1
            assert "Test" in stats["authors"]

    def test_cache_persistence(self):
        """Персистентность кэша."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "test.py").write_text("x = 1")
            _git(["add", "."], tmp_path)
            _git(["commit", "-m", "Initial"], tmp_path)

            # Первый инстанс
            memory1 = CommitMemory(tmp_path)
            memory1.fetch_commits()

            # Второй инстанс должен загрузить из кэша
            memory2 = CommitMemory(tmp_path)
            assert len(memory2._commits) == 1
