"""
Тесты для Index Guard — самовосстановление индекса.
"""

import tempfile
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")
import pyarrow as pa

from src.core.index_guard import IndexGuard, quick_health_check


class TestIndexGuard:
    """Тесты IndexGuard."""
    # Размерность вектора E5-base. При смене модели — обновить.
    DIM = 768

    def _create_full_schema(self) -> pa.schema:
        """Создаёт полную актуальную схему таблицы."""
        return pa.schema([
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), self.DIM)),
                pa.field("text", pa.string()),
                pa.field("text_full", pa.string()),
                pa.field("file_path", pa.string()),
                pa.field("file_hash", pa.string()),
                pa.field("chunk_index", pa.int32()),
                pa.field("source", pa.string()),
                pa.field("indexed_at", pa.string()),
                pa.field("summary", pa.string()),
            ]
        )

    def _create_db_with_table(self, db_path: Path, schema: pa.Schema = None):
        """Создаёт тестовую БД с таблицей."""
        db = lancedb.connect(str(db_path))

        if schema is None:
            schema = self._create_full_schema()

        db.create_table("codebase_chunks", schema=schema)
        return db

    def test_healthy_index(self, tmp_path):
        """Здоровый индекс — проверка проходит."""
        db_path = tmp_path / "test.db"
        db = self._create_db_with_table(db_path, schema=self._create_full_schema())

        # Добавляем тестовую запись
        table = db.open_table("codebase_chunks")
        table.add(
            [
                {
                    "id": "test1",
                    "vector": [0.0] * self.DIM,
                    "text": "test content",
                    "text_full": "test content",
                    "file_path": "test.py",
                    "file_hash": "abc123",
                    "chunk_index": 0,
                    "source": "filesystem",
                    "indexed_at": "2024-01-01",
                    "summary": "",
                }
            ]
        )

        health = quick_health_check(db_path)
        assert health["healthy"] is True
        assert health["table_exists"] is True
        assert health["row_count"] == 1

    def test_missing_table(self, tmp_path):
        """Отсутствующая таблица — нужен reindex."""
        db_path = tmp_path / "test.db"
        db = lancedb.connect(str(db_path))

        health = quick_health_check(db_path)
        assert health["healthy"] is False
        assert health["table_exists"] is False

    def test_empty_table(self, tmp_path):
        """Пустая таблица — нужен reindex."""
        db_path = tmp_path / "test.db"
        self._create_db_with_table(db_path)

        health = quick_health_check(db_path)
        assert health["healthy"] is False
        assert health["row_count"] == 0

    def test_schema_migration_needed(self, tmp_path):
        """Старая схема без обязательных полей — нужна миграция."""
        db_path = tmp_path / "test.db"

        # Создаём таблицу без обязательных полей
        db = lancedb.connect(str(db_path))
        old_schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("text", pa.string()),
            ]
        )
        db.create_table("codebase_chunks", schema=old_schema)

        health = quick_health_check(db_path)
        assert health["schema_ok"] is False

    def test_guard_repair_healthy(self, tmp_path):
        """Guard не третает здоровую таблицу."""
        db_path = tmp_path / "test.db"
        db = self._create_db_with_table(db_path, schema=self._create_full_schema())

        # Добавляем запись
        table = db.open_table("codebase_chunks")
        table.add(
            [
                {
                    "id": "test1",
                    "vector": [0.0] * self.DIM,
                    "text": "test",
                    "text_full": "test",
                    "file_path": "test.py",
                    "file_hash": "abc",
                    "chunk_index": 0,
                    "source": "filesystem",
                    "indexed_at": "2024-01-01",
                    "summary": "",
                }
            ]
        )

        guard = IndexGuard(db_path, tmp_path)
        report = guard.check_and_repair(db)

        assert report["status"] == "ok"

    def test_guard_detects_missing_table(self, tmp_path):
        """Guard обнаруживает отсутствующую таблицу."""
        db_path = tmp_path / "test.db"
        db = lancedb.connect(str(db_path))

        guard = IndexGuard(db_path, tmp_path)
        report = guard.check_and_repair(db)

        assert report["status"] == "needs_reindex"

    def test_symbol_index_persistence(self, tmp_path):
        """Сохранение и загрузка SymbolIndex."""
        db_path = tmp_path / "test.db"
        db_path.mkdir(parents=True, exist_ok=True)

        guard = IndexGuard(db_path, tmp_path)

        # Создаём моковый SymbolIndex
        class MockSymbolIndex:
            def __init__(self):
                self._definitions = {"func1": [], "func2": []}
                self._references = {"func1": []}
                self._file_to_symbols = {"test.py": {"func1", "func2"}}

        mock = MockSymbolIndex()

        # Сохраняем
        assert guard.save_symbol_index(mock) is True

        # Загружаем в новый
        mock2 = MockSymbolIndex()
        mock2._definitions = {}
        mock2._references = {}
        mock2._file_to_symbols = {}

        assert guard.load_symbol_index(mock2) is True
        assert len(mock2._definitions) == 2
        assert "func1" in mock2._definitions

    def test_symbol_index_no_cache(self, tmp_path):
        """Загрузка при отсутствии кэша."""
        db_path = tmp_path / "test.db"
        db_path.mkdir(parents=True, exist_ok=True)

        guard = IndexGuard(db_path, tmp_path)

        class MockSymbolIndex:
            def __init__(self):
                self._definitions = {}
                self._references = {}
                self._file_to_symbols = {}

        mock = MockSymbolIndex()
        assert guard.load_symbol_index(mock) is False

    def test_should_reindex_when_corrupted(self, tmp_path):
        """Определение необходимости reindex."""
        db_path = tmp_path / "test.db"
        db_path.mkdir(parents=True, exist_ok=True)

        guard = IndexGuard(db_path, tmp_path)

        # Симулируем повреждённый guard state
        guard._save_guard_state(
            {
                "status": "error",
                "errors": ["test error"],
                "actions_taken": [],
            }
        )

        assert guard.should_reindex() is True

    def test_should_not_reindex_when_healthy(self, tmp_path):
        """Не нужен reindex если здоров."""
        db_path = tmp_path / "test.db"
        db_path.mkdir(parents=True, exist_ok=True)

        guard = IndexGuard(db_path, tmp_path)
        guard._save_guard_state(
            {
                "status": "ok",
                "actions_taken": [],
                "errors": [],
            }
        )

        assert guard.should_reindex() is False
