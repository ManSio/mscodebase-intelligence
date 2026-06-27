"""
Тесты для Searcher.
"""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_index(tmp_path):
    """Каждый тест получает изолированный временный каталог (tmp_path)."""
    yield tmp_path


@pytest.mark.slow
def test_searcher_basic(temp_index):
    """Базовый тест поиска."""
    from src.core.embedder import Embedder
    from src.core.indexer import Indexer
    from src.core.searcher import Searcher

    # Создаём тестовый файл
    test_file = temp_index / "test.py"
    test_file.write_text('''
def calculate_sum(a, b):
    """Вычисляет сумму двух чисел."""
    return a + b

class Calculator:
    def multiply(self, a, b):
        return a * b
''')

    # Инициализируем компоненты
    model_dir = temp_index / "models"
    index_dir = temp_index / "index"

    from unittest.mock import MagicMock

    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 1024
    embedder.embed_batch.return_value = [[0.1] * 1024] * 5

    from src.core.file_guard import FileGuard

    file_guard = FileGuard(temp_index)
    indexer = Indexer(index_dir, embedder, file_guard=file_guard)
    # Используем _index_single_file через внутренний вызов
    # Вместо прямого вызова index_file (который удалён)
    # Используем index_project для одного файла
    # Копируем файл в поддиректорию, чтобы index_project его увидел
    (temp_index / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(test_file, temp_index / "src" / "test.py")

    # Индексируем через index_project (единственный публичный метод)
    count = indexer.index_project(temp_index)
    assert count >= 1

    searcher = Searcher(indexer, embedder)

    # Ищем
    result = searcher.search("функция сложения")

    assert "calculate_sum" in result or "sum" in result.lower()


@pytest.mark.slow
def test_searcher_empty_index(temp_index):
    """Тест поиска в пустом индексе."""
    from src.core.embedder import Embedder
    from src.core.indexer import Indexer
    from src.core.searcher import Searcher

    model_dir = temp_index / "models"
    index_dir = temp_index / "index"

    embedder = Embedder(model_dir=model_dir)
    embedder.load()

    from src.core.file_guard import FileGuard

    file_guard = FileGuard(temp_index)
    indexer = Indexer(index_dir, embedder, file_guard=file_guard)
    searcher = Searcher(indexer, embedder)

    result = searcher.search("что-то")
    assert (
        "ничего не найдено" in result.lower()
        or "empty" in result.lower()
        or "Ничего" in result
    )


@pytest.mark.slow
@pytest.mark.skip(
    reason="Требуется запущенный LM Studio (RemoteEmbedder) для полноценного теста BM25"
)
def test_searcher_reindex(temp_index):
    """Тест сброса кэша BM25."""
    from src.core.embedder import Embedder
    from src.core.indexer import Indexer
    from src.core.searcher import Searcher

    model_dir = temp_index / "models"
    index_dir = temp_index / "index"

    embedder = Embedder(model_dir=model_dir)
    embedder.load()

    from src.core.file_guard import FileGuard

    file_guard = FileGuard(temp_index)
    indexer = Indexer(index_dir, embedder, file_guard=file_guard)
    searcher = Searcher(indexer, embedder)

    # Инициализируем кэш
    searcher._bm25_search("test", 5)
    assert searcher._bm25 is not None

    # Сбрасываем
    searcher.reindex()
    assert searcher._bm25 is None
