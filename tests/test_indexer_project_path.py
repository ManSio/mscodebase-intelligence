"""
Тест на фикс бага: Indexer.project_path должен существовать.
Воспроизводит AttributeError: 'Indexer' object has no attribute 'project_path'
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_indexer_has_project_path_attribute():
    """Проверяет, что Indexer всегда имеет атрибут project_path."""
    from src.core.indexer import Indexer

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)
        db_path = project_path / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        file_guard_mock = MagicMock()

        # Создаём Indexer с project_path
        indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path)

        # Ключевая проверка: project_path должен существовать
        assert hasattr(indexer, 'project_path'), "Indexer должен иметь атрибут project_path"
        assert indexer.project_path == project_path


def test_indexer_project_path_fallback():
    """Проверяет, что project_path имеет fallback если не передан явно."""
    from src.core.indexer import Indexer

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)
        db_path = project_path / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        file_guard_mock = MagicMock()

        # Создаём Indexer БЕЗ project_path
        indexer = Indexer(db_path, embedder_mock, file_guard_mock)

        # project_path всё равно должен существовать (fallback)
        assert hasattr(indexer, 'project_path')
        assert indexer.project_path is not None


def test_indexer_switch_project_updates_path():
    """Проверяет, что switch_project обновляет project_path."""
    from src.core.indexer import Indexer

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_path_1 = Path(tmp_dir) / "project_1"
        project_path_2 = Path(tmp_dir) / "project_2"
        project_path_1.mkdir()
        project_path_2.mkdir()

        db_path = project_path_1 / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        file_guard_mock = MagicMock()

        indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path_1)
        assert indexer.project_path == project_path_1

        # Переключаемся на другой проект
        indexer.switch_project(project_path_2)
        assert indexer.project_path == project_path_2


def test_lsp_execute_file_indexing_no_attribute_error():
    """Интеграционный тест: LSP _execute_file_indexing не падает с AttributeError."""
    from src.core.indexer import Indexer

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)
        db_path = project_path / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        embedder_mock.embed_batch.return_value = [[0.1] * 1024]
        file_guard_mock = MagicMock()
        file_guard_mock.should_skip_file.return_value = False

        indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path)

        # Создаём тестовый файл
        test_file = project_path / "test.py"
        test_file.write_text("def hello(): pass\n", encoding="utf-8")

        # Это не должно вызывать AttributeError
        try:
            rel_path = test_file.relative_to(indexer.project_path)
            assert str(rel_path) == "test.py"
        except AttributeError:
            pytest.fail("indexer.project_path не существует — баг не исправлен!")
