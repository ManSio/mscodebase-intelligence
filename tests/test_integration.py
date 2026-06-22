"""
Интеграционные тесты.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_project():
    """Создаёт временный проект."""
    temp_dir = Path(tempfile.mkdtemp())

    # Создаём тестовые файлы
    (temp_dir / "main.py").write_text('''
def main():
    """Главная функция."""
    print("Hello")

if __name__ == "__main__":
    main()
''')

    (temp_dir / "utils.py").write_text('''
def helper():
    """Вспомогательная функция."""
    return 42
''')

    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def isolated_indexer(tmp_path):
    """
    Каждый тест получает абсолютно чистую, изолированную папку в /tmp/pytest-of-user/...
    Конфликты блокировок таблиц и старых данных LanceDB исключены на 100%.
    """
    from src.core.file_guard import FileGuard
    from src.core.indexer import Indexer

    db_dir = tmp_path / "isolated_lancedb"

    # Мокаем эмбеддер, возвращающий вектор правильной размерности
    embedder_mock = MagicMock()
    embedder_mock.embed.return_value = [0.1] * 384
    embedder_mock.embed_batch.return_value = [[0.1] * 384] * 5

    file_guard = FileGuard(tmp_path)
    indexer = Indexer(db_dir, embedder_mock, file_guard)

    yield indexer

    # LanceDB не имеет close() метода - просто удалим временную папку
    import shutil

    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.mark.slow
@pytest.mark.integration
def test_full_indexing_pipeline(temp_project, isolated_indexer):
    """Тест полного цикла индексации."""
    from src.core.searcher import Searcher

    indexer = isolated_indexer
    searcher = Searcher(indexer, indexer.embedder)
    indexer.searcher = searcher

    # Индексируем
    count = indexer.index_project(temp_project)
    assert count >= 2, f"Должно быть проиндексировано минимум 2 файла, получено {count}"

    # Проверяем статус
    status = indexer.get_status()
    assert status.get("total_files", 0) >= 2
    assert status.get("total_chunks", 0) >= 2

    # Ищем
    result = searcher.search("главная функция")
    assert "main" in result.lower() or "функци" in result.lower()

    # Проверяем, что результат содержит что-то полезное
    assert len(result) > 50, "Результат поиска должен быть содержательным"


@pytest.mark.slow
@pytest.mark.integration
def test_incremental_indexing(temp_project, isolated_indexer):
    """Тест инкрементальной индексации."""
    indexer = isolated_indexer

    # Первая индексация
    count1 = indexer.index_project(temp_project)
    assert count1 >= 2

    # Вторая индексация (ничего не изменилось)
    count2 = indexer.index_project(temp_project)
    assert count2 == 0, "Ничего не должно переиндексироваться"

    # Меняем файл
    (temp_project / "main.py").write_text('''
def main():
    """Обновлённая главная функция."""
    print("Updated")
''')

    # Третья индексация (один файл изменился)
    count3 = indexer.index_project(temp_project)
    assert count3 == 1, "Должен переиндексироваться один файл"


@pytest.mark.slow
@pytest.mark.integration
def test_file_deletion(temp_project, isolated_indexer):
    """Тест удаления файла из индекса."""
    indexer = isolated_indexer

    # Индексируем
    indexer.index_project(temp_project)
    status1 = indexer.get_status()

    # Удаляем файл
    (temp_project / "utils.py").unlink()

    # Переиндексируем
    indexer.index_project(temp_project)
    status2 = indexer.get_status()

    assert status2.get("total_files", 0) < status1.get("total_files", 0)
