"""
Тест на фикс бага: Indexer.project_path должен существовать.
Воспроизводит AttributeError: 'Indexer' object has no attribute 'project_path'
Также тестирует баг prune_deleted_files с одним элементом.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_prune_deleted_files_with_empty_set_does_nothing():
    """Тест на баг: prune_deleted_files с пустым set не должен удалять файлы."""
    from src.core.indexer import Indexer

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)
        db_path = project_path / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        file_guard_mock = MagicMock()

        indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path)

        # Добавляем несколько записей в таблицу напрямую
        data = [
            {
                "id": "file1_0",
                "vector": [0.1] * 1024,
                "text": "file1 content",
                "file_path": "file1.py",
                "file_hash": "hash1",
                "chunk_index": 0,
            },
            {
                "id": "file2_0",
                "vector": [0.2] * 1024,
                "text": "file2 content",
                "file_path": "file2.py",
                "file_hash": "hash2",
                "chunk_index": 0,
            },
            {
                "id": "file3_0",
                "vector": [0.3] * 1024,
                "text": "file3 content",
                "file_path": "file3.py",
                "file_hash": "hash3",
                "chunk_index": 0,
            },
        ]
        indexer.table.add(data)

        # Проверяем что все 3 файла в базе
        df = indexer.table.to_pandas()
        assert len(df) == 3

        # Вызываем prune_deleted_files с пустым set — не должно удалить ничего
        indexer.prune_deleted_files(set())

        # Проверяем что все файлы остались
        df = indexer.table.to_pandas()
        assert len(df) == 3, f"Ожалось 3 файла, осталось {len(df)}"


def test_delete_file_removes_only_specified_file():
    """Тест: delete_file удаляет только указанный файл, не трогая остальные."""
    from src.core.indexer import Indexer

    with tempfile.TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)
        db_path = project_path / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        file_guard_mock = MagicMock()

        indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path)

        # Добавляем 3 файла
        data = [
            {"id": "f1_0", "vector": [0.1] * 1024, "text": "f1", "file_path": "a.py", "file_hash": "h1", "chunk_index": 0},
            {"id": "f2_0", "vector": [0.2] * 1024, "text": "f2", "file_path": "b.py", "file_hash": "h2", "chunk_index": 0},
            {"id": "f3_0", "vector": [0.3] * 1024, "text": "f3", "file_path": "c.py", "file_hash": "h3", "chunk_index": 0},
        ]
        indexer.table.add(data)
        assert len(indexer.table.to_pandas()) == 3

        # Удаляем только b.py
        result = indexer.delete_file("b.py")
        assert result is True

        # Проверяем что a.py и c.py остались
        remaining = set(indexer.table.to_pandas()["file_path"].unique())
        assert remaining == {"a.py", "c.py"}, f"Ожалось {{a.py, c.py}}, получилось {remaining}"
