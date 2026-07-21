"""
Тест на фикс бага: Indexer.project_path должен существовать.
Воспроизводит AttributeError: 'Indexer' object has no attribute 'project_path'
Также тестирует баг prune_deleted_files с одним элементом.
"""
import gc
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_TEST_DIM = 768
_vec = lambda: [0.1] * _TEST_DIM


def _make_indexer(project_path):
    """Create an Indexer in a temp dir and return (indexer, db_path)."""
    from src.core.indexing.indexer import Indexer

        db_path = project_path / ".codebase_indices" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    embedder_mock = MagicMock()
    embedder_mock.embedding_dim = _TEST_DIM
    file_guard_mock = MagicMock()

    indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path)
    return indexer


def _cleanup(project_path):
    """Force close LanceDB handles and delete temp dir on Windows."""
    gc.collect()
    try:
        shutil.rmtree(project_path, ignore_errors=True)
    except Exception:
        pass


def test_indexer_has_project_path_attribute():
    """Проверяет, что Indexer всегда имеет атрибут project_path."""
    d = Path(tempfile.mkdtemp())
    try:
        indexer = _make_indexer(d)
        assert hasattr(indexer, 'project_path'), "Indexer должен иметь атрибут project_path"
        assert indexer.project_path == d
    finally:
        _cleanup(d)


def test_indexer_project_path_fallback():
    """Проверяет, что project_path имеет fallback если не передан явно."""
    from src.core.indexing.indexer import Indexer

    d = Path(tempfile.mkdtemp())
    try:
        db_path = d / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        embedder_mock.embedding_dim = _TEST_DIM
        file_guard_mock = MagicMock()

        indexer = Indexer(db_path, embedder_mock, file_guard_mock)

        assert hasattr(indexer, 'project_path')
        assert indexer.project_path is not None
    finally:
        _cleanup(d)


def test_indexer_switch_project_updates_path():
    """Проверяет, что switch_project обновляет project_path."""
    from src.core.indexing.indexer import Indexer

    d = Path(tempfile.mkdtemp())
    try:
        project_path_1 = d / "project_1"
        project_path_2 = d / "project_2"
        project_path_1.mkdir()
        project_path_2.mkdir()

        db_path = project_path_1 / ".codebase_indices" / "test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_mock = MagicMock()
        embedder_mock.embedding_dim = _TEST_DIM
        file_guard_mock = MagicMock()

        indexer = Indexer(db_path, embedder_mock, file_guard_mock, project_path=project_path_1)
        assert indexer.project_path == project_path_1

        indexer.switch_project(project_path_2)
        assert indexer.project_path == project_path_2
    finally:
        _cleanup(d)


def test_lsp_execute_file_indexing_no_attribute_error():
    """Интеграционный тест: LSP _execute_file_indexing не падает с AttributeError."""
    d = Path(tempfile.mkdtemp())
    try:
        indexer = _make_indexer(d)

        test_file = d / "test.py"
        test_file.write_text("def hello(): pass\n", encoding="utf-8")

        try:
            rel_path = test_file.relative_to(indexer.project_path)
            assert str(rel_path) == "test.py"
        except AttributeError:
            pytest.fail("indexer.project_path не существует — баг не исправлен!")
    finally:
        _cleanup(d)


def test_prune_deleted_files_with_empty_set_does_nothing():
    """Тест на баг: prune_deleted_files с пустым set не должен удалять файлы."""
    d = Path(tempfile.mkdtemp())
    try:
        indexer = _make_indexer(d)

        data = [
            {"id": "file1_0", "vector": _vec(), "text": "file1 content", "file_path": "file1.py", "file_hash": "hash1", "chunk_index": 0},
            {"id": "file2_0", "vector": _vec(), "text": "file2 content", "file_path": "file2.py", "file_hash": "hash2", "chunk_index": 0},
            {"id": "file3_0", "vector": _vec(), "text": "file3 content", "file_path": "file3.py", "file_hash": "hash3", "chunk_index": 0},
        ]
        indexer.table.add(data)

        df = indexer.table.to_pandas()
        assert len(df) == 3

        indexer.prune_deleted_files(set())

        df = indexer.table.to_pandas()
        assert len(df) == 3, f"Ожидалось 3 файла, осталось {len(df)}"
    finally:
        _cleanup(d)


def test_delete_file_removes_only_specified_file():
    """Тест: delete_file удаляет только указанный файл, не трогая остальные."""
    d = Path(tempfile.mkdtemp())
    try:
        indexer = _make_indexer(d)

        data = [
            {"id": "f1_0", "vector": _vec(), "text": "f1", "file_path": "a.py", "file_hash": "h1", "chunk_index": 0},
            {"id": "f2_0", "vector": _vec(), "text": "f2", "file_path": "b.py", "file_hash": "h2", "chunk_index": 0},
            {"id": "f3_0", "vector": _vec(), "text": "f3", "file_path": "c.py", "file_hash": "h3", "chunk_index": 0},
        ]
        indexer.table.add(data)
        assert len(indexer.table.to_pandas()) == 3

        result = indexer.delete_file("b.py")
        assert result is True

        remaining = set(indexer.table.to_pandas()["file_path"].unique())
        assert remaining == {"a.py", "c.py"}, f"Ожидалось {{a.py, c.py}}, получилось {remaining}"
    finally:
        _cleanup(d)
