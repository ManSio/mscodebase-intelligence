"""
Тесты для Semantic Commit Memory.
"""

import subprocess
import tempfile
from pathlib import Path

from src.core.commit_memory import CommitMemory


class TestCommitMemory:
    """Тесты CommitMemory."""

    def _init_git(self, path: Path):
        """Инициализирует git репозиторий."""
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)

    def _create_commit(self, path: Path, content: str, message: str):
        """Создаёт коммит для файла test.py."""
        (path / "test.py").write_text(content)
        subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=path, capture_output=True)

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
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add both files"], cwd=tmp_path, capture_output=True)

            (tmp_path / "a.py").write_text("a = 2")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Update a.py"], cwd=tmp_path, capture_output=True)

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
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "feat: add authentication"], cwd=tmp_path, capture_output=True)

            (tmp_path / "test.py").write_text("x = 2")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "fix: resolve bug"], cwd=tmp_path, capture_output=True)

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
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add stable"], cwd=tmp_path, capture_output=True)

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
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add both"], cwd=tmp_path, capture_output=True)

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
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True)

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
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True)

            # Первый инстанс
            memory1 = CommitMemory(tmp_path)
            memory1.fetch_commits()

            # Второй инстанс должен загрузить из кэша
            memory2 = CommitMemory(tmp_path)
            assert len(memory2._commits) == 1
