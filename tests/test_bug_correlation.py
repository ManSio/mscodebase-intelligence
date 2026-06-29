"""
Тесты для Bug Correlation.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.core.commit_memory import CommitMemory
from src.core.bug_correlation import BugCorrelation


class TestBugCorrelation:
    """Тесты BugCorrelation."""

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

    def test_no_bugfix_commits(self):
        """Нет баг-фиксов — пустой результат."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_commit(tmp_path, "x = 1", "Initial commit")
            self._create_commit(tmp_path, "x = 2", "Add feature")

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            stats = bug_corr.analyze()

            assert stats["bugfix_commits"] == 0
            assert stats["bugfix_ratio"] == 0.0

    def test_detects_bugfix_commits(self):
        """Определяет баг-фиксы по ключевым словам."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_commit(tmp_path, "x = 1", "Initial commit")
            self._create_commit(tmp_path, "x = 2", "Fix null pointer")
            self._create_commit(tmp_path, "x = 3", "Add feature")
            self._create_commit(tmp_path, "x = 4", "Bug fix: resolve crash")

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            stats = bug_corr.analyze()

            assert stats["bugfix_commits"] == 2
            assert stats["bugfix_ratio"] == 0.5

    def test_top_buggy_files(self):
        """Находит файлы с наибольшим количеством баг-фиксов."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            # Создаём файлы
            (tmp_path / "stable.py").write_text("x = 1")
            (tmp_path / "buggy.py").write_text("y = 1")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True)

            # Фиксим buggy.py несколько раз
            for i in range(3):
                (tmp_path / "buggy.py").write_text(f"y = {i+2}")
                subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"Fix bug in buggy.py #{i+1}"], cwd=tmp_path, capture_output=True)

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            top = bug_corr.get_top_buggy_files(5)

            assert len(top) > 0
            assert top[0]["file"] == "buggy.py"
            assert top[0]["bug_count"] == 3

    def test_bug_history_for_file(self):
        """Баго-история конкретного файла."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "test.py").write_text("x = 1")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True)

            (tmp_path / "test.py").write_text("x = 2")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Fix: resolve error"], cwd=tmp_path, capture_output=True)

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            history = bug_corr.get_bug_history_for_file("test.py")

            assert history["file"] == "test.py"
            assert history["bug_count"] == 1
            assert history["total_commits"] == 2
            assert history["bug_risk"] in ("low", "medium", "high", "critical")

    def test_hotspots(self):
        """Находит горячие точки."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "hot.py").write_text("x = 1")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True)

            for i in range(5):
                (tmp_path / "hot.py").write_text(f"x = {i+2}")
                subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"Hotfix: critical bug #{i+1}"], cwd=tmp_path, capture_output=True)

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            hotspots = bug_corr.get_hotspots(5)

            assert len(hotspots) > 0
            assert hotspots[0]["file"] == "hot.py"
            assert hotspots[0]["bug_count"] == 5

    def test_bug_risk_levels(self):
        """Определение уровня риска."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            (tmp_path / "test.py").write_text("x = 1")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, capture_output=True)

            # Все коммиты — баг-фиксы (100% ratio)
            for i in range(5):
                (tmp_path / "test.py").write_text(f"x = {i+2}")
                subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"Fix bug #{i+1}"], cwd=tmp_path, capture_output=True)

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            history = bug_corr.get_bug_history_for_file("test.py")

            assert history["bug_risk"] == "critical"

    def test_stats(self):
        """Статистика баго-корреляции."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._init_git(tmp_path)

            self._create_commit(tmp_path, "x = 1", "Initial")
            self._create_commit(tmp_path, "x = 2", "Fix bug")

            memory = CommitMemory(tmp_path)
            bug_corr = BugCorrelation(memory)
            stats = bug_corr.get_stats()

            assert stats["total_commits"] == 2
            assert stats["bugfix_commits"] == 1
            assert "unique_buggy_files" in stats
