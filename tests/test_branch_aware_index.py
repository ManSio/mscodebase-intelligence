"""
Тесты для Branch-Aware Index.
"""

import tempfile
from pathlib import Path

from src.core.search.branch_aware_index import BranchAwareIndex


class TestBranchAwareIndex:
    """Тесты BranchAwareIndex."""

    def test_get_current_branch(self):
        """Определение текущей ветки."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            # Без git — fallback на main
            branch = branch_index.get_current_branch()
            assert branch == "main"

    def test_get_current_branch_with_git(self):
        """Определение ветки с git."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Инициализируем git
            import subprocess
            subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)

            # Создаём файл и коммит
            (tmp_path / "test.py").write_text("x = 1")
            subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

            branch_index = BranchAwareIndex(tmp_path)
            branch = branch_index.get_current_branch()

            # Должен быть main или master
            assert branch in ("main", "master")

    def test_get_branch_db_path(self):
        """Путь к БД для ветки."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            db_path = branch_index.get_branch_db_path("feature/test")

            assert "feature_test" in str(db_path)
            assert "branches" in str(db_path)

    def test_get_branch_db_path_creates_dir(self):
        """Создание директории для ветки."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            db_path = branch_index.get_branch_db_path("develop")

            assert db_path.parent.exists()

    def test_switch_branch(self):
        """Переключение ветки."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            # Переключаем на другую ветку (не main)
            result = branch_index.switch_branch("feature/new")
            assert result is True

            # Переключаем на ту же ветку снова
            result = branch_index.switch_branch("feature/new")
            assert result is False

            # Переключаем на main (текущая по умолчанию)
            branch_index2 = BranchAwareIndex(Path(tmp))
            result = branch_index2.switch_branch("main")
            assert result is False  # Уже на main

    def test_get_branch_info_no_index(self):
        """Информация о ветке без индекса."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            info = branch_index.get_branch_info()

            assert "branch" in info
            assert "db_path" in info
            assert info["index_exists"] is False
            assert info["total_chunks"] == 0

    def test_list_branch_indices_empty(self):
        """Пустой список индексов."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            indices = branch_index.list_branch_indices()

            assert indices == {}

    def test_cleanup_old_branches(self):
        """Очистка устаревших веток."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Создаём директории веток
            branches_dir = tmp_path / ".codebase_indices" / "branches"
            branches_dir.mkdir(parents=True)

            (branches_dir / "old_branch").mkdir()
            (branches_dir / "old_branch" / "codebase_chunks.db").touch()

            (branches_dir / "keep_branch").mkdir()
            (branches_dir / "keep_branch" / "codebase_chunks.db").touch()

            branch_index = BranchAwareIndex(tmp_path)
            removed = branch_index.cleanup_old_branches(keep_branches=["keep_branch"])

            assert removed == 1
            assert not (branches_dir / "old_branch").exists()
            assert (branches_dir / "keep_branch").exists()

    def test_branch_name_normalization(self):
        """Нормализация имени ветки."""
        with tempfile.TemporaryDirectory() as tmp:
            branch_index = BranchAwareIndex(Path(tmp))

            # Ветка со слешами
            db_path = branch_index.get_branch_db_path("feature/auth-v2")

            # Слеши должны быть заменены на _
            assert "/" not in db_path.parent.name
            assert "\\" not in db_path.parent.name
            assert "feature_auth-v2" in str(db_path)
